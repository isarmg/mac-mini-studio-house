"""Load model profiles and fitting protocol from project configuration."""

import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime, timezone

from . import PROJECT_ROOT, __version__

PROFILES = json.loads((PROJECT_ROOT / "configs/models.json").read_text(encoding="utf-8"))
PROTOCOL = json.loads((PROJECT_ROOT / "configs/protocol.json").read_text(encoding="utf-8"))


def validate_protocol():
    margin = PROTOCOL["end_margin_fraction"]
    heights = sum(
        (PROTOCOL[key] for key in ["train_heights", "validation_heights", "test_heights"]), []
    )
    if not 0 < margin < 0.5 or len(heights) != len(set(heights)):
        raise ValueError(
            "Height splits must be disjoint and the end margin must be between 0 and 0.5"
        )
    if not all(margin < h < 1 - margin for h in heights):
        raise ValueError("A sample height lies in an excluded end region")
    if 0.5 not in heights:
        raise ValueError("The reference section at 50% height is required")
    if PROTOCOL["opening_guard_mm"] <= 0 or PROTOCOL["support_tolerance_mm"] <= 0:
        raise ValueError("Geometry tolerances must be positive")


def environment_info(audit, profile):
    dependencies = {}
    for name in ["usd-core", "numpy", "scipy", "matplotlib", "rhino3dm"]:
        dependencies[name] = importlib.metadata.version(name)
    return {
        "version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": dependencies,
        "source_file": audit["file"],
        "source_sha256": audit["sha256"],
        "profile": profile,
        "config_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (PROJECT_ROOT / "configs").glob("*.json")
        },
    }


validate_protocol()
