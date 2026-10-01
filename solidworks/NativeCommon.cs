using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public abstract class NativeCommon {
    public static SldWorks App;
    public static string Root, Output, Evidence;
    public static Dictionary<string,object> Input;
    public static object SourceBindings;
    static readonly Dictionary<string,Body2> References = new Dictionary<string,Body2>();
    public static void Need(bool value,string message) { Packet.Need(value,message); }
    public static string Number(double value) { return value.ToString("R",CultureInfo.InvariantCulture); }
    public static string Quote(string value) { return "\""+value+"\""; }
    public static void Equation(ModelDoc2 doc,string expression) {
        Need(doc.GetEquationMgr().Add2(-1,expression,false)>=0,"Equation rejected: "+expression);
    }
    public static void Global(ModelDoc2 doc,string name,double value,string units="mm") {
        Equation(doc,Quote(name)+"="+Number(value)+units);
    }
    public static void Link(ModelDoc2 doc,string dimension,string expression) {
        Equation(doc,Quote(dimension)+"="+expression);
    }
    public static Feature Plane(ModelDoc2 doc,int index=0) {
        int found=0;
        for(var f=(Feature)doc.FirstFeature();f!=null;f=(Feature)f.GetNextFeature())
            if(f.GetTypeName2()=="RefPlane" && found++==index)return f;
        throw new Exception("Reference plane missing");
    }
    public static ModelDoc2 NewPart() {
        var doc=(ModelDoc2)App.NewDocument(@"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot",0,0,0);
        Need(doc!=null,"Cannot create native part");
        Plane(doc,0).Name="XY";Plane(doc,1).Name="XZ";Plane(doc,2).Name="YZ";
        doc.GetEquationMgr().AngularEquationUnits=(int)swAngularEquationUnits_e.swAngularEquationUnitsDegrees;
        doc.FeatureManager.EnableFeatureTree=false;doc.FeatureManager.EnableFeatureTreeWindow=false;
        var view=(ModelView)doc.ActiveView;if(view!=null)view.EnableGraphicsUpdate=false;
        return doc;
    }
    public static void Activate(ModelDoc2 doc) {
        int error=0;Need(App.ActivateDoc3(doc.GetTitle(),false,0,ref error)!=null,"Cannot activate owned part: "+error);
    }
    public static Body2 Reference(Dictionary<string,object> definition) {
        string path=(string)definition["file"];
        Need(Packet.Sha(path)==(string)definition["sha256"],"Construction reference hash mismatch: "+path);
        if(!References.ContainsKey(path)) {
            int error=0;var source=(ModelDoc2)App.LoadFile4(path,"r",null,ref error);
            Need(source!=null,"Reference import failed: "+error);
            var bodies=(object[])((PartDoc)source).GetBodies2(0,false);
            Need(bodies!=null && bodies.Length==1,"Reference must contain one solid");
            References[path]=(Body2)((Body2)bodies[0]).Copy();App.CloseDoc(source.GetTitle());
        }
        return (Body2)References[path].Copy();
    }
    public static Body2[] Bodies(ModelDoc2 doc) {
        var bodies=(object[])((PartDoc)doc).GetBodies2(0,false);
        return bodies==null?new Body2[0]:bodies.Cast<Body2>().ToArray();
    }
    public static Body2 OnlyBody(ModelDoc2 doc) {
        var bodies=Bodies(doc);Need(bodies.Length==1,"Expected one native solid, found "+bodies.Length);return bodies[0];
    }
    public static double[] ExactBounds(Body2 body) {
        var bounds=new double[6];
        for(int axis=0;axis<3;axis++)for(int sign=-1;sign<=1;sign+=2) {
            double x,y,z;var direction=new double[3];direction[axis]=sign;
            Need(body.GetExtremePoint(direction[0],direction[1],direction[2],out x,out y,out z),"Native extreme-point query failed");
            bounds[axis+(sign>0?3:0)]=new[]{x,y,z}[axis]*1000;
        }
        return bounds;
    }
    public static Body2 InsertReference(ModelDoc2 doc,Dictionary<string,object> definition,string name) {
        var body=Reference(definition);Activate(doc);
        var existing=new HashSet<string>(Bodies(doc).Select(b=>b.Name));
        var feature=(Feature)((PartDoc)doc).CreateFeatureFromBody3(body,false,1);
        Need(feature!=null,"Cannot insert exact reference: "+name);feature.Name=name;
        var result=Bodies(doc).Single(b=>!existing.Contains(b.Name));result.Name=name+"_Body";
        return result;
    }
    public static Dictionary<string,double> Dimensions(Feature feature) {
        var result=new Dictionary<string,double>();
        for(var display=(DisplayDimension)feature.GetFirstDisplayDimension();display!=null;
            display=(DisplayDimension)feature.GetNextDisplayDimension(display)) {
            var dimension=display.GetDimension2(0);
            string name=String.Join("@",dimension.FullName.Split('@').Take(2));
            result[name]=dimension.SystemValue;
        }
        return result;
    }
    public static string Dimension(Feature feature,double expected) {
        var candidates=Dimensions(feature).Where(x=>Math.Abs(x.Value-expected)<1e-9).Select(x=>x.Key).ToArray();
        Need(candidates.Length==1,"Dimension is not unique: "+feature.Name+", expected "+expected+", "+
             String.Join("; ",Dimensions(feature).Select(x=>x.Key+"="+x.Value)));
        return candidates[0];
    }
    public static Feature GrowPrism(ModelDoc2 doc,Body2 body,double height,string name,string expression) {
        double top=Packet.V(body.GetBodyBox())[5];Face2 cap=null;
        foreach(Face2 face in (object[])body.GetFaces()) {
            var surface=(Surface)face.GetSurface();
            if(surface.IsPlane()) {var p=Packet.V(surface.PlaneParams);
                if(Math.Abs(Math.Abs(p[2])-1)<1e-10 && Math.Abs(p[5]-top)<1e-9)cap=face;}
        }
        Need(cap!=null && height/1000>top,"Prism height must exceed its reference depth");
        doc.ClearSelection2(true);var select=((SelectionMgr)doc.SelectionManager).CreateSelectData();select.Mark=1;
        Need(((Entity)cap).Select4(false,select) && Plane(doc).Select2(true,2),"Prism cap selection failed");
        double distance=height/1000-top;
        var feature=doc.FeatureManager.InsertMoveFace3((int)swMoveFaceType_e.swMoveFaceTypeTranslate,false,0,distance,null,null,0,0);
        Need(feature!=null,"Prismatic height feature failed");feature.Name=name;
        Link(doc,Dimension(feature,distance),expression+"-"+Number(top*1000)+"mm");return feature;
    }
    public static Feature MoveBody(ModelDoc2 doc,Body2 body,double x,double y,double z,string name) {
        doc.ClearSelection2(true);var selection=((SelectionMgr)doc.SelectionManager).CreateSelectData();selection.Mark=1;
        Need(body.Select2(false,selection),"Body placement selection failed");
        var feature=doc.FeatureManager.InsertMoveCopyBody2(x/1000,y/1000,z/1000,0,0,0,0,0,0,0,false,0);
        Need(feature!=null,"Body placement feature failed: "+name);feature.Name=name;return feature;
    }
    public static Feature Subtract(ModelDoc2 doc,Body2 main,Body2 tool,string name) {
        doc.ClearSelection2(true);var feature=doc.FeatureManager.InsertCombineFeature(15902,main,new Body2[]{tool});
        Need(feature!=null,"Native cut failed: "+name);feature.Name=name;return feature;
    }
    public static Feature BeginSketch(ModelDoc2 doc,string name,Feature plane=null) {
        doc.ClearSelection2(true);Need((plane??Plane(doc)).Select2(false,0),"Sketch plane selection failed");
        doc.SketchManager.InsertSketch(false);Need(doc.SketchManager.ActiveSketch!=null,"Cannot enter sketch");
        var feature=doc.IFeatureByPositionReverse(0);feature.Name=name;
        doc.SketchManager.AutoSolve=false;doc.SketchManager.AddToDB=true;doc.SketchManager.DisplayWhenAdded=false;return feature;
    }
    public static Feature EndSketch(ModelDoc2 doc) {
        var feature=doc.IFeatureByPositionReverse(0);doc.SketchManager.AddToDB=false;doc.SketchManager.AutoSolve=true;doc.SketchManager.DisplayWhenAdded=true;
        doc.SketchManager.InsertSketch(false);doc.ClearSelection2(true);Need(feature.Select2(false,0),"Sketch selection failed");return feature;
    }
    public static double[] InSketch(ModelDoc2 doc,double[] worldMm) {
        var utility=(MathUtility)App.GetMathUtility();var point=(MathPoint)utility.CreatePoint(worldMm.Select(x=>x/1000).ToArray());
        return Packet.V(((MathPoint)point.MultiplyTransform(doc.SketchManager.ActiveSketch.ModelToSketchTransform)).ArrayData);
    }
    public static string Diameter(ModelDoc2 doc,SketchSegment circle,double[] center,double radius) {
        doc.ClearSelection2(true);Need(circle.Select4(false,null),"Diameter selection");
        var display=(DisplayDimension)doc.AddDiameterDimension2(center[0]+radius*1.4,center[1]+radius,0);
        Need(display!=null,"Diameter dimension failed");return String.Join("@",display.GetDimension2(0).FullName.Split('@').Take(2));
    }
    public static string Circle(ModelDoc2 doc,string name,double radius,Feature plane=null,double[] worldMm=null) {
        BeginSketch(doc,name,plane);var p=worldMm==null?new double[]{0,0,0}:InSketch(doc,worldMm);
        var segment=doc.SketchManager.CreateCircleByRadius(p[0],p[1],0,radius/1000);Need(segment!=null,"Circle creation failed");
        var center=((SketchArc)segment).IGetCenterPoint2();center.Select4(false,null);doc.SketchAddConstraints("sgFIXED");
        string dimension=Diameter(doc,segment,p,radius/1000);EndSketch(doc);return dimension;
    }
    public static void PointRelation(ModelDoc2 doc,SketchPoint first,SketchPoint second) {
        doc.ClearSelection2(true);Need(first.Select4(false,null) && second.Select4(true,null),"Point relation selection");
        doc.SketchAddConstraints("sgCOINCIDENT");
    }
    public static string[] PositionPoint(ModelDoc2 doc,SketchPoint target,double[] p) {
        var dimensions=new string[2];SketchPoint last=null;
        for(int axis=0;axis<2;axis++) {
            if(Math.Abs(p[axis])<1e-10)continue;
            double x0=axis==0?0:p[0],y0=0,x1=p[0],y1=axis==0?0:p[1];
            var segment=doc.SketchManager.CreateLine(x0,y0,0,x1,y1,0);Need(segment!=null,"Position construction line");
            segment.ConstructionGeometry=true;var line=(SketchLine)segment;
            var start=line.IGetStartPoint2();var end=line.IGetEndPoint2();
            if(last==null){doc.ClearSelection2(true);start.Select4(false,null);doc.SketchAddConstraints("sgFIXED");}
            else PointRelation(doc,last,start);
            doc.ClearSelection2(true);segment.Select4(false,null);doc.SketchAddConstraints(axis==0?"sgHORIZONTAL2D":"sgVERTICAL2D");
            doc.ClearSelection2(true);segment.Select4(false,null);
            var display=(DisplayDimension)doc.AddDimension2((x0+x1)/2+.003,(y0+y1)/2+.003,0);
            Need(display!=null,"Position dimension");dimensions[axis]=String.Join("@",display.GetDimension2(0).FullName.Split('@').Take(2));last=end;
        }
        if(last==null){target.Select4(false,null);doc.SketchAddConstraints("sgFIXED");}
        else PointRelation(doc,last,target);
        return dimensions;
    }
    public static Feature ThreePointPlane(ModelDoc2 doc,string name,double[] origin,double[] u,double[] v) {
        doc.ClearSelection2(true);doc.SketchManager.Insert3DSketch(false);var sketch=doc.IFeatureByPositionReverse(0);sketch.Name=name+"Points";
        var points=new[]{doc.SketchManager.CreatePoint(origin[0]/1000,origin[1]/1000,origin[2]/1000),
            doc.SketchManager.CreatePoint((origin[0]+u[0])/1000,(origin[1]+u[1])/1000,(origin[2]+u[2])/1000),
            doc.SketchManager.CreatePoint((origin[0]+v[0])/1000,(origin[1]+v[1])/1000,(origin[2]+v[2])/1000)};
        doc.ClearSelection2(true);foreach(var point in points)Need(point.Select4(true,null),"Plane datum point");
        doc.SketchAddConstraints("sgFIXED");doc.SketchManager.Insert3DSketch(false);doc.ClearSelection2(true);
        for(int i=0;i<3;i++)Need(points[i].Select2(i>0,i),"Plane point selection");
        Need(doc.FeatureManager.InsertRefPlane(4,0,4,0,4,0)!=null,"Three-point plane construction failed");
        var plane=doc.IFeatureByPositionReverse(0);plane.Name=name;
        doc.ClearSelection2(true);sketch.Select2(false,0);doc.BlankSketch();return plane;
    }
    public static Feature LinearPattern(ModelDoc2 doc,Feature seed,Feature axis,int count,double spacing,string name,bool geometry=true,int coordinate=2) {
        return LinearPattern(doc,new[]{seed},axis,count,spacing,name,geometry,coordinate);
    }
    public static Feature LinearPattern(ModelDoc2 doc,Feature[] seeds,Feature axis,int count,double spacing,string name,bool geometry=true,int coordinate=2) {
        var parameters=Packet.V(((RefAxis)axis.GetSpecificFeature2()).GetRefAxisParams());
        bool flip=parameters[coordinate+3]-parameters[coordinate]<0;
        doc.ClearSelection2(true);bool append=false;
        foreach(var seed in seeds){Need(seed.Select2(append,4),"Linear pattern seed");append=true;}
        Need(axis.Select2(true,1),"Linear pattern axis");
        var pattern=doc.FeatureManager.FeatureLinearPattern5(count,spacing/1000,1,.001,flip,false,"","",geometry,false,
            false,false,false,false,false,false,false,false,0,0,false,true);
        Need(pattern!=null,"Linear pattern failed: "+name);pattern.Name=name;return pattern;
    }
    public static Feature CircularPattern(ModelDoc2 doc,Feature[] seeds,Feature axis,int count,string name) {
        doc.ClearSelection2(true);bool append=false;
        foreach(var seed in seeds){Need(seed.Select2(append,4),"Circular pattern seed");append=true;}
        Need(axis.Select2(true,1),"Circular pattern axis");
        var pattern=doc.FeatureManager.FeatureCircularPattern5(count,2*Math.PI,false,"",true,true,false,false,false,false,0,0,"",true);
        Need(pattern!=null,"Circular pattern failed: "+name);pattern.Name=name;return pattern;
    }
    public static Feature Extrude(ModelDoc2 doc,string name,double depth,bool draft=false,double angle=0,double offset=0) {
        var f=doc.FeatureManager.FeatureExtrusion3(true,false,false,0,0,depth/1000,0,draft,false,true,false,angle,0,
            false,false,false,false,true,true,true,offset==0?0:3,offset/1000,false);
        Need(f!=null,"Extrusion failed: "+name);f.Name=name;return f;
    }
    public static Feature Cut(ModelDoc2 doc,string name,double depth,bool draft=false,double angle=0,double offset=0,bool both=false) {
        var f=doc.FeatureManager.FeatureCut4(!both,false,true,0,0,depth/1000,both?depth/1000:0,draft,false,true,false,angle,0,
            false,false,false,false,false,true,true,false,false,false,offset==0?0:3,offset/1000,false,false);
        Need(f!=null,"Extruded cut failed: "+name);f.Name=name;return f;
    }
    public static Feature Axis(ModelDoc2 doc,Feature first,Feature second,string name) {
        doc.ClearSelection2(true);Need(first.Select2(false,0) && second.Select2(true,0),"Axis references");
        Need(doc.InsertAxis2(true),"Axis construction failed");var axis=doc.IFeatureByPositionReverse(0);axis.Name=name;return axis;
    }
    public static Feature OffsetPlane(ModelDoc2 doc,Feature source,double offset,string name) {
        doc.ClearSelection2(true);Need(source.Select2(false,0),"Offset plane reference");
        Need(doc.FeatureManager.InsertRefPlane(8,offset/1000,0,0,0,0)!=null,"Offset plane failed");
        var plane=doc.IFeatureByPositionReverse(0);plane.Name=name;return plane;
    }
    public static Feature AnglePlane(ModelDoc2 doc,Feature source,Feature axis,double radians,string name,bool reverse=false) {
        doc.ClearSelection2(true);Need(source.Select2(false,0) && axis.Select2(true,1),"Angular plane references");
        Need(doc.FeatureManager.InsertRefPlane(16|(reverse?256:0),radians,4,0,0,0)!=null,"Angular plane failed");
        var plane=doc.IFeatureByPositionReverse(0);plane.Name=name;return plane;
    }
    public static void Rebuild(ModelDoc2 doc) {
        var timer=System.Diagnostics.Stopwatch.StartNew();Console.WriteLine("Rebuilding changed native features");
        doc.GetEquationMgr().EvaluateAll();doc.ForceRebuild3(false);Console.WriteLine("Rebuild seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
    }
    public static void AssignGlobal(ModelDoc2 doc,string name,double value,string units="mm") {
        Activate(doc);
        var manager=doc.GetEquationMgr();int index=-1;
        for(int i=0;i<manager.GetCount();i++)if(manager.Equation[i].TrimStart().StartsWith(Quote(name)+" ") ||
            manager.Equation[i].TrimStart().StartsWith(Quote(name)+"=")){index=i;break;}
        Need(index>=0,"Global parameter missing: "+name);string expression=Quote(name)+"="+Number(value)+units;
        manager.Equation[index]=expression;
        Need(manager.Equation[index].Replace(" ","")==expression,"Native parameter assignment was not applied: "+name);
    }
    public static void SetGlobal(ModelDoc2 doc,string name,double value,string units="mm") {
        AssignGlobal(doc,name,value,units);Rebuild(doc);
    }
    static void InspectionView(ModelDoc2 doc,bool rear=false) {
        double r=1/Math.Sqrt(2),q=1/Math.Sqrt(6),n=1/Math.Sqrt(3);
        var data=rear?new double[]{1,0,0,0,0,-1,0,1,0,0,0,0,1,0,0,0}:
            new double[]{r,-q,n,r,q,-n,0,2*q,n,0,0,0,1,0,0,0};
        var view=(ModelView)doc.ActiveView;
        if(view!=null){view.EnableGraphicsUpdate=true;view.Orientation3=(MathTransform)((MathUtility)App.GetMathUtility()).CreateTransform(data);}
        doc.ViewZoomtofit2();doc.GraphicsRedraw2();
        bool command=App.CommandInProgress;App.CommandInProgress=false;
        try {
            System.Windows.Forms.Application.DoEvents();doc.WindowRedraw();
            if(view!=null)view.GraphicsRedraw(null);
            System.Windows.Forms.Application.DoEvents();
        } finally {App.CommandInProgress=command;}
    }
    public static void Preview(ModelDoc2 doc,string name) {
        string images=Path.Combine(Evidence,"images");Directory.CreateDirectory(images);int errors=0,warnings=0;
        doc.ViewDisplayShaded();
        InspectionView(doc);
        Need(doc.Extension.SaveAs(Path.Combine(images,Path.GetFileNameWithoutExtension(name)+".png"),0,1,null,ref errors,ref warnings),"Native preview export failed: "+errors);
        if(name.Contains("_housing.")) {
            InspectionView(doc,true);
            doc.ViewDisplayHiddenremoved();((ModelView)doc.ActiveView).Scale2*=.6;doc.WindowRedraw();
            ((ModelView)doc.ActiveView).GraphicsRedraw(null);System.Windows.Forms.Application.DoEvents();
            Need(doc.Extension.SaveAs(Path.Combine(images,Path.GetFileNameWithoutExtension(name)+"_rear.png"),0,1,null,ref errors,ref warnings),"Native rear preview export failed: "+errors);
            doc.ViewDisplayShaded();InspectionView(doc);
        }
    }
    public static string Save(ModelDoc2 doc,string name) {
        doc.FeatureManager.EnableFeatureTree=true;doc.FeatureManager.EnableFeatureTreeWindow=true;
        var view=(ModelView)doc.ActiveView;if(view!=null)view.EnableGraphicsUpdate=true;
        foreach(var setting in new[]{swUserPreferenceToggle_e.swDisplayPlanes,swUserPreferenceToggle_e.swDisplayAxes,
            swUserPreferenceToggle_e.swDisplayTemporaryAxes,swUserPreferenceToggle_e.swDisplaySketches,
            swUserPreferenceToggle_e.swDisplayOrigins,
            swUserPreferenceToggle_e.swDisplayFeatureDimensions,swUserPreferenceToggle_e.swDisplayReferenceDimensions})
            doc.SetUserPreferenceToggle((int)setting,false);
        string path=Path.Combine(Output,name);doc.ClearSelection2(true);doc.ShowNamedView2("",(int)swStandardViews_e.swIsometricView);
        if(doc.GetType()==1)doc.MaterialPropertyValues=new double[]{.68,.71,.74,.25,.75,.25,.3,0,0};
        doc.ViewDisplayShaded();
        InspectionView(doc);int errors=0,warnings=0;
        Need(doc.Extension.SaveAs(path,0,1,null,ref errors,ref warnings),"Native save failed: "+errors);
        Preview(doc,name);
        return path;
    }
}
