"""Prepare exact profile references and design tables for native SW features."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.vendor'), str(ROOT)]
import cadquery as cq
import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
from OCP.Geom import Geom_BSplineCurve
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
from OCP.gp import gp_Pnt
from enclosure.current_design import parameters, side_cutters, source_button
from enclosure.studio_rear_pattern import make_pattern
from enclosure.studio_base_pattern import circular_pattern

REFERENCE_DEPTH_MM = 0.5


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def array(cls, values):
    result = cls(1, len(values))
    for i, value in enumerate(values, 1):
        result.SetValue(i, value)
    return result


def profile_prism(definition):
    xy = np.asarray(definition['controls_mm'])
    edges = []
    for _ in range(4):
        curve = Geom_BSplineCurve(
            array(TColgp_Array1OfPnt, [gp_Pnt(float(x), float(y), 0) for x, y in xy]),
            array(TColStd_Array1OfReal, definition['knots']),
            array(TColStd_Array1OfInteger, definition['multiplicities']),
            definition['degree'])
        edges.append(cq.Edge(BRepBuilderAPI_MakeEdge(curve).Edge()))
        following = np.column_stack((xy[:, 1], -xy[:, 0]))
        edges.append(cq.Edge.makeLine(cq.Vector(*xy[-1], 0), cq.Vector(*following[0], 0)))
        xy = following
    return cq.Solid.extrudeLinear(cq.Wire.assembleEdges(edges), [], cq.Vector(0, 0, REFERENCE_DEPTH_MM))


def write_reference(shape, path):
    if len(shape.Solids()) != 1 or not shape.isValid():
        raise ValueError(f'Invalid native construction reference: {path.name}')
    cq.exporters.export(shape, str(path), exportType='STEP')
    return {'file': str(path.resolve()), 'sha256': sha(path)}


def centered_tool(shape, path):
    box = shape.BoundingBox()
    center = np.array([(box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2,
                       (box.zmin + box.zmax) / 2])
    local = shape.translate(tuple(-center))
    result = write_reference(local, path)
    result.update(center_mm=center.tolist(), width_mm=box.xlen, height_mm=box.zlen)
    return result


def prepare(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    definitions = read(ROOT / 'docs/technical/geometry_definition.json')
    packet = {'schema': 'solidworks-native-construction-v1', 'units': 'mm',
              'reference_depth_mm': REFERENCE_DEPTH_MM, 'models': {},
              'source_bindings': {p: sha(ROOT / p) for p in (
                  'docs/technical/geometry_definition.json', 'data/fitted_profiles.json',
                  'data/enclosure_design.json', 'data/input/mac-mini-silver.usdz',
                  'data/reference/mac-mini-observations.json',
                  'enclosure/cad.py', 'enclosure/current_design.py',
                  'enclosure/source_features.py', 'enclosure/usd.py', 'enclosure/specs.py',
                  'tools/shared_profiles.py', 'enclosure/studio_rear_pattern.py', 'enclosure/rear_profile.py')}}
    for model in ('mac-mini', 'mac-studio'):
        entry = {'profiles': {}, 'variants': {}}
        profile = definitions['profiles'][model]
        for key, definition in [('outer', profile['outer']),
                                ('inner2', profile['inner']['2']), ('inner3', profile['inner']['3'])]:
            entry['profiles'][key] = write_reference(profile_prism(definition), destination / f'{model}_{key}.stp')
        for wall in (2, 3):
            folder = ROOT / 'results/masters' / model / f'enclosure-{wall}mm'
            design = parameters(folder)
            variant = {'design': design, 'ports': []}
            interface = design['base_design']['interface_z_mm']
            for index, shape in enumerate(side_cutters(design), 1):
                local = shape.translate((0, 0, -interface))
                tool = centered_tool(local, destination / f'{model}_{wall}mm_port{index:02d}.stp')
                tool['side_y_sign'] = design['side_apertures'][index - 1]['side_y_sign']
                variant['ports'].append(tool)
            if model == 'mac-mini':
                variant['vents'] = read(folder / 'uniform_vent_pattern.json')
                rel = (folder / 'uniform_vent_pattern.json').relative_to(ROOT).as_posix()
                packet['source_bindings'][rel] = sha(ROOT / rel)
            else:
                variant['rear_holes'] = make_pattern(np.asarray(profile['outer']['controls_mm']), design['rear_grid_design']).tolist()
                variant['base_holes'] = circular_pattern(design['base_design']).tolist()
            entry['variants'][str(wall)] = variant
            rel = (folder / 'model_parameters.json').relative_to(ROOT).as_posix()
            packet['source_bindings'][rel] = sha(ROOT / rel)
        if model == 'mac-mini':
            entry['button'] = centered_tool(source_button(), destination / 'mac-mini_button.stp')
        packet['models'][model] = entry
    target = destination / 'construction.json'
    target.write_text(json.dumps(packet, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Prepared exact native references: {target}')
    return target


if __name__ == '__main__':
    prepare(sys.argv[1] if len(sys.argv) > 1 else ROOT / '.tmp/solidworks-native/references')
