"""Exact quotient of redundant face partitions; never modify CAD output.

Only adjacent faces on an algebraically identical carrier may be grouped.
Only complete collinear chains and complete analytic circles may be joined.
Every original boundary is retained or has an explicit coverage proof.
"""
from exact_verify import *

def carrier_equal(a,b):
    if a['type']!=b['type']:return None
    if a['type']=='SurfaceOfLinearExtrusion':
        c=curve(b['basis']['original']);c=GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(c,c.FirstParameter(),c.LastParameter()))
        return extrusion_carrier_equal(a,{'extrusion_profile_data':dict(type='BSplineCurve',**spline_data(c)),'extrusion_direction':b['direction']})
    return surface_equal(a,b)

def line_chain(source,ids):
    first=source['edges'][ids[0]]['curve']['original'];axis=np.array(first['direction']);origin=np.array(first['origin']);intervals=[]
    nodes=Counter(v for i in ids for v in source['edges'][i]['vertices'])
    if sorted(nodes.values()).count(1)!=2 or max(nodes.values())>2:return None
    for i in ids:
        c=source['edges'][i]['curve'];o=c['original'];points=np.array(c['endpoints'])
        if o['type']!='Line' or np.linalg.norm(np.cross(axis,o['direction']))>PARAMETER_TOL:return None
        if max(np.linalg.norm(np.cross(p-origin,axis)) for p in points)>GEOMETRY_TOL:return None
        intervals.append(sorted(float(np.dot(p-origin,axis)) for p in points))
    intervals.sort()
    if any(abs(a[1]-b[0])>GEOMETRY_TOL for a,b in zip(intervals,intervals[1:])):return None
    lo,hi=intervals[0][0],intervals[-1][1];c=G.Geom_Line(gp_Pnt(*origin),gp_Dir(*axis))
    return curve_data(c,lo,hi),{'kind':'collinear_chain','source_edges':ids,'endpoint_vertices':[v for v,count in nodes.items() if count==1],'coverage_intervals':intervals,'full_interval':[lo,hi]}

def circle_cycle(source,ids):
    first=source['edges'][ids[0]]['curve']['original'];origin=np.array(first['origin']);axis=np.array(first['z']);x=np.array(first['x']);y=np.array(first['y']);intervals=[];sweep=0.
    nodes=Counter(v for i in ids for v in source['edges'][i]['vertices'])
    closed=set(nodes.values())=={2}
    if not closed and (list(nodes.values()).count(1)!=2 or max(nodes.values())>2):return None
    for i in ids:
        c=source['edges'][i]['curve'];o=c['original']
        if o['type']!='Circle' or np.linalg.norm(np.array(o['origin'])-origin)>GEOMETRY_TOL or abs(o['radius']-first['radius'])>GEOMETRY_TOL or np.linalg.norm(np.cross(o['z'],axis))>PARAMETER_TOL:return None
        span=c['range'][1]-c['range'][0]
        if not 0<span<=2*math.pi+PARAMETER_TOL:return None
        p=np.array(c['endpoints'][0 if np.dot(o['z'],axis)>0 else 1])-origin
        start=math.atan2(float(np.dot(p,y)),float(np.dot(p,x)))%(2*math.pi);end=start+span;sweep+=span
        if end<=2*math.pi+PARAMETER_TOL:intervals.append([start,min(end,2*math.pi)])
        else:intervals.extend([[start,2*math.pi],[0.,end-2*math.pi]])
    if sweep>2*math.pi+PARAMETER_TOL:return None
    intervals.sort()
    blocks=[]
    for lo,hi in intervals:
        if blocks and lo<blocks[-1][1]-PARAMETER_TOL:return None
        if blocks and abs(lo-blocks[-1][1])<=PARAMETER_TOL:blocks[-1][1]=hi
        else:blocks.append([lo,hi])
    if len(blocks)==1:lo,hi=blocks[0]
    elif len(blocks)==2 and abs(blocks[0][0])<PARAMETER_TOL and abs(blocks[1][1]-2*math.pi)<PARAMETER_TOL:lo,hi=blocks[1][0],2*math.pi+blocks[0][1]
    else:return None
    if abs(hi-lo-sweep)>PARAMETER_TOL or closed!=(abs(sweep-2*math.pi)<PARAMETER_TOL):return None
    if closed:lo,hi=0.,2*math.pi
    return curve_data(curve(first),lo,hi),{'kind':'analytic_circle_chain','source_edges':ids,'endpoint_vertices':[v for v,count in nodes.items() if count==1],'coverage_intervals':intervals,'full_interval':[lo,hi],'closed':closed}

