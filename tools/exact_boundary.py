"""Align planar extrusion rims to their exact support definitions.

No fitting, support-surface editing, healing, sewing, or tolerance enlargement.
The input 3D edge and its extrusion pcurve are checked over their full domains by
GeomLib_CheckCurveOnSurface. This is the kernel's numerical maximum-distance
solver, not a formal interval-arithmetic certificate. Immutable input hashes,
the computed deviations, and each aligned edge are retained in the receipt.
"""
from exact_verify import *
from OCP.GeomLib import GeomLib_CheckCurveOnSurface
from OCP.GeomAdaptor import GeomAdaptor_Curve,GeomAdaptor_Surface
from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
from OCP.Adaptor3d import Adaptor3d_CurveOnSurface
from OCP.Geom2d import Geom2d_Line

def support_definition(d):
    d={k:v for k,v in d.items() if k not in ('uv_bounds','check_points')}
    if d['type']=='SurfaceOfLinearExtrusion':d['basis']=d['basis']['original']
    return d

def definition_roundoff(a,b,path=''):
    """Same definition, permitting only double-precision reconstruction noise."""
    if isinstance(a,dict):
        need(isinstance(b,dict) and a.keys()==b.keys(),'Definition keys changed: '+path)
        return max((definition_roundoff(v,b[k],path+'.'+k) for k,v in a.items()),default=0.)
    if isinstance(a,list):
        need(isinstance(b,list) and len(a)==len(b),'Definition size changed: '+path)
        return max((definition_roundoff(x,y,path+'['+str(i)+']') for i,(x,y) in enumerate(zip(a,b))),default=0.)
    if isinstance(a,float):
        error=abs(a-b);need(error<=1e-12,'Definition changed: '+path+' '+str(error));return error
    need(a==b,'Definition value changed: '+path);return 0.

def support_segment(definition,low,high):
    profile=curve(definition)
    # Segmenting a complete periodic curve one ULP short of its endpoint can
    # create a numerically singular knot span in OCCT. Use the stored endpoint
    # only within floating-point roundoff; the support definition is unchanged.
    for index,value in enumerate((profile.FirstParameter(),profile.LastParameter())):
        tolerance=16*abs(np.spacing(max(1.,abs(value))))
        if abs(low-value)<=tolerance:low=value
        if abs(high-value)<=tolerance:high=value
    profile.Segment(low,high)
    return profile

def candidates(source):
    incidence=defaultdict(list)
    for fi,f in enumerate(source['faces']):
        for loop in f['loops']:
            for t in loop['trims']:incidence[t['edge']].append((fi,f,t))
    for ei,e in enumerate(source['edges']):
        if e['curve']['original']['type']!='BSplineCurve':continue
        uses=incidence[ei]
        if len(uses)!=2 or sorted(f['surface']['type'] for _,f,_ in uses)!=['Plane','SurfaceOfLinearExtrusion']:continue
        fi,f,t=next(x for x in uses if x[1]['surface']['type']=='SurfaceOfLinearExtrusion')
        pc=t['curve'];poles=np.array(pc['nurbs']['poles']);ends=np.array(pc['endpoints'])
        if abs(ends[1,0]-ends[0,0])<1e-10:continue
        if f['surface']['basis']['original']['type']!='BSplineCurve':continue
        if e['curve']['original']['degree']<=f['surface']['basis']['original']['degree']:continue
        # Determine the isocurve from the unchanged support definitions. A
        # boolean's pcurve can contain small V noise even for an exact planar
        # section; that noise must not determine the replacement plane.
        plane=next(fd['surface'] for _,fd,_ in uses if fd['surface']['type']=='Plane')
        basis=np.array(f['surface']['basis']['original']['poles']);normal=np.array(plane['z']);direction=np.array(f['surface']['direction'])
        divisor=float(np.dot(normal,direction))
        if abs(divisor)<1e-12 or np.max(np.abs((basis-basis[0])@normal))>1e-12:continue
        v=float(np.dot(np.array(plane['origin'])-basis[0],normal)/divisor)
        if np.max(np.abs(poles[:,1]-v))>e['tolerance']:continue
        profile=support_segment(f['surface']['basis']['original'],min(ends[:,0]),max(ends[:,0]))
        transform=gp_Trsf();transform.SetTranslation(gp_Vec(*(direction*v)));profile.Transform(transform)
        if curve_equal(dict(type='BSplineCurve',**e['curve']['nurbs']),dict(type='BSplineCurve',**spline_data(profile))):continue
        # Positive equal weights and monotone U control coordinates establish
        # that the input pcurve covers the aligned edge's complete interval.
        weights=np.array(pc['nurbs']['weights'])
        need(np.min(weights)>0 and np.ptp(weights)<1e-12,'Unsupported rational rim parameterization')
        need(np.all(np.diff(poles[:,0])>=-1e-12) or np.all(np.diff(poles[:,0])<=1e-12),'Rim parameterization is not monotone')
        yield ei,e,uses,f,t,profile,v

