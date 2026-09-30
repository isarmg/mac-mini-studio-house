using System;
using System.IO;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swpublished;

[assembly: ComVisible(false)]

[ComVisible(true),Guid("2D16C047-FE48-4C43-8C60-9F02F43B9957"),ClassInterface(ClassInterfaceType.None)]
public sealed class ExactCadInspectionAddin : ISwAddin {
    public bool ConnectToSW(object application,int cookie) {
        string jobPath=System.Environment.GetEnvironmentVariable("EXACT_CAD_INSPECTION_JOB");
        if(String.IsNullOrEmpty(jobPath))jobPath=Path.Combine(Path.GetDirectoryName(typeof(ExactCadInspectionAddin).Assembly.Location),"job.json");
        File.AppendAllText(Path.Combine(Path.GetDirectoryName(typeof(ExactCadInspectionAddin).Assembly.Location),"connect.log"),DateTime.UtcNow.ToString("o")+" "+jobPath+System.Environment.NewLine);
        var envelope=Packet.Read(jobPath);
        var jobs=envelope.ContainsKey("jobs")?Packet.A(envelope["jobs"]):new object[]{envelope};
        foreach(var raw in jobs) {
            RunJob((SldWorks)application,Packet.D(raw));
            GC.Collect();GC.WaitForPendingFinalizers();
        }
        return true;
    }
    static void RunJob(SldWorks app,System.Collections.Generic.Dictionary<string,object> job) {
        string report=(string)job["report"];
        var previous=Console.Out;
        using(var log=new StreamWriter((string)job["log"],false,new System.Text.UTF8Encoding(false))) {
            log.AutoFlush=true;Console.SetOut(log);
            try {
                if(job.ContainsKey("action") && (string)job["action"]=="transfer")SwExact.TransferLoaded(app,(string)job["input"],(string)job["model"],report);
                else if(job.ContainsKey("action") && (string)job["action"]=="compose")SwExact.ComposeLoaded(app,(string)job["input"],(string)job["model"],report);
                else if(job.ContainsKey("action") && (string)job["action"]!="inspect") throw new InvalidOperationException("Unsupported native action");
                else SwExact.InspectLoaded(app,(string)job["model"],report);
            }
            catch(Exception ex) {Packet.Write(report,new{passed=false,error=ex.ToString(),in_process=true});Console.WriteLine(ex);}
            finally {Console.SetOut(previous);}
        }
        var outcome=Packet.Read(report);
        Packet.Write(report+".status.json",new{completed=true,topology_passed=outcome.ContainsKey("topology_passed")?outcome["topology_passed"]:null,error=outcome.ContainsKey("error")?outcome["error"]:null});
    }
    public bool DisconnectFromSW() {return true;}
}
