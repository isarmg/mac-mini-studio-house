"""Geometric acceptance for the uninterrupted, logo-free enclosure top."""

import numpy as np
import cadquery as cq
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp
from OCP.GeomLib import GeomLib_IsPlanarSurface
from OCP.GProp import GProp_GProps
from scipy.interpolate import BSpline

from .cad import main_outline


def validate_profile(controls):
    """Validate the G3 quarter used to construct the symmetric outer outline.

    The four reflected quarters and intervening straight lines are constructed
    by ``main_outline``. Symmetry here concerns that outline, not the asymmetric
    port locations or the complete perforated housing. Regularity, convexity and
    curvature monotonicity are sampled at 10,001 quarter-curve parameters.
    """
    controls = np.asarray(controls, dtype=float)
    if controls.shape != (8, 2) or not np.all(np.isfinite(controls)):
        raise ValueError("Profile requires eight finite 2D G3 controls")

    symmetry_error = float(np.max(abs(controls - controls[::-1, ::-1])))
    if symmetry_error > 1e-8:
        raise ValueError("Quarter diagonal symmetry failure")
    half_width = float(controls[-1, 0])
    half_depth = float(controls[0, 1])
    if min(half_width, half_depth) <= 0 or abs(half_width - half_depth) > 1e-8:
        raise ValueError("Invalid symmetric outline extents")
    if np.any(controls < 0) or np.any(controls > [half_width, half_depth]):
        raise ValueError("Quarter controls escape the positive outline quadrant")
    if controls[0, 0] <= 0 or controls[-1, 1] <= 0:
        raise ValueError("Missing straight sections between fitted corners")

    curve = BSpline(np.r_[np.zeros(8), np.ones(8)], controls, 7)
    parameters = np.linspace(0, 1, 10001)
    velocity, acceleration, jerk = [curve(parameters, nu=order) for order in (1, 2, 3)]
    speed = np.linalg.norm(velocity, axis=1)
    if speed.min() <= 0:
        raise ValueError("Nonregular quarter curve")
    cross = velocity[:, 0] * acceleration[:, 1] - velocity[:, 1] * acceleration[:, 0]
    cross1 = velocity[:, 0] * jerk[:, 1] - velocity[:, 1] * jerk[:, 0]
    curvature = -cross / speed**3
    curvature_derivative = -(
        cross1 / speed**4
        - 3 * cross * np.sum(velocity * acceleration, axis=1) / speed**6
    )
    if curvature.min() < -1e-9:
        raise ValueError("Nonconvex quarter curve")
    endpoint_curvature = float(max(abs(curvature[[0, -1]])))
    endpoint_curvature_derivative = float(max(abs(curvature_derivative[[0, -1]])))
    endpoint_tangent_error = float(
        max(abs(velocity[0, 1]) / speed[0], abs(velocity[-1, 0]) / speed[-1])
    )
    if endpoint_tangent_error > 1e-10:
        raise ValueError("Quarter tangents do not align with straight outline edges")
    if endpoint_curvature > 1e-9 or endpoint_curvature_derivative > 1e-9:
        raise ValueError("G3 line-corner endpoint failure")
    first_half_minimum = float(curvature_derivative[:5001].min())
    if first_half_minimum < -1e-8:
        raise ValueError("Nonmonotonic half-corner curvature")

    return {
        "passed": True,
        "degree": 7,
        "control_count": 8,
        "sample_count": len(parameters),
        "width_mm": 2 * half_width,
        "depth_mm": 2 * half_depth,
        "center_and_axis_symmetry_by_outline_construction": True,
        "quarter_rotational_symmetry": True,
        "quarter_diagonal_symmetry_error_mm": symmetry_error,
        "regular_convex_main_outline_sampled": True,
        "minimum_speed_mm_per_parameter": float(speed.min()),
        "minimum_curvature_per_mm": float(curvature.min()),
        "G3_line_corner_endpoints": True,
        "maximum_endpoint_tangent_alignment_error": endpoint_tangent_error,
        "maximum_endpoint_curvature_per_mm": endpoint_curvature,
        "maximum_endpoint_curvature_derivative_per_mm2": endpoint_curvature_derivative,
        "half_corner_curvature_monotonic_sampled": True,
        "minimum_first_half_curvature_derivative_per_mm2": first_half_minimum,
        "applies_to_outline_not_port_pattern": True,
    }


