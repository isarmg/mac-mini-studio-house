"""STEP transport with algebraic NURBS representations of noncircular conics.

This intermediate is accepted only after native STEP reread matches the master.
Its temporary OCCT body's changed parameter flags are never an acceptance claim.
"""
from exact_verify import *

def short_trim_support(edge):
    """Keep a short trim on its full spline using only knot insertion/rebasing."""
    definition=edge['curve']['original'];lo,hi=edge['curve']['range']
    if definition['type']!='BSplineCurve':return None
    first,last=definition['domain']
    if (hi-lo)/(last-first)>=.01:return None
    result=curve(definition)
    for t in (lo,hi):
        if first<t<last:result.InsertKnot(t,result.Degree(),1e-16,False)
    result.SetKnots(arr(TColStd_Array1OfReal,[(result.Knot(i)-lo)/(hi-lo) for i in range(1,result.NbKnots()+1)]))
    return result


def preserve_short_supports(data,created):
    builder=BRep_Builder();selected=[]
    for ei,e in enumerate(data['edges']):
        full=short_trim_support(e)
        if full is None:continue
        edge=created['edges'][ei];builder.UpdateEdge(edge,full,e['tolerance']);builder.Range(edge,0.,1.,True);selected.append(ei)
    chosen=set(selected)
    for fi,face_data in enumerate(data['faces']):
        groups={}
        for loop in face_data['loops']:
            for trim in loop['trims']:
                if trim['edge'] in chosen:groups.setdefault(trim['edge'],[]).append(trim)
        for ei,trims in groups.items():
            pcurves=[]
            for trim in sorted(trims,key=lambda t:t['reversed']):
                d=trim['curve']['nurbs'];pc=curve(dict(type='BSplineCurve',**d),2);lo,hi=d['domain']
                pc.SetKnots(arr(TColStd_Array1OfReal,[(pc.Knot(i)-lo)/(hi-lo) for i in range(1,pc.NbKnots()+1)]));pcurves.append(pc)
            edge=created['edges'][ei];face=TopoDS.Face_s(created['faces'][fi]);tol=data['edges'][ei]['tolerance']
            if len(pcurves)==1:builder.UpdateEdge(edge,pcurves[0],face,tol)
            else:builder.UpdateEdge(edge,pcurves[0],pcurves[1],face,tol)
            builder.Range(edge,face,0.,1.)
    return [{'edge':i,'original_range':data['edges'][i]['curve']['range'],'transport_range':[0.,1.],
        'full_support_preserved':True,'method':'Algebraic knot insertion and affine parameter change'} for i in selected]


def run(packet_path,destination,report_path):
    packet=json.loads(Path(packet_path).read_text());parts=[];conics=[];rebases=[]
    for bi,data in enumerate(packet['bodies']):
        body,created=build_body(data,with_maps=True,bounded_edges=True);builder=BRep_Builder()
        rebases.extend(dict(record,body=bi) for record in preserve_short_supports(data,created))
        for ei,e in enumerate(data['edges']):
            if e['curve']['original']['type'] not in ('Hyperbola','Ellipse','Parabola'):continue
            edge=created['edges'][ei];c=dict(type='BSplineCurve',**e['curve']['nurbs'])
            builder.UpdateEdge(edge,curve(c),e['tolerance']);builder.Range(edge,*c['domain'],True)
            builder.SameRange(edge,False);builder.SameParameter(edge,False)
            conics.append({'body':bi,'edge':ei,'original_type':e['curve']['original']['type'],'degree':c['degree']})
        parts.append(body)
    shape=parts[0] if len(parts)==1 else cq.Compound.makeCompound(parts)
    destination=Path(destination);write_step(shape,destination)
    text=destination.read_text().replace('.PCURVE_S1.','.CURVE_3D.').replace('.PCURVE_S2.','.CURVE_3D.')
    destination.write_text(text)
    verify_step(packet_path,destination,report_path)
    receipt=json.loads(Path(report_path).read_text());receipt.update(transport_only=True,algebraic_conic_representations=conics,algebraic_parameter_rebases=rebases,source_brep_sha256=packet['provenance']['source_sha256'])
    Path(report_path).write_text(json.dumps(receipt,separators=(',',':')));return receipt

if __name__=='__main__':run(sys.argv[1],sys.argv[2],sys.argv[3])
