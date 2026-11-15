"""Loopback-only API for the local AI workstation."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from uuid import uuid4
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .krita_bridge import KritaBridge
from .krita_api import create_krita_router
from .image_files import inspect_image
from .data_lock import DataDirectoryLock
from .catalog import inspect_catalog, model_root
from .audio_status import audio_status
from .chat_stream import ChatStreamResponse
from .audio_jobs import AudioJobs, AudioRunner, AudioRequest
from .comfy import ComfyManager
from .image_jobs import ImageJobs, ImageRequest, ImageInputRequest
from .conversations import CodeAssistantChat, ConversationRepository, LocalAssistantChat, ConversationBusy
from .folder_picker import choose_project_folder
from .hardware import SystemGpuObservationProvider, snapshot
from .llm import GemmaCancelled, LocalLlmManager, GemmaUnavailable
from .resources import GpuResourceManager
from .projects import ProjectService
from .security import LocalApiSecurity
from .settings import SettingsService
from .storage import open_database

APP_DATA = Path(os.environ.get("AI_WORKSTATION_DATA", Path.home() / ".local/share/ai-workstation")).expanduser().resolve()
DATA_LOCK = DataDirectoryLock(APP_DATA)
DATABASE = open_database(APP_DATA / "workstation.sqlite3")
SETTINGS = SettingsService(DATABASE)
PROJECTS = ProjectService(DATABASE)
GPU_MANAGER = GpuResourceManager(SystemGpuObservationProvider())
LLMS = LocalLlmManager(GPU_MANAGER)
COMFY_MANAGER = ComfyManager(resource_manager=GPU_MANAGER)
IMAGE_JOBS = ImageJobs(APP_DATA / "workstation.sqlite3", COMFY_MANAGER)
AUDIO_RUNNER = AudioRunner(model_root() / "audio", APP_DATA / "audio", GPU_MANAGER)
AUDIO_JOBS = AudioJobs(APP_DATA / "workstation.sqlite3", AUDIO_RUNNER)
GEMMA = LLMS.server("gemma-4-12b")
CONVERSATIONS = ConversationRepository(DATABASE)
CODE_CHAT = CodeAssistantChat(CONVERSATIONS, PROJECTS, GEMMA)
ASSISTANT_CHAT = LocalAssistantChat(CONVERSATIONS, PROJECTS, GEMMA)

app = FastAPI(
    title="Yerel AI Çalışma İstasyonu",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
)
KRITA_BRIDGE = KritaBridge(APP_DATA / "krita-editor")
app.include_router(create_krita_router(KRITA_BRIDGE))
CSRF_TOKEN = secrets.token_urlsafe(32)
app.add_middleware(LocalApiSecurity, csrf_token=CSRF_TOKEN)


@app.on_event("shutdown")
def shutdown_managed_services() -> None:
    """Wait for any current inference and gracefully stop this app's CPU model process."""
    KRITA_BRIDGE.close()
    AUDIO_JOBS.close()
    IMAGE_JOBS.close()
    try:
        LLMS.stop_all()
    except GemmaUnavailable:
        # Never force-kill a model service that did not stop on request.
        pass
    try:
        COMFY_MANAGER.stop()
    except Exception:
        pass
    DATABASE.close()
    DATA_LOCK.close()


@app.get("/api/v1/session")
def session() -> JSONResponse:
    """Give the local frontend a per-process CSRF token; never cache it."""
    return JSONResponse(
        {"csrf_token": CSRF_TOKEN},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "durum": "Yerel AI API çalışıyor; model hazırlığı modül durumlarından izlenir."}


@app.get("/api/v1/hardware")
def hardware() -> dict[str, object]:
    return {**snapshot(), "gpu_state": GPU_MANAGER.state, "gpu_owner": GPU_MANAGER.active_job_id, "gpu_reason": GPU_MANAGER.reason}


