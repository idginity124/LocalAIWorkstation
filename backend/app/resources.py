"""Conservative single-heavy-GPU lease with explicit release verification."""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ResourceState(StrEnum):
    IDLE = "IDLE"
    QUEUED = "QUEUED"
    RELEASING = "RELEASING"
    VERIFYING = "VERIFYING"
    ACQUIRING = "ACQUIRING"
    RUNNING = "RUNNING"
    CLEANUP = "CLEANUP"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


@dataclass(frozen=True)
class GpuObservation:
    used_bytes: int | None
    total_bytes: int | None
    source: str | None
    external_workloads_known: bool

    @property
    def free_bytes(self) -> int | None:
        if self.used_bytes is None or self.total_bytes is None:
            return None
        if self.used_bytes < 0 or self.total_bytes <= 0 or self.used_bytes > self.total_bytes:
            return None
        return self.total_bytes - self.used_bytes


class ObservationProvider(Protocol):
    async def observe(self) -> GpuObservation: ...


@dataclass(frozen=True)
class GpuLease:
    job_id: str
    baseline_used_bytes: int
    baseline_total_bytes: int
    source: str


class GpuResourceManager:
    """Only grant one lease when memory and outside workloads are observable."""

    def __init__(self, provider: ObservationProvider, tolerance_bytes: int = 256 * 1024**2,
                 release_attempts: int = 10, release_interval_seconds: float = 1.0):
        self._provider = provider
        self._tolerance = tolerance_bytes
        self._release_attempts = release_attempts
        self._release_interval_seconds = release_interval_seconds
        self._lock = threading.Lock()
        self._state = ResourceState.UNKNOWN
        self._lease: GpuLease | None = None
        self._reason = "Henüz ölçüm alınmadı."

    @asynccontextmanager
    async def _guard(self):
        # Adapters run in different worker threads and event loops.
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0.02)
        try:
            yield
        finally:
            self._lock.release()

    @property
    def state(self) -> ResourceState:
        return self._state

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def active_job_id(self) -> str | None:
        return self._lease.job_id if self._lease else None

    async def acquire(self, job_id: str, required_bytes: int) -> GpuLease:
        if required_bytes <= 0:
            raise ValueError("GPU bellek tahmini pozitif olmalı.")
        async with self._guard():
            if self._state == ResourceState.RECOVERY_REQUIRED:
                raise RuntimeError(self._reason)
            if self._lease is not None:
                self._state = ResourceState.QUEUED
                self._reason = f"{self._lease.job_id} işi GPU kaynağını kullanıyor."
                raise RuntimeError(self._reason)

            if self._state == ResourceState.RECOVERY_REQUIRED:
                raise RuntimeError(self._reason)
            self._state = ResourceState.VERIFYING
            observation = await self._provider.observe()
            if (
                observation.free_bytes is None
                or observation.used_bytes is None
                or observation.total_bytes is None
                or not observation.source
                or not observation.external_workloads_known
            ):
                self._state = ResourceState.UNKNOWN
                self._reason = "VRAM veya dış GPU işleri doğrulanamadı; görev bekletildi."
                raise RuntimeError(self._reason)
            if observation.free_bytes < required_bytes:
                self._state = ResourceState.IDLE
                self._reason = "Ölçülen boş VRAM işin tahmin edilen gereksiniminden az."
                raise RuntimeError(self._reason)

            self._state = ResourceState.ACQUIRING
            lease = GpuLease(
                job_id=job_id,
                baseline_used_bytes=observation.used_bytes,
                baseline_total_bytes=observation.total_bytes,
                source=observation.source,
            )
            self._lease = lease
            self._state = ResourceState.RUNNING
            self._reason = f"{job_id} işi için GPU kilidi alındı."
            return lease

    async def release_and_verify(self, lease: GpuLease) -> None:
        async with self._guard():
            if self._lease != lease:
                self._state = ResourceState.RECOVERY_REQUIRED
                self._reason = "GPU kilidi sahibi eşleşmiyor; durum elle incelenmeli."
                raise RuntimeError(self._reason)
            self._state = ResourceState.CLEANUP
            self._state = ResourceState.RELEASING
            self._reason = "Servis boşaltma adımı tamamlandı; VRAM ayrıca ölçülüyor."
            self._state = ResourceState.VERIFYING
            last_reason = "Boşaltma sonrası VRAM doğrulanamadı; yeni ağır iş engellendi."
            for attempt in range(self._release_attempts):
                observation = await self._provider.observe()
                if (
                    observation.used_bytes is None
                    or observation.total_bytes is None
                    or not observation.source
                    or not observation.external_workloads_known
                ):
                    last_reason = "Boşaltma sonrası VRAM veya dış GPU işleri doğrulanamadı."
                elif observation.used_bytes <= lease.baseline_used_bytes + self._tolerance:
                    self._lease = None
                    self._state = ResourceState.IDLE
                    self._reason = "VRAM başlangıç seviyesine göre doğrulandı ve GPU kilidi bırakıldı."
                    return
                else:
                    last_reason = "VRAM kullanımı başlangıç seviyesine henüz dönmedi."
                if attempt + 1 < self._release_attempts:
                    await asyncio.sleep(self._release_interval_seconds)
            self._state = ResourceState.RECOVERY_REQUIRED
            self._reason = f"{last_reason} Yeni ağır iş engellendi."
            raise RuntimeError(self._reason)

    def require_recovery(self, reason: str) -> None:
        self._state = ResourceState.RECOVERY_REQUIRED
        self._reason = reason
