"""Stage the final two-part Mini and Studio enclosures.

Only staged files are written. The accepted delivery is not replaced here.
"""

from pathlib import Path
import argparse
import hashlib
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enclosure import ROOT

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Curve

from enclosure.cad import main_outline
from enclosure.mini_capsules import make_capsule_cutters, validate_capsule_cylinders
from enclosure.validation import validate_plain_top,validate_profile
from enclosure.wall_offset import planar_inner_wire
from enclosure.current_design import parameters, housing_without_rear_holes, unperforated_base, source_button


STAGE = ROOT / ".tmp/bottom-revision-stage"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def horizontal_face(shape, z, *, largest=False):
    faces = [f for f in shape.Faces()
             if max(abs(f.BoundingBox().zmin - z), abs(f.BoundingBox().zmax - z)) < 2e-5]
    if not faces:
        raise ValueError(f"No horizontal face at z={z}")
    return max(faces, key=lambda f: f.Area()) if largest else faces[0]


def sampled_distance(source, target):
    error = 0.0
    for edge in source.Edges():
        curve = BRepAdaptor_Curve(edge.wrapped)
        for u in np.linspace(curve.FirstParameter(), curve.LastParameter(), 21):
            point = curve.Value(float(u))
            vertex = cq.Vertex.makeVertex(point.X(), point.Y(), point.Z())
            error = max(error, vertex.distance(target))
    return error


def bounds_tuple(box):
    return (box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax)


def stage_mini(folder, thickness):
    design=parameters(folder,for_rebuild=True)
    controls=np.asarray(design['main_G3_quarter_controls_mm'])
    z,height,base_top=6.5,49.5,8.0
    port_shift=design['source_port_transform']['z_shift_mm']
    housing,offset=housing_without_rear_holes(design)
    if not housing.isValid() or len(housing.Solids()) != 1:
        raise ValueError("Mini flush-bottom housing is invalid")
    if not validate_plain_top(housing, height, controls)["passed"]:
        raise ValueError("Mini top changed")
    inner_seams = [e for e in housing.Edges()
                   if abs(e.BoundingBox().zmin-(z+thickness)) < 1e-4
                   and e.BoundingBox().zlen < 1e-4 and e.Length() > 5]
    if inner_seams:
        raise ValueError("Mini inner bottom still has a visible ring edge")

    # The upper 1.5 mm planar rim surrounds, rather than covers, the cone.
    # Its outer edge is the exact G3 inner contour of the housing.
    cut_z = z
    definition=design['base_design'];slope=definition['cone_slope_dr_dz']
    outer_intercept=definition['outer_cone_radius_intercept_mm']
    intercept=outer_intercept-1.5*np.hypot(1,slope)
    core=unperforated_base(design)
    # Shorten and center the source-style slots so both the mouth and the
    # inward normal exit stay on the conical wall between the two planes.
    cone = {"slope_dr_dz":slope,"intercept_radius_mm":outer_intercept,"z_min_mm":0.0,"z_max_mm":cut_z}
    slot_tools, pattern = make_capsule_cutters(cone, 1.5,
        width_mm=definition['vent_width_mm'],length_mm=cut_z*np.hypot(1, slope)-1.5, center_z_mm=cut_z/2)
    half_z = pattern["length_mm"] / (2 * np.hypot(1, slope))
    normal_exit_z = pattern["center_z_mm"] + half_z + 1.5*slope/np.hypot(1, slope)
    normal_entry_z = pattern["center_z_mm"]-half_z+1.5*slope/np.hypot(1, slope)
    if normal_entry_z < 1.5-1e-7 or normal_exit_z > base_top:
        raise ValueError("Mini slots extend onto one of the planar plates")
    from enclosure.mini_openings import cut_mini_base_openings
    button = source_button()
    core, cutting = cut_mini_base_openings(core, slot_tools, button, thickness,
                                           cache_root=ROOT / ".tmp/mini-planar-opening-batches")
    base = core
    if not base.isValid() or len(base.Solids()) != 1:
        raise ValueError("Mini matched base is invalid")
    holes = validate_capsule_cylinders(base, pattern)
    if not holes.get("passed") or holes.get("verified_unique_capsule_cylinder_axes") != 216:
        raise ValueError("Mini slots changed")
    bottom_face = horizontal_face(housing, z, largest=True)
    top_face = horizontal_face(base, z, largest=True)
    inner_wires = bottom_face.innerWires()
    if len(inner_wires) != 1:
        raise ValueError("Mini housing bottom must have one inner wire")
    housing_wire, base_wire = inner_wires[0], top_face.outerWire()
    match_error = max(sampled_distance(housing_wire, base_wire),
                      sampled_distance(base_wire, housing_wire))
    if match_error > 1e-6:
        raise ValueError(f"Mini mating contour mismatch: {match_error} mm")
    pattern.update({"geometry": holes, "cutting": cutting,
                    "through_designed_wall": True, "button_aperture": True})
    return {"housing": housing, "base": base}, {
        "mini_inner_bottom_seam_edges": 0,
        "housing_height_mm":43.0,"base_height_mm":8.0,
        "housing_bottom_z_mm":6.5,"assembly_height_mm":49.5,
        "base_insertion_depth_mm":1.5,"side_port_z_shift_mm":port_shift,
        "upper_planar_plate_z_range_mm":[6.5,8.0],
        "conical_junction_extension_top_z_mm":8.0,
        "base_to_housing_contour_max_error_mm": match_error,
        "unchanged_capsule_axes": holes["verified_unique_capsule_cylinder_axes"],
        "inner_profile_offset": offset,
        "top":validate_plain_top(housing,height,controls),"profile":validate_profile(controls),
        "upper_planar_plate_thickness_mm": 1.5,
        "lower_planar_plate_thickness_mm": 1.5,
        "conical_normal_thickness_mm": 1.5,
        "inner_cone_radius_intercept_mm": intercept,
        "outer_cone_plane_intersection_z_mm": [0.0, cut_z],
        "vent_edge_clearance_along_cone_mm": 0.75,
        "upper_plate_start_z_mm": cut_z,
        "base_floor_extended_to_z_mm": 0,
        "slot_mouth_z_range_mm": [pattern["center_z_mm"]-half_z,
                                   pattern["center_z_mm"]+half_z],
        "slot_normal_exit_max_z_mm": normal_exit_z,
        "slots_only_on_conical_face": True,
        "inner_cone_direct_to_planes": True,
        "unperforated_reference": "generated in memory from current model_parameters.json",
    }, pattern


