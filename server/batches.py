"""Task CRUD, batch claiming, and result queries."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from server.db import Database
from server.settings_store import KEY_ANALYSIS_MAX_AGE_DAYS, parse_analysis_max_age_days
from server.tags import ensure_task_tag_ids, list_task_tags, replace_task_tags
from server.util import new_id, parse_json, to_iso_z, utc_now_iso

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
DEFAULT_HIT_THRESHOLD = 0.65
HITS_PAGE_SIZE = 40
_OPEN_BATCH_STATUSES = ("queued", "running")
KeepBatchIds = set[str] | Callable[[], set[str]] | None


def _keep_ids(keep_batch_ids: KeepBatchIds) -> set[str]:
    """Resolve protected batch ids at the moment of the check.

    A worker can enter a Jev call while a disable request is in flight, so a
    set captured before the database work is already stale.
    """
    if keep_batch_ids is None:
        return set()
    raw = keep_batch_ids() if callable(keep_batch_ids) else keep_batch_ids
    return {str(item) for item in raw if item}


async def _channel_ids(db: Database, task_id: str) -> list[str]:
    rows = await db.fetch_all("SELECT platform_id FROM task_channels WHERE task_id = ?", (task_id,))
    return [str(row["platform_id"]) for row in rows]


_EMPTY_POOL = {"total": 0, "analyzed": 0}


async def task_pool_counts(db: Database, task_id: str | None = None) -> dict[str, dict[str, int]]:
    """Count messages a task can see, and how many already carry its marker.

    Same subscribed chats and age window as claim. Age 0 counts every stored
    message in those chats. Disabled tasks stay in the result.
    """
    cutoff = await _analysis_cutoff(db)
    clauses = ["1 = 1"]
    params: list[Any] = []
    if task_id is not None:
        clauses.append("tc.task_id = ?")
        params.append(task_id)
    if cutoff:
        clauses.append("m.timestamp >= ?")
        params.append(cutoff)
    rows = await db.fetch_all(
        "SELECT tc.task_id AS task_id, COUNT(*) AS total, "
        "COALESCE(SUM(CASE WHEN am.message_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS analyzed "
        "FROM task_channels tc "
        "JOIN messages m ON m.chat_id = tc.platform_id "
        "LEFT JOIN analysis_markers am ON am.message_id = m.id AND am.task_id = tc.task_id "
        f"WHERE {' AND '.join(clauses)} "
        "GROUP BY tc.task_id",
        tuple(params),
    )
    return {
        str(row["task_id"]): {"total": int(row["total"] or 0), "analyzed": int(row["analyzed"] or 0)}
        for row in rows
    }


async def serialize_task(
    db: Database,
    row: dict[str, Any],
    pools: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    task_id = str(row["id"])
    tags = await list_task_tags(db, task_id)
    if pools is None:
        pools = await task_pool_counts(db, task_id)
    pool = pools.get(task_id, _EMPTY_POOL)
    return {
        "id": task_id,
        "name": row["name"],
        "prompt": row["prompt"],
        "batch_size": int(row["batch_size"]),
        "hit_threshold": float(row["hit_threshold"]),
        "tag_ids": [str(tag["id"]) for tag in tags],
        "tags": tags,
        "channel_ids": await _channel_ids(db, task_id),
        "enabled": bool(row["enabled"]),
        "priority": int(row["priority"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pool": {"total": int(pool["total"]), "analyzed": int(pool["analyzed"])},
    }


async def list_tasks(db: Database, usage_map: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM tasks ORDER BY priority DESC, created_at DESC")
    pools = await task_pool_counts(db)
    tasks = [await serialize_task(db, row, pools) for row in rows]
    if not usage_map:
        return tasks
    for task in tasks:
        stats = usage_map.get(str(task["id"]))
        if stats:
            task["usage"] = stats
    return tasks


async def get_task(db: Database, task_id: str) -> dict[str, Any] | None:
    row = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        return None
    return await serialize_task(db, row)


async def replace_task_channels(db: Database, task_id: str, channel_ids: list[str]) -> None:
    await db.execute("DELETE FROM task_channels WHERE task_id = ?", (task_id,))
    if channel_ids:
        await db.execute_many(
            "INSERT OR IGNORE INTO task_channels (task_id, platform_id) VALUES (?, ?)",
            [(task_id, str(cid)) for cid in channel_ids],
        )


async def create_task(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    await ensure_task_tag_ids(db, list(payload.get("tag_ids") or []))
    task_id = new_id()
    now = utc_now_iso()
    await db.execute(
        "INSERT INTO tasks (id, name, prompt, batch_size, hit_threshold, enabled, priority, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            str(payload["name"]).strip(),
            str(payload["prompt"]).strip(),
            int(payload.get("batch_size") or DEFAULT_BATCH_SIZE),
            float(payload.get("hit_threshold") if payload.get("hit_threshold") is not None else DEFAULT_HIT_THRESHOLD),
            1 if payload.get("enabled", True) else 0,
            int(payload.get("priority") or 0),
            now,
            now,
        ),
    )
    await replace_task_channels(db, task_id, list(payload.get("channel_ids") or []))
    await replace_task_tags(db, task_id, list(payload.get("tag_ids") or []))
    task = await get_task(db, task_id)
    assert task is not None
    return task


async def update_task(
    db: Database,
    task_id: str,
    payload: dict[str, Any],
    *,
    keep_batch_ids: KeepBatchIds = None,
    released_out: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    existing = await db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if existing is None:
        return None
    if "tag_ids" in payload:
        await ensure_task_tag_ids(db, list(payload.get("tag_ids") or []))
    name = str(payload["name"]).strip() if "name" in payload else existing["name"]
    prompt = str(payload["prompt"]).strip() if "prompt" in payload else existing["prompt"]
    batch_size = int(payload["batch_size"]) if "batch_size" in payload else int(existing["batch_size"])
    threshold = float(payload["hit_threshold"]) if "hit_threshold" in payload else float(existing["hit_threshold"])
    enabled = existing["enabled"] if "enabled" not in payload else (1 if payload["enabled"] else 0)
    priority = int(payload["priority"]) if "priority" in payload else int(existing["priority"])
    await db.execute(
        "UPDATE tasks SET name=?, prompt=?, batch_size=?, hit_threshold=?, enabled=?, priority=?, updated_at=? "
        "WHERE id=?",
        (name, prompt, max(1, batch_size), min(1.0, max(0.0, threshold)), enabled, priority, utc_now_iso(), task_id),
    )
    if "channel_ids" in payload:
        await replace_task_channels(db, task_id, list(payload.get("channel_ids") or []))
    if "tag_ids" in payload:
        await replace_task_tags(db, task_id, list(payload.get("tag_ids") or []))
    if "enabled" in payload and not enabled:
        released = await release_disabled_task_batches(db, task_id=task_id, keep_batch_ids=keep_batch_ids)
        if released_out is not None:
            released_out.extend(released)
    return await get_task(db, task_id)


async def delete_task(db: Database, task_id: str) -> bool:
    changed = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return changed > 0


def serialize_batch(row: dict[str, Any], *, task_name: str | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "task_name": task_name,
        "status": row["status"],
        "message_count": int(row["message_count"] or 0),
        "hit_count": int(row.get("hit_count") or 0),
        "noul": row.get("noul"),
        "confidence": row.get("confidence"),
        "category": row.get("category"),
        "category_confidence": row.get("category_confidence"),
        "error_message": row.get("error_message"),
        "time_start": row.get("time_start"),
        "time_end": row.get("time_end"),
        "worker_id": row.get("worker_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row.get("completed_at"),
    }


def serialize_hit_card(
    *,
    batch_id: str,
    message_id: str,
    task_id: str,
    task_name: str | None,
    category: str | None,
    category_confidence: float | None,
    hit_count: int,
    message_count: int,
    noul: float | None,
    ordinal: int | None,
    chat_id: str | None,
    chat_name: str | None,
    sender_name: str | None,
    content: str | None,
    timestamp: str | None,
    images: list[dict[str, Any]] | None,
    created_at: str | None,
    updated_at: str | None,
    completed_at: str | None,
) -> dict[str, Any]:
    clean_images = [item for item in (images or []) if isinstance(item, dict) and item.get("base64")]
    return {
        "id": f"{batch_id}:{message_id}",
        "batch_id": batch_id,
        "message_id": message_id,
        "task_id": task_id,
        "task_name": task_name,
        "status": "hit",
        "noul": noul,
        "category": category,
        "category_confidence": category_confidence,
        "chat_id": chat_id,
        "chat_name": chat_name,
        "sender_name": sender_name,
        "content": content,
        "timestamp": timestamp,
        "ordinal": ordinal,
        "images": clean_images,
        "hit_count": hit_count,
        "message_count": message_count,
        "created_at": created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
    }


class HitCursorError(ValueError):
    """Opaque results cursor could not be decoded."""


_HIT_SORT = "COALESCE(b.completed_at, b.updated_at, '')"


def _like_needle(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped.lower()}%"


def _encode_hit_cursor(row: dict[str, Any]) -> str:
    payload = {
        "t": str(row.get("sort_at") or ""),
        "b": str(row["batch_id"]),
        "o": int(row.get("ordinal") or 0),
        "m": str(row["message_id"]),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_hit_cursor(token: str) -> tuple[str, str, int, str]:
    pad = "=" * (-len(token) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(token + pad))
        sort_at = str(data["t"])
        batch_id = str(data["b"])
        ordinal = int(data["o"])
        message_id = str(data["m"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HitCursorError(token) from None
    if not batch_id or not message_id:
        raise HitCursorError(token)
    return sort_at, batch_id, ordinal, message_id


def _hit_card(row: dict[str, Any]) -> dict[str, Any]:
    images = parse_json(row.get("images_json"), [])
    return serialize_hit_card(
        batch_id=str(row["batch_id"]),
        message_id=str(row["message_id"]),
        task_id=str(row["task_id"]),
        task_name=str(row.get("task_name") or ""),
        category=row.get("category"),
        category_confidence=row.get("category_confidence"),
        hit_count=int(row.get("hit_count") or 0),
        message_count=int(row.get("message_count") or 0),
        noul=row.get("noul"),
        ordinal=row.get("ordinal"),
        chat_id=row.get("chat_id"),
        chat_name=row.get("chat_name"),
        sender_name=row.get("sender_name"),
        content=row.get("content"),
        timestamp=row.get("timestamp"),
        images=images if isinstance(images, list) else [],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        completed_at=row.get("completed_at"),
    )


def _hit_where(
    *,
    task_id: str | None,
    category: str | None,
    min_noul: float | None,
    query: str | None,
    cursor: str | None,
) -> tuple[str, list[Any]]:
    clauses = ["b.status = 'hit'", "COALESCE(bm.hit, 1) = 1"]
    params: list[Any] = []
    if task_id:
        clauses.append("b.task_id = ?")
        params.append(task_id)
    if category:
        clauses.append("b.category = ?")
        params.append(category)
    if min_noul is not None:
        clauses.append("COALESCE(bm.noul, 0) >= ?")
        params.append(min_noul)
    needle = (query or "").strip()
    if needle:
        like = _like_needle(needle)
        clauses.append(
            "(LOWER(COALESCE(bm.content, '')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(bm.sender_name, '')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(bm.chat_name, '')) LIKE ? ESCAPE '\\')"
        )
        params.extend((like, like, like))
    if cursor:
        sort_at, batch_id, ordinal, message_id = _decode_hit_cursor(cursor)
        clauses.append(
            f"({_HIT_SORT} < ? OR ({_HIT_SORT} = ? AND bm.batch_id < ?) "
            f"OR ({_HIT_SORT} = ? AND bm.batch_id = ? AND bm.ordinal > ?) "
            f"OR ({_HIT_SORT} = ? AND bm.batch_id = ? AND bm.ordinal = ? AND bm.message_id > ?))"
        )
        params.extend(
            (
                sort_at,
                sort_at,
                batch_id,
                sort_at,
                batch_id,
                ordinal,
                sort_at,
                batch_id,
                ordinal,
                message_id,
            )
        )
    return " AND ".join(clauses), params


async def page_hits(
    db: Database,
    *,
    task_id: str | None = None,
    category: str | None = None,
    min_noul: float | None = None,
    query: str | None = None,
    cursor: str | None = None,
    limit: int = HITS_PAGE_SIZE,
) -> dict[str, Any]:
    """Newest matching hits first. `next_cursor` continues toward older cards."""
    page_limit = max(1, min(int(limit), 200))
    where, params = _hit_where(
        task_id=task_id,
        category=category,
        min_noul=min_noul,
        query=query,
        cursor=None,
    )
    total_row = await db.fetch_one(
        "SELECT COUNT(*) AS n "
        "FROM batch_messages bm "
        "JOIN analysis_batches b ON b.id = bm.batch_id "
        "JOIN tasks t ON t.id = b.task_id "
        f"WHERE {where}",
        tuple(params),
    )
    total = int((total_row or {}).get("n") or 0)
    where, params = _hit_where(
        task_id=task_id,
        category=category,
        min_noul=min_noul,
        query=query,
        cursor=cursor,
    )
    rows = await db.fetch_all(
        "SELECT bm.batch_id, bm.message_id, bm.ordinal, bm.chat_id, bm.chat_name, bm.sender_name, "
        "bm.content, bm.timestamp, bm.noul, bm.images_json, "
        "b.task_id, b.category, b.category_confidence, b.hit_count, b.message_count, "
        "b.created_at, b.updated_at, b.completed_at, t.name AS task_name, "
        f"{_HIT_SORT} AS sort_at "
        "FROM batch_messages bm "
        "JOIN analysis_batches b ON b.id = bm.batch_id "
        "JOIN tasks t ON t.id = b.task_id "
        f"WHERE {where} "
        f"ORDER BY {_HIT_SORT} DESC, bm.batch_id DESC, bm.ordinal ASC, bm.message_id ASC "
        "LIMIT ?",
        tuple([*params, page_limit + 1]),
    )
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = _encode_hit_cursor(page_rows[-1]) if has_more and page_rows else None
    return {
        "items": [_hit_card(row) for row in page_rows],
        "limit": page_limit,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "total": total,
    }


async def list_hits(
    db: Database,
    *,
    task_id: str | None = None,
    category: str | None = None,
    min_noul: float | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    page = await page_hits(
        db,
        task_id=task_id,
        category=category,
        min_noul=min_noul,
        limit=limit,
    )
    return list(page["items"])


async def list_queued(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT b.*, t.name AS task_name FROM analysis_batches b "
        "JOIN tasks t ON t.id = b.task_id "
        "WHERE b.status = 'queued' ORDER BY b.created_at ASC LIMIT 40"
    )
    return [serialize_batch(row, task_name=str(row.get("task_name") or "")) for row in rows]


async def latest_error_batch(db: Database) -> dict[str, Any] | None:
    """Latest failed batch for the status banner. Read-only; never deletes the row."""
    row = await db.fetch_one(
        "SELECT b.*, t.name AS task_name FROM analysis_batches b "
        "JOIN tasks t ON t.id = b.task_id "
        "WHERE b.status = 'error' "
        "ORDER BY COALESCE(b.completed_at, b.updated_at) DESC LIMIT 1"
    )
    if not row:
        return None
    return serialize_batch(row, task_name=str(row.get("task_name") or ""))


async def get_batch(db: Database, batch_id: str) -> dict[str, Any] | None:
    row = await db.fetch_one(
        "SELECT b.*, t.name AS task_name FROM analysis_batches b "
        "JOIN tasks t ON t.id = b.task_id WHERE b.id = ?",
        (batch_id,),
    )
    if row is None:
        return None
    return serialize_batch(row, task_name=str(row.get("task_name") or ""))


async def recover_running_batches(db: Database) -> int:
    changed = await db.execute(
        "UPDATE analysis_batches SET status = 'queued', worker_id = NULL, updated_at = ? WHERE status = 'running'",
        (utc_now_iso(),),
    )
    return int(changed or 0)


async def requeue_batch(db: Database, batch_id: str) -> bool:
    changed = await db.execute(
        "UPDATE analysis_batches SET status = 'queued', worker_id = NULL, updated_at = ? "
        "WHERE id = ? AND status = 'running'",
        (utc_now_iso(), batch_id),
    )
    return int(changed or 0) > 0


async def queued_count(db: Database) -> int:
    value = await db.fetch_value("SELECT COUNT(*) FROM analysis_batches WHERE status = 'queued'")
    return int(value or 0)


async def stored_message_count(db: Database) -> int:
    value = await db.fetch_value("SELECT COUNT(*) FROM messages")
    return int(value or 0)


async def _analysis_cutoff(db: Database) -> str | None:
    """ISO timestamp lower bound, or None when the global window is unlimited."""
    raw = await db.fetch_value("SELECT value FROM settings WHERE key = ?", (KEY_ANALYSIS_MAX_AGE_DAYS,))
    days = parse_analysis_max_age_days(raw)
    if days <= 0:
        return None
    return to_iso_z(datetime.now(UTC) - timedelta(days=days))


async def claim_new_batch(db: Database) -> dict[str, Any] | None:
    """Occupy the next unanalyzed pair for the highest-priority enabled task."""
    cutoff = await _analysis_cutoff(db)
    tasks = await db.fetch_all(
        "SELECT * FROM tasks WHERE enabled = 1 ORDER BY priority DESC, created_at ASC"
    )
    for task in tasks:
        claimed = await _claim_for_task(db, task, cutoff)
        if claimed:
            return claimed
    return None


async def _claim_for_task(db: Database, task: dict[str, Any], cutoff: str | None = None) -> dict[str, Any] | None:
    task_id = str(task["id"])
    batch_size = max(1, int(task["batch_size"] or DEFAULT_BATCH_SIZE))
    channels = await _channel_ids(db, task_id)
    if not channels:
        return None
    placeholders = ",".join("?" * len(channels))
    age_sql = "AND m.timestamp >= ? " if cutoff else ""
    sql = (
        "SELECT m.* FROM messages m "
        f"WHERE m.chat_id IN ({placeholders}) "
        f"{age_sql}"
        "AND NOT EXISTS (SELECT 1 FROM analysis_markers am WHERE am.message_id = m.id AND am.task_id = ?) "
        "ORDER BY m.timestamp ASC, m.id ASC LIMIT ?"
    )
    params: tuple[Any, ...] = (*channels, cutoff, task_id, batch_size) if cutoff else (*channels, task_id, batch_size)
    now = utc_now_iso()
    batch_id = new_id()
    async with db.transaction() as conn:
        async with conn.execute("SELECT enabled FROM tasks WHERE id = ?", (task_id,)) as cursor:
            task_row = await cursor.fetchone()
        if task_row is None or not int(task_row["enabled"]):
            return None
        async with conn.execute(sql, params) as cursor:
            messages = [dict(row) for row in await cursor.fetchall()]
        if len(messages) < batch_size:
            return None
        message_ids = [str(row["id"]) for row in messages]
        await conn.execute(
            "INSERT INTO analysis_batches "
            "(id, task_id, status, message_ids_json, message_count, time_start, time_end, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                task_id,
                json.dumps(message_ids),
                len(messages),
                messages[0].get("timestamp"),
                messages[-1].get("timestamp"),
                now,
                now,
            ),
        )
        marker_rows = [(new_id(), mid, task_id, batch_id, now) for mid in message_ids]
        await conn.executemany(
            "INSERT INTO analysis_markers (id, message_id, task_id, batch_id, analyzed_at) VALUES (?, ?, ?, ?, ?)",
            marker_rows,
        )
    row = await db.fetch_one("SELECT * FROM analysis_batches WHERE id = ?", (batch_id,))
    return row


async def take_queued_batch(db: Database, worker_id: int) -> dict[str, Any] | None:
    now = utc_now_iso()
    async with db.transaction() as conn:
        async with conn.execute(
            "SELECT b.* FROM analysis_batches b "
            "JOIN tasks t ON t.id = b.task_id "
            "WHERE b.status = 'queued' AND t.enabled = 1 "
            "ORDER BY t.priority DESC, b.created_at ASC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        batch = dict(row)
        cursor = await conn.execute(
            "UPDATE analysis_batches SET status = 'running', worker_id = ?, updated_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (worker_id, now, batch["id"]),
        )
        if int(cursor.rowcount or 0) != 1:
            return None
        batch["status"] = "running"
        batch["worker_id"] = worker_id
        batch["updated_at"] = now
        return batch


async def load_batch_source_messages(db: Database, batch: dict[str, Any]) -> list[dict[str, Any]]:
    ids = parse_json(batch.get("message_ids_json"), [])
    if not isinstance(ids, list) or not ids:
        rows = await db.fetch_all(
            "SELECT m.* FROM messages m JOIN analysis_markers am ON am.message_id = m.id "
            "WHERE am.batch_id = ? ORDER BY m.timestamp ASC, m.id ASC",
            (batch["id"],),
        )
        return rows
    placeholders = ",".join("?" * len(ids))
    rows = await db.fetch_all(
        f"SELECT * FROM messages WHERE id IN ({placeholders})",
        tuple(str(item) for item in ids),
    )
    order = {str(mid): index for index, mid in enumerate(ids)}
    rows.sort(key=lambda row: order.get(str(row["id"]), 10_000))
    return rows


async def snapshot_hit_messages(db: Database, batch_id: str, hits: list[dict[str, Any]]) -> None:
    """Persist only messages at or above the task threshold, with per-message noul and JPEGs."""
    rows = []
    for item in hits:
        images = item.get("images") or []
        if not isinstance(images, list):
            images = []
        rows.append(
            (
                batch_id,
                str(item["id"]),
                int(item.get("i") or item.get("ordinal") or 0),
                item.get("chat_id"),
                item.get("chat_name"),
                item.get("sender_name"),
                item.get("content"),
                item.get("timestamp"),
                float(item["noul"]),
                1,
                json.dumps(images, ensure_ascii=False),
            )
        )
    await db.execute("DELETE FROM batch_messages WHERE batch_id = ?", (batch_id,))
    await db.execute_many(
        "INSERT INTO batch_messages "
        "(batch_id, message_id, ordinal, chat_id, chat_name, sender_name, content, timestamp, noul, hit, images_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


async def complete_batch(
    db: Database,
    *,
    batch_id: str,
    status: str,
    noul: float | None = None,
    confidence: float | None = None,
    category: str | None = None,
    category_confidence: float | None = None,
    jev_raw: dict[str, Any] | None = None,
    error_message: str | None = None,
    hit_count: int = 0,
) -> dict[str, Any] | None:
    now = utc_now_iso()
    await db.execute(
        "UPDATE analysis_batches SET status=?, noul=?, confidence=?, category=?, category_confidence=?, "
        "hit_count=?, jev_raw_json=?, error_message=?, completed_at=?, updated_at=? WHERE id=?",
        (
            status,
            noul,
            confidence,
            category,
            category_confidence,
            int(hit_count),
            json.dumps(jev_raw, ensure_ascii=False) if jev_raw is not None else None,
            error_message,
            now,
            now,
            batch_id,
        ),
    )
    return await get_batch(db, batch_id)


async def release_markers(db: Database, batch_id: str) -> None:
    await db.execute("DELETE FROM analysis_markers WHERE batch_id = ?", (batch_id,))


async def cancel_open_batch(
    db: Database,
    batch_id: str,
    *,
    statuses: tuple[str, ...] = _OPEN_BATCH_STATUSES,
    keep_batch_ids: KeepBatchIds = None,
) -> bool:
    """Remove a queued or running batch and the markers that claim its messages.

    Messages are left in place and are not marked analyzed. A batch that has
    already reached hit, miss, or error is left alone. Deleting the batch
    cascades ``analysis_markers``; the explicit marker delete covers the same
    rows if the cascade does not run.
    """
    allowed = tuple(status for status in statuses if status in _OPEN_BATCH_STATUSES)
    if not allowed:
        return False
    placeholders = ",".join("?" * len(allowed))
    async with db.transaction() as conn:
        async with conn.execute("SELECT status FROM analysis_batches WHERE id = ?", (batch_id,)) as cursor:
            existing = await cursor.fetchone()
        if existing is None or str(existing["status"]) not in allowed:
            return False
        if str(existing["status"]) == "running" and batch_id in _keep_ids(keep_batch_ids):
            return False
        await conn.execute(
            f"DELETE FROM analysis_batches WHERE id = ? AND status IN ({placeholders})",
            (batch_id, *allowed),
        )
        async with conn.execute("SELECT 1 FROM analysis_batches WHERE id = ?", (batch_id,)) as cursor:
            still_there = await cursor.fetchone()
        if still_there is not None:
            return False
        # Batch delete cascades markers. Repeat the delete so a claim cannot
        # survive if the foreign-key cascade did not run.
        await conn.execute("DELETE FROM analysis_markers WHERE batch_id = ?", (batch_id,))
    return True


async def list_open_batch_ids(db: Database, task_id: str) -> list[str]:
    rows = await db.fetch_all(
        "SELECT id FROM analysis_batches WHERE task_id = ? AND status IN ('queued', 'running') ORDER BY created_at ASC",
        (task_id,),
    )
    return [str(row["id"]) for row in rows]


async def release_disabled_task_batches(
    db: Database,
    *,
    task_id: str | None = None,
    keep_batch_ids: KeepBatchIds = None,
) -> list[dict[str, Any]]:
    """Cancel open batches for disabled tasks and unclaim their messages.

    Queued batches are always removed. Running batches are removed unless their
    id is currently protected (a worker is inside a Jev call). ``keep_batch_ids``
    may be a callable so that protection is read at each delete, not from a
    snapshot taken before this function awaited. Global pause is not consulted:
    paused-but-enabled tasks keep their queue.
    """
    clauses = ["t.enabled = 0", "b.status IN ('queued', 'running')"]
    params: list[Any] = []
    if task_id is not None:
        clauses.append("b.task_id = ?")
        params.append(task_id)
    rows = await db.fetch_all(
        "SELECT b.id, b.task_id, b.status, b.message_count, t.name AS task_name "
        "FROM analysis_batches b JOIN tasks t ON t.id = b.task_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY b.created_at ASC",
        tuple(params),
    )
    released: list[dict[str, Any]] = []
    for row in rows:
        batch_id = str(row["id"])
        status = str(row["status"])
        if status == "running" and batch_id in _keep_ids(keep_batch_ids):
            continue
        # Only delete the status we observed, so a batch taken into an active
        # call between the select and the delete is left for that worker.
        if not await cancel_open_batch(db, batch_id, statuses=(status,), keep_batch_ids=keep_batch_ids):
            continue
        released.append(
            {
                "id": batch_id,
                "task_id": str(row["task_id"]),
                "task_name": str(row.get("task_name") or ""),
                "status": status,
                "message_count": int(row.get("message_count") or 0),
            }
        )
    if released:
        logger.info("Cancelled %s open batch(es) for disabled tasks", len(released))
    return released


async def active_task_count(db: Database) -> int:
    value = await db.fetch_value("SELECT COUNT(*) FROM tasks WHERE enabled = 1")
    return int(value or 0)
