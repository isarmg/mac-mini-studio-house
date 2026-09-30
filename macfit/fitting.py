"""Candidate optimization and common-data scoring; test heights do not select models."""

import numpy as np
from scipy.optimize import minimize
from .geometry import knot_spec, make_ctrl, spline, geometry, closest
from .io import stats


def fit_model(name, train, half, tangent_prior, tangent_bounds):
    degree, knots = knot_spec(name)
    count = len(knots) - degree - 1
    dim = count - 4
    th = np.linspace(0.0001, 0.4999, 180)

    def cv(p):
        return spline(name, make_ctrl(p, half, count))

    def fun(p):
        crv = cv(p)
        d, _ = closest(train, crv)
        # Soft-L1, normalized to squared-distance units near zero.
        loss = np.mean(2 * 0.03**2 * (np.sqrt(1 + (d / 0.03) ** 2) - 1))
        k, ks, speed = geometry(crv, th)
        fair = np.trapezoid((ks * half**2) ** 2 * speed / half, th)
        # Broad, weak prior prevents an unidentifiable tangent from running away.
        return loss + 1e-5 * fair + 1e-5 * ((p[0] - tangent_prior) / 3) ** 2

    def con(p):
        k, ks, speed = geometry(cv(p), th)
        return np.r_[k * half, ks * half**2, speed / half - 0.10]

    candidates = []
    for xt in np.linspace(
        tangent_bounds[0] + 0.15 * np.ptp(tangent_bounds),
        tangent_bounds[1] - 0.15 * np.ptp(tangent_bounds),
        3,
    ):
        op = minimize(
            fun,
            np.r_[xt, np.zeros(dim - 1)],
            method="SLSQP",
            bounds=[tuple(tangent_bounds)] + [(-3, 3)] * (dim - 1),
            constraints=[dict(type="ineq", fun=con)],
            options={"maxiter": 250, "ftol": 2e-11},
        )
        crv = cv(op.x)
        k, ks, spd = geometry(crv, np.linspace(0, 0.5, 4001))
        passed = bool(op.success and ks.min() > -1e-8 and k.min() > -1e-9 and spd.min() > 0.01)
        candidates.append((not passed, fun(op.x), op, crv))
    candidates.sort(key=lambda r: (r[0], r[1]))
    bad, loss, op, crv = candidates[0]
    return crv, dict(
        name=name,
        degree=degree,
        knots=knots.tolist(),
        controls_mm=crv.c.tolist(),
        parameters=op.x.tolist(),
        fit_passed=not bad,
        objective=float(loss),
        optimizer_message=str(op.message),
        active_parameter_bounds=[
            i
            for i, x in enumerate(op.x)
            if (i == 0 and min(abs(x - tangent_bounds[0]), abs(x - tangent_bounds[1])) < 0.01)
            or (i > 0 and abs(x) > 2.99)
        ],
        tangent_prior_mm=tangent_prior,
        tangent_bounds_mm=tangent_bounds,
    )


def evaluate(crv, sections, refined=False):
    rows = []
    for sec in sections:
        d, sgn = closest(np.abs(sec["points"]), crv, refined)
        valid = sec["supported"]
        corner = np.abs(sec["points"]).min(axis=1) > sec["corner_threshold"]
        rows.append(
            dict(
                fraction=sec["fraction"],
                role=sec["role"],
                height_mm=sec["height"],
                all_hull=stats(d),
                supported=stats(d[valid]),
                supported_corner=stats(d[valid & corner]),
                unsupported_count=int((~valid).sum()),
                opening_mask_count=int(sec["opening_mask"].sum()),
                unsupported_bridge_count=int((~sec["source_supported"]).sum()),
                corners=[
                    stats(
                        d[
                            valid
                            & corner
                            & (sec["points"][:, 0] * sx >= 0)
                            & (sec["points"][:, 1] * sy >= 0)
                        ]
                    )
                    for sx, sy in [(1, 1), (1, -1), (-1, -1), (-1, 1)]
                ],
            )
        )
    return rows


def aggregate(rows, role, key="supported_corner"):
    rr = [r[key] for r in rows if r["role"] == role]
    return dict(
        rms_mm=float(
            np.sqrt(sum(r["rms_mm"] ** 2 * r["count"] for r in rr) / sum(r["count"] for r in rr))
        ),
        max_mm=max(r["max_mm"] for r in rr),
    )
