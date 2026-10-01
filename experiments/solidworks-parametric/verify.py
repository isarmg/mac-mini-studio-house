"""Independent checks for the SW prototype; this is not release acceptance."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".vendor"))
import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import brentq

GEOMETRY_TOL_MM = 1e-7
PARAMETER_TOL = 1e-11


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(actual, expected, tolerance=GEOMETRY_TOL_MM):
    need(abs(actual - expected) <= tolerance, f"{actual} differs from {expected}")


def quarter(points, count):
    points = np.asarray(points, dtype=float).copy()
    for _ in range(count):
        points = np.column_stack((points[:, 1], -points[:, 0]))
    return points


def normalize(knots):
    knots = np.asarray(knots, dtype=float)
    return (knots - knots[0]) / (knots[-1] - knots[0])


def outline_area(definition):
    """8-point Gauss integration is exact for the degree-13 polynomial integrand."""
    poles = np.asarray(definition["controls_mm"])
    curve = BSpline(np.repeat(definition["knots"], definition["multiplicities"]), poles, 7)
    nodes, weights = np.polynomial.legendre.leggauss(8)
    corner = 0.0
    for start, end in zip(definition["knots"][:-1], definition["knots"][1:]):
        u = (start + end) / 2 + nodes * (end - start) / 2
        p, tangent = curve(u), curve(u, 1)
        corner += (end - start) / 2 * np.dot(weights, p[:, 0] * tangent[:, 1] - p[:, 1] * tangent[:, 0])
    a, b = poles[-1], quarter(poles, 1)[0]
    return abs(2 * (corner + a[0] * b[1] - a[1] * b[0]))


def native_profile(surface):
    need(surface["type"] == "BSplineSurface", "Expected retained native B-spline support")
    need(surface["dimension"] == 3, "Unexpected rational/support coordinate convention")
    poles = np.asarray(surface["poles"], dtype=float)
    # Native control rows follow V; columns follow U, regardless of UV transposition.
    need(poles.shape == (surface["rows"], surface["columns"], 3), "Control-net dimensions disagree")
    if surface["u_degree"] == 7 and surface["v_degree"] == 1:
        controls, other, knots = poles[0], poles[1], surface["u_knots"]
    else:
        need(surface["v_degree"] == 7 and surface["u_degree"] == 1, "Profile degree changed")
        controls, other, knots = poles[:, 0], poles[:, 1], surface["v_knots"]
    close(float(np.max(np.linalg.norm((controls - other)[:, :2], axis=1))) * 1000, 0)
    # Independently evaluate the full native tensor-product definition against API samples.
    u_basis = BSpline(surface["u_knots"], np.eye(surface["columns"]), surface["u_degree"])
    v_basis = BSpline(surface["v_knots"], np.eye(surface["rows"]), surface["v_degree"])
    sample_error = max(float(np.linalg.norm(np.einsum("i,ijc,j->c", v_basis(s["uv"][1]), poles, u_basis(s["uv"][0])) - s["point"])) * 1000 for s in surface["samples"])
    close(sample_error, 0)
    return controls[:, :2] * 1000, normalize(knots), sample_error


def check_profiles(surfaces, definition):
    need(len(surfaces) == 8, "Expected four outer and four inner curved supports")
    expected = []
    for name, source in (("outer", definition["outer"]), ("inner_2mm", definition["inner"]["2"])):
        need(source["degree"] == 7 and all(w == 1 for w in source["weights"]), "Source curve convention changed")
        for q in range(4):
            expected.append((name, q, quarter(source["controls_mm"], q), np.repeat(source["knots"], source["multiplicities"])))
    matched, records = set(), []
    for surface in surfaces:
        controls, knots, sample_error = native_profile(surface)
        candidates = []
        for i, (name, q, source_controls, source_knots) in enumerate(expected):
            if len(controls) != len(source_controls) or len(knots) != len(source_knots):
                continue
            for reverse in (False, True):
                poles = controls[::-1] if reverse else controls
                ks = 1 - knots[::-1] if reverse else knots
                error = float(np.max(np.linalg.norm(poles - source_controls, axis=1)))
                knot_error = float(np.max(np.abs(ks - source_knots)))
                candidates.append((error, knot_error, i, reverse, poles, ks))
        need(candidates, "Native support lost control points or knots")
        error, knot_error, i, reverse, poles, ks = min(candidates, key=lambda c: c[:2])
        need(i not in matched, "Duplicate/missing profile quadrant")
        matched.add(i)
        close(error, 0)
        close(knot_error, 0, PARAMETER_TOL)
        name, q, source_controls, _ = expected[i]
        curve = BSpline(ks, poles, 7)
        seams = []
        for u, direction in ((0.0, source_controls[1] - source_controls[0]), (1.0, source_controls[-1] - source_controls[-2])):
            v, a, j = curve(u, 1), curve(u, 2), curve(u, 3)
            speed = float(np.linalg.norm(v))
            need(speed > 0, "Degenerate curve endpoint")
            det = float(v[0] * a[1] - v[1] * a[0])
            curvature = det / speed**3
            rate = float(v[0] * j[1] - v[1] * j[0]) / speed**4 - 3 * det * float(np.dot(v, a)) / speed**6
            sine = abs(float(v[0] * direction[1] - v[1] * direction[0])) / (speed * float(np.linalg.norm(direction)))
            need(sine < 1e-9 and np.dot(v, direction) > 0 and abs(curvature) < 1e-8 and abs(rate) < 1e-8, "Native G3 seam failed")
            seams.append({"curvature_per_mm": curvature, "curvature_rate_per_mm2": rate, "tangent_sine_error": sine})
        records.append({"curve": name, "quadrant": q, "native_parameter_reversed": reverse,
                        "control_count": len(poles), "control_error_mm": error, "knot_error": knot_error,
                        "surface_evaluation_error_mm": sample_error, "g3_seams": seams})
    return records


def check_state(state, height):
    need(state["body_faults"] == 0, "Native solid check failed")
    close(state["height_mm"], height)
    need(state["volume_mm3"] > 0, "Non-positive native volume")


def check_housing(out, model, definition):
    params = read(out / f"{model}_housing.parameters.json")
    native = read(out / f"{model}_housing.native.json")
    part = out / f"{model}_G3_height_prototype.sldprt"
    need(native["native_reopen"] and sha(part) == native["file_sha256"], "Native reopen evidence is stale")
    need(params["source_sha256"] == sha(ROOT / params["source"]), "Curve source changed")
    need(params["seed_sha256"] == sha(ROOT / params["seed_file"]), "Exact seed changed")
    for receipt in (params, native):
        need(receipt["implementation_sha256"] == sha(ROOT / "experiments/solidworks-parametric/Prototype.cs"), "Implementation changed since acquisition")
    height = 43 if model == "mac-mini" else 86.5
    seed_height = 50 if model == "mac-mini" else 95
    outer, inner = outline_area(definition["outer"]), outline_area(definition["inner"]["2"])
    checks = {}
    for label, state, h in (("imported_seed", params["imported_seed"], seed_height), ("baseline", params["baseline"], height),
                            ("height_plus_2mm", params["height_plus_2mm"], height + 2), ("restored", params["restored"], height),
                            ("native_reopen", native["state"], height)):
        check_state(state, h)
        analytic_volume = outer * h - inner * (h - 2)
        relative_volume_error = abs(state["volume_mm3"] - analytic_volume) / analytic_volume
        # SW's native mass/area integration is approximate even at Higher accuracy.
        # Exact shape acceptance below uses the complete support definitions, not this diagnostic.
        need(relative_volume_error < 5e-4, "Native volume sanity check failed")
        checks[label] = {"height_mm": state["height_mm"], "reported_sw_volume_mm3": state["volume_mm3"],
                         "analytic_volume_mm3": analytic_volume, "reported_volume_relative_error": relative_volume_error,
                         "curved_supports": check_profiles(state["extrusion_profiles"], definition)}
    features = {f["name"]: f["type"] for f in native["state"]["features"]}
    need(features.get("FixedG3Master") == "BaseBody" and features.get("NativeHeight") == "MoveFace", "Editable feature tree missing")
    expressions = [e["expression"] for e in native["state"]["equations"]]
    need(len(expressions) == 3 and any("@NativeHeight" in e and '"HousingHeight"' in e for e in expressions), "Native height equation missing")
    body = native["geometry"][0]
    uses = Counter(e["edge_id"] for face in body["faces"] for loop in face["loops"] for e in loop["edges"])
    need(len(uses) == body["counts"]["edges"] and set(uses.values()) == {2}, "Non-manifold face-loop connectivity")
    unavailable = [e["id"] for e in body["edges"] if e["curve"]["type"] == "UnavailableNativeCurve"]
    horizontal_planes = [f["surface"]["parameters"] for f in body["faces"] if f["surface"]["type"] == "Plane" and abs(f["surface"]["parameters"][2]) > .99]
    need(len(horizontal_planes) == 3, "Expected bottom, top and cavity ceiling planes")
    for actual, expected in zip(sorted(p[5] * 1000 for p in horizontal_planes), [0, height - 2, height]):
        close(actual, expected)
    intersection_checks = []
    for edge_id in unavailable:
        edge = body["edges"][edge_id]
        adjacent = [f["surface"] for f in body["faces"] if any(e["edge_id"] == edge_id for loop in f["loops"] for e in loop["edges"])]
        need(sorted(s["type"] for s in adjacent) == ["BSplineSurface", "Plane"], "Unsupported boundary is not the known plane/profile intersection")
        plane = next(s for s in adjacent if s["type"] == "Plane")["parameters"]
        need(abs(plane[0]) < 1e-11 and abs(plane[1]) < 1e-11 and abs(abs(plane[2]) - 1) < 1e-11, "Boundary plane is not horizontal")
        poles, ks, _ = native_profile(next(s for s in adjacent if s["type"] == "BSplineSurface"))
        curve = BSpline(ks, poles, 7)
        ends = np.asarray([edge["start"], edge["end"]])[:, :2] * 1000
        endpoint_error = min(float(np.max(np.linalg.norm(ends - poles[[0, -1]], axis=1))), float(np.max(np.linalg.norm(ends[::-1] - poles[[0, -1]], axis=1))))
        close(endpoint_error, 0)
        chord = poles[-1] - poles[0]
        chord /= np.linalg.norm(chord)
        errors = []
        for sample in edge["samples"]:
            point = np.asarray(sample["point"]) * 1000
            close(point[2], plane[5] * 1000)
            progress = float(np.dot(point[:2] - poles[0], chord))
            u = brentq(lambda t: float(np.dot(curve(t) - poles[0], chord)) - progress, 0, 1, xtol=1e-14)
            errors.append(float(np.linalg.norm(curve(u) - point[:2])))
        close(max(errors), 0)
        intersection_checks.append({"edge_id": edge_id, "exact_support_intersection": "horizontal_plane_and_profile_extrusion",
                                    "profile_control_count": len(poles), "endpoint_error_mm": endpoint_error,
                                    "native_edge_evaluation_error_mm": max(errors), "wrapper_parameter_definition_exposed": False})
    return {"passed": True, "states": checks, "native_feature_types": features, "equations": expressions,
            "face_loop_connectivity_passed": True, "unavailable_edge_definition_ids": unavailable,
            "intersection_boundary_checks": intersection_checks,
            "full_release_acceptance": False}


def check_cones(record, angle, height):
    check_state(record["solid"], height)
    cones = record["cones"]
    need(len(cones) == 2, "Expected exactly two cone supports")
    for cone in cones:
        close(cone["angle_to_horizontal_degrees"], angle, 1e-8)
        close(cone["slope"], 1 / np.tan(np.deg2rad(angle)), 1e-10)
    thickness = abs(cones[0]["intercept_mm"] - cones[1]["intercept_mm"]) / np.sqrt(1 + cones[0]["slope"]**2)
    close(thickness, 1.5)
    return {"height_mm": height, "angle_degrees": angle, "normal_thickness_mm": float(thickness)}


def check_cylinders(data, diameter, count):
    holes = [np.asarray(d["parameters"], dtype=float) for d in data if d["parameters"][6] < .002]
    need(len(holes) == count, f"Expected {count} cylindrical holes; got {len(holes)}")
    radius0, slope = 76.68363284099085, np.sqrt(3)
    centers, phases = [], []
    for cylinder in holes:
        p, axis = cylinder[:3] * 1000, cylinder[3:6]
        close(cylinder[6] * 2000, diameter)
        close(float(np.linalg.norm(axis)), 1, 1e-11)
        radial = axis[:2] / np.linalg.norm(axis[:2])
        if np.dot(radial, p[:2]) < 0:
            radial, axis = -radial, -axis
        normal = np.array([radial[0], radial[1], -slope]) / np.sqrt(1 + slope**2)
        close(float(np.linalg.norm(np.cross(axis, normal))), 0, 1e-10)
        delta = (radius0 + slope * p[2] - np.dot(radial, p[:2])) / (np.dot(axis[:2], radial) - slope * axis[2])
        center = p + delta * axis
        close(float(center[2]), 4.25)
        close(float(np.linalg.norm(center[:2])), radius0 + slope * 4.25)
        centers.append(center)
        phases.append(float(np.arctan2(center[1], center[0]) % (2 * np.pi)))
    phases.sort()
    pitches = np.diff(phases + [phases[0] + 2 * np.pi])
    pitch_error = float(np.max(np.abs(pitches - 2 * np.pi / count)))
    close(pitch_error, 0, 1e-10)
    return {"cylindrical_hole_count": count, "diameter_mm": diameter,
            "center_height_mm": 4.25, "angular_pitch_error_radians": pitch_error,
            "normal_axis_passed": True}


def check_base(out):
    params, native = read(out / "studio_base.parameters.json"), read(out / "studio_base.native.json")
    need(native["native_reopen"] and sha(out / "mac-studio_cone_ring_prototype.sldprt") == native["file_sha256"], "Base reopen evidence stale")
    for receipt in (params, native):
        need(receipt["implementation_sha256"] == sha(ROOT / "experiments/solidworks-parametric/Prototype.cs"), "Base acquisition implementation changed")
    cones = {label: check_cones(params[label], a, h) for label, a, h in
             (("baseline", 30, 10), ("height_11mm", 30, 11), ("angle_35_degrees", 35, 10), ("restored", 30, 10))}
    holes = {label: check_cylinders(params[label], diameter, count) for label, diameter, count in
             (("cylinders", 1.5, 244), ("diameter_1_6mm", 1.6, 244), ("count_200", 1.5, 200), ("final_cylinders", 1.5, 244))}
    check_state(native["state"], 10)
    faces = native["geometry"][0]["faces"]
    cylinders = [{"parameters": f["surface"]["parameters"]} for f in faces if f["surface"]["type"] == "CylindricalSurface"]
    holes["native_reopen"] = check_cylinders(cylinders, 1.5, 244)
    measured = []
    for face in faces:
        surface = face["surface"]
        if surface["type"] != "ConicalSurface":
            continue
        points = np.array([s["point"] for s in surface["samples"]]) * 1000
        radii = np.linalg.norm(points[:, :2], axis=1)
        slope, intercept = np.linalg.lstsq(np.column_stack((points[:, 2], np.ones(len(points)))), radii, rcond=None)[0]
        close(float(slope), np.sqrt(3), 1e-10)
        close(float(np.max(np.abs(radii - (slope * points[:, 2] + intercept)))), 0)
        measured.append(float(intercept))
    need(len(measured) == 2, "Missing reopened analytic cone supports")
    close(abs(measured[0] - measured[1]) / 2, 1.5)
    feature_types = {f["name"]: f["type"] for f in native["state"]["features"]}
    need(feature_types.get("VentRingPattern") == "CirPattern" and "NormalVentSeed" in feature_types, "Native circular cut pattern missing")
    return {"passed": True, "cone_mutations": cones, "hole_mutations": holes,
            "native_feature_types": feature_types, "full_release_acceptance": False,
            "limitation": params["limitation"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "results/experimental/solidworks-parametric")
    args = parser.parse_args()
    out = args.output.resolve()
    report = {"schema": "solidworks-parametric-prototype-v1", "baseline_commit": "ad5e7f0",
              "verified_at_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "full_release_acceptance": False, "geometry_tolerance_mm": GEOMETRY_TOL_MM, "parameter_tolerance": PARAMETER_TOL,
              "scope": "Two exact fixed-profile height prototypes and one Studio analytic core/ring prototype"}
    try:
        definition = read(ROOT / "docs/technical/geometry_definition.json")
        report["housings"] = {model: check_housing(out, model, definition["profiles"][model]) for model in ("mac-mini", "mac-studio")}
        report["base"] = check_base(out)
        inputs = [ROOT / "docs/technical/geometry_definition.json", ROOT / "experiments/solidworks-parametric/Prototype.cs",
                  ROOT / "experiments/solidworks-parametric/run.ps1", Path(__file__).resolve(),
                  ROOT / "tools/exact_native/Packet.cs", ROOT / "tools/exact_native/SwSession.cs", ROOT / "tools/exact_native/SwReadback.cs"]
        report["source_sha256"] = {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs}
        report["artifact_sha256"] = {p.name: sha(p) for p in out.iterdir() if p.is_file() and p.suffix.lower() in (".sldprt", ".json") and p.name != "verification.json"}
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    (out / "verification.json").write_text(serialized, encoding="utf-8", newline="\n")
    if out == (ROOT / "results/experimental/solidworks-parametric").resolve():
        Path(__file__).with_name("verification.json").write_text(serialized, encoding="utf-8", newline="\n")
    print(json.dumps({k: report[k] for k in ("passed", "full_release_acceptance", "scope")}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(report["error"])


if __name__ == "__main__":
    main()
