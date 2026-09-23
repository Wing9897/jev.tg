"""Call ledger for both analysis backends.

Jev rows may carry TypeSafe tokens and USD. Laya rows are local and must stay
out of dollar totals. `_is_laya_row` is the Python form of `_LAYA_SQL` /
`_NOT_LAYA_SQL`. `_backend_scope` applies those predicates to summary and
ledger queries. Task totals use the same not-Laya predicate for estimates.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from server.db import Database
from server.settings_store import SettingsStore
from server.util import new_id, utc_now_iso

logger = logging.getLogger(__name__)

RATES_NOTE = (
    "TypeSafe 官方 Usage 只有 input_tokens / output_tokens，沒有 cost_usd 或餘額。"
    "OpenAPI 標註輸入 token 為 billable、輸出目前免費。"
    "預設估計單價沿用 hosted jevtypesafeai 約 $0.42 / 百萬輸入 token；"
    "直連 api.typesafe.ai 實際費率可能不同。請只在 API 未回傳 cost 時把結果標為「估計」。"
)

COST_KEYS = ("cost_usd", "costUsd", "usd_cost", "total_cost_usd", "totalCostUsd")
CREDIT_KEYS = (
    "credits_remaining",
    "creditsRemaining",
    "remaining_credits",
    "remainingCredits",
    "credit_balance",
    "creditBalance",
)
CREDIT_HEADERS = (
    "x-typesafe-credits-remaining",
    "x-credits-remaining",
    "x-typesafe-credit-balance",
)
# Local Laya rows must not be priced with the TypeSafe estimate.
# NULL backend is legacy Jev, so the two predicates are not logical negations.
_LAYA_SQL = "backend = 'laya' OR COALESCE(cost_source, '') = 'laya'"
_NOT_LAYA_SQL = "COALESCE(backend, 'jev') != 'laya' AND COALESCE(cost_source, '') != 'laya'"
_ESTIMATE_ROW_SQL = (
    f"{_NOT_LAYA_SQL} AND cost_usd IS NULL AND (input_tokens IS NOT NULL OR output_tokens IS NOT NULL)"
)
_ESTIMATE_INPUT_SQL = f"CASE WHEN {_NOT_LAYA_SQL} AND cost_usd IS NULL THEN COALESCE(input_tokens, 0) ELSE 0 END"
_ESTIMATE_OUTPUT_SQL = f"CASE WHEN {_NOT_LAYA_SQL} AND cost_usd IS NULL THEN COALESCE(output_tokens, 0) ELSE 0 END"

INSUFFICIENT_RE = re.compile(
    r"(insufficient\s+(credits?|balance|funds)|payment required|額度不足|余额不足|credit(?:s)?\s+(?:exhausted|exceeded))",
    re.IGNORECASE,
)


def estimate_usd(input_tokens: int | None, output_tokens: int | None, input_rate: float, output_rate: float) -> float | None:
    if input_tokens is None and output_tokens is None:
        return None
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    usd = (inp / 1_000_000.0) * float(input_rate) + (out / 1_000_000.0) * float(output_rate)
    if not math.isfinite(usd):
        return None
    return usd


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _pick(mapping: Any, keys: tuple[str, ...], parse: Callable[[Any], Any]) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        if key in mapping and mapping[key] is not None:
            parsed = parse(mapping[key])
            if parsed is not None:
                return parsed
    return None


def _pick_float(mapping: Any, keys: tuple[str, ...]) -> float | None:
    return _pick(mapping, keys, _as_float)


def _pick_int(mapping: Any, keys: tuple[str, ...]) -> int | None:
    return _pick(mapping, keys, _as_int)


def _header_map(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return {str(key).lower(): str(value) for key, value in headers.items()}
    except Exception:
        return {}


def _decode_body(content: Any) -> Any:
    if content is None:
        return None
    if isinstance(content, (dict, list)):
        return content
    if isinstance(content, bytes):
        if not content:
            return None
        try:
            return json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
    if isinstance(content, str):
        text = content.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def extract_from_payload(body: Any, headers: Any = None) -> dict[str, Any]:
    """Pull optional cost / remaining-credits from a TypeSafe JSON body or headers.

    Official `Usage` only has input_tokens and output_tokens. Extra fields are ignored by
    the SDK model (`extra="ignore"`), so we read the raw payload when present.
    Never invent remaining credits: omit the field unless the API actually sent it.
    """
    decoded = _decode_body(body) if not isinstance(body, dict) else body
    usage = decoded.get("usage") if isinstance(decoded, dict) else None
    header_map = _header_map(headers)

    cost = _pick_float(usage, COST_KEYS) or _pick_float(decoded, COST_KEYS)
    if cost is None and isinstance(decoded, dict):
        billing = decoded.get("billing")
        cost = _pick_float(billing, COST_KEYS)

    credits = _pick_float(usage, CREDIT_KEYS) or _pick_float(decoded, CREDIT_KEYS)
    if credits is None and isinstance(decoded, dict):
        credits = _pick_float(decoded.get("billing"), CREDIT_KEYS)
    if credits is None:
        for name in CREDIT_HEADERS:
            if name in header_map:
                credits = _as_float(header_map[name])
                if credits is not None:
                    break

    input_tokens = _pick_int(usage, ("input_tokens", "inputTokens", "prompt_tokens"))
    output_tokens = _pick_int(usage, ("output_tokens", "outputTokens", "completion_tokens"))
    if input_tokens is None:
        input_tokens = _pick_int(decoded, ("input_tokens", "inputTokens"))
    if output_tokens is None:
        output_tokens = _pick_int(decoded, ("output_tokens", "outputTokens"))

    model = None
    if isinstance(decoded, dict) and decoded.get("model"):
        model = str(decoded.get("model"))

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "credits_remaining": credits,
        "model": model,
    }


def is_insufficient(status: Any, message: str, body: Any) -> bool:
    try:
        code = int(status)
    except (TypeError, ValueError):
        code = None
    if code == 402:
        return True
    parts = [message or ""]
    if isinstance(body, str):
        parts.append(body)
    elif isinstance(body, dict):
        try:
            parts.append(json.dumps(body, ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(body))
    return bool(INSUFFICIENT_RE.search(" ".join(parts)))


def meta_from_result(result: Any) -> dict[str, Any]:
    body = None
    headers = None
    try:
        raw = result.raw_http_response
        headers = raw.headers
        body = raw.content
    except Exception:
        pass
    meta = extract_from_payload(body, headers)
    usage = getattr(result, "usage", None)
    if usage is not None:
        if getattr(usage, "input_tokens", None) is not None:
            meta["input_tokens"] = int(usage.input_tokens)
        if getattr(usage, "output_tokens", None) is not None:
            meta["output_tokens"] = int(usage.output_tokens)
    model = getattr(result, "model", None)
    if model:
        meta["model"] = str(model)
    return meta


def meta_from_exc(exc: BaseException) -> dict[str, Any]:
    status = getattr(exc, "status", None)
    body = getattr(exc, "body", None)
    headers = getattr(exc, "headers", None)
    meta = extract_from_payload(body, headers)
    message = str(exc)
    insufficient = is_insufficient(status, message, body)
    if status is not None:
        meta["error_code"] = str(int(status)) if str(status).isdigit() or isinstance(status, int) else str(status)
    else:
        name = type(exc).__name__
        if "Timeout" in name:
            meta["error_code"] = "timeout"
        elif "Connection" in name:
            meta["error_code"] = "connection"
        else:
            meta["error_code"] = name
    if insufficient:
        meta["error_code"] = meta.get("error_code") or "402"
        meta["insufficient_credits"] = True
        meta["error_message"] = "TypeSafe 額度不足（HTTP 402）。請儲值後再繼續。"
        meta["error_detail"] = message[:2000]
    else:
        meta["insufficient_credits"] = False
        meta["error_message"] = message[:2000]
    return meta


def _window_kind(actual_rows: int, estimate_rows: int) -> str:
    if actual_rows <= 0 and estimate_rows <= 0:
        return "none"
    if actual_rows > 0 and estimate_rows > 0:
        return "mixed"
    if actual_rows > 0:
        return "actual"
    return "estimate"


def _stats_dict(
    *,
    calls: int,
    success_calls: int,
    error_calls: int,
    input_tokens: int,
    output_tokens: int,
    usd_actual: float,
    usd_estimated: float,
    usd_kind: str,
) -> dict[str, Any]:
    usd = float(usd_actual) + float(usd_estimated)
    return {
        "calls": calls,
        "success_calls": success_calls,
        "error_calls": error_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": input_tokens + output_tokens,
        "usd": usd,
        "usd_actual": float(usd_actual),
        "usd_estimated": float(usd_estimated),
        "usd_kind": usd_kind,
    }


def _empty_stats() -> dict[str, Any]:
    return _stats_dict(
        calls=0,
        success_calls=0,
        error_calls=0,
        input_tokens=0,
        output_tokens=0,
        usd_actual=0.0,
        usd_estimated=0.0,
        usd_kind="none",
    )


def _is_laya_row(row: dict[str, Any]) -> bool:
    """Row form of `_LAYA_SQL`. Empty backend is not Laya."""
    return str(row.get("backend") or "") == "laya" or str(row.get("cost_source") or "") == "laya"


def serialize_row(row: dict[str, Any], *, input_rate: float, output_rate: float) -> dict[str, Any]:
    input_tokens = row.get("input_tokens")
    output_tokens = row.get("output_tokens")
    input_i = int(input_tokens) if input_tokens is not None else None
    output_i = int(output_tokens) if output_tokens is not None else None
    local = _is_laya_row(row)
    cost_usd = None if local else _as_float(row.get("cost_usd"))
    estimated = None if local else estimate_usd(input_i, output_i, input_rate, output_rate)
    if local:
        spend = None
        kind = "none"
    elif cost_usd is not None:
        spend = cost_usd
        kind = "actual"
    elif estimated is not None:
        spend = estimated
        kind = "estimate"
    else:
        spend = None
        kind = "none"
    credits = _as_float(row.get("credits_remaining"))
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "task_id": row.get("task_id"),
        "batch_id": row.get("batch_id"),
        "model": row.get("model"),
        "backend": "laya" if local else str(row.get("backend") or "jev"),
        "input_tokens": input_i,
        "output_tokens": output_i,
        "tokens": (input_i or 0) + (output_i or 0) if input_i is not None or output_i is not None else None,
        "cost_usd": cost_usd,
        "estimated_cost_usd": estimated,
        "spend_usd": spend,
        "usd_kind": kind,
        "success": bool(row.get("success")),
        "error_code": row.get("error_code"),
        "error_message": row.get("error_message"),
        "credits_remaining": credits,
    }


async def record_call(
    db: Database,
    settings: SettingsStore,
    *,
    task_id: str | None,
    batch_id: str | None,
    model: str | None,
    success: bool,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = dict(meta or {})
    backend = str(payload.get("backend") or "jev").strip().lower()
    if backend != "laya":
        backend = "jev"
    input_tokens = _as_int(payload.get("input_tokens"))
    output_tokens = _as_int(payload.get("output_tokens"))
    cost_usd = _as_float(payload.get("cost_usd"))
    credits = _as_float(payload.get("credits_remaining"))
    rates = await settings.billing_rates()
    if backend == "laya":
        input_tokens = 0
        output_tokens = 0
        cost_usd = None
        estimated = None
        cost_source = "laya"
        credits = None
        insufficient = False
    else:
        estimated = estimate_usd(input_tokens, output_tokens, rates["input_usd_per_mtok"], rates["output_usd_per_mtok"])
        if cost_usd is not None:
            cost_source = "api"
        elif estimated is not None:
            cost_source = "estimate"
        else:
            cost_source = "none"
        insufficient = bool(payload.get("insufficient_credits")) or str(payload.get("error_code")) == "402"
    error_code = payload.get("error_code")
    error_message = payload.get("error_message")
    row_id = new_id()
    now = utc_now_iso()
    try:
        await db.execute(
            """
            INSERT INTO billing_usage (
                id, created_at, task_id, batch_id, model, backend,
                input_tokens, output_tokens, cost_usd, estimated_cost_usd, cost_source,
                success, error_code, error_message, credits_remaining
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                now,
                task_id,
                batch_id,
                (payload.get("model") or model or None),
                backend,
                input_tokens,
                output_tokens,
                cost_usd,
                estimated,
                cost_source,
                1 if success else 0,
                None if success else (str(error_code) if error_code else None),
                None if success else (str(error_message)[:2000] if error_message else None),
                credits,
            ),
        )
        if backend != "laya":
            if credits is not None:
                await settings.set_last_credits(credits, now)
            if insufficient and not success:
                await settings.set_insufficient_credits(True, now, str(error_message or "TypeSafe 額度不足（HTTP 402）")[:2000])
            elif success:
                await settings.set_insufficient_credits(False, None, None)
    except Exception:
        logger.exception("Failed to persist billing usage for batch %s", batch_id)
        return None
    return {
        "id": row_id,
        "created_at": now,
        "insufficient_credits": insufficient and not success,
        "credits_remaining": credits,
        "cost_source": cost_source,
    }


