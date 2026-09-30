"""Read-only audit of the redesigned Mini normal-cut capsule vents.

Checks actual final-CAD ray intersections and interfaces. Only the unperforated
comparison body is regenerated in memory; final parts are never modified.
--help and all readiness checks run before loading a CAD kernel.
"""

from pathlib import Path
import argparse
import hashlib
import json
import math
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, record):
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thickness", type=int, choices=[2, 3], required=True)
    args = parser.parse_args()
    thickness = float(args.thickness)
    label = f"{args.thickness}mm"
    folder = ROOT / "results/masters/mac-mini" / ("enclosure-"+label)
    validation_path = folder / "validation.json"
    validation = read(validation_path)
    if not validation.get("passed") or validation.get("wall_thickness_mm") != thickness:
        raise ValueError("Wait for an accepted build of the requested thickness")
    openings = validation["base_perforations"]
    if not openings.get("all_vents_use_exhaust_style") or not openings.get("inward_inlet_baffles_removed"):
        raise ValueError("The final files still describe the previous Mini base")
    pattern_path = folder / openings["pattern_file"]
    pattern_hash = sha(pattern_path)
    if pattern_hash != openings["pattern_sha256"]:
        raise ValueError("Capsule feature table does not match the accepted build")
    pattern = read(pattern_path)
    if pattern.get("design_thickness_mm") != 1.5 or len(pattern.get("holes", [])) != 108:
        raise ValueError("Wrong capsule feature count or thickness")
    if not pattern.get("geometry", {}).get("passed"):
        raise ValueError("Actual semicylinder verification has not passed")
    parameter_path=folder/'model_parameters.json'
    parameter_hash=sha(parameter_path)
    paths = {"housing": folder / "housing.brep", "base": folder / "base.brep"}
    hashes = {name: sha(path) for name, path in paths.items()}
    validation_hash = sha(validation_path)
    started = time.monotonic()

    from enclosure import ROOT as _dependency_root
    from enclosure.specs import source_report
    import cadquery as cq
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Pnt, gp_Dir, gp_Lin
    from OCP.TopAbs import TopAbs_IN, TopAbs_OUT

    parts = {name: cq.Shape.importBrep(str(path)) for name, path in paths.items()}
    from enclosure.current_design import parameters,unperforated_base,source_button_points
    uncut=unperforated_base(parameters(folder))
    if any(not shape.isValid() or len(shape.Solids()) != 1 for shape in [uncut, *parts.values()]):
        raise ValueError("Audit inputs are not valid single solids")
    boxes = {name: shape.BoundingBox() for name, shape in parts.items()}
    classifiers = {name: BRepClass3d_SolidClassifier(shape.wrapped) for name, shape in parts.items()}
    classifiers["uncut"] = BRepClass3d_SolidClassifier(uncut.wrapped)

    def state(name, point):
        classifiers[name].Perform(gp_Pnt(*map(float, point)), 1e-7)
        return classifiers[name].State()

    def intersector(shape):
        result = IntCurvesFace_ShapeIntersector()
        result.Load(shape.wrapped, 1e-7)
        return result

    rays = {name: intersector(shape) for name, shape in parts.items()}
    rays["uncut"] = intersector(uncut)

    def intersections(name, a, b):
        delta = np.asarray(b)-np.asarray(a)
        length = np.linalg.norm(delta)
        check = rays[name]
        check.Perform(gp_Lin(gp_Pnt(*map(float, a)), gp_Dir(*map(float, delta))), 0, float(length))
        if not check.IsDone():
            raise ValueError("Line/face intersection did not finish")
        return [float(check.WParameter(j)) for j in range(1, check.NbPnt()+1)]

    cone = pattern["cone"]
    slope, intercept = cone["slope_dr_dz"], cone["intercept_radius_mm"]
    factor = math.hypot(1, slope)
    floor = validation["base_wall"]["interior_floor_z_mm"]
    top = validation["base_wall"]["top_interface_z_mm"]
    body_inner_radius = min(validation["nominal_dimensions_mm"][:2])/2-thickness

    def endpoint_cavity(point):
        if any(state(name, point) != TopAbs_OUT for name in ("uncut", "housing")):
            return None
        r = np.linalg.norm(point[:2])
        if floor+1e-6 < point[2] < top-1e-6 and r < intercept+slope*point[2]-1.5*factor-1e-6:
            return "base_conical_cavity"
        if top+1e-6 < point[2] < validation["nominal_dimensions_mm"][2]-thickness-1e-6 and r < body_inner_radius-1e-6:
            return "housing_cavity_above_base"
        return None

    checks = []
    for index, hole in enumerate(pattern["holes"]):
        center = np.asarray(hole["center_mm"], dtype=float)
        normal = np.asarray(hole["outward_normal"], dtype=float)
        tangent = np.asarray(hole["tangent"], dtype=float)
        axis = np.asarray(hole["long_axis"], dtype=float)
        radial = center.copy();radial[2] = 0;radial /= np.linalg.norm(radial)
        expected_normal = (radial-[0, 0, slope])/factor
        if (abs(np.linalg.norm(normal)-1)>1e-10 or np.linalg.norm(normal-expected_normal)>1e-10
                or abs(normal@tangent)>1e-10 or abs(normal@axis)>1e-10):
            raise ValueError("The feature table does not describe local cone-normal slots")
        radius = hole["width_mm"]/2
        straight_half = (hole["length_mm"]-hole["width_mm"])/2
        # Every ninth slot probes near both rounded ends, including the portion
        # whose normal bore may leave through the top ring into the housing.
        station = hole["length_mm"]/2-.10
        stations = [-station, 0, station] if index % 9 == 0 else [0]
        for along in stations:
            cap_distance = max(0, abs(along)-straight_half)
            half_width = math.sqrt(radius*radius-cap_distance*cap_distance)
            for fraction in (.25, .5, .75):
                across = (2*fraction-1)*half_width
                p = center+along*axis+across*tangent
                a = p+hole["outside_lead_mm"]*normal
                b = a-hole["total_cut_depth_mm"]*normal
                before = intersections("uncut", a, b)
                after = intersections("base", a, b)
                housing = intersections("housing", a, b)
                cavity = endpoint_cavity(b)
                item = {"slot": index, "longitudinal_station_mm": along,
                        "tangent_fraction": fraction, "uncut_skin_intersections": len(before),
                        "cut_skin_intersections": len(after), "housing_intersections": len(housing),
                        "inner_endpoint_in_original_cavity": cavity is not None,
                        "cavity_region": cavity, "ray_start_mm": a.tolist(), "ray_end_mm": b.tolist()}
                checks.append(item)
                if len(before)<2 or after or housing or not cavity:
                    print("SLOT PROBLEM", item, flush=True)
        if index % 18 == 17:
            print("normal capsule slots checked", index+1, "rays", len(checks), flush=True)
    # The button is extracted directly from USDZ; no source-inspection cache is needed.
    report=source_report('mac-mini')
    if pattern['source_sha256']!=report['source_sha256']:raise ValueError('Source references disagree')
    button_xy=source_button_points()[:,:2].mean(0)
    button_rays = {name: intersections(name, [*button_xy, -.5], [*button_xy, 14]) for name in ("base", "housing")}
    button_samples = [{"z_mm": float(z), "occupied": [name for name in ("base", "housing")
                      if state(name, [*button_xy, z]) != TopAbs_OUT]} for z in np.linspace(-.5, 14, 59)]
    floor_samples = []
    for r in (0, 10, 20, 30, 40):
        for angle in np.linspace(0, 2*np.pi, 36, endpoint=False):
            for z in (validation["base_wall"]["bottom_z_mm"]+.1, floor-.1):
                floor_samples.append(state("base", [r*np.cos(angle), r*np.sin(angle), z]) == TopAbs_IN)

    def contact_faces(name, upper):
        boundary = 6.5 if name=='base' else boxes[name].zmin
        faces = [f for f in parts[name].Faces() if max(abs(f.BoundingBox().zmin-boundary),
                 abs(f.BoundingBox().zmax-boundary)) < 2e-5]
        if not faces:
            raise ValueError("No planar part interface found")
        z = float(np.mean([v.Z for f in faces for v in f.Vertices()]))
        return faces, z

    base_faces, z0 = contact_faces("base", True)
    housing_faces, z1 = contact_faces("housing", False)
    base_wire = max(base_faces, key=lambda face: face.Area()).outerWire()
    housing_inner = max(housing_faces, key=lambda face: face.Area()).innerWires()
    if len(housing_inner) != 1:
        raise ValueError("Housing bottom needs one mating inner contour")
    housing_wire = housing_inner[0]
    def contour_error(source, target):
        error = 0.0
        for edge in source.Edges():
            curve = BRepAdaptor_Curve(edge.wrapped)
            for u in np.linspace(curve.FirstParameter(), curve.LastParameter(), 21):
                p = curve.Value(float(u))
                error = max(error, cq.Vertex.makeVertex(p.X(), p.Y(), p.Z()).distance(target))
        return error
    match_error = max(contour_error(base_wire, housing_wire),
                      contour_error(housing_wire, base_wire))
    contacts = {"base_to_housing": {"lower_top_z_mm": z0, "upper_bottom_z_mm": z1,
        "height_gap_mm": z1-z0, "outer_to_inner_contour_max_error_mm": match_error,
        "contour_match_tolerance_mm": 1e-6}}

    from OCP.BRepAdaptor import BRepAdaptor_Surface
    vertical_risers = []
    cone_ranges = []
    for face in parts['base'].Faces():
        surface = BRepAdaptor_Surface(face.wrapped)
        if face.geomType() == 'CYLINDER':
            cylinder = surface.Cylinder()
            if cylinder.Radius() > 20 and abs(cylinder.Axis().Direction().Z()) > .999999:
                vertical_risers.append(cylinder.Radius())
        elif face.geomType() == 'CONE':
            cone_ranges.append([face.BoundingBox().zmin, face.BoundingBox().zmax])
    direct_cone = any(abs(lo-1.5)<1e-5 and abs(hi-8.0)<1e-5 for lo,hi in cone_ranges)
    horizontal = [(f, f.BoundingBox().zmin) for f in parts['base'].Faces()
                  if f.BoundingBox().zlen < 1e-5]
    # Slots form inner wire loops if they pierce a horizontal face. The only
    # allowed extra opening is the existing button aperture in the upper rim.
    planar_wire_counts = [{'z_mm':z,'wire_count':len(f.Wires())} for f,z in horizontal]
    no_planar_vents = all(len(f.Wires()) <= (3 if z>2 else 1) for f,z in horizontal)

    ports = []
    for index, port in enumerate(report["ports"]):
        p = np.asarray(port["mouth_points_world_mm"]).mean(0)
        p[2] -= report["source_bottom_offset_mm"];p *= report["calibration_xyz"]
        p[2] += validation.get("side_port_z_shift_mm",0)
        p[1] = port["side"]*(report["calibration_dimensions_mm"][1]/2+2)
        end = p.copy();end[1] = 0
        ports.append({"port": index, "skin_intersections": len(intersections("housing", p, end)),
                      "cavity_endpoint_outside_solid": state("housing", end) == TopAbs_OUT})
    record = {
        "schema_version": 3, "model": "mac-mini", "thickness_mm": thickness,
        "method": "Independent normal capsule-ray/face intersections against final CAD; unperforated reference regenerated in memory from current parameters",
        "input_hashes": hashes, "input_files": {k:p.name for k,p in paths.items()},
        "validation_sha256": validation_hash, "parameters_sha256": parameter_hash, "uniform_vent_pattern_sha256": pattern_hash,
        "uniform_vent_pattern_file": pattern_path.name,
        "unperforated_reference": {"construction": "current_design.unperforated_base", "parameters_sha256": parameter_hash},
        "source_base_slot_count": 108, "slot_rays": checks,
        "all_sampled_slot_paths_open_to_original_cavity": len(checks)==396 and all(
            x["uncut_skin_intersections"]>=2 and x["cut_skin_intersections"]==0
            and x["housing_intersections"]==0 and x["inner_endpoint_in_original_cavity"] for x in checks),
        "normal_direction_verified_against_cone": True,
        "sampling": {"transverse_fractions": [.25, .5, .75],
                     "every_ninth_slot_rounded_end_margin_mm": .10,
                     "contact_contour_samples_per_edge": 21},
        "button_center_xy_mm": button_xy.tolist(), "button_axis_intersections": button_rays,
        "button_axis_samples": button_samples,
        "button_axis_open": not any(button_rays.values()) and all(not x["occupied"] for x in button_samples),
        "central_floor_radius_tested_mm": 40, "central_floor_sample_count": len(floor_samples),
        "central_floor_all_material": all(floor_samples), "interfaces": contacts,
        "inner_cone_direct_to_both_planes": direct_cone,
        "unwanted_vertical_cylindrical_risers": vertical_risers,
        "planar_face_wire_counts": planar_wire_counts,
        "no_vent_loops_in_planar_faces": no_planar_vents,
        "side_port_axis_checks": ports,
        "all_side_port_axes_open_to_cavity": len(ports)==9 and all(x["skin_intersections"]==0 and x["cavity_endpoint_outside_solid"] for x in ports),
        "all_input_geometry_hashes_unchanged": all(sha(paths[k])==v for k,v in hashes.items()),
        "all_hashes_bound_to_final_delivery_brep": True,
        "source_usdz_sha256": report["source_sha256"], "source_button_extracted_from_usdz": True,
        "audit_script_sha256": sha(Path(__file__)), "elapsed_seconds": time.monotonic()-started,
        "scope_limit": "Sampled normal opening paths and exact mating contour; base upper adapter is not claimed uniformly thick",
    }
    record["passed"] = (record["all_sampled_slot_paths_open_to_original_cavity"] and record["button_axis_open"]
        and direct_cone and not vertical_risers and no_planar_vents
        and record["central_floor_all_material"] and record["all_side_port_axes_open_to_cavity"]
        and record["all_input_geometry_hashes_unchanged"] and all(abs(c["height_gap_mm"])<1e-5
        and c["outer_to_inner_contour_max_error_mm"]<=1e-6 for c in contacts.values()))
    if sha(validation_path)!=validation_hash or sha(pattern_path)!=pattern_hash or sha(parameter_path)!=parameter_hash:
        raise ValueError("Build evidence changed during the independent audit")
    output = folder / "mini_opening_interface_audit.json"
    save(output, record)
    print("AUDIT COMPLETE", record["passed"], output, "seconds", record["elapsed_seconds"], flush=True)
    raise SystemExit(0 if record["passed"] else 1)


if __name__ == "__main__":
    main()
