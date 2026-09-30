using SolidWorks.Interop.sldworks;
public static class SwInspectionHost {
    public static int Load(string path) {return SwSession.App.LoadAddIn(path);}
    public static int Unload(string path) {return SwSession.App.UnloadAddIn(path);}
}
