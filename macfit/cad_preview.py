"""Render this project's native solids with absolute-tolerance, offscreen VTK.

Triangulation is only a display representation. The STEP geometry is not edited.
Native OCCT meshes are copied into compact NumPy arrays without constructing a
Python CadQuery Vector for every vertex. No application windows are opened.
"""

from pathlib import Path
import argparse
import gc
import hashlib
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from macfit import PROJECT_ROOT as ROOT
import cadquery as cq
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopAbs import TopAbs_Orientation
from OCP.TopLoc import TopLoc_Location
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy


def mesh_solid(solid, tolerance, angle):
    mesher = BRepMesh_IncrementalMesh(solid.wrapped, tolerance, False, angle, False)
    if not mesher.IsDone():
        raise ValueError("OCCT triangulation did not finish")
    vertices, indices = [], []
    offset = 0
    for face in solid.Faces():
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face.wrapped, location)
        if mesh is None:
            raise ValueError("An actual STEP face has no display triangulation")
        transform = location.Transformation()
        points = np.empty((mesh.NbNodes(), 3), dtype=np.float32)
        for i in range(mesh.NbNodes()):
            point = mesh.Node(i + 1).Transformed(transform)
            points[i] = point.X(), point.Y(), point.Z()
        triangles = np.empty((mesh.NbTriangles(), 3), dtype=np.int64)
        for i in range(mesh.NbTriangles()):
            triangle = mesh.Triangle(i + 1)
            triangles[i] = triangle.Value(1), triangle.Value(2), triangle.Value(3)
        triangles += offset - 1
        if face.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
            triangles[:, [1, 2]] = triangles[:, [2, 1]]
        vertices.append(points)
        indices.append(triangles)
        offset += len(points)
    points_array = np.concatenate(vertices)
    faces_array = np.concatenate(indices)
    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(points_array, deep=True))
    cells = vtk.vtkCellArray()
    cells.SetData(
        numpy_to_vtkIdTypeArray(np.arange(0, faces_array.size + 1, 3), deep=True),
        numpy_to_vtkIdTypeArray(faces_array.ravel(), deep=True),
    )
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(cells)
    return poly, {"vertices": len(points_array), "triangles": len(faces_array)}


def font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return (
        ImageFont.truetype(str(path), size)
        if path.exists()
        else ImageFont.load_default()
    )


def render(model, tolerance, angular, source_path=None, output_path=None):
    start = time.monotonic()
    folder = ROOT / "results/masters" / model
    path = (
        Path(source_path).resolve()
        if source_path
        else folder / "curve-solid" / f"{model}_solid.brep"
    )
    output_path = (
        Path(output_path).resolve() if output_path else path.parent / "preview.png"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Importing {path.name}", flush=True)
    shape = (cq.Shape.importBrep(str(path)) if path.suffix.lower() == ".brep"
             else cq.importers.importStep(str(path)).val())
    # Compute exact geometry bounds before the display triangulation is attached.
    # OCCT's general bounding-box helper can include mesh deflection afterwards.
    bounds = shape.BoundingBox()
    solids = shape.Solids()
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.965, 0.972, 0.98)
    statistics = []
    for index, solid in enumerate(solids):
        print(
            f"Meshing {model} solid {index + 1}/{len(solids)} ({len(solid.Faces())} faces)",
            flush=True,
        )
        poly, info = mesh_solid(solid, tolerance, angular)
        statistics.append(info)
        print(f"  {info['triangles']:,} triangles", flush=True)
        # Display meshes duplicate vertices at CAD face boundaries. Merge only
        # coincident display points so normals remain smooth across tangent
        # row-band seams; this never changes the source BREP or its tolerances.
        merged = vtk.vtkCleanPolyData()
        merged.SetInputData(poly)
        merged.ToleranceIsAbsoluteOn()
        merged.SetAbsoluteTolerance(1e-6)
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(merged.GetOutputPort())
        normals.SetFeatureAngle(40)
        normals.SplittingOn()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        metal = solid.BoundingBox().zmax > 40
        actor.GetProperty().SetColor(
            *((0.67, 0.70, 0.73) if metal else (0.16, 0.18, 0.21))
        )
        actor.GetProperty().SetAmbient(0.24)
        actor.GetProperty().SetDiffuse(0.68)
        actor.GetProperty().SetSpecular(0.22)
        actor.GetProperty().SetSpecularPower(35)
        renderer.AddActor(actor)
        gc.collect()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1300, 920)
    window.AddRenderer(renderer)
    window.SetMultiSamples(4)
    center = np.array([0.0, 0.0, (bounds.zmax + bounds.zmin) / 2])
    width = max(bounds.xlen, bounds.ylen)
    camera = renderer.GetActiveCamera()
    camera.SetFocalPoint(*center)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(width * 0.65)
    views = []
    labels = ["Front / top", "Rear / top", "Front / underside", "Rear / underside"]
    for name, (azimuth, elevation) in zip(
        labels, [(55, 28), (235, 28), (55, -35), (235, -35)]
    ):
        print(f"Capturing {name}", flush=True)
        a, e = np.deg2rad([azimuth, elevation])
        direction = np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])
        camera.SetPosition(*(center + 3 * width * direction))
        camera.SetViewUp(0, 0, 1)
        renderer.ResetCameraClippingRange()
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        output = capture.GetOutput()
        w, h, _ = output.GetDimensions()
        pixels = vtk_to_numpy(output.GetPointData().GetScalars()).reshape(h, w, 3)
        view = Image.fromarray(np.flipud(pixels)).copy()
        ImageDraw.Draw(view).text((30, 24), name, fill=(35, 46, 58), font=font(27))
        views.append(view)
    canvas = Image.new("RGB", (2600, 1960), "white")
    for index, view in enumerate(views):
        canvas.paste(view, ((index % 2) * 1300, 120 + (index // 2) * 920))
    draw = ImageDraw.Draw(canvas)
    title = "Mac mini" if model == "mac-mini" else "Mac Studio"
    draw.text(
        (32, 19),
        f"{title} | {path.stem}",
        font=font(34),
        fill=(25, 38, 50),
    )
    draw.text(
        (32, 71),
        f"Actual {path.suffix[1:].upper()} geometry | {bounds.xlen:.2f} x {bounds.ylen:.2f} x {bounds.zlen:.2f} mm | Continuous flat top; no logo; no internal components",
        font=font(23),
        fill=(60, 72, 84),
    )
    canvas.save(output_path)
    window.Finalize()
    record = {
        "model": model,
        "source_cad": path.name,
        "source_cad_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rendering": "VTK offscreen, native OCCT absolute-deflection triangulation",
        "linear_deflection_mm": tolerance,
        "angular_deflection_radians": angular,
        "mesh_decimation": False,
        "solids": len(solids),
        "mesh_statistics": statistics,
        "elapsed_seconds": time.monotonic() - start,
    }
    output_path.with_name(output_path.stem + "_render.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved {output_path} in {record['elapsed_seconds']:.1f} s", flush=True)

