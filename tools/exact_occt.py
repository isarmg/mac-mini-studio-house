"""Build OCCT topology directly from the canonical exact geometry packet."""
from exact_geometry import *
import OCP.Geom as G
import OCP.Geom2d as G2
from OCP.gp import *
from OCP.TColgp import TColgp_Array1OfPnt,TColgp_Array1OfPnt2d
from OCP.TColStd import TColStd_Array1OfReal,TColStd_Array1OfInteger
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex,BRepBuilderAPI_MakeEdge
from OCP.TopoDS import TopoDS_Face,TopoDS_Wire,TopoDS_Shell,TopoDS_Solid
from OCP.TopLoc import TopLoc_Location
from OCP.BRepCheck import BRepCheck_Analyzer

def arr(cls,values):
    result=cls(1,len(values))
    for i,v in enumerate(values,1):result.SetValue(i,v)
    return result

def frame(d,dim=3):
    if dim==2:return gp_Ax22d(gp_Pnt2d(*d['origin']),gp_Dir2d(*d['x']),gp_Dir2d(*d['y']))
    a=gp_Ax3(gp_Pnt(*d['origin']),gp_Dir(*d['z']),gp_Dir(*d['x']))
    if a.YDirection().Dot(gp_Dir(*d['y']))<0:a.YReverse()
    return a

def curve(d,dim=3):
    module=G if dim==3 else G2;prefix='Geom_' if dim==3 else 'Geom2d_'
    P=gp_Pnt if dim==3 else gp_Pnt2d;D=gp_Dir if dim==3 else gp_Dir2d
    kind=d['type'];ctor=getattr(module,prefix+kind)
    if kind in ('BSplineCurve','BezierCurve'):
        poles=arr(TColgp_Array1OfPnt if dim==3 else TColgp_Array1OfPnt2d,[P(*p) for p in d['poles']]);weights=arr(TColStd_Array1OfReal,d['weights'])
        if kind=='BezierCurve':return ctor(poles,weights)
        return ctor(poles,weights,arr(TColStd_Array1OfReal,d['knots']),arr(TColStd_Array1OfInteger,d['multiplicities']),d['degree'],d['periodic'])
    if kind=='Line':return ctor(P(*d['origin']),D(*d['direction']))
    axis=frame(d,dim)
    if dim==3:axis=axis.Ax2()
    if kind=='Circle':return ctor(axis,d['radius'])
    if kind in ('Ellipse','Hyperbola'):return ctor(axis,d['major_radius'],d['minor_radius'])
    if kind=='Parabola':return ctor(axis,d['focal'])
    raise ValueError(kind)

def surface(d):
    kind=d['type']
    if kind=='Plane':return G.Geom_Plane(frame(d))
    if kind=='CylindricalSurface':return G.Geom_CylindricalSurface(frame(d),d['radius'])
    if kind=='ConicalSurface':return G.Geom_ConicalSurface(frame(d),d['semi_angle'],d['radius'])
    if kind=='SurfaceOfLinearExtrusion':return G.Geom_SurfaceOfLinearExtrusion(curve(d['basis']['original']),gp_Dir(*d['direction']))
    raise ValueError('Unsupported exact surface '+kind)

