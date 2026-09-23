"""Saved task templates are gone. Schema cleanup must not touch other rows."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from server.api import router
from server.db import Database


def test_task_template_routes_are_gone() -> None:
    paths = {getattr(route, "path", "") for route in router.routes}
    assert not any(path == "/task-templates" or path.startswith("/task-templates/") for path in paths)


def test_ensure_schema_drops_task_templates_only() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "app.db")
            await database.connect()
            await database.ensure_schema()
            await database.conn.executescript(
                """
                CREATE TABLE task_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO task_templates (id, name, prompt, created_at)
                    VALUES ('tpl', '舊範本', '舊 prompt', '2026-01-01T00:00:00Z');
                INSERT INTO tasks (id, name, prompt, batch_size, created_at, updated_at)
                    VALUES ('task', '既有任務', '不要刪', 12, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                INSERT INTO messages (id, chat_id, platform_message_id, content, timestamp, created_at)
                    VALUES ('msg', 'chat', 'pm', '原文', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                INSERT INTO analysis_batches (id, task_id, message_ids_json, created_at, updated_at)
                    VALUES ('batch', 'task', '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at)
                    VALUES ('mark', 'msg', 'task', 'batch', '2026-01-01T00:00:00Z');
                INSERT INTO billing_usage (id, created_at, task_id)
                    VALUES ('bill', '2026-01-01T00:00:00Z', 'task');
                """
            )
            await database.conn.commit()

            await database.ensure_schema()

            assert await database.fetch_value(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'task_templates'"
            ) is None
            task = await database.fetch_one("SELECT name, prompt, batch_size FROM tasks WHERE id = 'task'")
            assert task is not None
            assert task["name"] == "既有任務"
            assert task["prompt"] == "不要刪"
            assert task["batch_size"] == 12
            assert await database.fetch_value("SELECT content FROM messages WHERE id = 'msg'") == "原文"
            assert await database.fetch_value("SELECT COUNT(*) FROM analysis_markers") == 1
            assert await database.fetch_value("SELECT COUNT(*) FROM billing_usage") == 1
            await database.close()

    asyncio.run(run())
