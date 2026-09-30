"""Build plain solids and shells from the project's shared accepted outline."""

from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
from shared_profiles import profile as shared_profile, binding as shared_profile_binding
from macfit import __version__, FROZEN_RESULTS
from macfit.geometry import closest
from macfit.solid_geometry import main_outline, planar_inner_wire
from macfit.solid_validation import (
    validate_plain_top,
    validate_profile,
    validate_analytic_volume,
    _surface_area,
)

import cadquery as cq
import numpy as np
from scipy.interpolate import BSpline

DIMENSIONS = {"mac-mini": [127.0, 127.0, 50.0], "mac-studio": [197.0, 197.0, 95.0]}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plane_faces(shape, height):
    return [
        face
        for face in shape.Faces()
        if max(abs(face.BoundingBox().zmin - height), abs(face.BoundingBox().zmax - height)) < 1e-5
    ]


def validate(shape, controls, dimensions, thickness):
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise ValueError("Expected one valid solid")
    bounds = shape.BoundingBox()
    actual = np.array([bounds.xlen, bounds.ylen, bounds.zlen])
    error = float(np.max(abs(actual - dimensions)))
    if error > 0.001:
        raise ValueError(f"Nominal dimension mismatch: {actual}")
    if max(abs(bounds.xmin + bounds.xmax), abs(bounds.ymin + bounds.ymax), abs(bounds.zmin)) > 1e-5:
        raise ValueError("Model is not centered on X/Y with base datum Z=0")
    volume = shape.Volume(1e-9)
    if volume <= 0:
        raise ValueError("Nonpositive solid volume")
    top = validate_plain_top(shape, dimensions[2], controls)
    bottom = plane_faces(shape, 0)
    if len(bottom) != 1:
        raise ValueError("Expected one bottom planar face or annular lip")
    side_hole_faces = [
        face for face in shape.Faces() if face.BoundingBox().zlen > 1e-5 and len(face.Wires()) != 1
    ]
    if side_hole_faces:
        raise ValueError("Unexpected opening in an extruded side face")
    record = {
        "valid": True,
        "solid_count": 1,
        "face_count": len(shape.Faces()),
        "measured_dimensions_mm": actual.tolist(),
        "dimension_max_error_mm": error,
        "ocp_volume_estimate_mm3": float(volume),
        "ocp_volume_integration_requested_relative_tolerance": 1e-9,
        "ocp_volume_estimate_use": "Legacy VolumeProperties estimate for same-kernel roundtrip reference only; requested tolerance does not establish accuracy for high-degree trimmed faces",
        "volume_validation": validate_analytic_volume(shape, controls, dimensions[2], thickness),
        "datum": "centered X/Y; lowest plane Z=0",
        "top": top,
        "side_apertures": 0,
        "logo_or_logo_cutout": False,
    }
    if thickness is None:
        if len(bottom[0].Wires()) != 1 or len(shape.Faces()) != 10:
            raise ValueError("Unexpected solid-block topology")
        record.update({"variant": "solid", "internal_cavity": False, "bottom_open": False})
    else:
        ceiling = plane_faces(shape, dimensions[2] - thickness)
        if len(ceiling) != 1 or len(ceiling[0].Wires()) != 1:
            raise ValueError("Wrong interior ceiling or top plate thickness")
        if len(bottom[0].Wires()) != 2 or len(shape.Faces()) != 19:
            raise ValueError("Expected only the designed bottom opening")
        wires = bottom[0].Wires()
        inner = min(wires, key=lambda wire: _surface_area(cq.Face.makeFromWires(wire)))
        points = []
        for edge in inner.Edges():
            for fraction in np.linspace(0, 1, 41):
                point = edge.positionAt(float(fraction))
                points.append([abs(point.x), abs(point.y)])
        outer = BSpline(np.r_[np.zeros(8), np.ones(8)], controls, 7)
        distance, _ = closest(np.array(points), outer, True)
        wall_error = float(np.max(abs(distance - thickness)))
        if wall_error > 0.005:
            raise ValueError(f"Read-back normal wall thickness error: {wall_error}")
        # Bottom and ceiling inner loops must have the same planar contour.
        inner_area = _surface_area(cq.Face.makeFromWires(inner))
        ceiling_area = _surface_area(ceiling[0])
        if abs(inner_area - ceiling_area) > max(1e-4, inner_area * 1e-8):
            raise ValueError("Inner wall changes section between base and ceiling")
        record.update(
            {
                "variant": f"{thickness:g}mm",
                "internal_cavity": True,
                "bottom_open": True,
                "bottom_inner_wire_count": 1,
                "wall_thickness_mm": float(thickness),
                "top_plate_thickness_mm": float(thickness),
                "interior_ceiling_z_mm": float(dimensions[2] - thickness),
                "normal_wall_distance_samples": len(points),
                "normal_wall_maximum_error_mm": wall_error,
                "normal_wall_acceptance_tolerance_mm": 0.005,
                "inner_bottom_ceiling_area_error_mm2": float(abs(inner_area - ceiling_area)),
            }
        )
    return record


