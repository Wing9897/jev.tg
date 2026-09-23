"""SQLite WAL database wrapper."""

from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

import aiosqlite

logger = logging.getLogger(__name__)

_BUSY_RETRIES = 5
_BUSY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
_ResultT = TypeVar("_ResultT")

SCHEMA = """
CREATE TABLE IF NOT EXISTS telegram_sources (
    id                 TEXT PRIMARY KEY,
    name               TEXT,
    api_id             INTEGER,
    api_hash           TEXT,
    phone              TEXT,
    status             TEXT NOT NULL DEFAULT 'disconnected',
    last_error         TEXT,
    last_connected_at  TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    platform_id  TEXT PRIMARY KEY,
    name         TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_subscriptions (
    platform_id  TEXT PRIMARY KEY REFERENCES channels(platform_id) ON DELETE CASCADE,
    subscribed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id                   TEXT PRIMARY KEY,
    chat_id              TEXT NOT NULL,
    platform_message_id  TEXT NOT NULL,
    chat_name            TEXT,
    sender_id            TEXT,
    sender_name          TEXT,
    content              TEXT NOT NULL DEFAULT '',
    timestamp            TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    UNIQUE (platform_message_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_time ON messages(chat_id, timestamp ASC, id ASC);
CREATE INDEX IF NOT EXISTS idx_messages_time ON messages(timestamp ASC, id ASC);

CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    prompt         TEXT NOT NULL,
    batch_size     INTEGER NOT NULL DEFAULT 50,
    hit_threshold  REAL NOT NULL DEFAULT 0.65,
    enabled        INTEGER NOT NULL DEFAULT 1,
    priority       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id           TEXT PRIMARY KEY,
    key          TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_tags (
    task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tag_id   TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_task_tags_tag ON task_tags(tag_id);

CREATE TABLE IF NOT EXISTS task_channels (
    task_id      TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    platform_id  TEXT NOT NULL,
    PRIMARY KEY (task_id, platform_id)
);

CREATE TABLE IF NOT EXISTS analysis_batches (
    id                   TEXT PRIMARY KEY,
    task_id              TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status               TEXT NOT NULL DEFAULT 'queued',
    message_ids_json     TEXT NOT NULL DEFAULT '[]',
    message_count        INTEGER NOT NULL DEFAULT 0,
    hit_count            INTEGER NOT NULL DEFAULT 0,
    noul                 REAL,
    confidence           REAL,
    category             TEXT,
    category_confidence  REAL,
    jev_raw_json         TEXT,
    error_message        TEXT,
    time_start           TEXT,
    time_end             TEXT,
    worker_id            INTEGER,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    completed_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_batches_status_created ON analysis_batches(status, created_at);
CREATE INDEX IF NOT EXISTS idx_batches_task_status ON analysis_batches(task_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS batch_messages (
    batch_id     TEXT NOT NULL REFERENCES analysis_batches(id) ON DELETE CASCADE,
    message_id   TEXT NOT NULL,
    ordinal      INTEGER NOT NULL,
    chat_id      TEXT,
    chat_name    TEXT,
    sender_name  TEXT,
    content      TEXT,
    timestamp    TEXT,
    noul         REAL,
    hit          INTEGER NOT NULL DEFAULT 1,
    images_json  TEXT,
    PRIMARY KEY (batch_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_batch_messages_ordinal ON batch_messages(batch_id, ordinal);

CREATE TABLE IF NOT EXISTS analysis_markers (
    id           TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    task_id      TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    batch_id     TEXT NOT NULL REFERENCES analysis_batches(id) ON DELETE CASCADE,
    analyzed_at  TEXT NOT NULL,
    UNIQUE (message_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_markers_batch ON analysis_markers(batch_id);
CREATE INDEX IF NOT EXISTS idx_markers_task ON analysis_markers(task_id, message_id);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_usage (
    id                   TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    task_id              TEXT,
    batch_id             TEXT,
    model                TEXT,
    backend              TEXT NOT NULL DEFAULT 'jev',
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    cost_usd             REAL,
    estimated_cost_usd   REAL,
    cost_source          TEXT NOT NULL DEFAULT 'none',
    success              INTEGER NOT NULL DEFAULT 1,
    error_code           TEXT,
    error_message        TEXT,
    credits_remaining    REAL
);
CREATE INDEX IF NOT EXISTS idx_billing_usage_created ON billing_usage(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_billing_usage_task ON billing_usage(task_id, created_at DESC);
"""

# CREATE TABLE IF NOT EXISTS does not change a column default on an existing database.
_BATCH_SIZE_DEFAULT_100 = re.compile(
    r"(batch_size\s+INTEGER\s+NOT\s+NULL\s+DEFAULT\s+)100\b",
    re.IGNORECASE,
)

