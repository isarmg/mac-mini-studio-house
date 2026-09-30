"""Official USD parsing and numerical result I/O."""

import hashlib
import json
import numpy as np
from pxr import Usd, UsdGeom


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def read_usd(path):
    # Absolute path is necessary for this Windows USD build in a Unicode cwd.
    stage = Usd.Stage.Open(str(path.resolve()))
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    scale = UsdGeom.GetStageMetersPerUnit(stage) * 1000
    axis = str(UsdGeom.GetStageUpAxis(stage))
    up = {"Y": 1, "Z": 2}[axis]
    planar = [i for i in range(3) if i != up]
    rows, meshes = [], {}
    for prim in Usd.PrimRange(stage.GetPseudoRoot(), Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        local = np.asarray(mesh.GetPointsAttr().Get(), dtype=float)
        if not len(local):
            continue
        matrix = np.asarray(cache.GetLocalToWorldTransform(prim))
        world = (local @ matrix[:3, :3] + matrix[3, :3]) * scale
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), dtype=int)
        indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), dtype=int)
        if counts.sum() != len(indices) or indices.min() < 0 or indices.max() >= len(world):
            raise ValueError("Invalid topology: " + str(prim.GetPath()))
        name = str(prim.GetPath())
        extent = np.ptp(world, axis=0)
        row = dict(
            path=name,
            vertices=len(world),
            faces=len(counts),
            face_sizes=np.unique(counts).tolist(),
            subdivision=str(mesh.GetSubdivisionSchemeAttr().Get()),
            visible=str(mesh.ComputeVisibility()),
            purpose=str(mesh.ComputePurpose()),
            time_samples=mesh.GetPointsAttr().GetTimeSamples(),
            holes=list(mesh.GetHoleIndicesAttr().Get() or []),
            bounds_mm=[world.min(0).tolist(), world.max(0).tolist()],
            extent_mm=extent.tolist(),
            world_matrix=matrix.tolist(),
        )
        rows.append(row)
        meshes[name] = (world, counts, indices, row)
    return (
        dict(
            file=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            usd_version=list(Usd.GetVersion()),
            up_axis=axis,
            mm_per_unit=scale,
            units_authored=stage.HasAuthoredMetadata("metersPerUnit"),
            mesh_count=len(rows),
            meshes=rows,
        ),
        meshes,
        up,
        planar,
    )


def resample(poly, count=640):
    p = np.vstack([poly, poly[0]])
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    t = np.linspace(0, s[-1], count, endpoint=False)
    return np.column_stack([np.interp(t, s, p[:, j]) for j in range(2)])


def stats(d):
    return dict(
        rms_mm=float(np.sqrt(np.mean(d * d))),
        p95_mm=float(np.percentile(d, 95)),
        max_mm=float(np.max(d)),
        count=len(d),
    )
