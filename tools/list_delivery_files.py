"""Read-only inventory of the current hash-bound CAD delivery."""
import hashlib,json
from exact_publish import verify_manifest
from migrate_exact_delivery import ROOT

if __name__=='__main__':
    result=verify_manifest()
    manifest=json.loads((ROOT/'exact_delivery_manifest.json').read_text(encoding='utf-8'))
    result['files']=[d['file'] for m in manifest['models'] for d in m['files'].values()]
    native_path=ROOT/'validation/solidworks-native/acceptance.json'
    if native_path.is_file():
        native=json.loads(native_path.read_text(encoding='utf-8'))
        files=[]
        for record in native['parts']+native['assemblies']:
            path=ROOT/'results/SW'/record['file']
            valid=path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==record['sha256']
            files.append({'file':path.relative_to(ROOT).as_posix(),'hash_matches':valid})
        result['solidworks_native']={'passed':native['passed'] and len(files)==20 and all(f['hash_matches'] for f in files),'files':files}
        result['passed']=result['passed'] and result['solidworks_native']['passed']
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(not result['passed'])
