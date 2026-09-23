"""Global tags. Jev and Laya share this list; the call appends reserved `other`."""

from __future__ import annotations

import re
from typing import Any

from server.db import Database
from server.util import new_id, parse_json, utc_now_iso

RESERVED_TAG_KEY = "other"
KEY_MAX = 64
LABEL_MAX = 80
DESC_MAX = 400
# Jev Choice allows 255 options. Calls always append reserved `other`.
MAX_TASK_TAGS = 254


class TagError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def serialize_tag(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "label": row["label"],
        "description": row.get("description") or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def normalize_key(raw: str, *, allow_empty: bool = False) -> str:
    key = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not key:
        if allow_empty:
            return ""
        raise TagError("標籤 key 必填")
    if key.casefold() == RESERVED_TAG_KEY:
        raise TagError("other 為系統保留，無法作為自訂標籤")
    if len(key) > KEY_MAX:
        raise TagError(f"key 最長 {KEY_MAX} 字")
    if any(ord(ch) < 32 for ch in key):
        raise TagError("key 不可含控制字元")
    return key


def normalize_label(raw: str) -> str:
    label = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not label:
        raise TagError("標籤名稱必填")
    if len(label) > LABEL_MAX:
        raise TagError(f"名稱最長 {LABEL_MAX} 字")
    return label


def normalize_description(raw: str) -> str:
    text = str(raw or "").strip()
    if len(text) > DESC_MAX:
        raise TagError(f"說明最長 {DESC_MAX} 字")
    return text


def _slug_from_label(label: str) -> str:
    text = label.casefold().strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    text = re.sub(r"[-_]+", "-", text).strip("-_")
    return text[:KEY_MAX]


def _embedded_categories(raw: Any) -> list[dict[str, str]]:
    parsed = parse_json(raw, [])
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        out.append({"label": label, "description": str(item.get("description") or "").strip()})
    return out


async def list_tags(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM tags ORDER BY label COLLATE NOCASE ASC, key COLLATE NOCASE ASC")
    return [serialize_tag(row) for row in rows]


async def get_tag(db: Database, tag_id: str) -> dict[str, Any] | None:
    row = await db.fetch_one("SELECT * FROM tags WHERE id = ?", (tag_id,))
    if row is None:
        return None
    return serialize_tag(row)


async def _unique_key(db: Database, desired: str, *, exclude_id: str | None = None) -> str:
    base = desired
    suffix = 2
    while True:
        row = await db.fetch_one("SELECT id FROM tags WHERE key = ?", (base,))
        if row is None or (exclude_id and str(row["id"]) == exclude_id):
            return base
        trimmed = desired[: max(1, KEY_MAX - 3)]
        base = f"{trimmed}-{suffix}"[:KEY_MAX]
        suffix += 1
        if suffix > 99:
            return f"t-{new_id()[:10]}"


async def upsert_tag(db: Database, *, key: str, label: str, description: str) -> dict[str, Any]:
    existing = await db.fetch_one("SELECT * FROM tags WHERE key = ?", (key,))
    now = utc_now_iso()
    if existing:
        next_desc = str(existing.get("description") or "")
        if not next_desc and description:
            next_desc = description
        next_label = str(existing.get("label") or label)
        await db.execute(
            "UPDATE tags SET label=?, description=?, updated_at=? WHERE id=?",
            (next_label, next_desc, now, existing["id"]),
        )
        tag = await get_tag(db, str(existing["id"]))
        assert tag is not None
        return tag
    tag_id = new_id()
    await db.execute(
        "INSERT INTO tags (id, key, label, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (tag_id, key, label, description, now, now),
    )
    tag = await get_tag(db, tag_id)
    assert tag is not None
    return tag


async def create_tag(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    label = normalize_label(str(payload.get("label") or ""))
    description = normalize_description(str(payload.get("description") or ""))
    supplied = normalize_key(str(payload.get("key") or ""), allow_empty=True)
    if supplied:
        clash = await db.fetch_one("SELECT id FROM tags WHERE key = ?", (supplied,))
        if clash:
            raise TagError("key 已被使用", status_code=409)
        key = supplied
    else:
        generated = _slug_from_label(label)
        if not generated or generated.casefold() == RESERVED_TAG_KEY:
            generated = f"t-{new_id()[:10]}"
        key = await _unique_key(db, generated)
    return await upsert_tag(db, key=key, label=label, description=description)


async def update_tag(db: Database, tag_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = await db.fetch_one("SELECT * FROM tags WHERE id = ?", (tag_id,))
    if existing is None:
        return None
    label = normalize_label(str(payload["label"])) if "label" in payload else str(existing["label"])
    description = (
        normalize_description(str(payload["description"])) if "description" in payload else str(existing.get("description") or "")
    )
    if "key" in payload:
        key = normalize_key(str(payload["key"]))
        clash = await db.fetch_one("SELECT id FROM tags WHERE key = ? AND id != ?", (key, tag_id))
        if clash:
            raise TagError("key 已被使用", status_code=409)
    else:
        key = str(existing["key"])
    await db.execute(
        "UPDATE tags SET key=?, label=?, description=?, updated_at=? WHERE id=?",
        (key, label, description, utc_now_iso(), tag_id),
    )
    return await get_tag(db, tag_id)


async def delete_tag(db: Database, tag_id: str) -> bool:
    changed = await db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    return changed > 0


async def list_task_tags(db: Database, task_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT t.* FROM tags t JOIN task_tags tt ON tt.tag_id = t.id "
        "WHERE tt.task_id = ? ORDER BY t.label COLLATE NOCASE ASC, t.key COLLATE NOCASE ASC",
        (task_id,),
    )
    return [serialize_tag(row) for row in rows]


async def resolve_tag_ids(db: Database, tag_ids: list[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in tag_ids:
        tag_id = str(raw or "").strip()
        if not tag_id or tag_id in seen:
            continue
        row = await db.fetch_one("SELECT id, key FROM tags WHERE id = ?", (tag_id,))
        if row is None:
            raise TagError("找不到所選標籤")
        if str(row["key"]).casefold() == RESERVED_TAG_KEY:
            continue
        seen.add(tag_id)
        unique.append(tag_id)
    return unique


async def ensure_task_tag_ids(db: Database, tag_ids: list[Any]) -> list[str]:
    """Resolve custom tag ids and reject a selection above the Choice cap.

    Reserved `other` is omitted by resolve_tag_ids and does not count.
    """
    resolved = await resolve_tag_ids(db, tag_ids)
    if len(resolved) > MAX_TASK_TAGS:
        raise TagError(f"每個任務最多選擇 {MAX_TASK_TAGS} 個標籤")
    return resolved


async def replace_task_tags(db: Database, task_id: str, tag_ids: list[str]) -> None:
    resolved = await ensure_task_tag_ids(db, tag_ids)
    await db.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
    if resolved:
        await db.execute_many(
            "INSERT OR IGNORE INTO task_tags (task_id, tag_id) VALUES (?, ?)",
            [(task_id, tag_id) for tag_id in resolved],
        )


def choice_tags(tags: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Category options for one batch. Both backends consume this list."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in tags:
        key = str(item.get("key") or "").strip()
        if not key or key.casefold() == RESERVED_TAG_KEY or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "key": key,
                "label": str(item.get("label") or key),
                "description": str(item.get("description") or "").strip(),
            }
        )
    return out


async def migrate_embedded_categories(db: Database) -> int:
    """Upsert leftover per-task categories_json into global tags, then drop the column."""
    if "categories_json" not in await db._column_names("tasks"):
        return 0
    rows = await db.fetch_all("SELECT id, categories_json FROM tasks")
    moved = 0
    for row in rows:
        cats = _embedded_categories(row.get("categories_json"))
        if not cats:
            continue
        task_id = str(row["id"])
        selected: list[str] = []
        for item in cats:
            label = item["label"]
            if label.casefold() == RESERVED_TAG_KEY:
                continue
            try:
                key = normalize_key(label)
            except TagError:
                key = _slug_from_label(label) or f"t-{new_id()[:10]}"
                if key.casefold() == RESERVED_TAG_KEY:
                    key = f"t-{new_id()[:10]}"
            tag = await upsert_tag(db, key=key, label=label, description=item["description"])
            selected.append(str(tag["id"]))
            moved += 1
        await replace_task_tags(db, task_id, selected)
    await db.execute("ALTER TABLE tasks DROP COLUMN categories_json")
    return moved
