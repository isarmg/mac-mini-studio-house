"""Source topology, aperture masking and regular G3 spline geometry."""

from collections import Counter, defaultdict
import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from scipy.spatial import ConvexHull, cKDTree
from matplotlib.path import Path as PolygonPath
from .settings import PROTOCOL
from .io import resample


def segment_distance(points, segments):
    a, b = segments[:, 0], segments[:, 1]
    v = b - a
    delta = points[:, None, :] - a[None, :, :]
    t = np.clip(np.sum(delta * v, axis=2) / np.maximum(np.sum(v * v, axis=1), 1e-24), 0, 1)
    return np.linalg.norm(delta - t[:, :, None] * v, axis=2).min(axis=1)


def opening_loops(v, counts, indices):
    """Weld duplicate positions only for topology, then trace degree-two boundaries."""
    rounded, first, inv = np.unique(
        np.round(v, PROTOCOL["weld_decimals_mm"]), axis=0, return_index=True, return_inverse=True
    )
    welded = v[first]
    edges = Counter()
    pos = 0
    for n in counts:
        f = inv[indices[pos : pos + n]]
        pos += n
        edges.update(tuple(sorted((int(a), int(b)))) for a, b in zip(f, np.roll(f, -1)) if a != b)
    graph = defaultdict(set)
    for (a, b), num in edges.items():
        if num == 1:
            graph[a].add(b)
            graph[b].add(a)
    if any(len(neighbors) != 2 for neighbors in graph.values()):
        raise ValueError("Branched/open mesh boundary requires inspection")
    unused = set(graph)
    loops = []
    rims = []
    while unused:
        start = min(unused)
        ordered = [start]
        previous = None
        current = start
        while True:
            nxt = next(x for x in sorted(graph[current]) if x != previous)
            if nxt == start:
                break
            ordered.append(nxt)
            previous, current = current, nxt
            if len(ordered) > len(graph):
                raise ValueError("Boundary cycle failure")
        unused -= set(ordered)
        points = welded[ordered]
        if (
            np.ptp(points[:, 1]) < 0.01
            and min(
                abs(points[:, 1].mean() - v[:, 1].min()), abs(points[:, 1].mean() - v[:, 1].max())
            )
            < 0.02
        ):
            rims.append(points)
        else:
            loops.append(points)
    return loops, rims


def mask_openings(points, height, loops, center, margin=PROTOCOL["opening_guard_mm"]):
    """Projected aperture masks include a guard band; never substitute a fill surface."""
    reject = np.zeros(len(points), dtype=bool)
    for loop in loops:
        # A sidewall opening has one approximately constant horizontal coordinate.
        constant = 0 if np.ptp(loop[:, 0]) < np.ptp(loop[:, 2]) else 2
        horizontal = 2 if constant == 0 else 0
        hi = 0 if horizontal == 0 else 1
        ci = 0 if constant == 0 else 1
        uv = loop[:, [horizontal, 1]].astype(float)
        uv[:, 0] -= center[hi]
        query = np.c_[points[:, hi], np.full(len(points), height)]
        inside = PolygonPath(np.vstack([uv, uv[0]])).contains_points(query)
        boundary = (
            segment_distance(query, np.stack([uv, np.roll(uv, -1, axis=0)], axis=1)) <= margin
        )
        same_side = np.sign(points[:, ci]) == np.sign(loop[:, constant].mean() - center[ci])
        reject |= (inside | boundary) & same_side
    return reject


def section(v, counts, indices, height, center):
    """Polygon/plane segments with face provenance; no arbitrary triangulation."""
    segments, face_ids = [], []
    pos = 0
    for fi, n in enumerate(counts):
        face = v[indices[pos : pos + n]]
        pos += n
        d = face[:, 1] - height
        hits = []
        for j in range(n):
            k = (j + 1) % n
            if d[j] * d[k] < 0:
                t = d[j] / (d[j] - d[k])
                hits.append(face[j] + t * (face[k] - face[j]))
            elif abs(d[j]) < 1e-9:
                hits.append(face[j])
        if len(hits) >= 2:
            hits = np.unique(np.round(hits, 10), axis=0)
            if len(hits) == 2:
                segments.append(hits[:, [0, 2]] - center)
                face_ids.append(fi)
    seg = np.array(segments)
    pts = np.unique(seg.reshape(-1, 2), axis=0)
    hull = pts[ConvexHull(pts).vertices]
    sample = resample(hull, PROTOCOL["section_sample_count"])
    gap = segment_distance(sample, seg)
    supported = gap <= PROTOCOL["support_tolerance_mm"]
    return dict(
        height=height,
        hull=hull,
        segments=seg,
        face_ids=face_ids,
        points=sample,
        supported=supported,
        gap=gap,
    )


def knot_spec(name):
    if name == "quintic_C3":
        return 5, np.r_[np.zeros(6), 0.5, 0.5, np.ones(6)]
    p = int(name.replace("bezier", ""))
    return p, np.r_[np.zeros(p + 1), np.ones(p + 1)]


def make_ctrl(params, half, count):
    # First and last four CVs lie on the corresponding tangent lines.
    xt = params[0]
    r = np.cumsum(softmax(np.r_[params[1:], 0]))[:-1]
    x = np.r_[xt, xt + (half - xt) * r, np.full(4, half)]
    assert len(x) == count
    return np.c_[x, x[::-1]]


def spline(name, ctrl):
    degree, knots = knot_spec(name)
    return BSpline(knots, ctrl, degree, extrapolate=False)


def geometry(curve, t):
    d, dd, ddd = [curve(t, nu=i) for i in (1, 2, 3)]
    speed = np.linalg.norm(d, axis=1)
    c = d[:, 0] * dd[:, 1] - d[:, 1] * dd[:, 0]
    cp = d[:, 0] * ddd[:, 1] - d[:, 1] * ddd[:, 0]
    k = -c / speed**3
    ks = -(cp / speed**4 - 3 * c * np.sum(d * dd, axis=1) / speed**6)
    return k, ks, speed


def closest(points, curve, refined=False):
    grid = np.linspace(0, 1, 257)
    idx = cKDTree(curve(grid)).query(points)[1]
    t = grid[idx]
    for _ in range(7):
        c, d, dd = [curve(t, nu=k) for k in range(3)]
        den = np.sum(d * d + (c - points) * dd, axis=1)
        step = np.sum((c - points) * d, axis=1) / np.maximum(den, 1e-15)
        t = np.clip(t - np.clip(step, -0.03, 0.03), 0, 1)
    if refined:
        for j, i in enumerate(idx):
            lo, hi = grid[max(0, i - 2)], grid[min(256, i + 2)]
            fun = lambda u: float(np.sum((curve(u) - points[j]) ** 2))
            op = minimize_scalar(fun, bounds=(lo, hi), method="bounded", options={"xatol": 1e-13})
            t[j] = min([lo, hi, op.x], key=fun)
    c = curve(t)
    a, xt = curve(1)[0], curve(0)[0]
    top = np.c_[np.clip(points[:, 0], 0, xt), np.full(len(points), a)]
    side = np.c_[np.full(len(points), a), np.clip(points[:, 1], 0, xt)]
    choices = np.stack([c, top, side], axis=1)
    lengths = np.linalg.norm(choices - points[:, None, :], axis=2)
    winner = lengths.argmin(axis=1)
    nearest = choices[np.arange(len(points)), winner]
    delta = points - nearest
    # Radial sign is used only for residual maps / low-order height correction.
    sign = np.sign(np.sum(delta * nearest, axis=1))
    return lengths.min(axis=1), sign * lengths.min(axis=1)
