"""Verify native CAD evidence against exact curves and analytic hole definitions."""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.vendor'), str(ROOT)]
import numpy as np
from scipy.interpolate import BSpline
from scipy.spatial import cKDTree
from scipy.optimize import linear_sum_assignment

TOL = 1e-7
KNOT_TOL = 1e-11


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected, message, tolerance=TOL):
    a, b = np.asarray(actual), np.asarray(expected)
    need(a.shape == b.shape, f'{message}: shape {a.shape} != {b.shape}')
    error = float(np.max(np.abs(a - b))) if a.size else 0.
    need(error <= tolerance, f'{message}: error {error:.12g} > {tolerance}')
    return error


@lru_cache(None)
def definition(model, wall):
    return read(ROOT / 'results/masters' / model / f'enclosure-{wall or 2}mm/model_parameters.json')


@lru_cache(None)
def profiles():
    return read(ROOT / 'docs/technical/geometry_definition.json')['profiles']


def parameters(state):
    result = {}
    for item in state['equations']:
        match = re.fullmatch(r'\s*"([^"@]+)"\s*=\s*([-+\d.eE]+)\s*(?:mm)?\s*', item['expression'])
        if match:
            result[match[1]] = float(match[2])
    return result


def curve_data(profile):
    need(profile['type'] == 'BSplineCurve', 'Expected a native B-spline curve')
    cp = np.asarray(profile['coordinates']).reshape(-1, profile['dimension'])
    need(len(cp) == profile['control_count'], 'Control point count differs from data')
    if cp.shape[1] == 4:
        close(cp[:, 3], np.ones(len(cp)), 'Rational weights', 1e-14)
    knots = np.asarray(profile['knots'])
    return cp[:, :3] * 1000, knots, profile['degree']


def unit_knots(knots):
    return (knots - knots[0]) / (knots[-1] - knots[0])


def check_samples(surface):
    cp, knots, degree = curve_data(surface['profile'])
    curve = BSpline(knots, cp, degree)
    maximum = 0.
    for sample in surface['profile']['samples']:
        maximum = max(maximum, close(curve(sample['u']), np.asarray(sample['point']) * 1000,
                                     'Native curve evaluation'))
    for sample in surface['samples']:
        u, v = sample['uv']
        point = curve(u) + v * 1000 * np.asarray(surface['direction'])
        maximum = max(maximum, close(point, np.asarray(sample['point']) * 1000,
                                     'Native extrusion evaluation'))
    return maximum


def match_curves(actual, expected, axes):
    matched = set()
    maximum, knot_error = 0., 0.
    for surface in actual:
        cp, knots, degree = curve_data(surface['profile'])
        k = unit_knots(knots)
        candidates = []
        for index, (target, target_knots, target_degree) in enumerate(expected):
            if cp[:, axes].shape != target.shape or degree != target_degree:
                continue
            for reverse in (False, True):
                points = cp[::-1, axes] if reverse else cp[:, axes]
                keys = 1 - k[::-1] if reverse else k
                if keys.shape == target_knots.shape:
                    candidates.append((float(np.max(np.linalg.norm(points - target, axis=1))),
                                       float(np.max(abs(keys - target_knots))), index))
        need(candidates, 'Unrecognized native support curve')
        error, ke, index = min(candidates)
        need(error <= TOL and ke <= KNOT_TOL,
             f'Curve definition changed: control {error} mm; knots {ke}')
        matched.add(index)
        maximum, knot_error = max(maximum, error), max(knot_error, ke)
    need(matched == set(range(len(expected))), 'Exact support curves are missing')
    return {'matched_curves': len(matched), 'max_control_error_mm': maximum,
            'max_normalized_knot_error': knot_error}


