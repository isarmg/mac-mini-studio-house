using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public static class SwExact {
    public static void TransferLoaded(SldWorks app,string input,string output,string report) {
        int error=0;Console.WriteLine("Native transport import: "+input);var doc=(ModelDoc2)app.LoadFile4(input,"r",null,ref error);Packet.Need(doc!=null,"Canonical transport load failed: "+error);
        int errors=0,warnings=0;Packet.Need(doc.Extension.SaveAs(output,0,1,null,ref errors,ref warnings),"Native Parasolid save failed: "+errors);app.CloseAllDocuments(true);
        InspectLoaded(app,output,report);
        var result=Packet.Read(report);result["construction"]="canonical_exact_transport_native_parasolid_import";result["transport_format"]=Path.GetExtension(input);result["repair_or_simplify_requested"]=false;result["import_curve_tolerance_m"]=app.GetUserPreferenceDoubleValue((int)swUserPreferenceDoubleValue_e.swCustomizedImportTolerance);Packet.Write(report,result);
    }
    public static void ComposeLoaded(SldWorks app,string manifest,string output,string report) {
        var inputs=Packet.A(Packet.Read(manifest)["inputs"]);Packet.Need(inputs.Length==2,"Exactly two verified component bodies required");
        string template=@"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot";
        var target=(ModelDoc2)app.NewDocument(template,0,0,0);Packet.Need(target!=null,"Cannot create native composition part");
        var targetPart=(PartDoc)target;int error=0;
        for(int i=0;i<inputs.Length;i++) {
            var input=Packet.D(inputs[i]);string path=(string)input["path"];
            Packet.Need(Packet.Sha(path)==(string)input["sha256"],"Native component hash changed");
            var source=(ModelDoc2)app.LoadFile4(path,"r",null,ref error);Packet.Need(source!=null,"Native component load failed: "+error);
            var bodies=(object[])((PartDoc)source).GetBodies2(0,false);Packet.Need(bodies!=null && bodies.Length==1,"Expected one component solid");
            var copy=(Body2)((Body2)bodies[0]).Copy();Packet.Need(copy!=null,"Native body copy failed");
            app.ActivateDoc3(target.GetTitle(),false,0,ref error);
            var feature=(Feature)targetPart.CreateFeatureFromBody3(copy,false,1);Packet.Need(feature!=null,"Checked native body insertion failed");feature.Name=(string)input["label"];
            var actual=(object[])targetPart.GetBodies2(0,false);Packet.Need(actual.Length==i+1,"Component solids merged or disappeared");
            foreach(object body in actual)SwSession.Release(body);SwSession.Release(feature);SwSession.Release(copy);foreach(object body in bodies)SwSession.Release(body);
            app.CloseDoc(source.GetTitle());SwSession.Release(source);Console.WriteLine("Native component copied: "+(string)input["label"]);
        }
        int saveError=0,warning=0;Packet.Need(target.Extension.SaveAs(output,0,1,null,ref saveError,ref warning),"Native composition export failed: "+saveError);
        app.CloseAllDocuments(true);SwSession.Release(target);InspectLoaded(app,output,report);
        var result=Packet.Read(report);result["construction"]="verified_native_component_composition";result["component_inputs"]=inputs;result["identity_placement"]=true;result["boolean_combine_used"]=false;result["repair_or_simplify_requested"]=false;Packet.Write(report,result);
    }
    static object[] InspectionBodies(ModelDoc2 doc,out object componentEvidence) {
        componentEvidence=null;
        if(doc.GetType()==(int)swDocumentTypes_e.swDocPART)return (object[])((PartDoc)doc).GetBodies2(0,false);
        Packet.Need(doc.GetType()==(int)swDocumentTypes_e.swDocASSEMBLY,"Expected a part or assembly document for native readback");
        var assembly=(AssemblyDoc)doc;var components=(object[])assembly.GetComponents(false);
        Packet.Need(components!=null && components.Length>0,"Native assembly has no components");
        var bodies=new List<object>();var evidence=new List<object>();
        foreach(Component2 component in components) {
            try {
                var children=(object[])component.GetChildren();
                // GetComponents(false) already owns the child RCW aliases;
                // releasing them here would invalidate later array entries.
                if(children!=null && children.Length>0)continue;
                var transform=(MathTransform)component.Transform2;Packet.Need(transform!=null,"Native component has no placement evidence");
                double[] placement=Packet.V(transform.ArrayData);SwSession.Release(transform);
                Packet.Need(placement.Length>=13,"Native component transform is incomplete");
                for(int k=0;k<13;k++)Packet.Need(Math.Abs(placement[k]-((k==0 || k==4 || k==8 || k==12)?1.0:0.0))<1e-12,"This exact assembly reader requires verified identity component placements");
                object info=null;var actual=(object[])component.GetBodies3((int)swBodyType_e.swSolidBody,out info);
                Packet.Need(actual!=null && actual.Length>0,"Native leaf component contains no solid body: "+component.Name2);
                evidence.Add(new{name=component.Name2,first_body=bodies.Count,solid_count=actual.Length,placement=placement.Take(13).ToArray(),identity_placement_verified=true});
                bodies.AddRange(actual);
            } finally {SwSession.Release(component);}
        }
        componentEvidence=evidence;return bodies.ToArray();
    }
    public static void InspectLoaded(SldWorks app,string output,string report) {
            var timer=System.Diagnostics.Stopwatch.StartNew();
            var modeler=(Modeler)app.GetModeler();double[] old={modeler.SetToleranceValue(0,1e-12),modeler.SetToleranceValue(1,1e-12),modeler.SetToleranceValue(2,1e-12)};
            try {int error=0;Console.WriteLine("Native CAD import: "+output);var doc=(ModelDoc2)app.LoadFile4(output,"r",null,ref error);Packet.Need(doc!=null,"Native reread failed: "+error);var native=new List<object>();object componentEvidence=null;var bodies=InspectionBodies(doc,out componentEvidence);Packet.Need(bodies!=null && bodies.Length>0,"Native reread contains no solid bodies");int faultsCount=0;var faultDetails=new List<object>();
                foreach(Body2 b in bodies){Console.WriteLine("Native body check: "+b.GetFaceCount()+" faces");var faults=b.Check3;faultsCount+=faults==null?0:faults.Count;
                    if(faults!=null)for(int i=0;i<faults.Count;i++){var entity=faults.get_Entity2(i);int code=faults.get_ErrorCode(i);var face=entity as Face2;object bounds=face==null?null:face.GetBox();string name=Enum.GetName(typeof(swFaultEntityErrorCode_e),code);faultDetails.Add(new{code=code,name=name,face_bounds=bounds});Console.WriteLine("Native fault: "+code+" "+name);}
                    SwSession.Release(faults);if(System.Environment.GetEnvironmentVariable("EXACT_NATIVE_DEBUG")=="1")SwReadback.DebugCurves(modeler,b);native.Add(SwReadback.BodyData(b));}
                Packet.Write(report,new{readback_performed=true,file_sha256=Packet.Sha(output),geometry=native,component_placements=componentEvidence,passed=false,topology_passed=faultsCount==0,faults=faultsCount,fault_details=faultDetails,strict_validation_pending=true,curve_extraction="unwrapped_original_curve_parameters",circle_trim_evaluation="IEdge.Evaluate2",curve_extraction_tolerance_m=1e-12,inspection_seconds=timer.Elapsed.TotalSeconds});Console.WriteLine("Native exact inspection complete: "+bodies.Length+" solids, faults "+faultsCount+", seconds "+timer.Elapsed.TotalSeconds.ToString("F2"));
                app.CloseAllDocuments(true);
            }finally {for(int i=0;i<3;i++)modeler.SetToleranceValue(i,old[i]);}
    }
}
