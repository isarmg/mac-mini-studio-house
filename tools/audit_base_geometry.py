"""Measure final conical faces, planar plates and exterior mouth clearances."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from enclosure import ROOT
import cadquery as cq
import numpy as np
from scipy.optimize import minimize_scalar
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from tools.rebuild_bottom_revision import digest

def audit(model,t):
    folder=ROOT/'results/masters'/model/f'enclosure-{t}mm'
    shape=cq.Shape.importBrep(str(folder/'base.brep'))
    cones=[];risers=[];planes=[]
    for face in shape.Faces():
        surface=BRepAdaptor_Surface(face.wrapped);box=face.BoundingBox()
        if face.geomType()=='CONE':
            cone=surface.Cone();slope=np.tan(cone.SemiAngle())
            intercept=cone.RefRadius()-slope*cone.Location().Z()
            cones.append((intercept,slope,face))
        elif face.geomType()=='CYLINDER':
            cyl=surface.Cylinder()
            if cyl.Radius()>20 and abs(cyl.Axis().Direction().Z())>.99999:
                risers.append(cyl.Radius())
        elif face.geomType()=='PLANE' and box.zlen<1e-5:
            planes.append({'z':face.Center().z,'wires':len(face.Wires())})
    assert len(cones)>=2, len(cones)
    inner=min(cones,key=lambda row:row[0])
    outer=min([row for row in cones if row[0]>inner[0]+1],key=lambda row:row[2].BoundingBox().zmin)
    factor=np.hypot(1,outer[1]);normal=(outer[0]-inner[0])/factor
    measured_angle=float(np.degrees(np.arctan2(1,outer[1])))
    requirement=json.loads((ROOT/'data/enclosure_design.json').read_text(encoding='utf-8'))[model]
    angle_error=abs(measured_angle-requirement['cone_angle_to_horizontal_degrees'])
    lower=shape.BoundingBox().zmin+1e-7
    upper=6.5 if model=='mac-mini' else max(p['z'] for p in planes)-1.5
    edge_ranges=[]
    for edge in outer[2].Edges():
        curve=BRepAdaptor_Curve(edge.wrapped)
        us=np.linspace(curve.FirstParameter(),curve.LastParameter(),41)
        zs=np.array([curve.Value(float(u)).Z() for u in us])
        if zs.min()<lower+.1 or zs.max()>upper-.1:continue
        extremes=[]
        for sign in (1,-1):
            i=int(np.argmin(sign*zs));left=us[max(0,i-1)];right=us[min(len(us)-1,i+1)]
            solution=minimize_scalar(lambda u:sign*curve.Value(float(u)).Z(),bounds=(left,right),method='bounded',options={'xatol':1e-13})
            extremes.append(min(sign*zs.min(),sign*zs.max(),solution.fun)*sign)
        edge_ranges.append(extremes)
    assert edge_ranges
    clearances=[(min(x[0] for x in edge_ranges)-lower)*factor,
                (upper-max(x[1] for x in edge_ranges))*factor]
    levels=sorted({round(p['z'],6) for p in planes})
    floor_thickness=levels[1]-levels[0]
    top_thickness=min(p['z'] for p in planes if p['z']>upper+1e-5)-upper
    inside=inner[2].BoundingBox()
    direct=abs(inside.zmin-1.5)<2e-5 and abs(inside.zmax-levels[-1])<2e-5
    planar_clean=all(p['wires']<=(3 if model=='mac-mini' and p['z']>2 else 2 if p['z']>2 else 1) for p in planes)
    result={'model':model,'housing_thickness_mm':t,'base_brep_sha256':digest(folder/'base.brep'),
        'housing_brep_sha256':digest(folder/'housing.brep'),
        'measured_conical_normal_thickness_mm':normal,'measured_lower_plate_mm':floor_thickness,
        'measured_cone_angle_to_horizontal_degrees':measured_angle,'cone_angle_error_degrees':angle_error,
        'design_requirements_sha256':digest(ROOT/'data/enclosure_design.json'),
        'measured_upper_plate_mm':top_thickness,'measured_vent_clearances_along_cone_mm':clearances,
        'outer_cone_junction_z_mm':[lower,upper],'examined_outer_mouth_edges':len(edge_ranges),
        'vertical_risers':risers,'inner_cone_directly_intersects_both_planes':direct,
        'planar_faces':planes,'no_planar_vent_openings':planar_clean,
        'measured_base_height_mm':shape.BoundingBox().zlen}
    result['passed']=(shape.isValid() and len(shape.Solids())==1 and not risers and direct and planar_clean
        and all(abs(v-1.5)<2e-5 for v in (normal,floor_thickness,top_thickness))
        and max(abs(v-.75) for v in clearances)<1e-4 and angle_error<1e-9)
    result['passed']=bool(result['passed'])
    if model=='mac-mini':
        housing=cq.Shape.importBrep(str(folder/'housing.brep'));hb=housing.BoundingBox();bb=shape.BoundingBox()
        dimensions=[hb.zlen,bb.zlen,hb.zmax-min(hb.zmin,bb.zmin),bb.zmax-hb.zmin]
        result['housing_base_assembly_insertion_mm']=dimensions
        result['passed']=result['passed'] and max(abs(a-b) for a,b in zip(dimensions,[43,8,49.5,1.5]))<2e-5
    else:
        housing=cq.Shape.importBrep(str(folder/'housing.brep'));hb=housing.BoundingBox();bb=shape.BoundingBox()
        dimensions=[hb.zlen,bb.zlen,hb.zmax-min(hb.zmin,bb.zmin),bb.zmax-hb.zmin]
        result['housing_base_assembly_insertion_mm']=dimensions
        result['passed']=result['passed'] and max(abs(a-b) for a,b in zip(dimensions,[86.5,10,95,1.5]))<2e-5
    (folder/'base_geometry_audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
    if not result['passed']:raise ValueError('Final base geometry audit failed')
if __name__=='__main__':audit(sys.argv[1],int(sys.argv[2]))
