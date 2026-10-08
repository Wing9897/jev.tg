"""Jev / Laya backend switch. Ollama HTTP stays mocked; weights are never downloaded."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from server.batches import create_task, latest_error_batch
from server.billing import list_usage, record_call, serialize_row, summary
from server.db import Database
from server.laya import (
    OLLAMA_BASE_URL,
    OLLAMA_DOWN,
    OLLAMA_LAYA_MODEL,
    LayaError,
    category_question,
    judge_laya_batch,
    message_state,
    noul_from_laya_answer,
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
    def test_user_path_is_the_official_ollama_tag(self) -> None:
        self.assertEqual(OLLAMA_LAYA_MODEL, "laya")
        self.assertEqual(OLLAMA_BASE_URL, "http://127.0.0.1:11434")
        self.assertNotIn("multilingual", OLLAMA_LAYA_MODEL)

    def test_ollama_skips_images_and_typesafe(self) -> None:
        async def run() -> None:
            calls: list[dict[str, Any]] = []

            def post(payload: dict[str, Any]) -> dict[str, Any]:
                calls.append(payload)
                questions = payload["questions"]
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
            with patch("server.laya._post_systemone", post), patch(
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
            self.assertEqual(judged["usage_meta"]["model"], "laya")
            self.assertEqual(judged["usage_meta"]["input_tokens"], 0)
            self.assertIsNone(judged["usage_meta"]["cost_usd"])
            hit = calls[0]
            self.assertEqual(hit["model"], "laya")
            self.assertEqual(set(hit["state"]), {"text", "chat", "sender", "time"})
            self.assertNotIn("images", hit["state"])
            self.assertEqual(hit["questions"]["hit"]["instructions"], "找晶片")
            self.assertEqual(hit["questions"]["hit"]["type"], "noul")
            self.assertIn("other", calls[1]["questions"]["category"]["criteria"])
            self.assertEqual(message_state(message).keys(), hit["state"].keys())

        asyncio.run(run())

    def test_ollama_requests_may_overlap(self) -> None:
        async def run() -> None:
            current = 0
            peak = 0
            gate = threading.Lock()

            def post(payload: dict[str, Any]) -> dict[str, Any]:
                nonlocal current, peak
                with gate:
                    current += 1
                    peak = max(peak, current)
                time.sleep(0.05)
                with gate:
                    current -= 1
                self.assertEqual(payload["model"], "laya")
                return {"answers": {"hit": {"type": "noul", "noul": 0.2}}}

            message = {"id": "m", "content": "你好", "chat_name": "c", "sender_name": "s", "timestamp": "t"}
            with patch("server.laya._post_systemone", post):
                await asyncio.gather(
                    judge_laya_batch(task_prompt="相關嗎", messages=[message], categories=[]),
                    judge_laya_batch(task_prompt="相關嗎", messages=[message], categories=[]),
                )
            self.assertEqual(peak, 2)
            self.assertIsNone(category_question([]))

        asyncio.run(run())

    def test_connection_refused_asks_to_start_ollama(self) -> None:
        from server import laya as laya_mod

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

        with patch("server.laya.urllib.request.urlopen", boom):
            with self.assertRaises(LayaError) as caught:
                laya_mod._post_systemone({"model": "laya", "state": "hi", "questions": {}})
        text = str(caught.exception)
        self.assertEqual(text, OLLAMA_DOWN)
        self.assertIn("啟動 Ollama", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("uv sync", text)
        self.assertNotIn("refused", text)

    def test_missing_model_asks_for_pull(self) -> None:
        from email.message import Message
        from io import BytesIO

        from server import laya as laya_mod

        def boom(*_args: Any, **_kwargs: Any) -> None:
            body = BytesIO(json.dumps({"error": "model 'laya' not found"}).encode())
            raise urllib.error.HTTPError(
                "http://127.0.0.1:11434/v1/systemone",
                404,
                "Not Found",
                Message(),
                body,
            )

        with patch("server.laya.urllib.request.urlopen", boom):
            with self.assertRaises(LayaError) as caught:
                laya_mod._post_systemone({"model": "laya", "state": "hi", "questions": {}})
        text = str(caught.exception)
        self.assertIn("ollama pull laya", text)
        self.assertNotIn("Traceback", text)


class BillingLabelTests(unittest.TestCase):
    def test_laya_row_has_no_invented_usd(self) -> None:
        laya = serialize_row(
            {
                "id": "1",
                "created_at": "2026-09-23T00:00:00Z",
                "model": "laya",
                "backend": "laya",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": None,
                "cost_source": "laya",
                "success": 1,
            },
            input_rate=0.042,
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
            input_rate=0.042,
            output_rate=0,
        )
        self.assertEqual(jev["usd_kind"], "estimate")
        self.assertAlmostEqual(jev["spend_usd"], 0.042)


class WorkerBranchTests(unittest.TestCase):
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
            seen: list[str] = []

            def post(payload: dict[str, Any]) -> dict[str, Any]:
                seen.append(str(payload["model"]))
                return {"answers": {"hit": {"type": "noul", "noul": 0.2}}}

            try:
                with patch("server.workers.judge_batch", typesafe), patch("server.laya._post_systemone", post):
                    await _process(database, settings, batch)
                typesafe.assert_not_called()
                self.assertEqual(seen, ["laya"])
                stored = await database.fetch_one("SELECT status, noul FROM analysis_batches WHERE id = 'b1'")
                assert stored is not None
                self.assertEqual(stored["status"], "miss")
                ledger = await database.fetch_one(
                    "SELECT backend, model, cost_source, cost_usd, input_tokens FROM billing_usage"
                )
                assert ledger is not None
                self.assertEqual(ledger["backend"], "laya")
                self.assertEqual(ledger["model"], "laya")
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

            def post(_payload: dict[str, Any]) -> None:
                loaded.append("ollama")
                raise AssertionError("Ollama")

            try:
                with patch("server.workers.judge_batch", judge_batch), patch("server.laya._post_systemone", post):
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

            def post(_payload: dict[str, Any]) -> None:
                nonlocal attempts
                attempts += 1
                raise LayaError(OLLAMA_DOWN)

            try:
                with patch("server.workers.judge_batch", AsyncMock(side_effect=AssertionError("TypeSafe"))), patch(
                    "server.laya._post_systemone", post
                ):
                    await _process(database, settings, batch)
                self.assertEqual(attempts, 1)
                markers = await database.fetch_value("SELECT COUNT(*) FROM analysis_markers WHERE batch_id = 'b1'")
                self.assertEqual(int(markers or 0), 0)
                stored = await database.fetch_one("SELECT status, error_message FROM analysis_batches WHERE id = 'b1'")
                assert stored is not None
                self.assertEqual(stored["status"], "error")
                self.assertIn("啟動 Ollama", str(stored["error_message"]))
                self.assertNotIn("Traceback", str(stored["error_message"]))
                self.assertNotIn("uv sync", str(stored["error_message"]))
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
                        model="laya",
                        success=True,
                        meta={
                            "backend": "laya",
                            "model": "laya",
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
                        model="laya",
                        success=True,
                        meta={"backend": "laya", "model": "laya", "input_tokens": 80, "cost_usd": 3},
                    )
                    jev_summary = await summary(database, settings, backend="jev")
                    laya_summary = await summary(database, settings, backend="laya")
                    self.assertEqual(jev_summary["all_time"]["calls"], 1)
                    self.assertAlmostEqual(jev_summary["all_time"]["usd"], 0.042)
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