def normalize(source):
    incidence=defaultdict(list);parents=list(range(len(source['faces'])));merge_proofs=[]
    def root(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for fi,f in enumerate(source['faces']):
        for loop in f['loops']:
            for t in loop['trims']:incidence[t['edge']].append(fi)
    need(all(len(fs)==2 for fs in incidence.values()),'Partition normalization requires closed manifold incidence')
    for ei,fs in incidence.items():
        if fs[0]==fs[1]:continue
        check=carrier_equal(source['faces'][fs[0]]['surface'],source['faces'][fs[1]]['surface'])
        if check is not None:
            parents[root(fs[0])]=root(fs[1]);merge_proofs.append({'source_edge':ei,'faces':fs,'support_identity':check})
    grouped=defaultdict(list)
    for fi in range(len(parents)):grouped[root(fi)].append(fi)
    groups=list(grouped.values());face_map={fi:gi for gi,g in enumerate(groups) for fi in g}
    removed={ei for ei,fs in incidence.items() if face_map[fs[0]]==face_map[fs[1]]}
    seams=parameter_seams(source['faces'],True)
    need(removed==seams|{p['source_edge'] for p in merge_proofs},'An internal edge lacks an exact carrier identity proof')
    by_pair=defaultdict(list)
    for ei in incidence:
        if ei not in removed:by_pair[tuple(sorted(face_map[f] for f in incidence[ei]))].append(ei)
    joins=[];covered=set()
    for pair,edges in by_pair.items():
        for kind in ('Line','Circle'):
            selected=[i for i in edges if source['edges'][i]['curve']['original']['type']==kind];adjacency=defaultdict(list)
            for ei in selected:
                for vi in source['edges'][ei]['vertices']:adjacency[vi].append(ei)
            unused=set(selected)
            while unused:
                first=unused.pop();component={first};todo=[first]
                while todo:
                    ei=todo.pop()
                    for vi in source['edges'][ei]['vertices']:
                        for neighbor in adjacency[vi]:
                            if neighbor in unused:unused.remove(neighbor);component.add(neighbor);todo.append(neighbor)
                if len(component)<2:continue
                ids=sorted(component);proof=(line_chain if kind=='Line' else circle_cycle)(source,ids)
                if proof is not None:joins.append((ids,pair,*proof));covered.update(ids)
    edges=[];edge_map={};edge_faces=[];join_proofs=[]
    for ei,e in enumerate(source['edges']):
        if ei in removed or ei in covered:continue
        edge_map[ei]=len(edges);edges.append(e);edge_faces.append(tuple(sorted(face_map[f] for f in incidence[ei])))
    for ids,pair,definition,proof in joins:
        index=len(edges)
        for ei in ids:edge_map[ei]=index
        edges.append({'curve':definition,'vertices':proof['endpoint_vertices'],'tolerance':max(source['edges'][i]['tolerance'] for i in ids)});edge_faces.append(pair);join_proofs.append(dict(normalized_edge=index,**proof))
    face_edges=defaultdict(list)
    for ei,pair in enumerate(edge_faces):
        for fi in pair:face_edges[fi].append({'edge':ei,'reversed':False})
    faces=[{'surface':source['faces'][g[0]]['surface'],'loops':[{'outer':True,'trims':face_edges[i]}]} for i,g in enumerate(groups)]
    g3=[]
    for seam in source['g3_seams']:
        need(seam['edge'] in edge_map,'A G3 boundary was removed as an internal partition')
        fi=seam['curved_face'];gi=face_map[fi];a=source['faces'][fi]['surface'];b=faces[gi]['surface'];check=carrier_equal(a,b);need(check is not None,'G3 face group changed carrier')
        uv=list(seam['uv'])
        if check.get('extrusion_carrier_identity'):
            old=a['basis']['original']['domain'];new=b['basis']['original']['domain'];f=(uv[0]-old[0])/(old[1]-old[0]);f=1-f if check['u_reversed'] else f;uv[0]=new[0]+f*(new[1]-new[0])
        g3.append(dict(seam,edge=edge_map[seam['edge']],curved_face=gi,plane_face=face_map[seam['plane_face']],uv=uv,original_source_edge=seam['edge']))
    proof={'method':'adjacent_identical_carriers_and_exact_line_circle_coverage','face_groups':groups,'internal_edge_proofs':merge_proofs,
        'removed_periodic_edges':sorted(seams),'edge_join_proofs':join_proofs,'original_counts':source['counts'],'normalized_faces':len(faces),'normalized_physical_edges':len(edges),
        'physical_vertices_verified_by_exact_edge_endpoints':True,'original_to_normalized_edges':edge_map}
    return dict(source,edges=edges,faces=faces,g3_seams=g3,_topology_normalization=proof,
        _parameter_vertex_ids=sorted(parameter_vertex_ids(source,seams)))