def check_g3(state, spec):
    model, wall = spec['model'], spec['wall_mm']
    source = profiles()[model]
    choices = [] if 'base_height_mm' in spec else [source['outer']]
    if wall:
        choices.append(source['inner'][str(wall)])
    expected = []
    for p in choices:
        xy = np.asarray(p['controls_mm'])
        knots = np.repeat(p['knots'], p['multiplicities'])
        for _ in range(4):
            expected.append((xy, knots, p['degree']))
            xy = np.column_stack((xy[:, 1], -xy[:, 0]))
    actual = [s for s in state['supports'] if s['type'] == 'NativeExtrusion'
              and s['profile'].get('degree') == 7]
    proof = match_curves(actual, expected, [0, 1])
    curvature, rate, tangent, evaluation = 0., 0., 0., 0.
    for s in actual:
        close(np.abs(s['direction']), [0, 0, 1], 'G3 extrusion direction', 1e-12)
        cp, knots, degree = curve_data(s['profile'])
        close(cp[:, 2], np.full(len(cp), cp[0, 2]), 'Planar G3 profile')
        c = BSpline(unit_knots(knots), cp[:, :2], degree)
        for t in (0., 1.):
            v, a, j = c(t, 1), c(t, 2), c(t, 3)
            speed = np.linalg.norm(v)
            det = v[0] * a[1] - v[1] * a[0]
            k = det / speed**3
            ks = (v[0] * j[1] - v[1] * j[0]) / speed**4 - 3 * det * np.dot(v, a) / speed**6
            curvature, rate = max(curvature, abs(k)), max(rate, abs(ks))
            tangent = max(tangent, float(min(abs(v)) / speed))
        evaluation = max(evaluation, check_samples(s))
    need(curvature < 1e-8 and rate < 1e-8 and tangent < 1e-9, 'G3 line-to-curve continuity failed')
    proof.update(max_endpoint_curvature=curvature, max_endpoint_curvature_rate=rate,
                 max_endpoint_tangent_residual=tangent, max_evaluation_error_mm=evaluation)
    return proof


@lru_cache(None)
def aperture_curves(model, wall, button=False):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from enclosure.cad import smooth_wire
    from enclosure.current_design import source_button_points
    d = definition(model, wall)
    point_sets = []
    if button:
        points = source_button_points()
        points[:, 2] = -1
        point_sets.append(points)
    else:
        for port in d['side_apertures']:
            points = np.array(port['mouth_points_nominal_mm'])
            points[:, 1] = port['side_y_sign'] * (d['nominal_dimensions_mm'][1] / 2 + 2)
            points[:, 2] -= d['base_design']['interface_z_mm']
            point_sets.append(points)
    result = []
    for points in point_sets:
        c = BRepAdaptor_Curve(smooth_wire(points).Edges()[0].wrapped).BSpline()
        c.Segment(c.FirstParameter(), c.LastParameter())
        cp = np.array([c.Pole(i).Coord() for i in range(1, c.NbPoles() + 1)])
        knots = np.repeat([c.Knot(i) for i in range(1, c.NbKnots() + 1)],
                          [c.Multiplicity(i) for i in range(1, c.NbKnots() + 1)])
        result.append((cp, unit_knots(knots), c.Degree()))
    return result


def check_apertures(state, spec, values):
    is_button = 'base_height_mm' in spec and spec['model'] == 'mac-mini'
    count = 1 if is_button else spec.get('expected_ports', 0)
    actual = [s for s in state['supports'] if s['type'] == 'NativeExtrusion'
              and s['profile'].get('degree') == 3]
    need(len(actual) == count, f'Interface support count: {len(actual)} != {count}')
    if not count:
        return {'matched_curves': 0}
    axes = [0, 1] if is_button else [0, 2]
    expected = []
    for points, knots, degree in aperture_curves(spec['model'], spec['wall_mm'], is_button):
        cp = points.copy()
        if not is_button:
            cp[:, 2] += values['PortHeightOffset']
        expected.append((cp[:, axes], knots, degree))
    proof = match_curves(actual, expected, axes)
    proof['max_evaluation_error_mm'] = max(check_samples(s) for s in actual)
    if not is_button:
        ports = definition(spec['model'], spec['wall_mm'])['side_apertures']
        for surface in actual:
            cp, _, _ = curve_data(surface['profile'])
            matches = [float(np.max(np.linalg.norm(cp[:, axes] - p[0], axis=1))) for p in expected]
            index = int(np.argmin(matches))
            sign = ports[index]['side_y_sign']
            need(all(np.sign(s['point'][1]) == sign for s in surface['samples']), 'Interface is on the wrong side')
            close(np.abs(surface['direction']), [0, 1, 0], 'Interface extrusion direction', 1e-12)
    return proof


