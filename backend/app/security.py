"""Local API origin, loopback and CSRF protections."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

ASGIApp = Callable[..., Awaitable[None]]


class LocalApiSecurity:
    SAFE_METHODS = {b"GET", b"HEAD", b"OPTIONS"}

    def __init__(
        self,
        app: ASGIApp,
        *,
        csrf_token: str,
        allowed_origins: frozenset[str] = frozenset(
            {"http://127.0.0.1:5173", "http://127.0.0.1:8000"}
        ),
    ):
        self.app = app
        self.csrf_token = csrf_token.encode("ascii")
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        try:
            remote_ip = ipaddress.ip_address(client[0]) if client else None
        except ValueError:
            remote_ip = None
        if remote_ip is None or not remote_ip.is_loopback:
            await self._reject(send, 403, b"Yalnizca bu bilgisayardan erisim kabul edilir.")
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode("ascii", "ignore")
        if not _allowed_host(host):
            await self._reject(send, 403, b"Yerel API Host basligi reddedildi.")
            return

        origin = headers.get(b"origin")
        if origin is not None:
            origin_text = origin.decode("ascii", "ignore")
            if origin_text not in self.allowed_origins:
                await self._reject(send, 403, b"Origin izin listesinde degil.")
                return

        if scope.get("method", "GET").encode("ascii") not in self.SAFE_METHODS:
            supplied = headers.get(b"x-csrf-token", b"")
            if not hmac.compare_digest(supplied, self.csrf_token):
                await self._reject(send, 403, b"CSRF belirteci eksik veya gecersiz.")
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(send: Callable, status: int, message: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(message)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": message})


def _allowed_host(host: str) -> bool:
    try:
        parsed = urlsplit(f"//{host}")
        return (
            parsed.hostname == "127.0.0.1"
            and parsed.port in {8000, 5173}
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False
