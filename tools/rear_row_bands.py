"""Build Studio's repeated rear perforations using two reusable row solids.

The enclosure sidewall is a vertical extrusion. Entire horizontal annular bands
therefore have identical geometry, with only the alternating circle positions
changing. Drill each parity once, translate its result, and fuse at the planar
interfaces. This avoids intersecting thousands of cylinders with one increasingly
fragmented NURBS body. Artificial row seams may remain as face boundaries.
"""

from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enclosure import ROOT
from enclosure.cad import main_outline
from enclosure.validation import validate_plain_top
from enclosure.wall_offset import planar_inner_wire
from tools.housing_perforations import validate_cylinder_axes
import cadquery as cq
import numpy as np
from OCP.OSD import OSD_ThreadPool


def _box_values(shape):
    box = shape.BoundingBox()
    return np.array([box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax])


def _fingerprint(body, thickness, cache, source_paths):
    input_path = cache / f"input-wall-{thickness:g}.brep"
    body.exportBrep(str(input_path))
    digest = hashlib.sha256(input_path.read_bytes())
    digest.update(np.float64(thickness).tobytes())
    for path in source_paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def perforate_rear_by_rows(body, out, thickness, parameters, table_path):
    """Return one valid hollow housing and the rear-hole acceptance record."""
    started = time.monotonic()
    OSD_ThreadPool.DefaultPool_s().Init(4)
    thickness = float(thickness)
    if thickness <= 0:
        raise ValueError("Expected a positive designed wall thickness")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    table_path=Path(table_path)
    table=np.genfromtxt(table_path,delimiter=",",names=True)
    cp=np.asarray(parameters['main_G3_quarter_controls_mm'])
    levels=np.unique(table['z_mm']);pitch=float(np.median(np.diff(levels)))
    pattern={'vertical_pitch_mm':pitch,'source':'current rear_hole_axes.csv'}
    row_ids = np.unique(table["row"]).astype(int)
    centers = np.column_stack([table[name] for name in ["x_mm", "y_mm", "z_mm"]])
    inward = np.column_stack([table[name] for name in ["nx", "ny", "nz"]])
    radii = table["radius_mm"]
    if np.any(abs(inward[:, 2]) > 1e-12):
        raise ValueError("Reusable bands require horizontal drilling axes")
    if np.min(pitch / 2 - radii) <= 1e-4:
        raise ValueError("Circular holes would intersect horizontal band interfaces")
    if not np.array_equal(row_ids, np.arange(row_ids[0], row_ids[-1] + 1)):
        raise ValueError("The source row numbering is not contiguous")
    lower = float(centers[:, 2].min() - pitch / 2)
    upper = float(centers[:, 2].max() + pitch / 2)
    z_centers = {}
    reference_rows = {}
    for row in row_ids:
        ids = np.flatnonzero(table["row"] == row)
        ids = ids[np.argsort(table["column"][ids])]
        if np.ptp(centers[ids, 2]) > 1e-10:
            raise ValueError("A source row is not horizontal")
        z_centers[int(row)] = float(centers[ids[0], 2])
        parity = int(row % 2)
        if parity not in reference_rows:
            reference_rows[parity] = ids
        else:
            reference = reference_rows[parity]
            if len(reference) != len(ids) or not np.allclose(
                np.c_[centers[ids, :2], inward[ids], radii[ids]],
                np.c_[centers[reference, :2], inward[reference], radii[reference]],
                atol=1e-10,
                rtol=0,
            ):
                raise ValueError("Rows of one parity cannot be reused exactly")
    row_z = np.array([z_centers[int(row)] for row in row_ids])
    if np.max(abs(np.diff(row_z) - pitch)) > 1e-10:
        raise ValueError("Vertical spacing is not uniform")

    # The slab replacement must never discard an unrelated side opening.
    port_highs = []
    for port in parameters['side_apertures']:
        z=np.asarray(port['mouth_points_nominal_mm'])[:,2]
        port_highs.append(float(z.max()))
        if z.max() >= lower - 1e-4:
            raise ValueError("A side port reaches the rear row band region")
    original_bounds = _box_values(body)
    height = parameters["nominal_dimensions_mm"][2]
    original_top = validate_plain_top(body, height, cp)
    if lower <= original_bounds[4] or upper >= height - thickness:
        raise ValueError("Rear bands intersect the base datum or top plate")

    cache = ROOT / ".tmp/rear-row-bands"
    cache.mkdir(parents=True, exist_ok=True)
    fingerprint = _fingerprint(
        body,
        thickness,
        cache,
        [
            Path(__file__),
            table_path,
            ROOT / "enclosure/cad.py",
            ROOT / "enclosure/wall_offset.py",
            ROOT / "enclosure/specs.py",
            ROOT / "enclosure/validation.py",
            ROOT / "tools/housing_perforations.py",
        ],
    )
    prefix = f"wall-{thickness:g}-{fingerprint}"
    final_path = cache / f"{prefix}-complete.brep"
    metadata_path = cache / f"{prefix}-complete.json"
    cache_reused = final_path.exists() and metadata_path.exists()
    if cache_reused:
        print(f"Studio {thickness:g} mm: reusing complete row-band cache", flush=True)
        final = cq.Shape.importBrep(str(final_path))
        cached = json.loads(metadata_path.read_text(encoding="utf-8"))
        if hashlib.sha256(final_path.read_bytes()).hexdigest() != cached["brep_sha256"]:
            raise ValueError(
                "Cached final BREP content does not match its acceptance record"
            )
        band_records = cached["band_records"]
    else:
        bands, band_records = {}, {}
        for parity, ids in reference_rows.items():
            band_path = cache / f"{prefix}-row-{parity}.brep"
            row_record = cache / f"{prefix}-row-{parity}.json"
            z = float(centers[ids[0], 2])
            if band_path.exists() and row_record.exists():
                print(
                    f"Studio {thickness:g} mm: reusing drilled parity {parity}",
                    flush=True,
                )
                band = cq.Shape.importBrep(str(band_path))
                check = json.loads(row_record.read_text(encoding="utf-8"))
                if (
                    hashlib.sha256(band_path.read_bytes()).hexdigest()
                    != check["brep_sha256"]
                ):
                    raise ValueError("Cached row BREP content changed")
            else:
                band_low = z - pitch / 2
                inner, offset = planar_inner_wire(cp, band_low, thickness)
                band = cq.Solid.extrudeLinear(
                    main_outline(cp, band_low), [inner], (0, 0, pitch)
                )
                tools = []
                for index in ids:
                    outside = 1.0
                    tools.append(
                        cq.Solid.makeCylinder(
                            float(radii[index]),
                            thickness + 2.0 + outside,
                            cq.Vector(*(centers[index] - outside * inward[index])),
                            cq.Vector(*inward[index]),
                        )
                    )
                print(
                    f"Studio {thickness:g} mm: drilling parity {parity}, {len(tools)} holes",
                    flush=True,
                )
                band_start = time.monotonic()
                band = band.cut(*tools, tol=1e-6)
                if len(band.Solids()) != 1 or not band.isValid():
                    raise ValueError("Reusable drilled band is not one valid solid")
                axes = validate_cylinder_axes(
                    band, centers[ids], inward[ids], radii[ids]
                )
                band.exportBrep(str(band_path))
                check = {
                    "holes": len(ids),
                    "reference_center_z_mm": z,
                    "valid_single_solid": True,
                    "cylinders": axes,
                    "inner_offset": offset,
                    "elapsed_seconds": time.monotonic() - band_start,
                    "brep_sha256": hashlib.sha256(band_path.read_bytes()).hexdigest(),
                }
                row_record.write_text(
                    json.dumps(check, indent=2) + "\n", encoding="utf-8"
                )
                print(
                    f"  parity {parity} complete in {check['elapsed_seconds']:.1f} s",
                    flush=True,
                )
            bands[parity] = band
            band_records[str(parity)] = check

        half = max(abs(original_bounds[:4])) + 2
        slab = cq.Solid.makeBox(
            2 * half, 2 * half, upper - lower, cq.Vector(-half, -half, lower)
        )
        retained = body.cut(slab, tol=1e-6)
        if len(retained.Solids()) != 2 or not retained.isValid():
            raise ValueError(
                "Slab removal must retain the lower housing and upper top section"
            )
        translated = []
        for row in row_ids:
            parity = int(row % 2)
            delta = (
                z_centers[int(row)] - band_records[str(parity)]["reference_center_z_mm"]
            )
            translated.append(bands[parity].translate((0, 0, delta)))
        print(
            f"Studio {thickness:g} mm: fusing {len(translated)} drilled bands and retained housing",
            flush=True,
        )
        final = retained.fuse(*translated, glue=True, tol=1e-6)

    print(
        f"Studio {thickness:g} mm: validating row-band solid and all cylinder axes",
        flush=True,
    )
    if len(final.Solids()) != 1 or not final.isValid():
        raise ValueError("Assembled rear row bands are not one valid solid")
    geometry = validate_cylinder_axes(final, centers, inward, radii)
    extent_error = float(np.max(abs(_box_values(final) - original_bounds)))
    if extent_error > 1e-5:
        raise ValueError("The row-band replacement changed the outer envelope")
    top = validate_plain_top(final, height, cp)
    if not cache_reused:
        final.exportBrep(str(final_path))
        metadata_path.write_text(
            json.dumps(
                {
                    "brep_sha256": hashlib.sha256(final_path.read_bytes()).hexdigest(),
                    "band_records": band_records,
                    "geometry": geometry,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if table_path.resolve()!=(out/'rear_hole_axes.csv').resolve():
        shutil.copy2(table_path, out / "rear_hole_axes.csv")
    record = {
        "classification": "regular staggered circular grid fitted to source texture",
        "algorithm": "Two exactly reusable drilled annular row bands, translated into 29 rows and glued at planar interfaces",
        "hole_count": len(centers),
        "radius_mm": float(radii[0]),
        "direction": "local G3 profile inward normal",
        "designed_wall_thickness_mm": thickness,
        "through_designed_wall": True,
        "closure_is_not_physical_inner_wall": False,
        "pattern": pattern,
        "geometry": geometry,
        "band_z_interval_mm": [lower, upper],
        "band_interface_to_nearest_hole_margin_mm": float(np.min(pitch / 2 - radii)),
        "all_other_side_ports_below_bands": True,
        "maximum_other_side_port_z_mm": max(port_highs),
        "maximum_envelope_change_mm": extent_error,
        "original_top": original_top,
        "top": top,
        "band_records": band_records,
        "cache_fingerprint": fingerprint,
        "cache_reused": cache_reused,
        "elapsed_seconds": time.monotonic() - started,
    }
    return final, record
