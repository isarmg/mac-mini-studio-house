"""Prove each cylindrical bore has exactly two closed mouths on the two cones."""
import numpy as np
import cadquery as cq
from scipy.spatial import cKDTree
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.TopExp import TopExp
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

def key(p,d):
    p=np.asarray(p,dtype=float);d=np.asarray(d,dtype=float);d/=np.linalg.norm(d)
    if d[np.argmax(abs(d))]<0:d=-d
    return np.r_[p-np.dot(p,d)*d,100*d]

def verify(base,data):
    faces=TopTools_IndexedMapOfShape();TopExp.MapShapes_s(base.wrapped,TopAbs_FACE,faces)
    edges=TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(base.wrapped,TopAbs_EDGE,TopAbs_FACE,edges)
    tree=cKDTree([key(r[:3],r[3:6]) for r in data])
    cones=set();groups={i:set() for i in range(len(data))};by_id={}
    for i in range(1,faces.Extent()+1):
        f=cq.Shape.cast(faces.FindKey(i));by_id[i]=f
        if f.geomType()=='CONE':cones.add(i)
        if f.geomType()!='CYLINDER':continue
        c=BRepAdaptor_Surface(f.wrapped).Cylinder();a=c.Axis();p=a.Location();d=a.Direction()
        distance,index=tree.query(key([p.X(),p.Y(),p.Z()],[d.X(),d.Y(),d.Z()]))
        if distance<1e-5 and abs(c.Radius()-data[index,6])<1e-6:groups[int(index)].add(i)
    assert len(cones)==2, 'Expected the inner and outer cone'
    accepted=[]
    for index,wall_faces in groups.items():
        assert wall_faces, f'Missing bore wall {index}'
        mouth_edges={c:{} for c in cones};edge_ids=set()
        for face_id in wall_faces:
            for edge in by_id[face_id].Edges():edge_ids.add(edges.FindIndex(edge.wrapped))
        for edge_id in edge_ids:
            adjacent={faces.FindIndex(f) for f in edges.FindFromIndex(edge_id)}
            external=adjacent-wall_faces
            assert external<=cones, f'Bore {index} has a cap or other blocking boundary'
            for cone in external:mouth_edges[cone][edge_id]=cq.Shape.cast(edges.FindKey(edge_id))
        for cone,boundary in mouth_edges.items():
            wires=cq.Wire.combine(list(boundary.values()),tol=1e-6)
            assert len(wires)==1 and wires[0].IsClosed(), f'Bore {index} lacks a closed mouth on cone {cone}'
        accepted.append(index)
    return {'method':'Exact BREP edge-face adjacency: each cylindrical bore has two closed mouth loops, one on each cone, and no cap faces',
            'checked_holes':len(data),'accepted_holes':len(accepted),'passed':len(accepted)==len(data)}
