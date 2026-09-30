"""Housing and base construction within the unified G3 CAD project."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / ".vendor"))
