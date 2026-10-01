"""A regular planar staggered grid wrapped onto the Studio by profile arc length."""
import math
import numpy as np
from .rear_profile import RearProfile

FIELDS=('hole_id','row','column','s_mm','x_mm','y_mm','z_mm','nx','ny','nz','radius_mm','completed_uv_seam')


def grid_layout(definition):
    pitch=definition['horizontal_pitch_mm']
    vertical=pitch*definition['vertical_pitch_to_horizontal_ratio']
    low,high=definition['band_z_range_mm']
    columns=math.floor(2*definition['maximum_unwrapped_half_width_mm']/pitch)+1
    rows=math.floor((high-low)/vertical)
    if columns<3 or rows<2 or min(pitch,vertical)<=definition['diameter_mm']:
        raise ValueError('Rear grid has insufficient room between circles')
    return pitch,vertical,columns,rows,(low+high)/2


def make_pattern(controls,definition):
    pitch,vertical,columns,rows,center=grid_layout(definition)
    profile=RearProfile(controls);result=[];start=0
    for row in range(rows):
        count=columns-row%2
        arcs=(np.arange(count)-(count-1)/2)*pitch
        xy,tangent=profile.evaluate(arcs)
        z=center+(row-(rows-1)/2)*vertical
        inward=np.c_[-tangent[:,1],tangent[:,0],np.zeros(count)]
        result.extend(np.column_stack((np.arange(start,start+count),np.full(count,row),np.arange(count),
                      arcs,xy,np.full(count,z),inward,np.full(count,definition['diameter_mm']/2),np.zeros(count))))
        start+=count
    return np.array(result)


def write_pattern(path,data):
    np.savetxt(path,data,delimiter=',',fmt='%.17e',comments='',header=','.join(FIELDS))


def inspect_pattern(table,controls,definition,tolerance=1e-7):
    expected=make_pattern(controls,definition)
    actual=np.column_stack([table[name] for name in FIELDS]) if table.dtype.names else np.asarray(table)
    if actual.shape!=expected.shape:raise ValueError('Rear pattern count differs from its design')
    pitch,vertical,columns,rows,center=grid_layout(definition)
    error=float(np.max(abs(actual-expected)))
    triangles=[]
    for row in range(rows-1):
        first=actual[actual[:,1]==row];following=actual[actual[:,1]==row+1]
        first=first[np.argsort(first[:,3])];following=following[np.argsort(following[:,3])]
        for left,right in zip(first[:-1],first[1:]):
            middle=(left[3]+right[3])/2
            apex=following[np.argmin(abs(following[:,3]-middle))]
            lengths=[float(np.linalg.norm(point[[3,6]]-apex[[3,6]])) for point in (left,right)]
            triangles.append(abs(lengths[0]-lengths[1]))
    return {'passed':bool(error<=tolerance and max(triangles)<=tolerance),
            'placement':'regular planar staggered grid wrapped by outer-profile arc length',
            'hole_count':len(actual),'row_count':rows,'alternating_row_counts':[columns,columns-1],
            'diameter_mm':definition['diameter_mm'],'horizontal_pitch_mm':pitch,'vertical_pitch_mm':vertical,
            'adjacent_row_shift_mm':pitch/2,'tested_unwrapped_triangles':len(triangles),
            'maximum_unwrapped_equal_side_error_mm':max(triangles),
            'maximum_pattern_parameter_error':error,'tolerance_mm':tolerance}


def measure_wrapped_centers(table,controls,definition,tolerance=1e-7):
    """Recover planar center coordinates independently using adaptive arc integration."""
    from scipy.integrate import quad
    from scipy.optimize import brentq
    from .rear_profile import bezier
    actual=np.column_stack([table[name] for name in FIELDS]) if table.dtype.names else np.asarray(table)
    proof=inspect_pattern(actual,controls,definition,tolerance)
    profile=RearProfile(controls);measured=actual.copy();lookup={};surface_error=0.;integration_error=0.
    for x,y in np.unique(actual[:,4:6],axis=0):
        if abs(x)<=profile.flat_half_length:
            arc=x;residual=abs(y-profile.cp[0,1])
        else:
            parameter=brentq(lambda t:bezier(profile.cp,[t])[0,0]-abs(x),0.,1.,xtol=1e-14)
            length,error=quad(lambda t:np.linalg.norm(bezier(profile.dcp,[t])[0]),0.,parameter,epsabs=1e-10,epsrel=1e-12)
            arc=math.copysign(profile.flat_half_length+length,x)
            residual=abs(bezier(profile.cp,[parameter])[0,1]-y);integration_error=max(integration_error,error)
        lookup[(x,y)]=arc;surface_error=max(surface_error,residual)
    measured[:,3]=[lookup[tuple(xy)] for xy in actual[:,4:6]]
    recovered=inspect_pattern(measured,controls,definition,tolerance)
    arc_error=float(np.max(abs(measured[:,3]-actual[:,3])))
    proof.update(recovered_unwrapped_centers=len(actual),maximum_recovered_arc_error_mm=arc_error,
                 maximum_center_on_profile_error_mm=float(surface_error),adaptive_integration_error_estimate_mm=integration_error,
                 maximum_recovered_equal_side_error_mm=recovered['maximum_unwrapped_equal_side_error_mm'])
    proof['passed']=bool(proof['passed'] and recovered['passed'] and max(arc_error,surface_error,integration_error)<=tolerance)
    return proof
