"""Freeze rebuilt procedural BREP candidates without overwriting deliverables."""
import json,shutil,datetime
from pathlib import Path
from migrate_exact_delivery import ROOT,records,sha,migration_records,accepted,EXTENSIONS


def published_component(row):
    """Reuse an unchanged component only with its intact native acceptance."""
    if not row.get('published') or not all(accepted(row,engine) for engine in EXTENSIONS):
        raise ValueError('Assembly component is not an intact published model: '+row['key'])
    return {'source':row['source'].as_posix(),'source_sha256':sha(ROOT/row['source']),
            'packet':row['packet'].relative_to(ROOT).as_posix(),
            'preserved_published_component':True,'revision':None}

def prepare(source_map):
    from exact_geometry import export,cq
    from exact_boundary import revise,definition_roundoff,need
    rows=records();by_source={str((ROOT/r['source']).resolve()):r for r in rows}
    selected={};prepared={};original_packets={};preserved={}
    available={r['key']:r for r in migration_records()}
    for target,source in source_map.items():
        formal=(ROOT/target).resolve();candidate=(ROOT/source).resolve()
        formal.relative_to(ROOT);candidate.relative_to(ROOT)
        if str(formal) not in by_source:raise ValueError('Source map target is outside the formal 20-model catalog: '+target)
        row=by_source[str(formal)];selected[row['key']]=(row,candidate)
    for key,(row,source) in selected.items():
        if row['family']=='enclosure' and row['part']=='assembly':
            prefix=key.rsplit('__',1)[0]
            for label in ('housing','base'):
                component=prefix+'__'+label
                if component not in selected:
                    need(component in available,'Assembly component is missing: '+component)
                    preserved[component]=published_component(available[component])
    ordered=sorted(selected,key=lambda k:selected[k][0]['family']=='enclosure' and selected[k][0]['part']=='assembly')
    for key in ordered:
        row,candidate=selected[key];out=ROOT/'.tmp/exact-migration/candidates'/key/sha(candidate)
        out.mkdir(parents=True,exist_ok=True);raw=out/'procedural.brep';shutil.copy2(candidate,raw)
        source_packet=out/'procedural.geometry.json';export(raw,source_packet);original_packets[key]=source_packet
        revision=None
        if row['family']=='enclosure' and row['part'] in ('housing','base'):
            revision=out/'revision.json';revise(source_packet,out/'model.brep',revision)
            data=json.loads(revision.read_text(encoding='utf-8'))
            if data['changes']:source=out/'model.brep';packet=out/'model.geometry.json'
            else:source=raw;packet=source_packet;revision=None
        elif row['family']=='enclosure':
            prefix=key.rsplit('__',1)[0];before=json.loads(source_packet.read_text(encoding='utf-8'));parts=[];components=[];changes=[]
            need(len(before['bodies'])==2,'Assembly requires exactly two component bodies')
            for bi,label in enumerate(('housing','base')):
                component=prefix+'__'+label
                part=prepared[component] if component in prepared else preserved[component]
                original=original_packets.get(component,ROOT/part['packet'])
                old=json.loads(original.read_text(encoding='utf-8'))
                definition_roundoff(before['bodies'][bi],old['bodies'][0],'procedural assembly component '+label)
                parts.extend(cq.Shape.importBrep(str(ROOT/part['source'])).Solids());components.append(part)
                if part.get('revision'):
                    change=json.loads((ROOT/part['revision']).read_text(encoding='utf-8'));changes.extend(dict(c,body=bi) for c in change['changes'])
            del before
            source=out/'model.brep';packet=out/'model.geometry.json';cq.Compound.makeCompound(parts).exportBrep(str(source));combined=export(source,packet)
            for bi,part in enumerate(components):
                definition=json.loads((ROOT/part['packet']).read_text(encoding='utf-8'));definition_roundoff(definition['bodies'][0],combined['bodies'][bi],'revised component '+str(bi))
            del combined
            revision=out/'revision.json';revision.write_text(json.dumps({'authorized_source_revision':True,'valid':True,'source_brep':raw.relative_to(ROOT).as_posix(),
                'source_brep_sha256':sha(raw),'revised_brep_sha256':sha(source),'canonical_sha256':sha(packet),
                'support_surfaces_unchanged':True,'g3_controls_unchanged':True,'component_transforms_changed':False,'components':components,'changes':changes}),encoding='utf-8')
        else:source=raw;packet=source_packet
        prepared[key]={'source':source.relative_to(ROOT).as_posix(),'source_sha256':sha(source),'packet':packet.relative_to(ROOT).as_posix(),
            'stage':out.relative_to(ROOT).as_posix(),'formal_base_sha256':sha(ROOT/row['source']),
            'prepared_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'revision':revision.relative_to(ROOT).as_posix() if revision else None}
        design=next((candidate.parent/n for n in ('parameters.json','stage_validation.json') if (candidate.parent/n).is_file()),None)
        if design:
            frozen=out/'procedural-design.json'
            evidence=json.loads(design.read_text(encoding='utf-8'))
            feature_names=('uniform_vent_pattern.json','base_hole_axes.csv','rear_hole_axes.csv')
            evidence['feature_artifacts']={name:(candidate.parent/name).read_text(encoding='utf-8') for name in feature_names if (candidate.parent/name).is_file()}
            if 'uniform_vent_pattern.json' in evidence['feature_artifacts']:
                pattern=json.loads(evidence['feature_artifacts']['uniform_vent_pattern.json']);pattern.pop('cutting',None)
                evidence['feature_artifacts']['uniform_vent_pattern.json']=json.dumps(pattern,ensure_ascii=False,indent=2)+'\n'
            frozen.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            prepared[key]['design_evidence']=frozen.relative_to(ROOT).as_posix()
        print('Prepared exact candidate',key,flush=True)
    path=ROOT/'.tmp/exact-migration/candidates.json';existing=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    existing.update(prepared);temp=path.with_suffix('.incoming.json');temp.write_text(json.dumps(existing,indent=2),encoding='utf-8');temp.replace(path)
    return prepared

def deliver(source_map):
    prepare(source_map)
    from migrate_exact_delivery import migration_records,run_engine
    targets={str((ROOT/p).resolve()) for p in source_map}
    for row in migration_records():
        if str((ROOT/row['formal_source']).resolve()) not in targets:continue
        for engine in ('step','rhino','parasolid'):run_engine(row,engine)
    from exact_publish import publish
    publish()
