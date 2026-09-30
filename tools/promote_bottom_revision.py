"""Publish a rebuilt enclosure only after exact three-format native acceptance."""
import argparse,json,sys
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT
sys.path.insert(0,str(ROOT/'tools'))

def publish(model,thickness):
    from exact_candidates import deliver
    from migrate_exact_delivery import sha
    label=f'{thickness}mm';stage=PROJECT/'.tmp/bottom-revision-stage'/model/label
    target=PROJECT/'results/masters'/model/('enclosure-'+label)
    proof=json.loads((stage/'stage_validation.json').read_text(encoding='utf-8'))
    if not proof.get('passed') or proof['parts']!=['housing','base'] or proof['assembly_solid_count']!=2:
        raise ValueError('Procedural enclosure stage is incomplete')
    names=['housing','base',f'{model}_housing_{label}'];sources={}
    for name in names:
        source=stage/(name+'.brep')
        if sha(source)!=proof['changed_file_sha256'][source.name]:raise ValueError('Staged procedural BREP changed')
        sources[(target/source.name).relative_to(ROOT).as_posix()]=source.relative_to(ROOT).as_posix()
    deliver(sources)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model',choices=['mac-mini','mac-studio'],required=True)
    parser.add_argument('--thickness',type=int,choices=[2,3],required=True);args=parser.parse_args();publish(args.model,args.thickness)
