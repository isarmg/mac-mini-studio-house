using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

[assembly:ComVisible(false)]
[ComVisible(true),Guid("2D37D692-0752-49ED-875D-3439B1904EA8"),ClassInterface(ClassInterfaceType.None)]
public sealed class InspectionAddin : ISwAddin {
    static void Draw(SldWorks app,ModelDoc2 doc,string path,bool rear) {
        double r=1/Math.Sqrt(2),q=1/Math.Sqrt(6),n=1/Math.Sqrt(3);
        var matrix=rear?new double[]{1,0,0,0,0,-1,0,1,0,0,0,0,1,0,0,0}:
            new double[]{r,q,n,r,-q,-n,0,2*q,-n,0,0,0,1,0,0,0};
        doc.ClearSelection2(true);doc.ViewDisplayShaded();
        var view=(ModelView)doc.ActiveView;view.EnableGraphicsUpdate=true;
        view.Orientation3=(MathTransform)((MathUtility)app.GetMathUtility()).CreateTransform(matrix);
        doc.ViewZoomtofit2();Application.DoEvents();doc.WindowRedraw();view.GraphicsRedraw(null);Application.DoEvents();
        int error=0,warning=0;
        NativeCommon.Need(doc.Extension.SaveAs(path,0,1,null,ref error,ref warning),"Native inspection image failed: "+error);
    }
    public bool ConnectToSW(object application,int cookie) {
        string folder=Path.GetDirectoryName(typeof(InspectionAddin).Assembly.Location);
        var job=Packet.Read(Path.Combine(folder,"job.json"));var app=(SldWorks)application;
        var previous=Console.Out;bool command=app.CommandInProgress;
        using(var log=new StreamWriter((string)job["log"],false,new System.Text.UTF8Encoding(false))) {
            log.AutoFlush=true;Console.SetOut(log);
            try {
                NativeCommon.App=app;string output=(string)job["output"],evidence=(string)job["evidence"];
                string images=Path.Combine(evidence,"images");Directory.CreateDirectory(images);
                var records=new List<object>();var files=Directory.GetFiles(output,"*.sldprt");Array.Sort(files,StringComparer.OrdinalIgnoreCase);
                NativeCommon.Need(files.Length==16,"Sixteen native parts are required for default-session inspection");
                foreach(string file in files) {
                    Console.WriteLine("Default-session rebuild: "+Path.GetFileName(file));
                    string before=Packet.Sha(file);int error=0,warning=0;app.CommandInProgress=true;
                    var doc=(ModelDoc2)app.OpenDoc6(file,1,3,"",ref error,ref warning);
                    NativeCommon.Need(doc!=null && error==0,"Read-only native open failed: "+error);
                    NativeCommon.Rebuild(doc);var state=NativeAudit.State(doc);var views=new List<object>();
                    string stem=Path.GetFileNameWithoutExtension(file);bool housing=stem.EndsWith("_housing"),bottom=stem.EndsWith("_base");
                    if(housing || bottom) {
                        app.CommandInProgress=false;
                        var names=new List<string>{stem+(housing?"_interior":"_underside")+".png"};
                        if(housing)names.Add(stem+"_rear.png");
                        foreach(string name in names) {
                            string path=Path.Combine(images,name);Draw(app,doc,path,name.EndsWith("_rear.png"));
                            views.Add(new{file="images/"+name,sha256=Packet.Sha(path)});
                        }
                    }
                    app.CloseDoc(doc.GetTitle());NativeCommon.Need(Packet.Sha(file)==before,"Read-only inspection modified native CAD");
                    records.Add(new{file=Path.GetFileName(file).ToLowerInvariant(),file_sha256=before,cad_unchanged=true,state=state,images=views});
                }
                Packet.Write(Path.Combine(evidence,"default-session.json"),new{schema="solidworks-native-default-session-v1",
                    solidworks_revision=app.RevisionNumber(),read_only=true,modeler_tolerances_modified=false,
                    source_sha256=job["source_sha256"],files=records});
                Packet.Write((string)job["status"],new{completed=true,passed=true});
            } catch(Exception error) {
                Console.WriteLine(error);Packet.Write((string)job["status"],new{completed=true,passed=false,error=error.ToString()});
            } finally {app.CloseAllDocuments(true);app.CommandInProgress=command;Console.SetOut(previous);}
        }
        return true;
    }
    public bool DisconnectFromSW(){return true;}
}