def axes_key(center, normal):
    normal = normal / np.linalg.norm(normal, axis=1)[:, None]
    sign = np.sign(normal[np.arange(len(normal)), np.argmax(abs(normal), axis=1)])
    normal = normal * sign[:, None]
    projection = center - np.sum(center * normal, axis=1)[:, None] * normal
    return np.column_stack((projection, normal * 100))


def expected_base_bores(spec, v):
    angle = math.radians(v['ConeAngle'])
    h, t, r, clearance = (v[k] for k in ('BaseHeight', 'PlateThickness', 'LowerRadius', 'VentClearance'))
    if spec['model'] == 'mac-studio':
        rings, count, diameter = int(2 * v['RingPairs']), int(v['HolesPerRing']), v['VentDiameter']
        low = (clearance + diameter / 2) * math.sin(angle)
        z = np.linspace(low, h - t - low, rings)
        theta = np.array([(np.arange(count) + .5 * (ring % 2)) * 2 * math.pi / count for ring in range(rings)]).ravel()
        z = np.repeat(z, count)
        radius = r + z / math.tan(angle)
        center = np.column_stack((radius * np.cos(theta), radius * np.sin(theta), z))
        normal = np.column_stack((math.sin(angle) * np.cos(theta), math.sin(angle) * np.sin(theta), np.full(len(z), -math.cos(angle))))
        return center, normal, diameter / 2, rings * count
    count, width = int(v['VentCount']), v['VentWidth']
    theta = math.radians(v['VentPhase']) + np.arange(count) * 2 * math.pi / count
    z = (h - t) / 2
    radius = r + z / math.tan(angle)
    center = np.column_stack((radius * np.cos(theta), radius * np.sin(theta), np.full(count, z)))
    tangent = np.column_stack((math.cos(angle) * np.cos(theta), math.cos(angle) * np.sin(theta), np.full(count, math.sin(angle))))
    normal = np.column_stack((math.sin(angle) * np.cos(theta), math.sin(angle) * np.sin(theta), np.full(count, -math.cos(angle))))
    half_straight = ((h - t) / math.sin(angle) - 2 * clearance - width) / 2
    return np.vstack((center - tangent * half_straight, center + tangent * half_straight)), np.vstack((normal, normal)), width / 2, count + 1


def expected_rear_bores(spec, v):
    from enclosure.studio_rear_pattern import make_pattern, measure_wrapped_centers
    d = definition(spec['model'], spec['wall_mm'])
    controls = np.asarray(profiles()['mac-studio']['outer']['controls_mm'])
    table = make_pattern(controls, d['rear_grid_design'])
    proof = measure_wrapped_centers(table, controls, d['rear_grid_design'])
    need(proof['passed'], 'Planar grid wrapping definition failed')
    centers, normals = [], []
    for arc in np.unique(table[:, 3]):
        column = table[table[:, 3] == arc]
        first = column[np.argmin(column[:, 6])]
        parity = int(first[1]) % 2
        count = int(v['RearRowPairs']) + (1 - parity)
        z = v['RearBottomZ'] + (parity + 2 * np.arange(count)) * v['RearRowPitch']
        centers.extend(np.column_stack((np.full(count, first[4]), np.full(count, first[5]), z)))
        normals.extend(np.repeat(first[None, 7:10], count, axis=0))
    return np.array(centers), np.array(normals), v['RearHoleDiameter'] / 2, len(centers) + spec['expected_ports']