@app.get("/api/v1/audio/status")
def audio_preparation_status() -> dict:
    status = audio_status(model_root() / "audio")
    status["engine_available"] = AUDIO_RUNNER.available()
    status['engines']={engine:AUDIO_RUNNER.available(engine) for engine in ('tts','conversion','singing')}
    status["active_job_id"] = AUDIO_JOBS.active_job_id
    return status


@app.post("/api/v1/audio/references")
async def upload_audio_reference(request: Request) -> dict:
    try:
        identifier = AUDIO_JOBS.begin_upload()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    target = AUDIO_RUNNER.reference_path(identifier)
    temporary = target.with_name(target.name + ".part")
    size = 0
    completed = False
    try:
        with temporary.open("xb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 100 * 1024**2:
                    raise HTTPException(status_code=413, detail="Reference recording exceeds 100 MB.")
                stream.write(chunk)
        if not size:
            raise HTTPException(status_code=422, detail="Reference recording is empty.")
        temporary.replace(target)
        completed = True
    finally:
        AUDIO_JOBS.finish_upload(identifier, completed=completed)
    return {"reference_id": identifier}


@app.get("/api/v1/audio/jobs")
def audio_job_list(limit: int = Query(default=50, ge=1, le=100), before: int | None = Query(default=None, ge=1)) -> dict:
    return AUDIO_JOBS.page(limit=limit, before=before)


@app.delete('/api/v1/audio/references/{identifier}')
def discard_audio_reference(identifier: str) -> dict:
    try:
        AUDIO_JOBS.discard_reference(identifier)
        return {'deleted':True}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/audio/jobs")
def submit_audio_job(request: AudioRequest) -> dict:
    try:
        return AUDIO_JOBS.submit(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/audio/jobs/{identifier}/cancel")
def cancel_audio_job(identifier: str) -> dict:
    try:
        return AUDIO_JOBS.cancel(identifier)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Audio job not found.") from error


@app.get("/api/v1/audio/jobs/{identifier}/output")
def audio_job_output(identifier: str) -> FileResponse:
    try:
        path = AUDIO_JOBS.output_path(identifier)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Audio output not found.") from error
    return FileResponse(path, media_type="audio/wav", filename=f"voice-{identifier[:8]}.wav", content_disposition_type="inline")


@app.get("/api/v1/models")
def models() -> dict[str, object]:
    """Read-only allow-listed inventory; hash scans require an explicit request."""
    return {"model_root": str(model_root()), "models": inspect_catalog()}


@app.get("/api/v1/image/z-image-turbo/status")
def z_image_turbo_status() -> dict[str, object]:
    """Status and readiness check for Z-Image Turbo / ComfyUI."""
    return COMFY_MANAGER.status()


@app.post("/api/v1/image/z-image-turbo/start")
def z_image_turbo_start() -> dict[str, object]:
    """Start local managed ComfyUI process."""
    try:
        return COMFY_MANAGER.start()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/v1/image/z-image-turbo/stop")
def z_image_turbo_stop() -> dict[str, object]:
    """Stop local managed ComfyUI process."""
    try:
        if IMAGE_JOBS.active:
            raise RuntimeError("Önce devam eden görsel işini iptal edin veya tamamlanmasını bekleyin.")
        return COMFY_MANAGER.stop()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v1/diagnostics")
def diagnostics() -> dict:
    import re
    logs = []
    for name, path in [("Görsel servisi", COMFY_MANAGER.log_path), ("Audio / VoxCPM2", AUDIO_RUNNER.log_path)] + [(item.spec.name, item.log_path) for item in LLMS._servers.values()]:
        try:
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 8000))
                content = stream.read().decode("utf-8", errors="replace")
            content = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", content)
            for server in LLMS._servers.values():
                content = content.replace(server.api_key, "[gizli]")
        except FileNotFoundError:
            content = "Henüz günlük kaydı yok."
        logs.append({"name": name, "path": str(path), "text": content})
    return {"logs": logs}


