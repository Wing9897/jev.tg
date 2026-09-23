"""Serve the built Vite app from the same FastAPI process in production."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from server.paths import frontend_dist

logger = logging.getLogger(__name__)


def _safe_file(dist: Path, full_path: str) -> Path | None:
    if not full_path or full_path.endswith("/"):
        return None
    root = dist.resolve()
    candidate = (root / full_path).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate
    return None


def mount_frontend(app: FastAPI) -> bool:
    """Mount ``web/dist`` at ``/``. API routes registered earlier keep winning."""
    dist = frontend_dist()
    if dist is None:
        logger.info("No web/dist; serving API only")
        return False

    index = dist / "index.html"

    @app.get("/", include_in_schema=False)
    async def spa_index() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        found = _safe_file(dist, full_path)
        if found is not None:
            return FileResponse(found)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    logger.info("Serving frontend from %s", dist)
    return True