def check_bores(state, spec, values):
    if 'base_height_mm' in spec:
        center, normal, radius, holes = expected_base_bores(spec, values)
    elif spec.get('expected_rear_bores'):
        center, normal, radius, holes = expected_rear_bores(spec, values)
    else:
        need(not state['cylinders'], 'Unexpected cylinder faces')
        holes = spec.get('expected_ports', 0)
        need(state['boundary_euler_characteristic'] == 2 - 2 * holes, 'Solid aperture topology differs')
        return {'cylinder_axes': 0, 'through_openings': holes}
    actual = np.asarray(state['cylinders'])
    need(actual.ndim == 2 and actual.shape[1] == 7, 'Cylinder support data missing')
    expected = axes_key(center, normal)
    keys = axes_key(actual[:, :3] * 1000, actual[:, 3:6])
    distances, indices = cKDTree(expected).query(keys)
    error = float(np.max(distances))
    need(error <= TOL, f'Bore center or normal differs: {error} mm')
    need(set(indices) == set(range(len(expected))), 'Required bores are missing')
    radius_error = close(actual[:, 6] * 1000, np.full(len(actual), radius), 'Bore radius')
    slot_wall_error = 0.
    if 'base_height_mm' in spec and spec['model'] == 'mac-mini':
        count = int(values['VentCount'])
        theta = math.radians(values['VentPhase']) + np.arange(count) * 2 * math.pi / count
        target = []
        for a in theta:
            n = np.array([-math.sin(a), math.cos(a), 0.])
            for sign in (-1, 1):
                d = sign * values['VentWidth'] / 2
                canonical = np.sign(n[np.argmax(abs(n))])
                target.append(np.r_[n * canonical * 100, d * canonical])
        found = []
        for plane in state['planes']:
            p = np.asarray(plane['parameters'])
            n, origin = p[:3], p[3:] * 1000
            d = np.dot(n, origin)
            if abs(n[2]) < 1e-10 and abs(abs(d) - values['VentWidth'] / 2) < TOL:
                canonical = np.sign(n[np.argmax(abs(n))])
                found.append(np.r_[n * canonical * 100, d * canonical])
        need(len(found) == 2 * count, 'Mini capsule straight walls are missing')
        # Every actual wall consumes one expected wall, including coplanar pairs.
        costs = np.linalg.norm(np.asarray(found)[:, None, :] - np.asarray(target)[None, :, :], axis=2)
        actual_indexes, expected_indexes = linear_sum_assignment(costs)
        need(len(actual_indexes) == 2 * count and len(set(expected_indexes)) == 2 * count,
             'Mini capsule wall multiplicities differ')
        slot_wall_error = float(max(costs[actual_indexes, expected_indexes]))
        need(slot_wall_error <= TOL, f'Mini capsule straight walls differ: {slot_wall_error} mm')
    need(state['boundary_euler_characteristic'] == 2 - 2 * holes,
         f'Bore topology: {state["boundary_euler_characteristic"]} != {2-2*holes}')
    return {'cylinder_axes': len(expected), 'through_openings': holes,
            'max_axis_key_error_mm': error, 'max_radius_error_mm': radius_error,
            'max_capsule_wall_error_mm': slot_wall_error}


