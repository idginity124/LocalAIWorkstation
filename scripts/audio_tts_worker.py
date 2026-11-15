#!/usr/bin/env python3
"""Single-job VoxCPM2 worker. Model memory is released when this process exits."""
import argparse
import json
import os
from pathlib import Path
import subprocess

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', GRADIO_ANALYTICS_ENABLED='False', DO_NOT_TRACK='1')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    payload = json.loads(args.request.read_text())
    import torch
    import numpy as np
    import soundfile as sf
    from voxcpm import VoxCPM
    if not torch.version.hip or not torch.cuda.is_available():
        raise RuntimeError('The validated AMD GPU is not accessible.')
    languages = {'tr': 'Turkish', 'en': 'English', 'ja': 'Japanese', 'zh': 'Chinese', 'es': 'Spanish', 'fr': 'French', 'de': 'German', 'pt': 'Portuguese', 'ru': 'Russian', 'ar': 'Arabic', 'hi': 'Hindi'}
    styles = {'natural': 'natural delivery', 'calm': 'calm and gentle delivery', 'energetic': 'energetic delivery', 'dramatic': 'dramatic and expressive delivery'}
    guidance = [f"speaking {languages[payload['language']]}", styles[payload['style']]]
    if payload['mode'] == 'design' and payload['description'].strip():
        guidance.append(payload['description'].strip())
    # VoxCPM's CLI disallows control instructions with continuation transcripts.
    has_transcript = bool(args.reference and payload['transcript'].strip())
    text = payload['text'] if has_transcript else '(' + ', '.join(guidance) + ')' + payload['text']
    reference = None
    if args.reference:
        reference = args.directory / 'reference.wav'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'wav,mp3,mov,ogg,flac,matroska,aac', '-i', str(args.reference), '-t', '30', '-vn', '-ac', '1', '-ar', '16000', str(reference)], check=True, timeout=60)
        samples, _ = sf.read(str(reference))
        if len(samples) < 1600 or not np.isfinite(samples).all() or np.abs(samples).max() < 1e-6:
            raise ValueError('Reference audio is empty or silent.')
    model = VoxCPM.from_pretrained(str(args.root / 'voxcpm2'), load_denoiser=False, local_files_only=True, optimize=False, device='cuda:0')
    options = dict(text=text, normalize=False, denoise=False, inference_timesteps=10, retry_badcase=False)
    if reference:
        options['reference_wav_path'] = str(reference)
        if payload['transcript'].strip():
            options.update(prompt_wav_path=str(reference), prompt_text=payload['transcript'].strip())
    torch.manual_seed(42)
    audio = np.asarray(model.generate(**options), dtype=np.float32).reshape(-1)
    rate = int(model.tts_model.sample_rate)
    if len(audio) < rate // 10 or not np.isfinite(audio).all() or np.abs(audio).max() < 1e-6:
        raise RuntimeError('Generation did not return valid audio.')
    sf.write(str(args.directory / 'output.wav'), audio, rate, subtype='PCM_16')


if __name__ == '__main__':
    main()
