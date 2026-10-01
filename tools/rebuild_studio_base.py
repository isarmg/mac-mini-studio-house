"""Rebuild both Studio bases, preserving the accepted housings in assemblies."""
import argparse,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
from enclosure import ROOT
import cadquery as cq
import numpy as np
from enclosure.current_design import parameters,fuse
from enclosure.wall_offset import planar_inner_wire
from enclosure.mini_openings import _cut_batch
from enclosure.studio_base_pattern import circular_pattern,inspect_pattern,write_pattern,ring_layout
from tools.housing_perforations import validate_cylinder_axes
from tools.rebuild_bottom_revision import horizontal_face,sampled_distance,digest,STAGE


def build_common_core(design,data,cache):
    definition=design['base_design'];slope=definition['cone_slope_dr_dz']
    intercept=definition['outer_cone_radius_intercept_mm'];top=definition['height_mm']
    plate=definition['plate_thickness_mm'];wall=definition['cone_normal_thickness_mm']
    inner=intercept-wall*math.hypot(1,slope)
    core_radius=intercept+slope*top+.5
    outer=cq.Solid.makeCone(intercept,intercept+slope*top,top)
    cap=cq.Solid.makeCylinder(core_radius,plate,cq.Vector(0,0,definition['interface_z_mm']))
    cavity=cq.Solid.makeCone(inner+slope*plate,inner+slope*(top+1),top+1-plate,cq.Vector(0,0,plate))
    shape=fuse(outer,cap).cut(cavity,tol=1e-6).clean()
    source=cache/'uncut.brep';shape.exportBrep(str(source))
    signature=hashlib.sha256((digest(source)+data.tobytes().hex()+digest(Path(__file__))+digest(ROOT/'enclosure/mini_openings.py')).encode()).hexdigest()
    checkpoint=cache/'checkpoint.brep';record=cache/'checkpoint.json';start=0
    if checkpoint.exists() and record.exists():
        saved=json.loads(record.read_text(encoding='utf-8'))
        if saved['signature']==signature and digest(checkpoint)==saved['sha256']:
            shape=cq.Shape.importBrep(str(checkpoint));start=saved['completed_holes']
            if not shape.isValid() or len(shape.Solids())!=1:raise ValueError('Invalid core checkpoint')
            print('Verified Studio core checkpoint:',start,flush=True)
    batch_size=ring_layout(definition)[1]
    for index in range(start,len(data),batch_size):
        end=min(index+batch_size,len(data))
        cutters=[cq.Solid.makeCylinder(float(row[6]),5.5,cq.Vector(*(row[:3]+2*row[3:6])),cq.Vector(*(-row[3:6]))) for row in data[index:end]]
        shape=_cut_batch(shape,cutters,1e-6)
        if not shape.isValid() or len(shape.Solids())!=1:raise ValueError('Invalid Studio perforated core')
        shape.exportBrep(str(checkpoint))
        record.write_text(json.dumps({'signature':signature,'completed_holes':end,'sha256':digest(checkpoint)}),encoding='utf-8')
        print('Studio horizontal core holes',end,'/',len(data),flush=True)
    return shape,core_radius


