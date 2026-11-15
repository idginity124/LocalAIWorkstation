#!/usr/bin/env python3
"""Probe an isolated runtime. Optional smoke synthesis uses local weights only."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

PROJECT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['tts', 'conversion', 'separation'], default='tts')
    parser.add_argument('--device', choices=['rocm', 'cpu'], default='rocm')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--root', type=Path, default=(Path(os.environ.get('AI_WORKSTATION_MODEL_DIR', Path.home() / 'AI/models')).expanduser() / 'audio'))
    args = parser.parse_args()
    output_dir = PROJECT / 'runtime' / f'audio-{args.engine}'
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {'engine': args.engine, 'import_ok': False, 'compute_ok': False, 'smoke_ok': False, 'inference_ready': False}
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_CACHE=str(PROJECT / 'runtime/audio-cache'), GRADIO_ANALYTICS_ENABLED='False', DO_NOT_TRACK='1')
    try:
        import torch
        report.update(torch=torch.__version__, hip=torch.version.hip, python=sys.version.split()[0], device=args.device)
        if args.device == 'rocm' and (not torch.version.hip or not torch.cuda.is_available()):
            raise RuntimeError('AMD ROCm aygıtı erişilebilir değil; CPU’ya sessizce geçilmedi.')
        device = 'cuda:0' if args.device == 'rocm' else 'cpu'
        if args.device == 'rocm':
            report['gpu'] = torch.cuda.get_device_name(0)
        sample = torch.ones((32, 32), device=device)
        value = (sample @ sample).sum().item()
        if value != 32768:
            raise RuntimeError('Temel hesaplama testi başarısız.')
        report['compute_ok'] = True
        if args.engine == 'tts':
            from voxcpm import VoxCPM
            report['package'] = importlib.metadata.version('voxcpm')
        elif args.engine == 'conversion':
            sys.path.insert(0, str(output_dir / 'source'))
            from modules.v2.vc_wrapper import VoiceConversionWrapper
            import hydra
        else:
            import demucs.pretrained
            report['package'] = importlib.metadata.version('demucs')
        report['import_ok'] = True
        if args.smoke:
            memory_info = Path('/proc/meminfo')
            if memory_info.exists():
                available = next((int(line.split()[1]) * 1024 for line in memory_info.read_text().splitlines() if line.startswith('MemAvailable:')), 0)
                report['available_ram_bytes'] = available
                reserve = (8 if args.device == 'rocm' else 10) * 1024**3
                if available < reserve:
                    raise RuntimeError('İlk model testi için kullanılabilir RAM yetersiz; diğer ağır servisleri kapatın.')
            if args.device == 'rocm':
                try:
                    with urlopen('http://127.0.0.1:8000/api/v1/runtime', timeout=5) as response:
                        runtime = json.load(response)
                except (URLError, OSError, ValueError) as error:
                    raise RuntimeError('GPU kaynak kontrolü için yerel uygulamayı başlatın; test modeli yüklenmedi.') from error
                occupied = runtime['gpu'].get('owner') or runtime.get('image', {}).get('managed') or any(item.get('managed') for item in runtime.get('models', []))
                if occupied or runtime['gpu'].get('state') not in {'IDLE', 'UNKNOWN'}:
                    raise RuntimeError('GPU başka bir servis tarafından kullanılıyor; uygulamada önce modeli/görsel servisini durdurun.')
                free_vram, total_vram = torch.cuda.mem_get_info()
                report['free_vram_bytes'] = free_vram
                if free_vram < 8 * 1024**3:
                    raise RuntimeError('İlk test için en az 8 GiB boş VRAM gerekiyor.')
            if args.engine != 'tts':
                raise RuntimeError('Ses dönüşümünün uçtan uca testi için ayrıca kaynak ve referans kayıt gerekir.')
            import numpy as np
            import soundfile as sf
            start = time.monotonic()
            model = VoxCPM.from_pretrained(str(args.root / 'voxcpm2'), load_denoiser=False, local_files_only=True, optimize=False, device=device)
            torch.manual_seed(42)
            wav = model.generate(text='Merhaba. Bu kısa bir ses denemesidir.', normalize=False, denoise=False, inference_timesteps=10, max_len=160, retry_badcase=False)
            wav = np.asarray(wav, dtype=np.float32).reshape(-1)
            sample_rate = int(model.tts_model.sample_rate)
            if len(wav) < sample_rate // 10 or not np.isfinite(wav).all() or float(np.abs(wav).max()) < 1e-6:
                raise RuntimeError('Üretim geçerli bir ses dalgası vermedi.')
            output = output_dir / 'smoke-test.wav'
            sf.write(str(output), wav, sample_rate)
            report.update(smoke_ok=True, inference_ready=True, output=str(output), sample_rate=sample_rate, audio_seconds=len(wav) / sample_rate, elapsed_seconds=round(time.monotonic()-start, 2))
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    (output_dir / 'probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['import_ok'] and (not args.smoke or report['smoke_ok']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