def build(model, variant, output, replace=False):
    started = time.time()
    frozen = FROZEN_RESULTS / model
    report_path = frozen / "optimized_report.json"
    source = json.loads(report_path.read_text(encoding="utf-8"))
    definition = source["model"]
    if definition["degree"] != 7 or not np.allclose(
        definition["knots"], np.r_[np.zeros(8), np.ones(8)]
    ):
        raise ValueError("This builder requires the frozen seven-degree Bezier quarter")
    dimensions = DIMENSIONS[model].copy()
    if variant == "1mm-solid":
        dimensions[2] = 1.0
    scale = float(dimensions[0] / source["design_width_mm"])
    controls = np.array(definition["controls_mm"]) * scale
    shared=shared_profile(model)
    if controls.tolist()!=shared['controls_mm']:
        raise ValueError('Fitted curve and shared profile definition disagree')
    profile = validate_profile(controls)
    thickness = None if variant in ("solid", "1mm-solid") else float(variant[:-2])
    folder = output / model / variant
    folder.mkdir(parents=True, exist_ok=True)
    if any(folder.iterdir()) and not replace:
        raise FileExistsError(f"Use --replace to rebuild existing supplement: {folder}")
    height = dimensions[2]
    shape = cq.Solid.extrudeLinear(main_outline(controls, 0), [], (0, 0, height))
    offset = None
    if thickness is not None:
        wire, offset = planar_inner_wire(controls, -1.0, thickness)
        cavity = cq.Solid.extrudeLinear(wire, [], (0, 0, height - thickness + 1.0))
        shape = shape.cut(cavity, tol=1e-6)
    print(model, variant, "writing independent curve extrusion", flush=True)
    original = validate(shape, controls, dimensions, thickness)
    name = f"{model}_{variant}"
    # Procedural authoring writes only a staged BREP master. The shared exact
    # pipeline creates and natively validates all three delivery formats.
    paths = {"brep": folder / f"{name}.brep"}
    if not shape.exportBrep(str(paths["brep"])):
        raise IOError("Failed to write native OCP BREP")
    roundtrips = {}
    for extension, path in paths.items():
        reread = (
            cq.Shape.importBrep(str(path))
            if extension == "brep"
            else cq.importers.importStep(str(path)).val()
        )
        check = validate(reread, controls, dimensions, thickness)
        change = (
            abs(check["ocp_volume_estimate_mm3"] - original["ocp_volume_estimate_mm3"])
            / original["ocp_volume_estimate_mm3"]
        )
        if change > 1e-7:
            raise ValueError(f"{extension}: volume changed on roundtrip by {change}")
        check.update(
            {
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "roundtrip_ocp_volume_estimate_relative_change": change,
            }
        )
        roundtrips[extension] = check
    record = {
        "project": "Unified_G3_CAD",
        "artifact": "Nominal extrusion of this project's frozen side-profile fit",
        "model": model,
        "variant": variant,
        "units": "mm",
        "passed": True,
        "nominal_dimensions_mm": dimensions,
        "wall_thickness_mm": thickness,
        "source_frozen_version": __version__,
        "source_report": report_path.relative_to(ROOT).as_posix(),
        "source_report_sha256": sha256(report_path),
        "source_usdz_sha256": source["source_sha256"],
        "source_curve_model": source["selected_model"],
        "source_curve_controls_mm": definition["controls_mm"],
        "source_curve_knots": definition["knots"],
        "source_curve_degree": definition["degree"],
        "nominal_xy_scale": scale,
        "nominal_curve_controls_mm": controls.tolist(),
        "shared_profile": shared_profile_binding(model),
        "height_rule": ("User-specified 1 mm solid slab" if variant == "1mm-solid"
                        else "User-specified integer-mm overall height: mini 50, studio 95"),
        "construction": "Exact fitted planar outline extruded vertically; optional true normal inner offset and flat top plate",
        "source_openings_included": False,
        "physical_base_geometry_included": False,
        "internal_device_components_included": False,
        "apple_logo_included": False,
        "plain_full_top": True,
        "bottom_open": thickness is not None,
        "original_fit_results_modified": False,
        "profile_validation": profile,
        "inner_offset_validation": offset,
        "analytic_volume": original["volume_validation"]["analytic_derivation"],
        "original_geometry_validation": original,
        "format_roundtrips": roundtrips,
        "readback_acceptance_complete": False,
        "stage": "procedural master; exact three-format acceptance runs before publication",
        "native_master": paths["brep"].name,
        "design_parameters_not_original_wall_metrology": True,
        "manufacturing_release": False,
        "elapsed_seconds": time.time() - started,
    }
    temporary = folder / "parameters.tmp.json"
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(folder / "parameters.json")
    print(model, variant, "MASTER PASS", roundtrips["brep"]["measured_dimensions_mm"], flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=["mac-mini", "mac-studio", "both"], default="both")
    parser.add_argument("--variant", choices=["solid", "1mm-solid", "2mm", "3mm", "all"], default="all")
    parser.add_argument("--output", type=Path, default=ROOT / "results/masters")
    parser.add_argument("--sources-only", action="store_true", help="Write procedural BREP candidates only; never claims final format acceptance")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Rebuild existing supplements; never permits frozen beta output",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    frozen = FROZEN_RESULTS.resolve()
    if output == frozen or frozen in output.parents:
        raise ValueError("Frozen beta results must never be changed")
    if not args.sources_only and output != (ROOT / "results/masters").resolve():
        parser.error("Custom output folders require --sources-only; final publication uses the formal delivery catalog")
    stage_output = output if args.sources_only else ROOT / ".tmp/exact-procedural/nominal-solids"
    records = []
    source_map = {}
    for model in (["mac-mini", "mac-studio"] if args.model == "both" else [args.model]):
        for variant in (["solid", "1mm-solid", "2mm", "3mm"] if args.variant == "all" else [args.variant]):
            if not args.sources_only and (output / model / ("curve-"+variant)).exists() and not args.replace:
                raise FileExistsError("Use --replace to rebuild an existing formal version; replacement occurs only after strict acceptance")
            records.append(build(model, variant, stage_output, args.replace or not args.sources_only))
            name=f"{model}_{variant}.brep"
            source_map[(output/model/("curve-"+variant)/name).relative_to(ROOT).as_posix()] = (stage_output/model/variant/name).relative_to(ROOT).as_posix()
    summary = {
        "project": "Unified_G3_CAD",
        "passed": all(r["passed"] for r in records),
        "models": [
            {
                "model": r["model"],
                "variant": r["variant"],
                "dimensions_mm": r["nominal_dimensions_mm"],
                "parameters": f"{r['model']}/{r['variant']}/parameters.json",
                "analytic_volume_mm3": r["analytic_volume"]["analytic_volume_mm3"],
                "maximum_readback_analytic_volume_relative_error": max(
                    value["volume_validation"]["analytic_vs_ocp_gk_relative_difference"]
                    for value in r["format_roundtrips"].values()
                ),
            }
            for r in records
        ],
    }
    (stage_output / "verification.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    if not args.sources_only:
        sys.path.insert(0,str(ROOT/'tools'))
        from exact_candidates import deliver
        deliver(source_map)


if __name__ == "__main__":
    main()
