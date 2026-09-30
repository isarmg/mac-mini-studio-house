"""Run independent design checks against the current published native masters."""
from pathlib import Path
import argparse,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def run(*args):subprocess.run([sys.executable,'-X','utf8',*args],cwd=ROOT,check=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('model',choices=['mac-mini','mac-studio']);parser.add_argument('--thickness',type=int,choices=[2,3]);a=parser.parse_args()
    for t in ([a.thickness] if a.thickness else [2,3]):
        run('tools/audit_base_geometry.py',a.model,str(t))
        if a.model=='mac-mini':run('tools/audit_mini_capsules.py','--thickness',str(t))
        else:run('tools/audit_studio_final.py',str(t))
