"""Strict native-data verification; no meshes, fitted replacement curves, or STEP proxy for X_T."""
from exact_occt import *
import numpy as np
from collections import defaultdict,Counter
from OCP.TColgp import TColgp_Array2OfPnt
from OCP.TColStd import TColStd_Array2OfReal

GEOMETRY_TOL=1e-7
PARAMETER_TOL=1e-11

def need(value,message):
    if not value:raise ValueError(message)

def knots(d):return np.repeat(d['knots'],d['multiplicities'])
def normalized(k):
    k=np.asarray(k,dtype=float);return (k-k[0])/(k[-1]-k[0])

def compact_knots(full):
    values=[];mult=[]
    for x in full:
        if values and x==values[-1]:mult[-1]+=1
        else:values.append(float(x));mult.append(1)
    return values,mult

def native_curve(d,edge=None,planes=()):
    if 'multiplicities' in d:return d
    if d['type']=='Line':
        p=np.array([edge['start'],edge['end']])*1000;axis=np.array(d['parameters'][3:6]);root=np.array(d['parameters'][:3])*1000
        need(max(np.linalg.norm(np.cross(q-root,axis)) for q in p)<GEOMETRY_TOL,'Native line endpoints are off support')
        return {'type':'BSplineCurve','degree':1,'poles':p.tolist(),'weights':[1.,1.],'knots':[0.,1.],'multiplicities':[2,2],'periodic':False,'domain':[0.,1.]}
    if d['type']=='Circle':
        p=d['parameters'];origin=np.array(p[:3])*1000;radius=p[6]*1000;axis=np.array(p[3:6]);samples=edge.get('edge_evaluations') or edge.get('samples',[])
        need(len(samples)>=3,'Native circle requires parameter-frame evaluation evidence')
        reference=samples[0];radial=np.array(reference['point'])*1000-origin
        need(abs(np.linalg.norm(radial)-radius)<GEOMETRY_TOL and abs(np.dot(radial,axis))<GEOMETRY_TOL,'Native circle frame is off the analytic support')
        # CurveParams3 start/end can be tolerant topological vertices. Recover
        # the analytic curve frame from one native evaluation, and independently
        # validate it against the remaining evaluations; no curve fitting.
        for sign in (1,-1):
            direction=axis*sign
            def at(t):
                angle=t-reference['u'];return origin+radial*math.cos(angle)+np.cross(direction,radial)*math.sin(angle)
            if max(np.linalg.norm(at(s['u'])-np.array(s['point'])*1000) for s in samples)<GEOMETRY_TOL:
                return {'type':'AnalyticCircle','origin':origin.tolist(),'z':direction.tolist(),'radius':radius,'poles':[at(t).tolist() for t in edge['range']],'range':edge['range'],'sense':True,'parameter_frame_validated':True}
        raise ValueError('Native analytic circle data disagrees with independent evaluations')
    need(d['type']=='BSplineCurve','Native analytic curve needs its exact adapter: '+d['type'])
    if d['dimension']==2:
        uv=np.array(d['coordinates']).reshape(-1,2);k,m=compact_knots(d['knots'])
        for plane in planes:
            frame=np.array(plane['parameter_frame'])[:,:3];origin=frame[0];axes=frame[1:]-origin
            result={'type':'BSplineCurve','degree':d['degree'],'poles':((origin+uv@axes)*1000).tolist(),'weights':[1.]*len(uv),'knots':k,'multiplicities':m,'periodic':False,'domain':[k[0],k[-1]]}
            c=curve(result)
            if max(c.Value(s['u']).Distance(gp_Pnt(*(np.array(s['point'])*1000))) for s in d['samples'])<GEOMETRY_TOL:return trim_native_curve(result,edge)
        raise ValueError('Native 2D spline support frame is not exposed by its adjacent planes')
    coords=np.array(d['coordinates']).reshape(-1,d['dimension']);weights=coords[:,3] if d['dimension']==4 else np.ones(len(coords));poles=coords[:,:3]*1000
    k,m=compact_knots(d['knots'])
    result={'type':'BSplineCurve','degree':d['degree'],'poles':poles.tolist(),'weights':weights.tolist(),'knots':k,'multiplicities':m,'periodic':False,'domain':[k[0],k[-1]]}
    if d.get('samples'):
        errors=[]
        for homogeneous in (False,True):
            result['poles']=(poles/weights[:,None] if homogeneous else poles).tolist();c=curve(result)
            error=max(c.Value(s['u']).Distance(gp_Pnt(*(np.array(s['point'])*1000))) for s in d['samples']);errors.append(error)
            if error<1e-8:return trim_native_curve(result,edge)
        raise ValueError('Native spline data failed independent evaluation: '+str(errors))
    return result

