"""Lossless geometric definitions and explicit BREP topology for native adapters.

Source input is an accepted procedural OCCT BREP, never a STEP reimport.
NURBS conversion here is algebraic (Bezier/conics), never point fitting.
All coordinates are millimetres. Native adapters explicitly handle their units.
"""
from pathlib import Path
import sys, json, hashlib, math
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.vendor'))
import cadquery as cq
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.Geom import Geom_TrimmedCurve
from OCP.Geom2d import Geom2d_TrimmedCurve
from OCP.GeomConvert import GeomConvert
from OCP.Geom2dConvert import Geom2dConvert
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_VERTEX, TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def vector(p):
    return [float(p.X()),float(p.Y())]+([float(p.Z())] if hasattr(p,'Z') else [])

def axis_frame(axis):
    return {'origin':vector(axis.Location()),'x':vector(axis.XDirection()),
            'y':vector(axis.YDirection()),'z':vector(axis.Direction())}

def spline_data(curve):
    return {'degree':curve.Degree(),'poles':[vector(curve.Pole(i)) for i in range(1,curve.NbPoles()+1)],
            'weights':[float(curve.Weight(i)) for i in range(1,curve.NbPoles()+1)],
            'knots':[float(curve.Knot(i)) for i in range(1,curve.NbKnots()+1)],
            'multiplicities':[curve.Multiplicity(i) for i in range(1,curve.NbKnots()+1)],
            'periodic':bool(curve.IsPeriodic()),'domain':[float(curve.FirstParameter()),float(curve.LastParameter())]}

def bezier_data(curve):
    n=curve.Degree()
    return {'degree':n,'poles':[vector(curve.Pole(i)) for i in range(1,curve.NbPoles()+1)],
            'weights':[float(curve.Weight(i)) for i in range(1,curve.NbPoles()+1)],
            'knots':[0.,1.],'multiplicities':[n+1,n+1],'periodic':False,'domain':[0.,1.]}

def curve_data(curve,first,last,dimension=3):
    kind=curve.DynamicType().Name().replace('Geom2d_','').replace('Geom_','')
    if kind=='TrimmedCurve':return curve_data(curve.BasisCurve(),first,last,dimension)
    original={'type':kind}
    if kind=='BSplineCurve':original.update(spline_data(curve))
    elif kind=='BezierCurve':original.update(bezier_data(curve))
    elif kind=='Line':original.update(origin=vector(curve.Position().Location()),direction=vector(curve.Position().Direction()))
    elif kind in ('Circle','Ellipse','Hyperbola','Parabola'):
        if dimension==3:original.update(axis_frame(curve.Position()))
        else:
            position=curve.Position()
            original.update(origin=vector(position.Location()),x=vector(position.XDirection()),y=vector(position.YDirection()))
        if kind=='Circle':original['radius']=curve.Radius()
        elif kind in ('Ellipse','Hyperbola'):original.update(major_radius=curve.MajorRadius(),minor_radius=curve.MinorRadius())
        else:original['focal']=curve.Focal()
    else:raise ValueError('Unsupported exact curve '+kind)
    if dimension==3:
        limited=Geom_TrimmedCurve(curve,float(first),float(last))
        spline=GeomConvert.CurveToBSplineCurve_s(limited)
    else:
        limited=Geom2d_TrimmedCurve(curve,float(first),float(last))
        spline=Geom2dConvert.CurveToBSplineCurve_s(limited)
    # This is knot insertion / exact rational conversion, not interpolation.
    result={'original':original,'range':[float(first),float(last)],'nurbs':spline_data(spline)}
    result['endpoints']=[vector(curve.Value(float(first))),vector(curve.Value(float(last)))]
    return result

def surface_data(surface,uv):
    kind=surface.DynamicType().Name().replace('Geom_','')
    if kind=='RectangularTrimmedSurface':return surface_data(surface.BasisSurface(),uv)
    result={'type':kind,'uv_bounds':[float(x) for x in uv]}
    if kind in ('Plane','CylindricalSurface','ConicalSurface'):
        result.update(axis_frame(surface.Position()))
        if kind=='CylindricalSurface':result['radius']=surface.Radius()
        elif kind=='ConicalSurface':result.update(radius=surface.RefRadius(),semi_angle=surface.SemiAngle())
    elif kind=='SurfaceOfLinearExtrusion':
        basis=surface.BasisCurve();result['direction']=vector(surface.Direction())
        result['basis']=curve_data(basis,uv[0],uv[1])
    elif kind in ('BSplineSurface','BezierSurface'):
        result.update(u_degree=surface.UDegree(),v_degree=surface.VDegree(),
            poles=[[vector(surface.Pole(i,j)) for j in range(1,surface.NbVPoles()+1)] for i in range(1,surface.NbUPoles()+1)],
            weights=[[surface.Weight(i,j) for j in range(1,surface.NbVPoles()+1)] for i in range(1,surface.NbUPoles()+1)])
        for direction in ('U','V'):
            prefix=direction.lower()
            if kind=='BezierSurface':
                result[prefix+'_knots']=[0.,1.];result[prefix+'_multiplicities']=[getattr(surface,direction+'Degree')()+1]*2
                result[prefix+'_periodic']=False
            else:
                result[prefix+'_knots']=[getattr(surface,direction+'Knot')(i) for i in range(1,getattr(surface,'Nb'+direction+'Knots')()+1)]
                result[prefix+'_multiplicities']=[getattr(surface,direction+'Multiplicity')(i) for i in range(1,getattr(surface,'Nb'+direction+'Knots')()+1)]
                result[prefix+'_periodic']=getattr(surface,'Is'+direction+'Periodic')()
    else:raise ValueError('Unsupported exact surface '+kind)
    result['check_points']=[{'uv':[u,v],'point':vector(surface.Value(u,v))}
        for u in [uv[0]+f*(uv[1]-uv[0]) for f in (.13,.47,.83)]
        for v in [uv[2]+f*(uv[3]-uv[2]) for f in (.17,.53,.79)]]
    return result

