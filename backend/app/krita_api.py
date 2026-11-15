"""Small authenticated API surface for the experimental native layer editor."""
import base64
import binascii
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .krita_bridge import KritaBridge
from .krita_commands import FIELDS

MAX_BODY = 17 * 1024**2


def create_krita_router(bridge: KritaBridge) -> APIRouter:
    router = APIRouter(prefix='/api/v1/krita')

    @router.post('/command')
    async def command(request: Request):
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BODY:
                raise HTTPException(413, 'Görsel isteği çok büyük.')
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError('Geçersiz düzenleme isteği.')
            if set(data) - (FIELDS | {'image'}):
                raise ValueError('Bilinmeyen düzenleme alanı.')
            encoded = data.pop('image', None)
            image = None
            if encoded is not None:
                if not isinstance(encoded, str):
                    raise ValueError('Görsel verisi metin olmalı.')
                if encoded.startswith('data:'):
                    encoded = encoded.split(',', 1)[-1]
                image = base64.b64decode(encoded, validate=True)
            return await run_in_threadpool(bridge.execute, data, image)
        except (ValueError, binascii.Error, TypeError) as error:
            raise HTTPException(422, str(error)) from error
        except (OSError, RuntimeError) as error:
            raise HTTPException(503, str(error)) from error

    def output(name: str, mime: str, filename: str | None = None):
        path = bridge.root / name
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, 'Önce düzenleyicide bir görsel açın ve kaydedin.')
        return FileResponse(path, media_type=mime, filename=filename,
                            headers={'Cache-Control': 'no-store'})

    @router.get('/preview')
    def preview():
        return output('preview.png', 'image/png')

    @router.get('/project')
    def project():
        return output('project.kra', 'application/x-krita', 'workstation.kra')

    return router
