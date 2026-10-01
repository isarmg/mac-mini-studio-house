"""Regressions for exact parameter frames and algebraic normalization proofs."""
import copy,json,unittest,tempfile
from pathlib import Path
from exact_verify import *
from exact_topology import line_chain,circle_cycle,carrier_equal

FIXTURE=json.loads((Path(__file__).parent/'testdata/exact_native_circle.json').read_text())

def nurbs(c):return dict(type='BSplineCurve',**spline_data(c))

class ExactMigrationTests(unittest.TestCase):
    def test_step_preserves_normalized_knots_on_real_short_trimmed_span(self):
        from exact_occt import write_step
        d=json.loads((Path(__file__).parent/'testdata/short_trimmed_span.json').read_text())
        c=curve(dict(type='BSplineCurve',**d))
        edge=cq.Edge(BRepBuilderAPI_MakeEdge(c,c.FirstParameter(),c.LastParameter()).Edge())
        folder=ROOT/'.tmp/exact-publication-tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path=Path(temporary)/'short-span.stp';write_step(edge,path)
            native=cq.importers.importStep(str(path)).val().Edges()[0]
            adaptor=BRepAdaptor_Curve(native.wrapped)
            data=curve_data(BRep_Tool.Curve_s(native.wrapped,0.,0.),adaptor.FirstParameter(),adaptor.LastParameter())['nurbs']
            self.assertIsNotNone(curve_equal(dict(type='BSplineCurve',**d),dict(type='BSplineCurve',**data)))

    def test_short_trim_retains_full_support_and_exact_step_parameters(self):
        from exact_transport import short_trim_support
        data=json.loads((Path(__file__).parent/'testdata/short_trimmed_support.json').read_text())
        original=data['edge'];support=short_trim_support(original)
        self.assertIsNotNone(support)
        self.assertLess(support.FirstParameter(),0.)
        self.assertGreater(support.LastParameter(),1.)
        vertices=[]
        for v in data['vertices']:
            vertex=BRepBuilderAPI_MakeVertex(gp_Pnt(*v['point'])).Vertex();BRep_Builder().UpdateVertex(vertex,v['tolerance']);vertices.append(vertex)
        edge=cq.Edge(BRepBuilderAPI_MakeEdge(support,*vertices,0.,1.).Edge())
        folder=ROOT/'.tmp/exact-publication-tests';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder) as temporary:
            path=Path(temporary)/'full-support.stp';write_step(edge,path)
            native=cq.importers.importStep(str(path)).val().Edges()[0];adaptor=BRepAdaptor_Curve(native.wrapped)
            actual=curve_data(BRep_Tool.Curve_s(native.wrapped,0.,0.),adaptor.FirstParameter(),adaptor.LastParameter())['nurbs']
            self.assertIsNotNone(curve_equal(dict(type='BSplineCurve',**original['curve']['nurbs']),dict(type='BSplineCurve',**actual)))

    def test_planar_isocurve_uses_exact_support_despite_pcurve_roundoff(self):
        from exact_boundary import candidates,GeomLib_CheckCurveOnSurface,GeomAdaptor_Curve,GeomAdaptor_Surface,Geom2dAdaptor_Curve,Adaptor3d_CurveOnSurface
        source=json.loads((Path(__file__).parent/'testdata/noisy_planar_isocurve.json').read_text())
        selected=list(candidates(source));self.assertEqual(len(selected),1)
        _,edge,_,face,trim,profile,v=selected[0]
        self.assertEqual(v,-2.0)
        pc=trim['curve'];self.assertGreater(np.ptp(np.array(pc['nurbs']['poles'])[:,1]),1e-10)
        exact=dict(type='BSplineCurve',**pc['nurbs']);exact['poles']=[[p[0],v] for p in exact['poles']]
        checker=GeomLib_CheckCurveOnSurface(GeomAdaptor_Curve(curve(edge['curve']['original']),*edge['curve']['range']),1e-11)
        checker.Perform(Adaptor3d_CurveOnSurface(Geom2dAdaptor_Curve(curve(exact,2),*pc['range']),GeomAdaptor_Surface(surface(face['surface']))))
        self.assertTrue(checker.IsDone());self.assertLessEqual(checker.MaxDistance(),edge['tolerance'])

    def test_periodic_full_span_one_ulp_short_retains_planar_control_data(self):
        from exact_boundary import support_segment
        data=json.loads((Path(__file__).parent/'testdata/periodic_port_endpoint.json').read_text())
        original=curve(data['basis']);trimmed=support_segment(data['basis'],*data['reported_u_bounds'])
        result=spline_data(trimmed)
        self.assertLess(max(abs(p[1]-data['plane_y_mm']) for p in result['poles']),1e-10)
        self.assertTrue(np.all(np.isfinite(result['poles'])))
        for t in np.linspace(original.FirstParameter(),original.LastParameter(),129):
            self.assertLess(original.Value(float(t)).Distance(trimmed.Value(float(t))),1e-9)

    def test_native_circle_uses_edge_parameter_frame(self):
        s=FIXTURE['source_circle'];e=FIXTURE['native_circle'];a=dict(type='BSplineCurve',**s['nurbs'],_original=s['original'],_range=s['range'])
        self.assertIsNotNone(curve_equal(a,native_curve(e['curve'],e)))
        # The Curve interface uses a different phase for this real CAD edge.
        wrong=copy.deepcopy(e);wrong.pop('edge_evaluations')
        self.assertIsNone(curve_equal(a,native_curve(wrong['curve'],wrong)))

    def test_circle_perturbation_is_rejected(self):
        e=copy.deepcopy(FIXTURE['native_circle']);e['edge_evaluations'][2]['point'][0]+=1e-7
        with self.assertRaises(ValueError):native_curve(e['curve'],e)

    def test_degree_elevation_and_knot_insertion_preserve_definition(self):
        original=FIXTURE['g3_surface']['basis']['original'];c=curve(original)
        b=GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(c,c.FirstParameter(),c.LastParameter()));a=nurbs(b);refined=b.Copy();refined.IncreaseDegree(9);refined.InsertKnot(.37,3,1e-12,False)
        self.assertIsNotNone(curve_equal(a,nurbs(refined)))
        pole=refined.Pole(4);refined.SetPole(4,gp_Pnt(pole.X()+1e-4,pole.Y(),pole.Z()))
        self.assertIsNone(curve_equal(a,nurbs(refined)))

    def test_collinear_chain_requires_complete_coverage(self):
        c=G.Geom_Line(gp_Pnt(0,0,0),gp_Dir(1,0,0));s={'edges':[{'vertices':[0,1],'curve':curve_data(c,0,1)},{'vertices':[1,2],'curve':curve_data(c,1,2)}]}
        joined=line_chain(s,[0,1]);self.assertIsNotNone(joined);self.assertEqual(joined[0]['endpoints'],[[0.,0.,0.],[2.,0.,0.]])
        s['edges'][1]['curve']=curve_data(c,1.001,2)
        self.assertIsNone(line_chain(s,[0,1]))

    def test_circular_chain_can_cross_parameter_seam(self):
        c=G.Geom_Circle(gp_Ax2(gp_Pnt(0,0,0),gp_Dir(0,0,1)),2)
        s={'edges':[{'vertices':[0,1],'curve':curve_data(c,-.5,0)},{'vertices':[1,2],'curve':curve_data(c,0,.5)}]}
        result=circle_cycle(s,[0,1]);self.assertIsNotNone(result);self.assertAlmostEqual(result[1]['full_interval'][1]-result[1]['full_interval'][0],1)
        s['edges'][1]['curve']=curve_data(c,.01,.5)
        self.assertIsNone(circle_cycle(s,[0,1]))

    def test_extrusion_carrier_is_not_its_computed_uv_box(self):
        a=copy.deepcopy(FIXTURE['g3_surface']);b=copy.deepcopy(a);b['uv_bounds'][3]+=12
        self.assertIsNotNone(carrier_equal(a,b))
        b['basis']['original']['poles'][3][0]+=1e-4
        self.assertIsNone(carrier_equal(a,b))

    def test_only_periodic_auxiliary_vertices_use_original_tolerance(self):
        s={'vertices':[{'point':[0.,0.,0.],'tolerance':1e-5},{'point':[1.,0.,0.],'tolerance':1e-7}]}
        e={'vertices':[0,1]};n={'start':[8e-10,0.,0.],'end':[.001,0.,0.]}
        with self.assertRaises(ValueError):compare_vertices(s,e,n,set())
        check=compare_vertices(s,e,n,{0});self.assertEqual(len(check['periodic_auxiliary_vertex_normalization']),1)
        n['start'][0]=2e-8
        with self.assertRaises(ValueError):compare_vertices(s,e,n,{0})

if __name__=='__main__':unittest.main()
