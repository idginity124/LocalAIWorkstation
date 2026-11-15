"""Read-only, evidence-based Linux hardware inspection."""

from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
from pathlib import Path

from .resources import GpuObservation


def _read_text(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _meminfo_kib() -> dict[str, int]:
    values: dict[str, int] = {}
    content = _read_text("/proc/meminfo")
    if content is None:
        return values
    for line in content.splitlines():
        key, _, rest = line.partition(":")
        first = rest.strip().split(maxsplit=1)
        if first and first[0].isdigit():
            values[key] = int(first[0])
    return values


def _cpu_name() -> str | None:
    content = _read_text("/proc/cpuinfo")
    if content:
        for line in content.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Hardware"}:
                return value.strip()
    return platform.processor() or None


def _os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    content = _read_text("/etc/os-release")
    if content:
        for line in content.splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"PRETTY_NAME", "ID", "VERSION_ID"}:
                values[key.lower()] = value.strip().strip('"')
    return values


def _gpu_devices() -> list[dict[str, object]]:
    devices: list[dict[str, object]] = []
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]*")):
        device = Path(card) / "device"
        vendor = _read_text(device / "vendor")
        if vendor is None:
            continue
        if vendor.lower() != "0x1002":
            continue
        used = _read_text(device / "mem_info_vram_used")
        total = _read_text(device / "mem_info_vram_total")
        sensors = {}
        for name, filename in (
            ("temperature_millic", "hwmon/hwmon*/temp1_input"),
            ("gpu_busy_percent", "gpu_busy_percent"),
        ):
            values = [
                value
                for p in glob.glob(str(device / filename))
                if (value := _read_text(p)) is not None
            ]
            sensors[name] = values[0] if values else None
        devices.append(
            {
                "device": Path(card).name,
                "vendor": "AMD",
                "name": _read_text(device / "product_name"),
                "vram_used_bytes": int(used) if used and used.isdigit() else None,
                "vram_total_bytes": int(total) if total and total.isdigit() else None,
                "temperature_millic": sensors["temperature_millic"],
                "gpu_busy_percent": sensors["gpu_busy_percent"],
                "source": "amdgpu sysfs",
            }
        )
    return devices


def _recognized_external_ai_processes() -> list[str] | None:
    """Best-effort local-AI process scan; never claims to enumerate all GPU users."""
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="], check=True, capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return None
    markers = ("llama-server", "ollama serve", "comfyui", "vllm serve", "sglang")
    return [line.strip() for line in result.stdout.splitlines() if any(marker in line.lower() for marker in markers)]


class SystemGpuObservationProvider:
    """Observes the first AMD GPU via sysfs and blocks known external AI services.

    Generic desktop graphics clients cannot be attributed to VRAM with sysfs. They
    remain part of the measured baseline; recognized local heavy-AI services do not.
    """

    async def observe(self) -> GpuObservation:
        devices = _gpu_devices()
        gpu = devices[0] if devices else None
        external = _recognized_external_ai_processes()
        if gpu is None:
            return GpuObservation(None, None, None, False)
        return GpuObservation(
            used_bytes=gpu["vram_used_bytes"] if isinstance(gpu["vram_used_bytes"], int) else None,
            total_bytes=gpu["vram_total_bytes"] if isinstance(gpu["vram_total_bytes"], int) else None,
            source="amdgpu sysfs + tanınan yerel AI süreç taraması",
            external_workloads_known=external == [],
        )


def snapshot() -> dict[str, object]:
    mem = _meminfo_kib()
    cpu_load = _read_text("/proc/loadavg")
    cpu = _cpu_name()
    ram_total = mem.get("MemTotal")
    ram_available = mem.get("MemAvailable")
    swap_total = mem.get("SwapTotal")
    swap_free = mem.get("SwapFree")
    model_root = Path(os.environ.get("AI_WORKSTATION_MODEL_DIR", Path.home() / "AI/models")).expanduser()
    disk_path = model_root if model_root.exists() else model_root.parent
    try:
        disk_usage = shutil.disk_usage(disk_path)
        disk = {
            "path": str(disk_path),
            "total_bytes": disk_usage.total,
            "used_bytes": disk_usage.used,
            "free_bytes": disk_usage.free,
            "source": "statvfs",
        }
    except OSError:
        disk = {"path": str(disk_path), "total_bytes": None, "used_bytes": None, "free_bytes": None, "source": None}
    return {
        "sampling": "periodic; sampled per request",
        "os": platform.platform(),
        "distribution": _os_release(),
        "kernel": platform.release(),
        "desktop_session": os.environ.get("XDG_SESSION_TYPE", "unknown"),
        "cpu": {"name": cpu, "load_average": cpu_load},
        "memory": {
            "total_bytes": ram_total * 1024 if ram_total is not None else None,
            "available_bytes": ram_available * 1024 if ram_available is not None else None,
            "swap_total_bytes": swap_total * 1024 if swap_total is not None else None,
            "swap_free_bytes": swap_free * 1024 if swap_free is not None else None,
            "source": "/proc/meminfo",
        },
        "gpus": _gpu_devices(),
        "disk": disk,
        "gpu_state": "unknown; external GPU workloads have not been excluded",
    }