def trim_native_curve(result,edge):
    if edge is None:return result
    c=curve(result);a,b=edge['range'];lo,hi=result['domain']
    need(a>=lo-1e-10 and b<=hi+1e-10,'Native edge interval exceeds its exact underlying curve')
    a=max(a,lo);b=min(b,hi)
    ends=np.array([vector(c.Value(a)),vector(c.Value(b))]);vertices=np.array([edge['start'],edge['end']])*1000
    gap=min(float(np.max(np.linalg.norm(ends-vertices,axis=1))),float(np.max(np.linalg.norm(ends-vertices[::-1],axis=1))))
    # When a body supplies topology, check vertices against the SOURCE vertices
    # after exact curve matching. A periodic parameter seam may have a tolerant
    # auxiliary vertex although the full physical curve interval is unchanged.
    need(edge.get('_verify_vertices_after_matching') or gap<GEOMETRY_TOL,'Native edge interval endpoints differ from its vertices')
    c.Segment(a,b);return dict(type='BSplineCurve',**spline_data(c))

def curve_equal(a,b,tol=GEOMETRY_TOL):
    if b['type']=='AnalyticCircle':
        o=a.get('_original',{});
        if o.get('type')!='Circle':return None
        delta=max(float(np.linalg.norm(np.array(o['origin'])-b['origin'])),abs(o['radius']-b['radius']))
        if delta>tol or np.linalg.norm(np.cross(o['z'],b['z']))>PARAMETER_TOL:return None
        if abs(abs(a['_range'][1]-a['_range'][0])-abs(b['range'][1]-b['range'][0]))>PARAMETER_TOL:return None
        if a.get('_allow_circle_seam') and abs(abs(b['range'][1]-b['range'][0])-2*math.pi)<PARAMETER_TOL:
            return {'reversed':bool(np.dot(o['z'],b['z'])<0),'control_point_error_mm':delta,'full_analytic_circle_parameter_seam_normalized':True}
        sweep=abs(b['range'][1]-b['range'][0]);start=np.array(b['poles'][0 if b['sense'] else 1])-b['origin'];axis=np.array(b['z'])
        midpoint=np.array(b['origin'])+start*math.cos(sweep/2)+np.cross(axis,start)*math.sin(sweep/2)
        expected=vector(curve(o).Value(sum(a['_range'])/2))
        if np.linalg.norm(midpoint-expected)>tol:return None
        p=np.array([a['poles'][0],a['poles'][-1]]);q=np.array(b['poles'])
        for reverse in (False,True):
            error=float(np.max(np.linalg.norm(p-(q[::-1] if reverse else q),axis=1)))
            if error<=tol:return {'reversed':reverse,'control_point_error_mm':max(delta,error),'analytic_circle_identity':True}
        return None
    if a['degree']!=b['degree'] or len(a['poles'])!=len(b['poles']):return refined_curve_equal(a,b,tol)
    p=np.array(a['poles']);q=np.array(b['poles']);wa=np.array(a['weights']);wb=np.array(b['weights']);ka=normalized(knots(a));kb=normalized(knots(b))
    if len(ka)!=len(kb):return None
    for reverse in (False,True):
        qb=q[::-1] if reverse else q;w=wb[::-1] if reverse else wb;k=1-kb[::-1] if reverse else kb
        delta=float(np.max(np.linalg.norm(p-qb,axis=1)))
        if delta<=tol and np.max(np.abs(ka-k))<PARAMETER_TOL and np.max(np.abs(wa/wa[0]-w/w[0]))<PARAMETER_TOL:return {'reversed':reverse,'control_point_error_mm':delta}
    return None

