"""Stage exact definitions, read every final format natively, then publish.

STEP and Rhino are reconstructed from a shared exact packet. Parasolid uses
either the Rhino native writer or a verified STEP transport; acceptance always
reads the final X_T directly. Assemblies copy verified native component bodies.
"""
import argparse,json,subprocess,sys,hashlib,shutil,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'.tmp/exact-migration/staging'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def records():
    result=[]
    catalog=ROOT/'delivery_catalog.json'
    for row in json.loads(catalog.read_text(encoding='utf-8'))['shapes']:
        source=Path(row['files']['.brep']['file']);key=source.as_posix().replace('/','__').removesuffix('.brep')
        result.append({'key':key,'source':source,'files':row['files'],**{k:row[k] for k in ('family','model','variant','part')},'stage':STAGE/key,'packet':ROOT/'.tmp/exact-migration/packets'/(key+'.geometry.json')})
    return result

def migration_records():
    """Select staged candidates or accepted masters with formal output paths."""
    result=records()
    published_path=ROOT/'exact_delivery_manifest.json'
    published={r['key']:r for r in json.loads(published_path.read_text(encoding='utf-8'))['models']} if published_path.exists() else {}
    candidates_path=ROOT/'.tmp/exact-migration/candidates.json'
    candidates=json.loads(candidates_path.read_text(encoding='utf-8')) if candidates_path.exists() else {}
    for row in result:
        row['formal_source']=row['source']
        released=published.get(row['key'])
        if released:
            if sha(ROOT/row['source'])!=released['source_brep_sha256']:raise ValueError('Published master changed outside staged rebuild: '+row['key'])
            row.update(packet=ROOT/released['canonical']['file'],stage=ROOT/released['evidence_directory'],published=True,
                files=released['files'],
                outputs={e:ROOT/d['file'] for e,d in released['files'].items() if e!='.brep'},
                receipts={e:ROOT/d['file'] for e,d in released['receipts'].items()})
            if released.get('source_revision'):row['source_revision']=ROOT/released['source_revision']['file']
            if released.get('design_evidence'):row['design_evidence']=ROOT/released['design_evidence']['file']
        candidate=candidates.get(row['key'])
        if candidate and (not released or candidate.get('prepared_at_utc')!=released.get('candidate_token')):
            if candidate['formal_base_sha256']!=sha(ROOT/row['formal_source']):raise ValueError('Candidate was prepared against a different formal master: '+row['key'])
            row.update(source=Path(candidate['source']),packet=ROOT/candidate['packet'],stage=ROOT/candidate['stage'],published=False,candidate_token=candidate.get('prepared_at_utc'))
            row.pop('outputs',None);row.pop('receipts',None)
            row.pop('source_revision',None)
            row.pop('design_evidence',None)
            if candidate.get('revision'):row['source_revision']=ROOT/candidate['revision']
            if candidate.get('design_evidence'):row['design_evidence']=ROOT/candidate['design_evidence']
    return result

EXTENSIONS={'step':'.stp','rhino':'.3dm','parasolid':'.x_t'}

def packet_provenance(packet):
    # The exporter writes provenance before the potentially hundreds of MB of
    # body data. Native adapters need only this binding in the coordinator.
    with Path(packet).open(encoding='utf-8') as stream:head=stream.read(65536)
    start=head.index('"provenance"');start=head.index(':',start)+1
    return json.JSONDecoder().raw_decode(head[start:].lstrip())[0]

def paths(row,engine):
    return (row.get('outputs',{}).get(EXTENSIONS[engine],row['stage']/('model'+EXTENSIONS[engine])),
            row.get('receipts',{}).get(engine,row['stage']/(engine+'.json')))

def accepted(row,engine):
    output,receipt=paths(row,engine)
    if not all(p.is_file() for p in (output,receipt,row['packet'],ROOT/row['source'])):return False
    data=json.loads(receipt.read_text(encoding='utf-8'))
    return bool(data.get('passed') is True and (data.get('native_readback') or data.get('readback_performed'))
        and not data.get('strict_validation_pending',False)
        and data.get('canonical_sha256')==sha(row['packet'])
        and data.get('source_brep_sha256')==sha(ROOT/row['source']) and data.get('file_sha256')==sha(output)
        and (engine!='parasolid' or data.get('topology_passed') is True))

def native_job(row,action,input_path,output,receipt):
    script=ROOT/'tools/exact_native/run_sw_inprocess.ps1'
    cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-Action',action,
         '-InputGeometry',str(input_path),'-OutputModel',str(output),'-Report',str(receipt)]
    logfile=row['stage']/(receipt.stem+'.log')
    with logfile.open('w',encoding='utf-8') as log:
        proc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    if proc.returncode:raise RuntimeError('In-process native adapter failed; '+str(logfile))

