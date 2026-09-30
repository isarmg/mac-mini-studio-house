"""Current analytic outline and smooth source-aperture construction."""
import numpy as np
import cadquery as cq
from OCP.Geom import Geom_BezierCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.gp import gp_Pnt
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge

def bezier(cp):
    poles = TColgp_Array1OfPnt(1, len(cp))
    for i, p in enumerate(cp):
        poles.SetValue(i + 1, gp_Pnt(*map(float, p)))
    return cq.Edge(BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge())

def main_outline(cp, z):
    edges = []
    # Reflect/reverse a fitted quarter, preserving separate source X/Y extents.
    quarters = [cp, cp[::-1] * [1, -1], cp * [-1, -1], cp[::-1] * [-1, 1]]
    for j, q in enumerate(quarters):
        edges.append(bezier(np.c_[q, np.full(len(q), z)]))
        end, start = q[-1], quarters[(j + 1) % 4][0]
        edges.append(cq.Edge.makeLine(cq.Vector(*end, z), cq.Vector(*start, z)))
    return cq.Wire.assembleEdges(edges)

def smooth_wire(points):
    points = np.asarray(points)
    # Remove neighboring duplicate positions, including closure.
    keep = np.linalg.norm(points - np.roll(points, 1, axis=0), axis=1) > 1e-4
    p = points[keep]
    if len(p) < 4:
        raise ValueError("Too few profile points")
    closed = np.vstack([p, p[0]])
    length = np.r_[0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
    distance = np.linspace(0, length[-1], max(128, len(p)), endpoint=False)
    p = np.column_stack([np.interp(distance, length, closed[:, j]) for j in range(3)])
    edge = cq.Edge.makeSpline([cq.Vector(*v) for v in p], periodic=True, tol=1e-7)
    return cq.Wire.assembleEdges([edge])