def refined_curve_equal(a,b,tol):
    # Degree elevation and knot insertion are algebraic, never sampled fitting.
    for reverse in (False,True):
        ca=curve(dict(type='BSplineCurve',**{k:v for k,v in a.items() if k!='type'}));cb=curve(dict(type='BSplineCurve',**{k:v for k,v in b.items() if k!='type'}))
        if reverse:cb.Reverse()
        for c in (ca,cb):
            lo=c.FirstParameter();span=c.LastParameter()-lo
            c.SetKnots(arr(TColStd_Array1OfReal,[(c.Knot(i)-lo)/span for i in range(1,c.NbKnots()+1)]));c.IncreaseDegree(max(a['degree'],b['degree']))
        keys=sorted(set([ca.Knot(i) for i in range(1,ca.NbKnots()+1)]+[cb.Knot(i) for i in range(1,cb.NbKnots()+1)]));merged=[]
        for k in keys:
            if not merged or k-merged[-1]>PARAMETER_TOL:merged.append(k)
        for c in (ca,cb):
            c.SetKnots(arr(TColStd_Array1OfReal,[min(merged,key=lambda k:abs(k-c.Knot(i))) for i in range(1,c.NbKnots()+1)]))
        for k in merged[1:-1]:
            mult=max([c.Multiplicity(i) for c in (ca,cb) for i in range(1,c.NbKnots()+1) if abs(c.Knot(i)-k)<PARAMETER_TOL])
            for c in (ca,cb):c.InsertKnot(k,mult,PARAMETER_TOL,False)
        aa=spline_data(ca);bb=spline_data(cb)
        if len(aa['poles'])!=len(bb['poles']):continue
        delta=float(np.max(np.linalg.norm(np.array(aa['poles'])-bb['poles'],axis=1)));wa=np.array(aa['weights']);wb=np.array(bb['weights'])
        if delta<=tol and np.max(np.abs(wa/wa[0]-wb/wb[0]))<PARAMETER_TOL:return {'reversed':reverse,'control_point_error_mm':delta,'algebraic_common_basis':True}
    return None

def signature(d):
    original=d.get('_original',d)
    interval=d.get('_range',d.get('range',[]))
    if (d.get('_allow_circle_seam') or d['type']=='AnalyticCircle') and original['type'] in ('Circle','AnalyticCircle') and len(interval)==2 and abs(abs(interval[1]-interval[0])-2*math.pi)<PARAMETER_TOL:
        axis=np.array(original['z']);axis*=1 if axis[np.argmax(abs(axis))]>=0 else -1
        return ('full_circle',tuple(np.round(original['origin'],5)),round(original['radius'],5),tuple(np.round(axis,8)))
    endpoints=[tuple(np.round(np.array(d['poles'][i]),4)) for i in (0,-1)]
    return tuple(sorted(endpoints))

def expected_surface(s):
    if s['type']=='SurfaceOfLinearExtrusion':
        b=s['basis']['original'] if s.get('full_extrusion_support') else s['basis']['nurbs'];p=np.array(b['poles']);v=np.array(s['direction']);uv=[b['domain'][0],b['domain'][1],0.,1.] if s.get('full_extrusion_support') else s['uv_bounds']
        return {'type':'BSplineSurface','u_degree':b['degree'],'v_degree':1,'poles':np.stack([p+v*uv[2],p+v*uv[3]],axis=1).tolist(),
            'weights':np.repeat(np.array(b['weights'])[:,None],2,axis=1).tolist(),'u_knots':b['knots'],'u_multiplicities':b['multiplicities'],'v_knots':uv[2:],'v_multiplicities':[2,2],
            'u_periodic':False,'v_periodic':False}
    return s