def check_state(state, spec, edited=False):
    need(state['body_count'] == 1 and state['body_faults'] == 0, 'Native solid validity failed')
    need(all(f['error'] == 0 for f in state['features']), 'Native feature has an error or warning')
    need(all(not f['suppressed'] for f in state['features']), 'Required native feature is suppressed')
    need(all(s['type'] == 'NativeExtrusion' and s['profile'].get('degree') in (3, 7)
             for s in state['supports']), 'Unrecognized support surface in native part')
    v = parameters(state)
    model, wall = spec['model'], spec['wall_mm']
    design = definition(model, wall)
    base = 'base_height_mm' in spec
    width = 127 if model == 'mac-mini' else 197
    if base:
        source = design['base_design']
        close([spec['base_height_mm'], spec['cone_angle_degrees'], v['LowerRadius'], v['VentClearance']],
              [source['height_mm'], source['cone_angle_to_horizontal_degrees'], source['outer_cone_radius_intercept_mm'], .75],
              'Base authoritative design binding')
        if model == 'mac-mini':
            phase = read(ROOT / 'results/masters/mac-mini/enclosure-2mm/uniform_vent_pattern.json')['phase_radians']
            close([v['VentPhase']], [math.degrees(phase)], 'Mini design phase', 1e-10)
        h = spec['base_height_mm'] + (1 if edited else 0)
        alpha = spec['cone_angle_degrees'] + (5 if edited else 0)
        close([v['BaseHeight'], v['ConeAngle'], v['PlateThickness']], [h, alpha, 1.5], 'Base parameter mutation')
        if model == 'mac-studio':
            close([v['VentDiameter'], v['HolesPerRing'], v['RingPairs']],
                  [1.6, 200, 3] if edited else [1.5, 244, 4], 'Studio array mutation')
        else:
            close([v['VentWidth'], v['VentCount']], [2.2, 96] if edited else [2, 108], 'Mini array mutation')
        width -= 2 * wall
        plane_z = [0, 1.5, h - 1.5, h]
        angle = math.radians(alpha)
        expected_cones = sorted([v['LowerRadius'], v['LowerRadius'] - 1.5 / math.sin(angle)])
        need(len(state['cones']) == 2, 'Expected two directly extended conical supports')
        close(sorted(c['intercept_mm'] for c in state['cones']), expected_cones, 'Cone normal wall thickness')
        close([c['slope'] for c in state['cones']], [1 / math.tan(angle)] * 2, 'Cone angle', 1e-10)
    else:
        nominal = design['nominal_dimensions_mm'][2] - design['base_design']['interface_z_mm'] if spec['perforated'] else (
            1 if spec['height_mm'] == 1 else (50 if model == 'mac-mini' else 95))
        close([spec['height_mm']], [nominal], 'Housing authoritative height')
        ports = len(design['side_apertures']) if spec['perforated'] else 0
        need(spec['expected_ports'] == ports, 'Authoritative interface inventory differs')
        need(spec['expected_rear_bores'] == (2309 if spec['perforated'] and model == 'mac-studio' else 0),
             'Authoritative rear bore inventory differs')
        h = spec['height_mm'] + (2 if edited else 0)
        close([v['HousingHeight']], [h], 'Housing height mutation')
        plane_z = [0, h]
        if wall:
            top = wall + (.5 if edited else 0)
            close([v['TopThickness']], [top], 'Housing top thickness mutation')
            plane_z = [0, h - top, h]
        if spec['perforated']:
            close([v['PortHeightOffset']], [1 if edited else 0], 'Interface height mutation')
            if model == 'mac-studio':
                close([v['RearHoleDiameter'], v['RearRowPairs']], [1.6, 12] if edited else [1.5, 13], 'Rear grid mutation')
                from enclosure.studio_rear_pattern import make_pattern
                grid = make_pattern(np.asarray(profiles()[model]['outer']['controls_mm']), design['rear_grid_design'])
                row_pitch = design['rear_grid_design']['horizontal_pitch_mm'] * design['rear_grid_design']['vertical_pitch_to_horizontal_ratio']
                close([v['RearRowPitch'], v['RearBottomZ']],
                      [row_pitch, min(grid[:, 6]) - design['base_design']['interface_z_mm']], 'Rear grid authoritative position')
    bounds_error = close(state['bounds_mm'], [-width / 2, -width / 2, 0, width / 2, width / 2, h], 'Actual solid dimensions')
    z = np.array([p['parameters'][5] * 1000 for p in state['planes'] if abs(abs(p['parameters'][2]) - 1) < 1e-10])
    need(len(z) >= len(plane_z), 'Horizontal support planes are missing')
    distances, indexes = cKDTree(np.asarray(plane_z)[:, None]).query(z[:, None])
    need(max(distances) <= TOL and set(indexes) == set(range(len(plane_z))), 'Actual horizontal plane heights differ')
    half_widths = [width / 2]
    if not base and wall:
        half_widths.append(width / 2 - wall)
    expected_sides = [(axis, sign * half) for axis in (0, 1) for half in half_widths for sign in (-1, 1)]
    side_matches, side_error = set(), 0.
    for plane in state['planes']:
        data = np.asarray(plane['parameters'])
        axis = int(np.argmax(abs(data[:3])))
        if axis > 1 or np.max(abs(np.delete(data[:3], axis))) > 1e-10:
            continue
        candidates = [(abs(data[3 + axis] * 1000 - coordinate), index)
                      for index, (direction, coordinate) in enumerate(expected_sides) if direction == axis]
        error, index = min(candidates)
        need(error <= TOL, 'Straight inner or outer side plane changed')
        side_matches.add(index)
        side_error = max(side_error, error)
    need(side_matches == set(range(len(expected_sides))), 'Straight inner or outer side planes are missing')
    features = {f['name']: f['type'] for f in state['features']}
    if base:
        need(features.get('OuterCone') == 'Boss' and features.get('InnerCone') == 'Cut', 'Editable cone features missing')
        need(features.get('MatingPlateThickness') == 'MoveFace', 'Editable mating plate missing')
        outer = next(f for f in state['features'] if f['name'] == 'OuterCone')
        close([outer['dimensions']['D1@OuterCone'] * 1000], [h - 1.5], 'Outer cone must end at mating plate underside')
    else:
        need(features.get('ExtrusionHeight') == 'MoveFace', 'Editable exact-profile housing height missing')
        for index in range(spec['expected_ports']):
            need(features.get(f'Port{index+1:02d}Position') == 'MoveCopyBody' and
                 features.get(f'Port{index+1:02d}Cut') == 'CombineBodies', 'Editable interface features missing')
    return {'bounds_error_mm': bounds_error, 'side_plane_error_mm': side_error, 'g3': check_g3(state, spec),
            'interfaces': check_apertures(state, spec, v), 'bores': check_bores(state, spec, v)}


