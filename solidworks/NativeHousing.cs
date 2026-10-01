using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public sealed class NativeHousing : NativeCommon {
    public static void Build(string model,int wall,bool perforated,double plainHeight=0) {
        var modelData=Packet.D(Packet.D(Input["models"])[model]);var profiles=Packet.D(modelData["profiles"]);
        var variant=Packet.D(Packet.D(modelData["variants"])[wall==0?"2":wall.ToString()]);
        var design=Packet.D(variant["design"]);var baseDesign=Packet.D(design["base_design"]);
        double height=perforated?Packet.V(design["nominal_dimensions_mm"])[2]-Packet.N(baseDesign["interface_z_mm"]):plainHeight;
        string label=perforated?model+"_enclosure_"+wall+"mm_housing":
            model+(wall==0?(plainHeight==1?"_1mm-solid":"_solid"):"_plain-shell_"+wall+"mm");
        Console.WriteLine("Building native housing: "+label);
        var doc=NewPart();Global(doc,"HousingHeight",height);if(wall>0)Global(doc,"TopThickness",wall);
        var outer=InsertReference(doc,Packet.D(profiles["outer"]),"ExactG3OuterProfile");
        GrowPrism(doc,outer,height,"ExtrusionHeight",Quote("HousingHeight"));
        if(wall>0) {
            var tool=InsertReference(doc,Packet.D(profiles["inner"+wall]),"ExactG3InnerProfile");string toolName=tool.Name;
            GrowPrism(doc,tool,height-wall,"CavityDepth",Quote("HousingHeight")+"-"+Quote("TopThickness"));
            tool=Bodies(doc).Single(b=>b.Name==toolName);var main=Bodies(doc).Single(b=>b.Name!=toolName);
            Subtract(doc,main,tool,"HollowHousing");
        }
        if(perforated) {
            Global(doc,"PortHeightOffset",0);
            var ports=Packet.A(variant["ports"]);
            for(int i=0;i<ports.Length;i++) {
                var definition=Packet.D(ports[i]);double[] center=Packet.V(definition["center_mm"]);
                var main=OnlyBody(doc);string mainName=main.Name;
                var tool=InsertReference(doc,definition,"Port"+(i+1).ToString("D2")+"Profile");string toolName=tool.Name;
                var placement=MoveBody(doc,tool,center[0],center[1],center[2],"Port"+(i+1).ToString("D2")+"Position");
                Link(doc,Dimension(placement,center[2]/1000),Number(center[2])+"mm+"+Quote("PortHeightOffset"));
                tool=Bodies(doc).Single(b=>b.Name==toolName);main=Bodies(doc).Single(b=>b.Name!=toolName);
                Subtract(doc,main,tool,"Port"+(i+1).ToString("D2")+"Cut");
                Console.WriteLine("Functional ports: "+(i+1)+"/"+ports.Length);
            }
            if(model=="mac-studio")NativeRear.Build(doc,variant,height);
        }
        Validate(doc,label,model,wall,height,perforated);
    }
    public static void Validate(ModelDoc2 doc,string label,string model,int wall,double height,bool perforated) {
        Rebuild(doc);var tests=new Dictionary<string,object>{{"baseline",NativeAudit.State(doc)}};
        AssignGlobal(doc,"HousingHeight",height+2);if(wall>0)AssignGlobal(doc,"TopThickness",wall+.5);
        if(perforated) {
            AssignGlobal(doc,"PortHeightOffset",1);
            if(model=="mac-studio") {
                AssignGlobal(doc,"RearHoleDiameter",1.6);AssignGlobal(doc,"RearRowPairs",12,"");
            }
        }
        Rebuild(doc);tests["edited_parameters"]=NativeAudit.State(doc);
        AssignGlobal(doc,"HousingHeight",height);if(wall>0)AssignGlobal(doc,"TopThickness",wall);
        if(perforated){AssignGlobal(doc,"PortHeightOffset",0);if(model=="mac-studio"){AssignGlobal(doc,"RearHoleDiameter",1.5);AssignGlobal(doc,"RearRowPairs",13,"");}}
        Rebuild(doc);
        NativeAudit.Finish(doc,label,tests,new{model=model,wall_mm=wall,height_mm=height,perforated=perforated,
            expected_ports=perforated?(model=="mac-mini"?9:14):0,expected_rear_bores=perforated && model=="mac-studio"?2309:0});
    }
}