def native_surface(s):
    if 'origin' in s or 'weights' in s:return s
    if s['type']=='NativeExtrusion':
        b=native_curve(s['profile']);uv=s['uv_bounds'];direction=np.array(s['direction']);p=np.array(b['poles'])
        for swapped in (False,True):
            along=uv[:2] if swapped else uv[2:];profile_range=uv[2:] if swapped else uv[:2]
            profile=curve(b);profile.Segment(*profile_range);cb=spline_data(profile);p=np.array(cb['poles'])
            result={'type':'BSplineSurface','u_degree':cb['degree'],'v_degree':1,'poles':np.stack([p+direction*along[0]*1000,p+direction*along[1]*1000],axis=1).tolist(),
                'weights':np.repeat(np.array(cb['weights'])[:,None],2,axis=1).tolist(),'u_knots':cb['knots'],'u_multiplicities':cb['multiplicities'],
                'v_knots':along,'v_multiplicities':[2,2],'u_periodic':False,'v_periodic':False,'native_uv_transposed':swapped,'native_extrusion_original':True,
                'extrusion_profile_data':b,'extrusion_direction':direction.tolist()}
            geom=bsurface(result)
            delta=max(geom.Value(*(q['uv'][::-1] if swapped else q['uv'])).Distance(gp_Pnt(*(np.array(q['point'])*1000))) for q in s['samples'])
            if delta<GEOMETRY_TOL:return result
        raise ValueError('Native extrusion definition failed independent evaluation: '+str(delta))
    if s['type']=='SurfaceOfLinearExtrusion':return expected_surface(s)
    if s['type']=='Plane':return {'type':'Plane','z':s['parameters'][:3],'origin':(np.array(s['parameters'][3:6])*1000).tolist()}
    if s['type']=='CylindricalSurface':return {'type':s['type'],'origin':(np.array(s['parameters'][:3])*1000).tolist(),'z':s['parameters'][3:6],'radius':s['parameters'][6]*1000}
    if s['type']=='ConicalSurface':
        origin=np.array(s['parameters'][:3])*1000;axis=np.array(s['parameters'][3:6]);radius=s['parameters'][6]*1000
        need(s.get('samples'),'Native cone requires evaluation evidence for axis/angle convention')
        for sign in (1,-1):
            angle=sign*s['parameters'][7];errors=[]
            for sample in s['samples']:
                delta=np.array(sample['point'])*1000-origin;axial=np.dot(delta,axis);radial=np.linalg.norm(delta-axial*axis)
                errors.append(abs(radial-abs(radius+axial*math.tan(angle))))
            if max(errors)<GEOMETRY_TOL:return {'type':s['type'],'origin':origin.tolist(),'z':axis.tolist(),'radius':radius,'semi_angle':angle,'native_parameter_sign':sign,'native_parameter_validation_error_mm':max(errors)}
        raise ValueError('Native cone parameters disagree with independent surface evaluation')
    need(s['type']=='BSplineSurface','Unknown support '+s['type'])
    cp=np.transpose(np.array(s['poles']),(1,0,2));w=cp[:,:,3] if s['dimension']==4 else np.ones(cp.shape[:2]);p=cp[:,:,:3]*1000
    uk,um=compact_knots(s['u_knots']);vk,vm=compact_knots(s['v_knots'])
    result={'type':'BSplineSurface','u_degree':s['u_degree'],'v_degree':s['v_degree'],'poles':p.tolist(),'weights':w.tolist(),
        'u_knots':uk,'u_multiplicities':um,'v_knots':vk,'v_multiplicities':vm,'u_periodic':False,'v_periodic':False}
    for homogeneous in (False,True):
        result['poles']=(p/w[:,:,None] if homogeneous else p).tolist();geom=bsurface(result)
        delta=max(geom.Value(*q['uv']).Distance(gp_Pnt(*(np.array(q['point'])*1000))) for q in s['samples'])
        if delta<1e-7:
            if result['u_degree']==1 and result['v_degree']>1:
                result['poles']=np.transpose(np.array(result['poles']),(1,0,2)).tolist();result['weights']=np.transpose(np.array(result['weights'])).tolist()
                for suffix in ('degree','knots','multiplicities','periodic'):result['u_'+suffix],result['v_'+suffix]=result['v_'+suffix],result['u_'+suffix]
                result['native_uv_transposed']=True
            return result
    raise ValueError('Native surface data failed independent evaluation: '+str(delta))

def bsurface(d):
    p=np.array(d['poles']);w=np.array(d['weights']);pa=TColgp_Array2OfPnt(1,len(p),1,len(p[0]));wa=TColStd_Array2OfReal(1,len(p),1,len(p[0]))
    for i in range(len(p)):
        for j in range(len(p[0])):pa.SetValue(i+1,j+1,gp_Pnt(*p[i,j]));wa.SetValue(i+1,j+1,float(w[i,j]))
    return G.Geom_BSplineSurface(pa,wa,arr(TColStd_Array1OfReal,d['u_knots']),arr(TColStd_Array1OfReal,d['v_knots']),arr(TColStd_Array1OfInteger,d['u_multiplicities']),arr(TColStd_Array1OfInteger,d['v_multiplicities']),d['u_degree'],d['v_degree'],False,False)

