"""Render the eight current plain-solid and shell masters."""

from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macfit import PROJECT_ROOT
from macfit.cad_preview import render


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["mac-mini", "mac-studio", "both"], default="both")
    parser.add_argument("--variant", choices=["solid", "1mm-solid", "2mm", "3mm", "all"], default="all")
    args = parser.parse_args()
    for model in (["mac-mini", "mac-studio"] if args.model == "both" else [args.model]):
        for variant in (["solid", "1mm-solid", "2mm", "3mm"] if args.variant == "all" else [args.variant]):
            folder = PROJECT_ROOT / "results/masters" / model / ('curve-'+variant)
            render(model, 0.05, 0.15, folder / f"{model}_{variant}.brep", folder / "preview.png")


if __name__ == "__main__":
    main()