def indexed(shape,kind):
    result=TopTools_IndexedMapOfShape();TopExp.MapShapes_s(shape.wrapped,kind,result);return result

def body_data(solid):
    vm=indexed(solid,TopAbs_VERTEX);em=indexed(solid,TopAbs_EDGE);fm=indexed(solid,TopAbs_FACE)
    result={'vertices':[],'edges':[],'faces':[],'shells':[]}
    for i in range(1,vm.Extent()+1):
        v=TopoDS.Vertex_s(vm.FindKey(i));result['vertices'].append({'point':vector(BRep_Tool.Pnt_s(v)),'tolerance':BRep_Tool.Tolerance_s(v)})
    for i in range(1,em.Extent()+1):
        e=TopoDS.Edge_s(em.FindKey(i).Oriented(TopAbs_FORWARD));a=BRepAdaptor_Curve(e)
        curve=BRep_Tool.Curve_s(e,0.,0.)
        if curve is None:raise ValueError('Degenerate edge requires explicit support')
        v0=TopExp.FirstVertex_s(e,True);v1=TopExp.LastVertex_s(e,True)
        result['edges'].append({'vertices':[vm.FindIndex(v0)-1,vm.FindIndex(v1)-1],
            'tolerance':BRep_Tool.Tolerance_s(e),'curve':curve_data(curve,a.FirstParameter(),a.LastParameter())})
    for i in range(1,fm.Extent()+1):
        raw=TopoDS.Face_s(fm.FindKey(i));face=TopoDS.Face_s(raw.Oriented(TopAbs_FORWARD))
        surface=BRep_Tool.Surface_s(face);uv=BRepTools.UVBounds_s(face)
        loops=[];outer=BRepTools.OuterWire_s(face)
        for wire in cq.Face(face).Wires():
            trims=[];explorer=BRepTools_WireExplorer(wire.wrapped,face)
            while explorer.More():
                edge=explorer.Current();adaptor=BRepAdaptor_Curve2d(edge,face)
                curve=BRep_Tool.CurveOnSurface_s(edge,face,0.,0.)
                trims.append({'edge':em.FindIndex(edge)-1,'reversed':edge.Orientation()==TopAbs_REVERSED,
                    'curve':curve_data(curve,adaptor.FirstParameter(),adaptor.LastParameter(),2)})
                explorer.Next()
            if not trims:raise ValueError('Empty trim loop')
            loops.append({'outer':wire.wrapped.IsSame(outer),'trims':trims})
        result['faces'].append({'surface':surface_data(surface,uv),'reversed':raw.Orientation()==TopAbs_REVERSED,
            'tolerance':BRep_Tool.Tolerance_s(face),'loops':loops})
    for shell in solid.Shells():result['shells'].append([fm.FindIndex(f.wrapped)-1 for f in shell.Faces()])
    result['counts']={k:len(result[k]) for k in ('vertices','edges','faces','shells')}
    result['g3_seams']=g3_seams(result)
    return result

def g3_seams(data):
    incidence={}
    for fi,f in enumerate(data['faces']):
        for loop in f['loops']:
            for t in loop['trims']:incidence.setdefault(t['edge'],[]).append((fi,t))
    result=[]
    for ei,uses in incidence.items():
        e=data['edges'][ei];ends=e['curve']['endpoints']
        if len(uses)!=2 or e['curve']['original']['type']!='Line':continue
        if math.hypot(ends[1][0]-ends[0][0],ends[1][1]-ends[0][1])>1e-7 or abs(ends[1][2]-ends[0][2])<1e-7:continue
        planes=[(fi,t) for fi,t in uses if data['faces'][fi]['surface']['type']=='Plane']
        curved=[(fi,t) for fi,t in uses if data['faces'][fi]['surface']['type']=='SurfaceOfLinearExtrusion']
        if len(planes)!=1 or len(curved)!=1:continue
        fi,t=curved[0];s=data['faces'][fi]['surface'];basis=s['basis']['original']
        if basis.get('degree')!=7 or abs(abs(s['direction'][2])-1)>1e-10:continue
        uv0,uv1=t['curve']['endpoints'];u=(uv0[0]+uv1[0])/2
        if abs(uv0[0]-uv1[0])>1e-9 or min(abs(u-x) for x in basis['domain'])>1e-8:continue
        result.append({'edge':ei,'curved_face':fi,'plane_face':planes[0][0],'uv':[u,(uv0[1]+uv1[1])/2],
            'z_span_mm':sorted([ends[0][2],ends[1][2]]),'position_tolerance_mm':max(e['tolerance'],1e-7)})
    return result

def export(path,destination):
    path=Path(path);shape=cq.Shape.importBrep(str(path));b=shape.BoundingBox()
    packet={'schema':'exact-cad-v1','units':'mm','provenance':{'source_brep':path.relative_to(ROOT).as_posix(),
        'source_sha256':sha(path),'source_is_step_roundtrip':False},
        'bounds':[b.xmin,b.xmax,b.ymin,b.ymax,b.zmin,b.zmax],
        'bodies':[body_data(s) for s in shape.Solids()]}
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(packet,separators=(',',':'),allow_nan=False),encoding='utf-8')
    print('Exact geometry packet:',destination,'bodies',len(packet['bodies']),flush=True)
    return packet

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('brep');parser.add_argument('destination');a=parser.parse_args()
    export(ROOT/a.brep,ROOT/a.destination)
