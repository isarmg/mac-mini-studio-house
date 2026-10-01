"""Verify current native receipts plus hash-bound enclosure design audits."""
import argparse,json,subprocess,sys
from pathlib import Path
from migrate_exact_delivery import ROOT,sha
from exact_publish import verify_manifest,file_record,write

def collect():
    result=verify_manifest();design=[];errors=list(result['errors'])
    for model in ('mac-mini','mac-studio'):
        for thickness in (2,3):
            folder=ROOT/'results/masters'/model/f'enclosure-{thickness}mm'
            for name in ('base_geometry_audit.json','mini_opening_interface_audit.json' if model=='mac-mini' else 'studio_final_audit.json'):
                path=folder/name
                if not path.is_file():errors.append('Missing design audit '+str(path));continue
                d=json.loads(path.read_text(encoding='utf-8'));valid=d.get('passed') is True
                if name=='base_geometry_audit.json':valid=valid and d.get('base_brep_sha256')==sha(folder/'base.brep') and d.get('housing_brep_sha256')==sha(folder/'housing.brep') and d.get('design_requirements_sha256')==sha(ROOT/'data/enclosure_design.json')
                else:
                    valid=valid and all(d.get('input_hashes',{}).get(part)==sha(folder/(part+'.brep')) for part in ('housing','base'))
                    if model=='mac-mini':valid=valid and d.get('validation_sha256')==sha(folder/'validation.json') and d.get('uniform_vent_pattern_sha256')==sha(folder/'uniform_vent_pattern.json') and d.get('parameters_sha256')==sha(folder/'model_parameters.json')
                    else:valid=valid and d.get('port_count')==14 and d.get('base_hole_through_topology',{}).get('accepted_holes')==1952 and d.get('wrapped_rear_grid',{}).get('hole_count')==2309 and d.get('wrapped_rear_grid',{}).get('passed') is True and d.get('horizontal_base_rings',{}).get('passed') is True and d.get('base_hole_table_sha256')==sha(folder/'base_hole_axes.csv') and d.get('rear_hole_table_sha256')==sha(folder/'rear_hole_axes.csv') and d.get('parameters_sha256')==sha(folder/'model_parameters.json') and d.get('validation_sha256')==sha(folder/'validation.json')
                if not valid:errors.append('Stale or failed design audit '+str(path.relative_to(ROOT)))
                design.append(dict(file_record(path),passed=bool(valid)))
    result.update(passed=not errors,complete=not errors,errors=errors,design_audits=design);return result

def refresh_design_audits():
    project=ROOT
    for model in ('mac-mini','mac-studio'):
        for thickness in (2,3):
            commands=[['tools/audit_base_geometry.py',model,str(thickness)]]
            commands.append(['tools/audit_mini_capsules.py','--thickness',str(thickness)] if model=='mac-mini'
                else ['tools/audit_studio_final.py',str(thickness)])
            for command in commands:
                print('DESIGN AUDIT',model,thickness,' '.join(command),flush=True)
                subprocess.run([sys.executable,*command],cwd=project,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-design-audits',action='store_true',help='Measure current formal geometry and opening paths before verifying the release')
    args=parser.parse_args()
    if not (ROOT/'exact_delivery_manifest.json').exists():
        from exact_migration_status import collect as status
        result=status();print(json.dumps({k:v for k,v in result.items() if k!='models'},ensure_ascii=False,indent=2));raise SystemExit('Strict release is not yet published')
    if args.refresh_design_audits:
        preflight=verify_manifest()
        if not preflight['passed']:raise ValueError(str(preflight['errors']))
        refresh_design_audits()
    result=collect();write(ROOT/'exact_release_check.json',result)
    if result['passed']:
        audit=json.loads((ROOT/'delivery_audit.json').read_text(encoding='utf-8'));audit.update(passed=True,complete=True,design_audits=result['design_audits'],strict_release_check='exact_release_check.json')
        write(ROOT/'delivery_audit.json',audit)
    print(json.dumps({k:v for k,v in result.items() if k!='design_audits'},ensure_ascii=False,indent=2));raise SystemExit(not result['passed'])

if __name__=='__main__':main()
