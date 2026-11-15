from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from backend.app.audio_jobs import AudioRequest, conversion_ready, PROJECT


class ConversionTests(unittest.TestCase):
    def test_conversion_requests_require_source_and_reference(self):
        for values in ({'engine':'conversion'}, {'engine':'singing','mode':'design'}):
            with self.assertRaises(ValueError):AudioRequest(idempotency_key='fixture',**values)
        for mode in ('conversion','singing'):
            request=AudioRequest(engine=mode,mode='clone',reference_id='12345678-1234-1234-1234-123456789abc',source_id='12345678-1234-1234-1234-123456789abd',idempotency_key='fixture')
            self.assertEqual(request.engine,mode)

    def test_readiness_requires_verified_mode_current_source_and_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime=Path(temporary)/'runtime';root=Path(temporary)/'models'
            (runtime/'.venv/bin').mkdir(parents=True);(runtime/'.venv/bin/python').touch()
            (runtime/'source').mkdir();(runtime/'source/inference.py').touch()
            (runtime/'source-commit.txt').write_text('pinned-source')
            output=runtime/'fixture.wav';output.write_bytes(b'x'*100)
            (root/'seed-vc').mkdir(parents=True)
            for name in ('DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth','config_dit_mel_seed_uvit_whisper_small_wavenet.yml'):(root/'seed-vc'/name).write_bytes(b'fixture')
            proof=dict(import_ok=True,compute_ok=True,source_commit='pinned-source',modes={'conversion':True},outputs={'conversion':str(output)})
            path=runtime/'probe.json';path.write_text(json.dumps(proof))
            with patch('backend.app.audio_jobs.shutil.which',return_value='/usr/bin/ffmpeg'):
                self.assertTrue(conversion_ready(runtime,root,'conversion'))
                self.assertFalse(conversion_ready(runtime,root,'singing'))
                (runtime/'source-commit.txt').write_text('changed-source')
                self.assertFalse(conversion_ready(runtime,root,'conversion'))

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg is not installed')
    def test_worker_passes_pitch_preserving_flags_and_saves_valid_pcm_without_torchcodec(self):
        import builtins
        for mode in ('conversion','singing'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temporary:
                directory=Path(temporary);source=directory/'runtime/audio-conversion/source';source.mkdir(parents=True)
                job=directory/'job';job.mkdir()
                original=directory/'original.wav'
                def write_wave(path,rate=16000):
                    with wave.open(str(path),'wb') as output:
                        output.setnchannels(1);output.setsampwidth(2);output.setframerate(rate);output.writeframes(b'\x01\x00'*(rate//4))
                write_wave(original)
                request=job/'request.json';request.write_text(json.dumps({'engine':mode}))
                def read_wave(path,**kwargs):
                    with wave.open(str(path)) as value:return [1.0]*value.getnframes(),value.getframerate()
                fake_sound=SimpleNamespace(read=read_wave,write=lambda path,samples,rate,**kwargs:write_wave(path,rate))
                fake_np=SimpleNamespace(isfinite=lambda values:SimpleNamespace(all=lambda:True),abs=lambda values:values,max=builtins.max)
                fake_torch=SimpleNamespace(version=SimpleNamespace(hip='fixture'),cuda=SimpleNamespace(is_available=lambda:True))
                original_save=object();fake_ta=SimpleNamespace(save=original_save)
                spec=importlib.util.spec_from_file_location('conversion_fixture',PROJECT/'scripts/audio_conversion_worker.py')
                worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker);worker.PROJECT=directory
                def infer(*args,**kwargs):
                    flags=sys.argv
                    self.assertEqual(flags[flags.index('--f0-condition')+1],str(mode=='singing'))
                    self.assertEqual(flags[flags.index('--auto-f0-adjust')+1],'False')
                    self.assertEqual(flags[flags.index('--semi-tone-shift')+1],'0')
                    target=job/'converted/fixture.wav'
                    tensor=SimpleNamespace(detach=lambda:SimpleNamespace(cpu=lambda:SimpleNamespace(numpy=lambda:SimpleNamespace(T=[]))))
                    fake_ta.save(target,tensor,44100 if mode=='singing' else 22050)
                arguments=['worker','--request',str(request),'--root',str(directory/'models'),'--directory',str(job),'--reference',str(original),'--source',str(original)]
                with patch.dict(sys.modules,{'torch':fake_torch,'numpy':fake_np,'soundfile':fake_sound,'torchaudio':fake_ta}),patch.object(sys,'argv',arguments),patch('runpy.run_path',side_effect=infer):worker.main()
                self.assertIs(fake_ta.save,original_save)
                with wave.open(str(job/'output.wav')) as output:
                    self.assertGreater(output.getnframes(),0);self.assertEqual(output.getsampwidth(),2)
