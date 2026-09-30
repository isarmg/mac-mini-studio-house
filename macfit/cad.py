"""Exact Rhino curves, untrimmed reference sidewalls and source opening boundaries."""

import numpy as np
from scipy.interpolate import BSpline


def rhino_curve(crv):
    import rhino3dm as r

    count = len(crv.c)
    curve = r.NurbsCurve(3, False, crv.k + 1, count)
    for i, (x, y) in enumerate(crv.c):
        curve.Points[i] = r.Point4d(float(x), float(y), 0, 1)
    for i, val in enumerate(crv.t[1:-1]):
        curve.Knots[i] = float(val)
    return curve


def export(crv, height, scale, filename, reference, loops, center, bottom):
    import rhino3dm as r

    doc = r.File3dm()
    doc.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
    doc.Settings.ModelAbsoluteTolerance = 0.001
    for name, color in [
        ("Optimized_G3_outline", (20, 100, 210, 255)),
        ("Sidewall_NURBS", (90, 170, 220, 255)),
        ("Opening_boundaries_REFERENCE", (220, 50, 40, 255)),
        ("Source_reference", (180, 100, 30, 255)),
    ]:
        layer = r.Layer()
        layer.Name = name
        layer.Color = color
        doc.Layers.Add(layer)
    outline = r.PolyCurve()
    for q in range(4):
        a = -q * np.pi / 2
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        cp = crv.c @ rot.T * scale
        curve = rhino_curve(BSpline(crv.t, cp, crv.k))
        outline.Append(curve)
        end = cp[-1]
        a2 = a - np.pi / 2
        rot2 = np.array([[np.cos(a2), -np.sin(a2)], [np.sin(a2), np.cos(a2)]])
        start = crv.c[0] @ rot2.T * scale
        outline.Append(r.LineCurve(r.Point3d(*end, 0), r.Point3d(*start, 0)))
    attr = r.ObjectAttributes()
    attr.LayerIndex = 0
    attr.Name = "optimized_closed_G3_outline"
    doc.Objects.AddCurve(outline, attr)
    extrusion = r.Extrusion.Create(outline, float(height), False)
    if extrusion is None or not extrusion.IsValid:
        raise ValueError("Invalid sidewall")
    attr = r.ObjectAttributes()
    attr.LayerIndex = 1
    attr.Name = "UNTRIMMED_mid_sidewall_REFERENCE_not_a_finished_housing"
    doc.Objects.AddExtrusion(extrusion, attr)
    for j, loop in enumerate(loops):
        cp = loop[:, [0, 2, 1]].copy()
        cp[:, :2] = (cp[:, :2] - center) * scale
        cp[:, 2] -= bottom
        attr = r.ObjectAttributes()
        attr.LayerIndex = 2
        attr.Name = f"opening_{j+1:02d}_source_boundary_reference"
        doc.Objects.AddCurve(
            r.PolylineCurve([r.Point3d(*xyz) for xyz in np.vstack([cp, cp[0]])]), attr
        )
    attr = r.ObjectAttributes()
    attr.LayerIndex = 3
    attr.Name = "raw_midheight_reference_unscaled"
    doc.Objects.AddCurve(
        r.PolylineCurve(
            [
                r.Point3d(float(x), float(y), float(height) / 2)
                for x, y in np.vstack([reference, reference[0]])
            ]
        ),
        attr,
    )
    if not doc.Write(str(filename), 8):
        raise IOError(filename)
