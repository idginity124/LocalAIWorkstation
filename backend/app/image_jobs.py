"""Persistent, single-flight image jobs independent of the HTTP connection."""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from .comfy import ComfyManager, ImageCancelled, ImageRecoveryRequired
from .jobs import JobRepository, JobStatus
from .storage import open_database


class ImageInputRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    init_image: str = Field(min_length=1, max_length=17 * 1024**2)


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["generate", "edit"] = "generate"
    prompt: str = Field(min_length=1, max_length=8000)
    seed: StrictInt = Field(default=-1, ge=-1, le=2**53 - 1)
    steps: StrictInt = Field(default=8, ge=1, le=30)
    cfg: float = Field(default=1.0, ge=0.5, le=10)
    width: StrictInt = Field(default=1024, ge=256, le=1536)
    height: StrictInt = Field(default=1024, ge=256, le=1536)
    init_image: str | None = Field(default=None, max_length=17 * 1024**2)
    edit_mask: str | None = Field(default=None, max_length=17 * 1024**2)
    engine: Literal['flux','lama','sdxl'] = 'flux'
    denoise: float = Field(default=0.6, ge=0.05, le=1)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("prompt")
    @classmethod
    def clean_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("İstem boş olamaz.")
        return value.strip()

    @field_validator("width", "height")
    @classmethod
    def multiples_of_eight(cls, value: int) -> int:
        if value % 8:
            raise ValueError("Boyutlar 8'in katı olmalı.")
        return value


