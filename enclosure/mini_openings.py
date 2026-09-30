"""Serial, checkpointed Mini base opening cuts with bounded tool batches.

Each checkpoint contains one valid solid and is bound to the exact input BREP,
ordered tool BREPs, designed thickness, kernel, tolerance and algorithm AST.
No completed checkpoint is trusted only because its filename exists.
"""

from pathlib import Path
from importlib.metadata import version
import ast
import gc
import hashlib
import json
import time
import uuid

import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.TopTools import TopTools_ListOfShape

from . import ROOT


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, record):
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.pending")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _store_input(shape, folder):
    temporary = folder / f"capture-{uuid.uuid4().hex}.brep"
    try:
        shape.exportBrep(str(temporary))
        digest = _sha256(temporary)
        destination = folder / f"{digest}.brep"
        if destination.exists():
            if _sha256(destination) != digest:
                raise ValueError("Corrupt content-addressed Mini opening input")
        else:
            temporary.replace(destination)
        return digest
    finally:
        temporary.unlink(missing_ok=True)


def _algorithm_sha256():
    # Restrict invalidation to this module's executable AST. Edits to other
    # exporters, integration checks or documentation cannot discard progress.
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if hasattr(node, "body") and isinstance(node.body, list):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body.pop(0)
    return hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()


def _shape_check(shape):
    if shape.wrapped.IsNull():
        raise ValueError("Mini opening cut returned a null shape")
    solids = len(shape.Solids())
    valid = bool(shape.isValid())
    if solids != 1 or not valid:
        raise ValueError(f"Mini opening cut is not one valid solid: {solids}, {valid}")
    return {"valid": valid, "solids": solids, "faces": len(shape.Faces()),
            "edges": len(shape.Edges()), "vertices": len(shape.Vertices())}


def _cut_batch(shape, tools, tolerance):
    arguments = TopTools_ListOfShape()
    arguments.Append(shape.wrapped)
    operands = TopTools_ListOfShape()
    for tool in tools:
        operands.Append(tool.wrapped)
    operator = BRepAlgoAPI_Cut()
    try:
        operator.SetArguments(arguments)
        operator.SetTools(operands)
        operator.SetFuzzyValue(tolerance)
        operator.SetRunParallel(False)
        operator.Build()
        if not operator.IsDone() or operator.Shape().IsNull():
            raise RuntimeError("Serial Mini opening boolean did not complete")
        return cq.Shape.cast(operator.Shape())
    finally:
        # BOP history/intersection data is much larger than the resulting solid.
        # Never retain a builder or its argument lists between batches.
        del operator, arguments, operands
        gc.collect()