def check_bindings(packet):
    for section in ('implementation_source_bindings', 'design_source_bindings'):
        for name, digest in packet[section].items():
            path = Path(name)
            if not path.is_absolute():
                path = ROOT / path
            need(path.is_file() and sha(path) == digest, f'Source binding mismatch: {name}')


def check_part(path, output):
    packet = read(path)
    check_bindings(packet)
    native = output / packet['file']
    need(native.is_file() and sha(native) == packet['file_sha256'], 'Native file hash mismatch')
    need(packet['native_reopen'], 'Native file has not been reopened')
    need(packet['external_file_dependencies'] == [], 'Native part depends on external construction files')
    spec = packet['specification']
    result = {'file': packet['file'], 'sha256': packet['file_sha256'], 'states': {}}
    for name in ('baseline', 'edited_parameters', 'restored'):
        result['states'][name] = check_state(packet['tests'][name], spec, name == 'edited_parameters')
    result['states']['native_reopen'] = check_state(packet['final'], spec)
    result['passed'] = True
    return result


def check_assembly(path, output):
    packet = read(path)
    check_bindings(packet)
    need(sha(output / packet['file']) == packet['file_sha256'], 'Native assembly hash mismatch')
    need(packet['native_reopen'], 'Native assembly has not been reopened')
    for file, digest in packet['dependencies'].items():
        need(sha(output / file) == digest, f'Native assembly dependency changed: {file}')
    dependencies = {name.casefold(): name for name in packet['dependencies']}
    need(len(dependencies) == len(packet['dependencies']), 'Ambiguous assembly dependency names')
    spec = packet['specification']
    mini = spec['model'] == 'mac-mini'
    width, height, base = (127, 49.5, 8) if mini else (197, 95, 10)
    states = dict(packet['tests'], native_reopen=packet['final'])
    result = {'file': packet['file'], 'sha256': packet['file_sha256'], 'states': {}}
    for name, state in states.items():
        delta = 1 if name == 'edited_base_height' else 0
        need(state['component_count'] == 2, 'Native assembly component count')
        need(len(state['mates']) == 3 and all(m['error'] == 0 for m in state['mates']), 'Native assembly mate errors')
        error = close(state['bounds_mm'], [-width/2, -width/2, 0, width/2, width/2, height+delta], 'Assembly actual height')
        for component in state['components']:
            file = component['file'].casefold()
            bottom = file.endswith('_base.sldprt')
            need(file in dependencies, 'Unexpected assembly dependency')
            need((output / component['file']).samefile(output / dependencies[file]), 'Assembly dependency file identity differs')
            need(component['body_faults'] == 0, 'Assembly component body faults')
            need(component['fixed_component'] == bottom, 'Assembly fixing differs from mate design')
            z = 0 if bottom else base - 1.5 + delta
            transform = [1,0,0,0,1,0,0,0,1,0,0,z/1000,1,0,0,0]
            close(component['transform'], transform, 'Native component placement', 1e-10)
            if bottom:
                w = width - 2 * spec['wall_mm']
                expected = [-w/2, -w/2, 0, w/2, w/2, base+delta]
            else:
                expected = [-width/2, -width/2, z, width/2, width/2, height+delta]
            close(component['bounds_mm'], expected, 'Mated component dimensions')
        result['states'][name] = {'bounds_error_mm': error, 'passed': True}
    result['passed'] = True
    return result


