"""Z-Image Turbo / ComfyUI integration manager.

Provides:
- Model and workflow readiness detection
- Managed lifecycle (start/stop) for ComfyUI
- Real image generation via local ComfyUI API
- Gallery listing and file serving for generated images
"""

from __future__ import annotations

import asyncio
import threading
import json
import base64
import logging
import math
import re
from contextlib import contextmanager
from uuid import uuid4
from urllib.parse import quote
from .image_files import inspect_image, MAX_IMAGE_BYTES
import os
import random
import secrets
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from .hardware import _meminfo_kib
from .resources import GpuResourceManager, GpuLease

class ImageCancelled(RuntimeError):
    pass


class ImageRecoveryRequired(RuntimeError):
    pass

logger = logging.getLogger(__name__)
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

MODEL_ROOT = Path(os.environ.get("AI_WORKSTATION_MODEL_DIR", Path.home() / "AI/models")).expanduser()
COMFY_ROOT = Path(os.environ.get("AI_WORKSTATION_COMFYUI_DIR", Path.home() / "AI/ComfyUI")).expanduser()
OUTPUT_DIR = COMFY_ROOT / "output/LocalAIWorkstation"

Z_IMAGE_DIFFUSION_MODELS = (
    MODEL_ROOT / "Z-image turbo/z_image_turbo_int8_convrot.safetensors",
    MODEL_ROOT / "Z-image turbo/z_image_turbo_bf16.safetensors",
)
Z_IMAGE_TEXT_ENCODER = MODEL_ROOT / "Z-image turbo/qwen_3_4b_fp8_mixed.safetensors"
Z_IMAGE_VAE = MODEL_ROOT / "Z-image turbo/ae.safetensors"
WORKFLOW_TEMPLATE = Path(__file__).resolve().parents[2] / "workflows/z-image-turbo-api.json"
FLUX_DIR = MODEL_ROOT / "flux2-klein"
FLUX_UNET = FLUX_DIR / "flux-2-klein-4b-fp8.safetensors"
FLUX_VAE = FLUX_DIR / "flux2-vae.safetensors"
FLUX_CLIP_CANDIDATES = (FLUX_DIR / "qwen_3_4b.safetensors", Z_IMAGE_TEXT_ENCODER)
EDIT_WORKFLOW_TEMPLATE = Path(__file__).resolve().parents[2] / "workflows/flux2-klein-edit-api.json"


def _port_open(host: str = "127.0.0.1", port: int = 8188) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


