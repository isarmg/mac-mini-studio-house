"""Numerical, aperture-mask and Rhino round-trip acceptance checks."""

import json
import numpy as np
from scipy.interpolate import BSpline
from scipy.spatial import cKDTree
from .geometry import geometry, closest, mask_openings
from .io import save_json
from . import reference_cad_path


def verify_model(folder, write_report=False):
    if not __debug__:
        raise RuntimeError("Verification requires Python without -O")
    import rhino3dm as r

    report = json.loads((folder / "optimized_report.json").read_text())
    model = report["model"]
    curve = BSpline(np.array(model["knots"]), np.array(model["controls_mm"]), model["degree"])
    tt = np.linspace(0, 1, 16001)
    k, ks, speed = geometry(curve, tt)
    assert speed.min() > 0.01 and k.min() > -1e-10
    assert np.max(np.abs(k[[0, -1]])) < 1e-11
    assert np.max(np.abs(ks[[0, -1]])) < 1e-11
    assert ks[:8001].min() > -1e-8
    assert np.abs(curve(tt) - curve(1 - tt)[:, ::-1]).max() < 1e-9
    # Verify derivative on both sides of internal knots, not by differentiating mesh data.
    for knot in np.unique(curve.t[(curve.t > 0) & (curve.t < 1)]):
        for order in range(4):
            lhs = curve(knot - 1e-9, nu=order)
            rhs = curve(knot + 1e-9, nu=order)
            assert np.linalg.norm(lhs - rhs) < 1e-3
    t = np.linspace(0.02, 0.98, 80)
    eps = 1e-6
    numeric = (
        (geometry(curve, t + eps)[0] - geometry(curve, t - eps)[0])
        / (2 * eps)
        / geometry(curve, t)[2]
    )
    assert np.abs(numeric - geometry(curve, t)[1]).max() < 1e-8
    # Independent dense closest-distance bound.
    rng = np.random.default_rng(51)
    q = curve(rng.uniform(0.01, 0.99, 32)) + rng.normal(0, 0.07, (32, 2))
    d, _ = closest(q, curve, True)
    a = curve(1)[0]
    xt = curve(0)[0]
    line = np.c_[np.linspace(0, xt, 100001), np.full(100001, a)]
    cloud = np.vstack([curve(np.linspace(0, 1, 200001)), line, line[:, ::-1]])
    reference = cKDTree(cloud).query(q)[0]
    assert np.abs(d - reference).max() < 0.0005
    # Source and opening masks apply to both fitting and scoring points.
    masked = 0
    for row in model["sections"]:
        assert 0.10 < row["fraction"] < 0.90
        table = np.loadtxt(folder / f"section_{row['fraction']:.2f}.csv", delimiter=",", skiprows=1)
        valid = table[:, 2].astype(bool)
        assert np.all(table[valid, 3] <= 0.002000001)
        assert np.all(table[valid, 4] == 0)
        masked += int(table[:, 4].sum())
    assert masked > 0
    boundary = json.loads((folder / "opening_boundaries.json").read_text())
    assert boundary["rim_count"] == 2
    assert boundary["opening_or_panel_boundary_count"] == report["opening_boundary_count"]
    # Synthetic aperture: keep real exterior, reject interior and guard band.
    hole = np.array([[-1, -1, 10], [1, -1, 10], [1, 1, 10], [-1, 1, 10]])
    mask = mask_openings(np.array([[0, 10], [1.1, 10], [2, 10], [0, -10]]), 0, [hole], np.zeros(2))
    assert mask.tolist() == [True, True, False, False]
    for file, scale in [
        ("optimized_sidewall_raw.3dm", 1),
        ("optimized_sidewall_nominal.3dm", report["nominal_xy_scale"]),
    ]:
        doc = r.File3dm.Read(str(reference_cad_path(folder,file)))
        assert doc.Settings.ModelUnitSystem == r.UnitSystem.Millimeters
        assert len(doc.Objects) == 3 + report["opening_boundary_count"]
        outline = doc.Objects[0].Geometry
        assert outline.IsClosed and outline.IsValid and outline.SegmentCount == 8
        sidewall = doc.Objects[1].Geometry
        assert sidewall.IsValid and not sidewall.IsSolid
        for j in range(4):
            c = outline.SegmentCurve(2 * j)
            assert c.Degree == curve.k
        first = outline.SegmentCurve(0)
        for u in np.linspace(0, 1, 31):
            p = first.PointAt(float(u))
            expect = curve(u) * scale
            assert np.linalg.norm(np.array([p.X, p.Y]) - expect) < 1e-8
        # Sidewall height preserves only the selected middle band.
        bbox = sidewall.GetBoundingBox()
        assert abs((bbox.Max.Z - bbox.Min.Z) - report["core_height_mm"]) < 1e-8
        for obj in doc.Objects:
            assert obj.Geometry.IsValid
        # Every source opening is exported as a closed reference polyline.
        for obj in list(doc.Objects)[2 : 2 + report["opening_boundary_count"]]:
            assert obj.Geometry.IsClosed
    result = dict(
        model=folder.name,
        G3_endpoints=True,
        internal_C3=True,
        half_monotonic_sampled=True,
        symmetry=True,
        analytic_derivative=True,
        projection_crosscheck=True,
        opening_mask_and_guard=True,
        top_bottom_band_excluded=True,
        three_dimensional_roundtrip=True,
        opening_boundaries=report["opening_boundary_count"],
    )
    if write_report:
        save_json(folder / "verification.json", result)
    return result