def check_default_session(evidence, output, accepted_parts):
    packet = read(evidence / 'default-session.json')
    need(packet['read_only'] and not packet['modeler_tolerances_modified'], 'Default-session inspection settings differ')
    for name, digest in packet['source_sha256'].items():
        need(sha(ROOT / name) == digest, f'Default-session reader changed: {name}')
    required = {part['file'] for part in accepted_parts}
    files = packet['files']
    need(len(files) == 16 and {f['file'] for f in files} == required, 'Default-session native inventory differs')
    results = []
    for item in files:
        need(item['cad_unchanged'] and sha(output / item['file']) == item['file_sha256'], 'Default-session CAD hash differs')
        original = read(evidence / (Path(item['file']).stem + '.native.json'))
        state = check_state(item['state'], original['specification'])
        for view in item['images']:
            need(sha(evidence / view['file']) == view['sha256'], 'Native inspection image changed')
        results.append({'file': item['file'], 'passed': True, 'geometry': state})
    return {'passed': True, 'parts': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/SW')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'validation/solidworks-native')
    args = parser.parse_args()
    results = []
    for path in sorted(args.evidence.glob('*.native.json')):
        result = check_part(path, args.output)
        results.append(result)
        print('PASS', result['file'])
    need(len(results) == 16, f'Expected 16 native parts, found {len(results)}')
    assemblies = [check_assembly(p, args.output) for p in sorted(args.evidence.glob('*.assembly.json'))]
    need(len(assemblies) == 4, f'Expected four native assemblies, found {len(assemblies)}')
    expected_files = {p['file'] for p in results + assemblies}
    required_files = set()
    for model in ('mac-mini', 'mac-studio'):
        for suffix in ('solid', '1mm-solid', 'plain-shell_2mm', 'plain-shell_3mm'):
            required_files.add(f'{model}_{suffix}.sldprt')
        for wall in (2, 3):
            for role in ('housing', 'base', 'assembly'):
                required_files.add(f'{model}_enclosure_{wall}mm_{role}.sldasm' if role == 'assembly' else
                                   f'{model}_enclosure_{wall}mm_{role}.sldprt')
    need(expected_files == required_files, 'Required model variants are missing or unexpected')
    native_files = {p.name.casefold() for p in args.output.iterdir() if p.suffix.lower() in ('.sldprt', '.sldasm')}
    need(native_files == expected_files, 'Native delivery inventory differs from acceptance')
    default_session = check_default_session(args.evidence, args.output, results)
    report = {'schema': 'solidworks-native-acceptance-v1', 'passed': True,
              'verifier_file': 'solidworks/verify.py', 'verifier_sha256': sha(Path(__file__)),
              'curve_control_tolerance_mm': TOL, 'normalized_knot_tolerance': KNOT_TOL,
              'parts': results, 'assemblies': assemblies, 'default_session': default_session,
              'evidence_sha256': {p.name: sha(p) for p in sorted(args.evidence.glob('*.json')) if p.name != 'acceptance.json'}}
    (args.evidence / 'acceptance.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('PASS: 16 native parts, four mated assemblies, and default-session rebuild geometry')


if __name__ == '__main__':
    main()