def _backend_scope(backend: str | None) -> str:
    """SQL predicate for one engine. Jev includes legacy rows that are not Laya."""
    if backend is None:
        return ""
    if backend == "laya":
        return f"({_LAYA_SQL})"
    if backend == "jev":
        return f"({_NOT_LAYA_SQL})"
    raise ValueError(backend)


def _where_sql(*parts: str) -> str:
    clauses = [f"({part})" for part in parts if part]
    if not clauses:
        return ""
    return "WHERE " + " AND ".join(clauses)


async def _aggregate(
    db: Database,
    rates: dict[str, float],
    since: str | None,
    backend: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    since_sql = ""
    if since:
        since_sql = "created_at >= ?"
        params.append(since)
    where = _where_sql(since_sql, _backend_scope(backend))
    row = await db.fetch_one(
        f"""
        SELECT
            COUNT(*) AS calls,
            COALESCE(SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END), 0) AS success_calls,
            COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS error_calls,
            COALESCE(SUM(COALESCE(input_tokens, 0)), 0) AS input_tokens,
            COALESCE(SUM(COALESCE(output_tokens, 0)), 0) AS output_tokens,
            COALESCE(SUM(CASE WHEN {_NOT_LAYA_SQL} THEN cost_usd ELSE NULL END), 0) AS cost_usd_sum,
            COALESCE(SUM(CASE WHEN {_NOT_LAYA_SQL} AND cost_usd IS NOT NULL THEN 1 ELSE 0 END), 0) AS actual_rows,
            COALESCE(SUM(CASE WHEN {_ESTIMATE_ROW_SQL} THEN 1 ELSE 0 END), 0) AS estimate_rows,
            COALESCE(SUM({_ESTIMATE_INPUT_SQL}), 0) AS estimate_input,
            COALESCE(SUM({_ESTIMATE_OUTPUT_SQL}), 0) AS estimate_output
        FROM billing_usage
        {where}
        """,
        tuple(params),
    )
    if row is None:
        return _empty_stats()
    actual_rows = int(row["actual_rows"] or 0)
    estimate_rows = int(row["estimate_rows"] or 0)
    usd_estimated = estimate_usd(
        int(row["estimate_input"] or 0),
        int(row["estimate_output"] or 0),
        rates["input_usd_per_mtok"],
        rates["output_usd_per_mtok"],
    ) or 0.0
    return _stats_dict(
        calls=int(row["calls"] or 0),
        success_calls=int(row["success_calls"] or 0),
        error_calls=int(row["error_calls"] or 0),
        input_tokens=int(row["input_tokens"] or 0),
        output_tokens=int(row["output_tokens"] or 0),
        usd_actual=float(row["cost_usd_sum"] or 0),
        usd_estimated=float(usd_estimated),
        usd_kind=_window_kind(actual_rows, estimate_rows),
    )


async def summary(db: Database, settings: SettingsStore, *, backend: str | None = None) -> dict[str, Any]:
    rates = await settings.billing_rates()
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = await _aggregate(db, rates, today_start, backend)
    seven = await _aggregate(db, rates, week_start, backend)
    all_time = await _aggregate(db, rates, None, backend)
    scope = _backend_scope(backend)

    last_credits_row = await db.fetch_one(
        f"""
        SELECT credits_remaining, created_at
        FROM billing_usage
        {_where_sql("credits_remaining IS NOT NULL", scope)}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    last_credits = _as_float((last_credits_row or {}).get("credits_remaining")) if last_credits_row else None
    last_credits_at = (last_credits_row or {}).get("created_at") if last_credits_row else None
    if last_credits is None and backend != "laya":
        stored = await settings.get_last_credits()
        last_credits = stored[0]
        last_credits_at = stored[1]

    last_402 = await db.fetch_one(
        f"""
        SELECT created_at, error_message, error_code
        FROM billing_usage
        {_where_sql("success = 0 AND (error_code = '402' OR error_message LIKE '%額度不足%')", scope)}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    last_ok = await db.fetch_one(
        f"""
        SELECT created_at FROM billing_usage
        {_where_sql("success = 1", scope)}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    flagged = await settings.get_insufficient_credits()
    open_402 = False
    last_insufficient_at = None
    last_insufficient_message = None
    if last_402:
        last_insufficient_at = last_402.get("created_at")
        last_insufficient_message = last_402.get("error_message")
        if last_ok is None or str(last_402.get("created_at") or "") >= str(last_ok.get("created_at") or ""):
            open_402 = True
    if backend != "laya" and flagged[0] and not last_ok:
        open_402 = True
        last_insufficient_at = last_insufficient_at or flagged[1]
        last_insufficient_message = last_insufficient_message or flagged[2]

    threshold = await settings.get_low_credits_threshold()
    low_balance = last_credits is not None and last_credits <= threshold

    return {
        "today": today,
        "seven_days": seven,
        "all_time": all_time,
        "last_credits_remaining": last_credits,
        "last_credits_at": last_credits_at,
        "insufficient_credits": open_402,
        "low_balance": low_balance and not open_402,
        "last_insufficient_at": last_insufficient_at,
        "last_insufficient_message": last_insufficient_message,
        "analysis_backend": await settings.get_analysis_backend(),
        "rates": {
            "input_usd_per_mtok": rates["input_usd_per_mtok"],
            "output_usd_per_mtok": rates["output_usd_per_mtok"],
            "note": RATES_NOTE,
        },
        "hud": {
            "today_usd": today["usd"],
            "today_usd_kind": today["usd_kind"],
            "today_tokens": today["tokens"],
            "all_time_usd": all_time["usd"],
            "all_time_usd_kind": all_time["usd_kind"],
            "last_credits_remaining": last_credits,
            "insufficient_credits": open_402,
            "low_balance": low_balance and not open_402,
        },
    }


async def list_usage(
    db: Database,
    settings: SettingsStore,
    *,
    limit: int = 50,
    offset: int = 0,
    task_id: str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(200, int(limit)))
    offset = max(0, int(offset))
    rates = await settings.billing_rates()
    params: list[Any] = []
    task_sql = ""
    if task_id:
        task_sql = "task_id = ?"
        params.append(task_id)
    where = _where_sql(task_sql, _backend_scope(backend))
    total_row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM billing_usage {where}", tuple(params))
    total = int((total_row or {}).get("n") or 0)
    rows = await db.fetch_all(
        f"""
        SELECT * FROM billing_usage
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [limit, offset]),
    )
    return {
        "items": [serialize_row(row, input_rate=rates["input_usd_per_mtok"], output_rate=rates["output_usd_per_mtok"]) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def usage_by_task(db: Database, settings: SettingsStore) -> dict[str, dict[str, Any]]:
    rates = await settings.billing_rates()
    rows = await db.fetch_all(
        f"""
        SELECT
            task_id,
            COUNT(*) AS calls,
            COALESCE(SUM(COALESCE(input_tokens, 0)), 0) AS input_tokens,
            COALESCE(SUM(COALESCE(output_tokens, 0)), 0) AS output_tokens,
            COALESCE(SUM(cost_usd), 0) AS cost_usd_sum,
            COALESCE(SUM(CASE WHEN cost_usd IS NOT NULL THEN 1 ELSE 0 END), 0) AS actual_rows,
            COALESCE(SUM(CASE WHEN {_ESTIMATE_ROW_SQL} THEN 1 ELSE 0 END), 0) AS estimate_rows,
            COALESCE(SUM({_ESTIMATE_INPUT_SQL}), 0) AS estimate_input,
            COALESCE(SUM({_ESTIMATE_OUTPUT_SQL}), 0) AS estimate_output
        FROM billing_usage
        WHERE task_id IS NOT NULL
        GROUP BY task_id
        """
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        actual_rows = int(row["actual_rows"] or 0)
        estimate_rows = int(row["estimate_rows"] or 0)
        usd_estimated = estimate_usd(
            int(row["estimate_input"] or 0),
            int(row["estimate_output"] or 0),
            rates["input_usd_per_mtok"],
            rates["output_usd_per_mtok"],
        ) or 0.0
        usd_actual = float(row["cost_usd_sum"] or 0)
        kind = _window_kind(actual_rows, estimate_rows)
        out[str(row["task_id"])] = {
            "calls": int(row["calls"] or 0),
            "input_tokens": int(row["input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "tokens": int(row["input_tokens"] or 0) + int(row["output_tokens"] or 0),
            "spend_usd": usd_actual + usd_estimated,
            "usd_kind": kind,
        }
    return out
