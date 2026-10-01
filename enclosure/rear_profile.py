"""Map the accepted rear pattern arc coordinates onto the shared G3 profile."""
import numpy as np
from scipy.integrate import cumulative_simpson
from scipy.interpolate import PchipInterpolator
from scipy.spatial import cKDTree
from scipy.special import comb

def bezier(controls, parameters):
    t = np.atleast_1d(parameters)
    n = len(controls) - 1
    basis = np.array([comb(n, k) * t**k * (1 - t) ** (n - k) for k in range(n + 1)])
    return basis.T @ controls

class RearProfile:
    """Exact Bezier coordinates, numerically integrated arc length in mm."""

    def __init__(self, controls):
        self.cp = np.asarray(controls) * [1, -1]
        self.dcp = np.diff(self.cp, axis=0) * 7
        self.ddcp = np.diff(self.dcp, axis=0) * 6
        self.flat_half_length = self.cp[0, 0]
        self.parameters = np.linspace(0, 1, 32769)
        self.samples = bezier(self.cp, self.parameters)
        speed = np.linalg.norm(bezier(self.dcp, self.parameters), axis=1)
        self.arc = cumulative_simpson(speed, x=self.parameters, initial=0)
        self.arc += self.flat_half_length
        self.arc_from_t = PchipInterpolator(self.parameters, self.arc)
        self.t_from_arc = PchipInterpolator(self.arc, self.parameters)
        self.tree = cKDTree(self.samples)

    def project(self, xy):
        """Return signed arc coordinate of the closest point on the rear face."""
        xy = np.asarray(xy)
        absolute = xy.copy()
        absolute[:, 0] = abs(absolute[:, 0])
        index = self.tree.query(absolute)[1]
        t = self.parameters[index].copy()
        for _ in range(8):
            delta = bezier(self.cp, t) - absolute
            derivative = bezier(self.dcp, t)
            second = bezier(self.ddcp, t)
            denominator = np.sum(derivative**2 + delta * second, axis=1)
            t -= np.sum(delta * derivative, axis=1) / denominator
            t = np.clip(t, 0, 1)
        arc = self.arc_from_t(t) * np.sign(xy[:, 0])
        flat = absolute[:, 0] <= self.flat_half_length
        arc[flat] = xy[flat, 0]
        return arc

    def evaluate(self, arc):
        """Return exact profile XY and unit tangent along increasing arc length."""
        arc = np.atleast_1d(arc)
        absolute = abs(arc)
        t = self.t_from_arc(np.maximum(absolute, self.flat_half_length))
        xy = bezier(self.cp, t)
        tangent = bezier(self.dcp, t)
        xy[:, 0] *= np.sign(arc)
        tangent[:, 1] *= np.sign(arc)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        flat = absolute <= self.flat_half_length
        xy[flat, 0] = arc[flat]
        xy[flat, 1] = self.cp[0, 1]
        tangent[flat] = [1, 0]
        return xy, tangent