def revise_body(source,label=''):
    shape,created=build_body(source,validate=False,with_maps=True);builder=BRep_Builder();changes=[]
    for ei,e,uses,f,t,profile,v in candidates(source):
        pc=t['curve'];sd=f['surface']
        exact_pc=dict(type='BSplineCurve',**pc['nurbs'])
        exact_pc['poles']=[[p[0],v] for p in exact_pc['poles']]
        checker=GeomLib_CheckCurveOnSurface(GeomAdaptor_Curve(curve(e['curve']['original']),*e['curve']['range']),1e-11)
        checker.Perform(Adaptor3d_CurveOnSurface(Geom2dAdaptor_Curve(curve(exact_pc,2),*pc['range']),GeomAdaptor_Surface(surface(sd))))
        need(checker.IsDone() and checker.ErrorStatus()==0,'Maximum-distance calculation failed: '+str(ei))
        deviation=checker.MaxDistance();need(deviation<=e['tolerance'],'Boundary revision exceeds the original edge tolerance: '+str(ei))
        reverse=pc['endpoints'][1][0]<pc['endpoints'][0][0]
        if reverse:profile.Reverse()
        lo,hi=profile.FirstParameter(),profile.LastParameter();bs=spline_data(profile);edge=created['edges'][ei]
        for face_id,fd,trim in uses:
            if fd['surface']['type']=='Plane':
                plane=fd['surface'];residual=np.abs((np.array(bs['poles'])-plane['origin'])@np.array(plane['z']))
                need(max(residual)<GEOMETRY_TOL,'Replacement rim does not lie on its original planar support')
        builder.UpdateEdge(edge,profile,e['tolerance']);builder.Range(edge,lo,hi,True)
        for face_id,fd,trim in uses:
            fc=TopoDS.Face_s(created['faces'][face_id]);s=fd['surface']
            if s['type']=='Plane':
                uv=(np.array(bs['poles'])-s['origin'])@np.array([s['x'],s['y']]).T
                newpc=curve(dict(type='BSplineCurve',**dict(bs,poles=uv.tolist())),2)
            else:newpc=Geom2d_Line(gp_Pnt2d(lo+hi if reverse else 0,v),gp_Dir2d(-1 if reverse else 1,0))
            builder.UpdateEdge(edge,newpc,fc,e['tolerance']);builder.Range(edge,fc,lo,hi)
        builder.SameParameter(edge,True);builder.SameRange(edge,True)
        record={'edge':ei,'closed':bool(np.linalg.norm(np.array(e['curve']['endpoints'][0])-e['curve']['endpoints'][1])<=GEOMETRY_TOL),'old_degree':e['curve']['original']['degree'],'new_degree':profile.Degree(),'original_edge_tolerance_mm':e['tolerance'],
            'computed_max_deviation_mm':deviation,'computed_max_parameter':checker.MaxParameter(),'distance_method':'GeomLib_CheckCurveOnSurface',
            'isocurve_v_from_exact_plane':v,'source_pcurve_v_span_mm':float(np.ptp(np.array(pc['nurbs']['poles'])[:,1])),'support_surfaces_changed':False}
        changes.append(record);print('Boundary revision',label,ei,'deviation_mm',deviation,flush=True)
    if not shape.isValid():
        analyzer=BRepCheck_Analyzer(shape.wrapped)
        for kind,items in [('edge',shape.Edges()),('face',shape.Faces())]:
            for i,item in enumerate(items):
                result=analyzer.Result(item.wrapped);status=list(result.Status())
                if any(int(s)!=0 for s in status):print('Invalid revision',kind,i,status,flush=True)
        raise ValueError('Revised canonical BREP is invalid: '+label)
    current=body_data(shape)
    need(current['counts']==source['counts'],'Revision changed topology counts')
    mappings={}
    for name,kind in [('vertices',TopAbs_VERTEX),('edges',TopAbs_EDGE),('faces',TopAbs_FACE)]:
        actual=indexed(shape,kind);mappings[name]={i:actual.FindIndex(item)-1 for i,item in enumerate(created[name])}
        need(sorted(mappings[name].values())==list(range(len(created[name]))),'Reconstructed topology map is not bijective')
    for i,old in enumerate(source['vertices']):
        new=current['vertices'][mappings['vertices'][i]]
        need(old==new,'Revision changed vertex coordinates or tolerance: '+str(i))
    need([[mappings['faces'][i] for i in shell] for shell in source['shells']]==current['shells'],'Revision changed shells')
    for i,old in enumerate(source['faces']):
        new=current['faces'][mappings['faces'][i]]
        definition_roundoff(support_definition(old['surface']),support_definition(new['surface']),'support '+str(i))
        need(old['reversed']==new['reversed'],'Revision changed face orientation')
        need([[mappings['edges'][t['edge']] for t in l['trims']] for l in old['loops']]==[[t['edge'] for t in l['trims']] for l in new['loops']],'Revision changed trim incidence')
    changed={r['edge'] for r in changes}
    for i,old in enumerate(source['edges']):
        new=current['edges'][mappings['edges'][i]]
        need([mappings['vertices'][v] for v in old['vertices']]==new['vertices'],'Revision changed edge endpoints')
        if i not in changed:
            definition_roundoff(old['curve'],new['curve'],'unrelated edge '+str(i))
            need(old['tolerance']==new['tolerance'],'Revision changed an unrelated edge tolerance')
    converted=[dict(s,edge=mappings['edges'][s['edge']],curved_face=mappings['faces'][s['curved_face']],plane_face=mappings['faces'][s['plane_face']]) for s in source['g3_seams']]
    need(sorted(converted,key=lambda s:s['edge'])==sorted(current['g3_seams'],key=lambda s:s['edge']),'Revision changed G3 seam definitions')
    return shape,changes

