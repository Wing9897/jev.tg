"""Per-message noul questions, hit snapshots, and JPEG caps."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from server.batches import HitCursorError, complete_batch, create_task, list_hits, page_hits, snapshot_hit_messages
from server.db import Database
from server.hit_images import MAX_JPEG_BYTES, compress_jpeg, message_is_photo
from server.jev import QUESTION_RESERVE, batch_score, build_questions, build_state, noul_confidence
from server.util import utc_now_iso


class QuestionBuilderTests(unittest.TestCase):
    def test_one_noul_per_message_and_optional_choice(self) -> None:
        questions = build_questions(
            3,
            [{"key": "market", "label": "市場", "description": "行情"}],
        )
        self.assertEqual(set(questions), {"m1", "m2", "m3", "category"})
        self.assertNotIn("related", questions)
        self.assertIn("i=2", questions["m2"].instructions)
        self.assertNotIn("m2", questions["m2"].instructions)
        self.assertIn("other", questions["category"].criteria)
        bare = build_questions(2, [])
        self.assertEqual(set(bare), {"m1", "m2"})

    def test_truncation_keeps_every_row(self) -> None:
        messages = [
            {
                "id": f"id-{index}",
                "content": "字" * 8000,
                "timestamp": "2026-09-22T00:00:00Z",
                "chat_name": "快訊",
                "sender_name": "某人",
            }
            for index in range(100)
        ]
        state = build_state("找晶片資本支出", messages)
        self.assertGreaterEqual(QUESTION_RESERVE, 8_000)
        self.assertEqual(len(state["messages"]), 100)
        self.assertTrue(all(item["id"] == f"id-{index}" for index, item in enumerate(state["messages"])))
        self.assertTrue(all(len(item["text"]) < 8000 for item in state["messages"]))
        blob = str(state)
        self.assertNotIn("base64", blob)

    def test_batch_noul_is_max_among_hits(self) -> None:
        scored = batch_score([0.2, 0.91, 0.7], 0.65)
        self.assertTrue(scored["hit"])
        self.assertEqual(scored["hit_count"], 2)
        self.assertEqual(scored["noul"], 0.91)
        self.assertAlmostEqual(scored["confidence"], noul_confidence(0.91))
        missed = batch_score([0.1, 0.4], 0.65)
        self.assertFalse(missed["hit"])
        self.assertEqual(missed["hit_count"], 0)
        self.assertEqual(missed["noul"], 0.4)


class ImageTests(unittest.TestCase):
    def test_photo_filter_skips_video(self) -> None:
        self.assertTrue(message_is_photo(SimpleNamespace(photo=object())))
        self.assertTrue(message_is_photo(SimpleNamespace(document=SimpleNamespace(mime_type="image/png"))))
        self.assertFalse(message_is_photo(SimpleNamespace(video=object(), photo=None)))
        self.assertFalse(message_is_photo(SimpleNamespace(document=SimpleNamespace(mime_type="video/mp4"))))

    def test_jpeg_stays_under_cap(self) -> None:
        noisy = Image.effect_noise((1800, 1400), 90).convert("RGB")
        raw = BytesIO()
        noisy.save(raw, format="PNG")
        jpeg = compress_jpeg(raw.getvalue())
        self.assertIsNotNone(jpeg)
        assert jpeg is not None
        self.assertLessEqual(len(jpeg), MAX_JPEG_BYTES)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        with Image.open(BytesIO(jpeg)) as opened:
            self.assertLessEqual(max(opened.size), 960)


class SchemaTests(unittest.TestCase):
    def test_existing_database_gains_hit_columns(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "old.db"
                import aiosqlite

                conn = await aiosqlite.connect(path)
                await conn.executescript(
                    """
                    CREATE TABLE analysis_batches (
                        id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message_ids_json TEXT NOT NULL DEFAULT '[]',
                        message_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE batch_messages (
                        batch_id TEXT NOT NULL,
                        message_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        content TEXT,
                        PRIMARY KEY (batch_id, message_id)
                    );
                    """
                )
                await conn.commit()
                await conn.close()
                database = Database(path)
                await database.connect()
                await database.ensure_schema()
                batch_cols = await database._column_names("analysis_batches")
                message_cols = await database._column_names("batch_messages")
                await database.close()
                self.assertIn("hit_count", batch_cols)
                self.assertIn("message_count", batch_cols)
                self.assertIn("noul", message_cols)
                self.assertIn("hit", message_cols)
                self.assertIn("images_json", message_cols)

        asyncio.run(run())

    def test_only_hit_messages_are_listed(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {"name": "雷達", "prompt": "找晶片", "batch_size": 3, "hit_threshold": 0.65},
                )
                now = utc_now_iso()
                await database.execute(
                    "INSERT INTO analysis_batches "
                    "(id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
                    "VALUES ('b1', ?, 'running', '[]', 3, ?, ?)",
                    (task["id"], now, now),
                )
                await snapshot_hit_messages(
                    database,
                    "b1",
                    [
                        {
                            "id": "m-hit",
                            "i": 2,
                            "noul": 0.91,
                            "chat_name": "快訊",
                            "content": "資本支出上修",
                            "timestamp": now,
                            "images": [{"mime": "image/jpeg", "base64": "abc"}],
                        }
                    ],
                )
                await complete_batch(
                    database,
                    batch_id="b1",
                    status="hit",
                    noul=0.91,
                    confidence=noul_confidence(0.91),
                    category="market",
                    category_confidence=0.5,
                    hit_count=1,
                )
                cards = await list_hits(database, min_noul=0.8)
                too_high = await list_hits(database, min_noul=0.95)
                stored = await database.fetch_one("SELECT message_count, hit_count, noul FROM analysis_batches WHERE id = 'b1'")
                await database.close()
                self.assertEqual(len(cards), 1)
                self.assertEqual(cards[0]["id"], "b1:m-hit")
                self.assertEqual(cards[0]["noul"], 0.91)
                self.assertEqual(cards[0]["content"], "資本支出上修")
                self.assertEqual(cards[0]["images"], [{"mime": "image/jpeg", "base64": "abc"}])
                self.assertEqual(cards[0]["hit_count"], 1)
                self.assertEqual(cards[0]["message_count"], 3)
                self.assertEqual(too_high, [])
                assert stored is not None
                self.assertEqual(stored["message_count"], 3)
                self.assertEqual(stored["hit_count"], 1)

        asyncio.run(run())

    def test_hit_pages_apply_filters_and_cursor(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                task = await create_task(
                    database,
                    {"name": "雷達", "prompt": "找晶片", "batch_size": 3, "hit_threshold": 0.65},
                )
                other = await create_task(
                    database,
                    {"name": "其他", "prompt": "別的", "batch_size": 3, "hit_threshold": 0.65},
                )
                specs = [
                    ("b1", task["id"], "2026-01-01T00:00:00Z", "m1", "舊聞", "市場", 0.7, "other"),
                    ("b2", task["id"], "2026-02-01T00:00:00Z", "m2", "資本支出上修", "快訊", 0.91, "market"),
                    ("b3", other["id"], "2026-03-01T00:00:00Z", "m3", "無關", "雜談", 0.5, "other"),
                ]
                for batch_id, task_id, when, message_id, content, chat, noul, category in specs:
                    await database.execute(
                        "INSERT INTO analysis_batches "
                        "(id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
                        "VALUES (?, ?, 'running', '[]', 1, ?, ?)",
                        (batch_id, task_id, when, when),
                    )
                    await snapshot_hit_messages(
                        database,
                        batch_id,
                        [
                            {
                                "id": message_id,
                                "i": 1,
                                "noul": noul,
                                "chat_name": chat,
                                "sender_name": "記者",
                                "content": content,
                                "timestamp": when,
                                "images": [],
                            }
                        ],
                    )
                    await complete_batch(
                        database,
                        batch_id=batch_id,
                        status="hit",
                        noul=noul,
                        category=category,
                        hit_count=1,
                    )
                    await database.execute(
                        "UPDATE analysis_batches SET completed_at = ?, updated_at = ? WHERE id = ?",
                        (when, when, batch_id),
                    )
                page = await page_hits(database, limit=2)
                self.assertEqual([item["id"] for item in page["items"]], ["b3:m3", "b2:m2"])
                self.assertTrue(page["has_more"])
                self.assertEqual(page["total"], 3)
                self.assertEqual(page["limit"], 2)
                older = await page_hits(database, limit=2, cursor=page["next_cursor"])
                self.assertEqual([item["id"] for item in older["items"]], ["b1:m1"])
                self.assertFalse(older["has_more"])
                self.assertIsNone(older["next_cursor"])
                found = await page_hits(database, query="舊聞", limit=40)
                self.assertEqual([item["id"] for item in found["items"]], ["b1:m1"])
                self.assertEqual(found["total"], 1)
                by_sender = await page_hits(database, query="記者", limit=40)
                self.assertEqual(by_sender["total"], 3)
                by_task = await page_hits(database, task_id=task["id"], limit=40)
                self.assertEqual([item["id"] for item in by_task["items"]], ["b2:m2", "b1:m1"])
                by_cat = await page_hits(database, category="market", limit=40)
                self.assertEqual([item["id"] for item in by_cat["items"]], ["b2:m2"])
                by_noul = await page_hits(database, min_noul=0.9, limit=40)
                self.assertEqual([item["id"] for item in by_noul["items"]], ["b2:m2"])
                listed = await list_hits(database, min_noul=0.9)
                self.assertEqual([item["id"] for item in listed], ["b2:m2"])
                with self.assertRaises(HitCursorError):
                    await page_hits(database, cursor="not-a-cursor")
                await database.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
