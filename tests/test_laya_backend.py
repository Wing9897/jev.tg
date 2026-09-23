"""Jev / Laya backend switch. The Laya package and weights stay mocked."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from server.batches import create_task, latest_error_batch
from server.billing import list_usage, record_call, serialize_row, summary
from server.db import Database
from server.laya import (
    LAYA_CHECKPOINT,
    LayaError,
    category_question,
    judge_laya_batch,
    message_state,
    noul_from_laya_answer,
    reset_agent,
)
from server.settings_store import SettingsStore, live_worker_count, parse_analysis_backend
from server.sse import SseBroadcaster
from server.util import utc_now_iso
from server.workers import WorkerPool, WorkerState


class BackendDefaultTests(unittest.TestCase):
    def test_default_is_jev(self) -> None:
        self.assertEqual(parse_analysis_backend(None), "jev")
        self.assertEqual(parse_analysis_backend(""), "jev")
        self.assertEqual(parse_analysis_backend("english"), "jev")
        self.assertEqual(parse_analysis_backend("LAYA"), "laya")

    def test_both_backends_share_the_concurrency_cap(self) -> None:
        self.assertEqual(live_worker_count("laya", 8), 8)
        self.assertEqual(live_worker_count("LAYA", 16), 16)
        self.assertEqual(live_worker_count("laya", 99), 16)
        self.assertEqual(live_worker_count("jev", 8), 8)
        self.assertEqual(live_worker_count("nope", 3), 3)

    def test_empty_store_stays_jev(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                settings = SettingsStore(database, Path(folder))
                try:
                    self.assertEqual(await settings.get_analysis_backend(), "jev")
                    self.assertEqual((await settings.snapshot())["analysis_backend"], "jev")
                    await settings.set_analysis_backend("laya")
                    self.assertEqual(await settings.get_analysis_backend(), "laya")
                finally:
                    await database.close()

        asyncio.run(run())


class NoulMappingTests(unittest.TestCase):
    def test_noul_probability_is_used_as_is(self) -> None:
        self.assertEqual(noul_from_laya_answer({"type": "noul", "noul": 0.892}), 0.892)
        self.assertEqual(noul_from_laya_answer({"type": "noul", "noul": 1.4}), 1.0)
        self.assertEqual(noul_from_laya_answer({"type": "noul", "noul": -0.2}), 0.0)

    def test_score_maps_onto_unit_interval(self) -> None:
        mapped = noul_from_laya_answer(
            {
                "type": "score",
                "score": 1.84,
                "legend": {"0": "no", "1": "maybe", "2": "yes"},
            }
        )
        self.assertAlmostEqual(mapped, 0.92)
        self.assertAlmostEqual(noul_from_laya_answer({"type": "score", "score": 0.75}), 0.75)

    def test_yes_no_choice_uses_true_probability(self) -> None:
        self.assertAlmostEqual(
            noul_from_laya_answer(
                {"type": "choice", "choice": "false", "probabilities": {"true": 0.25, "false": 0.75}}
            ),
            0.25,
        )
        self.assertEqual(noul_from_laya_answer({"type": "choice", "choice": "yes"}), 1.0)
        self.assertEqual(noul_from_laya_answer({"type": "choice", "choice": "no"}), 0.0)


class LayaCallTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_agent()

    def test_checkpoint_is_multilingual(self) -> None:
        self.assertEqual(LAYA_CHECKPOINT, "convaiinnovations/laya-multilingual")
        self.assertNotEqual(LAYA_CHECKPOINT, "convaiinnovations/laya")

    def test_loader_calls_official_load(self) -> None:
        from server import laya as laya_mod

        reset_agent()
        seen: list[tuple[Any, ...]] = []
        fake = types.ModuleType("laya")

        def load(model_id: str, *args: Any, **kwargs: Any) -> object:
            seen.append((model_id, args, kwargs.get("subfolder")))
            return object()

        fake.load = load
        previous = sys.modules.get("laya")
        sys.modules["laya"] = fake
        try:
            laya_mod._load_agent()
            self.assertEqual(seen, [("convaiinnovations/laya-multilingual", (), None)])
        finally:
            reset_agent()
            if previous is None:
                sys.modules.pop("laya", None)
            else:
                sys.modules["laya"] = previous

    def test_missing_package_is_a_clear_error(self) -> None:
        from server import laya as laya_mod

        reset_agent()
        previous = sys.modules.get("laya")
        sys.modules["laya"] = None  # type: ignore[assignment]
        try:
            with self.assertRaises(LayaError) as caught:
                laya_mod._load_agent()
            self.assertIn("uv sync --extra laya", str(caught.exception))
        finally:
            reset_agent()
            if previous is None:
                sys.modules.pop("laya", None)
            else:
                sys.modules["laya"] = previous

    def test_predict_skips_images_and_typesafe(self) -> None:
        async def run() -> None:
            calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

            class Agent:
                def predict(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
                    calls.append((state, questions))
                    if "category" in questions:
                        return {"answers": {"category": {"type": "choice", "choice": "market", "confidence": 0.4}}}
                    return {"answers": {"hit": {"type": "noul", "noul": 0.81}}}

            message = {
                "id": "m1",
                "content": "晶片出口",
                "chat_name": "頻道",
                "sender_name": "某人",
                "timestamp": "2026-09-23T00:00:00Z",
                "images": [{"data": "jpeg-bytes"}],
            }
            with patch("server.laya._load_agent", return_value=Agent()), patch(
                "server.jev.AsyncTypeSafeClient",
                side_effect=AssertionError("TypeSafe"),
            ):
                judged = await judge_laya_batch(
                    task_prompt="找晶片",
                    messages=[message],
                    categories=[{"key": "market", "label": "市場", "description": "行情"}],
                )
            self.assertEqual(judged["messages"][0]["noul"], 0.81)
            self.assertEqual(judged["category"], "market")
            self.assertEqual(judged["tokens"], 0)
            self.assertEqual(judged["usage_meta"]["backend"], "laya")
            self.assertIsNone(judged["usage_meta"]["cost_usd"])
            hit_state, hit_questions = calls[0]
            self.assertEqual(set(hit_state), {"text", "chat", "sender", "time"})
            self.assertNotIn("images", hit_state)
            self.assertEqual(hit_questions["hit"]["instructions"], "找晶片")
            self.assertEqual(hit_questions["hit"]["type"], "noul")
            self.assertIn("other", calls[1][1]["category"]["criteria"])
            self.assertEqual(message_state(message).keys(), hit_state.keys())

        asyncio.run(run())

    def test_in_flight_inferences_stay_at_one(self) -> None:
        async def run() -> None:
            from server import laya as laya_mod

            current = 0
            peak = 0

            class Agent:
                def predict(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
                    nonlocal current, peak
                    current += 1
                    peak = max(peak, current)
                    time.sleep(0.05)
                    current -= 1
                    return {"answers": {"hit": {"type": "noul", "noul": 0.2}}}

            laya_mod._agent = Agent()
            message = {"id": "m", "content": "你好", "chat_name": "c", "sender_name": "s", "timestamp": "t"}
            await asyncio.gather(
                judge_laya_batch(task_prompt="相關嗎", messages=[message], categories=[]),
                judge_laya_batch(task_prompt="相關嗎", messages=[message], categories=[]),
            )
            self.assertEqual(peak, 1)
            self.assertIsNone(category_question([]))

        asyncio.run(run())


class BillingLabelTests(unittest.TestCase):
    def test_laya_row_has_no_invented_usd(self) -> None:
        laya = serialize_row(
            {
                "id": "1",
                "created_at": "2026-09-23T00:00:00Z",
                "model": LAYA_CHECKPOINT,
                "backend": "laya",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": None,
                "cost_source": "laya",
                "success": 1,
            },
            input_rate=0.42,
            output_rate=0,
        )
        self.assertEqual(laya["backend"], "laya")
        self.assertIsNone(laya["spend_usd"])
        self.assertIsNone(laya["estimated_cost_usd"])
        self.assertEqual(laya["usd_kind"], "none")
        jev = serialize_row(
            {
                "id": "2",
                "created_at": "2026-09-23T00:00:00Z",
                "model": "jev-1.13.0",
                "backend": "jev",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cost_usd": None,
                "cost_source": "estimate",
                "success": 1,
            },
            input_rate=0.42,
            output_rate=0,
        )
        self.assertEqual(jev["usd_kind"], "estimate")
        self.assertAlmostEqual(jev["spend_usd"], 0.42)


class WorkerBranchTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_agent()

    def test_laya_path_does_not_call_typesafe(self) -> None:
        asyncio.run(self._run_laya_success())

    def test_jev_path_does_not_load_laya(self) -> None:
        asyncio.run(self._run_jev())

    def test_laya_error_releases_markers(self) -> None:
        asyncio.run(self._run_laya_error())

    async def _run_laya_success(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database, settings, batch = await _seed_batch(folder, backend="laya")
            typesafe = AsyncMock(side_effect=AssertionError("TypeSafe"))
            loaded: list[str] = []

            class Agent:
                def predict(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
                    return {"answers": {"hit": {"type": "noul", "noul": 0.2}}}

            def load_agent() -> Agent:
                loaded.append("load")
                return Agent()

            try:
                with patch("server.workers.judge_batch", typesafe), patch("server.laya._load_agent", load_agent):
                    await _process(database, settings, batch)
                typesafe.assert_not_called()
                self.assertEqual(loaded, ["load"])
                stored = await database.fetch_one("SELECT status, noul FROM analysis_batches WHERE id = 'b1'")
                assert stored is not None
                self.assertEqual(stored["status"], "miss")
                ledger = await database.fetch_one("SELECT backend, cost_source, cost_usd, input_tokens FROM billing_usage")
                assert ledger is not None
                self.assertEqual(ledger["backend"], "laya")
                self.assertEqual(ledger["cost_source"], "laya")
                self.assertIsNone(ledger["cost_usd"])
                self.assertEqual(ledger["input_tokens"], 0)
            finally:
                await database.close()

    async def _run_jev(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database, settings, batch = await _seed_batch(folder, backend="jev")
            await settings.set_api_key("test-key")
            loaded: list[str] = []

            async def judge_batch(**kwargs: Any) -> dict[str, Any]:
                message = kwargs["messages"][0]
                return {
                    "messages": [{**message, "i": 1, "noul": 0.2}],
                    "category": None,
                    "category_confidence": None,
                    "tokens": 12,
                    "usage_meta": {"input_tokens": 12, "output_tokens": 0, "model": "jev-1.13.0"},
                    "raw": {"model": "jev-1.13.0"},
                }

            def load_agent() -> None:
                loaded.append("load")
                raise AssertionError("Laya loaded")

            try:
                with patch("server.workers.judge_batch", judge_batch), patch("server.laya._load_agent", load_agent):
                    await _process(database, settings, batch)
                self.assertEqual(loaded, [])
                ledger = await database.fetch_one("SELECT backend, model, input_tokens, cost_source FROM billing_usage")
                assert ledger is not None
                self.assertEqual(ledger["backend"], "jev")
                self.assertEqual(ledger["model"], "jev-1.13.0")
                self.assertEqual(ledger["input_tokens"], 12)
                self.assertEqual(ledger["cost_source"], "estimate")
            finally:
                await database.close()

    async def _run_laya_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database, settings, batch = await _seed_batch(folder, backend="laya")
            attempts = 0

            def load_agent() -> None:
                nonlocal attempts
                attempts += 1
                raise LayaError("weights missing")

            try:
                with patch("server.workers.judge_batch", AsyncMock(side_effect=AssertionError("TypeSafe"))), patch(
                    "server.laya._load_agent", load_agent
                ):
                    await _process(database, settings, batch)
                self.assertEqual(attempts, 1)
                markers = await database.fetch_value("SELECT COUNT(*) FROM analysis_markers WHERE batch_id = 'b1'")
                self.assertEqual(int(markers or 0), 0)
                stored = await database.fetch_one("SELECT status, error_message FROM analysis_batches WHERE id = 'b1'")
                assert stored is not None
                self.assertEqual(stored["status"], "error")
                self.assertIn("weights missing", str(stored["error_message"]))
                recent = await latest_error_batch(database)
                assert recent is not None
                self.assertEqual(recent["id"], "b1")
                self.assertEqual(recent["status"], "error")
            finally:
                await database.close()


async def _seed_batch(folder: str, *, backend: str) -> tuple[Database, SettingsStore, dict[str, Any]]:
    database = Database(Path(folder) / "app.db")
    await database.connect()
    await database.ensure_schema()
    settings = SettingsStore(database, Path(folder))
    await settings.set_analysis_backend(backend)
    task = await create_task(database, {"name": "雷達", "prompt": "找晶片", "batch_size": 1, "hit_threshold": 0.65})
    now = utc_now_iso()
    await database.execute(
        "INSERT INTO messages (id, chat_id, platform_message_id, chat_name, sender_name, content, timestamp, created_at) "
        "VALUES ('m1', 'chat', 'p1', '頻道', '某人', '晶片出口', ?, ?)",
        (now, now),
    )
    await database.execute(
        "INSERT INTO analysis_batches (id, task_id, status, message_ids_json, message_count, created_at, updated_at) "
        "VALUES ('b1', ?, 'running', '[\"m1\"]', 1, ?, ?)",
        (task["id"], now, now),
    )
    await database.execute(
        "INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at) VALUES ('mk1', 'm1', ?, 'b1', ?)",
        (task["id"], now),
    )
    batch = await database.fetch_one("SELECT * FROM analysis_batches WHERE id = 'b1'")
    assert batch is not None
    return database, settings, batch


async def _process(database: Database, settings: SettingsStore, batch: dict[str, Any]) -> None:
    class Telegram:
        async def fetch_hit_images(self, **kwargs: Any) -> list[dict[str, str]]:
            raise AssertionError(kwargs)

    pool = WorkerPool(database, SseBroadcaster(), settings, Telegram())
    await pool._process(WorkerState(worker_id=0), batch)


class RecordCallTests(unittest.TestCase):
    def test_record_call_keeps_laya_cost_null(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                settings = SettingsStore(database, Path(folder))
                try:
                    await record_call(
                        database,
                        settings,
                        task_id=None,
                        batch_id=None,
                        model=LAYA_CHECKPOINT,
                        success=True,
                        meta={
                            "backend": "laya",
                            "model": LAYA_CHECKPOINT,
                            "input_tokens": 80,
                            "output_tokens": 0,
                            "cost_usd": 1.25,
                        },
                    )
                    row = await database.fetch_one(
                        "SELECT backend, input_tokens, output_tokens, cost_usd, estimated_cost_usd, cost_source FROM billing_usage"
                    )
                    assert row is not None
                    self.assertEqual(row["backend"], "laya")
                    self.assertEqual(row["input_tokens"], 0)
                    self.assertEqual(row["output_tokens"], 0)
                    self.assertIsNone(row["cost_usd"])
                    self.assertIsNone(row["estimated_cost_usd"])
                    self.assertEqual(row["cost_source"], "laya")
                finally:
                    await database.close()

        asyncio.run(run())


class LedgerSplitTests(unittest.TestCase):
    def test_summary_and_ledger_follow_backend(self) -> None:
        async def run() -> None:
            with tempfile.TemporaryDirectory() as folder:
                database = Database(Path(folder) / "app.db")
                await database.connect()
                await database.ensure_schema()
                settings = SettingsStore(database, Path(folder))
                try:
                    await record_call(
                        database,
                        settings,
                        task_id=None,
                        batch_id=None,
                        model="jev-1.13.0",
                        success=False,
                        meta={
                            "input_tokens": 1_000_000,
                            "output_tokens": 0,
                            "model": "jev-1.13.0",
                            "error_code": "400",
                            "credits_remaining": 12.5,
                        },
                    )
                    await record_call(
                        database,
                        settings,
                        task_id=None,
                        batch_id=None,
                        model=LAYA_CHECKPOINT,
                        success=True,
                        meta={"backend": "laya", "model": LAYA_CHECKPOINT, "input_tokens": 80, "cost_usd": 3},
                    )
                    jev_summary = await summary(database, settings, backend="jev")
                    laya_summary = await summary(database, settings, backend="laya")
                    self.assertEqual(jev_summary["all_time"]["calls"], 1)
                    self.assertAlmostEqual(jev_summary["all_time"]["usd"], 0.42)
                    self.assertEqual(jev_summary["all_time"]["tokens"], 1_000_000)
                    self.assertEqual(jev_summary["last_credits_remaining"], 12.5)
                    self.assertEqual(laya_summary["all_time"]["calls"], 1)
                    self.assertEqual(laya_summary["all_time"]["usd"], 0)
                    self.assertEqual(laya_summary["all_time"]["tokens"], 0)
                    self.assertIsNone(laya_summary["last_credits_remaining"])

                    jev_page = await list_usage(database, settings, backend="jev")
                    laya_page = await list_usage(database, settings, backend="laya")
                    self.assertEqual(jev_page["total"], 1)
                    self.assertEqual(jev_page["items"][0]["backend"], "jev")
                    self.assertEqual(jev_page["items"][0]["model"], "jev-1.13.0")
                    self.assertEqual(laya_page["total"], 1)
                    self.assertEqual(laya_page["items"][0]["backend"], "laya")
                    self.assertIsNone(laya_page["items"][0]["spend_usd"])
                    self.assertIsNone(laya_page["items"][0]["estimated_cost_usd"])
                finally:
                    await database.close()

        asyncio.run(run())