def run_parasolid(row,output,receipt,verify_existing=False):
    if verify_existing and output.exists():native_job(row,'inspect',row['packet'],output,receipt)
    elif row['family']=='curve':
        script=ROOT/'tools/exact_native/run_rhino.ps1'
        subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-InputGeometry',str(row['packet']),
            '-OutputModel',str(output),'-Report',str(row['stage']/'parasolid-export.json'),'-WriteParasolid'],check=True)
        native_job(row,'inspect',row['packet'],output,receipt)
    elif row['part'] in ('housing','base'):
        from exact_transport import run
        transport=row['stage']/'transport.stp';proof=row['stage']/'transport.json'
        valid=False
        if transport.exists() and proof.exists():
            data=json.loads(proof.read_text(encoding='utf-8'))
            valid=data.get('passed') and data.get('canonical_sha256')==sha(row['packet']) and data.get('file_sha256')==sha(transport) and 'algebraic_parameter_rebases' in data
        if not valid:run(row['packet'],transport,proof)
        native_job(row,'transfer',transport,output,receipt)
    else:
        prefix=row['key'].rsplit('__',1)[0];inputs=[]
        for label in ['housing','base']:
            part=next(r for r in migration_records() if r['key']==prefix+'__'+label)
            run_engine(part,'parasolid');model,proof=paths(part,'parasolid')
            if not accepted(part,'parasolid'):raise ValueError('Unaccepted native assembly component '+part['key'])
            inputs.append({'path':str(model),'label':label,'sha256':sha(model),'receipt_sha256':sha(proof),'canonical_sha256':sha(part['packet'])})
        manifest=row['stage']/'native-components.json';manifest.write_text(json.dumps({'inputs':inputs,'assembly_canonical_sha256':sha(row['packet'])}),encoding='utf-8')
        native_job(row,'compose',manifest,output,receipt)
    from exact_verify import verify_sw
    verify_sw(row['packet'],receipt)

def run_engine(row,engine,force=False,verify_existing=False):
    if row.get('published') and force:raise ValueError('Published evidence is immutable; prepare a staged source candidate before forcing regeneration')
    out=row['stage'];out.mkdir(parents=True,exist_ok=True);packet=row['packet']
    if not packet.exists():
        from exact_geometry import export
        export(ROOT/row['source'],packet)
    native_files={'rhino':['Packet.cs','RhinoExact.cs','run_rhino.ps1'],'parasolid':['Packet.cs','SwSession.cs','SwExact.cs','SwReadback.cs','SwInspectionAddin.cs','SwInspectionHost.cs','run_sw_inprocess.ps1','RhinoExact.cs','run_rhino.ps1'],'step':[]}[engine]
    code_files=[ROOT/'tools/exact_native'/p for p in native_files]
    if engine!='rhino':code_files += [ROOT/'tools'/p for p in ['exact_geometry.py','exact_occt.py','exact_verify.py','exact_topology.py','exact_transport.py']]
    code_hash=hashlib.sha256(''.join(sha(p) for p in sorted(code_files)).encode()).hexdigest()
    output,receipt=paths(row,engine)
    if not force and accepted(row,engine):print('Verified cache:',row['key'],engine,flush=True);return
    if row.get('published'):raise ValueError('Published receipt/output is damaged; prepare a new staged candidate before repair')
    if engine=='step':source=json.loads(packet.read_text(encoding='utf-8'));provenance=source['provenance']
    else:provenance=packet_provenance(packet)
    assert provenance['source_sha256']==sha(ROOT/row['source']),'Canonical source drift'
    print('START',engine,row['key'],flush=True)
    if engine=='step':
        from exact_occt import build,cq,write_step
        from exact_verify import verify_step
        if not (verify_existing and output.exists()):write_step(build(source,bounded_edges=True),output)
        del source
        verify_step(packet,output,receipt)
    elif engine=='parasolid':run_parasolid(row,output,receipt,verify_existing)
    else:
        script=ROOT/'tools/exact_native/run_rhino.ps1'
        with (out/(engine+'.log')).open('w',encoding='utf-8') as log:
            proc=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-InputGeometry',str(packet),'-OutputModel',str(output),'-Report',str(receipt)],stdout=log,stderr=subprocess.STDOUT)
        if proc.returncode:raise RuntimeError('Native adapter failed; '+str(out/(engine+'.log')))
    record=json.loads(receipt.read_text(encoding='utf-8'));assert record.get('passed') is True,'Acceptance not complete'
    record.update(canonical_sha256=sha(packet),source_brep_sha256=sha(ROOT/row['source']),file_sha256=sha(output),adapter_sha256=code_hash,accepted_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    receipt.write_text(json.dumps(record,separators=(',',':')),encoding='utf-8');print('PASS',engine,row['key'],flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',choices=['all','step','rhino','parasolid'],default='all');p.add_argument('--match',default='');p.add_argument('--force',action='store_true');p.add_argument('--verify-existing',action='store_true');p.add_argument('--publish',action='store_true');p.add_argument('--publish-only',action='store_true');p.add_argument('--source-map',type=Path,help='JSON mapping formal BREP paths to staged procedural BREP candidates');a=p.parse_args();failures=[]
    if a.source_map:
        from exact_candidates import prepare
        prepare(json.loads(a.source_map.read_text(encoding='utf-8')))
    for row in ([] if a.publish_only else migration_records()):
        if a.match not in row['key']:continue
        try:
            for engine in (['step','rhino','parasolid'] if a.engine=='all' else [a.engine]):run_engine(row,engine,a.force,a.verify_existing)
        except Exception as e:failures.append({'key':row['key'],'error':str(e)});print('FAIL',row['key'],repr(e),flush=True)
    status={'engine':a.engine,'failures':failures,'passed':not failures};STAGE.mkdir(parents=True,exist_ok=True);(STAGE/(a.engine+'-batch.json')).write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    if not failures and (a.publish or a.publish_only):
        from exact_publish import publish
        publish()
    raise SystemExit(bool(failures))

if __name__=='__main__':main()
