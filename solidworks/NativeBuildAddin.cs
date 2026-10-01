using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;
using SolidWorks.Interop.swconst;

[assembly:ComVisible(false)]
[ComVisible(true),Guid("6AB4EFC0-B919-4CCB-AD94-24B10C2D0694"),ClassInterface(ClassInterfaceType.None)]
public sealed class NativeBuildAddin : ISwAddin {
    public bool ConnectToSW(object application,int cookie) {
        string build=Path.GetDirectoryName(typeof(NativeBuildAddin).Assembly.Location);
        var job=Packet.Read(Path.Combine(build,"job.json"));var app=(SldWorks)application;
        var previous=Console.Out;bool prompt=app.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate);
        bool command=app.CommandInProgress;
        var modeler=(Modeler)app.GetModeler();double[] tolerance=new double[3];
        using(var log=new StreamWriter((string)job["log"],false,new System.Text.UTF8Encoding(false))) {
            log.AutoFlush=true;Console.SetOut(log);
            try {
                for(int i=0;i<3;i++)tolerance[i]=modeler.SetToleranceValue(i,1e-12);
                app.CommandInProgress=true;
                app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate,false);
                NativeCommon.App=app;NativeCommon.Root=(string)job["root"];
                NativeCommon.Output=(string)job["output"];NativeCommon.Evidence=(string)job["evidence"];
                Directory.CreateDirectory(NativeCommon.Output);Directory.CreateDirectory(NativeCommon.Evidence);
                NativeCommon.Input=Packet.Read((string)job["input"]);
                NativeCommon.SourceBindings=job["source_sha256"];
                string mode=(string)job["mode"];
                bool recognized=mode=="all" || mode=="plain" || mode=="thin" || mode=="housing" || mode=="base" || mode=="assembly" || mode=="preview" || mode=="revalidate";
                foreach(string m in new[]{"mac-mini","mac-studio"})foreach(int w in new[]{2,3})
                    foreach(string kind in new[]{"housing","base","assembly"})if(mode==m+"-"+w+"-"+kind)recognized=true;
                NativeCommon.Need(recognized,"Unknown native construction mode: "+mode);
                if(mode=="revalidate")NativeRevalidate.Run();
                foreach(string model in new[]{"mac-mini","mac-studio"}) {
                    if(mode=="thin")NativeHousing.Build(model,0,false,1);
                    if(mode=="plain" || mode=="all") {
                        NativeHousing.Build(model,0,false,model=="mac-mini"?50:95);
                        NativeHousing.Build(model,0,false,1);
                        foreach(int wall in new[]{2,3})NativeHousing.Build(model,wall,false,model=="mac-mini"?50:95);
                    }
                    foreach(int wall in new[]{2,3})if(mode=="housing" || mode=="all" || mode==model+"-"+wall+"-housing")
                        NativeHousing.Build(model,wall,true);
                    foreach(int wall in new[]{2,3})if(mode=="base" || mode=="all" || mode==model+"-"+wall+"-base")
                        NativeBase.Build(model,wall);
                }
                foreach(string model in new[]{"mac-mini","mac-studio"})foreach(int wall in new[]{2,3})
                    if(mode=="assembly" || mode=="all" || mode=="revalidate" || mode==model+"-"+wall+"-assembly")NativeAssembly.Build(model,wall);
                if(mode=="preview")foreach(string file in Directory.GetFiles(NativeCommon.Output)) {
                    string extension=Path.GetExtension(file).ToLowerInvariant();if(extension!=".sldprt" && extension!=".sldasm")continue;
                    int error=0,warning=0;string before=Packet.Sha(file);
                    var doc=(ModelDoc2)app.OpenDoc6(file,extension==".sldprt"?1:2,1,"",ref error,ref warning);
                    NativeCommon.Need(doc!=null,"Native preview open failed: "+error);
                    NativeCommon.Preview(doc,Path.GetFileName(file));app.CloseAllDocuments(true);
                    NativeCommon.Need(Packet.Sha(file)==before,"Native preview changed the CAD file");
                    Console.WriteLine("Previewed native file: "+Path.GetFileName(file));
                }
                Packet.Write((string)job["status"],new{completed=true,passed=true,mode=mode});
            } catch(Exception error) {
                Console.WriteLine(error);Packet.Write((string)job["status"],new{completed=true,passed=false,error=error.ToString()});
            } finally {
                app.CloseAllDocuments(true);for(int i=0;i<3;i++)modeler.SetToleranceValue(i,tolerance[i]);
                app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate,prompt);Console.SetOut(previous);
                app.CommandInProgress=command;
            }
        }
        return true;
    }
    public bool DisconnectFromSW() { return true; }
}
