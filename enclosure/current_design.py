"""Current housing/base construction from the retained design parameters.

No earlier CAD result, revision input or pre-existing cache is a construction
input. Coordinates in the feature tables are already in final assembly space.
"""
import json
import math
import hashlib
import sys
from pathlib import Path
import numpy as np
import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
from OCP.TopTools import TopTools_ListOfShape
from .cad import main_outline, smooth_wire
from .wall_offset import planar_inner_wire
from .usd import read_usd
from .source_features import boundaries
from .specs import source_report
from . import ROOT
sys.path.insert(0,str(ROOT/'tools'))
from shared_profiles import profile,binding


def parameters(folder, *, for_rebuild=False):
    result=json.loads((Path(folder)/'model_parameters.json').read_text(encoding='utf-8'))
    if result.get('schema_version')!=2:raise ValueError('Current design parameter schema is required')
    shared=profile(result['model'])
    if not for_rebuild and result['main_G3_quarter_controls_mm']!=shared['controls_mm']:
        raise ValueError('Published enclosure still uses a different fitted outline')
    result['main_G3_quarter_controls_mm']=shared['controls_mm']
    result['shared_profile']=binding(result['model'])
    if for_rebuild:
        path=ROOT/'data/enclosure_design.json'
        rules=json.loads(path.read_text(encoding='utf-8'))[result['model']]
        definition=result['base_design']
        angle=rules['cone_angle_to_horizontal_degrees']
        slope=1. if angle==45. else math.sqrt(3.) if angle==30. else 1/math.tan(math.radians(angle))
        definition.update(cone_angle_to_horizontal_degrees=angle,cone_slope_dr_dz=slope)
        if result['model']=='mac-mini':definition['vent_width_mm']=rules['vent_width_mm']
        else:
            definition.update(vent_diameter_mm=rules['vent_diameter_mm'],horizontal_bore_rings=True,
                              base_ring_count=rules['base_ring_count'],base_minimum_center_pitch_mm=rules['base_minimum_center_pitch_mm'])
            result['rear_grid_design']=rules['rear_grid']
        wall=result['features']['base_wall'];intercept=definition['outer_cone_radius_intercept_mm']
        wall['cone']={'slope_dr_dz':slope,'intercept_radius_mm':intercept}
        wall['conical_surface']={'slope':slope,'outer_intercept':intercept,
                                'inner_intercept':intercept-definition['cone_normal_thickness_mm']*math.hypot(1,slope)}
        result['design_requirements']={'file':'data/enclosure_design.json','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return result


def fuse(a,b):
    operation=BRepAlgoAPI_Fuse();arguments=TopTools_ListOfShape();operands=TopTools_ListOfShape()
    arguments.Append(a.wrapped);operands.Append(b.wrapped)
    operation.SetArguments(arguments);operation.SetTools(operands);operation.SetRunParallel(False)
    operation.SetFuzzyValue(1e-6);operation.Build()
    if not operation.IsDone():raise ValueError('Base plate/cone union failed')
    return cq.Shape.cast(operation.Shape())


def side_cutters(design):
    half=design['nominal_dimensions_mm'][1]/2;result=[]
    for port in design['side_apertures']:
        points=np.asarray(port['mouth_points_nominal_mm']).copy();side=port['side_y_sign']
        points[:,1]=side*(half+2)
        result.append(cq.Solid.extrudeLinear(smooth_wire(points),[],(0,-side*(half+2),0)))
    return result


def housing_without_rear_holes(design):
    controls=np.asarray(design['main_G3_quarter_controls_mm'])
    low=design['base_design']['interface_z_mm'];top=design['nominal_dimensions_mm'][2]
    thickness=design['wall_thickness_mm']
    outer=cq.Solid.extrudeLinear(main_outline(controls,low),[],(0,0,top-low))
    inner,offset=planar_inner_wire(controls,low-1,thickness)
    cavity=cq.Solid.extrudeLinear(inner,[],(0,0,top-low-thickness+1))
    body=outer.cut(cavity,tol=1e-6).cut(*side_cutters(design),tol=1e-6).clean()
    if len(body.Solids())!=1 or not body.isValid():raise ValueError('Current housing construction failed')
    return body,offset


def unperforated_base(design):
    definition=design['base_design'];slope=definition['cone_slope_dr_dz']
    intercept=definition['outer_cone_radius_intercept_mm'];top=definition['height_mm']
    plate_thickness=definition['plate_thickness_mm'];wall=definition['cone_normal_thickness_mm']
    inner_intercept=intercept-wall*np.hypot(1,slope)
    wire,_=planar_inner_wire(np.asarray(design['main_G3_quarter_controls_mm']),definition['interface_z_mm'],design['wall_thickness_mm'])
    outer=cq.Solid.makeCone(intercept,intercept+slope*top,top)
    plate=cq.Solid.extrudeLinear(wire,[],(0,0,plate_thickness))
    outer=outer.fuse(plate) if design['model']=='mac-mini' else fuse(outer,plate)
    cavity=cq.Solid.makeCone(inner_intercept+slope*plate_thickness,inner_intercept+slope*(top+1),top+1-plate_thickness,cq.Vector(0,0,plate_thickness))
    return outer.cut(cavity,tol=1e-6).clean()


def source_button_points():
    report=source_report('mac-mini')
    audit,meshes,_,_=read_usd(ROOT/'data/input/mac-mini-silver.usdz')
    if audit['sha256']!=report['source_sha256']:raise ValueError('Source USDZ changed')
    vertices,counts,indices,_=list(meshes.values())[6]
    matches=[]
    for loop in boundaries(vertices[:,[0,2,1]],counts,indices):
        span=np.ptp(loop,axis=0)
        if span[2]<.01 and 9<span[0]<12:
            points=loop.copy();points[:,:2]*=report['calibration_xyz'][:2];matches.append(points)
    if len(matches)!=1:raise ValueError('Source button aperture is not unique')
    return matches[0]


def source_button():
    points=source_button_points();points[:,2]=-1
    return cq.Solid.extrudeLinear(smooth_wire(points),[],(0,0,15))
