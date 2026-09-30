"""MacFit: constrained G3 sidewall reconstruction from profiled USDZ assets."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_RESULTS = PROJECT_ROOT / 'results/fitting/reference'

def reference_cad_path(folder,filename):
    folder=Path(folder).resolve()
    if folder.parent==FROZEN_RESULTS.resolve():return PROJECT_ROOT/'results/3DM/reference'/folder.name/filename
    return folder/filename

__version__ = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()

# Optional project-local dependency used on the original workstation.
# Fresh installations use requirements.txt in a virtual environment.
_vendor = PROJECT_ROOT / ".vendor"
if _vendor.is_dir():
    sys.path.append(str(_vendor))
