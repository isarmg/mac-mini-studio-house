using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public sealed class NativeBase : NativeCommon {
    sealed class Frame { public Feature Plane, Generator; }
    static Frame TangentFrame(ModelDoc2 doc,Feature zAxis,double theta,string phaseExpression,double angle,double radius,string name) {
        Feature radial=Plane(doc,2),meridian=Plane(doc,1);
        if(Math.Abs(theta)>1e-12) {
            double magnitude=Math.Abs(theta);bool reverse=theta<0;
            string expression=reverse?"-("+phaseExpression+")":phaseExpression;
            radial=AnglePlane(doc,radial,zAxis,magnitude,name+"RadialPlane",reverse);
            meridian=AnglePlane(doc,meridian,zAxis,magnitude,name+"MeridianPlane",reverse);
            Link(doc,Dimension(radial,magnitude),expression);Link(doc,Dimension(meridian,magnitude),expression);
        }
        var tangentAxis=Axis(doc,Plane(doc),radial,name+"TangentAxis");
        double beta=Math.PI/2-angle;
        var tilt=AnglePlane(doc,radial,tangentAxis,beta,name+"ConeAnglePlane",true);
        Link(doc,Dimension(tilt,beta),"90-"+Quote("ConeAngle"));
        double distance=radius*Math.Sin(angle);
        var plane=OffsetPlane(doc,tilt,distance,name+"ConeTangentPlane");
        Link(doc,Dimension(plane,distance/1000),Quote("LowerRadius")+"*sin("+Quote("ConeAngle")+")");
        var generator=Axis(doc,plane,meridian,name+"Generatrix");
        return new Frame{Plane=plane,Generator=generator};
    }
    static int GeneratorCoordinate(double[] p,double scalar) {
        int axis=Math.Abs(p[0])>Math.Abs(p[1])?0:1;
        Need(Math.Abs(p[2])<1e-8 && Math.Abs(p[1-axis])<1e-8 && Math.Abs(Math.Abs(p[axis])*1000-scalar)<1e-5,
            "Cone tangent-plane coordinate mismatch: "+String.Join(",",p)+", expected scalar "+scalar);
        return axis;
    }
    static Feature CircularSeed(ModelDoc2 doc,Frame frame,string name,double theta,double z,double radius,double angle,double diameter,string heightExpression) {
        double slope=1/Math.Tan(angle),r=radius+slope*z;
        BeginSketch(doc,name+"Circle",frame.Plane);
        var p=InSketch(doc,new[]{r*Math.Cos(theta),r*Math.Sin(theta),z});
        int axis=GeneratorCoordinate(p,radius*Math.Cos(angle)+z/Math.Sin(angle));
        var circle=doc.SketchManager.CreateCircleByRadius(p[0],p[1],0,diameter/2000);Need(circle!=null,"Normal circular bore profile");
        string size=Diameter(doc,circle,p,diameter/2000);
        var position=PositionPoint(doc,((SketchArc)circle).IGetCenterPoint2(),p);
        Link(doc,size,Quote("VentDiameter"));
        Link(doc,position[axis],Quote("LowerRadius")+"*cos("+Quote("ConeAngle")+")+("+heightExpression+")/sin("+Quote("ConeAngle")+")");
        EndSketch(doc);return Cut(doc,name+"NormalCut",10,false,0,0,true);
    }
    static void StudioVents(ModelDoc2 doc,Feature zAxis,double height,double thickness,double radius,double angle) {
        const int count=244,pairs=4;const double diameter=1.5,clearance=.75;
        Global(doc,"VentDiameter",diameter);Global(doc,"RingPairs",pairs,"");Global(doc,"HolesPerRing",count,"");
        Equation(doc,Quote("LowestCenterZ")+"=("+Quote("VentClearance")+"+"+Quote("VentDiameter")+"/2)*sin("+Quote("ConeAngle")+")");
        Equation(doc,Quote("RingStepZ")+"=("+Quote("BaseHeight")+"-"+Quote("PlateThickness")+"-2*"+Quote("LowestCenterZ")+")/(2*"+Quote("RingPairs")+"-1)");
        double low=(clearance+diameter/2)*Math.Sin(angle),step=(height-thickness-2*low)/(2*pairs-1);
        for(int parity=0;parity<2;parity++) {
            string name=parity==0?"EvenRings":"OddRings";double theta=parity*Math.PI/count;
            var frame=TangentFrame(doc,zAxis,theta,parity==0?"0":"180/"+Quote("HolesPerRing"),angle,radius,name);
            string zExpression=Quote("LowestCenterZ")+(parity==0?"":"+"+Quote("RingStepZ"));
            var seed=CircularSeed(doc,frame,name,theta,low+parity*step,radius,angle,diameter,zExpression);
            var along=LinearPattern(doc,seed,frame.Generator,pairs,2*step/Math.Sin(angle),name+"AlongCone",false);
            Link(doc,Dimension(along,pairs),Quote("RingPairs"));
            Link(doc,Dimension(along,2*step/Math.Sin(angle)/1000),"2*"+Quote("RingStepZ")+"/sin("+Quote("ConeAngle")+")");
            var around=CircularPattern(doc,new[]{seed,along},zAxis,count,name+"AroundAxis");
            Link(doc,Dimension(around,count),Quote("HolesPerRing"));
            Console.WriteLine("Studio native ring group: "+(parity+1)+"/2");
        }
    }
    static void MiniVents(ModelDoc2 doc,Feature zAxis,Dictionary<string,object> variant,double height,double thickness,double radius,double angle) {
        var pattern=Packet.D(variant["vents"]);double theta=Packet.N(pattern["phase_radians"]);
        double span=height-thickness,length=span/Math.Sin(angle)-1.5,width=2,z=span/2;
        Global(doc,"VentWidth",width);Global(doc,"VentCount",108,"");Global(doc,"VentPhase",theta*180/Math.PI,"");
        Equation(doc,Quote("VentLength")+"=("+Quote("BaseHeight")+"-"+Quote("PlateThickness")+")/sin("+Quote("ConeAngle")+")-2*"+Quote("VentClearance"));
        var frame=TangentFrame(doc,zAxis,theta,Quote("VentPhase"),angle,radius,"Capsule");
        var sketch=BeginSketch(doc,"CapsuleProfile",frame.Plane);double r=radius+z/Math.Tan(angle);
        var p=InSketch(doc,new[]{r*Math.Cos(theta),r*Math.Sin(theta),z});
        int coordinate=GeneratorCoordinate(p,radius*Math.Cos(angle)+z/Math.Sin(angle));
        var start=(double[])p.Clone();var end=(double[])p.Clone();start[coordinate]-=(length-width)/2000;end[coordinate]+=(length-width)/2000;
        var slot=doc.SketchManager.CreateSketchSlot(0,1,width/1000,start[0],start[1],0,end[0],end[1],0,0,0,0,1,true);
        Need(slot!=null,"Native capsule slot construction failed");
        Console.WriteLine("Mini native slot: width="+slot.Width+", length="+slot.Length);
        var handle=slot.GetCenterPointHandle();Need(handle!=null,"Native slot centre handle");
        var position=PositionPoint(doc,handle,p);
        Link(doc,position[coordinate],Quote("LowerRadius")+"*cos("+Quote("ConeAngle")+")+("+Quote("BaseHeight")+"-"+Quote("PlateThickness")+")/(2*sin("+Quote("ConeAngle")+"))");
        Link(doc,Dimension(sketch,width/1000),Quote("VentWidth"));
        Link(doc,Dimension(sketch,length/1000),Quote("VentLength"));EndSketch(doc);
        var seed=Cut(doc,"CapsuleNormalCut",10,false,0,0,true);
        var around=CircularPattern(doc,new[]{seed},zAxis,108,"CapsulesAroundAxis");
        Link(doc,Dimension(around,108),Quote("VentCount"));
    }
    public static void Build(string model,int wall) {
        string name=model+"_enclosure_"+wall+"mm_base";Console.WriteLine("Building native base: "+name);
        var modelData=Packet.D(Packet.D(Input["models"])[model]);var profiles=Packet.D(modelData["profiles"]);
        var variant=Packet.D(Packet.D(modelData["variants"])[wall.ToString()]);var design=Packet.D(variant["design"]);
        var d=Packet.D(design["base_design"]);double height=Packet.N(d["height_mm"]),thickness=1.5;
        double angle=Packet.N(d["cone_angle_to_horizontal_degrees"])*Math.PI/180,radius=Packet.N(d["outer_cone_radius_intercept_mm"]);
        double slope=1/Math.Tan(angle),span=height-thickness,beta=Math.PI/2-angle;
        var doc=NewPart();Global(doc,"BaseHeight",height);Global(doc,"PlateThickness",thickness);
        Global(doc,"ConeAngle",angle*180/Math.PI,"");Global(doc,"LowerRadius",radius);Global(doc,"VentClearance",.75);
        var plate=InsertReference(doc,Packet.D(profiles["inner"+wall]),"ExactG3MatingProfile");
        GrowPrism(doc,plate,thickness,"MatingPlateThickness",Quote("PlateThickness"));
        var placement=MoveBody(doc,OnlyBody(doc),0,0,span,"MatingPlatePosition");
        Link(doc,Dimension(placement,span/1000),Quote("BaseHeight")+"-"+Quote("PlateThickness"));
        string diameter=Circle(doc,"OuterConeCircle",radius);Link(doc,diameter,"2*"+Quote("LowerRadius"));
        var outer=Extrude(doc,"OuterCone",span,true,beta);Link(doc,Dimension(outer,span/1000),Quote("BaseHeight")+"-"+Quote("PlateThickness"));
        Link(doc,Dimension(outer,beta),"90-"+Quote("ConeAngle"));
        double innerRadius=radius+slope*thickness-thickness/Math.Sin(angle);
        string innerDiameter=Circle(doc,"InnerConeCircle",innerRadius);
        Link(doc,innerDiameter,"2*("+Quote("LowerRadius")+"+"+Quote("PlateThickness")+"/tan("+Quote("ConeAngle")+")-"+Quote("PlateThickness")+"/sin("+Quote("ConeAngle")+"))");
        var cavity=Cut(doc,"InnerCone",height-thickness+1,true,beta,thickness);
        Link(doc,Dimension(cavity,(height-thickness+1)/1000),Quote("BaseHeight")+"-"+Quote("PlateThickness")+"+1mm");
        Link(doc,Dimension(cavity,thickness/1000),Quote("PlateThickness"));Link(doc,Dimension(cavity,beta),"90-"+Quote("ConeAngle"));
        var mate=OffsetPlane(doc,Plane(doc),span,"MatingPlane");Link(doc,Dimension(mate,span/1000),Quote("BaseHeight")+"-"+Quote("PlateThickness"));
        var axis=Axis(doc,Plane(doc,1),Plane(doc,2),"BaseAxis");
        if(model=="mac-studio")StudioVents(doc,axis,height,thickness,radius,angle);
        else {
            MiniVents(doc,axis,variant,height,thickness,radius,angle);
            var button=Packet.D(modelData["button"]);var center=Packet.V(button["center_mm"]);
            var tool=InsertReference(doc,button,"ButtonProfile");string toolName=tool.Name;
            MoveBody(doc,tool,center[0],center[1],center[2],"ButtonPosition");tool=Bodies(doc).Single(b=>b.Name==toolName);
            Subtract(doc,Bodies(doc).Single(b=>b.Name!=toolName),tool,"ButtonCut");
        }
        Validate(doc,name,model,wall,height,thickness,angle);
    }
    public static void Validate(ModelDoc2 doc,string name,string model,int wall,double height,double thickness,double angle) {
        Rebuild(doc);var tests=new Dictionary<string,object>{{"baseline",NativeAudit.State(doc)}};
        AssignGlobal(doc,"BaseHeight",height+1);AssignGlobal(doc,"ConeAngle",angle*180/Math.PI+5,"");
        if(model=="mac-studio") {
            AssignGlobal(doc,"VentDiameter",1.6);AssignGlobal(doc,"HolesPerRing",200,"");AssignGlobal(doc,"RingPairs",3,"");
        } else {
            AssignGlobal(doc,"VentWidth",2.2);AssignGlobal(doc,"VentCount",96,"");
        }
        Rebuild(doc);tests["edited_parameters"]=NativeAudit.State(doc);
        AssignGlobal(doc,"BaseHeight",height);AssignGlobal(doc,"ConeAngle",angle*180/Math.PI,"");
        if(model=="mac-studio"){AssignGlobal(doc,"VentDiameter",1.5);AssignGlobal(doc,"HolesPerRing",244,"");AssignGlobal(doc,"RingPairs",4,"");}
        else{AssignGlobal(doc,"VentWidth",2);AssignGlobal(doc,"VentCount",108,"");}
        Rebuild(doc);
        NativeAudit.Finish(doc,name,tests,new{model=model,wall_mm=wall,base_height_mm=height,plate_thickness_mm=thickness,
            cone_angle_degrees=angle*180/Math.PI,expected_base_bores=model=="mac-studio"?1952:108});
    }
}
