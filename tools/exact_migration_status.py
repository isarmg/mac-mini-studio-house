"""Summarize strict receipts, checking their canonical and output file hashes."""
import argparse,datetime,json
from pathlib import Path
from migrate_exact_delivery import ROOT,migration_records,sha,paths


def collect():
    rows=[]
    for row in migration_records():
        item={'key':row['key'],'source':row['source'].as_posix(),'formal_source':row['formal_source'].as_posix(),'formats':{}}
        packet_hash=sha(row['packet']) if row['packet'].exists() else None
        source_hash=sha(ROOT/row['source']) if (ROOT/row['source']).exists() else None
        for engine,ext in [('rhino','.3dm'),('step','.stp'),('parasolid','.x_t')]:
            model,receipt=paths(row,engine)
            state={'passed':False,'receipt':receipt.relative_to(ROOT).as_posix(),'staged_model':model.relative_to(ROOT).as_posix()}
            if receipt.exists():
                try:
                    evidence=json.loads(receipt.read_text(encoding='utf-8'))
                    state['passed']=bool(evidence.get('passed') is True and model.exists()
                        and evidence.get('canonical_sha256')==packet_hash
                        and evidence.get('source_brep_sha256')==source_hash
                        and evidence.get('file_sha256')==sha(model))
                    state['native_readback']=bool(evidence.get('native_readback') or evidence.get('readback_performed'))
                    if evidence.get('error'):state['error']=evidence['error']
                except (ValueError,OSError) as exc:state['error']=str(exc)
            item['formats'][ext]=state
        rows.append(item)
    passed=sum(s['passed'] for r in rows for s in r['formats'].values())
    return {'schema':'strict-migration-status-v1','generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'complete':passed==3*len(rows),'publication_performed':all(r.get('published') for r in migration_records()),'passed_files':passed,'required_files':3*len(rows),
        'by_format':{ext:sum(r['formats'][ext]['passed'] for r in rows) for ext in ('.3dm','.stp','.x_t')},
        'geometry_tolerance_mm':1e-7,'parameter_tolerance':1e-11,'models':rows}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'.tmp/exact-migration/status.json');args=parser.parse_args()
    result=collect();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='models'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