class ImageJobs:
    def __init__(self, database_path: Path, manager: ComfyManager):
        self.path = database_path
        self.manager = manager
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="image-job")
        self._active: str | None = None
        self._cancel = threading.Event()
        self._closed = False
        with self._db() as db:
            db.execute("UPDATE jobs SET status='RECOVERY_REQUIRED' WHERE module='image' AND status IN ('QUEUED','PREPARING','RUNNING','CANCELLING','CLEANUP')")

    def _db(self):
        # Each worker/request owns its SQLite connection; never share one across threads.
        from contextlib import contextmanager
        @contextmanager
        def connection():
            db = open_database(self.path)
            db.create_function('CASEFOLD', 1, lambda value: str(value).casefold(), deterministic=True)
            try:
                yield db
            finally:
                db.close()
        return connection()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active is not None

    def list(self, limit: int = 50) -> list[dict]:
        return self.page(limit=limit)['jobs']

    def page(self, *, limit: int = 50, before: int | None = None, search: str = '') -> dict:
        if not 1 <= limit <= 100 or (before is not None and before < 1) or len(search) > 200:
            raise ValueError('Geçersiz geçmiş sayfası.')
        where, params = ["j.module='image'"], []
        if before is not None:
            where.append('j.rowid < ?')
            params.append(before)
        if search:
            where.append("instr(CASEFOLD(json_extract(j.payload_json, '$.prompt')), CASEFOLD(?)) > 0")
            params.append(search)
        with self._db() as db:
            rows = db.execute("SELECT j.*, j.rowid AS cursor, h.details_json FROM jobs j LEFT JOIN history h ON h.job_id=j.id WHERE " +
                ' AND '.join(where) + ' ORDER BY j.rowid DESC LIMIT ?', (*params, limit + 1)).fetchall()
            return {'jobs':[self._public(row) for row in rows[:limit]],
                'next_cursor':rows[limit - 1]['cursor'] if len(rows) > limit else None}

    @staticmethod
    def _public(row) -> dict:
        payload = json.loads(row["payload_json"])
        detail = json.loads(row["details_json"]) if row["details_json"] else {}
        return {"id": row["id"], "status": row["status"], "mode": payload.get("mode"),
                "prompt": payload.get("prompt"), "created_at": row["created_at"],
                "updated_at": row["updated_at"], **detail}

    def get(self, job_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT j.*, h.details_json FROM jobs j LEFT JOIN history h ON h.job_id=j.id WHERE j.id=? AND module='image'", (job_id,)).fetchone()
            if row is None:
                raise KeyError("Görsel işi bulunamadı.")
            return self._public(row)

    def submit(self, request: ImageRequest) -> dict:
        payload = request.model_dump(exclude={"idempotency_key"})
        stored = dict(payload)
        # Keep existing default job identity stable across application upgrades.
        if request.engine=='flux':
            stored.pop('engine')
            payload.pop('engine')
        elif request.mode!='edit' or not request.edit_mask:
            raise ValueError('Bu motor için görsel ve seçim maskesi gerekli.')
        if request.init_image:
            raw = self.manager._decode_image(request.init_image)
            stored["init_image"] = hashlib.sha256(raw).hexdigest()
        if request.mode == "edit" and not request.init_image:
            raise ValueError("Düzenlemek için bir görsel seçin.")
        if request.edit_mask:
            if request.mode != 'edit' or not request.init_image:
                raise ValueError('Seçim maskesi yalnızca görsel düzenleme için kullanılabilir.')
            from .masked_edit import prepare_region
            mask_raw=self.manager._decode_image(request.edit_mask)
            prepare_region(self.manager._decode_image(request.init_image),mask_raw)
            stored['edit_mask']=hashlib.sha256(mask_raw).hexdigest()
        with self._lock, self._db() as db:
            existing = db.execute("SELECT id, module, payload_json FROM jobs WHERE idempotency_key=?", (request.idempotency_key,)).fetchone()
            if existing:
                if existing["module"] != "image" or json.loads(existing["payload_json"]) != stored:
                    raise ValueError("Bu istek anahtarı farklı bir iş için kullanılmış.")
                return self.get(existing["id"])
            if self._closed:
                raise RuntimeError("Uygulama kapanıyor.")
            if self._active:
                raise RuntimeError("Bir görsel işi devam ediyor. Bitmesini bekleyin veya iptal edin.")
            status = self.manager.status()
            available=status["edit"]["available"] if request.mode == "edit" else status["generation_available"]
            if request.mode=='edit' and request.engine!='flux':
                available=self.manager.inpaint_status()[request.engine]['available']
            if not available:
                if request.engine!='flux':
                    raise RuntimeError('ComfyUI açık olmalı. Eksik modeller için: bash scripts/krita-modelleri-kur.sh')
                raise RuntimeError(status["reason"] if request.mode == "generate" else "Görsel servisi veya düzenleme modeli hazır değil.")
            job, _ = JobRepository(db).enqueue("image", stored, request.idempotency_key)
            self._active = job.id
            self._cancel = threading.Event()
            self._pool.submit(self._run, job.id, payload, self._cancel)
            return self.get(job.id)

    def _run(self, job_id: str, payload: dict, cancel: threading.Event) -> None:
        with self._db() as db:
            repo = JobRepository(db)
            try:
                with self._lock:
                    if cancel.is_set():
                        raise ImageCancelled("Görsel işi iptal edildi.")
                    repo.transition(job_id, JobStatus.PREPARING)
                    repo.transition(job_id, JobStatus.RUNNING)
                mode = payload.pop("mode")
                if mode == "edit":
                    payload = {k: payload[k] for k in ("prompt", "init_image", "seed", "edit_mask", "engine") if payload.get(k) is not None}
                result = self.manager.execute(mode, payload, cancel, job_id=job_id)
                with self._lock:
                    if cancel.is_set():
                        raise ImageCancelled('Görsel işi iptal edildi.')
                    self._finish(db, job_id, "COMPLETED", {"result": result})
            except ImageCancelled as error:
                self._finish(db, job_id, "INTERRUPTED", {"error": str(error)})
            except ImageRecoveryRequired as error:
                self._finish(db, job_id, 'RECOVERY_REQUIRED', {'error':str(error)})
            except Exception as error:
                self._finish(db, job_id, "FAILED", {"error": str(error)})
            finally:
                with self._lock:
                    self._active = None

    @staticmethod
    def _finish(db, job_id: str, state: str, detail: dict):
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("INSERT OR REPLACE INTO history(job_id,details_json) VALUES (?,?)", (job_id, json.dumps(detail, ensure_ascii=False)))
            db.execute("UPDATE jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, job_id))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self.get(job_id)
            if self._active == job_id:
                self._cancel.set()
                with self._db() as db:
                    db.execute("UPDATE jobs SET status='CANCELLING',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('RUNNING','PREPARING','QUEUED')", (job_id,))
            return self.get(job_id)

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
        self._pool.shutdown(wait=True)
