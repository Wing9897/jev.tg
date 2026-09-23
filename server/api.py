"""HTTP routes."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import AliasGenerator, BaseModel, ConfigDict, Field

from server import batches, billing, tags as tagstore
from server.settings_store import (
    ANALYSIS_BACKENDS,
    MAX_ANALYSIS_MAX_AGE_DAYS,
    MAX_CONCURRENCY,
    MIN_CONCURRENCY,
    live_worker_count,
)
from server.sse import SseCapacityError, event_stream
from server.tags import TagError
from server.telegram_service import login_error_text
from server.util import camelize, to_camel

logger = logging.getLogger(__name__)

router = APIRouter()
billing_router = APIRouter()


def _telegram_http_error(exc: Exception) -> HTTPException:
    logger.warning("Telegram request failed: %s", exc.__cause__ or exc)
    return HTTPException(status_code=400, detail=login_error_text(exc))


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=AliasGenerator(validation_alias=to_camel, serialization_alias=to_camel),
        populate_by_name=True,
    )


class SettingsUpdate(CamelModel):
    typesafe_api_key: str | None = None
    model: str | None = None
    concurrency: int | None = Field(default=None, ge=MIN_CONCURRENCY, le=MAX_CONCURRENCY)
    input_usd_per_mtok: float | None = Field(default=None, ge=0)
    output_usd_per_mtok: float | None = Field(default=None, ge=0)
    low_credits_threshold: float | None = Field(default=None, ge=0)
    analysis_max_age_days: int | None = Field(default=None, ge=0, le=MAX_ANALYSIS_MAX_AGE_DAYS)
    analysis_paused: bool | None = None
    analysis_backend: Literal["jev", "laya"] | None = None


class PhoneLoginBody(CamelModel):
    api_id: int
    api_hash: str
    phone: str


class CodeBody(CamelModel):
    code: str
    phone_code_hash: str | None = None


class TwoFactorBody(CamelModel):
    password: str


class QrStartBody(CamelModel):
    api_id: int
    api_hash: str


class QrWaitBody(CamelModel):
    timeout_seconds: float | None = None


class SubscribeBody(CamelModel):
    subscribed_ids: list[str] = Field(default_factory=list)


class TagBody(CamelModel):
    key: str = ""
    label: str
    description: str = ""


class TagPatch(CamelModel):
    key: str | None = None
    label: str | None = None
    description: str | None = None


class TaskBody(CamelModel):
    name: str
    prompt: str
    batch_size: int = batches.DEFAULT_BATCH_SIZE
    hit_threshold: float = 0.65
    tag_ids: list[str] = Field(default_factory=list)
    channel_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 0


class TaskPatch(CamelModel):
    name: str | None = None
    prompt: str | None = None
    batch_size: int | None = None
    hit_threshold: float | None = None
    tag_ids: list[str] | None = None
    channel_ids: list[str] | None = None
    enabled: bool | None = None
    priority: int | None = None


def ctx(request: Request) -> Any:
    return request.app.state.ctx


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    return camelize(await ctx(request).settings.snapshot())


@router.put("/settings")
async def put_settings(request: Request, body: SettingsUpdate) -> dict[str, Any]:
    store = ctx(request).settings
    if body.typesafe_api_key is not None:
        await store.set_api_key(body.typesafe_api_key)
    if body.model is not None:
        model = body.model.strip() or "jev-1.13.0"
        await store.set_raw("model", model)
    pool_dirty = False
    if body.concurrency is not None:
        await store.set_raw("concurrency", str(body.concurrency))
        pool_dirty = True
    if body.input_usd_per_mtok is not None or body.output_usd_per_mtok is not None:
        await store.set_billing_rates(
            input_usd_per_mtok=body.input_usd_per_mtok,
            output_usd_per_mtok=body.output_usd_per_mtok,
        )
    if body.low_credits_threshold is not None:
        await store.set_low_credits_threshold(body.low_credits_threshold)
    if body.analysis_max_age_days is not None:
        await store.set_analysis_max_age_days(body.analysis_max_age_days)
    if body.analysis_paused is not None:
        await store.set_analysis_paused(body.analysis_paused)
        ctx(request).workers.kick()
    if body.analysis_backend is not None:
        if body.analysis_backend not in ANALYSIS_BACKENDS:
            raise HTTPException(status_code=400, detail="analysis_backend 必須是 jev 或 laya")
        await store.set_analysis_backend(body.analysis_backend)
        pool_dirty = True
    if pool_dirty:
        live = live_worker_count(await store.get_analysis_backend(), await store.get_concurrency())
        await ctx(request).workers.resize(live)
        ctx(request).workers.kick()
    return camelize(await store.snapshot())


@router.get("/telegram")
async def telegram_status(request: Request) -> dict[str, Any]:
    return camelize(await ctx(request).telegram.snapshot())


@router.post("/telegram/login/phone")
async def telegram_phone(request: Request, body: PhoneLoginBody) -> dict[str, Any]:
    try:
        result = await ctx(request).telegram.start_login(body.api_id, body.api_hash, body.phone)
    except Exception as exc:
        raise _telegram_http_error(exc) from exc
    return camelize(result)


@router.post("/telegram/login/code")
async def telegram_code(request: Request, body: CodeBody) -> dict[str, Any]:
    try:
        result = await ctx(request).telegram.verify_code(body.code, body.phone_code_hash)
    except Exception as exc:
        raise _telegram_http_error(exc) from exc
    return camelize(result)


@router.post("/telegram/login/2fa")
async def telegram_2fa(request: Request, body: TwoFactorBody) -> dict[str, Any]:
    try:
        result = await ctx(request).telegram.verify_2fa(body.password)
    except Exception as exc:
        raise _telegram_http_error(exc) from exc
    return camelize(result)


@router.post("/telegram/login/qr")
async def telegram_qr_start(request: Request, body: QrStartBody) -> dict[str, Any]:
    try:
        result = await ctx(request).telegram.start_qr_login(body.api_id, body.api_hash)
    except Exception as exc:
        raise _telegram_http_error(exc) from exc
    return camelize(result)


@router.post("/telegram/login/qr/wait")
async def telegram_qr_wait(request: Request, body: QrWaitBody | None = None) -> dict[str, Any]:
    timeout = body.timeout_seconds if body else None
    try:
        result = await ctx(request).telegram.wait_qr_login(timeout)
    except Exception as exc:
        raise _telegram_http_error(exc) from exc
    return camelize(result)


@router.post("/telegram/disconnect")
async def telegram_disconnect(request: Request) -> dict[str, Any]:
    await ctx(request).telegram.disconnect()
    return camelize(await ctx(request).telegram.snapshot())


@router.get("/telegram/channels")
async def telegram_channels(request: Request) -> dict[str, Any]:
    return camelize({"channels": await ctx(request).telegram.list_channels()})


@router.post("/telegram/channels/sync")
async def telegram_sync(request: Request) -> dict[str, Any]:
    try:
        count = await ctx(request).telegram.sync_dialogs()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    channels = await ctx(request).telegram.list_channels()
    return camelize({"synced": count, "channels": channels})


@router.put("/telegram/channels")
async def telegram_subscribe(request: Request, body: SubscribeBody) -> dict[str, Any]:
    await ctx(request).telegram.set_subscriptions(body.subscribed_ids)
    return camelize({"channels": await ctx(request).telegram.list_channels()})


@router.get("/tasks")
async def get_tasks(request: Request) -> dict[str, Any]:
    app = ctx(request)
    usage_map = await billing.usage_by_task(app.db, app.settings)
    return camelize({"tasks": await batches.list_tasks(app.db, usage_map)})


@router.get("/tags")
async def get_tags(request: Request) -> dict[str, Any]:
    return camelize({"tags": await tagstore.list_tags(ctx(request).db)})


@router.post("/tags")
async def post_tag(request: Request, body: TagBody) -> dict[str, Any]:
    try:
        tag = await tagstore.create_tag(ctx(request).db, body.model_dump())
    except TagError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return camelize(tag)


@router.put("/tags/{tag_id}")
async def put_tag(request: Request, tag_id: str, body: TagPatch) -> dict[str, Any]:
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    try:
        tag = await tagstore.update_tag(ctx(request).db, tag_id, payload)
    except TagError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if tag is None:
        raise HTTPException(status_code=404, detail="找不到標籤")
    return camelize(tag)


@router.delete("/tags/{tag_id}")
async def remove_tag(request: Request, tag_id: str) -> dict[str, bool]:
    ok = await tagstore.delete_tag(ctx(request).db, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到標籤")
    return {"ok": True}


@router.post("/tasks")
async def post_task(request: Request, body: TaskBody) -> dict[str, Any]:
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="任務名稱與 prompt 必填")
    try:
        task = await batches.create_task(ctx(request).db, body.model_dump())
    except TagError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return camelize(task)


@router.put("/tasks/{task_id}")
async def put_task(request: Request, task_id: str, body: TaskPatch) -> dict[str, Any]:
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    app = ctx(request)
    released: list[dict[str, Any]] = []
    keep = app.workers.protected_batch_ids if body.enabled is False else None
    try:
        task = await batches.update_task(
            app.db,
            task_id,
            payload,
            keep_batch_ids=keep,
            released_out=released,
        )
    except TagError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="找不到任務")
    for row in released:
        app.sse.publish("queue_take", {"id": row["id"]})
    if body.enabled is not None:
        app.workers.kick()
    return camelize(task)


@router.delete("/tasks/{task_id}")
async def remove_task(request: Request, task_id: str) -> dict[str, bool]:
    app = ctx(request)
    released: list[dict[str, Any]] = []
    updated = await batches.update_task(
        app.db,
        task_id,
        {"enabled": False},
        keep_batch_ids=app.workers.protected_batch_ids,
        released_out=released,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="找不到任務")
    still_open = await batches.list_open_batch_ids(app.db, task_id)
    ok = await batches.delete_task(app.db, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="找不到任務")
    notified: set[str] = set()
    for row in released:
        batch_id = str(row["id"])
        notified.add(batch_id)
        app.sse.publish("queue_take", {"id": batch_id})
    for batch_id in still_open:
        if batch_id in notified:
            continue
        app.sse.publish("queue_take", {"id": batch_id})
    app.workers.kick()
    return {"ok": True}


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _optional_min_noul(raw: str | None) -> float | None:
    text = _blank(raw)
    if text is None:
        return None
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


@router.get("/results")
async def get_results(
    request: Request,
    limit: int = batches.HITS_PAGE_SIZE,
    cursor: str | None = None,
    q: str | None = None,
    task_id: Annotated[str | None, Query(alias="taskId")] = None,
    category: str | None = None,
    min_noul: Annotated[str | None, Query(alias="minNoul")] = None,
) -> dict[str, Any]:
    """Newest hit page first. Filters apply in SQLite so unloaded cards still match."""
    app = ctx(request)
    page_limit = batches.HITS_PAGE_SIZE if limit < 1 else min(limit, batches.HITS_PAGE_SIZE)
    try:
        page = await batches.page_hits(
            app.db,
            task_id=_blank(task_id),
            category=_blank(category),
            min_noul=_optional_min_noul(min_noul),
            query=_blank(q),
            cursor=_blank(cursor),
            limit=page_limit,
        )
    except batches.HitCursorError as exc:
        raise HTTPException(status_code=400, detail="結果游標無效") from exc
    return camelize(page)


@router.get("/stage")
async def get_stage(request: Request) -> dict[str, Any]:
    app = ctx(request)
    settings = await app.settings.snapshot()
    return camelize(
        {
            "workers": app.workers.snapshot(),
            "concurrency": live_worker_count(settings["analysis_backend"], settings["concurrency"]),
            "queue": await batches.list_queued(app.db),
            "results": await batches.list_hits(app.db, limit=batches.HITS_PAGE_SIZE),
            "active_tasks": await batches.active_task_count(app.db),
            "jev_calls": settings["jev_calls"],
            "jev_hits": settings["jev_hits"],
            "jev_misses": settings["jev_misses"],
            "jev_tokens": settings["jev_tokens"],
            "model": settings["model"],
            "analysis_backend": settings["analysis_backend"],
            "typesafe_api_key_set": settings["typesafe_api_key_set"],
            "telegram_status": (await app.telegram.snapshot())["status"],
            "message_count": await batches.stored_message_count(app.db),
            "recent_batch_error": await batches.latest_error_batch(app.db),
        }
    )


@router.get("/events")
async def events(request: Request) -> Any:
    broadcaster = ctx(request).sse
    try:
        queue = broadcaster.subscribe()
    except SseCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return event_stream(broadcaster, request, queue)


def _usage_backend(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized not in {"jev", "laya"}:
        raise HTTPException(status_code=400, detail="backend 必須是 jev 或 laya")
    return normalized


@billing_router.get("/billing/summary")
async def billing_summary(
    request: Request,
    backend: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    app = ctx(request)
    return camelize(await billing.summary(app.db, app.settings, backend=_usage_backend(backend)))


@billing_router.get("/billing/usage")
async def billing_usage(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    task_id: Annotated[str | None, Query(alias="taskId")] = None,
    backend: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    app = ctx(request)
    return camelize(
        await billing.list_usage(
            app.db,
            app.settings,
            limit=limit,
            offset=offset,
            task_id=task_id,
            backend=_usage_backend(backend),
        )
    )
