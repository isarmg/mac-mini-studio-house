"""Uniform Mini exhaust-style capsule openings, cut along the cone normal.

Only the 36 source mouths closest to the rear are used to estimate a common
stadium. The final manufacturing feature has two exact semicircles and two
straight edges; source mesh polygons and inlet baffles are not copied.
"""

from collections import Counter
from functools import lru_cache
from pathlib import Path
import hashlib
import numpy as np
from scipy.optimize import least_squares

from . import ROOT
from .specs import source_report
from .usd import read_usd


@lru_cache(maxsize=1)
def fit_source_capsules():
    from .source_features import boundaries

    report = source_report("mac-mini")
    path = ROOT / "data/input/mac-mini-silver.usdz"
    audit, meshes, _, _ = read_usd(path)
    if audit["sha256"] != report["source_sha256"]:
        raise ValueError("Mini source SHA differs from the calibrated model")
    vertices, counts, indices, _ = list(meshes.values())[6]
    loops = boundaries(vertices[:, [0, 2, 1]], counts, indices)
    records = []
    for index, raw in enumerate(loops):
        span = np.ptp(raw, axis=0)
        if not (4 < span[2] < 6.5 and max(span[:2]) < 12):
            continue
        points = (raw - [0, 0, report["source_bottom_offset_mm"]]) * report["calibration_xyz"]
        radial = points[:, :2].mean(0)
        radial /= np.linalg.norm(radial)
        tangent = np.array([-radial[1], radial[0]])
        u = points[:, :2] @ tangent
        rz = np.c_[points[:, :2] @ radial, points[:, 2]]
        mean = rz.mean(0)
        _, _, vectors = np.linalg.svd(rz - mean, full_matrices=False)
        axis = vectors[0] * (1 if vectors[0, 1] > 0 else -1)
        v = (rz - mean) @ axis

        def residual(params):
            x, y, radius, straight = params
            return np.hypot(u - x, np.maximum(abs(v - y) - straight / 2, 0)) - radius

        initial = [np.mean(u), np.mean(v), np.ptp(u) / 2, max(.1, np.ptp(v) - np.ptp(u))]
        fit = least_squares(residual, initial,
                            bounds=([-5, -5, .05, .05], [5, 5, 5, 20]),
                            xtol=1e-12, gtol=1e-12, ftol=1e-12)
        center = mean + axis * fit.x[1]
        records.append({
            "source_boundary_index": index,
            "angle_radians": float(np.arctan2(radial[1], radial[0])),
            "width_mm": float(2 * fit.x[2]),
            "length_mm": float(fit.x[3] + 2 * fit.x[2]),
            "center_z_mm": float(center[1]),
            "center_radius_mm": float(center[0]),
            "source_capsule_fit_rms_mm": float(np.sqrt(np.mean(fit.fun ** 2))),
            "source_capsule_fit_max_mm": float(abs(fit.fun).max()),
        })
    if len(records) != 108:
        raise ValueError("Expected 108 Mini source vent mouths")
    # Six rear connector apertures versus three front apertures identify the rear.
    rear_side = Counter(port["side"] for port in report["ports"]).most_common(1)[0][0]
    rear_angle = rear_side * np.pi / 2

    def angular_distance(item):
        return abs(np.angle(np.exp(1j * (item["angle_radians"] - rear_angle))))

    outlets = sorted(records, key=angular_distance)[:36]
    count = len(records)
    angles = np.array([item["angle_radians"] for item in records])
    phase = float(np.angle(np.exp(1j * count * angles).mean()) / count)
    angular_errors = np.angle(np.exp(1j * count * (angles - phase))) / count
    pattern = {
        "source_sha256": audit["sha256"], "source_mesh_index": 6,
        "source_mesh_slots": count, "exhaust_reference_count": len(outlets),
        "exhaust_selection": "Nearest one third of source mouths to the rear connector side",
        "rear_side": rear_side,
        "width_mm": float(np.median([item["width_mm"] for item in outlets])),
        "length_mm": float(np.median([item["length_mm"] for item in outlets])),
        "center_z_mm": float(np.median([item["center_z_mm"] for item in outlets])),
        "phase_radians": phase, "angular_pitch_radians": 2 * np.pi / count,
        "maximum_source_angular_residual_degrees": float(np.degrees(abs(angular_errors).max())),
        "source_mouth_fits": records,
        "exhaust_reference_boundary_indices": [item["source_boundary_index"] for item in outlets],
        "all_vents_use_exhaust_style": True, "inward_inlet_baffles_removed": True,
        "profile": "two exact semicircles joined tangentially by two straight lines",
        "fit_parameters_are_source_estimates_not_factory_metrology": True,
        "algorithm_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return pattern


def make_capsule_cutters(cone, thickness, *, length_mm=None, center_z_mm=None):
    """Return 108 exact capsule prisms and their world-space feature table.

    cone: slope_dr_dz, intercept_radius_mm, z_min_mm, z_max_mm.
    The capsule is defined in the tangent plane at its centre, exactly as a
    normal CNC slot tool profile. Its intersection with the cone is curved.
    """
    import cadquery as cq

    pattern = dict(fit_source_capsules())
    if length_mm is not None:
        pattern["source_estimated_length_mm"] = pattern["length_mm"]
        pattern["length_mm"] = float(length_mm)
    if center_z_mm is not None:
        pattern["source_estimated_center_z_mm"] = pattern["center_z_mm"]
        pattern["center_z_mm"] = float(center_z_mm)
    if length_mm is not None or center_z_mm is not None:
        pattern["design_adjustment"] = "Slots remain wholly on the conical sidewall; neither 1.5 mm planar plate is perforated"
    slope = float(cone["slope_dr_dz"])
    norm = float(np.hypot(1, slope))
    height = pattern["center_z_mm"]
    radius = cone["intercept_radius_mm"] + slope * height
    half_length_z = pattern["length_mm"] / (2 * norm)
    if not (cone["z_min_mm"] < height - half_length_z
            and height + half_length_z < cone["z_max_mm"]):
        raise ValueError("Unified capsule extends beyond the conical vent band")
    tools, rows = [], []
    lead, depth = 2.0, float(thickness) + 4.0
    for index in range(108):
        angle = pattern["phase_radians"] + index * pattern["angular_pitch_radians"]
        radial = np.array([np.cos(angle), np.sin(angle), 0.0])
        tangent = np.array([-np.sin(angle), np.cos(angle), 0.0])
        normal = (radial - [0, 0, slope]) / norm
        generatrix = (slope * radial + [0, 0, 1]) / norm
        center = radius * radial + [0, 0, height]
        plane = cq.Plane(origin=tuple(center + lead * normal),
                         xDir=tuple(tangent), normal=tuple(normal))
        sketch = cq.Workplane(plane).slot2D(pattern["length_mm"], pattern["width_mm"], 90)
        wire = sketch.val()
        types = sorted(edge.geomType() for edge in wire.Edges())
        if types != ["CIRCLE", "CIRCLE", "LINE", "LINE"] or not wire.IsClosed():
            raise ValueError("Capsule is not exactly two arcs and two tangent lines")
        tool = sketch.extrude(-depth).val()
        if len(tool.Solids()) != 1 or not tool.isValid():
            raise ValueError("Invalid capsule prism")
        straight = pattern["length_mm"] - pattern["width_mm"]
        rows.append({"index": index, "angle_radians": angle,
                     "center_mm": center.tolist(), "outward_normal": normal.tolist(),
                     "long_axis": generatrix.tolist(), "tangent": tangent.tolist(),
                     "cap_centers_mm": [(center + sign * straight / 2 * generatrix).tolist()
                                        for sign in (-1, 1)],
                     "cap_radius_mm": pattern["width_mm"] / 2,
                     "width_mm": pattern["width_mm"], "length_mm": pattern["length_mm"],
                     "outside_lead_mm": lead, "total_cut_depth_mm": depth})
        tools.append(tool)
    pattern.update({"holes": rows, "design_thickness_mm": float(thickness),
                    "cone": cone, "cut_direction": "inward local cone normal",
                    "capsule_wire_edge_counts": {"semicircle": 2, "straight": 2},
                    "expected_unique_capsule_cylinder_axes": 216})
    return tools, pattern


def validate_capsule_cylinders(shape, pattern):
    """Match both true semicylindrical end surfaces of every finished slot."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from scipy.spatial import cKDTree

    def key(point, normal, radius):
        normal = np.asarray(normal, float)
        normal /= np.linalg.norm(normal)
        normal *= 1 if normal[np.argmax(abs(normal))] > 0 else -1
        point = np.asarray(point, float)
        anchor = point - np.dot(point, normal) * normal
        return np.r_[anchor, normal * 100, radius]

    expected = [key(point, hole["outward_normal"], hole["cap_radius_mm"])
                for hole in pattern["holes"] for point in hole["cap_centers_mm"]]
    observed = []
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        origin, direction = cylinder.Axis().Location(), cylinder.Axis().Direction()
        observed.append(key([origin.X(), origin.Y(), origin.Z()],
                            [direction.X(), direction.Y(), direction.Z()], cylinder.Radius()))
    if not observed:
        raise ValueError("Finished Mini base has no analytic capsule caps")
    actual = np.unique(np.round(observed, 9), axis=0)
    expected = np.asarray(expected)
    _, indices = cKDTree(actual).query(expected)
    errors = abs(actual[indices] - expected)
    anchor_error = float(np.linalg.norm(errors[:, :3], axis=1).max())
    normal_error = float(np.linalg.norm(errors[:, 3:6], axis=1).max() / 100)
    radius_error = float(errors[:, 6].max())
    if (len(set(indices.tolist())) != 216 or anchor_error > 1e-5
            or normal_error > 1e-8 or radius_error > 1e-7):
        raise ValueError("Uniform Mini capsule surface geometry differs from the feature table")
    return {"passed": True, "verified_unique_capsule_cylinder_axes": 216,
            "observed_unique_cylinder_axes": len(actual),
            "maximum_axis_anchor_error_mm": anchor_error,
            "maximum_direction_error": normal_error,
            "maximum_cap_radius_error_mm": radius_error}
