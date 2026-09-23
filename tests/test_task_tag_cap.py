"""Per-task custom tag cap: 254, with reserved other excluded."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from server.batches import create_task, get_task, update_task
from server.db import Database
from server.tags import MAX_TASK_TAGS, TagError, ensure_task_tag_ids
from server.util import utc_now_iso


def _tag_row(index: int, now: str, *, key: str | None = None) -> tuple[str, ...]:
    tag_key = key if key is not None else f"k{index}"
    return (f"id-{index}", tag_key, f"標籤{index}", "", now, now)


class TaskTagCapTests(unittest.TestCase):
    def test_create_and_update_reject_more_than_254_custom_tags(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                now = utc_now_iso()
                await database.execute_many(
                    "INSERT INTO tags (id, key, label, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    [_tag_row(index, now) for index in range(255)] + [_tag_row(900, now, key="other")],
                )
                custom = [f"id-{index}" for index in range(255)]
                other_id = "id-900"

                with self.assertRaises(TagError) as over:
                    await create_task(
                        database,
                        {"name": "過多", "prompt": "條件", "tag_ids": custom},
                    )
                self.assertEqual(over.exception.status_code, 400)
                self.assertIn(str(MAX_TASK_TAGS), str(over.exception))
                self.assertEqual(await database.fetch_value("SELECT COUNT(*) FROM tasks"), 0)

                task = await create_task(
                    database,
                    {"name": "剛好", "prompt": "條件", "tag_ids": [*custom[:254], other_id]},
                )
                self.assertEqual(len(task["tag_ids"]), 254)
                self.assertNotIn(other_id, task["tag_ids"])

                with self.assertRaises(TagError) as updated:
                    await update_task(database, task["id"], {"name": "不該改到", "tag_ids": [*custom, other_id]})
                self.assertEqual(updated.exception.status_code, 400)
                kept = await get_task(database, task["id"])
                assert kept is not None
                self.assertEqual(kept["name"], "剛好")
                self.assertEqual(len(kept["tag_ids"]), 254)

                duplicated = await ensure_task_tag_ids(database, [custom[0]] * 300)
                self.assertEqual(duplicated, [custom[0]])
                await database.close()

        asyncio.run(run())