def build_body(d,validate=True,with_maps=False,bounded_edges=False):
    builder=BRep_Builder();verts=[];edges=[];faces=[]
    for v in d['vertices']:
        shape=BRepBuilderAPI_MakeVertex(gp_Pnt(*v['point'])).Vertex();builder.UpdateVertex(shape,v['tolerance']);verts.append(shape)
    for e in d['edges']:
        c=e['curve']
        # STEP readers otherwise reproject a trimmed edge's endpoints onto a
        # much longer underlying spline. The canonical algebraic segment has
        # identical geometry and parameters, with its bounds already explicit.
        definition=dict(type='BSplineCurve',**c['nurbs']) if bounded_edges and c['original']['type']=='BSplineCurve' else c['original']
        edge=BRepBuilderAPI_MakeEdge(curve(definition),verts[e['vertices'][0]],verts[e['vertices'][1]],*c['range']).Edge()
        builder.UpdateEdge(edge,e['tolerance']);edges.append(edge)
    for fd in d['faces']:
        face=TopoDS_Face();s=surface(fd['surface']);builder.MakeFace(face,s,TopLoc_Location(),fd['tolerance'])
        trims={}
        for loop in fd['loops']:
            for t in loop['trims']:trims.setdefault(t['edge'],[]).append(t)
        for eid,ts in trims.items():
            ts=sorted(ts,key=lambda t:t['reversed']);cs=[curve(t['curve']['original'],2) for t in ts]
            if len(cs)==1:builder.UpdateEdge(edges[eid],cs[0],face,d['edges'][eid]['tolerance'])
            elif len(cs)==2:builder.UpdateEdge(edges[eid],cs[0],cs[1],face,d['edges'][eid]['tolerance'])
            else:raise ValueError('Non-manifold edge')
            builder.Range(edges[eid],face,*ts[0]['curve']['range'])
        for loop in fd['loops']:
            wire=TopoDS_Wire();builder.MakeWire(wire)
            for t in loop['trims']:builder.Add(wire,edges[t['edge']].Oriented(TopAbs_REVERSED if t['reversed'] else TopAbs_FORWARD))
            wire.Closed(True);builder.Add(face,wire)
        faces.append(face.Oriented(TopAbs_REVERSED if fd['reversed'] else TopAbs_FORWARD))
    solid=TopoDS_Solid();builder.MakeSolid(solid)
    for sf in d['shells']:
        shell=TopoDS_Shell();builder.MakeShell(shell)
        for i in sf:builder.Add(shell,faces[i])
        shell.Closed(True);builder.Add(solid,shell)
    if validate and not BRepCheck_Analyzer(solid).IsValid():raise ValueError('Reconstructed canonical BREP is invalid')
    shape=cq.Solid(solid)
    return (shape,{'vertices':verts,'edges':edges,'faces':faces}) if with_maps else shape

def build(packet,validate=True,bounded_edges=False):
    solids=[build_body(b,validate=validate,bounded_edges=bounded_edges) for b in packet['bodies']]
    return solids[0] if len(solids)==1 else cq.Compound.makeCompound(solids)

def write_step(shape,destination):
    """Serialize STEP reals with 17 significant digits, without shape edits.

    The usual STEP writer's shorter decimal format can lose normalized knot
    precision on a tiny trimmed span. Configure its numeric serializer rather
    than enlarging comparison tolerances or refitting the edge.
    """
    import io
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from OCP.StepData import StepData_StepWriter
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone
    writer=STEPControl_Writer()
    Interface_Static.SetIVal_s('write.surfacecurve.mode',1)
    Interface_Static.SetIVal_s('write.precision.mode',0)
    Interface_Static.SetCVal_s('xstep.cascade.unit','MM')
    Interface_Static.SetCVal_s('write.step.unit','MM')
    if writer.Transfer(shape.wrapped,STEPControl_AsIs)!=IFSelect_RetDone:
        raise ValueError('STEP transfer failed')
    serializer=StepData_StepWriter(writer.Model())
    serializer.FloatWriter().SetFormat('%.16E',True)
    serializer.SendModel(writer.WS().Protocol())
    output=io.BytesIO()
    if not serializer.Print(output):raise ValueError('STEP serialization failed')
    Path(destination).write_bytes(output.getvalue())

def run(source,destination):
    packet=json.loads(Path(source).read_text(encoding='utf-8'));shape=build(packet)
    destination=Path(destination);shape.exportBrep(str(destination.with_suffix('.brep')))
    write_step(shape,destination.with_suffix('.stp'))
    print('OCCT direct reconstruction passed:',destination,flush=True)
    return shape

if __name__=='__main__':run(sys.argv[1],sys.argv[2])