def export_stage(model,thickness,*,preserve_housing=False):
    label=f'{thickness}mm';folder=ROOT/'results/masters'/model/('enclosure-'+label)
    out=STAGE/model/label;out.mkdir(parents=True,exist_ok=True)
    if model=='mac-mini':parts,checks,pattern=stage_mini(folder,thickness)
    else:
        from tools.final_studio_revision import build
        parts,checks=build(folder,thickness);pattern=None
    if preserve_housing:
        parts['housing']=cq.Shape.importBrep(str(folder/'housing.brep'))
    outputs=[]
    for name,shape in parts.items():
        if preserve_housing and name=='housing':continue
        path=out/(name+'.brep')
        if not shape.exportBrep(str(path)):raise ValueError('BREP export failed')
        outputs.append(path);print(model,label,name,'procedural BREP staged',flush=True)
    compound=cq.Compound.makeCompound([parts['housing'],parts['base']])
    path=out/f'{model}_housing_{label}.brep';compound.exportBrep(str(path));outputs.append(path)
    bounds=compound.BoundingBox();dimensions=[bounds.xlen,bounds.ylen,bounds.zlen]
    expected=[127,127,49.5] if model=='mac-mini' else [197,197,95]
    if len(compound.Solids())!=2 or max(abs(a-b) for a,b in zip(dimensions,expected))>.001:
        raise ValueError('Staged assembly dimensions or body count differ')
    record={'model':model,'thickness_mm':thickness,'passed':True,'parts':['housing','base'],'checks':checks,
        'assembly_solid_count':2,'assembly_dimensions_mm':dimensions,'changed_file_sha256':{p.name:digest(p) for p in outputs},
        'stage':'procedural BREP only; all formats require shared strict native acceptance',
        'design_parameters':parameters(folder,for_rebuild=True)}
    if preserve_housing:
        record['preserved_housing']={'file':(folder/'housing.brep').relative_to(ROOT).as_posix(),'sha256':digest(folder/'housing.brep')}
    if pattern is not None:
        pattern.pop('cutting',None)
        (out/'uniform_vent_pattern.json').write_text(json.dumps(pattern,indent=2)+'\n',encoding='utf-8')
        record['pattern_sha256']=digest(out/'uniform_vent_pattern.json')
    (out/'stage_validation.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(model,label,'STAGED',flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=('mac-mini','mac-studio'),required=True)
    parser.add_argument('--thickness',type=int,choices=(2,3),required=True);args=parser.parse_args()
    export_stage(args.model,args.thickness)

if __name__=='__main__':main()
