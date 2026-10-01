"""Horizontal rings of normal circular bores on the Studio conical base."""
import math
import numpy as np


def ring_layout(definition):
    factor=math.hypot(1.,definition['cone_slope_dr_dz'])
    radius=definition['vent_diameter_mm']/2
    low=(definition['vent_clearance_along_cone_mm']+radius)/factor
    high=definition['interface_z_mm']-low
    levels=np.linspace(low,high,definition['base_ring_count'])
    smallest_radius=definition['outer_cone_radius_intercept_mm']+definition['cone_slope_dr_dz']*low
    count=math.floor(2*math.pi*smallest_radius/definition['base_minimum_center_pitch_mm'])
    count-=count%2
    if count<4 or (levels[1]-levels[0])*factor<=2*radius:raise ValueError('Bore spacing is too small')
    return levels,count


def ring_indices(data,definition):
    data = np.asarray(data, dtype=float)
    levels,count=ring_layout(definition)
    if data.shape != (len(levels)*count, 7) or not np.isfinite(data).all():
        raise ValueError('Unexpected bore count or nonfinite center/normal/radius rows')
    order = np.argsort(data[:, 2])
    groups = np.split(order, np.flatnonzero(np.diff(data[order, 2]) > .1) + 1)
    if len(groups) != len(levels) or any(len(group) != count for group in groups):
        raise ValueError('Studio bore rings differ from the design count')
    return groups


def inspect_pattern(data, definition, tolerance=1e-9):
    """Check every center against its horizontal ring and analytic cone."""
    data = np.asarray(data, dtype=float)
    groups = ring_indices(data,definition)
    levels,count=ring_layout(definition)
    slope = definition['cone_slope_dr_dz']
    intercept = definition['outer_cone_radius_intercept_mm']
    factor = math.hypot(1., slope)
    theta = np.arctan2(data[:, 1], data[:, 0])
    expected_normals = np.column_stack((np.cos(theta)/factor, np.sin(theta)/factor,
                                       np.full(len(data), -slope/factor)))
    rings = [{'ring': index + 1, 'holes': len(group),
              'center_height_mm': float(data[group[0], 2]),
              'height_range_mm': float(np.ptp(data[group, 2]))}
             for index, group in enumerate(groups)]
    low = data[groups[0], 2]*factor - data[groups[0], 6]
    high = (definition['interface_z_mm']-data[groups[-1], 2])*factor-data[groups[-1], 6]
    cone_error = float(np.max(np.abs(np.hypot(data[:, 0], data[:, 1])-intercept-slope*data[:, 2])))
    normal_error = float(np.max(np.abs(data[:, 3:6]-expected_normals)))
    radius_range = float(np.ptp(data[:, 6]))
    radius_error=float(np.max(abs(data[:,6]-definition['vent_diameter_mm']/2)))
    level_error=float(max(np.max(abs(data[group,2]-level)) for group,level in zip(groups,levels)))
    angle_error=0.
    for group in groups:
        angles=np.sort(theta[group]%(2*math.pi))
        gaps=np.diff(np.r_[angles,angles[0]+2*math.pi])
        angle_error=max(angle_error,float(np.max(abs(gaps-2*math.pi/count))))
    clearance_error = float(max(np.max(np.abs(low-.75)), np.max(np.abs(high-.75))))
    return {'passed': bool(max(r['height_range_mm'] for r in rings) <= tolerance
                          and max(cone_error, normal_error, radius_error, level_error,angle_error,clearance_error) <= tolerance),
            'rings': rings, 'ring_count': len(levels), 'holes_per_ring': count,
            'maximum_ring_height_range_mm': max(r['height_range_mm'] for r in rings),
            'maximum_center_on_cone_error_mm': cone_error, 'maximum_normal_component_error': normal_error,
            'radius_range_mm': radius_range,'maximum_radius_error_mm':radius_error,
            'maximum_design_height_error_mm':level_error,'maximum_angular_pitch_error_radians':angle_error,
            'outermost_ring_clearance_error_mm': clearance_error,
            'lower_ring_clearance_range_mm': [float(low.min()), float(low.max())],
            'upper_ring_clearance_range_mm': [float(high.min()), float(high.max())],
            'height_tolerance_mm': tolerance}


