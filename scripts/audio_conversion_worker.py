#!/usr/bin/env python3
"""Offline Seed-VC CLI adapter for speech or pitch-preserving singing conversion."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import runpy

PROJECT=Path(__file__).resolve().parents[1]
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',GRADIO_ANALYTICS_ENABLED='False',DO_NOT_TRACK='1')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    args=parser.parse_args()
    args.directory=args.directory.resolve()
    args.root=args.root.resolve()
    args.source=args.source.resolve(strict=True)
    args.reference=args.reference.resolve(strict=True)
    import torch
    import numpy as np
    import soundfile as sf
    if not torch.version.hip or not torch.cuda.is_available():raise RuntimeError('AMD GPU is not accessible.')
    payload=json.loads(args.request.read_text())
    singing=payload['engine']=='singing'
    rate=44100 if singing else 22050
    for name,input_path,seconds in [('source',args.source,601),('reference',args.reference,30)]:
        target=args.directory/(name+'.wav')
        subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-protocol_whitelist','file,pipe','-format_whitelist','wav,mp3,mov,ogg,flac,matroska,aac','-i',str(input_path),'-t',str(seconds),'-vn','-ac','1','-ar',str(rate),str(target)],check=True,timeout=90)
        samples,_=sf.read(target)
        if len(samples)<rate//10 or not np.isfinite(samples).all() or np.max(np.abs(samples))<1e-6:raise ValueError('The recording is empty or silent.')
        if name=='source' and len(samples)>rate*600:raise ValueError('Source recording must be at most 10 minutes.')
    source=PROJECT/'runtime/audio-conversion/source'
    basename='DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth' if singing else 'DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth'
    config='config_dit_mel_seed_uvit_whisper_base_f0_44k.yml' if singing else 'config_dit_mel_seed_uvit_whisper_small_wavenet.yml'
    output=args.directory/'converted';output.mkdir()
    # Modern torchaudio.save requires TorchCodec. Keep the upstream inference
    # unchanged and write its final tensor through the installed SoundFile codec.
    import torchaudio
    original_save=torchaudio.save
    def save_wave(filename, tensor, sample_rate, **kwargs):
        sf.write(filename, tensor.detach().cpu().numpy().T, sample_rate, subtype='PCM_16')
    torchaudio.save=save_wave
    sys.path.insert(0,str(source))
    sys.argv=[str(source/'inference.py'),'--source',str(args.directory/'source.wav'),'--target',str(args.directory/'reference.wav'),'--output',str(output),'--checkpoint',str(args.root/'seed-vc'/basename),'--config',str(args.root/'seed-vc'/config),'--diffusion-steps','30','--length-adjust','1.0','--inference-cfg-rate','0.7','--f0-condition',str(singing),'--auto-f0-adjust','False','--semi-tone-shift','0','--fp16','True']
    original_directory=Path.cwd()
    try:
        os.chdir(source)
        runpy.run_path(str(source/'inference.py'),run_name='__main__')
    finally:
        torchaudio.save=original_save
        os.chdir(original_directory)

    files=list(output.glob('*.wav'))
    if len(files)!=1:raise RuntimeError('Conversion did not produce one audio file.')
    samples,output_rate=sf.read(files[0],dtype='float32')
    if not len(samples) or not np.isfinite(samples).all():raise RuntimeError('Conversion returned invalid audio.')
    sf.write(args.directory/'output.wav',samples,output_rate,subtype='PCM_16')
    files[0].unlink();output.rmdir()

if __name__=='__main__':main()
