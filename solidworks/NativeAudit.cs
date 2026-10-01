using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public static class NativeAudit {
    public static object State(ModelDoc2 doc) {
        var timer=System.Diagnostics.Stopwatch.StartNew();var body=NativeCommon.OnlyBody(doc);
        Console.WriteLine("Inspecting native solid: "+body.GetFaceCount()+" faces");
        var fault=body.Check3;int count=fault==null?0:fault.Count;
        NativeCommon.Need(count==0,"Native solid check found "+count+" faults");SwSession.Release(fault);
        Console.WriteLine("Kernel check seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
        var support=new List<object>();var cylinders=new List<object>();var planes=new List<object>();var cones=new List<object>();
        int faceEuler=0;
        foreach(Face2 face in (object[])body.GetFaces()) {
            var surface=(Surface)face.GetSurface();double[] uv=Packet.V(face.GetUVBounds());
            faceEuler+=2-face.GetLoopCount();
            if(surface.IsCylinder())cylinders.Add(Packet.V(surface.CylinderParams));
            else if(surface.IsPlane())planes.Add(new{parameters=surface.PlaneParams,area_m2=face.GetArea()});
            else if(surface.IsCone()) {
                var p=Packet.V(surface.Evaluate((uv[0]+uv[1])/2,.75*uv[2]+.25*uv[3],0,0));
                var q=Packet.V(surface.Evaluate((uv[0]+uv[1])/2,.25*uv[2]+.75*uv[3],0,0));
                double r1=Math.Sqrt(p[0]*p[0]+p[1]*p[1]),r2=Math.Sqrt(q[0]*q[0]+q[1]*q[1]);
                double k=(r2-r1)/(q[2]-p[2]);
                cones.Add(new{slope=k,intercept_mm=(r1-k*p[2])*1000,angle_degrees=Math.Atan(1/Math.Abs(k))*180/Math.PI});
            } else support.Add(SwReadback.SurfaceData(surface,uv));
        }
        var features=new List<object>();
        for(var f=(Feature)doc.FirstFeature();f!=null;f=(Feature)f.GetNextFeature()) {
            bool warning=false;int error=f.GetErrorCode2(out warning);
            NativeCommon.Need(error==0 || warning,"Native feature error: "+f.Name+" ("+error+")");
            NativeCommon.Need(!f.IsSuppressed(),"Required native feature is suppressed: "+f.Name);
            features.Add(new{name=f.Name,type=f.GetTypeName2()=="ICE"?f.GetTypeName():f.GetTypeName2(),error=error,warning=warning,suppressed=f.IsSuppressed(),
                dimensions=NativeCommon.Dimensions(f)});
        }
        var manager=doc.GetEquationMgr();var equations=new List<object>();
        for(int i=0;i<manager.GetCount();i++)equations.Add(new{expression=manager.Equation[i],value=manager.Value[i],global_variable=manager.GlobalVariable[i],status=manager.Status});
        int vertices=((object[])body.GetVertices()).Length,edges=body.GetEdgeCount(),closedEdges=0;
        foreach(Edge edge in (object[])body.GetEdges())if(edge.GetStartVertex()==null && edge.GetEndVertex()==null)closedEdges++;
        return new{units="m",body_faults=count,body_count=1,bounds_mm=NativeCommon.ExactBounds(body),
            counts=new{faces=body.GetFaceCount(),edges=edges,vertices=vertices,closed_edges_without_vertices=closedEdges},boundary_euler_characteristic=vertices+closedEdges-edges+faceEuler,
            supports=support,cylinders=cylinders,planes=planes,cones=cones,features=features,equations=equations,
            diagnostic_volume_mm3=Packet.V(body.GetMassProperties(1))[3]*1e9};
    }
    public static void Finish(ModelDoc2 doc,string name,Dictionary<string,object> tests,object specification) {
        tests["restored"]=State(doc);string file=NativeCommon.Save(doc,name+".sldprt");
        NativeCommon.App.CloseDoc(doc.GetTitle());int error=0,warning=0;
        doc=(ModelDoc2)NativeCommon.App.OpenDoc6(file,1,1,"",ref error,ref warning);
        NativeCommon.Need(doc!=null,"Native reopen failed: "+error);Console.WriteLine("Force rebuild after native reopen");
        doc.GetEquationMgr().EvaluateAll();doc.ForceRebuild3(false);
        var final=State(doc);var dependencies=(object[])doc.GetDependencies2(false,false,false);
        NativeCommon.Need(dependencies==null || dependencies.Length==0,"Native part has external file dependencies");
        NativeCommon.App.CloseDoc(doc.GetTitle());
        Packet.Write(Path.Combine(NativeCommon.Evidence,name+".native.json"),new{schema="solidworks-native-evidence-v1",
            solidworks_revision=NativeCommon.App.RevisionNumber(),
            external_file_dependencies=dependencies??new object[0],
            file=Path.GetFileName(file),file_sha256=Packet.Sha(file),native_reopen=true,tests=tests,final=final,specification=specification,
            implementation_source_bindings=NativeCommon.SourceBindings,design_source_bindings=NativeCommon.Input["source_bindings"]});
        Console.WriteLine("Native part saved and reopened: "+name);
    }
}