def surface_equal(a,b):
    if a['type']=='SurfaceOfLinearExtrusion' and b.get('native_extrusion_original'):
        return extrusion_carrier_equal(a,b)
    a=expected_surface(a)
    if a['type']!=b['type']:return None
    if a['type']=='Plane':
        na=np.array(a['z']);nb=np.array(b['z']);distance=abs(np.dot(np.array(a['origin'])-b['origin'],na))
        if np.linalg.norm(np.cross(na,nb))<PARAMETER_TOL and distance<GEOMETRY_TOL:return {'support_error_mm':float(distance)}
        return None
    if a['type']=='CylindricalSurface':
        na=np.array(a['z']);nb=np.array(b['z']);distance=np.linalg.norm(np.cross(np.array(a['origin'])-b['origin'],na));rad=abs(a['radius']-b['radius'])
        if np.linalg.norm(np.cross(na,nb))<PARAMETER_TOL and max(distance,rad)<GEOMETRY_TOL:return {'support_error_mm':float(max(distance,rad))}
        return None
    if a['type']=='ConicalSurface':
        na=np.array(a['z']);nb=np.array(b['z']);apex_a=np.array(a['origin'])-na*a['radius']/math.tan(a['semi_angle']);apex_b=np.array(b['origin'])-nb*b['radius']/math.tan(b['semi_angle']);delta=float(np.linalg.norm(apex_a-apex_b))
        if np.linalg.norm(np.cross(na,nb))<PARAMETER_TOL and abs(abs(a['semi_angle'])-abs(b['semi_angle']))<PARAMETER_TOL and delta<GEOMETRY_TOL:return {'support_error_mm':delta}
        return None
    need(a['type']=='BSplineSurface','Unhandled support comparison '+a['type'])
    if (a['u_degree'],a['v_degree'])!=(b['u_degree'],b['v_degree']):return None
    pa=np.array(a['poles']);pb=np.array(b['poles']);wa=np.array(a['weights']);wb=np.array(b['weights'])
    if pa.shape!=pb.shape:return ruled_surface_equal(a,b)
    akeys=[normalized(np.repeat(a[k+'_knots'],a[k+'_multiplicities'])) for k in ('u','v')];bkeys=[normalized(np.repeat(b[k+'_knots'],b[k+'_multiplicities'])) for k in ('u','v')]
    for ru in (False,True):
        for rv in (False,True):
            p=pb[::-1] if ru else pb;w=wb[::-1] if ru else wb
            if rv:p=p[:,::-1];w=w[:,::-1]
            ks=[1-bkeys[0][::-1] if ru else bkeys[0],1-bkeys[1][::-1] if rv else bkeys[1]]
            if any(len(x)!=len(y) or np.max(np.abs(x-y))>PARAMETER_TOL for x,y in zip(akeys,ks)):continue
            delta=float(np.max(np.linalg.norm(pa-p,axis=2)))
            if delta<GEOMETRY_TOL and np.max(np.abs(wa/wa[0,0]-w/w[0,0]))<PARAMETER_TOL:return {'u_reversed':ru,'v_reversed':rv,'support_error_mm':delta}
    return None

def extrusion_carrier_equal(a,b):
    # A support is unbounded in the extrusion direction. Its face UV bounding
    # box is derived trim data and may include kernel-specific tolerances.
    # Compare the FULL original profile after projecting to a common plane;
    # all physical boundaries and their face incidence are verified separately.
    da=np.array(a['direction']);db=np.array(b['extrusion_direction'])
    if np.linalg.norm(np.cross(da,db))>PARAMETER_TOL:return None
    basis=curve(a['basis']['original']);ca=GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(basis,basis.FirstParameter(),basis.LastParameter()))
    aa=dict(type='BSplineCurve',**spline_data(ca));bb=dict(b['extrusion_profile_data'])
    for definition,direction in ((aa,da),(bb,db)):
        poles=np.array(definition['poles']);along=poles@direction
        if np.ptp(along)>GEOMETRY_TOL:return None
        definition['poles']=(poles-along[:,None]*direction).tolist()
    check=curve_equal(aa,bb)
    if check is None:return None
    return {'extrusion_carrier_identity':True,'u_reversed':check['reversed'],'v_reversed':bool(np.dot(da,db)<0),
        'support_error_mm':check['control_point_error_mm'],'full_profile_checked':True}

def ruled_surface_equal(a,b):
    # Exact tensor-product identity for linear extrusion supports. Additional
    # Parasolid U knots do not change the represented polynomial surface.
    if a['v_degree']!=1 or b['v_degree']!=1 or len(a['poles'][0])!=2 or len(b['poles'][0])!=2:return None
    for rv in (False,True):
        checks=[]
        for v in (0,1):
            defs=[]
            for s,col in ((a,v),(b,1-v if rv else v)):
                defs.append({'type':'BSplineCurve','degree':s['u_degree'],'poles':[p[col] for p in s['poles']],'weights':[w[col] for w in s['weights']],
                    'knots':s['u_knots'],'multiplicities':s['u_multiplicities'],'periodic':False,'domain':[s['u_knots'][0],s['u_knots'][-1]]})
            checks.append(curve_equal(*defs))
        if all(checks) and checks[0]['reversed']==checks[1]['reversed']:
            # The homogeneous V interpolation must use a common scale.
            wa=np.array(a['weights']);wb=np.array(b['weights']);ratioa=wa[:,1]/wa[:,0];ratiob=wb[:,1]/wb[:,0]
            if max(np.max(np.abs(ratioa-1)),np.max(np.abs(ratiob-1)))>PARAMETER_TOL:return None
            return {'u_reversed':checks[0]['reversed'],'v_reversed':rv,'support_error_mm':max(c['control_point_error_mm'] for c in checks),'algebraic_common_basis':True}
    return None

