"""Add a validated inward curve to frozen beta CAD, as separate outputs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from macfit import __version__, FROZEN_RESULTS, reference_cad_path
from macfit.cad import rhino_curve
from macfit.geometry import closest, geometry

import numpy as np
from scipy.interpolate import BSpline, make_interp_spline
import rhino3dm as r

DISTANCE = 2.0
TOLERANCE = 0.000001


def offset_jet(curve, t, distance=DISTANCE):
    """Position and first three derivatives of C + d * right_unit_normal."""
    c, v, a, b, j = [curve(t, nu=order) for order in range(5)]
    dot = lambda x, y: np.sum(x * y, axis=-1, keepdims=True)
    w = dot(v, v)
    w1 = 2 * dot(v, a)
    w2 = 2 * (dot(a, a) + dot(v, b))
    w3 = 2 * (3 * dot(a, b) + dot(v, j))
    h = w**-0.5
    h1 = -0.5 * w**-1.5 * w1
    h2 = 0.75 * w**-2.5 * w1**2 - 0.5 * w**-1.5 * w2
    h3 = -1.875 * w**-3.5 * w1**3 + 2.25 * w**-2.5 * w1 * w2 - 0.5 * w**-1.5 * w3
    tangent_jets = [
        v * h,
        a * h + v * h1,
        b * h + 2 * a * h1 + v * h2,
        j * h + 3 * b * h1 + 3 * a * h2 + v * h3,
    ]
    rotate = lambda p: np.stack([p[..., 1], -p[..., 0]], axis=-1)
    return [base + distance * rotate(tangent) for base, tangent in zip([c, v, a, b], tangent_jets)]


def make_inner(curve, distance=DISTANCE):
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Offset distance must be finite and positive")
    test_t = np.linspace(0, 1, 20001)
    k, _, _ = geometry(curve, test_t)
    regularity = float(np.min(1 - distance * k))
    if regularity <= 0:
        raise ValueError("Offset reaches a curvature singularity")
    ends = offset_jet(curve, np.array([0.0, 1.0]), distance)
    boundary = ([(i, ends[i][0]) for i in range(1, 4)], [(i, ends[i][1]) for i in range(1, 4)])
    target = offset_jet(curve, test_t, distance)[0]
    for count in [33, 65, 129, 257]:
        t = np.linspace(0, 1, count)
        inner = make_interp_spline(t, offset_jet(curve, t, distance)[0], k=7, bc_type=boundary)
        error = float(np.max(np.linalg.norm(inner(test_t) - target, axis=1)))
        if error < TOLERANCE:
            break
    else:
        raise ValueError("Offset spline did not reach tolerance")
    k_inner, ks_inner, speed = geometry(inner, test_t)
    if speed.min() <= 0 or k_inner.min() < -1e-8:
        raise ValueError("Nonregular or nonconvex offset")
    if np.max(np.abs(k_inner[[0, -1]])) > 1e-8 or np.max(np.abs(ks_inner[[0, -1]])) > 1e-8:
        raise ValueError("G3 line-to-corner continuity failed")
    # Independent nearest-distance check against the outer corner and its straight extensions.
    measured_distance, _ = closest(inner(np.linspace(0, 1, 2001)), curve, True)
    distance_error = float(np.max(np.abs(measured_distance - distance)))
    if distance_error > TOLERANCE:
        raise ValueError(f"Nearest distance check failed: {distance_error}")
    if np.max(np.abs(inner(test_t) - inner(1 - test_t)[:, ::-1])) > TOLERANCE:
        raise ValueError("Offset symmetry failed")
    return inner, {
        "distance_mm": float(distance),
        "acceptance_tolerance_mm": TOLERANCE,
        "normal_offset_max_deviation_mm": error,
        "nearest_distance_max_error_mm": distance_error,
        "validation_samples_per_corner": len(test_t),
        "nearest_distance_samples_per_corner": 2001,
        "interpolation_nodes_per_corner": count,
        "minimum_1_minus_distance_times_curvature": regularity,
        "G3_endpoint_curvature_max": float(np.max(np.abs(k_inner[[0, -1]]))),
        "G3_endpoint_curvature_derivative_max": float(np.max(np.abs(ks_inner[[0, -1]]))),
    }


def closed_outline(corner):
    outline = r.PolyCurve()
    for q in range(4):
        a = -q * np.pi / 2
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        segment = BSpline(corner.t, corner.c @ rot.T, corner.k)
        outline.Append(rhino_curve(segment))
        a2 = a - np.pi / 2
        rot2 = np.array([[np.cos(a2), -np.sin(a2)], [np.sin(a2), np.cos(a2)]])
        start = corner(0) @ rot2.T
        end = segment(1)
        outline.Append(r.LineCurve(r.Point3d(*end, 0), r.Point3d(*start, 0)))
    if not outline.IsClosed or not outline.IsValid:
        raise ValueError("Invalid closed inner outline")
    return outline


def add_curve(doc, curve, name, color, distance=None):
    layer = r.Layer()
    layer.Name = name
    layer.Color = color
    index = doc.Layers.Add(layer)
    attr = r.ObjectAttributes()
    attr.LayerIndex = index
    attr.Name = name
    if name.startswith("Inner_offset_"):
        attr.SetUserString("offset_distance_mm", str(DISTANCE if distance is None else distance))
    doc.Objects.AddCurve(curve, attr)


def check_written(path, expected_count, inner, outer, expected_width):
    doc = r.File3dm.Read(str(path))
    if doc is None or len(doc.Objects) != expected_count:
        raise ValueError("CAD roundtrip object count failed")
    actual = list(doc.Objects)[-1].Geometry
    if not actual.IsValid or not actual.IsClosed or actual.SegmentCount != 8:
        raise ValueError("CAD roundtrip closed curve failed")
    max_error = 0.0
    for j in range(4):
        segment = actual.SegmentCurve(2 * j)
        for t in np.linspace(0, 1, 301):
            a, b = segment.PointAt(float(t)), inner.SegmentCurve(2 * j).PointAt(float(t))
            max_error = max(max_error, np.linalg.norm([a.X - b.X, a.Y - b.Y, a.Z - b.Z]))
        end = segment.PointAtEnd
        line = actual.SegmentCurve(2 * j + 1)
        start = line.PointAtStart
        next_start = actual.SegmentCurve((2 * j + 2) % 8).PointAtStart
        if end.DistanceTo(start) > 1e-8 or line.PointAtEnd.DistanceTo(next_start) > 1e-8:
            raise ValueError("Offset join gap")
    bounds = actual.GetBoundingBox()
    width = bounds.Max.X - bounds.Min.X
    if abs(width - expected_width) > 1e-7 or max_error > 1e-8:
        raise ValueError("CAD dimensions/geometry changed on write")
    # The outer curve is unchanged in the compact two-curve document.
    if expected_count == 2 and doc.Objects[0].Geometry.Encode() != outer.Encode():
        raise ValueError("Outer curve changed")
    return {
        "closed": True,
        "segments": actual.SegmentCount,
        "inner_width_mm": width,
        "roundtrip_max_error_mm": float(max_error),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distance",
        type=float,
        default=DISTANCE,
        help="True inward normal offset in mm (default: 2)",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    distance = args.distance
    if not np.isfinite(distance) or distance <= 0:
        raise ValueError("Offset distance must be finite and positive")
    label = f"{distance:g}mm"
    output = (args.output or ROOT / ".tmp" / f"offset-{label}").resolve()
    frozen = FROZEN_RESULTS.resolve()
    if output == frozen or frozen in output.parents:
        raise ValueError("Do not modify the frozen beta results")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Choose an empty output directory")
    output.mkdir(parents=True, exist_ok=True)
    reports = {}
    plot_curves = []
    for model in ["mac-mini", "mac-studio"]:
        source = frozen / model
        report = json.loads((source / "optimized_report.json").read_text(encoding="utf-8"))
        spline = report["model"]
        for units, scale in [("raw", 1.0), ("nominal", report["nominal_xy_scale"])]:
            outer_corner = BSpline(
                spline["knots"], np.array(spline["controls_mm"]) * scale, spline["degree"]
            )
            inner_corner, metrics = make_inner(outer_corner, distance)
            inner = closed_outline(inner_corner)
            original = reference_cad_path(source,f"optimized_sidewall_{units}.3dm")
            doc = r.File3dm.Read(str(original))
            outer = doc.Objects[0].Geometry
            previous_count = len(doc.Objects)
            add_curve(doc, inner, f"Inner_offset_{label}", (20, 175, 80, 255), distance)
            full_path = output / f"{model}_{units}_with_inner_{label}.3dm"
            if not doc.Write(str(full_path), 8):
                raise IOError(full_path)
            expected_width = report["design_width_mm"] * scale - 2 * distance
            metrics["full_model"] = check_written(
                full_path, previous_count + 1, inner, outer, expected_width
            )
            curves_doc = r.File3dm()
            curves_doc.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
            curves_doc.Settings.ModelAbsoluteTolerance = 0.001
            add_curve(curves_doc, outer, "Outer_G3_outline", (20, 100, 210, 255))
            add_curve(curves_doc, inner, f"Inner_offset_{label}", (20, 175, 80, 255), distance)
            curves_path = output / f"{model}_{units}_curves_{label}.3dm"
            if not curves_doc.Write(str(curves_path), 8):
                raise IOError(curves_path)
            metrics["curves_only"] = check_written(curves_path, 2, inner, outer, expected_width)
            metrics["source_3dm_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
            reports[f"{model}_{units}"] = metrics
            if units == "nominal":
                plot_curves.append((model, outer_corner, inner_corner))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 6), constrained_layout=True)
    for ax, (model, outer, inner) in zip(axes, plot_curves):
        for curve, color, legend in [
            (outer, "#1464d2", "Outer outline"),
            (inner, "#14af50", f"Inner offset: {distance:g} mm"),
        ]:
            parts = []
            for q in range(4):
                a = -q * np.pi / 2
                rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
                parts.append(curve(np.linspace(0, 1, 1001)) @ rot.T)
            pts = np.vstack([*parts, parts[0][0:1]])
            ax.plot(pts[:, 0], pts[:, 1], color=color, lw=1.4, label=legend)
        ax.set(aspect="equal", title=model + " / nominal / z = 0", xlabel="mm", ylabel="mm")
        ax.grid(alpha=0.15)
        ax.legend(loc="center")
    fig.savefig(output / f"inner_offset_{label}_preview.png", dpi=180)
    plt.close(fig)
    (output / "verification.json").write_text(
        json.dumps(reports, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
