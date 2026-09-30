"""Read saved data and render diagnostics without refitting."""

import json
import numpy as np
from scipy.interpolate import BSpline
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from .geometry import geometry


def plot(folder, case):
    name = folder.name
    report = json.loads((folder / "optimized_report.json").read_text())
    models = json.loads((folder / "model_comparison.json").read_text())
    curves = {
        m["name"]: BSpline(m["knots"], np.array(m["controls_mm"]), m["degree"]) for m in models
    }
    selected = report["selected_model"]
    half = report["design_width_mm"] / 2
    t = np.linspace(0, 1, 2001)
    fig, axs = plt.subplots(2, 2, figsize=(12, 9), layout="constrained")
    for m in models:
        rows = m["sections"]
        axs[0, 0].plot(
            [r["fraction"] for r in rows],
            [r["supported_corner"]["rms_mm"] for r in rows],
            ".-",
            label=m["name"],
        )
    axs[0, 0].set(
        xlabel="Shell height fraction",
        ylabel="Supported corner RMS (mm)",
        title="Same supported data for all models",
    )
    axs[0, 0].legend()
    h = 0.35 if case == "mini" else 0.5
    data = np.loadtxt(folder / f"section_{h:.2f}.csv", delimiter=",", skiprows=1)
    valid = data[:, 2] > 0
    axs[0, 1].scatter(data[valid, 0], data[valid, 1], s=5, label="Source-supported")
    axs[0, 1].scatter(
        data[~valid, 0], data[~valid, 1], s=8, c="red", label="Excluded bridge / opening guard"
    )
    axs[0, 1].set(
        xlim=(18, 45) if case == "mini" else (-0.95 * half, 0.95 * half),
        ylim=(-half - 1, -half + (3.5 if case == "mini" else 8)),
        xlabel="u (mm)",
        ylabel="v (mm)",
        title=f"{h:.0%} section: explicit missing-data mask",
    )
    axs[0, 1].legend(fontsize=8)
    for nm in dict.fromkeys(["previous", selected]):
        c = curves[nm]
        k, ks, _ = geometry(c, t)
        arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(c(t), axis=0), axis=1))]
        axs[1, 0].plot(arc, k, label=nm)
        axs[1, 1].plot(arc, ks, label=nm)
    axs[1, 0].set(xlabel="Arc length (mm)", ylabel="Curvature (1/mm)", title="Curvature")
    axs[1, 0].legend()
    axs[1, 1].set(
        xlabel="Arc length (mm)", ylabel="d curvature / ds (1/mm^2)", title="Curvature variation"
    )
    axs[1, 1].legend()
    fig.savefig(folder / "comparison.png", dpi=170)
    plt.close(fig)
    c = curves[selected]
    height = report["core_height_mm"]
    center = np.array(report["center_world_xz_mm"])
    fig = plt.figure(figsize=(10, 7), layout="constrained")
    ax = fig.add_subplot(111, projection="3d")
    for q in range(4):
        a = -q * np.pi / 2
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        xy = c(t[::20]) @ rot.T
        for z in [0, height]:
            ax.plot(xy[:, 0], xy[:, 1], np.full(len(xy), z), color="#2676bd")
        a2 = a - np.pi / 2
        r2 = np.array([[np.cos(a2), -np.sin(a2)], [np.sin(a2), np.cos(a2)]])
        pair = np.array([c(1) @ rot.T, c(0) @ r2.T])
        for z in [0, height]:
            ax.plot(pair[:, 0], pair[:, 1], [z, z], color="#2676bd")
        for pt in [xy[0], xy[-1]]:
            ax.plot([pt[0]] * 2, [pt[1]] * 2, [0, height], color="#8ab6de", lw=0.7)
    holes = json.loads((folder / "opening_boundaries.json").read_text())["boundaries_world_mm"]
    for hole in holes:
        p = np.array(hole)[:, [0, 2, 1]]
        p[:, :2] -= center
        p[:, 2] -= report["core_world_y_bounds_mm"][0]
        p = np.vstack([p, p[0]])
        ax.plot(p[:, 0], p[:, 1], p[:, 2], color="#d84135", lw=1)
    ax.set(
        xlabel="u (mm)",
        ylabel="v (mm)",
        zlabel="Height from retained band bottom (mm)",
        title=name
        + " | mid-sidewall and SOURCE opening boundaries\nReference surface; openings are not boolean-cut",
    )
    ax.set_box_aspect([2 * half, 2 * half, height])
    ax.view_init(elev=26, azim=-65)
    fig.savefig(folder / "sidewall_preview.png", dpi=160)
    plt.close(fig)
