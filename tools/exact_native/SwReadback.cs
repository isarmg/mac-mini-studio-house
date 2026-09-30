using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public static class SwReadback {
    public static void DebugCurves(Modeler modeler,Body2 body) {
        var edges=(object[])body.GetEdges();
        for(int i=0;i<Math.Min(24,edges.Length);i++) {
            var e=(Edge)edges[i];var values=new List<string>();
            foreach(double tolerance in new[]{.01,1e-4,1e-6,1e-8,1e-10,1e-12}) {
                modeler.SetToleranceValue(0,tolerance);modeler.SetToleranceValue(1,tolerance);
                var c=(Curve)e.GetCurve();
                if(c.IsLine() || c.IsCircle()){values.Add(tolerance+":analytic("+c.Identity()+")");SwSession.Release(c);continue;}
                double start=0,end=0;bool closed=false,periodic=false;c.GetEndParams(out start,out end,out closed,out periodic);var d=c.GetBCurveParams5(false,false,false,closed);
                string detail=tolerance+":type"+c.Identity()+"/trimmed"+c.IsTrimmedCurve()+"/degree"+(d==null?-2:d.Order-1)+"/cp"+(d==null?-1:d.ControlPointsCount);
                if(c.IsTrimmedCurve()){var bc=c.GetBaseCurve();var bd=bc.GetBCurveParams5(false,false,false,false);detail+="/base"+bc.Identity()+"/degree"+(bd==null?-2:bd.Order-1)+"/cp"+(bd==null?-1:bd.ControlPointsCount);SwSession.Release(bd);SwSession.Release(bc);}
                values.Add(detail);SwSession.Release(d);SwSession.Release(c);
            }
            Console.WriteLine("Curve diagnostic "+i+": "+String.Join("; ",values));
        }
    }
    static long Identity(object value) {var p=Marshal.GetIUnknownForObject(value);try{return p.ToInt64();}finally{Marshal.Release(p);}}
    static double[] Mm(object v) {return Packet.V(v).Select(x=>x*1000).ToArray();}
    public static object SurfaceData(Surface surface,double[] faceBounds) {
        if(surface.IsPlane())return new {type="Plane",parameters=surface.PlaneParams,parameter_frame=new[]{surface.Evaluate(0,0,0,0),surface.Evaluate(1,0,0,0),surface.Evaluate(0,1,0,0)}};
        if(surface.IsCylinder())return new {type="CylindricalSurface",parameters=surface.CylinderParams};
        if(surface.IsCone()) {
            var samples=new List<object>();
            foreach(double fu in new[]{.13,.47,.83})foreach(double fv in new[]{.17,.53,.79}){
                double u=faceBounds[0]+fu*(faceBounds[1]-faceBounds[0]),v=faceBounds[2]+fv*(faceBounds[3]-faceBounds[2]);
                samples.Add(new{uv=new[]{u,v},point=Packet.V(surface.Evaluate(u,v,0,0)).Take(3).ToArray()});
            }
            return new {type="ConicalSurface",parameters=surface.ConeParams2,samples=samples};
        }
        if(surface.Identity()==4009) {
            var profile=(Curve)surface.GetProfileCurve();var evidence=new List<object>();
            try {
                foreach(double fu in new[]{.13,.47,.83})foreach(double fv in new[]{.17,.53,.79}) {double u=faceBounds[0]+fu*(faceBounds[1]-faceBounds[0]),v=faceBounds[2]+fv*(faceBounds[3]-faceBounds[2]);evidence.Add(new{uv=new[]{u,v},point=Packet.V(surface.Evaluate(u,v,0,0)).Take(3).ToArray()});}
                return new{type="NativeExtrusion",profile=CurveData(profile),direction=surface.GetExtrusionsurfParams(),uv_bounds=faceBounds,samples=evidence};
            }finally{SwSession.Release(profile);}
        }
        Packet.Need(surface.IsParametric(),"Unexpected native support representation: "+surface.Identity());
        var parameterization=surface.Parameterization2();bool sense=false;
        var b=surface.GetBSurfParams3(false,false,parameterization,1e-12,out sense);
        Packet.Need(b!=null,"Native B-spline parameter extraction failed");
        try {
            int rowCount=b.ControlPointRowCount,columnCount=b.ControlPointColumnCount;
            double u0=parameterization.UMin,u1=parameterization.UMax,v0=parameterization.VMin,v1=parameterization.VMax;
            var poles=new List<object>();
            for(int r=1;r<=rowCount;r++) {var row=new List<object>();for(int c=1;c<=columnCount;c++)row.Add(b.GetControlPoints(r,c));poles.Add(row);}
            var samples=new List<object>();
            foreach(double fu in new[]{.13,.47,.83})foreach(double fv in new[]{.17,.53,.79}) {
                double u=u0+fu*(u1-u0),v=v0+fv*(v1-v0);
                samples.Add(new {uv=new[]{u,v},point=Packet.V(surface.Evaluate(u,v,0,0)).Take(3).ToArray()});
            }
            return new {type="BSplineSurface",u_degree=b.UOrder-1,v_degree=b.VOrder-1,rows=rowCount,columns=columnCount,dimension=b.ControlPointDimension,
                u_periodic=b.UPeriodicity,v_periodic=b.VPeriodicity,u_knots=b.UKnots,v_knots=b.VKnots,poles=poles,sense=sense,
                uv_bounds=new[]{u0,u1,v0,v1},samples=samples};
        }finally {SwSession.Release(b);SwSession.Release(parameterization);}
    }
    static object CurveData(Curve curve) {
        // GetBCurveParams5 approximates a trimmed wrapper. Read its exact
        // underlying curve instead; retain the edge interval separately.
        if(curve.IsTrimmedCurve()) {
            var basis=curve.GetBaseCurve();
            Packet.Need(basis!=null,"Trimmed curve has no underlying curve");
            try {return CurveData(basis);} finally {SwSession.Release(basis);}
        }
        int identity=curve.Identity();
        // Analytic intersection/parameter curves may have a wrapper identity.
        // The analytic predicates also recognize these exact native supports.
        if(curve.IsLine())return new {type="Line",native_identity=identity,parameters=curve.LineParams};
        if(curve.IsCircle())return new {type="Circle",native_identity=identity,parameters=curve.CircleParams};
        Packet.Need(curve.IsBcurve(),"Unexpected native edge representation: "+curve.Identity());
        double first=0,last=0;bool closed=false,periodic=false;curve.GetEndParams(out first,out last,out closed,out periodic);
                var d=curve.GetBCurveParams5(false,false,true,closed);Packet.Need(d!=null,"Native curve parameter extraction failed");
        try {object controls=null,knots=null;Packet.Need(d.GetControlPoints(out controls) && d.GetKnotPoints(out knots),"Native curve data unavailable: identity "+identity+", degree "+(d.Order-1)+", controls "+d.ControlPointsCount+", closed "+closed+", periodic "+periodic);
            var ks=Packet.V(knots);var samples=new List<object>();foreach(double f in new[]{.13,.47,.83}){double t=ks[0]+f*(ks[ks.Length-1]-ks[0]);samples.Add(new{u=t,point=Packet.V(curve.Evaluate2(t,0)).Take(3).ToArray()});}
            return new {type="BSplineCurve",native_identity=curve.Identity(),degree=d.Order-1,dimension=d.Dimension,periodic=d.Periodic,control_count=d.ControlPointsCount,coordinates=controls,knots=knots,samples=samples};
        }finally {SwSession.Release(d);}
    }
    public static object BodyData(Body2 body) {
        var faces=(object[])body.GetFaces();var edges=(object[])body.GetEdges();var vertices=(object[])body.GetVertices();var edgeIndex=new Dictionary<long,int>();
        var edgeReports=new List<object>();bool probedUnavailableCurve=false;
        for(int i=0;i<edges.Length;i++) {
            if(i%500==0)Console.WriteLine("Native exact edge data: "+i+"/"+edges.Length);
            var e=(Edge)edges[i];edgeIndex[Identity(e)]=i;var c=(Curve)e.GetCurve();var p=e.GetCurveParams3();
            try {
                double u0=p.UMinValue,u1=p.UMaxValue;
                var samples=new List<object>();
                foreach(double f in new[]{.13,.47,.83}) {double u=u0+f*(u1-u0);samples.Add(new {u=u,point=Packet.V(c.Evaluate2(u,0)).Take(3).ToArray()});}
                var edgeEvaluations=new List<object>();
                if(c.IsCircle() || c.IsLine())foreach(double f in new[]{0.0,.13,.47,.83,1.0}) {
                    double u=u0+f*(u1-u0);var evaluated=Packet.V(e.Evaluate2(u,0));
                    Packet.Need(evaluated.Length==4 && (BitConverter.DoubleToInt64Bits(evaluated[3]) & 0xffffffffL)==1,"Native edge evaluation failed");
                    edgeEvaluations.Add(new{u=u,point=evaluated.Take(3).ToArray()});
                }
                double tolerance=0;bool tolerant=e.IsTolerant(out tolerance);
                object definition;
                try {definition=CurveData(c);}
                catch(Exception unavailable) {
                    Console.WriteLine("Unavailable native edge "+i+": "+unavailable.Message);
                    if(!probedUnavailableCurve) {
                        probedUnavailableCurve=true;
                        double first=0,last=0;bool closed=false,periodic=false;c.GetEndParams(out first,out last,out closed,out periodic);
                        var probe=c.GetBCurveParams5(false,false,true,closed);
                        Console.WriteLine("Original wrapper "+c.Identity()+", trimmed="+c.IsTrimmedCurve()+", domain="+first+","+last+", degree="+(probe==null?-2:probe.Order-1)+", controls="+(probe==null?-1:probe.ControlPointsCount));
                        SwSession.Release(probe);
                    }
                    // Preserve the rest of the native evidence for diagnosis.
                    // The strict verifier rejects this unsupported definition.
                    definition=new {type="UnavailableNativeCurve",native_identity=c.Identity(),error=unavailable.Message};
                }
                edgeReports.Add(new {id=i,curve=definition,range=new[]{u0,u1},start=p.StartPoint,end=p.EndPoint,sense=p.Sense,samples=samples,edge_evaluations=edgeEvaluations,tolerant=tolerant,tolerance_m=tolerance});
            }
            finally {SwSession.Release(p);SwSession.Release(c);}
        }
        var faceReports=new List<object>();
        for(int i=0;i<faces.Length;i++) {
            if(i%500==0)Console.WriteLine("Native exact surface data: "+i+"/"+faces.Length);
            var f=(Face2)faces[i];var surface=(Surface)f.GetSurface();var loopReports=new List<object>();var loops=(object[])f.GetLoops();
            try {
                foreach(Loop2 loop in loops) {
                    var entries=(object[])loop.GetCoEdges();var er=new List<object>();
                    foreach(CoEdge co in entries) {var edge=(Edge)co.GetEdge();er.Add(new {edge_id=edgeIndex[Identity(edge)],sense=co.GetSense()});SwSession.Release(co);}
                    loopReports.Add(new {outer=loop.IsOuter(),edges=er});SwSession.Release(loop);
                }
                var bounds=Packet.V(f.GetUVBounds());faceReports.Add(new {id=f.GetFaceId(),surface=SurfaceData(surface,bounds),reversed=!f.FaceInSurfaceSense(),loops=loopReports,area_m2=f.GetArea(),uv_bounds=bounds});
            }finally {SwSession.Release(surface);}
        }
        var vertexReports=new List<object>();foreach(Vertex v in vertices){vertexReports.Add(v.GetPoint());SwSession.Release(v);}
        foreach(var f in faces)SwSession.Release(f);foreach(var e in edges)SwSession.Release(e);
        return new {units="m",faces=faceReports,edges=edgeReports,vertices=vertexReports,counts=new{faces=faces.Length,edges=edges.Length,vertices=vertices.Length},volume_m3=Packet.V(body.GetMassProperties(1))[3]};
    }
}
