"""Persistent idempotent job records; GPU scheduling is handled separately."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4
from collections.abc import Iterator


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CLEANUP = "CLEANUP"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.PREPARING, JobStatus.FAILED, JobStatus.INTERRUPTED},
    JobStatus.PREPARING: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.RECOVERY_REQUIRED},
    JobStatus.RUNNING: {JobStatus.CANCELLING, JobStatus.CLEANUP, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RECOVERY_REQUIRED},
    JobStatus.CANCELLING: {JobStatus.CLEANUP, JobStatus.FAILED, JobStatus.RECOVERY_REQUIRED},
    JobStatus.CLEANUP: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.RECOVERY_REQUIRED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.INTERRUPTED: {JobStatus.RECOVERY_REQUIRED},
    JobStatus.RECOVERY_REQUIRED: set(),
}


@dataclass(frozen=True)
class Job:
    id: str
    module: str
    status: JobStatus
    priority: int
    payload: dict[str, Any]
    idempotency_key: str


class JobRepository:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def enqueue(
        self, module: str, payload: dict[str, Any], idempotency_key: str, priority: int = 0
    ) -> tuple[Job, bool]:
        if not module or len(module) > 64:
            raise ValueError("Modül kimliği geçersiz.")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("İdempotency anahtarı geçersiz.")
        with self._transaction():
            existing = self.connection.execute(
                "SELECT id, module, status, priority, payload_json, idempotency_key "
                "FROM jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["module"] != module or json.loads(existing["payload_json"]) != payload:
                    raise ValueError("Aynı idempotency anahtarı farklı istek için kullanılmış.")
                return self._decode(existing), False

            job_id = str(uuid4())
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.connection.execute(
                "INSERT INTO jobs(id,module,status,priority,payload_json,idempotency_key) "
                "VALUES(?,?,?,?,?,?)",
                (job_id, module, JobStatus.QUEUED, priority, payload_json, idempotency_key),
            )
            return Job(job_id, module, JobStatus.QUEUED, priority, payload, idempotency_key), True

    def transition(self, job_id: str, target: JobStatus) -> Job:
        with self._transaction():
            row = self.connection.execute(
                "SELECT id, module, status, priority, payload_json, idempotency_key "
                "FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError("İş bulunamadı.")
            current = JobStatus(row["status"])
            if target not in TRANSITIONS[current]:
                raise ValueError(f"Geçersiz iş geçişi: {current} → {target}.")
            self.connection.execute(
                "UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (target, job_id),
            )
            row = dict(row)
            row["status"] = target
            return self._decode(row)

    def recover_after_restart(self) -> int:
        """Mark uncertain in-flight records; never submit them a second time."""
        with self._transaction():
            cursor = self.connection.execute(
                "UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE status IN (?, ?, ?, ?)",
                (
                    JobStatus.RECOVERY_REQUIRED,
                    JobStatus.PREPARING,
                    JobStatus.RUNNING,
                    JobStatus.CANCELLING,
                    JobStatus.CLEANUP,
                ),
            )
            return cursor.rowcount

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> Job:
        return Job(
            id=row["id"],
            module=row["module"],
            status=JobStatus(row["status"]),
            priority=row["priority"],
            payload=json.loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"],
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
