"""Train-only low-order height field experiment; writes diagnostics, not new CAD."""

import json
import numpy as np
from scipy.interpolate import BSpline
from scipy.optimize import minimize
from .geometry import closest
from .io import save_json, stats


def check(folder):
    report = json.loads((folder / "optimized_report.json").read_text())
    m = report["model"]
    c = BSpline(m["knots"], np.array(m["controls_mm"]), m["degree"])
    half = report["design_width_mm"] / 2
    data = []
    for row in m["sections"]:
        table = np.loadtxt(folder / f"section_{row['fraction']:.2f}.csv", delimiter=",", skiprows=1)
        p = np.abs(table[table[:, 2] > 0, :2])
        p = p[p.min(axis=1) > 0.38 * half]
        data.append((row["fraction"], row["role"], p))
    results = []
    for degree in [0, 1, 2]:

        def factor(x, h):
            z = (h - 0.5) / 0.4
            offset = 0 if degree == 0 else x[0] * z
            if degree == 2:
                offset += x[1] * (z * z - 1 / 3)
            return 1 + offset / half

        def loss(x):
            ds = []
            for h, role, p in data:
                if role != "train":
                    continue
                sc = factor(x, h)
                d, _ = closest(p / sc, c)
                ds.extend(d * sc)
            d = np.array(ds)
            return np.mean(2 * 0.03**2 * (np.sqrt(1 + (d / 0.03) ** 2) - 1)) + 1e-3 * np.sum(
                np.array(x) ** 2
            )

        if degree:
            op = minimize(
                loss,
                np.zeros(degree),
                method="L-BFGS-B",
                bounds=[(-0.05, 0.05)] * degree,
                options={"ftol": 1e-12, "maxiter": 100},
            )
            x = op.x
        else:
            x = []
        rec = dict(height_degree=degree, halfwidth_offset_coefficients_mm=list(x), roles={})
        for wanted in ["train", "validation", "test"]:
            ds = []
            for h, role, p in data:
                if role != wanted:
                    continue
                sc = factor(x, h)
                d, _ = closest(p / sc, c)
                ds.extend(d * sc)
            rec["roles"][wanted] = stats(np.array(ds))
        results.append(rec)
    baseline = results[0]["roles"]["validation"]
    qualified = [
        r
        for r in results[1:]
        if baseline["rms_mm"] - r["roles"]["validation"]["rms_mm"] >= 0.005
        and r["roles"]["validation"]["max_mm"] <= baseline["max_mm"] + 0.002
    ]
    out = dict(
        candidate_fields=results,
        minimum_required_validation_gain_mm=0.005,
        variable_height_supported=bool(qualified),
        interpretation="Use constant extrusion unless height variation has a material held-out benefit; no physical measurement supplied",
    )
    save_json(folder / "height_dependence.json", out)
    print(folder.name, "height variation justified:", bool(qualified), flush=True)
    return out
