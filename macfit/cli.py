"""Fit and verify the retained source contour reference."""

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys

from . import PROJECT_ROOT, __version__, FROZEN_RESULTS


def integrity():
    manifest_path = PROJECT_ROOT / "fit_reference_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = []
    for entry in manifest["files"]:
        path = (PROJECT_ROOT / entry["path"]).resolve()
        if not path.is_relative_to(PROJECT_ROOT):
            errors.append("Unsafe manifest path: " + entry["path"])
        elif not path.is_file():
            errors.append("Missing: " + entry["path"])
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            errors.append("Changed: " + entry["path"])
    if errors:
        raise ValueError("\n".join(errors))
    return {"version": manifest["version"], "checked_files": len(manifest["files"]), "passed": True}


def doctor():
    dependencies = {}
    for name in ["numpy", "scipy", "matplotlib", "pxr.Usd", "rhino3dm"]:
        module = importlib.import_module(name)
        if name == "rhino3dm" and not hasattr(module, "File3dm"):
            raise ImportError(
                "rhino3dm is not readable or incomplete; install requirements.txt in a venv"
            )
        dependencies[name] = getattr(module, "__version__", "available")
    from .settings import PROFILES

    for profile in PROFILES.values():
        path = PROJECT_ROOT / "data/input" / profile["input_file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != profile["source_sha256"]:
            raise ValueError("Source checksum mismatch: " + str(path))
    return {
        "version": __version__,
        "python": platform.python_version(),
        "dependencies": dependencies,
        "input_checksums_passed": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="MacFit: G3 contour fitting and retained reference verification"
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check dependencies and source file checksums")
    commands.add_parser("integrity", help="Read-only validation of the published release manifest")
    run = commands.add_parser("run", help="Fit, export, verify and render both or one model")
    run.add_argument("--model", choices=["mini", "studio", "both"], default="both")
    run.add_argument("--input-dir", type=Path, default=PROJECT_ROOT / "data/input")
    run.add_argument("--output", type=Path, default=PROJECT_ROOT / ".tmp/refit")
    run.add_argument(
        "--overwrite", action="store_true", help="Update existing work results; never deletes files"
    )
    for name, description in [
        ("verify", "Read-only CAD and numerical verification"),
        ("plot", "Regenerate plots from saved data"),
        ("height", "Run the height-dependence diagnostic"),
    ]:
        command = commands.add_parser(name, help=description)
        command.add_argument("--model", choices=["mini", "studio", "both"], default="both")
        command.add_argument(
            "--results",
            type=Path,
            default=FROZEN_RESULTS if name == "verify" else PROJECT_ROOT / ".tmp/refit",
        )
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            print(json.dumps(doctor(), indent=2))
            return 0
        if args.command == "integrity":
            print(json.dumps(integrity(), indent=2))
            return 0
        from .settings import PROFILES

        cases = ["mini", "studio"] if args.model == "both" else [args.model]
        if args.command == "run":
            from .pipeline import run_model
            from .verification import verify_model
            from .height import check
            from .diagnostics import plot

            output = args.output.resolve()
            release = FROZEN_RESULTS.resolve()
            if output == release or output.is_relative_to(release):
                raise ValueError(
                    "Published results are frozen. Choose a separate work output directory."
                )
            for case in cases:
                folder = output / PROFILES[case]["output_folder"]
                if folder.exists() and any(folder.iterdir()) and not args.overwrite:
                    raise ValueError(
                        f"{folder} is not empty; choose another --output or use --overwrite"
                    )
            for case in cases:
                folder = output / PROFILES[case]["output_folder"]
                run_model(case, args.input_dir.resolve(), output)
                verify_model(folder, write_report=True)
                check(folder)
                plot(folder, case)
            print("Completed: " + str(output))
        else:
            release = FROZEN_RESULTS.resolve()
            if args.command != "verify" and (
                args.results.resolve() == release or args.results.resolve().is_relative_to(release)
            ):
                raise ValueError(
                    "Published results are frozen. Plot/height commands require work results."
                )
            results = []
            for case in cases:
                folder = args.results.resolve() / PROFILES[case]["output_folder"]
                if args.command == "verify":
                    from .verification import verify_model

                    results.append(verify_model(folder))
                elif args.command == "plot":
                    from .diagnostics import plot

                    plot(folder, case)
                else:
                    from .height import check

                    results.append(check(folder))
            if results:
                print(json.dumps(results, indent=2))
        return 0
    except (OSError, ValueError, ImportError, AssertionError, RuntimeError) as exc:
        print(f'ERROR: {exc or "Verification assertion failed"}', file=sys.stderr)
        return 1
