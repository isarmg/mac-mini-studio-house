"""Independent design volume from the frozen planar Bezier outline.

Green's area integral is polynomial and evaluated by Gaussian quadrature exact
through a degree well above the degree-13 integrand. Arc length uses adaptive
quadrature. For regular inward offsets of a convex C2 boundary, Steiner's
formula gives A_inner = A - t*P + pi*t^2. This reference does not depend on a
CAD kernel's volume integration or the tessellation of an exported file.
"""

import math

import numpy as np
from scipy.integrate import quad
from scipy.interpolate import BSpline
from scipy.optimize import minimize_scalar


def analytic_volume(controls, height, thickness=None):
    """Return the ideal extrusion/normal-offset volume and its derivation.

    The native inner B-spline approximates the mathematical normal offset;
    its separate geometric acceptance record remains necessary. This helper
    validates the convexity and offset regularity needed by Steiner's formula.
    """
    controls = np.asarray(controls, dtype=float)
    height = float(height)
    if controls.shape != (8, 2) or not np.all(np.isfinite(controls)):
        raise ValueError("Expected eight finite planar degree-seven controls")
    if not math.isfinite(height) or height <= 0:
        raise ValueError("Expected positive finite height")
    if np.max(abs(controls - controls[::-1, ::-1])) > 1e-8:
        raise ValueError("Expected the frozen diagonally symmetric quarter")
    curve = BSpline(np.r_[np.zeros(8), np.ones(8)], controls, 7)

    def green_integral(order):
        nodes, weights = np.polynomial.legendre.leggauss(order)
        parameters = (nodes + 1.0) / 2.0
        points = curve(parameters)
        velocity = curve(parameters, nu=1)
        cross = points[:, 0] * velocity[:, 1] - points[:, 1] * velocity[:, 0]
        return float(np.dot(weights, cross) / 2.0)

    # Four clockwise corners plus their four straight connecting segments.
    integral = green_integral(16)
    area = 2.0 * abs(integral - np.prod(controls[0]) - np.prod(controls[-1]))
    area_check = 2.0 * abs(green_integral(32) - np.prod(controls[0]) - np.prod(controls[-1]))
    length, length_error = quad(
        lambda u: float(np.linalg.norm(curve(u, nu=1))),
        0.0,
        1.0,
        epsabs=1e-10,
        epsrel=5e-14,
    )
    perimeter = 4.0 * (controls[0, 0] + controls[-1, 1] + length)

    def curvature(u):
        velocity, acceleration = curve(u, nu=1), curve(u, nu=2)
        cross = velocity[..., 0] * acceleration[..., 1] - velocity[..., 1] * acceleration[..., 0]
        return -cross / np.linalg.norm(velocity, axis=-1) ** 3

    parameters = np.linspace(0.0, 1.0, 10001)
    sampled_curvature = curvature(parameters)
    if sampled_curvature.min() < -1e-9:
        raise ValueError("Steiner inner-area formula requires a convex outline")
    maximum = max(
        float(sampled_curvature.max()),
        -float(minimize_scalar(lambda u: -curvature(u), bounds=(0.0, 1.0), method="bounded").fun),
    )
    radius = 1.0 / maximum
    if thickness is None:
        volume = area * height
        inner_area = None
        rule = "V = A*H"
    else:
        thickness = float(thickness)
        if not math.isfinite(thickness) or not 0 < thickness < min(height, radius):
            raise ValueError("Wall exceeds height or the regular inward-offset radius")
        inner_area = area - thickness * perimeter + math.pi * thickness**2
        if inner_area <= 0:
            raise ValueError("Normal offset collapses the cavity")
        volume = area * thickness + (height - thickness) * (
            thickness * perimeter - math.pi * thickness**2
        )
        rule = "V = t*A + (H-t)*(t*P - pi*t^2)"

    return {
        "analytic_volume_mm3": float(volume),
        "outer_area_mm2": float(area),
        "outer_perimeter_mm": float(perimeter),
        "inner_area_mm2": None if inner_area is None else float(inner_area),
        "height_mm": height,
        "wall_and_top_thickness_mm": thickness,
        "volume_formula": rule,
        "inner_area_formula": "Ai = A - t*P + pi*t^2",
        "area_method": "Green boundary integral; degree-13 polynomial; 16-point Gauss-Legendre quadrature",
        "area_16_vs_32_point_difference_mm2": abs(float(area - area_check)),
        "perimeter_method": "Bezier speed adaptive quadrature plus exact straight segments",
        "perimeter_quadrature_estimated_error_mm": float(4.0 * length_error),
        "minimum_outline_curvature_radius_mm": float(radius),
        "convexity_samples": len(parameters),
        "offset_regularity_verified": thickness is None or thickness < radius,
        "reference": "Ideal extrusion of frozen profile and its mathematical normal offset; native offset approximation is checked separately",
        "independent_of_cad_volume_integration": True,
    }
