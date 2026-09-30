"""Validated physical normal offsets of the symmetric planar G3 enclosure.

The offset is C(t) + thickness * right_unit_normal(t), not a scaled outline.
A degree-seven B-spline approximates that non-polynomial curve to 1e-6 mm;
the public acceptance limit is 0.005 mm. Endpoint derivatives through order
three are constrained so that the line/corner G3 joins are retained.
"""

import numpy as np
import cadquery as cq
from scipy.interpolate import BSpline, make_interp_spline
from scipy.spatial import cKDTree
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal
from OCP.gp import gp_Pnt

from .cad import main_outline

ACCEPTANCE_TOLERANCE_MM = 0.005
FIT_TARGET_MM = 0.000001


def _offset_jets(curve, t, thickness):
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
    rotate_right = lambda p: np.stack([p[..., 1], -p[..., 0]], axis=-1)
    return [
        base + thickness * rotate_right(tangent)
        for base, tangent in zip([c, v, a, b], tangent_jets)
    ]


def _geometry(curve, t):
    v, a, b = [curve(t, nu=k) for k in (1, 2, 3)]
    cross = lambda x, y: x[:, 0] * y[:, 1] - x[:, 1] * y[:, 0]
    speed = np.linalg.norm(v, axis=1)
    curvature = -cross(v, a) / speed**3
    curvature_derivative = (
        -cross(v, b) / speed**4 + 3 * cross(v, a) * np.sum(v * a, axis=1) / speed**6
    )
    return curvature, curvature_derivative, speed


def _nearest_distance(points, outer):
    grid = np.linspace(0, 1, 4001)
    t = grid[cKDTree(outer(grid)).query(points)[1]]
    for _ in range(12):
        delta = outer(t) - points
        v, a = outer(t, nu=1), outer(t, nu=2)
        denominator = np.sum(v * v + delta * a, axis=1)
        if np.any(denominator <= 0):
            raise ValueError("Normal offset leaves the unique closest-point region")
        t = np.clip(t - np.sum(delta * v, axis=1) / denominator, 0, 1)
    distance = np.linalg.norm(outer(t) - points, axis=1)
    first, last = outer(0), outer(1)
    # The corner's adjoining straight segments are part of the distance target.
    distance = np.minimum(
        distance,
        np.where(points[:, 0] <= first[0], abs(points[:, 1] - first[1]), np.inf),
    )
    distance = np.minimum(
        distance, np.where(points[:, 1] <= last[1], abs(points[:, 0] - last[0]), np.inf)
    )
    return distance


def _spline_edge(curve, z, rotation):
    controls = curve.c @ rotation.T
    knots, multiplicities = np.unique(curve.t, return_counts=True)
    poles = TColgp_Array1OfPnt(1, len(controls))
    for i, point in enumerate(controls, start=1):
        poles.SetValue(i, gp_Pnt(float(point[0]), float(point[1]), float(z)))
    occ_knots = TColStd_Array1OfReal(1, len(knots))
    occ_mults = TColStd_Array1OfInteger(1, len(knots))
    for i, (knot, multiplicity) in enumerate(zip(knots, multiplicities), start=1):
        occ_knots.SetValue(i, float(knot))
        occ_mults.SetValue(i, int(multiplicity))
    geometry = Geom_BSplineCurve(poles, occ_knots, occ_mults, curve.k, False)
    edge = cq.Edge(BRepBuilderAPI_MakeEdge(geometry).Edge())
    # Independent read-back evaluation of the OCC curve catches knot/pole errors.
    error = 0.0
    for t in np.linspace(0, 1, 301):
        actual = geometry.Value(float(t))
        expected = curve(t) @ rotation.T
        error = max(
            error, float(np.linalg.norm(np.array([actual.X(), actual.Y()]) - expected))
        )
    if error > 1e-8:
        raise ValueError("OCC spline conversion changed the fitted offset")
    return edge, error


