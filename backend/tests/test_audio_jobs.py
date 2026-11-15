import ast
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from contextlib import closing
import unittest
from unittest.mock import patch, Mock
from uuid import uuid4
import wave

from backend.app.audio_jobs import AudioJobs, AudioRunner, AudioRequest, AudioCancelled, tts_ready, PROJECT
from backend.app.jobs import JobRepository
from backend.app.storage import open_database


class FakeRunner:
    def __init__(self, data):
        self.data = data
        self.references = data / 'references'
        self.references.mkdir(parents=True)
        self.gpu = SimpleNamespace(state='IDLE')
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.ready = True

    def available(self):
        return self.ready

    reference_path = AudioRunner.reference_path

    def run(self, identifier, payload, cancel):
        self.calls += 1
        self.entered.set()
        while not self.release.wait(.01):
            if cancel.is_set():
                raise AudioCancelled('Cancelled')
        directory = self.data / identifier
        directory.mkdir()
        with wave.open(str(directory / 'output.wav'), 'wb') as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(48000)
            sound.writeframes(b'\x01\x00' * 4800)
        return {'filename':'fixture.wav', 'seconds':.1, 'sample_rate':48000, 'bytes':9644, 'url':f'/api/v1/audio/jobs/{identifier}/output'}


class AudioJobTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.db = self.base / 'jobs.sqlite3'
        self.runner = FakeRunner(self.base / 'audio')
        self.jobs = AudioJobs(self.db, self.runner)
        self.addCleanup(self.jobs.close)

    def wait_finished(self, identifier):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.jobs.active_job_id is None:
                return self.jobs.get(identifier)
            time.sleep(.01)
        self.fail('Job did not finish')

    def test_idempotent_request_runs_once_and_persists_playable_result(self):
        request = AudioRequest(text='Hello', idempotency_key='same')
        job = self.jobs.submit(request)
        self.assertTrue(self.runner.entered.wait(1))
        self.assertEqual(self.jobs.submit(request)['id'], job['id'])
        with self.assertRaises(ValueError):
            self.jobs.submit(AudioRequest(text='Changed', idempotency_key='same'))
        with self.assertRaises(RuntimeError):
            self.jobs.submit(AudioRequest(text='Other', idempotency_key='different'))
        self.runner.release.set()
        completed = self.wait_finished(job['id'])
        self.assertEqual(completed['status'], 'COMPLETED')
        self.assertEqual(self.runner.calls, 1)
        with wave.open(str(self.jobs.output_path(job['id']))) as sound:
            self.assertEqual(sound.getnframes(), 4800)
        restarted = AudioJobs(self.db, self.runner)
        try:
            self.assertEqual(restarted.get(job['id'])['result'], completed['result'])
        finally:
            restarted.close()

    def test_cancel_cleans_reference_and_blocks_output(self):
        reference = str(uuid4())
        path = self.runner.reference_path(reference)
        path.write_bytes(b'reference fixture')
        job = self.jobs.submit(AudioRequest(text='Hello', mode='clone', reference_id=reference, idempotency_key='cancel'))
        self.assertTrue(self.runner.entered.wait(1))
        self.jobs.cancel(job['id'])
        self.assertEqual(self.wait_finished(job['id'])['status'], 'INTERRUPTED')
        self.assertFalse(path.exists())
        with self.assertRaises(KeyError):
            self.jobs.output_path(job['id'])

    def test_requires_ready_engine_and_existing_reference(self):
        self.runner.ready = False
        with self.assertRaises(RuntimeError):
            self.jobs.submit(AudioRequest(text='Hello', idempotency_key='unready'))
        self.runner.ready = True
        with self.assertRaises(ValueError):
            self.jobs.submit(AudioRequest(text='Hello', mode='clone', reference_id=str(uuid4()), idempotency_key='missing'))
        for identifier in ('../../secret', 'not-a-uuid'):
            with self.assertRaises(ValueError):
                self.runner.reference_path(identifier)
        identifier = str(uuid4())
        self.runner.reference_path(identifier).symlink_to(self.db)
        with self.assertRaises(ValueError):
            self.runner.reference_path(identifier)

    def test_restart_marks_inflight_audio_without_resubmitting_or_touching_other_modules(self):
        with closing(open_database(self.db)) as db:
            audio, _ = JobRepository(db).enqueue('audio', {'text':'Interrupted'}, 'restart-audio')
            image, _ = JobRepository(db).enqueue('image', {}, 'restart-image')
        restarted = AudioJobs(self.db, self.runner)
        try:
            self.assertEqual(restarted.get(audio.id)['status'], 'RECOVERY_REQUIRED')
            with closing(open_database(self.db)) as db:
                self.assertEqual(db.execute('SELECT status FROM jobs WHERE id=?', (image.id,)).fetchone()[0], 'QUEUED')
            self.assertEqual(self.runner.calls, 0)
        finally:
            restarted.close()

    def test_readiness_requires_successful_local_gpu_output(self):
        runtime, root = self.base / 'runtime', self.base / 'models'
        (runtime / '.venv/bin').mkdir(parents=True)
        (runtime / '.venv/bin/python').touch()
        (root / 'voxcpm2').mkdir(parents=True)
        for name in ('model.safetensors','audiovae.pth','config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','tokenization_voxcpm2.py'):
            (root / 'voxcpm2' / name).write_bytes(b'fixture')
        output = runtime / 'smoke.wav'
        output.write_bytes(b'x' * 100)
        proof = dict(engine='tts', device='rocm', import_ok=True, compute_ok=True, smoke_ok=True, inference_ready=True, output=str(output))
        with patch('backend.app.audio_jobs.shutil.which', return_value='/usr/bin/ffmpeg'):
            for key in ('smoke_ok','inference_ready'):
                (runtime / 'probe.json').write_text(json.dumps({**proof, key:False}))
                self.assertFalse(tts_ready(runtime, root))
            (runtime / 'probe.json').write_text(json.dumps(proof))
            self.assertTrue(tts_ready(runtime, root))
            (runtime / 'probe.json').write_text(json.dumps({**proof, 'output':str(self.db)}))
            self.assertFalse(tts_ready(runtime, root))

    def test_runner_releases_gpu_and_removes_inputs_after_worker_failure(self):
        gpu = Mock(state='RUNNING')
        async def acquire(*args):
            return 'test-lease'
        async def release(lease):
            self.assertEqual(lease, 'test-lease')
        gpu.acquire.side_effect = acquire
        gpu.release_and_verify.side_effect = release
        runner = AudioRunner(self.base / 'models', self.base / 'worker', gpu)
        reference_id = str(uuid4())
        reference = runner.reference_path(reference_id)
        reference.write_bytes(b'fixture')
        identifier = str(uuid4())
        payload = AudioRequest(text='Hello', mode='clone', reference_id=reference_id, idempotency_key='worker').model_dump()
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with patch('backend.app.audio_jobs._meminfo_kib', return_value={'MemAvailable':16*1024**2}), patch('backend.app.audio_jobs.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'generation failed'):
                runner.run(identifier, payload, threading.Event())
        gpu.acquire.assert_called_once()
        gpu.release_and_verify.assert_called_once()
        self.assertFalse(reference.exists())
        self.assertFalse((runner.data / identifier / 'request.json').exists())

    def test_worker_matches_installed_voxcpm_generate_parameters(self):
        source = PROJECT / 'runtime/audio-tts/.venv/lib/python3.12/site-packages/voxcpm/core.py'
        if not source.exists():
            self.skipTest('Optional installed TTS runtime is absent')
        installed = ast.parse(source.read_text())
        signature = next(node for node in ast.walk(installed) if isinstance(node, ast.FunctionDef) and node.name == '_generate')
        accepted = {arg.arg for arg in signature.args.args}
        worker = ast.parse((PROJECT / 'scripts/audio_tts_worker.py').read_text())
        options = next(node.value for node in ast.walk(worker) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'options' for target in node.targets))
        self.assertTrue({kw.arg for kw in options.keywords} <= accepted)
        self.assertTrue({'reference_wav_path','prompt_wav_path','prompt_text'} <= accepted)
        self.assertNotIn('seed', {kw.arg for kw in options.keywords})


if __name__ == '__main__':
    unittest.main()