def circular_pattern(definition):
    """Build horizontal circular rings with a uniform alternating angular pitch."""
    levels,count=ring_layout(definition)
    slope = definition['cone_slope_dr_dz']
    factor = math.hypot(1., slope)
    theta=np.concatenate([(np.arange(count)+(index%2)*.5)*2*math.pi/count for index in range(len(levels))])
    z=np.repeat(levels,count)
    radii = definition['outer_cone_radius_intercept_mm']+slope*z
    result=np.column_stack((radii*np.cos(theta),radii*np.sin(theta),z,np.cos(theta)/factor,
                            np.sin(theta)/factor,np.full(len(z),-slope/factor),np.full(len(z),definition['vent_diameter_mm']/2)))
    if not inspect_pattern(result, definition)['passed']:
        raise ValueError('Horizontal ring construction failed')
    return result


def write_pattern(path, data):
    np.savetxt(path, data, delimiter=',', fmt='%.17e', comments='',
               header='x_mm,y_mm,z_mm,normal_x,normal_y,normal_z,radius_mm')


def measure_horizontal_rings(shape, expected, definition):
    """Recover hole centers from actual cylinder axes intersecting the cone."""
    from scipy.spatial import cKDTree
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    expected=np.asarray(expected,dtype=float)
    def axis_key(point,direction):
        direction=np.asarray(direction,dtype=float)
        if direction[np.argmax(np.abs(direction))]<0:direction=-direction
        return np.r_[point-np.dot(point,direction)*direction,100*direction]
    tree=cKDTree([axis_key(row[:3],row[3:6]) for row in expected])
    slope=definition['cone_slope_dr_dz'];intercept=definition['outer_cone_radius_intercept_mm']
    actual=expected.copy();seen=set();maximum_error=0.;duplicate_error=0.
    for face in shape.Faces():
        if face.geomType()!='CYLINDER':continue
        cylinder=BRepAdaptor_Surface(face.wrapped).Cylinder();axis=cylinder.Axis()
        point=np.array(axis.Location().Coord());direction=np.array(axis.Direction().Coord())
        distance,index=tree.query(axis_key(point,direction));index=int(index)
        if distance>1e-5:continue
        a=np.dot(direction[:2],direction[:2])-(slope*direction[2])**2
        b=2*(np.dot(point[:2],direction[:2])-slope*direction[2]*(intercept+slope*point[2]))
        c=np.dot(point[:2],point[:2])-(intercept+slope*point[2])**2
        roots=np.roots([a,b,c])
        intersections=[point+float(t.real)*direction for t in roots if abs(t.imag)<1e-10]
        if not intersections:raise ValueError('A bore axis does not meet its outer cone')
        center=min(intersections,key=lambda p:np.linalg.norm(p-expected[index,:3]))
        maximum_error=max(maximum_error,float(np.linalg.norm(center-expected[index,:3])))
        if index in seen:duplicate_error=max(duplicate_error,float(np.linalg.norm(center-actual[index,:3])))
        actual[index,:3]=center
        actual[index,3:6]=direction if np.dot(direction,expected[index,3:6])>0 else -direction
        actual[index,6]=cylinder.Radius();seen.add(index)
    proof=inspect_pattern(actual,definition,tolerance=1e-7)
    proof.update(method='Actual analytic cylinder axes intersected with the outer cone',
                 recovered_hole_centers=len(seen),maximum_center_to_table_error_mm=maximum_error,
                 maximum_duplicate_axis_center_error_mm=duplicate_error)
    proof['passed']=bool(proof['passed'] and len(seen)==len(expected) and max(maximum_error,duplicate_error)<1e-7)
    return proof
