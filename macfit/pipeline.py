"""Reproducible beta fitting pipeline. Baselines come from configs, never old outputs."""

import numpy as np
from . import __version__
from .settings import PROTOCOL, PROFILES, environment_info
from .io import read_usd, save_json
from .geometry import opening_loops, section, mask_openings, spline, closest, geometry
from .fitting import fit_model, evaluate, aggregate
from .cad import export


def run_model(model, input_dir, output_root):
    profile = PROFILES[model]
    OUT = output_root / profile["output_folder"]
    OUT.mkdir(exist_ok=True, parents=True)
    old = dict(
        control_points_mm=profile["baseline_control_points_mm"],
        design_width_mm=profile["design_width_mm"],
    )
    nominal = profile["nominal_width_mm"]
    shell = profile["shell_leaf"]
    oldctrl = np.array(old["control_points_mm"])
    half = old["design_width_mm"] / 2
    audit, meshes, up, planar = read_usd(input_dir / profile["input_file"])
    if audit["sha256"] != profile["source_sha256"]:
        raise ValueError("Source SHA-256 differs from the versioned model profile")
    if up != 1:
        raise ValueError("This beta supports only the profiled Y-up source models")
    save_json(OUT / "usd_audit.json", audit)
    v, counts, indices, meta = next(m for k, m in meshes.items() if k.endswith("/" + shell))
    if (
        meta["subdivision"] != "none"
        or meta["holes"]
        or meta["time_samples"]
        or meta["visible"] == "invisible"
    ):
        raise ValueError("Unexpected source topology")
    center = (v[:, [0, 2]].min(0) + v[:, [0, 2]].max(0)) / 2
    low, high = v[:, 1].min(), v[:, 1].max()
    loops, rims = opening_loops(v, counts, indices)
    # Explicit policy from the user: ignore top/bottom and circular base effects.
    margin = PROTOCOL["end_margin_fraction"]
    core_low, core_high = low + margin * (high - low), low + (1 - margin) * (high - low)
    if len(loops) != profile["expected_openings"] or len(rims) != 2:
        raise ValueError("Unexpected source opening/rim count")
    save_json(
        OUT / "opening_boundaries.json",
        dict(
            weld_tolerance_mm=10 ** (-PROTOCOL["weld_decimals_mm"]),
            guard_band_mm=PROTOCOL["opening_guard_mm"],
            rim_count=len(rims),
            opening_or_panel_boundary_count=len(loops),
            boundaries_world_mm=[x.tolist() for x in loops],
        ),
    )
    sections = []
    for fraction in sorted(
        PROTOCOL["train_heights"] + PROTOCOL["validation_heights"] + PROTOCOL["test_heights"]
    ):
        sec = section(v, counts, indices, low + (high - low) * fraction, center)
        sec["fraction"] = fraction
        sec["role"] = (
            "train"
            if fraction in PROTOCOL["train_heights"]
            else ("validation" if fraction in PROTOCOL["validation_heights"] else "test")
        )
        sec["source_supported"] = sec["supported"].copy()
        sec["opening_mask"] = mask_openings(sec["points"], sec["height"], loops, center)
        sec["supported"] &= ~sec["opening_mask"]
        sec["corner_threshold"] = PROTOCOL["corner_threshold_halfwidth_ratio"] * half
        np.savetxt(
            OUT / f"section_{fraction:.2f}.csv",
            np.c_[sec["points"], sec["supported"], sec["gap"], sec["opening_mask"]],
            delimiter=",",
            header="u_mm,v_mm,valid_exterior,source_gap_mm,opening_guard_mask",
            comments="",
        )
        sections.append(sec)
    train = np.vstack(
        [np.abs(s["points"][s["supported"]]) for s in sections if s["role"] == "train"]
    )
    # Equally spaced data; real port edges remain excluded by exterior-envelope construction.
    train = train[np.abs(train).min(axis=1) > PROTOCOL["train_threshold_halfwidth_ratio"] * half][
        ::2
    ]
    models = []
    curves = {}
    baseline = spline("bezier7", oldctrl)
    b = dict(
        name="previous",
        degree=7,
        knots=baseline.t.tolist(),
        controls_mm=oldctrl.tolist(),
        fit_passed=True,
    )
    b["sections"] = evaluate(baseline, sections)
    models.append(b)
    curves["previous"] = baseline
    for name in PROTOCOL["candidate_names"]:
        print("Fitting", name, flush=True)
        prior = profile["tangent_prior_mm"]
        bounds = profile["tangent_bounds_mm"]
        crv, record = fit_model(name, train, half, prior, bounds)
        record["sections"] = evaluate(crv, sections)
        models.append(record)
        curves[name] = crv
        print(name, record["fit_passed"], aggregate(record["sections"], "validation"), flush=True)
    for model in models:
        for role in ["train", "validation", "test"]:
            model[role] = aggregate(model["sections"], role)
        if model["name"] != "previous":
            model["movement_from_previous_max_mm"] = float(
                closest(baseline(np.linspace(0, 1, 3001)), curves[model["name"]])[0].max()
            )
    # Test data do not participate in selection. Prefer fewer CVs within 1% of best RMS.
    eligible = [
        m
        for m in models
        if m["fit_passed"]
        and m.get("movement_from_previous_max_mm", 0) < PROTOCOL["maximum_baseline_movement_mm"]
        and m["validation"]["max_mm"]
        <= b["validation"]["max_mm"] + PROTOCOL["maximum_validation_regression_mm"]
    ]
    best = min(m["validation"]["rms_mm"] for m in eligible)
    eligible = [
        m
        for m in eligible
        if m["validation"]["rms_mm"] <= best * (1 + PROTOCOL["model_selection_relative_margin"])
    ]
    selected = min(
        eligible, key=lambda m: (len(m["controls_mm"]), m["degree"], m["validation"]["rms_mm"])
    )
    crv = curves[selected["name"]]
    # Higher precision final evaluation, including all gaps (reported but not used to fit).
    selected["sections"] = evaluate(crv, sections, True)
    for role in ["train", "validation", "test"]:
        selected[role] = aggregate(selected["sections"], role)
    t = np.linspace(0, 1, 10001)
    k, ks, spd = geometry(crv, t)
    save_json(OUT / "model_comparison.json", models)
    report = dict(
        version=__version__,
        schema_version=1,
        protocol=PROTOCOL,
        selected_model=selected["name"],
        source_sha256=audit["sha256"],
        shell_prim=meta["path"],
        design_width_mm=2 * half,
        nominal_width_mm=nominal,
        nominal_xy_scale=nominal / (2 * half),
        source_shell_height_mm=float(high - low),
        core_height_mm=float(core_high - core_low),
        core_world_y_bounds_mm=[float(core_low), float(core_high)],
        excluded_shell_height_fraction=[0, margin, 1 - margin, 1],
        opening_boundary_count=len(loops),
        center_world_xz_mm=center.tolist(),
        selection_rule="validation only; 1 percent relative RMS simplicity margin; movement < 0.15 mm",
        source_support_tolerance_mm=PROTOCOL["support_tolerance_mm"],
        model=selected,
        g3=dict(
            endpoint_kappa=k[[0, -1]].tolist(),
            endpoint_dk_ds=ks[[0, -1]].tolist(),
            minimum_speed=float(spd.min()),
            minimum_radius_mm=float(1 / k.max()),
            half_monotonic_sampled=bool(ks[:5001].min() >= -1e-8),
        ),
        limits=[
            "No new physical measurements",
            "Top/bottom 10 percent and circular base excluded",
            "Mid-sidewall is an UNTRIMMED reference extrusion",
            "Openings masked from fit; source boundaries exported separately, not boolean-cut",
            "No top plane, bottom, circular base or unresolved transition reconstructed",
        ],
    )
    save_json(OUT / "optimized_report.json", report)
    np.savetxt(OUT / "control_points_mm.csv", crv.c, delimiter=",", header="u_mm,v_mm", comments="")
    mid = next(s for s in sections if s["fraction"] == 0.5)
    export(
        crv,
        core_high - core_low,
        1,
        OUT / "optimized_sidewall_raw.3dm",
        mid["hull"],
        loops,
        center,
        core_low,
    )
    export(
        crv,
        core_high - core_low,
        nominal / (2 * half),
        OUT / "optimized_sidewall_nominal.3dm",
        mid["hull"],
        loops,
        center,
        core_low,
    )
    save_json(OUT / "run_info.json", environment_info(audit, profile))
    print("SELECTED", selected["name"], selected["validation"], selected["test"], flush=True)
    return report
