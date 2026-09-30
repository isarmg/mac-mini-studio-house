"""Unified G3 fitting, CAD generation, native export and acceptance entry point."""
import argparse,subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def run(*args):
    environment=os.environ.copy();environment['PYTHONDONTWRITEBYTECODE']='1'
    subprocess.run([sys.executable,'-B',*args],cwd=ROOT,env=environment,check=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    verify=commands.add_parser('verify');verify.add_argument('--refresh-design-audits',action='store_true')
    build=commands.add_parser('build');build.add_argument('--family',choices=['all','curve','enclosure'],default='all')
    build.add_argument('--model',choices=['mac-mini','mac-studio','both'],default='both');build.add_argument('--thickness',choices=['2','3'])
    commands.add_parser('export');commands.add_parser('fit-check');commands.add_parser('files')
    args=parser.parse_args()
    if args.command=='verify':run('tools/audit_delivery.py',*(['--refresh-design-audits'] if args.refresh_design_audits else []))
    elif args.command=='files':run('tools/list_delivery_files.py')
    elif args.command=='fit-check':run('-m','macfit','verify');run('-m','macfit','integrity')
    elif args.command=='export':run('tools/migrate_exact_delivery.py','--engine','all','--publish')
    else:
        if args.family in ('all','curve'):run('tools/build_nominal_solids.py','--model',args.model,'--replace')
        if args.family in ('all','enclosure'):run('tools/build_wall_variants.py','--model',args.model,*(['--thickness',args.thickness] if args.thickness else []))
        run('tools/audit_delivery.py','--refresh-design-audits')

if __name__=='__main__':main()
