using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using Rhino;
using Rhino.Geometry;
using Rhino.FileIO;
using Rhino.Runtime.InProcess;

public static class RhinoExact {
    static double maxTrimNormalizationMm=0;
    static int normalizedTrimJoins=0;
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] static extern bool SetDllDirectory(string path);
    static Point3d P(object p) {var a=Packet.V(p);return new Point3d(a[0],a[1],a.Length>2?a[2]:0);}
    static Vector3d V(object p) {var a=Packet.V(p);return new Vector3d(a[0],a[1],a.Length>2?a[2]:0);}
    static NurbsCurve Curve(Dictionary<string,object> data) {
        Packet.Need(!(bool)data["periodic"],"Periodic spline needs an explicit knot adapter");
        var points=Packet.A(data["poles"]);var weights=Packet.V(data["weights"]);int degree=Packet.I(data["degree"]);
        var curve=new NurbsCurve(Packet.A(points[0]).Length,weights.Any(w=>w!=1.0),degree+1,points.Length);
        for(int i=0;i<points.Length;i++)curve.Points.SetPoint(i,P(points[i]),weights[i]);
        var knots=Packet.Knots(data);Packet.Need(curve.Knots.Count==knots.Length-2,"Curve knot count mismatch");
        for(int i=0;i<curve.Knots.Count;i++)curve.Knots[i]=knots[i+1];
        Packet.Need(curve.IsValid,"Invalid exact NURBS curve");return curve;
    }
    static Surface Surface(Dictionary<string,object> data) {
        string kind=(string)data["type"];var uv=Packet.V(data["uv_bounds"]);
        if(kind=="Plane")return new PlaneSurface(new Plane(P(data["origin"]),V(data["x"]),V(data["y"])),new Interval(uv[0],uv[1]),new Interval(uv[2],uv[3]));
        if(kind=="SurfaceOfLinearExtrusion") {
            var basis=Packet.D(Packet.D(data["basis"])["nurbs"]);var points=Packet.A(basis["poles"]);var weights=Packet.V(basis["weights"]);
            var s=NurbsSurface.Create(3,weights.Any(w=>w!=1.0),Packet.I(basis["degree"])+1,2,points.Length,2);var direction=V(data["direction"]);
            var knots=Packet.Knots(basis);Packet.Need(s.KnotsU.Count==knots.Length-2,"Surface knot count mismatch");
            for(int i=0;i<s.KnotsU.Count;i++)s.KnotsU[i]=knots[i+1];
            s.KnotsV[0]=uv[2];s.KnotsV[1]=uv[3];
            for(int i=0;i<points.Length;i++)for(int j=0;j<2;j++)s.Points.SetControlPoint(i,j,new ControlPoint(P(points[i])+direction*uv[2+j],weights[i]));
            return s;
        }
        if(kind=="CylindricalSurface" || kind=="ConicalSurface") {
            var origin=P(data["origin"]);var x=V(data["x"]);var axis=V(data["z"]);double r=Packet.N(data["radius"]);
            double angle=kind=="ConicalSurface"?Packet.N(data["semi_angle"]):0;
            var a=origin+x*(r+uv[2]*Math.Sin(angle))+axis*(uv[2]*Math.Cos(angle));
            var b=origin+x*(r+uv[3]*Math.Sin(angle))+axis*(uv[3]*Math.Cos(angle));
            var meridian=new LineCurve(a,b);meridian.Domain=new Interval(uv[2],uv[3]);
            var rotationAxis=Vector3d.CrossProduct(x,V(data["y"]));
            var s=RevSurface.Create(meridian,new Line(origin,origin+rotationAxis),0,2*Math.PI);
            Packet.Need(s!=null,"Revolution surface creation failed");s.SetDomain(0,new Interval(0,2*Math.PI));s.SetDomain(1,new Interval(uv[2],uv[3]));return s;
        }
        throw new Exception("Unsupported exact surface "+kind);
    }
    static Brep Build(Dictionary<string,object> data) {
        var brep=new Brep();var vertices=Packet.A(data["vertices"]);var edges=Packet.A(data["edges"]);var faces=Packet.A(data["faces"]);
        foreach(var raw in vertices) {var d=Packet.D(raw);brep.Vertices.Add(P(d["point"]),Packet.N(d["tolerance"]));}
        foreach(var raw in edges) {
            var d=Packet.D(raw);var curve=Curve(Packet.D(Packet.D(d["curve"])["nurbs"]));int ci=brep.Curves3D.Add(curve);var vi=Packet.A(d["vertices"]);
            brep.Edges.Add(Packet.I(vi[0]),Packet.I(vi[1]),ci,Packet.N(d["tolerance"]));
        }
        int faceIndex=0;
        foreach(var raw in faces) {
            var d=Packet.D(raw);var definition=Packet.D(d["surface"]);var surface=Surface(definition);
            Packet.Need(surface.IsValid,"Invalid support surface "+faceIndex);
            foreach(var qraw in Packet.A(definition["check_points"])) {
                var q=Packet.D(qraw);var uv=Packet.V(q["uv"]);double delta=surface.PointAt(uv[0],uv[1]).DistanceTo(P(q["point"]));
                Packet.Need(delta<1e-7,"Surface parameter mapping differs: face "+faceIndex+", error "+delta);
            }
            var face=brep.Faces.Add(brep.AddSurface(surface));face.OrientationIsReversed=(bool)d["reversed"];
            foreach(var lraw in Packet.A(d["loops"])) {
                var l=Packet.D(lraw);var loop=brep.Loops.Add((bool)l["outer"]?BrepLoopType.Outer:BrepLoopType.Inner,face);
                var trims=Packet.A(l["trims"]);var curves=new List<NurbsCurve>();
                foreach(var traw in trims) {var t=Packet.D(traw);var c=Curve(Packet.D(Packet.D(t["curve"])["nurbs"]));if((bool)t["reversed"])c.Reverse();curves.Add(c);}
                for(int k=0;k<curves.Count;k++) {
                    int next=(k+1)%curves.Count;var a=curves[k].PointAtEnd;var b=curves[next].PointAtStart;
                    if(a.DistanceTo(b)>1e-12) {
                        double gap=surface.PointAt(a.X,a.Y).DistanceTo(surface.PointAt(b.X,b.Y));
                        double budget=Math.Max(Packet.N(Packet.D(edges[Packet.I(Packet.D(trims[k])["edge"])])["tolerance"]),Packet.N(Packet.D(edges[Packet.I(Packet.D(trims[next])["edge"])])["tolerance"]));
                        Packet.Need(gap<=2*budget,"Source trim gap exceeds inherited tolerance: "+gap);
                        var midpoint=new Point3d((a.X+b.X)/2,(a.Y+b.Y)/2,0);curves[k].SetEndPoint(midpoint);curves[next].SetStartPoint(midpoint);
                        maxTrimNormalizationMm=Math.Max(maxTrimNormalizationMm,gap/2);normalizedTrimJoins++;
                    }
                }
                int ti=0;
                foreach(var traw in trims) {
                    var t=Packet.D(traw);var curve=Curve(Packet.D(Packet.D(t["curve"])["nurbs"]));bool reverse=(bool)t["reversed"];
                    curve.Dispose();curve=curves[ti++];int ci=brep.Curves2D.Add(curve);
                    var trim=brep.Trims.Add(brep.Edges[Packet.I(t["edge"])],reverse,loop,ci);
                    trim.SetTolerances(0,0);trim.IsoStatus=surface.IsIsoparametric(curve);trim.TrimType=BrepTrimType.Mated;
                }
            }
            faceIndex++;
        }
        brep.SetTolerancesBoxesAndFlags();string diagnostic;
        Packet.Need(brep.IsValidTopology(out diagnostic),"Topology: "+diagnostic);
        Packet.Need(brep.IsValidGeometry(out diagnostic),"Geometry: "+diagnostic);
        Packet.Need(brep.IsValidTolerancesAndFlags(out diagnostic),"Tolerances: "+diagnostic);
        Packet.Need(brep.IsSolid,"Directly built Rhino BREP is not a solid");return brep;
    }
    static object Verify(Brep actual,Dictionary<string,object> data) {
        // Rebuild expected definitions independently from the canonical packet.
        using(var expected=Build(data)) {
            Packet.Need(actual.Faces.Count==expected.Faces.Count && actual.Edges.Count==expected.Edges.Count && actual.Vertices.Count==expected.Vertices.Count && actual.Trims.Count==expected.Trims.Count,"Readback topology counts changed");
            for(int i=0;i<actual.Vertices.Count;i++)Packet.Need(actual.Vertices[i].Location.DistanceTo(expected.Vertices[i].Location)<1e-10,"Readback vertex changed");
            for(int i=0;i<actual.Edges.Count;i++) {
                var a=actual.Edges[i];var e=expected.Edges[i];Packet.Need(a.StartVertex.VertexIndex==e.StartVertex.VertexIndex && a.EndVertex.VertexIndex==e.EndVertex.VertexIndex,"Readback shared edge incidence changed");
                Packet.Need(a.EdgeCurve.ToNurbsCurve().EpsilonEquals(e.EdgeCurve.ToNurbsCurve(),1e-12),"Readback 3D curve controls, weights, knots or degree changed: "+i);
            }
            var faceReports=new List<object>();
            for(int i=0;i<actual.Faces.Count;i++) {
                var a=actual.Faces[i];var e=expected.Faces[i];var sa=a.UnderlyingSurface();var se=e.UnderlyingSurface();
                Packet.Need(sa.GetType()==se.GetType(),"Readback support surface representation changed: "+i);
                Packet.Need(GeometryBase.GeometryEquals(sa,se) || sa.ToNurbsSurface().EpsilonEquals(se.ToNurbsSurface(),1e-12),"Readback exact support surface data changed: "+i);
                Packet.Need(a.OrientationIsReversed==e.OrientationIsReversed && a.Loops.Count==e.Loops.Count,"Readback face orientation/loops changed");
                faceReports.Add(new {face=i,type=sa.GetType().Name,exact_support_data_preserved=true});
            }
            for(int i=0;i<actual.Trims.Count;i++) {
                var a=actual.Trims[i];var e=expected.Trims[i];Packet.Need(a.Edge.EdgeIndex==e.Edge.EdgeIndex && a.Loop.LoopIndex==e.Loop.LoopIndex,"Readback trim incidence changed");
                Packet.Need(a.TrimCurve.ToNurbsCurve().EpsilonEquals(e.TrimCurve.ToNurbsCurve(),1e-12),"Readback UV trim controls/knots changed: "+i);
            }
            var seamReports=new List<object>();
            foreach(var raw in Packet.A(data["g3_seams"])) {
                var d=Packet.D(raw);var uv=Packet.V(d["uv"]);var curved=actual.Faces[Packet.I(d["curved_face"])].UnderlyingSurface();var planar=actual.Faces[Packet.I(d["plane_face"])].UnderlyingSurface();
                Point3d point;Vector3d[] derivatives;Packet.Need(curved.Evaluate(uv[0],uv[1],3,out point,out derivatives),"Readback third derivative evaluation failed");
                var a=derivatives[0];var b=derivatives[2];var c=derivatives[5];double speed2=a.X*a.X+a.Y*a.Y;
                Packet.Need(speed2>1e-16,"Degenerate G3 seam tangent");double cross=a.X*b.Y-a.Y*b.X;
                double curvature=cross/Math.Pow(speed2,1.5);double rate=(a.X*c.Y-a.Y*c.X)/(speed2*speed2)-3*cross*(a.X*b.X+a.Y*b.Y)/(speed2*speed2*speed2);
                double pu,pv;Packet.Need(planar.ClosestPoint(point,out pu,out pv),"G3 adjacent plane evaluation failed");
                double gap=point.DistanceTo(planar.PointAt(pu,pv));var normal=planar.NormalAt(pu,pv);a.Unitize();normal.Unitize();double tangentError=Math.Abs(a*normal);
                Packet.Need(gap<=Packet.N(d["position_tolerance_mm"])*2 && tangentError<1e-9 && Math.Abs(curvature)<1e-8 && Math.Abs(rate)<1e-8,"Final native G3 seam failed: edge "+d["edge"]);
                seamReports.Add(new {edge=d["edge"],curved_face=d["curved_face"],plane_face=d["plane_face"],gap_mm=gap,tangent_sine_error=tangentError,curvature_per_mm=curvature,curvature_rate_per_mm2=rate});
            }
            return new {faces=faceReports,edge_count=actual.Edges.Count,vertex_count=actual.Vertices.Count,trim_count=actual.Trims.Count,all_control_points_weights_knots_and_topology_checked=true,g3_seams=seamReports};
        }
    }
    public static void Run(string input,string output,string report) {
        SetDllDirectory(@"C:\Program Files\Rhino 8\System");
        using(var core=new RhinoCore(new[]{"/nosplash","/notemplate"},WindowStyle.NoWindow)) {
            var packet=Packet.Read(input);Packet.Need((string)packet["units"]=="mm","Expected millimetres");int count=0;
            using(var doc=RhinoDoc.CreateHeadless(null)) {
                doc.ModelUnitSystem=UnitSystem.Millimeters;doc.ModelAbsoluteTolerance=1e-6;
                foreach(var raw in Packet.A(packet["bodies"])) {using(var brep=Build(Packet.D(raw))) {var attributes=new Rhino.DocObjects.ObjectAttributes();attributes.SetUserString("exact_canonical_body",count.ToString());doc.Objects.AddBrep(brep,attributes);count++;}}
                Packet.Need(doc.WriteFile(output,new FileWriteOptions{SuppressDialogBoxes=true,SuppressAllInput=true,IncludeRenderMeshes=false,IncludePreviewImage=false,FileVersion=8}),"3DM save failed");
            }
            int readCount=0;var checks=new List<object>();var sourceBodies=Packet.A(packet["bodies"]);
            using(var reread=RhinoDoc.OpenHeadless(output)) {
                Packet.Need(reread!=null && reread.ModelUnitSystem==UnitSystem.Millimeters,"Native reread failed");
                var indices=new HashSet<int>();foreach(var obj in reread.Objects) {var b=obj.Geometry as Brep;Packet.Need(b!=null && b.IsSolid && b.IsValid,"Invalid native reread BREP");int index=Int32.Parse(obj.Attributes.GetUserString("exact_canonical_body"));Packet.Need(indices.Add(index),"Duplicate native body identity");checks.Add(Verify(b,Packet.D(sourceBodies[index])));readCount++;}
            }
            Packet.Need(readCount==count,"Body count changed");
            Packet.Write(report,new {construction="exact_parameter_and_topology_API",step_imported=false,readback_performed=true,solids=readCount,checks=checks,trim_normalization=new{joins=normalizedTrimJoins/2,max_endpoint_move_mm=maxTrimNormalizationMm,policy="UV endpoint normalization within inherited source tolerance; support surfaces and 3D edge curves unchanged"},passed=true});
            Console.WriteLine("Rhino direct construction / native reread passed: "+readCount+" solids");
        }
    }
    public static void ExportParasolid(string input,string output,string report) {
        SetDllDirectory(@"C:\Program Files\Rhino 8\System");
        using(var core=new RhinoCore(new[]{"/nosplash","/notemplate"},WindowStyle.NoWindow))using(var doc=RhinoDoc.CreateHeadless(null)) {
            var packet=Packet.Read(input);doc.ModelUnitSystem=UnitSystem.Millimeters;doc.ModelAbsoluteTolerance=1e-7;
            foreach(var raw in Packet.A(packet["bodies"]))using(var brep=Build(Packet.D(raw)))doc.Objects.AddBrep(brep);
            Packet.Need(FileX_T.Write(output,doc,new FileX_TWriteOptions{Type=FileX_TWriteOptions.X_T_Types.Default}),"Direct Parasolid writer failed");
            Packet.Write(report,new{construction="canonical_exact_Rhino_BREP_to_native_Parasolid_writer",step_imported=false,readback_performed=false,passed=false,strict_validation_pending=true});
            Console.WriteLine("Canonical exact BREP exported with native Parasolid writer; strict verification pending");
        }
    }
}
