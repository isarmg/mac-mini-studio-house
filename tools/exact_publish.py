"""Hash-bound publication with per-file atomic replacement and rollback.

The complete release is NOT a filesystem-wide atomic transaction. A durable
journal and byte-for-byte backups permit recovery after a failed replacement.
No final CAD file is touched until every required native receipt passes.
"""
import argparse,datetime,json,os,shutil,uuid
from pathlib import Path
from migrate_exact_delivery import ROOT,EXTENSIONS,accepted,migration_records,paths,records,sha

def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.incoming-'+uuid.uuid4().hex)
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)

def rel(path):return Path(path).resolve().relative_to(ROOT.resolve()).as_posix()
def file_record(path):return {'file':rel(path),'sha256':sha(path),'bytes':Path(path).stat().st_size}

def current_design_evidence(source):
    """Retain measured stage evidence and replace inherited feature summaries.

    A rebuild reads design inputs from the preceding parameter document, whose
    feature summaries describe the preceding geometry. Those summaries are not
    evidence for the new shape; use the newly measured feature records instead.
    """
    data=json.loads(Path(source).read_text(encoding='utf-8'))
    data['source_stage_metadata_sha256']=sha(source)
    checks=data.get('checks',{});features=data.get('design_parameters',{}).get('features',{})
    for name in ('base_perforations','rear_perforations'):
        if name in checks:features[name]=checks[name]
    artifacts=data.get('feature_artifacts',{})
    if 'uniform_vent_pattern.json' in artifacts:
        pattern=json.loads(artifacts['uniform_vent_pattern.json']);pattern.pop('cutting',None)
        content=json.dumps(pattern,ensure_ascii=False,indent=2)+'\n';artifacts['uniform_vent_pattern.json']=content
        import hashlib
        digest=hashlib.sha256(content.encode('utf-8')).hexdigest();data['pattern_sha256']=digest
        features.setdefault('base_perforations',{}).update(geometry=pattern['geometry'],pattern_sha256=digest)
    return data

class FileTransaction:
    def __init__(self,root,folder):
        self.root=Path(root).resolve();self.folder=Path(folder).resolve();self.entries=[]
        self.folder.relative_to(self.root);self.journal=self.folder/'transaction.json'
    def inside(self,path):
        path=Path(path).resolve();path.relative_to(self.root);return path
    def add(self,source,target):
        source=self.inside(source);target=self.inside(target)
        if any(e['target']==str(target.relative_to(self.root)) for e in self.entries):raise ValueError('Duplicate publication target '+str(target))
        self.entries.append({'source':str(source.relative_to(self.root)),'target':str(target.relative_to(self.root)),
            'new_sha256':sha(source),'old_sha256':sha(target) if target.exists() else None,'installed':False})
    def save(self,state):write(self.journal,{'schema':'exact-publication-transaction-v1','state':state,'root':str(self.root),'entries':self.entries})
    def prepare(self):
        for e in self.entries:
            if e['old_sha256']:
                old=self.root/e['target'];backup=self.folder/'previous'/e['target'];backup.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(old,backup)
                if sha(backup)!=e['old_sha256']:raise ValueError('Rollback backup hash differs')
        self.save('prepared')
    def commit(self):
        self.prepare()
        try:
            for e in self.entries:
                source=self.root/e['source'];target=self.root/e['target']
                if sha(source)!=e['new_sha256']:raise ValueError('Staged file changed after preflight')
                if (sha(target) if target.exists() else None)!=e['old_sha256']:raise ValueError('Formal file changed after preflight')
                target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_name(target.name+'.exact-incoming-'+uuid.uuid4().hex)
                shutil.copy2(source,temp)
                if sha(temp)!=e['new_sha256']:raise ValueError('Incoming copy hash differs')
                os.replace(temp,target);e['installed']=True;self.save('publishing')
            self.save('committed')
        except BaseException:
            self.rollback();raise
    def rollback(self):
        for e in reversed(self.entries):
            target=self.inside(self.root/e['target']);current=sha(target) if target.exists() else None
            if current==e['old_sha256']:continue
            if current!=e['new_sha256']:raise ValueError('Rollback would overwrite a later user edit: '+str(target))
            if e['old_sha256']:
                backup=self.inside(self.folder/'previous'/e['target'])
                if sha(backup)!=e['old_sha256']:raise ValueError('Rollback backup damaged')
                temp=target.with_name(target.name+'.exact-rollback-'+uuid.uuid4().hex);shutil.copy2(backup,temp);os.replace(temp,target)
            elif target.exists():target.unlink()
            e['installed']=False
        self.save('rolled_back')

