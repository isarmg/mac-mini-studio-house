"""Draw the frozen mathematical profiles without refitting or importing project code.

Standard library only for SVG/CSV. --rhino additionally uses rhino3dm.
The SVG/CSV are sampled previews; the optional 3DM stores the exact spline data.
"""
import argparse
import csv
import json
import math
from pathlib import Path


def bezier(controls, t):
    """de Casteljau evaluation, including exact stored endpoints."""
    if not 0 <= t <= 1:
        raise ValueError("Parameter outside [0, 1]")
    q = [list(p) for p in controls]
    while len(q) > 1:
        q = [[(1-t)*a+t*b for a, b in zip(q[i], q[i+1])] for i in range(len(q)-1)]
    return q[0]


def expand_knots(curve):
    return [u for u, n in zip(curve['knots'], curve['multiplicities']) for _ in range(n)]


def bspline(curve, t):
    """Homogeneous de Boor evaluation of the supplied full-precision NURBS."""
    p = curve['degree']; knots = expand_knots(curve); poles = curve['controls_mm']
    n = len(poles)-1
    if not knots[p] <= t <= knots[n+1]:
        raise ValueError("Parameter outside spline domain")
    span = n if t == knots[n+1] else next(i for i in range(p, n+1) if knots[i] <= t < knots[i+1])
    weights = curve.get('weights', [1.0]*len(poles))
    d = [[x*weights[j] for x in poles[j]]+[weights[j]] for j in range(span-p, span+1)]
    for r in range(1, p+1):
        for j in range(p, r-1, -1):
            i = span-p+j; denominator = knots[i+p-r+1]-knots[i]
            a = (t-knots[i])/denominator if denominator else 0.0
            d[j] = [(1-a)*x+a*y for x, y in zip(d[j-1], d[j])]
    return [x/d[p][-1] for x in d[p][:-1]]


def rotate(point, q):
    x, y = point[:2]
    return [(x, y), (y, -x), (-x, -y), (-y, x)][q % 4]


def quarter(profile, wall=None):
    if wall is None:
        return lambda t: bezier(profile['outer']['controls_mm'], t)
    curve = profile['inner'][str(wall)]
    return lambda t: bspline(curve, t)


def point(profile, u, wall=None):
    """Full closed outline parameter u in [0,8], clockwise, curve then line."""
    if not 0 <= u <= 8:
        raise ValueError("Full-outline parameter outside [0, 8]")
    if u == 8:
        u = 0.0
    segment = int(u); t = u-segment; q = segment//2; curve = quarter(profile, wall)
    if segment % 2 == 0:
        return rotate(curve(t), q)
    a = rotate(curve(1.0), q); b = rotate(curve(0.0), q+1)
    return tuple((1-t)*x+t*y for x, y in zip(a, b))


def sample(profile, samples=401, wall=None):
    if samples < 2:
        raise ValueError("At least two samples per corner")
    rows = []
    for q in range(4):
        rows.extend((2*q+i/(samples-1), *point(profile, 2*q+i/(samples-1), wall)) for i in range(samples))
        rows.append((2*q+2, *point(profile, 2*q+2, wall)))
    return rows


def rhino_outline(profile, wall=None):
    """Exact degree-seven spline objects, not an interpolated point cloud."""
    import rhino3dm as r
    definition = profile['outer'] if wall is None else profile['inner'][str(wall)]
    full_knots = expand_knots(definition)
    poly = r.PolyCurve()
    for q in range(4):
        curve = r.NurbsCurve(3, any(w != 1 for w in definition['weights']),
                             definition['degree']+1, len(definition['controls_mm']))
        for i, (p, w) in enumerate(zip(definition['controls_mm'], definition['weights'])):
            x, y = rotate(p, q)
            curve.Points[i] = r.Point4d(x*w, y*w, 0.0, w)
        for i, value in enumerate(full_knots[1:-1]):
            curve.Knots[i] = value
        assert curve.IsValid
        poly.Append(curve)
        a = rotate(definition['controls_mm'][-1], q)
        b = rotate(definition['controls_mm'][0], q+1)
        poly.Append(r.LineCurve(r.Point3d(*a, 0), r.Point3d(*b, 0)))
    assert poly.IsValid and poly.IsClosed and poly.SegmentCount == 8
    return poly


def write_outputs(data, output, samples, with_rhino=False):
    output.mkdir(parents=True, exist_ok=True)
    for name, profile in data['profiles'].items():
        half = profile['outer']['controls_mm'][0][1]; pad = 6; paths = []
        for wall, color in ((None, '#215d9c'), (2, '#12886f'), (3, '#c47522')):
            rows = sample(profile, samples, wall)
            label = 'outer' if wall is None else f'inner_{wall}mm'
            with (output/f'{name}_{label}.csv').open('w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f); writer.writerow(['u', 'x_mm', 'y_mm']); writer.writerows(rows)
            coordinates = ' '.join(f'{x:.17g},{-y:.17g}' for _, x, y in rows)
            paths.append(f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="0.35"/>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-half-pad} {-half-pad} {2*(half+pad)} {2*(half+pad)}">'
               '<title>Frozen G3 profiles in millimetres; sampled preview</title>' + ''.join(paths) + '</svg>')
        (output/f'{name}_profiles.svg').write_text(svg, encoding='utf-8')
        if with_rhino:
            import rhino3dm as r
            doc = r.File3dm(); doc.Settings.ModelUnitSystem = r.UnitSystem.Millimeters
            for wall in (None, 2, 3):
                attributes = r.ObjectAttributes(); attributes.Name = 'outer' if wall is None else f'inner_{wall}mm'
                doc.Objects.AddCurve(rhino_outline(profile, wall), attributes)
            if not doc.Write(str(output/f'{name}_exact_profiles.3dm'), 8):
                raise IOError('Rhino curve export failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).with_name('geometry_definition.json'))
    parser.add_argument('--out', type=Path, default=Path('reproduced-profiles'))
    parser.add_argument('--samples', type=int, default=401)
    parser.add_argument('--rhino', action='store_true')
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding='utf-8'))
    write_outputs(data, args.out, args.samples, args.rhino)
    print('Saved formula-based profiles:', args.out.resolve())


if __name__ == '__main__':
    main()
