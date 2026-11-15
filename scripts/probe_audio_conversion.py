#!/usr/bin/env python3
"""Verify speech/singing conversion with user-selected recordings and local weights."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import wave
from urllib.request import urlopen

PROJECT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['conversion','singing'],required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--root',type=Path,default=(Path(os.environ.get('AI_WORKSTATION_MODEL_DIR', Path.home() / 'AI/models')).expanduser() / 'audio'))
    args=parser.parse_args()
    runtime=PROJECT/'runtime/audio-conversion'
    commit=(runtime/'source-commit.txt').read_text().strip()
    proof={'engine':'conversion','source_commit':commit,'modes':{},'outputs':{}}
    path=runtime/'probe.json'
    if path.is_file():
        old=json.loads(path.read_text())
        if old.get('source_commit')==commit:proof.update(old)
    directory=runtime/('validation-'+args.mode);directory.mkdir(exist_ok=True)
    try:
        import torch
        if not torch.version.hip or not torch.cuda.is_available():raise RuntimeError('AMD GPU is not accessible.')
        with urlopen('http://127.0.0.1:8000/api/v1/runtime',timeout=5) as response:status=json.load(response)
        if status['gpu'].get('owner') or status['gpu']['state'] not in {'IDLE','UNKNOWN'}:raise RuntimeError('Stop other GPU services first.')
        free,_=torch.cuda.mem_get_info()
        if free<8*1024**3:raise RuntimeError('At least 8 GiB of free VRAM is required.')
        if (torch.ones((32,32),device='cuda')@torch.ones((32,32),device='cuda')).sum().item()!=32768:raise RuntimeError('GPU compute test failed.')
        request=directory/'request.json';request.write_text(json.dumps({'engine':args.mode}))
        subprocess.run([sys.executable,str(PROJECT/'scripts/audio_conversion_worker.py'),'--request',str(request),'--root',str(args.root.resolve()),'--directory',str(directory),'--source',str(args.source.resolve(strict=True)),'--reference',str(args.reference.resolve(strict=True))],check=True,timeout=1800,env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'})
        output=directory/'output.wav'
        with wave.open(str(output)) as sound:
            if not sound.getnframes():raise RuntimeError('Conversion produced empty audio.')
        proof.update(import_ok=True,compute_ok=True,smoke_ok=True,inference_ready=True,device='rocm')
        proof['modes'][args.mode]=True;proof['outputs'][args.mode]=str(output)
        proof.pop('error',None)
    except Exception as error:
        proof['modes'][args.mode]=False;proof['error']=str(error)
    finally:
        for name in ('request.json','reference.wav','source.wav'):(directory/name).unlink(missing_ok=True)
    path.write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,indent=2))
    return 0 if proof['modes'].get(args.mode) else 1

if __name__=='__main__':raise SystemExit(main())