def parameter_seams(faces,source):
    incidence=defaultdict(list)
    for i,f in enumerate(faces):
        for l in f['loops']:
            for t in l['trims' if source else 'edges']:incidence[t['edge' if source else 'edge_id']].append(i)
    return {e for e,uses in incidence.items() if len(uses)==2 and uses[0]==uses[1]}

def parameter_vertex_ids(source,seams):
    """Only degree-two boundary nodes split by a periodic face seam qualify."""
    incidence=defaultdict(list);pairs=defaultdict(list)
    for fi,f in enumerate(source['faces']):
        for l in f['loops']:
            for t in l['trims']:pairs[t['edge']].append(fi)
    for ei,e in enumerate(source['edges']):
        if ei not in seams:
            for vi in e['vertices']:incidence[vi].append(ei)
    candidates={vi for ei in seams for vi in source['edges'][ei]['vertices']}
    return {vi for vi in candidates if len(incidence[vi])==2
            and sorted(pairs[incidence[vi][0]])==sorted(pairs[incidence[vi][1]])}

def compare_vertices(source,e,native_edge,parameter_vertices):
    ids=e['vertices'];p=np.array([source['vertices'][v]['point'] for v in ids]);q=np.array([native_edge['start'],native_edge['end']])*1000
    if np.max(np.linalg.norm(p-q[::-1],axis=1))<np.max(np.linalg.norm(p-q,axis=1)):q=q[::-1]
    errors=np.linalg.norm(p-q,axis=1);exceptions=[]
    for vi,error in zip(ids,errors):
        if error<GEOMETRY_TOL:continue
        tolerance=source['vertices'][vi]['tolerance']
        need(vi in parameter_vertices and error<=tolerance,'Native physical vertex coordinates changed at source vertex '+str(vi))
        exceptions.append({'source_vertex':vi,'displacement_mm':float(error),'original_vertex_tolerance_mm':tolerance,
            'reason':'degree_two_auxiliary_node_on_removed_periodic_parameter_seam','complete_physical_curve_definition_checked':True})
    return {'topological_vertex_error_mm':float(max(errors)), 'periodic_auxiliary_vertex_normalization':exceptions}

