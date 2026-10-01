using System;
using System.IO;
using SolidWorks.Interop.sldworks;

public sealed class NativeRevalidate : NativeCommon {
    static ModelDoc2 Open(string name) {
        Console.WriteLine("Validating saved native features: "+name);
        string file=Path.Combine(Output,name+".sldprt");Need(File.Exists(file),"Native part is missing: "+file);
        int error=0,warning=0;var doc=(ModelDoc2)App.OpenDoc6(file,1,1,"",ref error,ref warning);
        Need(doc!=null && error==0,"Cannot open native part for parameter validation: "+error);return doc;
    }
    public static void Run() {
        foreach(string model in new[]{"mac-mini","mac-studio"}) {
            string name=model+"_solid";
            NativeHousing.Validate(Open(name),name,model,0,model=="mac-mini"?50:95,false);
            name=model+"_1mm-solid";NativeHousing.Validate(Open(name),name,model,0,1,false);
            var modelData=Packet.D(Packet.D(Input["models"])[model]);
            foreach(int wall in new[]{2,3}) {
                name=model+"_plain-shell_"+wall+"mm";
                NativeHousing.Validate(Open(name),name,model,wall,model=="mac-mini"?50:95,false);
                var variant=Packet.D(Packet.D(modelData["variants"])[wall.ToString()]);var design=Packet.D(variant["design"]);
                var basis=Packet.D(design["base_design"]);
                double height=Packet.V(design["nominal_dimensions_mm"])[2]-Packet.N(basis["interface_z_mm"]);
                name=model+"_enclosure_"+wall+"mm_housing";NativeHousing.Validate(Open(name),name,model,wall,height,true);
                name=model+"_enclosure_"+wall+"mm_base";
                NativeBase.Validate(Open(name),name,model,wall,Packet.N(basis["height_mm"]),1.5,
                    Packet.N(basis["cone_angle_to_horizontal_degrees"])*Math.PI/180);
            }
        }
    }
}
