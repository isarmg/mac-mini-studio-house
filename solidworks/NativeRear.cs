using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public sealed class NativeRear : NativeCommon {
    sealed class Column { public double[] First;public int Width=1; }
    public static void Build(ModelDoc2 doc,Dictionary<string,object> variant,double height) {
        var rows=Packet.A(variant["rear_holes"]).Select(Packet.V).ToArray();
        var design=Packet.D(variant["design"]);var definition=Packet.D(design["rear_grid_design"]);
        double interfaceZ=Packet.N(Packet.D(design["base_design"])["interface_z_mm"]);
        double pitch=Packet.N(definition["horizontal_pitch_mm"])*Packet.N(definition["vertical_pitch_to_horizontal_ratio"]);
        double low=rows.Min(r=>r[6])-interfaceZ;
        Global(doc,"RearHoleDiameter",Packet.N(definition["diameter_mm"]));Global(doc,"RearRowPitch",pitch);
        Global(doc,"RearBottomZ",low);Global(doc,"RearRowPairs",13,"");
        var axis=Axis(doc,Plane(doc,1),Plane(doc,2),"RearPatternZAxis");int index=0;
        var xAxis=Axis(doc,Plane(doc),Plane(doc,1),"RearPatternXAxis");
        var seeds=new[]{new List<Feature>(),new List<Feature>()};
        var columns=rows.GroupBy(r=>r[3]).Select(g=>g.OrderBy(r=>r[6]).First()).OrderBy(r=>r[3]).ToArray();
        var work=new List<Column>();
        foreach(var first in columns.Where(r=>Math.Abs(r[7])>1e-12))work.Add(new Column{First=first});
        for(int parity=0;parity<2;parity++) {
            var flat=columns.Where(r=>Math.Abs(r[7])<=1e-12 && (int)r[1]%2==parity).ToArray();
            Need(flat.Length>1,"Rear straight profile row");
            for(int i=1;i<flat.Length;i++)Need(Math.Abs(flat[i][4]-flat[i-1][4]-2)<1e-8,"Rear straight row pitch");
            work.Add(new Column{First=flat[0],Width=flat.Length});
        }
        Need(work.Sum(c=>c.Width)==171,"Rear wrapped column inventory");
        foreach(var column in work) {
            var timer=System.Diagnostics.Stopwatch.StartNew();
            var first=column.First;int parity=(int)first[1]%2;
            string id="RearColumn"+(index++).ToString("D3");
            var plane=ThreePointPlane(doc,id+"Plane",new[]{first[4],first[5],0},
                new[]{-first[8]*5,first[7]*5,0},new[]{0.0,0,5});
            if(index<=3)Console.WriteLine(id+" datum seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
            BeginSketch(doc,id+"Circle",plane);double z=first[6]-interfaceZ;
            var p=InSketch(doc,new[]{first[4],first[5],z});var lifted=InSketch(doc,new[]{first[4],first[5],z+1});
            var circle=doc.SketchManager.CreateCircleByRadius(p[0],p[1],0,first[10]/1000);
            Need(circle!=null,"Rear bore profile");
            string diameter=Diameter(doc,circle,p,first[10]/1000);
            var position=PositionPoint(doc,((SketchArc)circle).IGetCenterPoint2(),p);
            int vertical=Math.Abs(lifted[0]-p[0])>.0009?0:1;
            double coefficient=Math.Sign(p[vertical])*(lifted[vertical]-p[vertical])*1000;
            Need(position[vertical]!=null && Math.Abs(Math.Abs(coefficient)-1)<1e-8,"Rear profile vertical coordinate");
            Link(doc,diameter,Quote("RearHoleDiameter"));
            Link(doc,position[vertical],Number(Math.Abs(p[vertical])*1000)+"mm+"+Number(coefficient)+"*("+
                Quote("RearBottomZ")+(parity==1?"+"+Quote("RearRowPitch"):"")+"-"+Number(z)+"mm)");
            EndSketch(doc);if(index<=3)Console.WriteLine(id+" sketch seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
            var seed=Cut(doc,id+"Bore",10,false,0,0,true);
            if(index<=3)Console.WriteLine(id+" cut seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
            seeds[parity].Add(seed);
            if(column.Width>1)seeds[parity].Add(LinearPattern(doc,seed,xAxis,column.Width,2,id+"StraightRow",true,0));
            if(index%10==0)Console.WriteLine("Rear normal cut groups: "+index+"/"+work.Count+", group seconds: "+timer.Elapsed.TotalSeconds.ToString("F2"));
        }
        Need(index==work.Count,"Rear normal cut group count");
        for(int parity=0;parity<2;parity++) {
            int count=parity==0?14:13;
            var pattern=LinearPattern(doc,seeds[parity].ToArray(),axis,count,2*pitch,parity==0?"RearEvenRows":"RearOddRows");
            Link(doc,Dimension(pattern,count),Quote("RearRowPairs")+(parity==0?"+1":""));
            Link(doc,Dimension(pattern,2*pitch/1000),"2*"+Quote("RearRowPitch"));
            Console.WriteLine("Rear native row group: "+(parity+1)+"/2");
        }
    }
}