def verify_body(source,native,normalize_periodic_seams=False):
    ss=parameter_seams(source['faces'],True) if normalize_periodic_seams else set();ns=parameter_seams(native['faces'],False) if normalize_periodic_seams else set()
    need(len(source['faces'])==len(native['faces']),'Face count changed')
    need(len(source['edges'])-len(ss)==len(native['edges'])-len(ns),'Physical edge count changed')
    if not source.get('_topology_normalization'):need(abs(len(source['vertices'])-len(native['vertices']))<=2*(len(ss)+len(ns)),'Vertex count difference exceeds periodic seam normalization')
    planes=defaultdict(list)
    for f in native['faces']:
        if 'parameter_frame' in f['surface']:
            for l in f['loops']:
                for t in l['edges']:planes[t['edge_id']].append(f['surface'])
    parameter_vertices=set(source.get('_parameter_vertex_ids',[]))|parameter_vertex_ids(source,ss) if normalize_periodic_seams else set()
    curves={i:native_curve(e['curve'],dict(e,_verify_vertices_after_matching=normalize_periodic_seams),planes[i]) for i,e in enumerate(native['edges']) if i not in ns};lookup=defaultdict(list)
    for i,c in curves.items():lookup[signature(c)].append(i)
    edge_map={};edge_checks=[]
    for i,e in enumerate(source['edges']):
        if i in ss:continue
        a=dict(type='BSplineCurve',**e['curve']['nurbs'],_original=e['curve']['original'],_range=e['curve']['range'],_allow_circle_seam=normalize_periodic_seams);candidates=lookup[signature(a)];match=None
        for j in candidates:
            check=curve_equal(a,curves[j])
            if check is not None:
                if normalize_periodic_seams and e.get('vertices') and not check.get('full_analytic_circle_parameter_seam_normalized'):
                    check.update(compare_vertices(source,e,native['edges'][j],parameter_vertices))
                match=j;edge_checks.append({'source_edge':i,'native_edge':j,**check});break
        need(match is not None,'Exact 3D edge definition mismatch: source edge '+str(i));edge_map[i]=match;candidates.remove(match)
    face_map={};face_checks=[];native_surfaces=[native_surface(f['surface']) for f in native['faces']];face_index=defaultdict(list)
    def face_key(face,is_source):
        if normalize_periodic_seams:
            return tuple(sorted(edge_map[t['edge']] if is_source else t['edge_id'] for l in face['loops'] for t in l['trims' if is_source else 'edges'] if t['edge' if is_source else 'edge_id'] not in (ss if is_source else ns)))
        return tuple(sorted(tuple(sorted(edge_map[t['edge']] if is_source else t['edge_id'] for t in l['trims' if is_source else 'edges'])) for l in face['loops']))
    for j,nf in enumerate(native['faces']):face_index[face_key(nf,False)].append(j)
    for i,f in enumerate(source['faces']):
        expected=face_key(f,True);match=None
        candidates=face_index[expected]
        for j in candidates:
            check=surface_equal(f['surface'],native_surfaces[j])
            if check is not None:match=j;face_checks.append({'source_face':i,'native_face':j,**check});break
        need(match is not None,'Face support/trim incidence mismatch: source face '+str(i));face_map[i]=match;candidates.remove(match)
    seams=[]
    for seam in source['g3_seams']:
        fi=seam['curved_face'];nf=native_surfaces[face_map[fi]];original=source['faces'][fi]['surface'];e=expected_surface(original);mapping=surface_equal(original,nf);uv=seam['uv'];newuv=[]
        if mapping.get('extrusion_carrier_identity'):
            old=original['basis']['original']['domain'];profile=curve(nf['extrusion_profile_data']);lo,hi=profile.FirstParameter(),profile.LastParameter()
            fraction=(uv[0]-old[0])/(old[-1]-old[0]);fraction=1-fraction if mapping['u_reversed'] else fraction;u=lo+fraction*(hi-lo)
            p=np.array(vector(profile.Value(u)));direction=np.array(nf['extrusion_direction'])
            need(abs(abs(direction[2])-1)<PARAMETER_TOL,'G3 carrier is not a vertical extrusion')
            p=p+direction*((sum(seam['z_span_mm'])/2-p[2])/direction[2]);point=gp_Pnt(*p)
            d1,d2,d3=[np.array(vector(profile.DN(u,k))) for k in (1,2,3)]
        else:
            for k,key in enumerate(('u','v')):
                old=e[key+'_knots'];new=nf[key+'_knots'];fraction=(uv[k]-old[0])/(old[-1]-old[0]);fraction=1-fraction if mapping[key+'_reversed'] else fraction;newuv.append(new[0]+fraction*(new[-1]-new[0]))
            geom=bsurface(nf);point=geom.Value(*newuv);d1=np.array(vector(geom.DN(*newuv,1,0)));d2=np.array(vector(geom.DN(*newuv,2,0)));d3=np.array(vector(geom.DN(*newuv,3,0)))
        speed=np.linalg.norm(d1[:2]);cross=d1[0]*d2[1]-d1[1]*d2[0];curvature=cross/speed**3;rate=(d1[0]*d3[1]-d1[1]*d3[0])/speed**4-3*cross*np.dot(d1[:2],d2[:2])/speed**6
        plane=native_surfaces[face_map[seam['plane_face']]];normal=np.array(plane['z']);gap=abs(np.dot(np.array(vector(point))-plane['origin'],normal));angle=abs(np.dot(d1/np.linalg.norm(d1),normal))
        need(gap<=2*seam['position_tolerance_mm'] and angle<1e-9 and abs(curvature)<1e-8 and abs(rate)<1e-8,'Final native G3 seam failed: '+str(seam['edge']))
        seams.append({'source_edge':seam['edge'],'gap_mm':float(gap),'tangent_sine_error':float(angle),'curvature_per_mm':float(curvature),'curvature_rate_per_mm2':float(rate)})
    return {'edge_checks':edge_checks,'face_checks':face_checks,'g3_seams':seams,'exact_support_and_edge_data_preserved':True,'trim_incidence_preserved':True,'topology_partition_normalization':source.get('_topology_normalization'),
        'periodic_parameter_seams':{'source_edges':sorted(ss),'native_edges':sorted(ns),'physical_boundaries_unchanged':True}}

