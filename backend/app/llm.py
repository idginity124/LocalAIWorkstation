"""Managed, loopback-only llama.cpp adapter for the preinstalled Gemma GGUF."""

from __future__ import annotations

import json
import http.client
from contextlib import contextmanager
import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .resources import GpuLease, GpuResourceManager

DEFAULT_ROOT = Path(os.environ.get("AI_WORKSTATION_MODEL_DIR", Path.home() / "AI/models")).expanduser()
MODEL_RELATIVE = Path("gemma-4-12b/gemma-4-12B-it-Q4_0.gguf")
MMPROJ_RELATIVE = Path("gemma-4-12b/mmproj-gemma-4-12B-it-Q8_0.gguf")
HOST = "127.0.0.1"
PORT = 18080
CONTEXT_SIZE = 2048
RAM_RESERVE_BYTES = 3 * 1024**3
GPU_MODE_RAM_RESERVE_BYTES = 2 * 1024**3  # GPU modunda ağırlıklar VRAM'e gider; RAM'de yalnızca çalışma payı gerekir
GPU_REQUIRED_BYTES = 8 * 1024**3
MAX_REQUEST_BYTES = 32 * 1024
MAX_OUTPUT_TOKENS = 512
CONTEXT_MARGIN = 64
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class LocalModelSpec:
    """An allow-listed local GGUF model.  No user supplied paths reach llama.cpp."""

    id: str
    name: str
    model_relative: Path
    port: int
    gpu_required_bytes: int
    mmproj_relative: Path | None = None
    reasoning_off: bool = False


GEMMA_SPEC = LocalModelSpec(
    "gemma-4-12b", "Gemma 4 12B IT Q4_0", MODEL_RELATIVE, PORT, GPU_REQUIRED_BYTES,
    mmproj_relative=MMPROJ_RELATIVE, reasoning_off=True,
)
QWEN_SPEC = LocalModelSpec(
    "qwen3.5-9b-q8_0", "Qwen3.5 9B Q8_0", Path("qwen3.5-9b/qwen3.5-9b-Q8_0.gguf"),
    18082, 12 * 1024**3, reasoning_off=True,
)
GPT_OSS_SPEC = LocalModelSpec(
    "gpt-oss-20b-mxfp4", "gpt-oss 20B MXFP4", Path("gpt-oss-20b/gpt-oss-20b-MXFP4.gguf"),
    18083, 13 * 1024**3,
)
LOCAL_MODEL_SPECS: dict[str, LocalModelSpec] = {
    spec.id: spec for spec in (GEMMA_SPEC, QWEN_SPEC, GPT_OSS_SPEC)
}


class GemmaUnavailable(RuntimeError):
    pass


class GemmaCancelled(GemmaUnavailable):
    pass


