"""Persistent, cancellable local TTS jobs sharing the application's GPU lease."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import wave
from uuid import uuid4
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from .hardware import _meminfo_kib
from .jobs import JobRepository
from .resources import GpuResourceManager
from .storage import open_database

PROJECT = Path(__file__).resolve().parents[2]
ID_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
ACTIVE = ('QUEUED', 'PREPARING', 'RUNNING', 'CANCELLING', 'CLEANUP')


class AudioRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    engine: Literal['tts','conversion','singing'] = 'tts'
    text: str = Field(default='', max_length=8000)
    source_id: str | None = Field(default=None, pattern=ID_PATTERN)
    mode: Literal['clone', 'design'] = 'design'
    description: str = Field(default='', max_length=1000)
    language: Literal['tr','en','ja','zh','es','fr','de','pt','ru','ar','hi'] = 'tr'
    style: Literal['natural','calm','energetic','dramatic'] = 'natural'
    reference_id: str | None = Field(default=None, pattern=ID_PATTERN)
    transcript: str = Field(default='', max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode='after')
    def reference_for_clone(self):
        if self.engine == 'tts' and not self.text:
            raise ValueError('Text is required.')
        if self.engine != 'tts' and (not self.reference_id or not self.source_id or self.mode != 'clone'):
            raise ValueError('Source and reference recordings are required.')
        if self.engine == 'tts' and self.source_id:
            raise ValueError('Source audio is only supported for conversion.')
        if self.mode == 'clone' and not self.reference_id:
            raise ValueError('A voice profile is required for cloning.')
        return self


def tts_ready(runtime: Path, root: Path) -> bool:
    try:
        proof = json.loads((runtime / 'probe.json').read_text())
        output = Path(proof['output']).resolve()
        return bool(proof.get('engine') == 'tts' and proof.get('device') == 'rocm' and proof.get('import_ok') and proof.get('compute_ok') and proof.get('smoke_ok') and proof.get('inference_ready') and output.is_relative_to(runtime.resolve()) and output.is_file() and output.stat().st_size > 44 and (runtime / '.venv/bin/python').is_file() and all((root / 'voxcpm2' / name).is_file() for name in ('model.safetensors','audiovae.pth','config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','tokenization_voxcpm2.py')) and shutil.which('ffmpeg'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def conversion_ready(runtime: Path, root: Path, mode: str) -> bool:
    try:
        proof=json.loads((runtime/'probe.json').read_text())
        output=Path(proof['outputs'][mode]).resolve()
        commit=(runtime/'source-commit.txt').read_text().strip()
        weights = ('DiT_seed_v2_uvit_whisper_base_f0_44k_bigvgan_pruned_ft_ema_v2.pth','config_dit_mel_seed_uvit_whisper_base_f0_44k.yml') if mode=='singing' else ('DiT_seed_v2_uvit_whisper_small_wavenet_bigvgan_pruned.pth','config_dit_mel_seed_uvit_whisper_small_wavenet.yml')
        if not all((root/'seed-vc'/name).is_file() and (root/'seed-vc'/name).stat().st_size for name in weights):return False
        return bool(proof.get('import_ok') and proof.get('compute_ok') and proof.get('modes',{}).get(mode) and proof.get('source_commit')==commit and output.is_relative_to(runtime.resolve()) and output.is_file() and output.stat().st_size>44 and (runtime/'.venv/bin/python').is_file() and (runtime/'source/inference.py').is_file() and shutil.which('ffmpeg'))
    except (OSError,ValueError,TypeError,KeyError):
        return False


class AudioCancelled(RuntimeError):
    pass


class AudioRunner:
    def __init__(self, root: Path, data: Path, gpu: GpuResourceManager):
        self.root = root
        self.data = data
        self.runtime = PROJECT / 'runtime/audio-tts'
        self.references = data / 'references'
        self.references.mkdir(parents=True, exist_ok=True)
        self.log_path = data / 'audio.log'
        self.gpu = gpu

    def available(self, engine='tts'):
        if engine == 'tts':
            return tts_ready(self.runtime, self.root)
        return conversion_ready(PROJECT/'runtime/audio-conversion', self.root, engine)

    def reference_path(self, identifier: str) -> Path:
        if not re.fullmatch(ID_PATTERN, identifier):
            raise ValueError('Invalid reference identifier.')
        path = self.references / identifier
        if path.is_symlink():
            raise ValueError('Invalid reference path.')
        return path

    def run(self, job_id: str, payload: dict, cancel: threading.Event) -> dict:
        if _meminfo_kib().get('MemAvailable', 0) * 1024 < 8 * 1024**3:
            raise RuntimeError('At least 8 GiB of available RAM is required.')
        directory = self.data / job_id
        directory.mkdir(exist_ok=True)
        request = directory / 'request.json'
        request.write_text(json.dumps(payload, ensure_ascii=False))
        engine=payload.get('engine','tts')
        runtime=self.runtime if engine=='tts' else PROJECT/'runtime/audio-conversion'
        worker='audio_tts_worker.py' if engine=='tts' else 'audio_conversion_worker.py'
        command = [str(runtime / '.venv/bin/python'), str(PROJECT / 'scripts' / worker), '--request', str(request), '--root', str(self.root), '--directory', str(directory)]
        reference_id = payload.get('reference_id') if payload['mode'] == 'clone' else None
        if reference_id:
            command += ['--reference', str(self.reference_path(reference_id))]
        if payload.get('source_id'):
            command += ['--source', str(self.reference_path(payload['source_id']))]
        lease = None
        process = None
        try:
            if cancel.is_set():
                raise AudioCancelled('Generation cancelled.')
            lease = asyncio.run(self.gpu.acquire('audio-' + job_id, 8 * 1024**3))
            with self.log_path.open('ab') as log:
                log.write(f'\nAudio job {job_id}\n'.encode()); log.flush()
                process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1', 'HF_HUB_DISABLE_TELEMETRY':'1', 'GRADIO_ANALYTICS_ENABLED':'False'})
                started = time.monotonic()
                while process.poll() is None:
                    if cancel.wait(.2):
                        raise AudioCancelled('Generation cancelled.')
                    if time.monotonic() - started > 1800:
                        raise RuntimeError('Audio generation timed out.')
                if cancel.is_set():
                    raise AudioCancelled('Generation cancelled.')
                if process.returncode:
                    raise RuntimeError('Audio generation failed. Check service logs.')
            output = directory / 'output.wav'
            with wave.open(str(output)) as sound:
                frames, rate = sound.getnframes(), sound.getframerate()
                if not frames or not rate:
                    raise RuntimeError('Generated audio is empty.')
            return {'filename': f'voice-{job_id[:8]}.wav', 'url': f'/api/v1/audio/jobs/{job_id}/output', 'sample_rate': rate, 'seconds': frames / rate, 'bytes': output.stat().st_size}
        finally:
            try:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
            finally:
                if lease is not None:
                    if process is not None and process.poll() is None:
                        (directory/'keep-inputs').touch()
                        self.gpu.require_recovery('Audio worker could not be stopped.')
                    else:
                        asyncio.run(self.gpu.release_and_verify(lease))
                if reference_id:
                    self.reference_path(reference_id).unlink(missing_ok=True)
                (directory / 'reference.wav').unlink(missing_ok=True)
                request.unlink(missing_ok=True)


class AudioJobs:
    def __init__(self, database_path: Path, runner: AudioRunner):
        self.path, self.runner = database_path, runner
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='audio-job')
        self._active = None
        self._closed = False
        self._uploads: set[str] = set()
        self._cancel = threading.Event()
        with self._db() as db:
            db.execute("UPDATE jobs SET status='RECOVERY_REQUIRED' WHERE module='audio' AND status IN ('QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP')")

    @contextmanager
    def _db(self):
        db = open_database(self.path)
        try:
            yield db
        finally:
            db.close()

    @property
    def active_job_id(self):
        with self._lock:
            return self._active

    def _public(self, row):
        payload = json.loads(row['payload_json'])
        return {'id': row['id'], 'status': row['status'], 'text': payload['text'], 'created_at': row['created_at'], 'engine':payload.get('engine','tts'), **json.loads(row['details_json'] or '{}')}

    def list(self):
        return self.page()['jobs']

    def page(self, limit=50, before=None):
        if not 1 <= limit <= 100 or (before is not None and before < 1):
            raise ValueError('Invalid history page.')
        where = "module='audio'" + (' AND j.rowid < ?' if before is not None else '')
        params = (before, limit + 1) if before is not None else (limit + 1,)
        with self._db() as db:
            rows = db.execute("SELECT j.*, j.rowid AS cursor, h.details_json FROM jobs j LEFT JOIN history h ON h.job_id=j.id WHERE " + where + ' ORDER BY j.rowid DESC LIMIT ?', params).fetchall()
            return {'jobs':[self._public(row) for row in rows[:limit]],
                    'next_cursor':rows[limit - 1]['cursor'] if len(rows) > limit else None}

    def _claimed(self, identifier):
        with self._db() as db:
            return db.execute("SELECT 1 FROM jobs WHERE module='audio' AND status IN ('QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP','RECOVERY_REQUIRED') AND (json_extract(payload_json,'$.reference_id')=? OR json_extract(payload_json,'$.source_id')=?) LIMIT 1", (identifier,identifier)).fetchone() is not None

    def discard_reference(self, identifier):
        with self._lock:
            if identifier not in self._uploads and not self._claimed(identifier):
                self.runner.reference_path(identifier).unlink(missing_ok=True)

    def begin_upload(self):
        with self._lock:
            paths = list(self.runner.references.iterdir())
            for path in paths:
                identifier = path.name.removesuffix('.part')
                if re.fullmatch(ID_PATTERN, identifier) and not path.is_symlink() and identifier not in self._uploads and not self._claimed(identifier):
                    if path.stat().st_mtime < time.time() - 3600:
                        path.unlink(missing_ok=True)
            pending = [path for path in self.runner.references.iterdir() if re.fullmatch(ID_PATTERN, path.name.removesuffix('.part'))]
            if len(pending) + len(self._uploads) >= 8:
                raise RuntimeError('Too many pending audio uploads. Remove unused recordings first.')
            identifier = str(uuid4())
            self._uploads.add(identifier)
            return identifier

    def finish_upload(self, identifier, *, completed):
        with self._lock:
            self._uploads.discard(identifier)
            path = self.runner.reference_path(identifier)
            path.with_name(path.name + '.part').unlink(missing_ok=True)
            if not completed:
                path.unlink(missing_ok=True)

    def get(self, identifier):
        with self._db() as db:
            row = db.execute("SELECT j.*, h.details_json FROM jobs j LEFT JOIN history h ON h.job_id=j.id WHERE module='audio' AND j.id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError('Audio job not found.')
            return self._public(row)

    def submit(self, request: AudioRequest):
        try:
            return self._submit(request)
        except (ValueError, RuntimeError):
            if request.reference_id:
                self.discard_reference(request.reference_id)
            source_id = getattr(request, 'source_id', None)
            if source_id:
                self.discard_reference(source_id)
            raise

    def _submit(self, request: AudioRequest):
        payload = request.model_dump(exclude={'idempotency_key'})
        with self._lock, self._db() as db:
            row = db.execute('SELECT id,module,payload_json FROM jobs WHERE idempotency_key=?', (request.idempotency_key,)).fetchone()
            if row:
                if row['module'] != 'audio' or json.loads(row['payload_json']) != payload:
                    raise ValueError('Request key is already used for different content.')
                return self.get(row['id'])
            if self._closed or self._active:
                raise RuntimeError('An audio job is already active or the application is closing.')
            if not (self.runner.available() if request.engine == 'tts' else self.runner.available(request.engine)):
                raise RuntimeError('Audio engine setup or verification is incomplete.')
            if request.source_id and not self.runner.reference_path(request.source_id).is_file():
                raise ValueError('Source recording was not found. Upload it again.')
            if request.mode == 'clone' and not self.runner.reference_path(request.reference_id).is_file():
                raise ValueError('Reference recording was not found. Upload it again.')
            job, _ = JobRepository(db).enqueue('audio', payload, request.idempotency_key)
            self._active, self._cancel = job.id, threading.Event()
            self._pool.submit(self._run, job.id, payload, self._cancel)
            return self.get(job.id)

    def _finish(self, db, identifier, state, details):
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT OR REPLACE INTO history(job_id,details_json) VALUES (?,?)', (identifier, json.dumps(details)))
            db.execute('UPDATE jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (state, identifier))
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK'); raise

    def _run(self, identifier, payload, cancel):
        with self._db() as db:
            try:
                with self._lock:
                    if cancel.is_set():
                        raise AudioCancelled('Generation cancelled.')
                    db.execute("UPDATE jobs SET status='RUNNING' WHERE id=?", (identifier,))
                result = self.runner.run(identifier, payload, cancel)
                with self._lock:
                    if cancel.is_set():
                        raise AudioCancelled('Generation cancelled.')
                    self._finish(db, identifier, 'COMPLETED', {'result': result})
            except AudioCancelled as error:
                self._finish(db, identifier, 'INTERRUPTED', {'error': str(error)})
            except Exception as error:
                self._finish(db, identifier, 'RECOVERY_REQUIRED' if self.runner.gpu.state == 'RECOVERY_REQUIRED' else 'FAILED', {'error': str(error)})
            finally:
                try:
                    directory = self.runner.data / identifier
                    if not (directory/'keep-inputs').exists():
                        for key in ('reference_id','source_id'):
                            if payload.get(key):self.runner.reference_path(payload[key]).unlink(missing_ok=True)
                        for name in ('reference.wav','source.wav','request.json'):
                            (directory/name).unlink(missing_ok=True)
                finally:
                    with self._lock:
                        self._active = None

    def cancel(self, identifier):
        with self._lock:
            self.get(identifier)
            if self._active == identifier:
                self._cancel.set()
                with self._db() as db:
                    db.execute("UPDATE jobs SET status='CANCELLING' WHERE id=? AND status IN ('QUEUED','PREPARING','RUNNING')", (identifier,))
            return self.get(identifier)

    def output_path(self, identifier):
        if not re.fullmatch(ID_PATTERN, identifier) or self.get(identifier)['status'] != 'COMPLETED':
            raise KeyError('Audio output not found.')
        path = self.runner.data / identifier / 'output.wav'
        if not path.is_file() or path.is_symlink():
            raise KeyError('Audio output not found.')
        return path

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
        self._pool.shutdown(wait=True)