def verify_manifest(manifest=None):
    manifest=manifest or json.loads((ROOT/'exact_delivery_manifest.json').read_text(encoding='utf-8'))
    errors=[]
    profile_record=manifest.get('shared_profile_definition')
    if profile_record and (not (ROOT/profile_record['file']).is_file() or sha(ROOT/profile_record['file'])!=profile_record['sha256']):
        errors.append('Shared fitted-profile definition changed after publication')
    for descriptor in manifest.get('implementation_snapshot',[]):
        path=ROOT/descriptor['file']
        if not path.is_file() or sha(path)!=descriptor['sha256']:errors.append('Implementation snapshot changed: '+descriptor['file'])
    for row in manifest['models']:
        extra=[row[k] for k in ('source_revision','design_evidence') if k in row]
        for descriptor in [row['canonical'],*row['files'].values(),*row['receipts'].values(),*extra]:
            path=ROOT/descriptor['file']
            if not path.is_file() or sha(path)!=descriptor['sha256']:errors.append('Missing or changed: '+descriptor['file'])
        for engine,proof in row['receipts'].items():
            path=ROOT/proof['file']
            if not path.exists():continue
            d=json.loads(path.read_text(encoding='utf-8'));fmt=EXTENSIONS[engine]
            if not (d.get('passed') is True and (d.get('native_readback') or d.get('readback_performed'))
                    and not d.get('strict_validation_pending',False)
                    and d.get('canonical_sha256')==row['canonical']['sha256']
                    and d.get('source_brep_sha256')==row['source_brep_sha256']
                    and d.get('file_sha256')==row['files'][fmt]['sha256']
                    and (engine!='parasolid' or d.get('topology_passed') is True)):
                errors.append('Acceptance binding differs: '+row['key']+' '+engine)
    from shared_profiles import verify_definitions
    profiles=verify_definitions(manifest);errors.extend(profiles['errors'])
    return {'schema':'strict-publication-verification-v1','passed':not errors,'errors':errors,'shared_profile_check':profiles,
        'models':len(manifest['models']),'usage_files':3*len(manifest['models']),'masters':len(manifest['models'])}