# CREATE TABLE IF NOT EXISTS does not add columns to an existing database.
_ADDED_COLUMNS = (
    ("analysis_batches", "hit_count", "INTEGER NOT NULL DEFAULT 0"),
    ("batch_messages", "noul", "REAL"),
    ("batch_messages", "hit", "INTEGER NOT NULL DEFAULT 1"),
    ("batch_messages", "images_json", "TEXT"),
    ("billing_usage", "backend", "TEXT NOT NULL DEFAULT 'jev'"),
)


def _is_busy(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database is busy" in text or "busy" in text and "sqlite" in text


async def _with_busy_retry(action: Callable[[], Awaitable[_ResultT]]) -> _ResultT:
    last: BaseException | None = None
    for attempt in range(_BUSY_RETRIES):
        try:
            return await action()
        except Exception as exc:
            last = exc
            if not _is_busy(exc) or attempt >= _BUSY_RETRIES - 1:
                raise
        await asyncio.sleep(_BUSY_DELAYS[attempt])
    assert last is not None
    raise last


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._transaction_owner: asyncio.Task[Any] | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be called before use")
        return self._conn

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(self.path), timeout=30.0)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=15000")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.commit()
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def ensure_schema(self) -> None:
        await self.conn.executescript(SCHEMA)
        await self._migrate_columns()
        await self._migrate_batch_size_default()
        await self._drop_task_templates()
        await self.conn.commit()

    async def _writable_schema(self, enabled: bool) -> None:
        if enabled:
            await self.conn.execute("PRAGMA writable_schema=ON")
            return
        if sqlite3.sqlite_version_info >= (3, 42, 0):
            await self.conn.execute("PRAGMA writable_schema=RESET")
        else:
            await self.conn.execute("PRAGMA writable_schema=OFF")

    async def _column_names(self, table: str) -> set[str]:
        async with self.conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
        return {str(row[1]) for row in rows}

    async def _migrate_columns(self) -> None:
        for table, name, ddl in _ADDED_COLUMNS:
            if name in await self._column_names(table):
                continue
            await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            logger.info("Added column %s.%s", table, name)

    async def _migrate_batch_size_default(self) -> None:
        """Set the column default to 50. Do not rewrite saved task batch_size values."""
        cursor = await self.conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'tasks'")
        row = await cursor.fetchone()
        await cursor.close()
        original = str(row[0]) if row is not None and row[0] else ""
        if not _BATCH_SIZE_DEFAULT_100.search(original):
            return
        updated, replaced = _BATCH_SIZE_DEFAULT_100.subn(r"\g<1>50", original, count=1)
        if replaced != 1:
            return
        saved = await self.conn.execute("SELECT id, batch_size FROM tasks")
        before = [(str(item[0]), int(item[1])) for item in await saved.fetchall()]
        await saved.close()
        await self._writable_schema(True)
        await self.conn.execute(
            "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'tasks'",
            (updated,),
        )
        await self._writable_schema(False)
        await self.conn.commit()
        check = await self.conn.execute("SELECT id, batch_size FROM tasks")
        after = [(str(item[0]), int(item[1])) for item in await check.fetchall()]
        await check.close()
        if sorted(before) != sorted(after):
            await self._writable_schema(True)
            await self.conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type = 'table' AND name = 'tasks'",
                (original,),
            )
            await self._writable_schema(False)
            await self.conn.commit()
            raise RuntimeError("batch_size default migration changed saved task rows")
        logger.info("tasks.batch_size default is 50; %s saved row(s) left unchanged", len(after))

    async def _drop_task_templates(self) -> None:
        """User templates were rejected. Drop only that table."""
        cursor = await self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'task_templates'"
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return
        await self.conn.execute("DROP TABLE task_templates")
        logger.info("Dropped unused task_templates table")

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        async def action() -> int:
            async with self._lock:
                cursor = await self.conn.execute(sql, params)
                rowcount = cursor.rowcount
                await cursor.close()
                await self.conn.commit()
            return int(rowcount or 0)

        return await _with_busy_retry(action)

    async def execute_many(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return

        async def action() -> None:
            async with self._lock:
                await self.conn.executemany(sql, rows)
                await self.conn.commit()

        await _with_busy_retry(action)

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async def action() -> list[dict[str, Any]]:
            async with self._lock, self.conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
            return [dict(row) for row in rows]

        return await _with_busy_retry(action)

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        async def action() -> dict[str, Any] | None:
            async with self._lock, self.conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
            return dict(row) if row is not None else None

        return await _with_busy_retry(action)

    async def fetch_value(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = await self.fetch_one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()), None)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        owner = asyncio.current_task()
        if owner is not None and self._transaction_owner is owner:
            raise RuntimeError("Database.transaction() cannot be nested in the same task")
        async with self._lock:
            self._transaction_owner = owner
            try:
                await _with_busy_retry(lambda: self.conn.execute("BEGIN IMMEDIATE"))
                try:
                    yield self.conn
                    await self.conn.commit()
                except BaseException:
                    try:
                        await self.conn.rollback()
                    except BaseException:
                        logger.exception("Failed to roll back database transaction")
                    raise
            finally:
                if self._transaction_owner is owner:
                    self._transaction_owner = None
