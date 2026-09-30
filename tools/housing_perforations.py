"""Verify every current hole axis against analytic cylindrical CAD walls."""
import numpy as np
from scipy.spatial import cKDTree
from OCP.BRepAdaptor import BRepAdaptor_Surface

def validate_cylinder_axes(shape, centers, inward, radii):
    """Every requested axis must have an analytic cylindrical wall after cutting."""
    def key(point, axis):
        axis = np.asarray(axis, dtype=float)
        pivot = np.argmax(np.abs(axis))
        if axis[pivot] < 0:
            axis = -axis
        point = np.asarray(point, dtype=float)
        return np.r_[point - np.dot(point, axis) * axis, axis * 100]

    expected = np.array([key(p, n) for p, n in zip(centers, inward)])
    tree = cKDTree(expected)
    seen = set()
    face_count = 0
    maximum_axis_error = 0.0
    maximum_radius_error = 0.0
    for face in shape.Faces():
        if face.geomType() != "CYLINDER":
            continue
        cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
        axis = cylinder.Axis()
        p, d = axis.Location(), axis.Direction()
        distance, index = tree.query(key([p.X(), p.Y(), p.Z()], [d.X(), d.Y(), d.Z()]))
        if distance > 1e-5:
            continue
        radius_error = abs(cylinder.Radius() - radii[index])
        if radius_error > 1e-6:
            raise ValueError("Cylindrical face radius differs from specification")
        maximum_axis_error = max(maximum_axis_error, float(distance))
        maximum_radius_error = max(maximum_radius_error, float(radius_error))
        seen.add(int(index))
        face_count += 1
    if len(seen) != len(centers):
        raise ValueError(f"Only {len(seen)}/{len(centers)} openings have cylindrical walls")
    return {"expected_holes": len(centers), "verified_unique_cylinder_axes": len(seen),
            "cylindrical_wall_faces": face_count,
            "maximum_axis_key_error": maximum_axis_error,
            "maximum_radius_error_mm": maximum_radius_error}