def publish():
    rows=migration_records()
    if len(rows)!=20:raise ValueError('Expected the complete 20-model delivery')
    for row in rows:
        for descriptor in row['files'].values():
            target=ROOT/descriptor['file']
            if descriptor.get('sha256') and (not target.exists() or sha(target)!=descriptor['sha256']):
                raise ValueError('Formal file changed since the accepted baseline: '+descriptor['file'])
        for engine in EXTENSIONS:
            if not accepted(row,engine):raise ValueError('Publication blocked by absent/stale/failed native acceptance: '+row['key']+' '+engine)
        if row.get('source_revision'):
            change=json.loads(row['source_revision'].read_text(encoding='utf-8'))
            if not (change.get('authorized_source_revision') and change.get('valid') and change.get('support_surfaces_unchanged')
                    and change.get('g3_controls_unchanged') and change.get('canonical_sha256')==sha(row['packet'])
                    and change.get('revised_brep_sha256')==sha(ROOT/row['source'])):
                raise ValueError('Source revision approval/proof is absent or stale: '+row['key'])
    if all(r.get('published') for r in rows):
        check=verify_manifest()
        if not check['passed']:raise ValueError(str(check['errors']))
        print('Current publication verified: 20 models, 60 usage files, 20 masters',flush=True);return
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    release=ROOT/'validation/exact-delivery'/stamp;release.mkdir(parents=True)
    tx=FileTransaction(ROOT,release);manifest={'schema':'exact-delivery-manifest-v1','release':stamp,'units':'mm',
        'complete':True,'geometry_tolerance_mm':1e-7,'parameter_tolerance':1e-11,
        'publication_method':'per-file atomic replacements with durable rollback journal',
        'rollback_journal':rel(tx.journal),'models':[]}
    def queue_json(target,data):
        staged=release/'metadata'/rel(target);write(staged,data);tx.add(staged,target);return staged
    folders={}
    for row in rows:
        print('Prepare publication evidence:',row['key'],flush=True)
        evidence=release/'evidence'/row['key'];evidence.mkdir(parents=True)
        packet=evidence/'canonical.geometry.json';shutil.copy2(row['packet'],packet)
        model={'key':row['key'],**{k:row[k] for k in ('family','model','variant','part')},'source_brep_sha256':sha(ROOT/row['source']),'evidence_directory':rel(evidence),
            'canonical':file_record(packet),'files':{},'receipts':{}}
        if row.get('candidate_token'):model['candidate_token']=row['candidate_token']
        source_data=json.loads(packet.read_text(encoding='utf-8'))
        if source_data['provenance']['source_sha256']!=model['source_brep_sha256']:raise ValueError('Canonical master binding differs')
        model['source_geometry']={'bounds_mm':source_data['bounds'],'solids':len(source_data['bodies']),
            'bodies':[{'counts':b['counts'],'g3_connection_count':len(b['g3_seams'])} for b in source_data['bodies']]}
        del source_data
        if row.get('source_revision'):
            revision=evidence/'source_revision.json';shutil.copy2(row['source_revision'],revision);model['source_revision']=file_record(revision)
        if row.get('design_evidence'):
            design=evidence/'procedural-design.json';write(design,current_design_evidence(row['design_evidence']));model['design_evidence']=file_record(design)
        for ext in ('.brep','.3dm','.stp','.x_t'):
            target=ROOT/row['files'][ext]['file']
            if ext=='.brep':source=ROOT/row['source']
            else:source,_=paths(row,next(e for e,x in EXTENSIONS.items() if x==ext))
            model['files'][ext]={'file':rel(target),'sha256':sha(source),'bytes':source.stat().st_size};tx.add(source,target)
        for engine in EXTENSIONS:
            _,receipt=paths(row,engine);archive=evidence/(engine+'.json');shutil.copy2(receipt,archive);model['receipts'][engine]=file_record(archive)
        manifest['models'].append(model);formal=ROOT/row['formal_source'];folders.setdefault(formal.parent,[]).append(model)
        native={'schema':'strict-native-format-acceptance-v1','source':formal.name,'source_sha256':model['source_brep_sha256'],
            'canonical':model['canonical'],'source_step_roundtrip':False,'passed':True,'formats':{}}
        for engine,ext in EXTENSIONS.items():
            native['formats'][engine]={'path':os.path.relpath(ROOT/model['files'][ext]['file'],formal.parent).replace('\\','/'),
                'sha256':model['files'][ext]['sha256'],'passed':True,'native_readback':model['receipts'][engine]}
        queue_json(formal.with_name(formal.stem+'_formats.json'),native)
        queue_json(formal.with_suffix('.native.json'),{'schema':'strict-native-master-v1','file':formal.name,'sha256':model['source_brep_sha256'],
            'origin':'authorized_boundary_revision' if 'source_revision' in model else 'procedural_brep_master',
            'source_step_roundtrip':False,'geometry':model['source_geometry'],'canonical':model['canonical'],'source_revision':model.get('source_revision')})
    for folder,models in folders.items():
        current_paths={Path(m['files']['.brep']['file']).stem:{ext:dict(d,file=os.path.relpath(ROOT/d['file'],folder).replace('\\','/')) for ext,d in m['files'].items()} for m in models}
        queue_json(folder/'delivery_manifest.json',{'schema_version':2,'units':'mm','formal_formats':['.brep','.3dm','.stp','.x_t'],
            'step_suffix':'.stp','current_paths':current_paths,'acceptance_manifest':'exact_delivery_manifest.json'})
        if folder.name.startswith('curve-'):
            path=folder/'parameters.json'
            if path.exists():
                design=models[0].get('design_evidence');d=json.loads((ROOT/design['file'] if design else path).read_text(encoding='utf-8'))
                for field in ('format_roundtrips','previous_format_roundtrips','previous_format_roundtrips_status','feature_artifacts'):d.pop(field,None)
                d.pop('step_and_stp_are_identical_bytes',None);d['format_acceptance']=models[0]['receipts'];d['current_master_sha256']=models[0]['source_brep_sha256']
                d['readback_acceptance_complete']=True
                d['stage']='published after strict native acceptance';queue_json(path,d)
        if not folder.name.startswith('enclosure-'):continue
        by_name={Path(m['files']['.brep']['file']).stem:m for m in models};parts={name:by_name[name] for name in ('housing','base')};assembly=next(m for name,m in by_name.items() if name not in parts)
        master=lambda m:{'file':Path(m['files']['.brep']['file']).name,'sha256':m['source_brep_sha256'],'source_step_roundtrip':False,
            'geometry':m['source_geometry'],'canonical':m['canonical'],'strict_receipts':m['receipts']}
        masters={'schema_version':2,'packaged':True,'units':'mm','parts':{n:master(m) for n,m in parts.items()},
            'assembly':dict(master(assembly),component_order=['housing','base'],component_placement='identity'),
            'embedded_feature_history':False,'acceptance_manifest':'exact_delivery_manifest.json'}
        project=ROOT
        queue_json(folder/'native_sources.json',{'files':[str((ROOT/m['files']['.stp']['file']).relative_to(project)).replace('\\','/') for m in models],
            'native_export_source':'procedural BREP and canonical packet; STEP list is an output inventory'})
        path=folder/'validation.json'
        if path.exists():
            d=json.loads(path.read_text(encoding='utf-8'));d['parts']={n:master(m) for n,m in parts.items()}
            for field in ('historical_parts_geometry','historical_geometry_status','STEP_sha256','native_assembly_master','previous_validation_sha256','preserved_parts_sha256'):d.pop(field,None)
            if assembly.get('design_evidence'):
                design=json.loads((ROOT/assembly['design_evidence']['file']).read_text(encoding='utf-8'))
                d['bottom_revision']=design['checks']
                for field in ('top','profile','inner_profile_offset','rear_perforations','base_perforations'):
                    if field in design['checks']:d[field]=design['checks'][field]
                if 'bottom_plate' in d and 'plate_to_housing_contour_max_error_mm' in design['checks']:
                    d['bottom_plate']['outer_to_housing_inner_max_error_mm']=design['checks']['plate_to_housing_contour_max_error_mm']
                for name,content in design.get('feature_artifacts',{}).items():
                    if name not in ('uniform_vent_pattern.json','base_hole_axes.csv','rear_hole_axes.csv'):raise ValueError('Unexpected feature artifact')
                    if name=='uniform_vent_pattern.json':
                        pattern=json.loads(content);pattern.pop('cutting',None)
                        content=json.dumps(pattern,ensure_ascii=False,indent=2)+'\n'
                    staged=release/'metadata'/rel(folder/name);staged.parent.mkdir(parents=True,exist_ok=True);staged.write_text(content,encoding='utf-8');tx.add(staged,folder/name)
                    if name=='uniform_vent_pattern.json':d['base_perforations'].update(pattern_file=name,pattern_sha256=sha(staged),geometry=pattern['geometry'])
            d['strict_receipts']={Path(m['files']['.brep']['file']).stem:m['receipts'] for m in models}
            d['current_native_assembly_master']=master(assembly);d['readback_acceptance_complete']=True;validation_staged=queue_json(path,d)
            parameters=folder/'model_parameters.json'
            if parameters.exists():
                params=design['design_parameters'] if assembly.get('design_evidence') and design.get('design_parameters') else json.loads(parameters.read_text(encoding='utf-8'))
                params['validation_sha256']=sha(validation_staged)
                for field in ('base_perforations','rear_perforations'):
                    if field in d:params.setdefault('features',{})[field]=d[field]
                for name,content in design.get('feature_artifacts',{}).items() if assembly.get('design_evidence') else []:
                    if name.endswith('.csv'):params['hole_axis_tables'][name]={'file':name,'sha256':sha(release/'metadata'/rel(folder/name))}
                params['reconstruction_code_sha256']={p:sha(project/p) for p in params.get('reconstruction_code_sha256',{}) if (project/p).is_file()}
                params['strict_delivery_pipeline']='tools/migrate_exact_delivery.py';staged_params=queue_json(parameters,params)
                masters['parameters']={'file':parameters.name,'sha256':sha(staged_params)}
        queue_json(folder/'native_masters.json',masters)
    base=ROOT/'results'
    queue_json(base/'native_sources.json',{'files':[m['files']['.stp']['file'] for m in manifest['models']],
        'native_export_source':'procedural BREP and canonical packet'})
    queue_json(base/'native_formats.json',{'schema':'strict-native-formats-index-v1','passed':True,'sources':[
        {'source':m['files']['.brep']['file'],'source_sha256':m['source_brep_sha256'],'formats':m['receipts']} for m in manifest['models']]})
    from shared_profiles import verify_definitions
    consistency=verify_definitions(manifest)
    if not consistency['passed']:raise ValueError(str(consistency['errors']))
    implementation=[]
    design_scripts=[ROOT/'tools'/name for name in ('audit_base_geometry.py','audit_mini_capsules.py','audit_studio_final.py')]
    for source in sorted((ROOT/'tools').glob('exact_*.py'))+sorted((ROOT/'tools/exact_native').glob('*'))+[ROOT/'tools/migrate_exact_delivery.py',ROOT/'tools/data/studio_short_arc_revision.json',ROOT/'tools/audit_delivery.py']+design_scripts:
        if not source.is_file():continue
        implementation.append({'source_file':rel(source),'sha256':sha(source),'bytes':source.stat().st_size})
    for source in [ROOT/'tools/shared_profiles.py',ROOT/'project.py',ROOT/'data/fitted_profiles.json']:
        implementation.append({'source_file':rel(source),'sha256':sha(source),'bytes':source.stat().st_size})
    manifest['shared_profile_definition']=file_record(ROOT/'data/fitted_profiles.json')
    manifest['acquisition_implementation_fingerprints']=implementation
    audit={'schema_version':2,'acceptance_standard':'exact native definitions and G3','passed':True,'complete':True,'pending':[],
        'units':'mm','formal_shape_count':20,'files_per_shape':['.brep','.3dm','.stp','.x_t'],'strict_manifest':'exact_delivery_manifest.json',
        'shapes':[{'step':m['files']['.stp']['file'],'expected_solids':m['source_geometry']['solids'],'files':m['files'],'strict_receipts':m['receipts']} for m in manifest['models']],'errors':[]}
    queue_json(ROOT/'delivery_catalog.json',{'schema_version':1,'shapes':[{**{k:r[k] for k in ('family','model','variant','part')},'files':{e:{'file':f['file']} for e,f in r['files'].items()}} for r in records()]})
    queue_json(ROOT/'delivery_audit.json',audit)
    queue_json(ROOT/'delivery_file_status.json',{'check_type':'hash-bound strict native acceptance','all_required_files_present':True,
        'formal_shape_count':20,'file_count':80,'readback_acceptance_complete':True,'missing':[],'record_errors':[],'shapes':audit['shapes']})
    # Manifest is replaced last, so readers never see a new complete release
    # before its usage files and evidence are in place.
    queue_json(ROOT/'exact_delivery_manifest.json',manifest)
    write(release/'manifest.json',manifest);tx.commit()
    check=verify_manifest(manifest);write(release/'publication_verification.json',check)
    if not check['passed']:tx.rollback();raise ValueError(str(check['errors']))
    print('Published and hash-verified: 20 models, 60 usage files, 20 masters. Rollback: '+rel(tx.journal),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify',action='store_true');parser.add_argument('--rollback',type=Path);args=parser.parse_args()
    if args.rollback:
        journal=args.rollback.resolve();data=json.loads(journal.read_text(encoding='utf-8'));tx=FileTransaction(ROOT,journal.parent);tx.entries=data['entries'];tx.rollback();print('Rolled back',journal)
    elif args.verify:
        result=verify_manifest();print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(not result['passed'])
    else:publish()

if __name__=='__main__':main()
