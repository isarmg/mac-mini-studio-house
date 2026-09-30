
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Threading;
using SolidWorks.Interop.sldworks;

public static class SwSession {
    public static bool SkipReadback=false;
    static Dictionary<int,bool> savedImportPreferences=new Dictionary<int,bool>();
    static Dictionary<int,int> savedImportIntegers=new Dictionary<int,int>();
    static Dictionary<int,double> savedImportDoubles=new Dictionary<int,double>();
    static SldWorks app;
    static bool owned;
    static int processId;
    static Process launchedProcess;
    static bool keepApplication;
    public static bool CollectCylinders=false;
    [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
    [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved,out IBindCtx context);
    // A returned RCW has exactly one owner here. ModelDoc2 -> PartDoc/AssemblyDoc
    // casts are borrowed aliases and are never released separately from the model.
    public static void Release(object value) {
        if(value==null || !Marshal.IsComObject(value))return;
        try {Marshal.FinalReleaseComObject(value);}
        catch(InvalidComObjectException){}
        catch(COMException error){Console.WriteLine("SolidWorks COM release: "+error.Message);}
    }
    static void ReleaseArray(object[] values) {
        if(values==null)return;
        for(int i=0;i<values.Length;i++) {
            object value=values[i];values[i]=null;Release(value);
        }
    }
    static void CollectReleasedGeometry() {
        GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
    }
    [StructLayout(LayoutKind.Sequential)] sealed class RereadMemoryStatus {
        public uint length=(uint)Marshal.SizeOf(typeof(RereadMemoryStatus));public uint load;
        public ulong totalPhysical,availablePhysical,totalCommit,availableCommit,totalVirtual,availableVirtual,availableExtended;
    }
    [DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx([In,Out] RereadMemoryStatus value);
    public static double MinimumFreeGiB=1.0;
    static void RequireRereadMemory() {
        var status=new RereadMemoryStatus();
        if(!GlobalMemoryStatusEx(status))throw new Exception("Windows memory check before native reread failed");
        double physical=status.availablePhysical/1073741824.0,commit=status.availableCommit/1073741824.0;
        Console.WriteLine("SolidWorks released source; available GiB: physical="+physical.ToString("F2")+", commit="+commit.ToString("F2"));
        if(physical<MinimumFreeGiB || commit<MinimumFreeGiB)throw new Exception("Need "+MinimumFreeGiB+" GiB physical and commit headroom before native reread; source document has been closed.");
    }
    static SldWorks FindOwnedApplication(int pid) {
        IRunningObjectTable table=null;IBindCtx context=null;IEnumMoniker items=null;
        var item=new IMoniker[1];
        try {
            Marshal.ThrowExceptionForHR(GetRunningObjectTable(0,out table));
            Marshal.ThrowExceptionForHR(CreateBindCtx(0,out context));
            table.EnumRunning(out items);
            while(items.Next(1,item,IntPtr.Zero)==0) {
                object found=null;
                try {
                    string name;item[0].GetDisplayName(context,null,out name);
                    if(name.IndexOf("SolidWorks_PID_"+pid,StringComparison.OrdinalIgnoreCase)>=0) {
                        table.GetObject(item[0],out found);var candidate=found as SldWorks;
                        if(candidate!=null && candidate.GetProcessID()==pid) {
                            found=null; // Transfer this RCW to the caller.
                            return candidate;
                        }
                    }
                } finally {
                    Release(found);Release(item[0]);item[0]=null;
                }
            }
        } finally {
            Release(item[0]);Release(items);Release(context);Release(table);
        }
        SldWorks active=null;
        try {
            active=(SldWorks)Marshal.GetActiveObject("SldWorks.Application");
            if(active.GetProcessID()==pid) {
                var result=active;active=null;return result;
            }
        }catch(COMException){}
        finally {Release(active);}
        return null;
    }
    public static void Begin() {
        var info=new ProcessStartInfo(@"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe");
        info.WindowStyle=ProcessWindowStyle.Hidden;info.UseShellExecute=true;
        launchedProcess=Process.Start(info);processId=launchedProcess.Id;owned=true;
        Console.WriteLine("SolidWorks launched isolated PID "+processId);
        var started=DateTime.UtcNow;
        while((DateTime.UtcNow-started).TotalSeconds<180) {
            if(launchedProcess.HasExited)throw new Exception("Isolated SolidWorks process exited during startup");
            try {app=FindOwnedApplication(processId);}catch(COMException){}
            if(app!=null)break;
            Thread.Sleep(1000);
        }
        if(app==null)throw new Exception("The isolated SolidWorks PID did not publish a COM/ROT application");
        app.Visible=false; app.UserControl=false; app.CommandInProgress=true;
        if(SkipReadback)foreach(string name in new string[]{"swImportAutoRunImportDiagnosticsPersist","swImportAutoRunImportDiagnostics","swImportNeutralRunDiagnostics","swForceEnableImportDiagnosis","swMultiCAD_Enable3DInterconnect","swImportNeutralAnalyticalConversion"}) {
            int key=(int)Enum.Parse(typeof(SolidWorks.Interop.swconst.swUserPreferenceToggle_e),name);
            savedImportPreferences[key]=app.GetUserPreferenceToggle(key);
            app.SetUserPreferenceToggle(key,false);
        }
        if(SkipReadback) {
            int key=(int)SolidWorks.Interop.swconst.swUserPreferenceIntegerValue_e.swCreateBodyFromSurfacesOption;
            savedImportIntegers[key]=app.GetUserPreferenceIntegerValue(key);
            if(!app.SetUserPreferenceIntegerValue(key,(int)SolidWorks.Interop.swconst.swGeneralImportSurfaceSolidEntityOptions_e.swGeneralImportByBrep)
                || app.GetUserPreferenceIntegerValue(key)!=(int)SolidWorks.Interop.swconst.swGeneralImportSurfaceSolidEntityOptions_e.swGeneralImportByBrep)
                throw new Exception("BREP import mode was not applied");
            // The default import tolerance can simplify very short spline
            // edges even with analytic surface conversion disabled. Keep the
            // smallest supported import tolerance; exact acceptance remains
            // independently stricter and is never inferred from this setting.
            foreach(var preference in new Dictionary<int,int>{
                // SOLIDWORKS requires both this switch and the body mode above.
                // Its documented value 0 enables direct BREP mapping.
                {(int)SolidWorks.Interop.swconst.swUserPreferenceIntegerValue_e.swImportUseBrep,0},
                {(int)SolidWorks.Interop.swconst.swUserPreferenceIntegerValue_e.swImportCheckAndRepair,0},
                {(int)SolidWorks.Interop.swconst.swUserPreferenceIntegerValue_e.swUseCustomizedImportTolerance,1}}) {
                savedImportIntegers[preference.Key]=app.GetUserPreferenceIntegerValue(preference.Key);
                Console.WriteLine("Import integer "+preference.Key+": previous "+savedImportIntegers[preference.Key]+", requested "+preference.Value);
                if(!app.SetUserPreferenceIntegerValue(preference.Key,preference.Value)
                    || app.GetUserPreferenceIntegerValue(preference.Key)!=preference.Value)
                    throw new Exception("Native import preference was not applied: "+preference.Key);
            }
            key=(int)SolidWorks.Interop.swconst.swUserPreferenceDoubleValue_e.swCustomizedImportTolerance;
            savedImportDoubles[key]=app.GetUserPreferenceDoubleValue(key);
            if(!app.SetUserPreferenceDoubleValue(key,1e-8)
                || Math.Abs(app.GetUserPreferenceDoubleValue(key)-1e-8)>1e-20)
                throw new Exception("Native import curve tolerance was not applied");
            Console.WriteLine("Import BREP mapping enabled; analytic conversion and repair disabled; curve tolerance 1e-8 m");
        }
    }
    public static void End() {
        var endingApp=app;var endingProcess=launchedProcess;
        bool endingOwned=owned,leaveRunning=keepApplication;
        app=null;launchedProcess=null;owned=false;keepApplication=false;
        try {
            if(endingApp!=null && endingOwned) {
                foreach(var preference in savedImportPreferences)endingApp.SetUserPreferenceToggle(preference.Key,preference.Value);
                savedImportPreferences.Clear();
                foreach(var preference in savedImportIntegers)endingApp.SetUserPreferenceIntegerValue(preference.Key,preference.Value);
                savedImportIntegers.Clear();
                foreach(var preference in savedImportDoubles)endingApp.SetUserPreferenceDoubleValue(preference.Key,preference.Value);
                savedImportDoubles.Clear();
                try {endingApp.CommandInProgress=false;}
                finally {if(!leaveRunning)endingApp.ExitApp();}
            }
        } catch(COMException error) {
            Console.WriteLine("SolidWorks application shutdown: "+error.Message);
        } finally {
            try {Release(endingApp);}
            finally {
                try {CollectReleasedGeometry();}
                finally {
                    try {
                        // Only a Process object created by this bridge can be killed.
                        if(endingProcess!=null && !leaveRunning && !endingProcess.HasExited
                            && !endingProcess.WaitForExit(15000)) {
                            endingProcess.Kill();
                            if(!endingProcess.WaitForExit(15000))throw new Exception("Owned SolidWorks did not exit");
                        }
                    } finally {if(endingProcess!=null)endingProcess.Dispose();}
                }
            }
        }
    }
    public static SldWorks App {get {return app;}}
}