class _FinalAnswerFilter:
    """Suppress Gemma thought-channel bytes before they reach UI or storage."""

    OPEN = "<|channel>thought"
    CLOSE = "<channel|>"
    FINAL = "<|channel>final"

    def __init__(self) -> None:
        self.state = "prefix"
        self.buffer = ""

    @staticmethod
    def _strip_final_label(value: str) -> str:
        if value.startswith(_FinalAnswerFilter.FINAL):
            value = value[len(_FinalAnswerFilter.FINAL):]
            if value.startswith("\r\n"):
                value = value[2:]
            elif value.startswith("\n"):
                value = value[1:]
        return value

    def feed(self, value: str) -> str:
        if self.state == "final":
            return value
        if self.state == "final_newline":
            self.state = "final"
            if value.startswith("\r\n"):
                return value[2:]
            if value.startswith("\n"):
                return value[1:]
            if value == "\r":
                self.state = "final_newline"
                return ""
            return value
        if self.state == "final_label":
            self.buffer += value
            if "final".startswith(self.buffer):
                return ""
            if not self.buffer.startswith("final"):
                self.state = "final"
                value, self.buffer = self.buffer, ""
                return value
            remainder = self.buffer[len("final"):]
            self.buffer = ""
            if remainder == "\r":
                self.state = "final_newline"
                return ""
            if remainder.startswith("\r\n"):
                remainder = remainder[2:]
            elif remainder.startswith("\n"):
                remainder = remainder[1:]
            self.state = "final"
            return remainder
        if self.state == "prefix":
            self.buffer += value
            if self.OPEN.startswith(self.buffer) or self.FINAL.startswith(self.buffer):
                return ""
            if self.buffer.startswith(self.OPEN):
                self.state = "thought"
                self.buffer = self.buffer[len(self.OPEN):]
                value, self.buffer = self.buffer, ""
            elif self.buffer.startswith(self.FINAL):
                self.state = "final"
                value, self.buffer = self._strip_final_label(self.buffer), ""
                return value
            else:
                self.state = "final"
                value, self.buffer = self._strip_final_label(self.buffer), ""
                return value
        if self.state == "thought":
            self.buffer += value
            position = self.buffer.find(self.CLOSE)
            if position < 0:
                return ""
            value = self.buffer[position + len(self.CLOSE):]
            self.buffer = ""
            self.state = "final_label"
            return self.feed(value)
        return value

    def finish(self) -> None:
        if self.state == "thought":
            raise GemmaUnavailable("Gemma thinking bölümü güvenle ayrılamadı; yanıt kaydedilmedi.")
        if self.state == "prefix" and self.buffer and (self.OPEN.startswith(self.buffer) or self.FINAL.startswith(self.buffer)):
            raise GemmaUnavailable("Gemma kanal etiketi yarım kaldı; yanıt kaydedilmedi.")
        if self.state == "final_label" and self.buffer:
            raise GemmaUnavailable("Gemma final kanal etiketi yarım kaldı; yanıt kaydedilmedi.")


