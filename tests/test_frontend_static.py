"""Production static mount serves the Vite build and leaves /api alone."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI

from server.static_files import mount_frontend


def _app_with_health() -> FastAPI:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


async def _get(app: FastAPI, path: str) -> tuple[int, bytes]:
    status = 0
    body = bytearray()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            body.extend(message.get("body") or b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
    }
    await app(scope, receive, send)
    return status, bytes(body)


def test_missing_override_does_not_mount(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JEV_TG_FRONTEND_DIST", str(tmp_path / "absent"))
    app = _app_with_health()
    assert mount_frontend(app) is False


def test_dist_is_served_and_api_stays_json(monkeypatch, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>tray</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("ok", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setenv("JEV_TG_FRONTEND_DIST", str(dist))

    app = _app_with_health()
    assert mount_frontend(app) is True

    index_status, index_body = asyncio.run(_get(app, "/"))
    assert index_status == 200
    assert b"tray" in index_body

    fallback_status, fallback_body = asyncio.run(_get(app, "/stage"))
    assert fallback_status == 200
    assert b"tray" in fallback_body

    asset_status, asset_body = asyncio.run(_get(app, "/assets/app.js"))
    assert asset_status == 200
    assert asset_body == b"ok"

    health_status, health_body = asyncio.run(_get(app, "/api/health"))
    assert health_status == 200
    assert b'"ok"' in health_body

    missing_status, missing_body = asyncio.run(_get(app, "/api/missing"))
    assert missing_status == 404
    assert b"nope" not in missing_body

    escape_status, escape_body = asyncio.run(_get(app, "/assets/../../secret.txt"))
    assert escape_status in {200, 404}
    assert b"nope" not in escape_body