def planar_inner_wire(controls, z, thickness):
    """Return ``(closed_inner_wire, validation_record)`` in calibrated mm.

    ``controls`` is the eight-pole, D4-symmetric quarter used by main_outline.
    Fails rather than returning an invalid, nonconvex or inaccurate offset.
    Four exact integer quarter-turns and one diagonal-symmetric spline ensure
    center symmetry, both axis symmetries, and 90-degree rotational symmetry.
    """
    controls = np.asarray(controls, dtype=float)
    thickness, z = float(thickness), float(z)
    if controls.shape != (8, 2) or not np.all(np.isfinite(controls)):
        raise ValueError("Expected eight finite quarter-profile controls")
    if not np.isfinite(z) or not np.isfinite(thickness) or thickness <= 0:
        raise ValueError("Height must be finite and thickness positive")
    if np.max(abs(controls - controls[::-1, ::-1])) > 1e-8:
        raise ValueError("The input quarter is not diagonally symmetric")
    if thickness >= min(controls[0, 1], controls[-1, 0]):
        raise ValueError("Wall thickness collapses the profile")
    outer = BSpline(np.r_[np.zeros(8), np.ones(8)], controls, 7)
    validation_t = np.linspace(0, 1, 20001)
    curvature, _, speed = _geometry(outer, validation_t)
    regularity = float(np.min(1 - thickness * curvature))
    if speed.min() <= 0 or curvature.min() < -1e-8 or regularity <= 0:
        raise ValueError("Offset reaches a curvature singularity or nonconvex profile")
    endpoint_jets = _offset_jets(outer, np.array([0.0, 1.0]), thickness)
    boundary = (
        [(order, endpoint_jets[order][0]) for order in range(1, 4)],
        [(order, endpoint_jets[order][1]) for order in range(1, 4)],
    )
    target = _offset_jets(outer, validation_t, thickness)[0]
    for node_count in (33, 65, 129, 257, 513):
        t = np.linspace(0, 1, node_count)
        corner = make_interp_spline(
            t, _offset_jets(outer, t, thickness)[0], k=7, bc_type=boundary
        )
        # Uniform symmetric knots permit exact diagonal symmetry at pole level.
        corner = BSpline(corner.t, (corner.c + corner.c[::-1, ::-1]) / 2, corner.k)
        approximation_error = float(
            np.max(np.linalg.norm(corner(validation_t) - target, axis=1))
        )
        if approximation_error <= FIT_TARGET_MM:
            break
    else:
        raise ValueError("Normal-offset interpolation did not reach tolerance")
    k, ks, inner_speed = _geometry(corner, validation_t)
    derivative = corner(validation_t, nu=1)
    if inner_speed.min() <= 0 or k.min() < -1e-8:
        raise ValueError("Nonregular or nonconvex inner corner")
    if derivative[:, 0].min() < -1e-8 or derivative[:, 1].max() > 1e-8:
        raise ValueError("Inner corner is not coordinate-monotone")
    if abs(k[[0, -1]]).max() > 1e-8 or abs(ks[[0, -1]]).max() > 1e-8:
        raise ValueError("Offset lost G3 line/corner joins")
    symmetry_error = float(
        np.max(abs(corner(validation_t) - corner(1 - validation_t)[:, ::-1]))
    )
    distance_error = float(
        np.max(
            abs(_nearest_distance(corner(np.linspace(0, 1, 4001)), outer) - thickness)
        )
    )
    if max(approximation_error, distance_error, symmetry_error) > FIT_TARGET_MM:
        raise ValueError("Independent offset distance or symmetry check failed")
    rotations = np.array(
        [
            [[1, 0], [0, 1]],
            [[0, 1], [-1, 0]],
            [[-1, 0], [0, -1]],
            [[0, -1], [1, 0]],
        ]
    )
    edges, conversion_error = [], 0.0
    for i, rotation in enumerate(rotations):
        edge, error = _spline_edge(corner, z, rotation)
        edges.append(edge)
        conversion_error = max(conversion_error, error)
        end = corner(1) @ rotation.T
        start = corner(0) @ rotations[(i + 1) % 4].T
        if np.linalg.norm(end - start) <= 1e-8:
            raise ValueError("Collapsed straight segment")
        edges.append(cq.Edge.makeLine(cq.Vector(*end, z), cq.Vector(*start, z)))
    wire = cq.Wire.assembleEdges(edges)
    if not wire.IsClosed() or not wire.isValid():
        raise ValueError("Inner offset is not a valid closed wire")
    face = cq.Face.makeFromWires(wire)
    if not face.isValid():
        raise ValueError("Inner offset has invalid planar topology/self-intersection")
    area = face.Area()
    outer_area = cq.Face.makeFromWires(main_outline(controls, z)).Area()
    if not 0 < area < outer_area:
        raise ValueError("Offset did not move inward")
    bounds = wire.BoundingBox()
    expected_width = 2 * (controls[0, 1] - thickness)
    extent_error = max(
        abs(bounds.xlen - expected_width), abs(bounds.ylen - expected_width)
    )
    if extent_error > 1e-5:
        raise ValueError("Inner profile extents do not match the wall thickness")
    return wire, {
        "method": "true inward unit-normal offset, derivative-constrained degree-seven B-spline",
        "thickness_mm": thickness,
        "acceptance_tolerance_mm": ACCEPTANCE_TOLERANCE_MM,
        "fit_target_mm": FIT_TARGET_MM,
        "normal_offset_max_error_mm": approximation_error,
        "nearest_outer_distance_max_error_mm": distance_error,
        "occ_curve_conversion_max_error_mm": conversion_error,
        "symmetry_max_error_mm": symmetry_error,
        "extent_max_error_mm": float(extent_error),
        "minimum_one_minus_thickness_times_curvature": regularity,
        "minimum_inner_speed": float(inner_speed.min()),
        "minimum_inner_curvature": float(k.min()),
        "endpoint_curvature_max": float(abs(k[[0, -1]]).max()),
        "endpoint_curvature_derivative_max": float(abs(ks[[0, -1]]).max()),
        "interpolation_nodes_per_quarter": node_count,
        "validation_samples_per_quarter": len(validation_t),
        "nearest_distance_samples_per_quarter": 4001,
        "closed": True,
        "valid_planar_face": True,
        "self_intersection": False,
        "self_intersection_check": "regular convex monotone quarter, exact D4 joins, valid OCC planar face",
        "symmetry": "D4: center, X/Y axes, diagonals, and 90-degree rotations",
        "inner_width_mm": float(bounds.xlen),
        "inner_depth_mm": float(bounds.ylen),
        "inner_area_mm2": float(area),
    }
