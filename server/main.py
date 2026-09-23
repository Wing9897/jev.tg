"""FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api import billing_router, router
from server.batches import recover_running_batches, release_disabled_task_batches
from server.db import Database
from server.paths import data_dir, db_path, sessions_dir
from server.static_files import mount_frontend
from server.tags import migrate_embedded_categories
from server.settings_store import SettingsStore, live_worker_count
from server.sse import SseBroadcaster
from server.telegram_service import TelegramService
from server.workers import WorkerPool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    db: Database
    sse: SseBroadcaster
    settings: SettingsStore
    telegram: TelegramService
    workers: WorkerPool
    data_dir: Path


@asynccontextmanager
async def lifespan(app: FastAPI):
    root = data_dir()
    database = Database(db_path())
    await database.connect()
    await database.ensure_schema()
    await migrate_embedded_categories(database)
    await recover_running_batches(database)
    released = await release_disabled_task_batches(database)
    for row in released:
        logger.info(
            "Startup cancelled %s batch %s for disabled task %s (%s messages kept)",
            row["status"],
            row["id"],
            row.get("task_name") or row["task_id"],
            row["message_count"],
        )
    sse = SseBroadcaster()
    settings = SettingsStore(database, root)
    telegram = TelegramService(database, sse, sessions_dir())
    workers = WorkerPool(database, sse, settings, telegram)
    app.state.ctx = AppContext(
        db=database,
        sse=sse,
        settings=settings,
        telegram=telegram,
        workers=workers,
        data_dir=root,
    )
    await telegram.restore()
    telegram.set_ingest_hook(workers.kick)
    await workers.start(live_worker_count(await settings.get_analysis_backend(), await settings.get_concurrency()))
    logger.info("JEV Telegram Filter listening with data dir %s", root)
    try:
        yield
    finally:
        await workers.stop()
        await telegram.disconnect()
        await database.close()


app = FastAPI(title="JEV Telegram Filter", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(billing_router, prefix="/api/v1")
mount_frontend(app)
