"""The single accepted fitted outline definition used by every model family."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROFILE_FILE=ROOT/'data/fitted_profiles.json'

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def profile(model):
    record=json.loads(PROFILE_FILE.read_text(encoding='utf-8'))['profiles'][model]
    if sha(ROOT/record['source_report'])!=record['source_report_sha256']:
        raise ValueError('Accepted fitted-profile source changed')
    if record['degree']!=7 or record['knots']!=[0.0]*8+[1.0]*8 or record['weights']!=[1.0]*8:
        raise ValueError('Expected the accepted degree-seven Bezier quarter')
    return record

def binding(model):
    record=profile(model)
    return {'file':'data/fitted_profiles.json','sha256':sha(PROFILE_FILE),'model':model,
        'source_report':record['source_report'],'source_report_sha256':record['source_report_sha256']}

def verify_definitions(manifest):
    """Check actual canonical extrusion supports, not only parameter labels."""
    rows=[];errors=[]
    for row in manifest['models']:
        if row['family']=='enclosure' and row['part']=='base':continue
        expected=profile(row['model']);cp=expected['controls_mm']
        packet=json.loads((ROOT/row['canonical']['file']).read_text(encoding='utf-8'))
        body=packet['bodies'][0];quadrants=set();maximum=0.0
        for face in body['faces']:
            surface=face['surface']
            if surface.get('type')!='SurfaceOfLinearExtrusion':continue
            definition=surface['basis']['original']
            points=definition.get('poles',[])
            if definition.get('degree')!=7 or len(points)!=8:continue
            if definition.get('multiplicities')!=[8,8] or definition.get('periodic',False):continue
            if len(definition.get('knots',[]))!=2 or max(abs(a-b) for a,b in zip(definition['knots'],[0.,1.]))>1e-11:continue
            if len(definition.get('domain',[]))!=2 or max(abs(a-b) for a,b in zip(definition['domain'],[0.,1.]))>1e-11:continue
            xy=[[abs(p[0]),abs(p[1])] for p in points]
            error=min(max(abs(a-b) for p,q in zip(candidate,cp) for a,b in zip(p,q)) for candidate in (xy,xy[::-1]))
            if error>1e-7:continue
            if max(abs(w-1) for w in definition['weights'])>1e-11:continue
            quadrants.add((points[0][0]>0,points[0][1]>0));maximum=max(maximum,error)
        passed=len(quadrants)==4
        rows.append({'key':row['key'],'passed':passed,'four_outer_quarters_matched':len(quadrants),
            'maximum_control_coordinate_error_mm':maximum if passed else None,'canonical_sha256':row['canonical']['sha256']})
        if not passed:errors.append('Fitted profile differs from the shared definition: '+row['key'])
    return {'passed':not errors,'shared_profile_sha256':sha(PROFILE_FILE),'checked_models':len(rows),
        'method':'Actual canonical extruded-support degree, knots, multiplicities, domain, periodicity, control coordinates and weights compared in all four quadrants; native receipts bind each delivery file to these supports',
        'rows':rows,'errors':errors}