class GemmaServer:
    """Starts only on an explicit call; never auto-loads a model at app startup."""

    def __init__(self, model_root: Path = DEFAULT_ROOT, executable: str | None = None,
                 resource_manager: GpuResourceManager | None = None,
                 spec: LocalModelSpec = GEMMA_SPEC):
        self.model_root = model_root.expanduser().resolve()
        self.spec = spec
        self.executable = executable or shutil.which("llama-server")
        self.process: subprocess.Popen[bytes] | None = None
        self.api_key = secrets.token_urlsafe(32)
        self.log_path = Path(os.environ.get("AI_WORKSTATION_DATA", Path.home() / ".local/share/ai-workstation")) / "logs" / f"{spec.id}.log"
        self._lifecycle_lock = threading.Lock()
        self._chat_lock = threading.Lock()
        self._active_cancel: threading.Event | None = None
        self._active_connection: http.client.HTTPConnection | None = None
        self._active_socket: socket.socket | None = None
        self.resource_manager = resource_manager
        self._gpu_lease: GpuLease | None = None

    @property
    def model_path(self) -> Path:
        return (self.model_root / self.spec.model_relative).resolve()

    @property
    def mmproj_path(self) -> Path | None:
        if self.spec.mmproj_relative is None:
            return None
        return (self.model_root / self.spec.mmproj_relative).resolve()

    def _model_files(self) -> tuple[Path, ...]:
        return tuple(path for path in (self.model_path, self.mmproj_path) if path is not None)

    def status(self) -> dict[str, Any]:
        if self.process is not None:
            if self.process.poll() is None:
                healthy = self._healthy()
                return {"state": "RUNNING" if healthy else "ACQUIRING", "managed": True,
                        "model": self.spec.name, "model_id": self.spec.id,
                        "device": "Vulkan0" if self.resource_manager else "CPU", "context_size": CONTEXT_SIZE,
                        "host": HOST, "port": self.spec.port, "active_request": self._active_cancel is not None}
            self.process = None
            if self._gpu_lease is not None and self.resource_manager is not None:
                self.resource_manager.require_recovery("Gemma süreci beklenmedik biçimde kapandı; VRAM elle doğrulanmalı.")
        if self._port_open():
            return {"state": "UNKNOWN", "managed": False, "reason": "Bu portta uygulamanın başlatmadığı bir servis var.",
                    "model": self.spec.name, "model_id": self.spec.id}
        available = self._available_ram()
        files = self._model_files()
        files_available = all(path.is_file() for path in files)
        needed = self._ram_needed(files) if files_available else None
        runtime_available = bool(self.executable)
        start_allowed = runtime_available and files_available and available is not None and needed is not None and available >= needed
        reason = None
        if not runtime_available:
            reason = "llama-server bulunamadı."
        elif not files_available:
            reason = f"{self.spec.name} GGUF dosyası bulunamadı."
        elif available is None:
            reason = "Kullanılabilir RAM ölçülemedi."
        elif needed is not None and available < needed:
            reason = "Mevcut RAM, model ve 3 GiB güvenlik payı için yetersiz."
        if self.resource_manager and self.resource_manager.active_job_id == "comfyui":
            start_allowed = False
            reason = "Görsel servisi GPU belleğini kullanıyor. Üst çubuktan belleği boşaltın."
        if self.resource_manager and self.resource_manager.state == "RECOVERY_REQUIRED":
            start_allowed = False
            reason = self.resource_manager.reason
        resource_state = self.resource_manager.state if self.resource_manager else None
        resource_reason = self.resource_manager.reason if self.resource_manager else None
        return {"state": "IDLE", "managed": False, "runtime_available": runtime_available,
                "model": self.spec.name, "model_id": self.spec.id,
                "device": "Vulkan0" if self.resource_manager else "CPU", "context_size": CONTEXT_SIZE,
                "model_files_available": files_available, "start_allowed": start_allowed,
                "available_ram_bytes": available, "reason": reason, "host": HOST, "port": self.spec.port,
                "resource_state": resource_state, "resource_reason": resource_reason}

    def start(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            return self._start_locked()

    def preflight(self) -> None:
        if not self.executable or not Path(self.executable).is_file():
            raise GemmaUnavailable("llama-server bulunamadı.")
        if not all(path.is_file() and path.stat().st_size > 0 for path in self._model_files()):
            raise GemmaUnavailable(f"{self.spec.name} GGUF dosyası bulunamadı.")
        available = self._available_ram()
        if available is None or available < self._ram_needed(self._model_files()):
            raise GemmaUnavailable("Kullanılabilir RAM, model ve güvenlik payı için yetersiz; model yüklenmedi.")
        if self._port_open() and (self.process is None or self.process.poll() is not None):
            raise GemmaUnavailable("Hedef model portu başka bir servis tarafından kullanılıyor.")

    def _start_locked(self) -> dict[str, Any]:
        if self.process is not None and self.process.poll() is None:
            return self.status()
        if self._port_open():
            raise GemmaUnavailable(f"127.0.0.1:{self.spec.port} kullanımda; dış servise dokunulmadı.")
        if not self.executable:
            raise GemmaUnavailable("llama-server bulunamadı.")
        for path in self._model_files():
            if not path.is_file():
                raise GemmaUnavailable(f"{self.spec.name} GGUF dosyası bulunamadı.")
        needed = self._ram_needed(self._model_files())
        available = self._available_ram()
        if available is None or available < needed:
            raise GemmaUnavailable("Kullanılabilir RAM, model ve güvenlik payı için yetersiz; model yüklenmedi.")
        lease: GpuLease | None = None
        if self.resource_manager is not None:
            try:
                lease = asyncio.run(self.resource_manager.acquire(self.spec.id, self.spec.gpu_required_bytes))
            except RuntimeError as error:
                raise GemmaUnavailable(f"{self.spec.name} GPU kaynağı alınamadı: {error}") from error
        command = [
            self.executable,
            "--model", str(self.model_path),
            "--host", HOST, "--port", str(self.spec.port),
            "--device", "Vulkan0" if lease else "none", "--gpu-layers", "999" if lease else "0",
            "--ctx-size", str(CONTEXT_SIZE),
            "--threads", "4", "--batch-size", "128", "--ubatch-size", "128", "--parallel", "1",
            "--alias", self.spec.id, "--no-webui",
        ]
        if self.mmproj_path is not None:
            command.extend(["--mmproj", str(self.mmproj_path)])
        if self.spec.reasoning_off:
            command.extend(["--reasoning", "off"])
        process_env = {**os.environ, "LLAMA_API_KEY": self.api_key}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > 8 * 1024**2:
                self.log_path.replace(self.log_path.with_suffix(".previous.log"))
            with self.log_path.open("ab") as log:
                self.process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, close_fds=True, start_new_session=True, env=process_env,
                )
        except OSError as error:
            self._release_gpu_after_failed_start(lease)
            raise GemmaUnavailable("llama-server başlatılamadı.") from error
        self._gpu_lease = lease
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.process = None
                self._release_gpu_after_failed_start(lease)
                self._gpu_lease = None
                raise GemmaUnavailable(f"Model yüklenirken kapandı. Günlük: {self.log_path}")
            if self._healthy():
                return self.status()
            time.sleep(0.25)
        self._stop_managed()
        raise GemmaUnavailable(f"{self.spec.name} 90 saniyede hazır olmadı; servis kontrollü biçimde durduruldu.")

    def stop(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            active = self._active_cancel is not None
            if self._active_cancel is not None:
                self._active_cancel.set()
            result = self._stop_locked()
            result["cancelled_active_request"] = active
            return result

    def _stop_locked(self) -> dict[str, Any]:
        if self.process is None:
            if self._port_open():
                raise GemmaUnavailable("Portta uygulamanın yönetmediği servis var; durdurulmadı.")
            self._release_owned_gpu()
            return {"state": "IDLE", "managed": False}
        self._stop_managed()
        return {"state": "IDLE", "managed": False}

    def cancel_response(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            active = self._active_cancel is not None
            if self._active_cancel is not None:
                self._active_cancel.set()
            active_socket = self._active_socket
        # close() alone can block behind a concurrent buffered read. shutdown()
        # wakes that read, and closing the HTTP stream cancels llama.cpp's task.
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        return {"cancelled_active_request": active, "model_loaded": self.process is not None and self.process.poll() is None}

    @contextmanager
    def _open_stream(self, request, cancel_event):
        connection = http.client.HTTPConnection(HOST, self.spec.port, timeout=1)
        with self._lifecycle_lock:
            if cancel_event.is_set():
                raise GemmaCancelled("Yanıt durduruldu.")
            self._active_connection = connection
        response = None
        try:
            connection.connect()
            with self._lifecycle_lock:
                self._active_socket = connection.sock
            if connection.sock is not None:
                connection.sock.settimeout(300)
            if cancel_event.is_set():
                raise GemmaCancelled("Yanıt durduruldu.")
            connection.request('POST', request.selector, body=request.data, headers=dict(request.header_items()))
            response = connection.getresponse()
            if response.status != 200:
                raise GemmaUnavailable(f"Yerel model isteği reddetti (HTTP {response.status}).")
            yield response
        finally:
            try:
                if response is not None:
                    response.close()
            finally:
                try:
                    connection.close()
                finally:
                    with self._lifecycle_lock:
                        if self._active_connection is connection:
                            self._active_connection = None
                            self._active_socket = None

    def _post_json(self, endpoint, payload, cancel_event):
        request = urllib.request.Request(
            f'http://{HOST}:{self.spec.port}{endpoint}',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type':'application/json', 'Authorization':f'Bearer {self.api_key}'}, method='POST',
        )
        with self._open_stream(request, cancel_event) as response:
            value = json.loads(response.read(4 * 1024**2))
        if not isinstance(value, dict):
            raise GemmaUnavailable("Yerel model geçersiz bağlam bilgisi verdi.")
        return value

    def _count_tokens(self, messages, cancel_event):
        payload = {'messages':messages}
        if self.spec.reasoning_off:
            payload['chat_template_kwargs'] = {'enable_thinking':False}
        prompt = self._post_json('/apply-template', payload, cancel_event).get('prompt')
        if not isinstance(prompt, str):
            raise GemmaUnavailable("Modelin sohbet şablonu okunamadı.")
        tokens = self._post_json('/tokenize', {'content':prompt, 'add_special':True, 'parse_special':True}, cancel_event).get('tokens')
        if not isinstance(tokens, list):
            raise GemmaUnavailable("Modelin token sayısı okunamadı.")
        return len(tokens)

    def _fit_context(self, messages, cancel_event, continuation=False):
        # Keep system instructions and the current request intact. Remove only
        # complete old user/assistant pairs; persisted history is never deleted.
        budget = CONTEXT_SIZE - MAX_OUTPUT_TOKENS - CONTEXT_MARGIN
        prefix = messages[:1] if messages[0]['role'] == 'system' else []
        body = messages[len(prefix):]
        keep = 3 if continuation else 1
        recent = [dict(item) for item in body[-keep:]]
        if self._count_tokens(prefix + recent, cancel_event) > budget:
            if not continuation:
                raise ValueError("Mesaj modelin bağlam sınırını aşıyor; daha kısa bir mesaj gönderin.")
            # The original answer must remain available when continuing. Prefer
            # its newest text over the beginning of an oversized original prompt.
            for index in (0, 1):
                original = recent[index]['content']
                low, high = 0, len(original)
                while low < high:
                    middle = (low + high + 1) // 2
                    recent[index]['content'] = original[-middle:]
                    if self._count_tokens(prefix + recent, cancel_event) <= budget:
                        low = middle
                    else:
                        high = middle - 1
                recent[index]['content'] = original[-low:] if low else '…'
                if self._count_tokens(prefix + recent, cancel_event) <= budget:
                    break
            if self._count_tokens(prefix + recent, cancel_event) > budget:
                raise ValueError("Devam yanıtı modelin bağlam sınırına sığmıyor.")
        older = body[:-keep]
        # Binary search a suffix of complete exchanges instead of re-tokenizing
        # the entire database on every turn of a long conversation.
        pairs = len(older) // 2
        low, high = 0, pairs
        while low < high:
            middle = (low + high + 1) // 2
            candidate = prefix + older[-2 * middle:] + recent
            if self._count_tokens(candidate, cancel_event) <= budget:
                low = middle
            else:
                high = middle - 1
        selected = prefix + (older[-2 * low:] if low else []) + recent
        # Token counts can vary at template boundaries. Verify the final choice.
        while self._count_tokens(selected, cancel_event) > budget and len(selected) > len(prefix) + keep:
            del selected[len(prefix):len(prefix) + 2]
        if self._count_tokens(selected, cancel_event) > budget:
            raise ValueError("Mesaj modelin bağlam sınırını aşıyor; daha kısa bir mesaj gönderin.")
        return selected, len(body) - (len(selected) - len(prefix))

    def chat(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return self.chat_stream(messages)

    def chat_stream(self, messages: list[dict[str, str]], on_delta=None, *, cancel_event=None, continuation=False) -> dict[str, Any]:
        with self._chat_lock:
            return self._chat_stream_locked(messages, on_delta, cancel_event=cancel_event, continuation=continuation)

    def _chat_stream_locked(self, messages: list[dict[str, str]], on_delta=None, *, cancel_event=None, continuation=False) -> dict[str, Any]:
        if self.process is None or self.process.poll() is not None or not self._healthy():
            raise GemmaUnavailable("Gemma hazır değil; önce yerel modeli başlatın.")
        if not messages:
            raise ValueError("En az bir mesaj gerekli.")
        clean: list[dict[str, str]] = []
        for message in messages:
            if set(message) != {"role", "content"} or message["role"] not in {"system", "user", "assistant"}:
                raise ValueError("Mesaj biçimi veya rolü geçersiz.")
            if not isinstance(message["content"], str):
                raise ValueError("Mesaj içeriği metin olmalı.")
            if message is messages[-1] and len(message["content"].encode("utf-8")) > MAX_REQUEST_BYTES:
                raise ValueError("Mesaj 32 KiB sınırını aşıyor; daha kısa bir mesaj gönderin.")
            clean.append({"role": message["role"], "content": message["content"]})
        cancel_event = cancel_event if cancel_event is not None else threading.Event()
        with self._lifecycle_lock:
            if cancel_event.is_set():
                raise GemmaCancelled("Yanıt durduruldu.")
            self._active_cancel = cancel_event
        try:
            clean, omitted = self._fit_context(clean, cancel_event, continuation)
        except BaseException:
            with self._lifecycle_lock:
                if self._active_cancel is cancel_event:
                    self._active_cancel = None
            if cancel_event.is_set():
                raise GemmaCancelled("Yanıt durduruldu.")
            raise
        request_body = json.dumps({
            "model": self.spec.id, "messages": clean,
            "temperature": 1.0, "top_p": 0.95, "top_k": 64,
            "max_tokens": MAX_OUTPUT_TOKENS, "stream": True,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if self.spec.reasoning_off:
            body = json.loads(request_body)
            body["reasoning_effort"] = "none"
            request_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"http://{HOST}:{self.spec.port}/v1/chat/completions", data=request_body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                     "Authorization": f"Bearer {self.api_key}"}, method="POST",
        )
        answer_parts: list[str] = []
        answer_filter = _FinalAnswerFilter() if self.spec.id == GEMMA_SPEC.id else None
        usage: dict[str, Any] = {}
        timings: dict[str, Any] = {}
        saw_done = False
        finish_reason = None
        try:
            with self._open_stream(request, cancel_event) as response:
                for raw_line in iter(response.readline, b""):
                    if cancel_event.is_set():
                        raise GemmaCancelled("Gemma yanıtı durduruldu; tamamlanmamış mesaj kaydedilmedi.")
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].lstrip()
                    if data == "[DONE]":
                        saw_done = True
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError as error:
                        raise GemmaUnavailable("Gemma akışında geçersiz SSE JSON alındı.") from error
                    if not isinstance(payload, dict):
                        continue
                    final_usage = payload.get("usage")
                    if isinstance(final_usage, dict):
                        usage = final_usage
                    final_timings = payload.get("timings")
                    if isinstance(final_timings, dict):
                        timings = final_timings
                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if isinstance(choice, dict) and choice.get('finish_reason') is not None:
                        finish_reason = choice['finish_reason']
                    delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                    part = delta.get("content") if isinstance(delta, dict) else None
                    if part is None:
                        continue
                    if not isinstance(part, str):
                        raise GemmaUnavailable("Gemma metin dışı sohbet çıktısı verdi.")
                    safe_part = answer_filter.feed(part) if answer_filter else part
                    if safe_part:
                        answer_parts.append(safe_part)
                        if on_delta is not None:
                            on_delta(safe_part)
            if cancel_event.is_set():
                raise GemmaCancelled("Gemma yanıtı durduruldu; tamamlanmamış mesaj kaydedilmedi.")
        except GemmaCancelled:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as error:
            if cancel_event.is_set():
                raise GemmaCancelled("Gemma yanıtı durduruldu; tamamlanmamış mesaj kaydedilmedi.") from error
            raise GemmaUnavailable("Yerel Gemma akışı kesildi; tamamlanmamış yanıt kaydedilmedi.") from error
        finally:
            with self._lifecycle_lock:
                if self._active_cancel is cancel_event:
                    self._active_cancel = None
        if answer_filter:
            answer_filter.finish()
        if not saw_done:
            raise GemmaUnavailable("Gemma akışı tamamlanmadı; kısmi yanıt kaydedilmedi.")
        if finish_reason not in {'stop', 'length'}:
            raise GemmaUnavailable("Model yanıtı normal biçimde tamamlamadı; mesaj kaydedilmedi.")
        answer = "".join(answer_parts)
        if not answer.strip():
            raise GemmaUnavailable("Gemma boş yanıt verdi; mesaj kaydedilmedi.")
        return {"answer": answer, "usage": usage, "timings": timings, "finish_reason": finish_reason, "omitted_messages": omitted}

    def _stop_managed(self) -> None:
        process = self.process
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=30)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired as error:
                raise GemmaUnavailable("llama-server kapanmadı; süreç zorla sonlandırılmadı.") from error
            self.process = None
        self._release_owned_gpu()

    def _release_owned_gpu(self) -> None:
        lease = self._gpu_lease
        if lease is not None and self.resource_manager is not None:
            try:
                asyncio.run(self.resource_manager.release_and_verify(lease))
            except RuntimeError as error:
                raise GemmaUnavailable(f"Model kapandı ancak VRAM boşaltması doğrulanamadı: {error}") from error
            self._gpu_lease = None

    def _release_gpu_after_failed_start(self, lease: GpuLease | None) -> None:
        if lease is None or self.resource_manager is None:
            return
        self._gpu_lease = lease
        try:
            asyncio.run(self.resource_manager.release_and_verify(lease))
            self._gpu_lease = None
        except RuntimeError as error:
            raise GemmaUnavailable(f"Başarısız başlangıçtan sonra VRAM doğrulanamadı: {error}") from error

    def _ram_needed(self, files: tuple[Path, ...]) -> int:
        if self.resource_manager is not None:
            return GPU_MODE_RAM_RESERVE_BYTES
        return sum(path.stat().st_size for path in files) + RAM_RESERVE_BYTES

    @staticmethod
    def _available_ram() -> int | None:
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def _port_open(self) -> bool:
        try:
            with socket.create_connection((HOST, self.spec.port), timeout=0.15):
                return True
        except OSError:
            return False

    def _healthy(self) -> bool:
        try:
            request = urllib.request.Request(
                f"http://{HOST}:{self.spec.port}/health", headers={"Authorization": f"Bearer {self.api_key}"}
            )
            with LOCAL_OPENER.open(request, timeout=0.4) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False


class LocalLlmManager:
    """Allow-listed model switcher: exactly one application-managed LLM may own the GPU."""

    def __init__(self, resource_manager: GpuResourceManager, model_root: Path = DEFAULT_ROOT) -> None:
        self._lock = threading.Lock()
        self._servers = {
            model_id: GemmaServer(model_root, resource_manager=resource_manager, spec=spec)
            for model_id, spec in LOCAL_MODEL_SPECS.items()
        }

    def model_list(self) -> list[dict[str, Any]]:
        return [self._servers[model_id].status() for model_id in LOCAL_MODEL_SPECS]

    def status(self, model_id: str) -> dict[str, Any]:
        return self._server(model_id).status()

    def server(self, model_id: str) -> GemmaServer:
        """Internal adapters that need a ChatBackend get only an allow-listed server."""
        return self._server(model_id)

    def start(self, model_id: str) -> dict[str, Any]:
        with self._lock:
            target = self._server(model_id)
            target.preflight()
            stopped = []
            for other_id, other in self._servers.items():
                if other_id == model_id:
                    continue
                status = other.status()
                if status.get("managed"):
                    if status.get("active_request"):
                        raise GemmaUnavailable("Başka bir yerel model yanıt üretiyor; önce yanıtın bitmesini bekleyin.")
                    other.stop()
                    stopped.append(other)
            try:
                return target.start()
            except Exception:
                # Preflight failures never unload a working model; if loading
                # itself fails, try restoring the previously loaded model.
                for previous in stopped:
                    try:
                        previous.start()
                    except GemmaUnavailable:
                        pass
                raise

    def stop(self, model_id: str) -> dict[str, Any]:
        with self._lock:
            return self._server(model_id).stop()

    def stop_all(self) -> None:
        with self._lock:
            for server in self._servers.values():
                if server.status().get("managed"):
                    server.stop()

    def chat_stream(self, model_id: str, messages: list[dict[str, str]], on_delta=None, **options) -> dict[str, Any]:
        return self._server(model_id).chat_stream(messages, on_delta, **options)

    @staticmethod
    def validate_model_id(model_id: str) -> str:
        if model_id not in LOCAL_MODEL_SPECS:
            raise ValueError("Bilinmeyen veya izin verilmeyen yerel model.")
        return model_id

    def _server(self, model_id: str) -> GemmaServer:
        self.validate_model_id(model_id)
        return self._servers[model_id]