def verify_step(packet_path,step_path,report_path):
    source=json.loads(Path(packet_path).read_text(encoding='utf-8'));print('STEP native import:',Path(step_path).parent.name,flush=True);shape=cq.importers.importStep(str(step_path)).val();need(shape.isValid(),'Native STEP reread is invalid')
    bodies=shape.Solids();need(len(bodies)==len(source['bodies']),'STEP body count changed')
    checks=[]
    for bi,(s,body) in enumerate(zip(source['bodies'],bodies)):
        print('STEP exact data extraction: body',bi+1,'of',len(bodies),flush=True);n=step_body_data(body)
        # STEP may change computed face UV extents by roundoff. Compare the
        # complete extrusion support data, independently of those trim bounds.
        for data in (s,n):
            for f in data['faces']:
                if f['surface']['type']=='SurfaceOfLinearExtrusion':f['surface']['full_extrusion_support']=True
        print('STEP exact definitions and G3 comparison: body',bi+1,flush=True)
        checks.append(verify_body(s,n))
    result={'passed':True,'construction':'canonical_exact_geometry_and_topology','native_readback':True,'format':'STEP','canonical_sha256':sha(packet_path),'file_sha256':sha(step_path),'checks':checks,'geometry_tolerance_mm':GEOMETRY_TOL,'parameter_tolerance':PARAMETER_TOL}
    Path(report_path).write_text(json.dumps(result,separators=(',',':')),encoding='utf-8');print('Strict STEP data and G3 passed:',step_path,flush=True)

def step_body_data(solid):
    vm=indexed(solid,TopAbs_VERTEX);em=indexed(solid,TopAbs_EDGE);fm=indexed(solid,TopAbs_FACE)
    n={'vertices':[],'edges':[],'faces':[]}
    for i in range(1,vm.Extent()+1):n['vertices'].append({'point':vector(BRep_Tool.Pnt_s(TopoDS.Vertex_s(vm.FindKey(i))))})
    for i in range(1,em.Extent()+1):
        e=TopoDS.Edge_s(em.FindKey(i).Oriented(TopAbs_FORWARD));a=BRepAdaptor_Curve(e);c=BRep_Tool.Curve_s(e,0.,0.)
        bs=GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(c,a.FirstParameter(),a.LastParameter()))
        n['edges'].append({'curve':dict(type='BSplineCurve',**spline_data(bs))})
    for i in range(1,fm.Extent()+1):
        raw=TopoDS.Face_s(fm.FindKey(i));face=TopoDS.Face_s(raw.Oriented(TopAbs_FORWARD));s=BRep_Tool.Surface_s(face);uv=list(BRepTools.UVBounds_s(face))
        if s.DynamicType().Name()=='Geom_SurfaceOfLinearExtrusion':
            b=s.BasisCurve();uv[:2]=[b.FirstParameter(),b.LastParameter()];uv[2:]=[0.,1.]
        sd=surface_data(s,uv);loops=[]
        for wire in cq.Face(face).Wires():
            explorer=BRepTools_WireExplorer(wire.wrapped,face);edges=[]
            while explorer.More():edges.append({'edge_id':em.FindIndex(explorer.Current())-1});explorer.Next()
            loops.append({'edges':edges})
        n['faces'].append({'surface':sd,'loops':loops})
    return n

def verify_sw(packet_path,report_path):
    source=json.loads(Path(packet_path).read_text(encoding='utf-8'));report=json.loads(Path(report_path).read_text(encoding='utf-8'));need(len(source['bodies'])==len(report['geometry']),'Body count differs')
    need(report.get('topology_passed') is True,'Native body reports topology faults')
    checks=[];unused=set(range(len(report['geometry'])))
    for si,s in enumerate(source['bodies']):
        normalized_source=None;match=None;failures=[]
        for ni in sorted(unused):
            n=report['geometry'][ni];candidate=s
            if len(s['faces'])!=len(n['faces']):
                if normalized_source is None:
                    from exact_topology import normalize
                    normalized_source=normalize(s)
                candidate=normalized_source
                if len(candidate['faces'])!=len(n['faces']):continue
                print('Exact partition quotient:',len(candidate['faces']),'faces,',len(candidate['edges']),'physical edges; native:',len(n['faces']),len(n['edges']),flush=True)
            try:check=verify_body(candidate,n,True)
            except ValueError as error:failures.append('native body '+str(ni)+': '+str(error));continue
            match=ni;checks.append(dict(check,source_body=si,native_body=ni));break
        need(match is not None,'No exact native match for source body '+str(si)+': '+'; '.join(failures));unused.remove(match)
    report.update(strict_validation_pending=False,passed=True,checks=checks,geometry_tolerance_mm=GEOMETRY_TOL,parameter_tolerance=PARAMETER_TOL)
    Path(report_path).write_text(json.dumps(report,separators=(',',':')),encoding='utf-8');print('Strict native Parasolid data and G3 passed:',report_path,flush=True)

if __name__=='__main__':verify_sw(sys.argv[1],sys.argv[2])
