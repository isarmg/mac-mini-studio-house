using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public static class SwParametricPrototype {
    static string root, output;
    static string ImplementationHash() { return Packet.Sha(Path.Combine(root, "experiments", "solidworks-parametric", "Prototype.cs")); }
    static void Need(bool condition, string message) { if (!condition) throw new Exception(message); }
    static Feature Plane(ModelDoc2 doc, int index = 0) {
        var feature = (Feature)doc.FirstFeature(); int found = 0;
        while (feature != null) {
            if (feature.GetTypeName2() == "RefPlane" && found++ == index) return feature;
            feature = (Feature)feature.GetNextFeature();
        }
        throw new Exception("Default reference plane missing");
    }
    static ModelDoc2 NewPart(SldWorks app) {
        var doc = (ModelDoc2)app.NewDocument(@"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot", 0, 0, 0);
        Need(doc != null, "Cannot create prototype part"); return doc;
    }
    static void BeginSketch(ModelDoc2 doc, string name, int plane = 0) {
        doc.ClearSelection2(true); Need(Plane(doc, plane).Select2(false, 0), "Plane selection failed");
        doc.SketchManager.InsertSketch(true);
        Need(doc.SketchManager.ActiveSketch != null, "Sketch creation failed");
        doc.IFeatureByPositionReverse(0).Name = name;
        doc.SketchManager.AddToDB = true;
    }
    static Feature EndSketch(ModelDoc2 doc) {
        Feature sketch = doc.IFeatureByPositionReverse(0);
        doc.SketchManager.AddToDB = false;
        doc.SketchManager.InsertSketch(true); doc.ClearSelection2(true);
        Need(sketch.Select2(false, 0), "Sketch selection failed"); return sketch;
    }
    static Feature Extrude(ModelDoc2 doc, string name, double depth, bool draft = false, double draftAngle = 0, double offset = 0) {
        var feature = doc.FeatureManager.FeatureExtrusion3(true, false, false, 0, 0, depth / 1000, 0,
            draft, false, true, false, draftAngle, 0, false, false, false, false, true, true, true,
            offset == 0 ? 0 : 3, offset / 1000, false);
        Need(feature != null, "Extrusion failed: " + name); feature.Name = name; return feature;
    }
    static Feature Cut(ModelDoc2 doc, string name, double depth, bool draft = false,
        double draftAngle = 0, double offset = 0, bool both = false) {
        var feature = doc.FeatureManager.FeatureCut4(!both, false, true, 0, 0, depth / 1000, both ? depth / 1000 : 0,
            draft, false, true, false, draftAngle, 0, false, false, false, false, false,
            true, true, false, false, false, offset == 0 ? 0 : 3, offset / 1000, false, false);
        Need(feature != null, "Cavity cut failed"); feature.Name = name; return feature;
    }
    static object State(ModelDoc2 doc) {
        var bodies = (object[])((PartDoc)doc).GetBodies2((int)swBodyType_e.swSolidBody, false);
        Need(bodies != null && bodies.Length == 1, "Expected one solid prototype body");
        var body = (Body2)bodies[0]; var faultEntities = body.Check3;
        int faults = faultEntities == null ? 0 : faultEntities.Count;
        SwSession.Release(faultEntities);
        Need(faults == 0, "Native body check found faults: " + faults);
        double[] box = Packet.V(body.GetBodyBox());
        var features = new List<object>(); Feature f = (Feature)doc.FirstFeature();
        while (f != null) { features.Add(new { name = f.Name, type = f.GetTypeName2() }); f = (Feature)f.GetNextFeature(); }
        var manager = doc.GetEquationMgr(); var equations = new List<object>();
        for (int i = 0; i < manager.GetCount(); i++)
            equations.Add(new { expression = manager.Equation[i], value = manager.Value[i], status = manager.Status });
        var profiles = new List<object>();
        foreach (Face2 face in (object[])body.GetFaces()) {
            var surface = (Surface)face.GetSurface();
            if (surface.Identity() == 4009 || surface.IsParametric()) profiles.Add(SwReadback.SurfaceData(surface, Packet.V(face.GetUVBounds())));
            SwSession.Release(surface); SwSession.Release(face);
        }
        var mass = (MassProperty2)doc.Extension.CreateMassProperty2();
        mass.UseSystemUnits = true;
        mass.AccuracyLevel = (int)swMassPropertyAccuracyLevel_e.swMassPropertyAccuracyLevel_Higher;
        Need(mass.Recalculate(), "High-accuracy mass-property calculation failed");
        double volume = mass.Volume * 1e9; SwSession.Release(mass);
        return new { body_faults = faults, height_mm = (box[5] - box[2]) * 1000,
            bounds_mm = box.Select(v => v * 1000).ToArray(), volume_mm3 = volume, volume_accuracy_level = 2,
            features = features, equations = equations, extrusion_profiles = profiles };
    }
    static void Save(SldWorks app, ModelDoc2 doc, string path) {
        int errors = 0, warnings = 0;
        Need(doc.Extension.SaveAs(path, 0, 1, null, ref errors, ref warnings), "Native part save failed: " + errors);
        app.CloseDoc(doc.GetTitle());
    }
    static void InspectNative(SldWorks app, string path, string report) {
        string fileHash = Packet.Sha(path);
        int errors = 0, warnings = 0;
        var doc = (ModelDoc2)app.OpenDoc6(path, (int)swDocumentTypes_e.swDocPART,
            (int)swOpenDocOptions_e.swOpenDocOptions_Silent, "", ref errors, ref warnings);
        Need(doc != null, "Native part reopen failed: " + errors);
        var state = State(doc); var geometry = new List<object>();
        var bodies = (object[])((PartDoc)doc).GetBodies2(0, false);
        var modeler = (Modeler)app.GetModeler(); var tolerance = new[] {
            modeler.SetToleranceValue(0, 1e-12), modeler.SetToleranceValue(1, 1e-12), modeler.SetToleranceValue(2, 1e-12) };
        try {
            foreach (Body2 body in bodies) {
                if (path.IndexOf("cone_ring", StringComparison.OrdinalIgnoreCase) >= 0) {
                    var faces = new List<object>();
                    foreach (Face2 face in (object[])body.GetFaces()) {
                        var surface = (Surface)face.GetSurface();
                        faces.Add(new { surface = SwReadback.SurfaceData(surface, Packet.V(face.GetUVBounds())), area_m2 = face.GetArea() });
                        SwSession.Release(surface); SwSession.Release(face);
                    }
                    geometry.Add(new { units = "m", faces = faces, counts = new { faces = body.GetFaceCount(), edges = body.GetEdgeCount() },
                        support_inspection_only = true, volume_m3 = Packet.V(body.GetMassProperties(1))[3] });
                } else geometry.Add(SwReadback.BodyData(body));
            }
            Packet.Write(report, new { file_sha256 = fileHash, implementation_sha256 = ImplementationHash(), native_reopen = true, state = state,
                geometry = geometry, prototype = true, full_release_acceptance = false });
        } finally {
            for (int i = 0; i < 3; i++) modeler.SetToleranceValue(i, tolerance[i]);
            app.CloseDoc(doc.GetTitle());
        }
    }
    static string Circle(ModelDoc2 doc, string name, double radius, Feature plane = null, double[] worldCenter = null) {
        Console.WriteLine("Circle sketch: " + name);
        if (plane == null) BeginSketch(doc, name);
        else {
            doc.ClearSelection2(true); Need(plane.Select2(false, 0), "Vent plane selection failed");
            doc.SketchManager.InsertSketch(true); doc.IFeatureByPositionReverse(0).Name = name;
            Need(doc.SketchManager.ActiveSketch != null, "Vent sketch did not activate");
            doc.SketchManager.AddToDB = true;
            Console.WriteLine("Vent reference feature: " + plane.GetTypeName2());
        }
        double[] xy = new double[] { 0, 0, 0 };
        if (worldCenter != null) {
            var utility = (MathUtility)SwSession.App.GetMathUtility();
            var point = (MathPoint)utility.CreatePoint(worldCenter);
            var transformed = (MathPoint)point.MultiplyTransform(doc.SketchManager.ActiveSketch.ModelToSketchTransform);
            xy = Packet.V(transformed.ArrayData);
            Console.WriteLine("Vent sketch center: " + String.Join(",", xy));
        }
        var segment = doc.SketchManager.CreateCircleByRadius(xy[0], xy[1], 0, radius / 1000);
        Need(segment != null, "Circle creation failed");
        var center = ((SketchArc)segment).IGetCenterPoint2(); center.Select4(false, null); doc.SketchAddConstraints("sgFIXED");
        segment.Select4(false, null);
        var display = (DisplayDimension)doc.AddDiameterDimension2(xy[0] + radius * 1.4 / 1000, xy[1] + radius / 1000, 0);
        Need(display != null, "Circle diameter dimension failed");
        string dimension = display.GetDimension2(0).FullName;
        EndSketch(doc); return String.Join("@", dimension.Split('@').Take(2));
    }
    static void Equation(ModelDoc2 doc, string text) {
        Need(doc.GetEquationMgr().Add2(-1, text, true) >= 0, "Equation rejected: " + text);
    }
    static string DimensionName(Feature feature, double expected) {
        var display = (DisplayDimension)feature.GetFirstDisplayDimension();
        string match = null;
        while (display != null) {
            var dimension = display.GetDimension2(0);
            Console.WriteLine("Feature dimension: " + dimension.FullName + " = " + dimension.SystemValue);
            if (Math.Abs(dimension.SystemValue - expected) < 1e-10) {
                Need(match == null, "Ambiguous feature dimension: " + feature.Name);
                match = String.Join("@", dimension.FullName.Split('@').Take(2));
            }
            display = (DisplayDimension)feature.GetNextDisplayDimension(display);
        }
        Need(match != null, "Expected feature dimension not found: " + feature.Name + ", " + expected);
        return match;
    }
    static object ConeState(ModelDoc2 doc) {
        var state = State(doc); var cones = new List<object>();
        var bodies = (object[])((PartDoc)doc).GetBodies2(0, false);
        foreach (Body2 body in bodies) foreach (Face2 face in (object[])body.GetFaces()) {
            var surface = (Surface)face.GetSurface();
            if (surface.IsCone()) {
                double[] uv = Packet.V(face.GetUVBounds());
                var p = Packet.V(surface.Evaluate((uv[0] + uv[1]) / 2, uv[2] * .75 + uv[3] * .25, 0, 0));
                var q = Packet.V(surface.Evaluate((uv[0] + uv[1]) / 2, uv[2] * .25 + uv[3] * .75, 0, 0));
                double r1 = Math.Sqrt(p[0] * p[0] + p[1] * p[1]), r2 = Math.Sqrt(q[0] * q[0] + q[1] * q[1]);
                double slope = (r2 - r1) / (q[2] - p[2]);
                cones.Add(new { slope = slope, intercept_mm = (r1 - slope * p[2]) * 1000,
                    angle_to_horizontal_degrees = Math.Atan(1 / Math.Abs(slope)) * 180 / Math.PI });
            }
            SwSession.Release(surface); SwSession.Release(face);
        }
        Need(cones.Count == 2, "Expected two analytic cone supports");
        return new { solid = state, cones = cones };
    }
    static Feature VentPlane(ModelDoc2 doc, double radius, double z, double slope) {
        doc.ClearSelection2(true); doc.SketchManager.Insert3DSketch(true);
        var sketch = doc.IFeatureByPositionReverse(0); sketch.Name = "VentPlanePoints";
        double factor = Math.Sqrt(1 + slope * slope); var points = new[] {
            doc.SketchManager.CreatePoint(radius / 1000, 0, z / 1000),
            doc.SketchManager.CreatePoint(radius / 1000, .005, z / 1000),
            doc.SketchManager.CreatePoint(radius / 1000 + .005 * slope / factor, 0, z / 1000 + .005 / factor) };
        doc.ClearSelection2(true); foreach (var point in points) point.Select4(true, null); doc.SketchAddConstraints("sgFIXED");
        doc.SketchManager.Insert3DSketch(true); doc.ClearSelection2(true);
        for (int i = 0; i < 3; i++) Need(points[i].Select2(i > 0, i), "Reference plane point selection failed");
        var reference = doc.FeatureManager.InsertRefPlane(4, 0, 4, 0, 4, 0);
        Need(reference != null, "Normal vent plane creation failed");
        var plane = doc.IFeatureByPositionReverse(0); plane.Name = "ConeNormalVentPlane"; return plane;
    }
    static object Cylinders(ModelDoc2 doc) {
        State(doc); var result = new List<object>();
        var bodies = (object[])((PartDoc)doc).GetBodies2(0, false);
        foreach (Body2 body in bodies) foreach (Face2 face in (object[])body.GetFaces()) {
            var surface = (Surface)face.GetSurface();
            if (surface.IsCylinder()) result.Add(new { parameters = surface.CylinderParams });
            SwSession.Release(surface); SwSession.Release(face);
        }
        return result;
    }
    static void BaseCore(SldWorks app) {
        Console.WriteLine("Studio conical core and circular vent-pattern prototype");
        const double r0 = 76.68363284099085, height = 10, thickness = 1.5;
        double slope = Math.Sqrt(3), span = height - thickness, top = r0 + slope * span;
        var doc = NewPart(app);
        string lowerDiameter = Circle(doc, "LowerCircle", r0);
        var outerCone = Extrude(doc, "OuterConeDraft", span, true, Math.PI / 3);
        string outerDepth = DimensionName(outerCone, span / 1000), outerAngle = DimensionName(outerCone, Math.PI / 3);
        string topDiameter = Circle(doc, "UpperCircle", top);
        var upperPlate = Extrude(doc, "UpperPlate", thickness, false, 0, span);
        string plateDepth = DimensionName(upperPlate, thickness / 1000), plateOffset = DimensionName(upperPlate, span / 1000);
        double inner = r0 + slope * thickness - thickness * Math.Sqrt(1 + slope * slope);
        string innerDiameter = Circle(doc, "InnerCircle", inner);
        var innerCone = Cut(doc, "InnerConeDraft", height - thickness, true, Math.PI / 3, thickness);
        string innerDepth = DimensionName(innerCone, span / 1000), innerAngle = DimensionName(innerCone, Math.PI / 3);
        doc.GetEquationMgr().AngularEquationUnits = (int)swAngularEquationUnits_e.swAngularEquationUnitsDegrees;
        Equation(doc, "\"BaseHeight\" = 10mm"); Equation(doc, "\"PlateThickness\" = 1.5mm"); Equation(doc, "\"ConeAngle\" = 30");
        Equation(doc, "\"LowerRadius\" = 76.68363284099085mm");
        Equation(doc, "\"" + lowerDiameter + "\" = 2 * \"LowerRadius\"");
        Equation(doc, "\"" + outerDepth + "\" = \"BaseHeight\" - \"PlateThickness\"");
        Equation(doc, "\"" + outerAngle + "\" = 90 - \"ConeAngle\"");
        Equation(doc, "\"" + topDiameter + "\" = 2 * (\"LowerRadius\" + (\"BaseHeight\" - \"PlateThickness\") / tan(\"ConeAngle\"))");
        Equation(doc, "\"" + plateDepth + "\" = \"PlateThickness\"");
        Equation(doc, "\"" + plateOffset + "\" = \"BaseHeight\" - \"PlateThickness\"");
        Equation(doc, "\"" + innerDiameter + "\" = 2 * (\"LowerRadius\" + \"PlateThickness\" / tan(\"ConeAngle\") - \"PlateThickness\" / sin(\"ConeAngle\"))");
        Equation(doc, "\"" + innerDepth + "\" = \"BaseHeight\" - \"PlateThickness\"");
        Equation(doc, "\"" + innerAngle + "\" = 90 - \"ConeAngle\"");
        Console.WriteLine("Rebuilding conical core with equations");
        doc.GetEquationMgr().EvaluateAll(); doc.ForceRebuild3(false); var baseline = ConeState(doc);
        doc.GetEquationMgr().Equation[0] = "\"BaseHeight\" = 11mm";
        doc.GetEquationMgr().EvaluateAll(); doc.ForceRebuild3(false); var heightChanged = ConeState(doc);
        doc.GetEquationMgr().Equation[0] = "\"BaseHeight\" = 10mm";
        doc.GetEquationMgr().EvaluateAll(); doc.ForceRebuild3(false);
        doc.GetEquationMgr().Equation[2] = "\"ConeAngle\" = 35";
        doc.GetEquationMgr().EvaluateAll(); doc.ForceRebuild3(false); var angleChanged = ConeState(doc);
        doc.GetEquationMgr().Equation[2] = "\"ConeAngle\" = 30";
        doc.GetEquationMgr().EvaluateAll(); doc.ForceRebuild3(false); var restored = ConeState(doc);
        Console.WriteLine("Conical core angle mutations completed; creating normal vent");
        var plane = VentPlane(doc, r0 + slope * 4.25, 4.25, slope);
        string boreDiameter = Circle(doc, "VentCircle", .75, plane, new[] { (r0 + slope * 4.25) / 1000, 0, .00425 });
        var bore = Cut(doc, "NormalVentSeed", 10, false, 0, 0, true);
        doc.ClearSelection2(true); Plane(doc, 1).Select2(false, 0); Plane(doc, 2).Select2(true, 0);
        Need(doc.InsertAxis2(true), "Circular pattern axis creation failed");
        var axis = doc.IFeatureByPositionReverse(0); axis.Name = "BaseAxis";
        doc.ClearSelection2(true); bore.Select2(false, 4); axis.Select2(true, 1);
        Console.WriteLine("Creating 244-instance circular vent pattern");
        var pattern = doc.FeatureManager.FeatureCircularPattern5(244, Math.PI * 2, false, "", true, true, false, false, false, false, 0, 0, "", true);
        Need(pattern != null, "Circular vent pattern failed"); pattern.Name = "VentRingPattern";
        var cylinders = Cylinders(doc); Console.WriteLine("Checking vent diameter and count mutations");
        ((Dimension)doc.Parameter(boreDiameter)).SystemValue = .0016;
        doc.ForceRebuild3(false); var largerBores = Cylinders(doc);
        ((Dimension)doc.Parameter(boreDiameter)).SystemValue = .0015;
        var data = (CircularPatternFeatureData)pattern.GetDefinition();
        Need(data.AccessSelections(doc, null), "Pattern parameter access failed"); data.TotalInstances = 200;
        Need(pattern.ModifyDefinition(data, doc, null), "Pattern count change failed"); doc.ForceRebuild3(false); var fewerBores = Cylinders(doc);
        data = (CircularPatternFeatureData)pattern.GetDefinition(); Need(data.AccessSelections(doc, null), "Pattern access failed"); data.TotalInstances = 244;
        Need(pattern.ModifyDefinition(data, doc, null), "Pattern count restore failed"); doc.ForceRebuild3(false);
        var final = Cylinders(doc); string path = Path.Combine(output, "mac-studio_cone_ring_prototype.sldprt");
        Save(app, doc, path);
        Packet.Write(Path.Combine(output, "studio_base.parameters.json"), new { prototype = true, implementation_sha256 = ImplementationHash(), baseline = baseline,
            height_11mm = heightChanged, angle_35_degrees = angleChanged, restored = restored, cylinders = cylinders, diameter_1_6mm = largerBores,
            count_200 = fewerBores, final_cylinders = final, limitation = "Core and one representative ring only. Mating G3 plate and vent-plane/angle coupling are not migrated." });
        InspectNative(app, path, Path.Combine(output, "studio_base.native.json"));
    }
    static void Housing(SldWorks app, string model) {
        Console.WriteLine("Housing prototype: " + model);
        double height = model == "mac-mini" ? 43 : 86.5, seedHeight = model == "mac-mini" ? 50 : 95;
        string seedPath = Path.Combine(root, "results", "X_T", model + "_plain-shell_2mm.x_t");
        var manifest = Packet.Read(Path.Combine(root, "validation", "exact-delivery", "20261001T030828560157Z", "manifest.json"));
        var record = Packet.A(manifest["models"]).Select(Packet.D).Single(m =>
            (string)m["family"] == "curve" && (string)m["model"] == model && (string)m["variant"] == "2mm");
        Need(Packet.Sha(seedPath) == (string)Packet.D(Packet.D(record["files"])[".x_t"])["sha256"], "Verified seed hash changed");
        int importError = 0;
        var seedDocument = (ModelDoc2)app.LoadFile4(seedPath, "r", null, ref importError);
        Need(seedDocument != null, "Exact seed import failed: " + importError);
        var imported = State(seedDocument);
        var seedBodies = (object[])((PartDoc)seedDocument).GetBodies2(0, false);
        var copy = ((Body2)seedBodies[0]).Copy();
        var doc = NewPart(app);
        var frozen = (Feature)((PartDoc)doc).CreateFeatureFromBody3(copy, false, 1);
        Need(frozen != null, "Exact body seed insertion failed"); frozen.Name = "FixedG3Master";
        app.CloseDoc(seedDocument.GetTitle());
        var bodies = (object[])((PartDoc)doc).GetBodies2(0, false);
        doc.ClearSelection2(true); int selected = 0;
        var selection = ((SelectionMgr)doc.SelectionManager).CreateSelectData(); selection.Mark = 1;
        foreach (Face2 face in (object[])((Body2)bodies[0]).GetFaces()) {
            var surface = (Surface)face.GetSurface();
            if (surface.IsPlane()) {
                var p = Packet.V(surface.PlaneParams);
                if (Math.Abs(p[0]) < 1e-10 && Math.Abs(p[1]) < 1e-10 && Math.Abs(Math.Abs(p[2]) - 1) < 1e-10
                    && p[5] * 1000 > seedHeight - 2.01) {
                    Need(((Entity)face).Select4(true, selection), "Top plane selection failed"); selected++;
                }
            }
            SwSession.Release(surface);
        }
        Need(selected == 2, "Expected outer top and cavity ceiling planes");
        Need(Plane(doc).Select2(true, 2), "Height translation direction selection failed");
        var move = doc.FeatureManager.InsertMoveFace3((int)swMoveFaceType_e.swMoveFaceTypeTranslate, true,
            0, (seedHeight - height) / 1000, null, null, (int)swEndConditions_e.swEndCondBlind, 0);
        Need(move != null, "Native height translation feature failed"); move.Name = "NativeHeight";
        string moveDimension = DimensionName(move, (seedHeight - height) / 1000);
        var equations = doc.GetEquationMgr();
        Need(equations.Add2(-1, "\"HousingHeight\" = " + height.ToString(System.Globalization.CultureInfo.InvariantCulture) + "mm", true) >= 0, "Height variable rejected");
        Equation(doc, "\"SeedHeight\" = " + seedHeight + "mm");
        Equation(doc, "\"" + moveDimension + "\" = \"SeedHeight\" - \"HousingHeight\"");
        equations.EvaluateAll(); doc.ForceRebuild3(false);
        var baseline = State(doc);
        equations.Equation[0] = "\"HousingHeight\" = " + (height + 2).ToString(System.Globalization.CultureInfo.InvariantCulture) + "mm";
        equations.EvaluateAll(); doc.ForceRebuild3(false); var changed = State(doc);
        equations.Equation[0] = "\"HousingHeight\" = " + height.ToString(System.Globalization.CultureInfo.InvariantCulture) + "mm";
        equations.EvaluateAll(); doc.ForceRebuild3(false); var restored = State(doc);
        string path = Path.Combine(output, model + "_G3_height_prototype.sldprt"); Save(app, doc, path);
        Packet.Write(Path.Combine(output, model + "_housing.parameters.json"), new {
            prototype = true, implementation_sha256 = ImplementationHash(), imported_seed = imported, baseline = baseline, height_plus_2mm = changed, restored = restored,
            editable_parameter = "HousingHeight", fixed_side_wall_mm = 2,
            seed_file = "results/X_T/" + model + "_plain-shell_2mm.x_t", seed_sha256 = Packet.Sha(seedPath),
            source = "docs/technical/geometry_definition.json", source_sha256 = Packet.Sha(Path.Combine(root, "docs/technical/geometry_definition.json")),
            intended_scope = "Frozen verified BREP seed, editable native translation of top and ceiling together; no fitted replacement sketch or side apertures" });
        Console.WriteLine("Saved editable housing; collecting reopened native support definitions");
        string native = Path.Combine(output, model + "_housing.native.json"); InspectNative(app, path, native);
    }
    [STAThread] public static int Main(string[] args) {
        root = Path.GetFullPath(args[0]); output = Path.GetFullPath(args[1]); Directory.CreateDirectory(output);
        bool oldDimensionPrompt = false, dimensionPromptSaved = false;
        Modeler modeler = null; double[] tolerances = null;
        try {
            string mode = args.Length > 2 ? args[2] : "all";
            SwSession.SkipReadback = mode != "base"; SwSession.Begin();
            int prompt = (int)swUserPreferenceToggle_e.swInputDimValOnCreate;
            oldDimensionPrompt = SwSession.App.GetUserPreferenceToggle(prompt); dimensionPromptSaved = true;
            SwSession.App.SetUserPreferenceToggle(prompt, false);
            Need(!SwSession.App.GetUserPreferenceToggle(prompt), "Cannot disable dimension input prompt");
            modeler = (Modeler)SwSession.App.GetModeler();
            tolerances = new[] { modeler.SetToleranceValue(0, 1e-12), modeler.SetToleranceValue(1, 1e-12), modeler.SetToleranceValue(2, 1e-12) };
            if (mode == "all" || mode == "housing")
                foreach (string model in new[] { "mac-mini", "mac-studio" }) Housing(SwSession.App, model);
            if (mode == "all" || mode == "base") BaseCore(SwSession.App);
            return 0;
        } catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally {
            try {
                if (modeler != null && tolerances != null)
                    for (int i = 0; i < 3; i++) modeler.SetToleranceValue(i, tolerances[i]);
                if (dimensionPromptSaved && SwSession.App != null)
                    SwSession.App.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate, oldDimensionPrompt);
            } finally { SwSession.End(); }
        }
    }
}
