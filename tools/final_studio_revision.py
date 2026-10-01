"""Build the current Studio housing and merged base from design inputs."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from enclosure import ROOT
import cadquery as cq
import numpy as np
from enclosure.current_design import parameters,housing_without_rear_holes,unperforated_base
from enclosure.mini_openings import _cut_batch
from tools.rebuild_bottom_revision import horizontal_face,sampled_distance,STAGE
from tools.housing_perforations import validate_cylinder_axes
from tools.rear_row_bands import perforate_rear_by_rows
from enclosure.studio_rear_pattern import make_pattern as make_rear_pattern,write_pattern as write_rear_pattern,inspect_pattern as inspect_rear_pattern
from enclosure.validation import validate_profile,validate_plain_top
from enclosure.studio_base_pattern import circular_pattern,inspect_pattern,write_pattern


def perforate_base(base,table_path,progress_label='Studio'):
    """Drill the current circular feature table, without an earlier CAD input."""
    data=np.loadtxt(table_path,delimiter=',',skiprows=1)
    centers,normals,radii=data[:,:3],data[:,3:6],data[:,6]
    rings=np.split(np.sort(centers[:,2]),np.flatnonzero(np.diff(np.sort(centers[:,2]))>.1)+1)
    if len(rings)!=8 or any(len(ring)!=len(rings[0]) for ring in rings):
        raise ValueError('Studio requires eight equally populated base rings')
    if not np.allclose(np.linalg.norm(normals,axis=1),1,atol=1e-12,rtol=0):
        raise ValueError('Base drilling directions must be unit normals')
    for start in range(0,len(data),126):
        end=min(start+126,len(data))
        cutters=[cq.Solid.makeCylinder(float(r),5.5,cq.Vector(*(p+2*n)),cq.Vector(*(-n)))
                 for p,n,r in zip(centers[start:end],normals[start:end],radii[start:end])]
        base=_cut_batch(base,cutters,1e-6)
        if not base.isValid() or len(base.Solids())!=1:
            raise ValueError('Studio base hole boolean failed')
        print(progress_label,'base holes',end,'/',len(data),flush=True)
    geometry=validate_cylinder_axes(base,centers,-normals,radii)
    return base,{'hole_count':len(data),'radius_mm':float(radii[0]),
        'designed_wall_thickness_mm':1.5,'through_designed_wall':True,
        'vent_edge_clearance_along_cone_mm':.75,'geometry':geometry}


def build_housing(design,out,thickness):
    housing,offset=housing_without_rear_holes(design)
    table=make_rear_pattern(design['main_G3_quarter_controls_mm'],design['rear_grid_design'])
    write_rear_pattern(out/'rear_hole_axes.csv',table)
    housing,rear=perforate_rear_by_rows(housing,out,thickness,design,out/'rear_hole_axes.csv')
    rear['wrapped_planar_grid']=inspect_rear_pattern(table,design['main_G3_quarter_controls_mm'],design['rear_grid_design'])
    if not rear['wrapped_planar_grid']['passed']:raise ValueError('Rear planar pattern does not satisfy the design')
    return housing,rear,offset


def build(folder,thickness):
    folder=Path(folder);design=parameters(folder,for_rebuild=True);definition=design['base_design']
    out=STAGE/'mac-studio'/f'{thickness}mm';out.mkdir(parents=True,exist_ok=True)
    housing,rear,offset=build_housing(design,out,thickness)
    data=circular_pattern(definition)
    write_pattern(out/'base_hole_axes.csv',data)
    base,holes=perforate_base(unperforated_base(design),out/'base_hole_axes.csv',f'Studio {thickness} mm')
    holes['horizontal_rings']=inspect_pattern(data,definition)
    bottom=definition['interface_z_mm']
    inner=horizontal_face(housing,bottom,largest=True).innerWires()[0]
    outer=horizontal_face(base,bottom,largest=True).outerWire()
    error=max(sampled_distance(inner,outer),sampled_distance(outer,inner))
    if error>1e-6:raise ValueError('Studio mating contours differ')
    slope=definition['cone_slope_dr_dz'];intercept=definition['outer_cone_radius_intercept_mm']
    return {'housing':housing,'base':base},{
        'plate_to_housing_contour_max_error_mm':error,'inner_profile_offset':offset,
        'top':validate_plain_top(housing,95,np.asarray(design['main_G3_quarter_controls_mm'])),
        'profile':validate_profile(np.asarray(design['main_G3_quarter_controls_mm'])),
        'bottom_plate_merged_into_base':True,'support_ring_removed':True,
        'port_order_reflected_x':True,'front_and_rear_port_count':len(design['side_apertures']),
        'housing_height_mm':86.5,'base_height_mm':10.0,'base_insertion_depth_mm':1.5,
        'side_port_z_shift_mm':design['source_port_transform']['z_shift_mm'],
        'base_floor_extended_to_z_mm':0,'upper_planar_plate_thickness_mm':1.5,
        'lower_planar_plate_thickness_mm':1.5,'conical_normal_thickness_mm':1.5,
        'outer_cone_plane_intersection_z_mm':[0.0,bottom],'inner_cone_direct_to_planes':True,
        'vent_edge_clearance_along_cone_mm':.75,
        'conical_surface':{'slope':slope,'outer_intercept':intercept,'inner_intercept':intercept-1.5*np.hypot(1,slope)},
        'rear_perforations':rear,'base_perforations':holes}
