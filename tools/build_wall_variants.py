"""Build the current 2/3 mm housing variants and their 1.5 mm bases."""
from pathlib import Path
import argparse,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def build(model,thickness):
    from tools.rebuild_bottom_revision import export_stage
    from tools.promote_bottom_revision import publish
    export_stage(model,int(thickness));publish(model,int(thickness))

def main():
    from enclosure import ROOT
    from OCP.OSD import OSD_ThreadPool
    OSD_ThreadPool.DefaultPool_s().Init(4)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=['mac-mini','mac-studio','both'],default='both')
    parser.add_argument('--thickness',type=int,choices=[2,3]);args=parser.parse_args()
    for model in (['mac-mini','mac-studio'] if args.model=='both' else [args.model]):
        for thickness in ([args.thickness] if args.thickness else [2,3]):build(model,thickness)

if __name__=='__main__':main()