def revise(packet_path,destination,report_path):
    packet=json.loads(Path(packet_path).read_text(encoding='utf-8'));parts=[];changes=[]
    need(sha(ROOT/packet['provenance']['source_brep'])==packet['provenance']['source_sha256'],'Source BREP hash drift')
    for bi,source in enumerate(packet['bodies']):
        shape,records=revise_body(source,Path(packet_path).stem+':'+str(bi));parts.append(shape)
        changes.extend(dict(body=bi,**r) for r in records)
    shape=parts[0] if len(parts)==1 else cq.Compound.makeCompound(parts)
    destination=Path(destination).resolve();destination.parent.mkdir(parents=True,exist_ok=True);shape.exportBrep(str(destination))
    newpacket=destination.with_suffix('.geometry.json');export(destination,newpacket)
    report={'authorized_source_revision':True,'source_brep':packet['provenance']['source_brep'],'source_brep_sha256':packet['provenance']['source_sha256'],
        'source_packet_sha256':sha(packet_path),'revised_brep':destination.relative_to(ROOT).as_posix(),'revised_brep_sha256':sha(destination),'canonical_sha256':sha(newpacket),
        'support_surfaces_unchanged':True,'g3_controls_unchanged':True,'topology_unchanged':True,'valid':True,'changes':changes}
    Path(report_path).write_text(json.dumps(report,indent=2),encoding='utf-8');return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('packet');p.add_argument('destination');p.add_argument('report');a=p.parse_args();revise(a.packet,a.destination,a.report)