def _run_batches(base, tools, thickness, batch_size, cache_root, roles):
    thickness = float(thickness)
    tolerance = 1e-8
    if thickness <= 0 or batch_size < 1 or batch_size > 18:
        raise ValueError("Expected positive thickness and 1..18 tools per batch")
    if len(tools) != len(roles) or not tools:
        raise ValueError("Tool roles must describe every opening")
    started = time.monotonic()
    cache_root = Path(cache_root)
    inputs = cache_root / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    source_hash = _store_input(base, inputs)
    tool_hashes = [_store_input(tool, inputs) for tool in tools]
    signature = {
        "schema": 1, "model": "mac-mini", "design_thickness_mm": thickness,
        "source_base_brep_sha256": source_hash,
        "ordered_tool_brep_sha256": tool_hashes, "ordered_tool_roles": roles,
        "batch_size": batch_size, "fuzzy_tolerance_mm": tolerance,
        "run_parallel": False, "algorithm_ast_sha256": _algorithm_sha256(),
        "kernel": {name: version(name) for name in ("cadquery", "cadquery-ocp")},
    }
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    folder = cache_root / f"mini-{thickness:g}mm-{fingerprint}"
    folder.mkdir(parents=True, exist_ok=True)
    signature_path = folder / "input_signature.json"
    if signature_path.exists():
        if json.loads(signature_path.read_text(encoding="utf-8")) != signature:
            raise ValueError("Mini opening cache signature mismatch")
    else:
        _write_json(signature_path, signature)

    ranges = [(start, min(start + batch_size, len(tools)))
              for start in range(0, len(tools), batch_size)]
    checkpoints = []
    previous_hash = source_hash
    current_path = inputs / f"{source_hash}.brep"
    for index, (start, end) in enumerate(ranges, 1):
        brep = folder / f"batch-{index:02d}-tools-{end:03d}.brep"
        metadata = brep.with_suffix(".json")
        if not metadata.exists():
            break
        record = json.loads(metadata.read_text(encoding="utf-8"))
        if (record.get("cache_fingerprint") != fingerprint
                or record.get("input_brep_sha256") != previous_hash
                or record.get("tool_start_index") != start
                or record.get("completed_tool_count") != end
                or record.get("tool_brep_sha256") != tool_hashes[start:end]
                or not record.get("valid") or record.get("solids") != 1
                or not brep.exists() or record.get("output_brep_sha256") != _sha256(brep)):
            raise ValueError(f"Untrusted Mini opening checkpoint: {metadata}")
        checkpoints.append(record)
        current_path = brep
        previous_hash = record["output_brep_sha256"]
    resumed = checkpoints[-1]["completed_tool_count"] if checkpoints else 0
    current = cq.Shape.importBrep(str(current_path))
    _shape_check(current)
    if resumed:
        print(f"Mini {thickness:g}mm openings resume {resumed}/{len(tools)} tools", flush=True)

    for index in range(len(checkpoints), len(ranges)):
        start, end = ranges[index]
        print(f"Mini {thickness:g}mm serial openings {start + 1}..{end}/{len(tools)}", flush=True)
        batch_started = time.monotonic()
        batch_tools = [cq.Shape.importBrep(str(inputs / f"{digest}.brep"))
                       for digest in tool_hashes[start:end]]
        result = _cut_batch(current, batch_tools, tolerance)
        del batch_tools
        current = None
        gc.collect()
        check = _shape_check(result)
        brep = folder / f"batch-{index + 1:02d}-tools-{end:03d}.brep"
        temporary = brep.with_name(brep.name + ".pending")
        result.exportBrep(str(temporary))
        output_hash = _sha256(temporary)
        temporary.replace(brep)
        record = {
            "cache_fingerprint": fingerprint,
            "batch_number": index + 1, "tool_start_index": start,
            "completed_tool_count": end, "tool_brep_sha256": tool_hashes[start:end],
            "input_brep_sha256": previous_hash, "output_brep_sha256": output_hash,
            "brep_file": str(brep.relative_to(cache_root)), **check,
            "run_parallel": False, "fuzzy_tolerance_mm": tolerance,
            "elapsed_seconds": time.monotonic() - batch_started,
        }
        _write_json(brep.with_suffix(".json"), record)
        checkpoints.append(record)
        previous_hash = output_hash
        # Re-import the saved boundary representation to discard BOP history and
        # normalize exactly the same way on a continuous run and a resumed run.
        result = None
        gc.collect()
        current = cq.Shape.importBrep(str(brep))
        print(f"Mini {thickness:g}mm checkpoint {end}/{len(tools)} saved", flush=True)

    _shape_check(current)
    record = {
        "method": "serial OCCT Cut with persistent validated BREP checkpoints",
        "model": "mac-mini", "design_thickness_mm": thickness,
        "source_mesh_slots": roles.count("slot"), "button_aperture": "button" in roles,
        "through_designed_wall": True, "run_parallel": False,
        "batch_size": batch_size, "fuzzy_tolerance_mm": tolerance,
        "cache_fingerprint": fingerprint, "input_signature": signature,
        "resumed_completed_tool_count": resumed, "completed_tool_count": len(tools),
        "checkpoint_count": len(checkpoints), "checkpoints": checkpoints,
        "final_brep_sha256": previous_hash,
        "checkpoint_directory": str(folder.resolve()),
        "elapsed_seconds": time.monotonic() - started,
        "no_wall_geometry_from_other_thickness_reused": True,
    }
    _write_json(folder / "completed.json", record)
    return current, record


def cut_mini_base_openings(base, slots, button, thickness, *, batch_size=12, cache_root=None):
    """Cut exactly 108 source slots and the button aperture, resuming if possible."""
    if len(slots) != 108 or button is None:
        raise ValueError("Mini requires 108 identified slots and its button aperture")
    if float(thickness) not in (2.0, 3.0):
        raise ValueError("Only explicitly designed 2 mm / 3 mm wall variants are supported")
    return _run_batches(base, list(slots) + [button], float(thickness), int(batch_size),
                        cache_root or ROOT / ".tmp/mini-opening-batches",
                        ["slot"] * len(slots) + ["button"])
