"""Queue filler and one worker slot per shared concurrency setting.

The saved analysis backend chooses the judge. `_judge_jev` is a TypeSafe call
per slot. `_judge_laya` may have that many batches in flight, but Laya loads
one model and serializes inference on its own lock. Billing is recorded on
each path; Laya meta never invents a Jev USD amount.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from typesafe_sdk import (
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPITimeoutError,
    TypeSafeInternalServerError,
    TypeSafeRateLimitError,
)

from server import batches, billing
from server.jev import batch_score, judge_batch
from server.laya import LAYA_CHECKPOINT, judge_laya_batch, laya_billing_meta
from server.settings_store import clamp_concurrency
from server.sse import SseBroadcaster
from server.tags import choice_tags
from server.telegram_service import TelegramService

if TYPE_CHECKING:
    from server.db import Database
    from server.settings_store import SettingsStore

logger = logging.getLogger(__name__)

JEV_ATTEMPTS = 3


def _is_transient_jev(exc: BaseException) -> bool:
    if isinstance(exc, (TypeSafeAPIConnectionError, TypeSafeAPITimeoutError, TypeSafeRateLimitError, TypeSafeInternalServerError)):
        return True
    if isinstance(exc, TypeSafeAPIError):
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        try:
            code = int(status)
        except (TypeError, ValueError):
            return any(token in str(exc) for token in ("429", "529", "503"))
        return code in {408, 409, 425, 429} or code >= 500
    text = str(exc).lower()
    return any(token in text for token in ("429", "529", "timeout", "temporar", "overloaded", "rate limit"))


@dataclass
class WorkerState:
    worker_id: int
    status: str = "idle"
    batch_id: str | None = None
    task_name: str | None = None
    message_count: int = 0


def _worker_payload(worker: WorkerState) -> dict[str, Any]:
    return {
        "worker_id": worker.worker_id,
        "status": worker.status,
        "batch_id": worker.batch_id,
        "task_name": worker.task_name,
        "message_count": worker.message_count,
    }


@dataclass
class WorkerPool:
    db: Database
    sse: SseBroadcaster
    settings: SettingsStore
    telegram: TelegramService
    workers: list[WorkerState] = field(default_factory=list)
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _filler: asyncio.Task[None] | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _kick: asyncio.Event = field(default_factory=asyncio.Event)

    def snapshot(self) -> list[dict[str, Any]]:
        return [_worker_payload(worker) for worker in self.workers]

    def kick(self) -> None:
        self._kick.set()

    def protected_batch_ids(self) -> set[str]:
        """Batches whose judge call is in flight. Packing does not count."""
        return {
            str(worker.batch_id)
            for worker in self.workers
            if worker.batch_id and worker.status == "judging"
        }

    async def start(self, concurrency: int) -> None:
        await self.stop()
        self._stop = asyncio.Event()
        self._kick = asyncio.Event()
        n = clamp_concurrency(concurrency)
        self.workers = [WorkerState(worker_id=index) for index in range(n)]
        self._tasks = [asyncio.create_task(self._run_worker(index), name=f"jev-worker-{index}") for index in range(n)]
        self._filler = asyncio.create_task(self._fill_loop(), name="jev-queue-filler")
        for worker in self.workers:
            self._publish_worker(worker)
        self._publish_pool()

    async def resize(self, concurrency: int) -> None:
        await self.start(concurrency)

    async def stop(self) -> None:
        self._stop.set()
        self._kick.set()
        jobs = list(self._tasks)
        if self._filler is not None:
            jobs.append(self._filler)
        for job in jobs:
            job.cancel()
        for job in jobs:
            try:
                await job
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Worker shutdown error")
        self._tasks = []
        self._filler = None
        self.workers = []
        recovered = await batches.recover_running_batches(self.db)
        if recovered:
            logger.info("Re-queued %s in-flight batches after worker stop", recovered)

    def _publish_pool(self) -> None:
        self.sse.publish(
            "workers_snapshot",
            {"workers": self.snapshot(), "concurrency": len(self.workers)},
        )

    def _publish_worker(self, worker: WorkerState) -> None:
        self.sse.publish("worker_update", _worker_payload(worker))

    async def _wait_kick(self, timeout: float = 0.55) -> None:
        self._kick.clear()
        try:
            await asyncio.wait_for(self._kick.wait(), timeout=timeout)
        except TimeoutError:
            pass

    def _idle(self, worker: WorkerState) -> None:
        worker.status = "idle"
        worker.batch_id = None
        worker.task_name = None
        worker.message_count = 0
        self._publish_worker(worker)

    async def _sweep_disabled_batches(self) -> None:
        """Drop open batches whose task is disabled. Pause does not do this."""
        released = await batches.release_disabled_task_batches(
            self.db,
            keep_batch_ids=self.protected_batch_ids,
        )
        for row in released:
            logger.info(
                "Cancelled %s batch %s for disabled task %s (%s messages)",
                row["status"],
                row["id"],
                row.get("task_name") or row["task_id"],
                row["message_count"],
            )
            self.sse.publish("queue_take", {"id": row["id"]})

    async def _fill_loop(self) -> None:
        while not self._stop.is_set():
            packed = 0
            try:
                await self._sweep_disabled_batches()
                if not await self.settings.analysis_paused():
                    cap = max(4, len(self.workers) * 4)
                    while await batches.queued_count(self.db) < cap:
                        if await self.settings.analysis_paused():
                            break
                        claimed = await batches.claim_new_batch(self.db)
                        if not claimed:
                            break
                        packed += 1
                        task = await batches.get_task(self.db, str(claimed["task_id"]))
                        self.sse.publish(
                            "queue_update",
                            batches.serialize_batch(claimed, task_name=(task or {}).get("name")),
                        )
                        self.kick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Queue filler failed")
            if packed:
                continue
            await self._wait_kick()

    async def _run_worker(self, worker_id: int) -> None:
        worker = self.workers[worker_id]
        while not self._stop.is_set():
            try:
                await self._tick(worker)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker %s crashed; restarting", worker_id)
                worker.status = "error"
                self._publish_worker(worker)
                await asyncio.sleep(1.2)
                self._idle(worker)
                await asyncio.sleep(0.4)

    async def _return_batch_to_queue(self, worker: WorkerState, batch: dict[str, Any], task: dict[str, Any] | None) -> None:
        """Put a claimed batch back. Does not cancel a Jev call that already started."""
        parked = await batches.requeue_batch(self.db, str(batch["id"]))
        if parked:
            shown = {**batch, "status": "queued", "worker_id": None}
            self.sse.publish(
                "queue_update",
                batches.serialize_batch(shown, task_name=(task or {}).get("name")),
            )
        self._idle(worker)

    async def _drop_disabled_batch(self, worker: WorkerState, batch: dict[str, Any]) -> None:
        """Cancel a batch the worker holds because its task is off. Messages stay."""
        batch_id = str(batch["id"])
        cancelled = await batches.cancel_open_batch(self.db, batch_id)
        if cancelled:
            logger.info("Cancelled held batch %s because its task is disabled", batch_id)
            self.sse.publish("queue_take", {"id": batch_id, "worker_id": worker.worker_id})
        self._idle(worker)

    async def _batch_is_running(self, batch_id: str) -> bool:
        row = await self.db.fetch_one("SELECT status FROM analysis_batches WHERE id = ?", (batch_id,))
        return row is not None and str(row["status"]) == "running"

    async def _tick(self, worker: WorkerState) -> None:
        if await self.settings.analysis_paused():
            if worker.status != "idle":
                self._idle(worker)
            await self._wait_kick()
            return

        if await self.settings.get_analysis_backend() != "laya" and not await self.settings.get_api_key():
            if worker.status != "idle":
                self._idle(worker)
            await asyncio.sleep(1.6)
            return

        batch = await batches.take_queued_batch(self.db, worker.worker_id)
        if batch is None:
            if worker.status != "idle":
                self._idle(worker)
            await self._wait_kick()
            return

        batch_id = str(batch["id"])
        try:
            await self._process(worker, batch)
        except asyncio.CancelledError:
            await batches.requeue_batch(self.db, batch_id)
            raise
        except Exception:
            logger.exception("Worker %s failed on batch %s; re-queueing", worker.worker_id, batch_id)
            await batches.requeue_batch(self.db, batch_id)
            worker.status = "error"
            self._publish_worker(worker)
            await asyncio.sleep(0.8)
            self._idle(worker)

    async def _process(self, worker: WorkerState, batch: dict[str, Any]) -> None:
        task = await batches.get_task(self.db, str(batch["task_id"]))
        if task is None or not task.get("enabled"):
            await self._drop_disabled_batch(worker, batch)
            return
        if await self.settings.analysis_paused():
            await self._return_batch_to_queue(worker, batch, task)
            return
        worker.status = "packing"
        worker.batch_id = str(batch["id"])
        worker.task_name = (task or {}).get("name")
        worker.message_count = int(batch.get("message_count") or 0)
        self._publish_worker(worker)
        self.sse.publish("queue_take", {"id": batch["id"], "worker_id": worker.worker_id})
        await asyncio.sleep(0.28)

        messages = await batches.load_batch_source_messages(self.db, batch)
        if not messages:
            await batches.release_markers(self.db, str(batch["id"]))
            await batches.complete_batch(self.db, batch_id=str(batch["id"]), status="error", error_message="批次沒有訊息")
            self._idle(worker)
            return

        worker.status = "judging"
        self._publish_worker(worker)

        judged: dict[str, Any] | None = None
        last_error: str | None = None
        backend = await self.settings.get_analysis_backend()
        if backend == "laya":
            judged, last_error = await self._judge_laya(worker, batch, messages)
        else:
            judged, last_error = await self._judge_jev(worker, batch, messages)
        if judged is None and last_error == "__stopped__":
            return

        if not await self._batch_is_running(str(batch["id"])):
            logger.info("Batch %s was cancelled before its result could be stored", batch["id"])
            self._idle(worker)
            return
        fresh = await batches.get_task(self.db, str(batch["task_id"]))
        if fresh is None:
            self._idle(worker)
            return
        task = fresh

        if judged is None:
            await batches.release_markers(self.db, str(batch["id"]))
            completed = await batches.complete_batch(
                self.db, batch_id=str(batch["id"]), status="error", error_message=last_error
            )
            self.sse.publish("batch_error", {**(completed or {"id": batch["id"]}), "worker_id": worker.worker_id})
            worker.status = "error"
            self._publish_worker(worker)
            await asyncio.sleep(0.55)
            self._idle(worker)
            return

        threshold = float((task or {}).get("hit_threshold") or 0.65)
        scored = list(judged.get("messages") or [])
        summary = batch_score([float(item["noul"]) for item in scored], threshold)
        hit = bool(summary["hit"])
        status = "hit" if hit else "miss"
        hit_rows = [item for item in scored if float(item["noul"]) >= threshold]
        stored_hits: list[dict[str, Any]] = []
        for item in hit_rows:
            images: list[dict[str, str]] = []
            try:
                images = await self.telegram.fetch_hit_images(
                    chat_id=item.get("chat_id"),
                    platform_message_id=item.get("platform_message_id"),
                )
            except Exception:
                logger.warning("Hit image fetch failed for message %s", item.get("id"), exc_info=True)
                images = []
            stored_hits.append({**item, "images": images})
        await batches.snapshot_hit_messages(self.db, str(batch["id"]), stored_hits)
        completed = await batches.complete_batch(
            self.db,
            batch_id=str(batch["id"]),
            status=status,
            noul=summary["noul"],
            confidence=summary["confidence"],
            category=judged["category"],
            category_confidence=judged["category_confidence"],
            jev_raw=judged["raw"],
            hit_count=int(summary["hit_count"]),
        )
        await self.settings.bump_usage(
            calls=1,
            hits=1 if hit else 0,
            misses=0 if hit else 1,
            tokens=int(judged.get("tokens") or 0),
        )
        event_name = "batch_hit" if hit else "batch_miss"
        payload = completed or serialize_fallback(batch, task, summary, status)
        payload["worker_id"] = worker.worker_id
        payload["tokens"] = int(judged.get("tokens") or 0)
        payload["hit_count"] = int(summary["hit_count"])
        payload["noul"] = summary["noul"]
        payload["confidence"] = summary["confidence"]
        if hit:
            payload["hits"] = [
                batches.serialize_hit_card(
                    batch_id=str(batch["id"]),
                    message_id=str(item["id"]),
                    task_id=str(batch["task_id"]),
                    task_name=(task or {}).get("name"),
                    category=judged.get("category"),
                    category_confidence=judged.get("category_confidence"),
                    hit_count=int(summary["hit_count"]),
                    message_count=int(batch.get("message_count") or len(scored)),
                    noul=float(item["noul"]),
                    ordinal=int(item.get("i") or 0),
                    chat_id=item.get("chat_id"),
                    chat_name=item.get("chat_name"),
                    sender_name=item.get("sender_name"),
                    content=item.get("content"),
                    timestamp=item.get("timestamp"),
                    images=list(item.get("images") or []),
                    created_at=(completed or {}).get("created_at") or batch.get("created_at"),
                    updated_at=(completed or {}).get("updated_at"),
                    completed_at=(completed or {}).get("completed_at"),
                )
                for item in stored_hits
            ]
        self.sse.publish(event_name, payload)
        worker.status = "done"
        self._publish_worker(worker)
        await asyncio.sleep(0.42)
        self._idle(worker)

    async def _runnable_task(self, worker: WorkerState, batch: dict[str, Any]) -> dict[str, Any] | None:
        """Return the task when this batch should be scored now.

        A disabled task cancels the batch, pause puts it back on the queue, and a
        batch that is no longer running is dropped. None means the caller stops.
        """
        task = await batches.get_task(self.db, str(batch["task_id"]))
        if task is None or not task.get("enabled"):
            await self._drop_disabled_batch(worker, batch)
            return None
        if await self.settings.analysis_paused():
            await self._return_batch_to_queue(worker, batch, task)
            return None
        if not await self._batch_is_running(str(batch["id"])):
            self._idle(worker)
            return None
        return task

    async def _judge_laya(
        self,
        worker: WorkerState,
        batch: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """One local pass. Failures are not retried."""
        task = await self._runnable_task(worker, batch)
        if task is None:
            return None, "__stopped__"
        try:
            judged = await judge_laya_batch(
                task_prompt=str(task.get("prompt") or ""),
                messages=messages,
                categories=choice_tags(list(task.get("tags") or [])),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Laya call failed for batch %s: %s", batch["id"], exc)
            await billing.record_call(
                self.db,
                self.settings,
                task_id=str(batch["task_id"]),
                batch_id=str(batch["id"]),
                model=LAYA_CHECKPOINT,
                success=False,
                meta=laya_billing_meta(error=last_error),
            )
            return None, last_error
        await billing.record_call(
            self.db,
            self.settings,
            task_id=str(batch["task_id"]),
            batch_id=str(batch["id"]),
            model=LAYA_CHECKPOINT,
            success=True,
            meta=judged.get("usage_meta") or laya_billing_meta(),
        )
        return judged, None

    async def _judge_jev(
        self,
        worker: WorkerState,
        batch: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None]:
        api_key = await self.settings.get_api_key()
        if not api_key:
            await batches.requeue_batch(self.db, str(batch["id"]))
            worker.status = "error"
            self._publish_worker(worker)
            await asyncio.sleep(0.6)
            self._idle(worker)
            return None, "__stopped__"

        last_error: str | None = None
        model_name = await self.settings.get_model()
        for attempt in range(1, JEV_ATTEMPTS + 1):
            task = await self._runnable_task(worker, batch)
            if task is None:
                return None, "__stopped__"
            try:
                judged = await judge_batch(
                    api_key=api_key,
                    model=model_name,
                    task_prompt=str(task.get("prompt") or ""),
                    messages=messages,
                    categories=choice_tags(list(task.get("tags") or [])),
                )
                await billing.record_call(
                    self.db,
                    self.settings,
                    task_id=str(batch["task_id"]),
                    batch_id=str(batch["id"]),
                    model=model_name,
                    success=True,
                    meta=judged.get("usage_meta") or {},
                )
                return judged, None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_meta = billing.meta_from_exc(exc)
                last_error = str(last_meta.get("error_message") or exc)
                await billing.record_call(
                    self.db,
                    self.settings,
                    task_id=str(batch["task_id"]),
                    batch_id=str(batch["id"]),
                    model=model_name,
                    success=False,
                    meta=last_meta,
                )
                logger.warning("Jev call failed for batch %s (attempt %s/%s): %s", batch["id"], attempt, JEV_ATTEMPTS, exc)
                insufficient = bool(last_meta.get("insufficient_credits"))
                retryable = (not insufficient) and _is_transient_jev(exc) and attempt < JEV_ATTEMPTS
                if not retryable:
                    return None, last_error
                worker.status = "error"
                self._publish_worker(worker)
                await asyncio.sleep(1.1 * attempt)
                worker.status = "judging"
                self._publish_worker(worker)
        return None, last_error


def serialize_fallback(batch: dict[str, Any], task: dict[str, Any] | None, summary: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "id": batch["id"],
        "task_id": batch["task_id"],
        "task_name": (task or {}).get("name"),
        "status": status,
        "message_count": batch.get("message_count"),
        "hit_count": summary.get("hit_count"),
        "noul": summary.get("noul"),
        "confidence": summary.get("confidence"),
        "time_start": batch.get("time_start"),
        "time_end": batch.get("time_end"),
    }
