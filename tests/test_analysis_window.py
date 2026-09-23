"""Stored message counts and the claim-time age window."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server.batches import (
    _claim_for_task,
    claim_new_batch,
    create_task,
    get_task,
    list_tasks,
    release_disabled_task_batches,
    stored_message_count,
    take_queued_batch,
    update_task,
)
from server.db import Database
from server.settings_store import SettingsStore, parse_analysis_max_age_days
from server.util import to_iso_z, utc_now_iso


def _message(message_id: str, chat_id: str, timestamp: str) -> tuple[str, ...]:
    return (message_id, chat_id, message_id, "頻道", None, None, "內容", timestamp, timestamp)


class AnalysisWindowTests(unittest.TestCase):
    def test_parse_blank_and_non_positive_as_unlimited(self) -> None:
        self.assertEqual(parse_analysis_max_age_days(None), 0)
        self.assertEqual(parse_analysis_max_age_days(""), 0)
        self.assertEqual(parse_analysis_max_age_days("  "), 0)
        self.assertEqual(parse_analysis_max_age_days("0"), 0)
        self.assertEqual(parse_analysis_max_age_days(-3), 0)
        self.assertEqual(parse_analysis_max_age_days("nope"), 0)
        self.assertEqual(parse_analysis_max_age_days("7"), 7)
        self.assertEqual(parse_analysis_max_age_days(4000), 3650)

    def test_setting_roundtrip(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                database = Database(root / "app.db")
                await database.connect()
                await database.ensure_schema()
                store = SettingsStore(database, root)
                self.assertEqual(await store.get_analysis_max_age_days(), 0)
                await store.set_analysis_max_age_days(14)
                self.assertEqual((await store.snapshot())["analysis_max_age_days"], 14)
                await store.set_analysis_max_age_days(0)
                self.assertEqual(await store.get_analysis_max_age_days(), 0)
                self.assertFalse(await store.analysis_paused())
                await store.set_analysis_paused(True)
                self.assertTrue((await store.snapshot())["analysis_paused"])
                await store.set_analysis_paused(False)
                self.assertFalse(await store.analysis_paused())
                await database.close()

        asyncio.run(run())

    def test_claim_skips_old_messages_without_deleting_them(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {
                        "name": "雷達",
                        "prompt": "找晶片",
                        "batch_size": 2,
                        "channel_ids": ["chat-1"],
                    },
                )
                now = utc_now_iso()
                await database.execute_many(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        _message("old-a", "chat-1", "2020-01-01T00:00:00Z"),
                        _message("old-b", "chat-1", "2020-01-02T00:00:00Z"),
                        _message("new-a", "chat-1", now),
                        _message("new-b", "chat-1", now),
                    ],
                )
                self.assertEqual(await stored_message_count(database), 4)
                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_max_age_days', '7')"
                )

                recent = await claim_new_batch(database)
                assert recent is not None
                self.assertEqual(recent["task_id"], task["id"])
                self.assertEqual(recent["message_count"], 2)
                self.assertNotIn("old-", str(recent["message_ids_json"]))
                self.assertEqual(await stored_message_count(database), 4)
                marked = await database.fetch_value(
                    "SELECT COUNT(*) FROM analysis_markers WHERE task_id = ?",
                    (task["id"],),
                )
                self.assertEqual(int(marked or 0), 2)

                missed = await claim_new_batch(database)
                self.assertIsNone(missed)
                self.assertEqual(await stored_message_count(database), 4)

                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_max_age_days', '0') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
                older = await claim_new_batch(database)
                assert older is not None
                self.assertIn("old-a", str(older["message_ids_json"]))
                self.assertIn("old-b", str(older["message_ids_json"]))
                self.assertEqual(await stored_message_count(database), 4)
                marked_after = await database.fetch_value("SELECT COUNT(*) FROM analysis_markers")
                self.assertEqual(int(marked_after or 0), 4)
                await database.close()

        asyncio.run(run())

    def test_disabled_task_claims_nothing_and_reenable_skips_stale(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {
                        "name": "雷達",
                        "prompt": "找晶片",
                        "batch_size": 1,
                        "channel_ids": ["chat-1"],
                        "enabled": False,
                    },
                )
                fresh = utc_now_iso()
                stale = to_iso_z(datetime.now(UTC) - timedelta(days=10))
                await database.execute_many(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        _message("stale", "chat-1", stale),
                        _message("fresh", "chat-1", fresh),
                    ],
                )
                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_max_age_days', '1')"
                )

                self.assertIsNone(await claim_new_batch(database))
                self.assertEqual(int(await database.fetch_value("SELECT COUNT(*) FROM analysis_markers") or 0), 0)
                self.assertEqual(await stored_message_count(database), 2)

                updated = await update_task(database, str(task["id"]), {"enabled": True})
                assert updated is not None
                self.assertTrue(updated["enabled"])
                claimed = await claim_new_batch(database)
                assert claimed is not None
                self.assertIn("fresh", str(claimed["message_ids_json"]))
                self.assertNotIn("stale", str(claimed["message_ids_json"]))
                stale_marked = await database.fetch_value(
                    "SELECT COUNT(*) FROM analysis_markers WHERE message_id = ?",
                    ("stale",),
                )
                self.assertEqual(int(stale_marked or 0), 0)
                self.assertEqual(await stored_message_count(database), 2)

                await update_task(database, str(task["id"]), {"enabled": False})
                self.assertIsNone(await take_queued_batch(database, 1))
                self.assertIsNone(
                    await database.fetch_value(
                        "SELECT status FROM analysis_batches WHERE id = ?",
                        (claimed["id"],),
                    )
                )
                self.assertEqual(int(await database.fetch_value("SELECT COUNT(*) FROM analysis_markers") or 0), 0)
                self.assertEqual(await stored_message_count(database), 2)
                self.assertIsNone(await claim_new_batch(database))

                await update_task(database, str(task["id"]), {"enabled": True})
                again = await claim_new_batch(database)
                assert again is not None
                self.assertIn("fresh", str(again["message_ids_json"]))
                self.assertNotIn("stale", str(again["message_ids_json"]))
                self.assertEqual(await stored_message_count(database), 2)
                await database.close()

        asyncio.run(run())

    def test_sweep_drops_queued_batches_of_disabled_tasks_only(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                disabled = await create_task(
                    database,
                    {
                        "name": "薅羊毛信息",
                        "prompt": "找活動",
                        "batch_size": 1,
                        "channel_ids": ["chat-1"],
                        "enabled": False,
                    },
                )
                enabled = await create_task(
                    database,
                    {
                        "name": "仍啟用",
                        "prompt": "找活動",
                        "batch_size": 1,
                        "channel_ids": ["chat-1"],
                        "enabled": True,
                    },
                )
                now = utc_now_iso()
                await database.execute_many(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        _message("msg-q", "chat-1", now),
                        _message("msg-run", "chat-1", now),
                        _message("msg-held", "chat-1", now),
                    ],
                )
                await database.execute_many(
                    "INSERT INTO analysis_batches "
                    "(id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 1, ?, ?)",
                    [
                        ("q-off", disabled["id"], "queued", '["msg-q"]', now, now),
                        ("run-off", disabled["id"], "running", '["msg-run"]', now, now),
                        ("held", disabled["id"], "running", '["msg-held"]', now, now),
                        ("q-on", enabled["id"], "queued", '["msg-q"]', now, now),
                    ],
                )
                await database.execute_many(
                    "INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        ("m1", "msg-q", disabled["id"], "q-off", now),
                        ("m2", "msg-run", disabled["id"], "run-off", now),
                        ("m3", "msg-held", disabled["id"], "held", now),
                        ("m4", "msg-q", enabled["id"], "q-on", now),
                    ],
                )

                released = await release_disabled_task_batches(database, keep_batch_ids={"held"})
                released_ids = {row["id"] for row in released}
                self.assertEqual(released_ids, {"q-off", "run-off"})
                self.assertEqual(await stored_message_count(database), 3)
                left = await database.fetch_all(
                    "SELECT id, status FROM analysis_batches ORDER BY id"
                )
                self.assertEqual([(row["id"], row["status"]) for row in left], [("held", "running"), ("q-on", "queued")])
                markers = await database.fetch_all(
                    "SELECT batch_id FROM analysis_markers ORDER BY batch_id"
                )
                self.assertEqual([row["batch_id"] for row in markers], ["held", "q-on"])

                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_paused', '1')"
                )
                paused = await release_disabled_task_batches(database, keep_batch_ids={"held"})
                self.assertEqual([row["id"] for row in paused], [])
                self.assertEqual(
                    await database.fetch_value("SELECT status FROM analysis_batches WHERE id = ?", ("q-on",)),
                    "queued",
                )
                self.assertEqual(
                    await database.fetch_value("SELECT status FROM analysis_batches WHERE id = ?", ("held",)),
                    "running",
                )
                self.assertEqual(await stored_message_count(database), 3)
                await database.close()

        asyncio.run(run())


    def test_claim_rechecks_enabled_before_inserting_markers(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {
                        "name": "雷達",
                        "prompt": "找晶片",
                        "batch_size": 1,
                        "channel_ids": ["chat-1"],
                        "enabled": True,
                    },
                )
                now = utc_now_iso()
                await database.execute(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _message("fresh", "chat-1", now),
                )
                stale = await database.fetch_one("SELECT * FROM tasks WHERE id = ?", (task["id"],))
                assert stale is not None
                await database.execute("UPDATE tasks SET enabled = 0 WHERE id = ?", (task["id"],))

                claimed = await _claim_for_task(database, stale)
                self.assertIsNone(claimed)
                self.assertEqual(int(await database.fetch_value("SELECT COUNT(*) FROM analysis_batches") or 0), 0)
                self.assertEqual(int(await database.fetch_value("SELECT COUNT(*) FROM analysis_markers") or 0), 0)
                self.assertEqual(await stored_message_count(database), 1)
                await database.close()

        asyncio.run(run())

    def test_release_reads_protected_ids_at_cancel_time(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {
                        "name": "進行中",
                        "prompt": "找活動",
                        "batch_size": 1,
                        "channel_ids": ["chat-1"],
                        "enabled": False,
                    },
                )
                now = utc_now_iso()
                await database.execute(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _message("held-msg", "chat-1", now),
                )
                await database.execute(
                    "INSERT INTO analysis_batches "
                    "(id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
                    "VALUES ('held', ?, 'running', '[\"held-msg\"]', 1, ?, ?)",
                    (task["id"], now, now),
                )
                await database.execute(
                    "INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at) VALUES ('m', 'held-msg', ?, 'held', ?)",
                    (task["id"], now),
                )

                released = await release_disabled_task_batches(database, keep_batch_ids=lambda: {"held"})
                self.assertEqual(released, [])
                self.assertEqual(
                    await database.fetch_value("SELECT status FROM analysis_batches WHERE id = ?", ("held",)),
                    "running",
                )
                self.assertEqual(int(await database.fetch_value("SELECT COUNT(*) FROM analysis_markers") or 0), 1)
                self.assertEqual(await stored_message_count(database), 1)
                await database.close()

        asyncio.run(run())

    def test_task_pool_counts_match_claim_window(self) -> None:
        async def mark(database: Database, message_id: str, task_id: str) -> None:
            now = utc_now_iso()
            batch_id = f"b-{task_id[:8]}-{message_id}"
            await database.execute(
                "INSERT INTO analysis_batches "
                "(id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
                "VALUES (?, ?, 'hit', '[]', 1, ?, ?)",
                (batch_id, task_id, now, now),
            )
            await database.execute(
                "INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"m-{batch_id}", message_id, task_id, batch_id, now),
            )

        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task_a = await create_task(
                    database,
                    {"name": "雷達", "prompt": "找晶片", "batch_size": 50, "channel_ids": ["chat-1"]},
                )
                task_b = await create_task(
                    database,
                    {
                        "name": "停用",
                        "prompt": "別的",
                        "batch_size": 50,
                        "channel_ids": ["chat-2"],
                        "enabled": False,
                    },
                )
                task_c = await create_task(
                    database,
                    {"name": "未綁", "prompt": "空", "batch_size": 50, "channel_ids": []},
                )
                now = utc_now_iso()
                old = "2020-01-01T00:00:00Z"
                await database.execute_many(
                    "INSERT INTO messages "
                    "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        _message("old-a", "chat-1", old),
                        _message("new-a", "chat-1", now),
                        _message("new-b", "chat-1", now),
                        _message("other", "chat-x", now),
                        _message("bee", "chat-2", now),
                    ],
                )
                await mark(database, "old-a", str(task_a["id"]))
                await mark(database, "new-b", str(task_a["id"]))
                await mark(database, "bee", str(task_a["id"]))
                await mark(database, "new-a", str(task_b["id"]))
                await mark(database, "bee", str(task_b["id"]))
                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_max_age_days', '7')"
                )

                listed = {item["id"]: item["pool"] for item in await list_tasks(database)}
                self.assertEqual(listed[task_a["id"]], {"total": 2, "analyzed": 1})
                self.assertEqual(listed[task_b["id"]], {"total": 1, "analyzed": 1})
                self.assertEqual(listed[task_c["id"]], {"total": 0, "analyzed": 0})
                self.assertFalse((await get_task(database, str(task_b["id"])))["enabled"])
                self.assertEqual((await get_task(database, str(task_b["id"])))["pool"], {"total": 1, "analyzed": 1})
                self.assertEqual(await stored_message_count(database), 5)

                await database.execute(
                    "INSERT INTO settings (key, value) VALUES ('analysis_max_age_days', '0') "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
                )
                opened = (await get_task(database, str(task_a["id"])))["pool"]
                self.assertEqual(opened, {"total": 3, "analyzed": 2})
                self.assertEqual((await get_task(database, str(task_b["id"])))["pool"], {"total": 1, "analyzed": 1})
                self.assertEqual(await stored_message_count(database), 5)
                await database.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