class ComfyManager:
    """Manages the local ComfyUI process and image generation."""

    def __init__(self, comfy_root: Path = COMFY_ROOT, output_dir: Path = OUTPUT_DIR, resource_manager: GpuResourceManager | None = None) -> None:
        self.resource_manager = resource_manager
        self._lease: GpuLease | None = None
        self._lifecycle = threading.RLock()
        self._execution = threading.Lock()
        self._cancel = threading.Event()
        self._prompt_id: str | None = None
        self._unit: str | None = None
        self._recovery_reason = ""
        self.log_path = Path(os.environ.get("AI_WORKSTATION_DATA", Path.home() / ".local/share/ai-workstation")) / "logs/comfy.log"
        self.comfy_root = comfy_root
        self.output_dir = output_dir
        self.process: subprocess.Popen[bytes] | None = None
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_installed(self) -> bool:
        return (self.comfy_root / "main.py").is_file() and (self.comfy_root / ".venv/bin/python").is_file()

    def is_running(self) -> bool:
        return _port_open("127.0.0.1", 8188)

    def check_assets(self) -> tuple[bool, list[dict[str, Any]]]:
        assets: list[dict[str, Any]] = []
        diffusion_present = False
        for p in Z_IMAGE_DIFFUSION_MODELS:
            present = p.is_file()
            if present and p == Z_IMAGE_DIFFUSION_MODELS[0]:
                diffusion_present = True
            assets.append({
                "path": str(p),
                "filename": p.name,
                "role": "diffusion",
                "present": present,
                "bytes": p.stat().st_size if present else None,
            })
        for role, p in (("text_encoder", Z_IMAGE_TEXT_ENCODER), ("vae", Z_IMAGE_VAE)):
            present = p.is_file()
            assets.append({
                "path": str(p),
                "filename": p.name,
                "role": role,
                "present": present,
                "bytes": p.stat().st_size if present else None,
            })
        encoder_present = Z_IMAGE_TEXT_ENCODER.is_file()
        vae_present = Z_IMAGE_VAE.is_file()
        ready = diffusion_present and encoder_present and vae_present
        return ready, assets

    def status(self) -> dict[str, Any]:
        models_ready, assets = self.check_assets()
        installed = self.is_installed()
        workflow_ready = WORKFLOW_TEMPLATE.is_file()
        running = self.is_running()
        managed = self.process is not None and self.process.poll() is None
        available_ram = _meminfo_kib().get("MemAvailable", 0) * 1024
        owner = self.resource_manager.active_job_id if self.resource_manager else None
        start_reason = ""
        if owner and owner != "comfyui":
            start_reason = "Sohbet modeli GPU belleğini kullanıyor. Üst çubuktan belleği boşaltın."
        elif available_ram < 10 * 1024**3:
            start_reason = "Görsel servisini başlatmak için en az 10 GiB kullanılabilir RAM gerekiyor."
        generation_available = models_ready and installed and running and workflow_ready and managed and not self._recovery_reason

        if self._recovery_reason:
            reason = self._recovery_reason
        elif not models_ready:
            reason = "Z-Image Turbo için gereken model dosyaları eksik (INT8 diffusion, Qwen text encoder ve VAE gerekli)."
        elif not installed:
            reason = "İzole ComfyUI ortamı bulunamadı."
        elif not workflow_ready:
            reason = "Doğrulanmış Z-Image Turbo API workflow dosyası bulunamadı."
        elif not running:
            reason = "ComfyUI servisi kapalı. 'ComfyUI'yi Başlat' düğmesine basarak servisi açabilirsiniz."
        elif not managed:
            reason = "8188 portunda dışarıdan başlatılmış bir servis var. Bu uygulama onu yönetmiyor; kendi terminalinden kapatıp burada başlatın."
        else:
            reason = "ComfyUI hazır ve Z-Image Turbo INT8 modeliyle üretime bağlanmış durumda."

        return {
            "model": "Z-Image Turbo INT8",
            "assets": assets,
            "models_ready": models_ready,
            "comfy_root": str(self.comfy_root),
            "comfy_installed": installed,
            "workflow_path": str(WORKFLOW_TEMPLATE),
            "workflow_ready": workflow_ready,
            "comfy_running": running,
            "managed": self.process is not None and self.process.poll() is None,
            "generation_available": generation_available,
            "reason": reason,
            "log_path": str(self.log_path),
            "output_dir": str(self.output_dir.resolve()),
            "memory_protected": True,
            "start_allowed": installed and not running and not start_reason,
            "start_reason": start_reason,
            "busy": self._execution.locked(),
            "gpu_owner": self.resource_manager.active_job_id if self.resource_manager else None,
            "edit": self.edit_status(),
        }

    def _edit_clip(self) -> Path | None:
        return next((p for p in FLUX_CLIP_CANDIDATES if p.is_file()), None)

    def edit_status(self) -> dict[str, Any]:
        clip = self._edit_clip()
        assets = [
            {"filename": FLUX_UNET.name, "role": "diffusion", "present": FLUX_UNET.is_file()},
            {"filename": FLUX_VAE.name, "role": "vae", "present": FLUX_VAE.is_file()},
            {"filename": clip.name if clip else "qwen_3_4b.safetensors", "role": "text_encoder", "present": clip is not None},
        ]
        missing = [a["filename"] for a in assets if not a["present"]]
        files_ready = not missing and EDIT_WORKFLOW_TEMPLATE.is_file()
        return {
            "model": "FLUX.2 klein 4B (FP8)",
            "assets": assets,
            "missing": missing,
            "ready": files_ready,
            "available": not self._recovery_reason and files_ready and self.is_installed() and self.is_running() and self.process is not None and self.process.poll() is None,
            "hint": "" if files_ready else "Eksik dosyalar için: bash scripts/download_flux2_klein.sh — sonra ComfyUI'yi yeniden başlatın.",
        }

    @staticmethod
    def _request_json(path: str, body: dict | None = None, timeout: float = 5) -> dict:
        request = urllib.request.Request('http://127.0.0.1:8188' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json'})
        with LOCAL_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(16 * 1024**2)
        value = json.loads(raw) if raw else {}
        if not isinstance(value, dict):
            raise ValueError('ComfyUI geçersiz yanıt verdi.')
        return value

    def _stop_uncertain_work(self):
        # A lost acknowledgement can arrive after validation has enqueued work.
        # Stop our owned service before reporting failure or deleting its inputs.
        try:
            with self._lifecycle:
                self._stop_process()
        except Exception as error:
            self._recovery_reason = 'Görsel işi doğrulanamadı; servisi durdurup yeniden başlatın.'
            if self.resource_manager:
                self.resource_manager.require_recovery(self._recovery_reason)
            raise ImageRecoveryRequired(self._recovery_reason) from error

    def _run_workflow(self, workflow: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
        if self._cancel.is_set():
            raise ImageCancelled('Görsel işi iptal edildi.')
        prompt_id = self._prompt_id or str(uuid4())
        self._prompt_id = prompt_id
        try:
            data = self._request_json('/prompt', {'prompt':workflow,
                'prompt_id':prompt_id, 'client_id':'workstation-' + prompt_id}, timeout=10)
            if data.get('prompt_id') != prompt_id:
                raise ValueError('ComfyUI iş kimliğini doğrulamadı.')
        except urllib.error.HTTPError as error:
            if error.code >= 500:
                self._stop_uncertain_work()
            raise RuntimeError('ComfyUI workflow isteğini reddetti.') from error
        except Exception as error:
            self._stop_uncertain_work()
            if self._cancel.is_set():
                raise ImageCancelled('Görsel işi iptal edildi.') from error
            raise RuntimeError('İş gönderimi doğrulanamadı; görsel servisi durduruldu. Yeniden başlatın.') from error
        start = time.monotonic()
        try:
            while time.monotonic() - start < 600:
                if self._cancel.wait(.25):
                    raise ImageCancelled('Görsel işi iptal edildi.')
                if self.process is None or self.process.poll() is not None:
                    raise RuntimeError('Görsel servisi kapandı veya bellek sınırına ulaştı. Belleği boşaltıp yeniden başlatın.')
                try:
                    item = self._request_json('/history/' + prompt_id).get(prompt_id)
                except (OSError, ValueError):
                    continue
                if self._cancel.is_set():
                    raise ImageCancelled('Görsel işi iptal edildi.')
                if not item:
                    continue
                info = item.get('status', {})
                if info.get('status_str') == 'success':
                    images = []
                    for node in item.get('outputs', {}).values():
                        images.extend(node.get('images', []))
                    if not images:
                        raise RuntimeError('ComfyUI tamamlandı ancak çıktı görseli bulunamadı.')
                    return images, time.monotonic() - start
                if info.get('status_str') == 'error':
                    raise RuntimeError('ComfyUI işi başarısız oldu; ayrıntılar servis günlüğünde.')
            raise TimeoutError('Görsel üretimi zaman aşımına uğradı (10 dakika).')
        except BaseException:
            self._abort_workflow(prompt_id)
            raise

    @contextmanager
    def _reference_file(self, value: str):
        raw = self._decode_image(value)
        info = inspect_image(raw, verify=False)
        directory = self.comfy_root / 'input'
        directory.mkdir(parents=True, exist_ok=True)
        name = 'LocalAIWorkstation_ref_' + secrets.token_hex(12) + info['extension']
        path = directory / name
        try:
            path.write_bytes(raw)
            yield name
        finally:
            if not self._recovery_reason:
                path.unlink(missing_ok=True)

    def output_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename or '..' in filename or '\\' in filename:
            raise ValueError('Geçersiz görsel dosya adı.')
        path = self.output_dir / filename
        if path.is_symlink() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'} or not path.is_file():
            raise ValueError('Çıktı görseli bulunamadı.')
        return path

    def _result(self, images: list, meta: dict) -> dict:
        first = images[0]
        if first.get('type', 'output') != 'output' or first.get('subfolder', 'LocalAIWorkstation') != 'LocalAIWorkstation':
            raise ValueError('Çıktı görseli beklenen klasörde değil.')
        path = self.output_path(first.get('filename', ''))
        info = inspect_image(path)
        stat = path.stat()
        result = {**meta, 'success':True, 'filename':path.name,
            'url':'/api/v1/image/output/' + quote(path.name), 'path':str(path.resolve()),
            'width':info['width'], 'height':info['height'], 'bytes':stat.st_size, 'mtime':stat.st_mtime}
        temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.meta.json.part')
        try:
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False)
            temporary.replace(path.with_name(path.name + '.meta.json'))
        except OSError:
            logger.exception('Image metadata could not be saved')
        finally:
            temporary.unlink(missing_ok=True)
        return result

    def inpaint_status(self) -> dict:
        from .inpaint_workflows import assets
        node_ready=(self.comfy_root/'custom_nodes/comfyui-inpaint-nodes/__init__.py').is_file()
        running=not self._recovery_reason and self.process is not None and self.process.poll() is None and self.is_running()
        return {engine:{'ready':node_ready and all(p.is_file() for p in assets(self.comfy_root,engine)),
                        'available':running and node_ready and all(p.is_file() for p in assets(self.comfy_root,engine)),
                        'missing':[p.name for p in assets(self.comfy_root,engine) if not p.is_file()],
                        'node_ready':node_ready}
                for engine in ('lama','sdxl')}

    def inpaint(self, prompt: str, init_image: str, seed: int, edit_mask: str | None, engine: str) -> dict:
        from .inpaint_workflows import inputs, workflow
        from .masked_edit import prepare_region, composite_region
        if not edit_mask:
            raise ValueError('Önce fırçayla bir alan işaretleyin.')
        if not self.inpaint_status()[engine]['ready']:
            raise RuntimeError('Alan düzenleme modellerini kurun: bash scripts/krita-modelleri-kur.sh')
        required='INPAINT_InpaintWithModel' if engine=='lama' else 'INPAINT_ApplyFooocusInpaint'
        if required not in self._request_json('/object_info/'+required):
            raise RuntimeError('Alan düzenleme düğümleri yüklenmedi. ComfyUI servisini durdurup yeniden başlatın.')
        started=time.monotonic()
        source, selection, context, _=prepare_region(self._decode_image(init_image),self._decode_image(edit_mask))
        pixels, mask, size=inputs(source,selection,context,engine)
        actual_seed=random.randint(1,2**31-1) if seed<0 else int(seed)
        with self._reference_file(base64.b64encode(pixels).decode('ascii')) as image_name, self._reference_file(base64.b64encode(mask).decode('ascii')) as mask_name:
            images, duration=self._run_workflow(workflow(engine,image_name,mask_name,prompt,actual_seed))
        first=images[0]
        if first.get('type','output')!='output' or first.get('subfolder','LocalAIWorkstation')!='LocalAIWorkstation':
            raise ValueError('Çıktı görseli beklenen klasörde değil.')
        merged=composite_region(source,selection,context,self.output_path(first.get('filename','')).read_bytes())
        destination=self.output_dir/('Krita-Region-'+uuid4().hex+'.png')
        with destination.open('xb') as stream:stream.write(merged)
        return self._result([{**first,'filename':destination.name}],{
            'prompt':prompt.strip(),'seed':actual_seed,'steps':0 if engine=='lama' else 20,
            'cfg':0 if engine=='lama' else 5.0,'engine':engine,'masked':True,'mode':'edit',
            'processing_width':size[0],'processing_height':size[1],
            'duration_seconds':round(time.monotonic()-started,2),'workflow_seconds':round(duration,2),
            'created_at':time.strftime('%Y-%m-%d %H:%M:%S')})

    def edit(self, prompt: str, init_image: str, seed: int = -1, edit_mask: str | None = None, engine: str = 'flux') -> dict[str, Any]:
        """Instruction-based image edit with FLUX.2 klein 4B via ComfyUI."""
        if not self.is_running():
            raise RuntimeError("ComfyUI servisi çalışmıyor. Lütfen önce servisi başlatın.")
        if engine not in {'flux','lama','sdxl'}:
            raise ValueError('Bilinmeyen alan düzenleme motoru.')
        if engine!='flux':
            return self.inpaint(prompt,init_image,seed,edit_mask,engine)
        status = self.edit_status()
        if not status["ready"]:
            raise RuntimeError("FLUX.2 klein dosyaları eksik: " + ", ".join(status["missing"]) + ". " + status["hint"])
        if not prompt or not prompt.strip():
            raise ValueError("Düzenleme talimatı boş olamaz.")
        if not init_image:
            raise ValueError("Düzenlemek için bir girdi görseli gerekli.")
        actual_seed = random.randint(1, 2**31 - 1) if seed < 0 else int(seed)
        region = None
        if edit_mask:
            from .masked_edit import prepare_region
            source, selected, context, cropped = prepare_region(self._decode_image(init_image), self._decode_image(edit_mask))
            region = (source, selected, context)
            init_image = base64.b64encode(cropped).decode('ascii')
        with self._reference_file(init_image) as init_name:
            with EDIT_WORKFLOW_TEMPLATE.open(encoding='utf-8') as stream:
                workflow = json.load(stream)
            clip = self._edit_clip()
            workflow['2']['inputs']['clip_name'] = clip.name if clip else 'qwen_3_4b.safetensors'
            workflow['4']['inputs']['image'] = init_name
            workflow['7']['inputs']['text'] = prompt.strip()
            workflow['15']['inputs']['noise_seed'] = actual_seed
            if region:
                from .masked_edit import region_megapixels
                workflow['5']['inputs']['megapixels'] = region_megapixels(region[2])
            processing_mp = workflow['5']['inputs']['megapixels']
            logger.info('Image edit: masked=%s processing_megapixels=%.4f', bool(region), processing_mp)
            images, duration = self._run_workflow(workflow)
            if region:
                from .masked_edit import composite_region
                first=images[0]
                if first.get('type','output')!='output' or first.get('subfolder','LocalAIWorkstation')!='LocalAIWorkstation':
                    raise ValueError('Çıktı görseli beklenen klasörde değil.')
                generated=self.output_path(first.get('filename',''))
                merged=composite_region(*region,generated.read_bytes())
                destination=self.output_dir/('Krita-Region-'+uuid4().hex+'.png')
                with destination.open('xb') as stream:stream.write(merged)
                images=[{**first,'filename':destination.name}]
            return self._result(images, {'prompt':prompt.strip(), 'seed':actual_seed,
                'steps':4, 'cfg':1.0, 'duration_seconds':round(duration, 2),
                'created_at':time.strftime('%Y-%m-%d %H:%M:%S'), 'mode':'edit', 'masked':bool(region),
                'processing_megapixels':processing_mp})

    def _abort_workflow(self, prompt_id: str) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self._request_json('/queue', {'delete':[prompt_id]}, timeout=2)
            self._request_json('/interrupt', {'prompt_id':prompt_id}, timeout=2)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                queue = self._request_json('/queue', timeout=2)
                if not any(len(item) > 1 and item[1] == prompt_id
                    for item in queue.get('queue_running', []) + queue.get('queue_pending', [])):
                    return
                time.sleep(.2)
        except (OSError, ValueError):
            logger.exception('ComfyUI cancellation could not be confirmed')
        self._stop_uncertain_work()

    def execute(self, mode: str, payload: dict, cancel: threading.Event, *, job_id: str | None = None) -> dict:
        with self._execution:
            with self._lifecycle:
                if self.process is None or self.process.poll() is not None or not self.is_running():
                    raise RuntimeError("Önce uygulamanın görsel servisini başlatın.")
                if self._recovery_reason:
                    raise ImageRecoveryRequired(self._recovery_reason)
                self._cancel = cancel
                self._prompt_id = job_id
            try:
                if cancel.is_set():
                    raise ImageCancelled("Görsel işi iptal edildi.")
                return self.edit(**payload) if mode == "edit" else self.generate(**payload)
            finally:
                self._prompt_id = None

    def start(self) -> dict[str, Any]:
        with self._lifecycle:
            if self.is_running():
                if self.process is None or self.process.poll() is not None:
                    raise RuntimeError("8188 portu başka bir servis tarafından kullanılıyor.")
                if self._recovery_reason:
                    raise ImageRecoveryRequired(self._recovery_reason)
                return self.status()
            if self.process is not None or self._lease is not None:
                self._stop_process()
            if not self.is_installed():
                raise RuntimeError("ComfyUI kurulumu bulunamadı.")
            available = _meminfo_kib().get("MemAvailable", 0) * 1024
            if available < 10 * 1024**3:
                raise RuntimeError("Görsel servisi için en az 10 GiB kullanılabilir RAM gerekiyor. Diğer ağır uygulamaları kapatın.")
            if not shutil.which("systemd-run") or not shutil.which("systemctl"):
                raise RuntimeError("Görsel servisini bellek sınırıyla çalıştırmak için systemd kullanıcı servisi gerekli.")
            memory_limit = min(10 * 1024**3, available - 2 * 1024**3)
            if self.resource_manager:
                self._lease = asyncio.run(self.resource_manager.acquire("comfyui", 12 * 1024**3))
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                if self.log_path.exists() and self.log_path.stat().st_size > 8 * 1024**2:
                    self.log_path.replace(self.log_path.with_suffix(".previous.log"))
                env = os.environ.copy()
                env["TORCH_BLAS_PREFER_HIPBLASLT"] = "0"
                self._unit = f"ai-workstation-image-{secrets.token_hex(6)}"
                with self.log_path.open("ab") as log:
                    self.process = subprocess.Popen([
                        "systemd-run", "--user", "--quiet", "--pipe", "--wait", "--collect",
                        f"--unit={self._unit}", "--service-type=exec",
                        f"--property=MemoryMax={memory_limit}", f"--property=MemoryHigh={int(memory_limit * .9)}",
                        "--property=MemorySwapMax=536870912", "--property=OOMPolicy=stop",
                        "--property=KillMode=control-group", "--property=TimeoutStopSec=15",
                        f"--working-directory={self.comfy_root}", "--setenv=TORCH_BLAS_PREFER_HIPBLASLT=0",
                        str(self.comfy_root / ".venv/bin/python"), str(self.comfy_root / "main.py"),
                        "--listen", "127.0.0.1", "--port", "8188", "--disable-pinned-memory", "--disable-auto-launch",
                        # Reuse loaders for the current graph. Classic cache drops
                        # keys outside the next graph, unlike cross-workflow LRU.
                        # The systemd RAM/swap limits remain enforced above.
                        "--disable-async-offload", "--fast-disk", "--cache-classic",
                    ], cwd=str(self.comfy_root), env=env, stdout=log, stderr=subprocess.STDOUT)
                for _ in range(120):
                    if self.process.poll() is not None:
                        raise RuntimeError(f"ComfyUI başlatılamadı. Günlük: {self.log_path}")
                    if self.is_running():
                        self._cleanup_stale_inputs()
                        return self.status()
                    time.sleep(0.5)
                raise RuntimeError(f"ComfyUI başlangıcı zaman aşımına uğradı. Günlük: {self.log_path}")
            except BaseException:
                self._stop_process()
                raise

    def _cleanup_stale_inputs(self):
        # Called only after starting our own idle service, never on an external
        # service or while a previous prompt could still be using these files.
        try:
            queue = self._request_json('/queue')
            if queue.get('queue_running') or queue.get('queue_pending'):
                return
            for path in (self.comfy_root / 'input').glob('LocalAIWorkstation_*'):
                if not path.is_symlink() and path.is_file() and re.fullmatch(r'LocalAIWorkstation_(?:edit|init|ref)_[0-9a-f]{12,24}\.(?:png|jpg|webp)', path.name):
                    path.unlink()
        except (OSError, ValueError):
            logger.exception('Old image references could not be cleaned')

    def _stop_process(self) -> None:
        if self._unit:
            result = subprocess.run(["systemctl", "--user", "stop", self._unit], capture_output=True, timeout=25)
            # An already-collected unit has no remaining process to stop.
            if result.returncode and self.process is not None and self.process.poll() is None:
                raise RuntimeError("Görsel servisi durdurulamadı; GPU kilidi korundu.")
            self._unit = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None
        if self._lease is not None and self.resource_manager:
            asyncio.run(self.resource_manager.release_and_verify(self._lease))
            self._lease = None
        self._recovery_reason = ''

    def stop(self) -> dict[str, Any]:
        with self._lifecycle:
            if self._execution.locked():
                raise RuntimeError("Önce devam eden görsel işini iptal edin veya tamamlanmasını bekleyin.")
            self._stop_process()
            return self.status()

    def generate(
        self,
        prompt: str,
        seed: int = -1,
        steps: int = 8,
        cfg: float = 1.0,
        width: int = 1024,
        height: int = 1024,
        init_image: str | None = None,
        denoise: float = 0.6,
    ) -> dict[str, Any]:
        if not self.is_running():
            raise RuntimeError("ComfyUI servisi çalışmıyor. Lütfen önce servisi başlatın.")
        if not prompt or not prompt.strip():
            raise ValueError("Prompt boş olamaz.")

        clean_prompt = prompt.strip()
        steps = max(1, min(int(steps), 30))
        cfg = max(0.5, min(float(cfg), 10.0))
        width = max(256, min(int(width), 2048))
        height = max(256, min(int(height), 2048))
        actual_seed = random.randint(1, 2**31 - 1) if seed < 0 else int(seed)

        with open(WORKFLOW_TEMPLATE, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        workflow["4"]["inputs"]["text"] = clean_prompt
        workflow["6"]["inputs"]["width"] = width
        workflow["6"]["inputs"]["height"] = height
        workflow["8"]["inputs"]["seed"] = actual_seed
        workflow["8"]["inputs"]["steps"] = steps
        workflow["8"]["inputs"]["cfg"] = cfg

        def finish(mode):
            images, duration = self._run_workflow(workflow)
            return self._result(images, {'prompt':clean_prompt, 'seed':actual_seed,
                'steps':steps, 'cfg':cfg, 'duration_seconds':round(duration, 2),
                'created_at':time.strftime('%Y-%m-%d %H:%M:%S'), 'mode':mode})
        if init_image:
            with self._reference_file(init_image) as init_name:
                workflow['11'] = {'class_type':'LoadImage', 'inputs':{'image':init_name}}
                workflow['12'] = {'class_type':'ImageScale', 'inputs':{'image':['11',0], 'upscale_method':'lanczos', 'width':width, 'height':height, 'crop':'center'}}
                workflow['13'] = {'class_type':'VAEEncode', 'inputs':{'pixels':['12',0], 'vae':['3',0]}}
                workflow['8']['inputs']['latent_image'] = ['13',0]
                workflow['8']['inputs']['denoise'] = max(.05, min(float(denoise), 1.0))
                return finish('img2img')
        return finish('text2img')

    @staticmethod
    def _decode_image(value: str) -> bytes:
        if len(value) > 17 * 1024**2:
            raise ValueError('Görsel 12 MB altında olmalı.')
        try:
            raw = base64.b64decode(value.split(',', 1)[-1], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Girdi görseli geçerli base64 değil.') from error
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Görsel 12 MB altında olmalı.')
        inspect_image(raw)
        return raw

    def list_gallery(self) -> list[dict[str, Any]]:
        if not self.output_dir.is_dir():
            return []
        results = []
        for file in self.output_dir.iterdir():
            try:
                if file.is_symlink() or not file.is_file() or file.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
                    continue
                info = inspect_image(file, verify=False)
                stat = file.stat()
                meta_path = file.with_name(file.name + '.meta.json')
                meta = {}
                if not meta_path.is_symlink() and meta_path.is_file() and meta_path.stat().st_size <= 1024**2:
                    try:
                        value = json.loads(meta_path.read_text(encoding='utf-8'))
                        if isinstance(value, dict):
                            meta = value
                    except (OSError, ValueError):
                        pass
                item = {'filename':file.name, 'url':'/api/v1/image/output/' + quote(file.name),
                    'path':str(file.resolve()), 'bytes':stat.st_size, 'mtime':stat.st_mtime,
                    'created_at':time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime)),
                    'prompt':'', 'width':info['width'], 'height':info['height']}
                for key in ('created_at','prompt','mode'):
                    if isinstance(meta.get(key), str):
                        item[key] = meta[key]
                for key in ('seed','steps','cfg','duration_seconds'):
                    if isinstance(meta.get(key), (int,float)) and not isinstance(meta[key],bool) and abs(meta[key]) <= 2**53 - 1 and math.isfinite(meta[key]):
                        item[key] = meta[key]
                results.append(item)
            except (OSError, ValueError, OverflowError):
                continue
        return sorted(results, key=lambda item:(item['mtime'], item['filename']), reverse=True)
