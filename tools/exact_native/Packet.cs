using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Web.Script.Serialization;

public static class Packet {
    public static string Sha(string path) {
        using(var stream=File.OpenRead(path))using(var hash=System.Security.Cryptography.SHA256.Create())
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
    }
    public static Dictionary<string,object> D(object value) { return (Dictionary<string,object>)value; }
    public static object[] A(object value) { return ((IEnumerable)value).Cast<object>().ToArray(); }
    public static double N(object value) { return Convert.ToDouble(value,System.Globalization.CultureInfo.InvariantCulture); }
    public static int I(object value) { return Convert.ToInt32(value); }
    public static double[] V(object value) {return A(value).Select(N).ToArray();}
    public static Dictionary<string,object> Read(string path) {
        var parser=new JavaScriptSerializer {MaxJsonLength=Int32.MaxValue,RecursionLimit=300};
        return D(parser.DeserializeObject(File.ReadAllText(path)));
    }
    public static void Write(string path,object value) {
        var parser=new JavaScriptSerializer {MaxJsonLength=Int32.MaxValue,RecursionLimit=300};
        File.WriteAllText(path,parser.Serialize(value),new System.Text.UTF8Encoding(false));
    }
    public static double[] Knots(Dictionary<string,object> data) {
        var knots=V(data["knots"]);var counts=A(data["multiplicities"]).Select(I).ToArray();var result=new List<double>();
        for(int i=0;i<knots.Length;i++)for(int j=0;j<counts[i];j++)result.Add(knots[i]);return result.ToArray();
    }
    public static void Need(bool value,string message) {if(!value)throw new Exception(message);}
    public static double[] EvaluateNurbs(Dictionary<string,object> data,double u) {
        var points=A(data["poles"]);var w=V(data["weights"]);var k=Knots(data);int degree=I(data["degree"]),span=degree;
        while(span<points.Length-1 && u>=k[span+1])span++;
        var d=new double[degree+1][];
        for(int j=0;j<=degree;j++){int id=span-degree+j;var p=V(points[id]);d[j]=new[]{p[0]*w[id],p[1]*w[id],(p.Length>2?p[2]:0)*w[id],w[id]};}
        for(int r=1;r<=degree;r++)for(int j=degree;j>=r;j--){int id=span-degree+j;double alpha=(u-k[id])/(k[id+degree-r+1]-k[id]);for(int v=0;v<4;v++)d[j][v]=(1-alpha)*d[j-1][v]+alpha*d[j][v];}
        return d[degree].Take(3).Select(x=>x/d[degree][3]).ToArray();
    }
}
