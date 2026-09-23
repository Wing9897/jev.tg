"""Persisted app settings (API key stays server-side)."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

from server.crypto import decrypt_secret, encrypt_secret, load_fernet
from server.db import Database
from server.paths import data_dir
from server.util import utc_now_iso

DEFAULT_MODEL = "jev-1.13.0"
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 16
DEFAULT_CONCURRENCY = 4
# Hosted jevtypesafeai was ~$0.42 / million input tokens. TypeSafe OpenAPI Usage
# marks input as billable and output as currently free; the official response has
# no cost_usd, so this is only a labeled 估計 fallback.
DEFAULT_INPUT_USD_PER_MTOK = 0.42
DEFAULT_OUTPUT_USD_PER_MTOK = 0.0
DEFAULT_LOW_CREDITS_THRESHOLD = 0.0
# 0 means every stored message is eligible. Positive values are a claim window only.
DEFAULT_ANALYSIS_MAX_AGE_DAYS = 0
MAX_ANALYSIS_MAX_AGE_DAYS = 3650
KEY_API = "typesafe_api_key"
KEY_MODEL = "model"
KEY_CONCURRENCY = "concurrency"
KEY_JEV_CALLS = "jev_calls"
KEY_JEV_HITS = "jev_hits"
KEY_JEV_MISSES = "jev_misses"
KEY_JEV_TOKENS = "jev_tokens"
KEY_INPUT_USD_PER_MTOK = "billing_input_usd_per_mtok"
KEY_OUTPUT_USD_PER_MTOK = "billing_output_usd_per_mtok"
KEY_LOW_CREDITS_THRESHOLD = "billing_low_credits_threshold"
KEY_LAST_CREDITS = "billing_last_credits_remaining"
KEY_LAST_CREDITS_AT = "billing_last_credits_at"
KEY_INSUFFICIENT = "billing_insufficient_credits"
KEY_INSUFFICIENT_AT = "billing_insufficient_at"
KEY_INSUFFICIENT_MSG = "billing_insufficient_message"
KEY_ANALYSIS_MAX_AGE_DAYS = "analysis_max_age_days"
KEY_ANALYSIS_PAUSED = "analysis_paused"
KEY_ANALYSIS_BACKEND = "analysis_backend"
DEFAULT_ANALYSIS_BACKEND = "jev"
ANALYSIS_BACKENDS = ("jev", "laya")


def parse_analysis_backend(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ANALYSIS_BACKENDS:
        return text
    return DEFAULT_ANALYSIS_BACKEND


def clamp_concurrency(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONCURRENCY
    return max(MIN_CONCURRENCY, min(MAX_CONCURRENCY, n))


def live_worker_count(_backend: Any, concurrency: int) -> int:
    """In-flight batch slots for either backend. Same stored 1–16 cap.

    Jev: that many TypeSafe calls at once. Laya: that many batch jobs may be
    queued or running. Laya still loads one model; inference stays on one lock.
    """
    return clamp_concurrency(concurrency)


def parse_analysis_max_age_days(value: Any) -> int:
    """0 or blank = no age limit. Positive integers are capped."""
    if value is None:
        return DEFAULT_ANALYSIS_MAX_AGE_DAYS
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return DEFAULT_ANALYSIS_MAX_AGE_DAYS
        value = raw
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ANALYSIS_MAX_AGE_DAYS
    if days <= 0:
        return DEFAULT_ANALYSIS_MAX_AGE_DAYS
    return min(days, MAX_ANALYSIS_MAX_AGE_DAYS)


class SettingsStore:
    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root
        self._fernet = load_fernet(root)

    async def get_raw(self, key: str, default: str = "") -> str:
        value = await self.db.fetch_value("SELECT value FROM settings WHERE key = ?", (key,))
        if value is None:
            return default
        return str(value)

    async def set_raw(self, key: str, value: str) -> None:
        await self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    async def get_model(self) -> str:
        model = (await self.get_raw(KEY_MODEL, DEFAULT_MODEL)).strip()
        return model or DEFAULT_MODEL

    async def get_concurrency(self) -> int:
        return clamp_concurrency(await self.get_raw(KEY_CONCURRENCY, str(DEFAULT_CONCURRENCY)))

    async def get_api_key(self) -> str | None:
        stored = await self.get_raw(KEY_API, "")
        if stored:
            plain = decrypt_secret(self._fernet, stored)
            if plain:
                return plain
        env = os.environ.get("TYPESAFE_API_KEY", "").strip()
        return env or None

    async def api_key_set(self) -> bool:
        return bool(await self.get_api_key())

    async def set_api_key(self, key: str | None) -> None:
        if key is None:
            return
        cleaned = key.strip()
        if not cleaned:
            await self.db.execute("DELETE FROM settings WHERE key = ?", (KEY_API,))
            return
        await self.set_raw(KEY_API, encrypt_secret(self._fernet, cleaned))

    async def _get_float(self, key: str, default: float) -> float:
        raw = (await self.get_raw(key, "")).strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        if not math.isfinite(value) or value < 0:
            return default
        return value

    async def billing_rates(self) -> dict[str, float]:
        return {
            "input_usd_per_mtok": await self._get_float(KEY_INPUT_USD_PER_MTOK, DEFAULT_INPUT_USD_PER_MTOK),
            "output_usd_per_mtok": await self._get_float(KEY_OUTPUT_USD_PER_MTOK, DEFAULT_OUTPUT_USD_PER_MTOK),
        }

    async def set_billing_rates(self, *, input_usd_per_mtok: float | None = None, output_usd_per_mtok: float | None = None) -> None:
        if input_usd_per_mtok is not None:
            await self.set_raw(KEY_INPUT_USD_PER_MTOK, str(float(input_usd_per_mtok)))
        if output_usd_per_mtok is not None:
            await self.set_raw(KEY_OUTPUT_USD_PER_MTOK, str(float(output_usd_per_mtok)))

    async def get_low_credits_threshold(self) -> float:
        return await self._get_float(KEY_LOW_CREDITS_THRESHOLD, DEFAULT_LOW_CREDITS_THRESHOLD)

    async def set_low_credits_threshold(self, value: float) -> None:
        await self.set_raw(KEY_LOW_CREDITS_THRESHOLD, str(float(value)))

    async def get_analysis_max_age_days(self) -> int:
        return parse_analysis_max_age_days(await self.get_raw(KEY_ANALYSIS_MAX_AGE_DAYS, "0"))

    async def set_analysis_max_age_days(self, value: int) -> None:
        await self.set_raw(KEY_ANALYSIS_MAX_AGE_DAYS, str(parse_analysis_max_age_days(value)))

    async def get_analysis_backend(self) -> str:
        return parse_analysis_backend(await self.get_raw(KEY_ANALYSIS_BACKEND, DEFAULT_ANALYSIS_BACKEND))

    async def set_analysis_backend(self, value: str) -> None:
        await self.set_raw(KEY_ANALYSIS_BACKEND, parse_analysis_backend(value))

    async def analysis_paused(self) -> bool:
        return (await self.get_raw(KEY_ANALYSIS_PAUSED, "0")).strip() == "1"

    async def set_analysis_paused(self, paused: bool) -> None:
        await self.set_raw(KEY_ANALYSIS_PAUSED, "1" if paused else "0")

    async def get_last_credits(self) -> tuple[float | None, str | None]:
        raw = (await self.get_raw(KEY_LAST_CREDITS, "")).strip()
        if not raw:
            return None, None
        try:
            value = float(raw)
        except ValueError:
            return None, None
        if not math.isfinite(value):
            return None, None
        at = (await self.get_raw(KEY_LAST_CREDITS_AT, "")).strip() or None
        return value, at

    async def set_last_credits(self, value: float, at: str) -> None:
        await self.set_raw(KEY_LAST_CREDITS, str(float(value)))
        await self.set_raw(KEY_LAST_CREDITS_AT, at)

    async def get_insufficient_credits(self) -> tuple[bool, str | None, str | None]:
        flagged = (await self.get_raw(KEY_INSUFFICIENT, "0")).strip() == "1"
        at = (await self.get_raw(KEY_INSUFFICIENT_AT, "")).strip() or None
        message = (await self.get_raw(KEY_INSUFFICIENT_MSG, "")).strip() or None
        return flagged, at, message

    async def set_insufficient_credits(self, flagged: bool, at: str | None, message: str | None) -> None:
        await self.set_raw(KEY_INSUFFICIENT, "1" if flagged else "0")
        if flagged:
            await self.set_raw(KEY_INSUFFICIENT_AT, at or "")
            await self.set_raw(KEY_INSUFFICIENT_MSG, message or "")
        else:
            await self.db.execute("DELETE FROM settings WHERE key IN (?, ?)", (KEY_INSUFFICIENT_AT, KEY_INSUFFICIENT_MSG))

    async def bump_usage(self, *, calls: int = 0, hits: int = 0, misses: int = 0, tokens: int = 0) -> None:
        for key, delta in (
            (KEY_JEV_CALLS, calls),
            (KEY_JEV_HITS, hits),
            (KEY_JEV_MISSES, misses),
            (KEY_JEV_TOKENS, tokens),
        ):
            if not delta:
                continue
            current = await self.get_raw(key, "0")
            try:
                total = int(current) + int(delta)
            except ValueError:
                total = int(delta)
            await self.set_raw(key, str(total))

    async def snapshot(self) -> dict[str, Any]:
        def as_int(raw: str) -> int:
            try:
                return int(raw)
            except ValueError:
                return 0

        rates = await self.billing_rates()
        last_credits, last_credits_at = await self.get_last_credits()
        return {
            "typesafe_api_key_set": await self.api_key_set(),
            "model": await self.get_model(),
            "concurrency": await self.get_concurrency(),
            "data_dir": str(data_dir()),
            "jev_calls": as_int(await self.get_raw(KEY_JEV_CALLS, "0")),
            "jev_hits": as_int(await self.get_raw(KEY_JEV_HITS, "0")),
            "jev_misses": as_int(await self.get_raw(KEY_JEV_MISSES, "0")),
            "jev_tokens": as_int(await self.get_raw(KEY_JEV_TOKENS, "0")),
            "input_usd_per_mtok": rates["input_usd_per_mtok"],
            "output_usd_per_mtok": rates["output_usd_per_mtok"],
            "low_credits_threshold": await self.get_low_credits_threshold(),
            "analysis_max_age_days": await self.get_analysis_max_age_days(),
            "analysis_backend": await self.get_analysis_backend(),
            "analysis_paused": await self.analysis_paused(),
            "last_credits_remaining": last_credits,
            "last_credits_at": last_credits_at,
            "updated_at": utc_now_iso(),
        }
