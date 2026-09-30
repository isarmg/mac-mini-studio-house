"""Read-only inventory of the current hash-bound CAD delivery."""
import json
from exact_publish import verify_manifest
from migrate_exact_delivery import ROOT

if __name__=='__main__':
    result=verify_manifest()
    manifest=json.loads((ROOT/'exact_delivery_manifest.json').read_text(encoding='utf-8'))
    result['files']=[d['file'] for m in manifest['models'] for d in m['files'].values()]
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(not result['passed'])
