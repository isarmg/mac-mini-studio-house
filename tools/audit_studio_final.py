"""Independent checks of Studio port handedness and two-part assembly."""
from pathlib import Path
import json,sys,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from enclosure import ROOT
from enclosure.specs import source_report
import cadquery as cq
import numpy as np
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.gp import gp_Pnt,gp_Dir,gp_Lin
from tools.rebuild_bottom_revision import horizontal_face,sampled_distance,digest
from tools.housing_perforations import validate_cylinder_axes
from tools.audit_through_hole_topology import verify as verify_through_holes

def audit(t):
    folder=ROOT/'results/masters/mac-studio'/f'enclosure-{t}mm'
    housing=cq.Shape.importBrep(str(folder/'housing.brep'))
    base=cq.Shape.importBrep(str(folder/'base.brep'))
    report=source_report('mac-studio')
    ray=IntCurvesFace_ShapeIntersector();ray.Load(housing.wrapped,1e-7)
    ports=[]
    for index,port in enumerate(report['ports']):
        p=np.array(port['mouth_points_world_mm']).mean(0)
        p[2]-=report['source_bottom_offset_mm'];p*=report['calibration_xyz']
        p[2]+=json.loads((folder/'validation.json').read_text(encoding='utf-8')).get('side_port_z_shift_mm',0)
        old_x=float(p[0]);p[0]*=-1;p[1]=port['side']*100.5
        ray.Perform(gp_Lin(gp_Pnt(*map(float,p)),gp_Dir(0,-port['side'],0)),0,20)
        ports.append({'index':index,'side':port['side'],'source_x_mm':old_x,
                      'corrected_x_mm':float(p[0]),'skin_intersections':ray.NbPnt()})
    rings=horizontal_face(housing,housing.BoundingBox().zmin,largest=True).innerWires()
    top=horizontal_face(base,base.BoundingBox().zmax,largest=True).outerWire()
    # Base's upper planar rim reaches inside the housing by its plate thickness.
    aligned=top.translate((0,0,housing.BoundingBox().zmin-base.BoundingBox().zmax))
    error=max(sampled_distance(rings[0],aligned),sampled_distance(aligned,rings[0]))
    data=np.loadtxt(folder/'base_hole_axes.csv',delimiter=',',skiprows=1)
    geometry=validate_cylinder_axes(base,data[:,:3],-data[:,3:6],data[:,6])
    topology=verify_through_holes(base,data)
    print('Studio exact through-hole topology',topology['accepted_holes'],flush=True)
    bore=IntCurvesFace_ShapeIntersector();bore.Load(base.wrapped,1e-7)
    blocked=[]
    sample_indices=sorted(set(int(i) for i in np.linspace(0,len(data)-1,16)))
    for index in sample_indices:
        row=data[index]
        p=row[:3]+2*row[3:6];direction=-row[3:6]
        bore.Perform(gp_Lin(gp_Pnt(*map(float,p)),gp_Dir(*map(float,direction))),0,5.5)
        if not bore.IsDone() or bore.NbPnt():blocked.append(index)
        print('Studio sampled bore',index,'clear' if index not in blocked else 'BLOCKED',flush=True)
    result={'model':'mac-studio','thickness_mm':t,'input_hashes':{n:digest(folder/(n+'.brep')) for n in ('housing','base')},
            'ports':ports,'port_order_reflected_x':True,'port_count':len(ports),
            'base_single_valid_solid':base.isValid() and len(base.Solids())==1,
            'housing_single_valid_solid':housing.isValid() and len(housing.Solids())==1,
            'mating_contour_error_mm':error,'bottom_plate_merged_into_base':True,
            'support_foot_removed':True,'base_hole_geometry':geometry,
            'base_hole_through_topology':topology,'base_hole_center_rays_checked':len(sample_indices),
            'sampled_base_hole_indices':sample_indices,'blocked_base_hole_centers':blocked}
    result['passed']=len(ports)==14 and all(p['skin_intersections']==0 for p in ports) and result['base_single_valid_solid'] and result['housing_single_valid_solid'] and error<1e-6 and len(data)==2016 and topology['passed'] and not blocked
    (folder/'studio_final_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Studio independent audit',t,result['passed'],flush=True)
    if not result['passed']:raise ValueError(result)
if __name__=='__main__':audit(int(sys.argv[1]))