@app.get("/api/v1/runtime")
async def runtime_status() -> dict:
    return {"gpu": {"state": GPU_MANAGER.state, "owner": GPU_MANAGER.active_job_id, "reason": GPU_MANAGER.reason},
            "models": await asyncio.to_thread(LLMS.model_list),
            "image": await asyncio.to_thread(COMFY_MANAGER.status),
            "jobs": (await asyncio.to_thread(IMAGE_JOBS.list)) + (await asyncio.to_thread(AUDIO_JOBS.list))}


@app.get("/api/v1/image/jobs")
def image_jobs(limit: int = Query(default=50, ge=1, le=100), before: int | None = Query(default=None, ge=1), search: str = Query(default='', max_length=200)) -> dict:
    return IMAGE_JOBS.page(limit=limit, before=before, search=search)


@app.get("/api/v1/image/jobs/{job_id}")
def image_job(job_id: str) -> dict:
    try:
        return IMAGE_JOBS.get(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post('/api/v1/image/input/validate')
def validate_image_input(payload: ImageInputRequest) -> dict:
    try:
        raw = COMFY_MANAGER._decode_image(payload.init_image)
        return inspect_image(raw, verify=False)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get('/api/v1/image/edit-engines')
def edit_engines() -> dict:
    return COMFY_MANAGER.inpaint_status()


@app.post("/api/v1/image/jobs", status_code=202)
def submit_image_job(payload: ImageRequest) -> dict:
    try:
        return IMAGE_JOBS.submit(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/image/jobs/{job_id}/cancel")
def cancel_image_job(job_id: str) -> dict:
    try:
        return IMAGE_JOBS.cancel(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


async def legacy_image_job(request: Request, mode: str) -> dict:
    from pydantic import ValidationError
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("JSON nesnesi gerekli.")
        job = await asyncio.to_thread(IMAGE_JOBS.submit, ImageRequest(**{**payload, "mode": mode,
            "idempotency_key": request.headers.get("Idempotency-Key", secrets.token_hex(16))}))
    except (ValueError, ValidationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    while job["status"] in {"QUEUED", "PREPARING", "RUNNING", "CANCELLING"}:
        await asyncio.sleep(1)
        job = await asyncio.to_thread(IMAGE_JOBS.get, job["id"])
    if job["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=job.get("error", "İş tamamlanamadı."))
    return job["result"]


@app.post("/api/v1/image/z-image-turbo/generate")
async def z_image_turbo_generate(request: Request) -> dict:
    return await legacy_image_job(request, "generate")


@app.post("/api/v1/image/flux2-klein/edit")
async def flux2_klein_edit(request: Request) -> dict:
    return await legacy_image_job(request, "edit")


@app.get("/api/v1/image/gallery")
def z_image_gallery() -> dict[str, object]:
    """List previously generated output images."""
    return {"images": COMFY_MANAGER.list_gallery()}


@app.get("/api/v1/image/output/{filename}")
def z_image_output_file(filename: str) -> FileResponse:
    """Safely serve generated image files."""
    try:
        file_path = COMFY_MANAGER.output_path(filename)
    except ValueError as error:
        raise HTTPException(status_code=404, detail='Görsel dosyası bulunamadı.') from error
    safe_name = file_path.name

    media_type = "image/png"
    if safe_name.lower().endswith(".webp"):
        media_type = "image/webp"
    elif safe_name.lower().endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"

    return FileResponse(file_path, media_type=media_type)


@app.get("/api/v1/settings")
async def get_settings() -> dict[str, object]:
    return SETTINGS.get_all()


@app.put("/api/v1/settings/{key}")
async def update_setting(key: str, request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"value"}:
            raise ValueError("İstek yalnızca value alanı içermeli.")
        return SETTINGS.update(key, payload["value"])
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/projects")
async def list_projects() -> dict[str, object]:
    return {"projects": PROJECTS.list()}


@app.post("/api/v1/projects")
async def register_project(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"path", "name"} or not isinstance(payload.get("path"), str):
            raise ValueError("İstek path ve isteğe bağlı name alanlarını içermeli.")
        if "name" in payload and not isinstance(payload["name"], str):
            raise ValueError("Proje adı metin olmalı.")
        return PROJECTS.register(payload["path"], payload.get("name"))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (KeyError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail="Seçilen klasör bulunamadı.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/projects/pick")
async def pick_project_folder() -> dict[str, object]:
    try:
        selected = await asyncio.to_thread(choose_project_folder)
        if selected is None:
            return {"cancelled": True}
        existing = next((item for item in PROJECTS.list() if item["root_path"] == str(selected)), None)
        if existing:
            return {"cancelled": False, "project": existing, "already_registered": True}
        project = PROJECTS.register(str(selected))
        return {"cancelled": False, "project": project, "already_registered": False}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/projects/{project_id}/tree")
async def project_tree(project_id: str, path: str = ".") -> dict[str, object]:
    try:
        return {"entries": PROJECTS.tree(project_id, path)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/projects/{project_id}/file")
async def project_file(project_id: str, path: str) -> dict[str, object]:
    try:
        return PROJECTS.read_file(project_id, path)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Dosya bulunamadı.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/projects/{project_id}/proposals")
async def propose_project_edit(project_id: str, request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"path", "content"}:
            raise ValueError("İstek path ve content alanlarını içermeli.")
        if not isinstance(payload["path"], str) or not isinstance(payload["content"], str):
            raise ValueError("path ve content metin olmalı.")
        return PROJECTS.propose(project_id, payload["path"], payload["content"])
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Dosya yolu bulunamadı.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/proposals/{proposal_id}/apply")
async def apply_project_edit(proposal_id: str, request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"approved", "overwrite_approved"}:
            raise ValueError("İstek yalnızca onay alanlarını içerebilir.")
        if payload.get("approved") is not True:
            raise PermissionError("Diff kullanıcı tarafından onaylanmadı.")
        if "overwrite_approved" in payload and not isinstance(payload["overwrite_approved"], bool):
            raise ValueError("overwrite_approved boolean olmalı.")
        return PROJECTS.apply(proposal_id, approved=True, overwrite_approved=payload.get("overwrite_approved", False))
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v1/llm/gemma/status")
def gemma_status() -> dict[str, object]:
    return LLMS.status("gemma-4-12b")


@app.post("/api/v1/llm/gemma/start")
def start_gemma() -> dict[str, object]:
    try:
        return LLMS.start("gemma-4-12b")
    except GemmaUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/v1/llm/gemma/stop")
def stop_gemma() -> dict[str, object]:
    try:
        return LLMS.stop("gemma-4-12b")
    except GemmaUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v1/llm/models")
def llm_models() -> dict[str, object]:
    return {"models": LLMS.model_list()}


@app.get("/api/v1/llm/{model_id}/status")
def llm_status(model_id: str) -> dict[str, object]:
    try:
        return LLMS.status(model_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/v1/llm/{model_id}/start")
def start_llm(model_id: str) -> dict[str, object]:
    try:
        return LLMS.start(model_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except GemmaUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/v1/llm/{model_id}/stop")
def stop_llm(model_id: str) -> dict[str, object]:
    try:
        return LLMS.stop(model_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except GemmaUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/v1/llm/{model_id}/cancel")
def cancel_llm_response(model_id: str) -> dict:
    try:
        queued = CONVERSATIONS.cancel_turn(model_id)
        result = LLMS.server(model_id).cancel_response()
        result['cancelled_active_request'] = queued or result['cancelled_active_request']
        return result
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/v1/conversations")
async def list_conversations(kind: str | None = None) -> dict[str, object]:
    try:
        return {"conversations": CONVERSATIONS.list(kind)}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/v1/conversations")
async def create_conversation(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) - {"title", "kind", "model_id", "auto_title"}:
            raise ValueError("İstek yalnızca title, kind, model_id ve auto_title alanlarını içerebilir.")
        if "title" in payload and not isinstance(payload["title"], str):
            raise ValueError("Sohbet adı metin olmalı.")
        if "kind" in payload and not isinstance(payload["kind"], str):
            raise ValueError("Sohbet türü metin olmalı.")
        kind = payload.get("kind", "assistant")
        model_id = payload.get("model_id", "gemma-4-12b")
        if not isinstance(model_id, str):
            raise ValueError("model_id metin olmalı.")
        LLMS.validate_model_id(model_id)
        auto_title = payload.get('auto_title', 'title' not in payload)
        if not isinstance(auto_title, bool):
            raise ValueError("auto_title mantıksal değer olmalı.")
        return CONVERSATIONS.create(payload.get("title", "Yeni sohbet"), kind, model_id, auto_title=auto_title)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, object]:
    try:
        return {"conversation": CONVERSATIONS.get(conversation_id), "messages": CONVERSATIONS.get_messages(conversation_id)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.patch("/api/v1/conversations/{conversation_id}")
async def rename_conversation(conversation_id: str, request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or set(payload) != {"title"} or not isinstance(payload["title"], str):
            raise ValueError("İstek title metin alanını içermeli.")
        return CONVERSATIONS.rename(conversation_id, payload["title"])
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    try:
        CONVERSATIONS.delete(conversation_id)
        return {"deleted": True}
    except ConversationBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/v1/conversations/{conversation_id}/messages")
async def send_conversation_message(conversation_id: str, request: Request) -> StreamingResponse:
    cancel_event = None
    try:
        payload = await request.json()
        allowed = {"content", "project_id", "context_path", "context_content", "continue"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError("Geçersiz sohbet isteği.")
        continuation = payload.get('continue', False)
        if not isinstance(continuation, bool):
            raise ValueError("continue mantıksal değer olmalı.")
        if continuation:
            if set(payload) != {'continue'}:
                raise ValueError("Devam isteği başka alan içeremez.")
        elif not isinstance(payload.get('content'), str):
            raise ValueError("İstek content metin alanını içermeli.")
        for key in {'project_id', 'context_path', 'context_content'}:
            if key in payload and not isinstance(payload[key], str):
                raise ValueError(f"{key} metin olmalı.")
        conversation = CONVERSATIONS.get(conversation_id)
        service = CODE_CHAT if conversation['kind'] == 'code' else ASSISTANT_CHAT
        cancel_event = CONVERSATIONS.begin_turn(conversation_id)
        if continuation:
            prepared = service.prepare_continuation(conversation_id)
        else:
            prepared = service.prepare(conversation_id, payload['content'],
                project_id=payload.get('project_id'), context_path=payload.get('context_path'),
                context_content=payload.get('context_content'))
        model_id = conversation['model_id']
        return ChatStreamResponse(
            generate=lambda on_delta: LLMS.chat_stream(model_id, prepared['model_messages'], on_delta,
                cancel_event=cancel_event, continuation=continuation),
            commit=lambda result: service.commit(prepared, result),
            cancel=lambda: LLMS.server(model_id).cancel_response(),
            release=lambda: CONVERSATIONS.end_turn(conversation_id, cancel_event),
            cancel_event=cancel_event,
        )
    except ConversationBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (KeyError, FileNotFoundError) as error:
        if cancel_event is not None:
            CONVERSATIONS.end_turn(conversation_id, cancel_event)
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        if cancel_event is not None:
            CONVERSATIONS.end_turn(conversation_id, cancel_event)
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        if cancel_event is not None:
            CONVERSATIONS.end_turn(conversation_id, cancel_event)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BaseException:
        if cancel_event is not None:
            CONVERSATIONS.end_turn(conversation_id, cancel_event)
        raise


# Serve the built UI on the same loopback origin as the API.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend/dist"
if FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