def stage(*,rebuild_housings=False):
    folders={t:ROOT/'results/masters/mac-studio'/f'enclosure-{t}mm' for t in (2,3)}
    designs={t:parameters(folder,for_rebuild=True) for t,folder in folders.items()}
    if not rebuild_housings:
        for t,folder in folders.items():
            if parameters(folder).get('rear_grid_design')!=designs[t]['rear_grid_design']:
                raise ValueError('The rear pattern changed; use --rebuild-housing')
    tables={t:circular_pattern(designs[t]['base_design']) for t in folders}
    if not np.array_equal(tables[2],tables[3]) or designs[2]['base_design']!=designs[3]['base_design']:
        raise ValueError('Both housing thicknesses must share one base cone and bore pattern')
    cache=ROOT/'.tmp/studio-base-core';cache.mkdir(parents=True,exist_ok=True)
    core,core_radius=build_common_core(designs[2],tables[2],cache)
    join_radius=core_radius-.25
    definition=designs[2]['base_design']
    if join_radius<=definition['outer_cone_radius_intercept_mm']+definition['cone_slope_dr_dz']*definition['height_mm']:
        raise ValueError('Rim joint would enter the perforated cone')
    source_map={}
    for thickness,folder in folders.items():
        design=designs[thickness];data=tables[thickness];out=STAGE/'mac-studio'/f'{thickness}mm';out.mkdir(parents=True,exist_ok=True)
        wire,offset=planar_inner_wire(np.asarray(design['main_G3_quarter_controls_mm']),definition['interface_z_mm'],thickness)
        if wire.distance(cq.Vertex.makeVertex(0,0,definition['interface_z_mm']))<=core_radius:
            raise ValueError('Core extends beyond the intended mating rim')
        plate=cq.Solid.extrudeLinear(wire,[],(0,0,definition['plate_thickness_mm']))
        ring=plate.cut(cq.Solid.makeCylinder(join_radius,definition['plate_thickness_mm'],cq.Vector(0,0,definition['interface_z_mm'])),tol=1e-6)
        base=fuse(core,ring).clean()
        if not base.isValid() or len(base.Solids())!=1:raise ValueError('Base rim union failed')
        rear=None
        if rebuild_housings:
            from tools.final_studio_revision import build_housing
            housing,rear,offset=build_housing(design,out,thickness)
        else:housing=cq.Shape.importBrep(str(folder/'housing.brep'))
        inner=horizontal_face(housing,definition['interface_z_mm'],largest=True).innerWires()[0]
        outer=horizontal_face(base,definition['interface_z_mm'],largest=True).outerWire()
        error=max(sampled_distance(inner,outer),sampled_distance(outer,inner))
        if error>1e-6:raise ValueError('Base and housing contours differ')
        geometry=validate_cylinder_axes(base,data[:,:3],-data[:,3:6],data[:,6])
        pattern=inspect_pattern(data,definition)
        checks=json.loads((folder/'validation.json').read_text(encoding='utf-8'))['bottom_revision']
        checks.update(plate_to_housing_contour_max_error_mm=error,inner_profile_offset=offset)
        checks['conical_surface']=design['features']['base_wall']['conical_surface']
        if rear is not None:
            checks['rear_perforations']=rear;design['features']['rear_perforations']=rear
        holes={'hole_count':len(data),'radius_mm':float(data[0,6]),'designed_wall_thickness_mm':1.5,
               'through_designed_wall':True,'vent_edge_clearance_along_cone_mm':.75,'geometry':geometry,'horizontal_rings':pattern}
        checks['base_perforations']=holes;design['features']['base_perforations']=holes
        design['base_design']['horizontal_bore_rings']=True
        write_pattern(out/'base_hole_axes.csv',data)
        assembly=cq.Compound.makeCompound([housing,base]);outputs=[]
        parts=([('housing',housing)] if rebuild_housings else [])+[('base',base),(f'mac-studio_housing_{thickness}mm',assembly)]
        for name,shape in parts:
            path=out/(name+'.brep');shape.exportBrep(str(path));outputs.append(path)
            source_map[(folder/path.name).relative_to(ROOT).as_posix()]=path.relative_to(ROOT).as_posix()
        b=assembly.BoundingBox()
        if len(assembly.Solids())!=2 or max(abs(a-b) for a,b in zip([b.xlen,b.ylen,b.zlen],[197,197,95]))>1e-5:
            raise ValueError('Studio assembly dimensions changed')
        evidence={'model':'mac-studio','thickness_mm':thickness,'passed':True,'parts':['housing','base'],
                  'checks':checks,'design_parameters':design,'assembly_solid_count':2,'assembly_dimensions_mm':[b.xlen,b.ylen,b.zlen],
                  'changed_file_sha256':{p.name:digest(p) for p in outputs},
                  'construction':'Current analytic cone, planar plates, horizontal circular bore rings and wrapped planar rear grid'}
        if not rebuild_housings:evidence['preserved_housing']={'file':(folder/'housing.brep').relative_to(ROOT).as_posix(),'sha256':digest(folder/'housing.brep')}
        (out/'stage_validation.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
        print('STAGED horizontal-ring Studio base and assembly:',thickness,'mm',flush=True)
    path=cache/'source-map.json';path.write_text(json.dumps(source_map,indent=2),encoding='utf-8');return path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stage-only',action='store_true');parser.add_argument('--rebuild-housing',action='store_true');args=parser.parse_args()
    from OCP.OSD import OSD_ThreadPool
    OSD_ThreadPool.DefaultPool_s().Init(4)
    mapping=stage(rebuild_housings=args.rebuild_housing)
    if not args.stage_only:
        from tools.exact_candidates import deliver
        deliver(json.loads(mapping.read_text(encoding='utf-8')))


if __name__=='__main__':main()
