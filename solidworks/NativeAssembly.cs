using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public sealed class NativeAssembly : NativeCommon {
    static MathTransform Translation(double z) {
        return (MathTransform)((MathUtility)App.GetMathUtility()).CreateTransform(new double[]{1,0,0,0,1,0,0,0,1,0,0,z/1000,1,0,0,0});
    }
    static void Mate(ModelDoc2 doc,Component2 first,string firstPlane,Component2 second,string secondPlane,string name) {
        doc.ClearSelection2(true);
        string assembly=Path.GetFileNameWithoutExtension(doc.GetTitle());
        Need(doc.Extension.SelectByID2(firstPlane+"@"+first.Name2+"@"+assembly,"PLANE",0,0,0,false,1,null,0),"First assembly mate reference");
        Need(doc.Extension.SelectByID2(secondPlane+"@"+second.Name2+"@"+assembly,"PLANE",0,0,0,true,1,null,0),"Second assembly mate reference");
        int error=0;
        var mate=((AssemblyDoc)doc).AddMate5((int)swMateType_e.swMateCOINCIDENT,(int)swMateAlign_e.swMateAlignALIGNED,
            false,0,0,0,0,0,0,0,0,false,false,0,out error);
        Need(mate!=null && error==(int)swAddMateError_e.swAddMateError_NoError,"Native assembly mate failed: "+error);
        ((Feature)mate).Name=name;doc.ClearSelection2(true);
    }
    static object State(ModelDoc2 doc) {
        var components=((object[])((AssemblyDoc)doc).GetComponents(true)).Cast<Component2>().ToArray();
        Need(components.Length==2,"Assembly must contain housing and base");
        var records=new List<object>();var overall=new[]{Double.PositiveInfinity,Double.PositiveInfinity,Double.PositiveInfinity,
            Double.NegativeInfinity,Double.NegativeInfinity,Double.NegativeInfinity};
        foreach(var component in components) {
            var model=(ModelDoc2)component.GetModelDoc2();Need(model!=null,"Unresolved native assembly component");
            Need(String.Equals(Path.GetFullPath(component.GetPathName()),Path.Combine(Output,Path.GetFileName(component.GetPathName())),StringComparison.OrdinalIgnoreCase),
                "Assembly component is outside its delivery folder");
            var body=(Body2)OnlyBody(model).Copy();Need(body.ApplyTransform(component.Transform2),"Assembly body transform");
            var bounds=ExactBounds(body);
            for(int i=0;i<3;i++){overall[i]=Math.Min(overall[i],bounds[i]);overall[i+3]=Math.Max(overall[i+3],bounds[i+3]);}
            records.Add(new{name=component.Name2,file=Path.GetFileName(component.GetPathName()),
                fixed_component=component.IsFixed(),transform=component.Transform2.ArrayData,bounds_mm=bounds,
                body_faults=body.Check3==null?0:body.Check3.Count});
        }
        var mates=new List<object>();
        for(var f=(Feature)doc.FirstFeature();f!=null;f=(Feature)f.GetNextFeature())if(f.GetTypeName2()=="MateGroup") {
            for(var sub=(Feature)f.GetFirstSubFeature();sub!=null;sub=(Feature)sub.GetNextSubFeature()) {
                bool warning=false;int error=sub.GetErrorCode2(out warning);
                Need(error==0,"Assembly mate error: "+sub.Name+" ("+error+")");
                mates.Add(new{name=sub.Name,type=sub.GetTypeName2(),error=error});
            }
        }
        Need(mates.Count==3,"Three native assembly plane mates are required");
        return new{component_count=components.Length,components=records,mates=mates,bounds_mm=overall};
    }
    public static void Build(string model,int wall) {
        string name=model+"_enclosure_"+wall+"mm_assembly";Console.WriteLine("Building native assembly: "+name);
        string stem=model+"_enclosure_"+wall+"mm_";
        string baseFile=Path.Combine(Output,stem+"base.sldprt"),housingFile=Path.Combine(Output,stem+"housing.sldprt");
        Need(File.Exists(baseFile) && File.Exists(housingFile),"Assembly native parts are missing");
        var before=new Dictionary<string,string>{{baseFile,Packet.Sha(baseFile)},{housingFile,Packet.Sha(housingFile)}};
        int error=0,warning=0;
        var baseDoc=(ModelDoc2)App.OpenDoc6(baseFile,1,1,"",ref error,ref warning);Need(baseDoc!=null,"Open base for assembly");
        var housingDoc=(ModelDoc2)App.OpenDoc6(housingFile,1,1,"",ref error,ref warning);Need(housingDoc!=null,"Open housing for assembly");
        var doc=(ModelDoc2)App.NewDocument(@"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_assembly.asmdot",0,0,0);
        Need(doc!=null,"Cannot create native assembly");var assembly=(AssemblyDoc)doc;
        double height=model=="mac-mini"?8:10,interfaceZ=height-1.5;
        var bottom=assembly.AddComponent5(baseFile,0,"",false,"",0,0,0);Need(bottom!=null,"Insert base component");
        bottom.Transform2=Translation(0);bottom.Select4(false,null,false);assembly.FixComponent();doc.ClearSelection2(true);
        var housing=assembly.AddComponent5(housingFile,0,"",false,"",0,0,interfaceZ/1000);Need(housing!=null,"Insert housing component");
        housing.Select4(false,null,false);assembly.UnfixComponent();doc.ClearSelection2(true);housing.Transform2=Translation(interfaceZ);
        Mate(doc,bottom,"MatingPlane",housing,"XY","BaseToHousing");
        Mate(doc,bottom,"XZ",housing,"XZ","AlignXZ");Mate(doc,bottom,"YZ",housing,"YZ","AlignYZ");
        doc.ForceRebuild3(false);var tests=new Dictionary<string,object>{{"baseline",State(doc)}};
        string file=Save(doc,name+".sldasm");
        Activate(baseDoc);SetGlobal(baseDoc,"BaseHeight",height+1);Activate(doc);doc.ForceRebuild3(false);
        tests["edited_base_height"]=State(doc);
        Activate(baseDoc);SetGlobal(baseDoc,"BaseHeight",height);Activate(doc);doc.ForceRebuild3(false);
        tests["restored"]=State(doc);App.CloseAllDocuments(true);
        doc=(ModelDoc2)App.OpenDoc6(file,2,1,"",ref error,ref warning);Need(doc!=null,"Native assembly reopen failed: "+error);
        doc.ForceRebuild3(false);var final=State(doc);App.CloseAllDocuments(true);
        var dependencies=new Dictionary<string,string>();
        foreach(var pair in before){Need(Packet.Sha(pair.Key)==pair.Value,"Assembly validation modified a delivered part");dependencies[Path.GetFileName(pair.Key)]=pair.Value;}
        Packet.Write(Path.Combine(Evidence,name+".assembly.json"),new{schema="solidworks-native-assembly-evidence-v1",file=Path.GetFileName(file),
            solidworks_revision=App.RevisionNumber(),
            file_sha256=Packet.Sha(file),native_reopen=true,tests=tests,final=final,dependencies=dependencies,
            specification=new{model=model,wall_mm=wall,assembly_height_mm=model=="mac-mini"?49.5:95},
            implementation_source_bindings=SourceBindings,design_source_bindings=Input["source_bindings"]});
        Console.WriteLine("Native assembly saved and reopened: "+name);
    }
}
