"""A locked correction for the known Studio cone/cylinder short chord.

This is an explicit source revision, never a conversion acceptance exception.
Every final output must still match the revised full curve definition at 1e-7
mm. Support surfaces, vertices, edge tolerances and G3 controls are unchanged.
"""
from exact_verify import *
from OCP.GeomProjLib import GeomProjLib
from OCP.GeomLib import GeomLib_CheckCurveOnSurface
from OCP.GeomAdaptor import GeomAdaptor_Curve,GeomAdaptor_Surface
from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
from OCP.Adaptor3d import Adaptor3d_CurveOnSurface
from OCP.gp import gp_Vec2d

RECIPE=Path(__file__).parent/'data/studio_short_arc_revision.json'

def apply(source,created,builder):
    from exact_boundary import definition_roundoff,support_definition
    recipe=json.loads(RECIPE.read_text(encoding='utf-8'));result=[]
    for ei,e in enumerate(source['edges']):
        if e['curve']['original']['type']!='BSplineCurve' or e['curve']['original']['degree']!=1:continue
        try:definition_roundoff(e['curve']['original'],recipe['original_curve'],'locked short chord')
        except ValueError:continue
        need(e['curve']['range']==recipe['original_range'],'Locked short-chord interval changed')
        need(abs(e['tolerance']-recipe['original_edge_tolerance_mm'])<1e-12,'Locked short-chord tolerance changed')
        uses=[(fi,f,t) for fi,f in enumerate(source['faces']) for l in f['loops'] for t in l['trims'] if t['edge']==ei]
        need(len(uses)==2,'Short chord is not a two-face manifold edge')
        supports={s['type']:s for s in recipe['support_definitions']}
        for _,f,_ in uses:
            sd=support_definition(f['surface']);need(sd['type'] in supports,'Short chord supports changed')
            definition_roundoff(sd,supports[sd['type']],'locked short-chord support')
        c=curve(recipe['replacement_curve']);lo,hi=recipe['replacement_range'];edge=created['edges'][ei]
        # Full-domain numerical displacement proof, including parameterization.
        line2=curve({'type':'BSplineCurve','degree':1,'poles':[[lo,0.],[hi,0.]],'weights':[1.,1.],
            'knots':[0.,1.],'multiplicities':[2,2],'periodic':False},2)
        comparison=G.Geom_SurfaceOfLinearExtrusion(c,gp_Dir(*recipe['replacement_curve']['z']))
        checker=GeomLib_CheckCurveOnSurface(GeomAdaptor_Curve(curve(e['curve']['original']),*e['curve']['range']),1e-12)
        checker.Perform(Adaptor3d_CurveOnSurface(Geom2dAdaptor_Curve(line2,0.,1.),GeomAdaptor_Surface(comparison)))
        need(checker.IsDone() and checker.ErrorStatus()==0,'Short-chord displacement calculation failed')
        displacement=checker.MaxDistance();allowance=recipe['replacement_distance_numerical_allowance_mm']
        need(displacement<=e['tolerance']+allowance,'Short-chord correction exceeds its locked displacement budget')
        builder.UpdateEdge(edge,c,e['tolerance']);builder.Range(edge,lo,hi,True);checks=[]
        for fi,f,t in uses:
            support=surface(f['surface']);pc=GeomProjLib.Curve2d_s(c,lo,hi,support,1e-10);need(pc is not None,'Short arc projection failed')
            old_mid=curve(t['curve']['original'],2).Value(sum(t['curve']['range'])/2);new_mid=pc.Value((lo+hi)/2)
            if support.IsUPeriodic():pc.Translate(gp_Vec2d(round((old_mid.X()-new_mid.X())/support.UPeriod())*support.UPeriod(),0))
            checker=GeomLib_CheckCurveOnSurface(GeomAdaptor_Curve(c,lo,hi),1e-12)
            checker.Perform(Adaptor3d_CurveOnSurface(Geom2dAdaptor_Curve(pc,lo,hi),GeomAdaptor_Surface(support)))
            need(checker.IsDone() and checker.ErrorStatus()==0 and checker.MaxDistance()<=e['tolerance'],'Short arc leaves the unchanged support tolerance')
            face=TopoDS.Face_s(created['faces'][fi]);builder.UpdateEdge(edge,pc,face,e['tolerance']);builder.Range(edge,face,lo,hi)
            checks.append({'face':fi,'type':f['surface']['type'],'maximum_curve_on_support_error_mm':checker.MaxDistance()})
        builder.SameRange(edge,True);builder.SameParameter(edge,True)
        result.append({'edge':ei,'old_degree':1,'new_type':'Circle','recipe_sha256':sha(RECIPE),'support_surfaces_changed':False,
            'original_edge_tolerance_mm':e['tolerance'],'computed_max_deviation_mm':displacement,
            'deviation_exceeds_original_tolerance_mm':max(0.,displacement-e['tolerance']),
            'source_revision_distance_numerical_allowance_mm':allowance,'support_checks':checks,
            'note':'Old-to-new displacement and curve-on-surface residual are separate quantities; original edge tolerance is not enlarged.'})
        print('Locked short-arc revision',ei,'displacement_mm',displacement,flush=True)
    return result