def _surface_area(face):
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, properties, 1e-10)
    return float(properties.Mass())


def validate_plain_top(shape, height, controls):
    """Require one full planar top, with one boundary and no logo/other cutouts.

    ``height`` and the symmetric G3 quarter ``controls`` are in calibrated mm.
    Affine calibration can represent a plane as a B-spline surface; the OCP
    planarity predicate checks its geometry rather than its representation tag.
    Raises ValueError on failure and returns a JSON-serializable acceptance record.
    This local face check does not replace the complete solid validity check.
    """
    height = float(height)
    controls = np.asarray(controls, dtype=float)
    if controls.shape != (8, 2) or not np.all(np.isfinite(controls)):
        raise ValueError("Top validation requires eight finite 2D G3 controls")
    if not np.isfinite(height):
        raise ValueError("Nonfinite top height")

    tolerance = 1e-5
    top_faces = []
    for face in shape.Faces():
        bounds = face.BoundingBox()
        if max(abs(bounds.zmin - height), abs(bounds.zmax - height)) <= tolerance:
            top_faces.append(face)
    if len(top_faces) != 1:
        raise ValueError(f"Expected one continuous top face; found {len(top_faces)}")

    top = top_faces[0]
    if not top.isValid():
        raise ValueError("Invalid top face topology")
    wire_count = len(top.Wires())
    if wire_count != 1:
        raise ValueError(
            f"Top must have one outer wire and no holes; found {wire_count}"
        )

    planar = GeomLib_IsPlanarSurface(BRep_Tool.Surface_s(top.wrapped), 1e-8)
    if not planar.IsPlanar():
        raise ValueError("Top surface is not planar")
    plane = planar.Plan()
    normal = plane.Axis().Direction()
    if abs(abs(normal.Z()) - 1.0) > 1e-10:
        raise ValueError("Top plane is not horizontal")
    plane_z_error = abs(plane.Location().Z() - height)
    if plane_z_error > tolerance:
        raise ValueError(f"Top plane height error {plane_z_error} mm")

    expected = cq.Face.makeFromWires(main_outline(controls, height))
    area = _surface_area(top)
    expected_area = _surface_area(expected)
    area_error = abs(area - expected_area)
    area_tolerance = max(1e-5, expected_area * 1e-8)
    if area_error > area_tolerance:
        raise ValueError(f"Top region differs from full G3 outline by {area_error} mm2")

    measured_bounds = top.BoundingBox()
    expected_bounds = expected.BoundingBox()
    bounds_error = max(
        abs(getattr(measured_bounds, field) - getattr(expected_bounds, field))
        for field in ("xmin", "xmax", "ymin", "ymax")
    )
    if bounds_error > tolerance:
        raise ValueError(f"Top extent differs from G3 outline by {bounds_error} mm")
    z_error = max(
        abs(measured_bounds.zmin - height),
        abs(measured_bounds.zmax - height),
        plane_z_error,
    )
    return {
        "passed": True,
        "top_face_count": 1,
        "wire_count": wire_count,
        "inner_wire_count": 0,
        "edge_count": len(top.Edges()),
        "surface_representation": top.geomType(),
        "geometrically_planar": True,
        "horizontal": True,
        "height_mm": height,
        "maximum_height_error_mm": float(z_error),
        "height_tolerance_mm": tolerance,
        "area_mm2": area,
        "full_outline_area_mm2": expected_area,
        "area_error_mm2": area_error,
        "area_tolerance_mm2": area_tolerance,
        "outline_bounds_error_mm": float(bounds_error),
        "apple_logo_and_cutout_absent": True,
    }
