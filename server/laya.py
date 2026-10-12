"""Laya through a local System One endpoint. The app does not import the Python `laya` package.

Ollama's official tag ``laya`` (https://ollama.com/library/laya) and Unsloth Desktop's
Decision API (https://unsloth.ai/docs/models/decision-laya) both accept
``POST /v1/systemone`` with model ``laya``. Unsloth documents the same body:
``model``, ``state`` (a string or any JSON), and ``questions``. This module sends
that body to whichever host the setting names. It never downloads weights.
Hit images are not part of ``state``.

Ollama: http://127.0.0.1:11434
Unsloth Desktop: http://127.0.0.1:8888
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from server.jev import category_choice, scored_message

# https://ollama.com/library/laya — official tag, not a user-typed name.
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
# https://unsloth.ai/docs/models/decision-laya — Decision API, model name `laya`.
UNSLOTH_BASE_URL = "http://127.0.0.1:8888"
OLLAMA_LAYA_MODEL = "laya"
OLLAMA_TIMEOUT_SECONDS = 120
OLLAMA_DOWN = "無法連上 Ollama。請先啟動 Ollama（http://127.0.0.1:11434）。"
OLLAMA_MISSING = "Ollama 還沒有 laya。請先執行 ollama pull laya，並確認 Ollama 已啟動。"
UNSLOTH_DOWN = "無法連上 Unsloth Desktop。請先啟動 Unsloth Desktop（http://127.0.0.1:8888）。"
UNSLOTH_MISSING = "Unsloth Desktop 還沒有 Laya。請先啟動 Unsloth Desktop，並確認 Laya 可用。"

_CATEGORY_CHARS = 4_000


class LayaError(RuntimeError):
    """One Laya batch failed. The worker records the error and does not retry it."""


def noul_from_laya_answer(answer: Mapping[str, Any]) -> float:
    # Laya noul is already P(true) in [0, 1] (system_one softmax on the true option) and is used as-is.
    # A score is an expected ordinal index, divided by (legend levels - 1) so the top step is 1.
    # A yes/no choice uses P(true) when present, otherwise 1 or 0 for true/yes versus false/no.
    kind = str(answer.get("type") or "noul")
    if kind == "score":
        score = _finite(answer.get("score"), label="score")
        legend = answer.get("legend")
        levels = len(legend) if isinstance(legend, dict) else 0
        if levels >= 2:
            return _clamp01(score / (levels - 1))
        return _clamp01(score)
    if kind == "choice":
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict) and "true" in probabilities:
            return _clamp01(_finite(probabilities.get("true"), label="noul"))
        choice = str(answer.get("choice") or "").strip().casefold()
        if choice in {"true", "yes"}:
            return 1.0
        if choice in {"false", "no"}:
            return 0.0
        raise LayaError("Laya choice 無法對應 noul")
    return _clamp01(_finite(answer.get("noul"), label="noul"))


def laya_billing_meta(*, error: str | None = None) -> dict[str, Any]:
    """Ledger marker for a local run: zero tokens and no TypeSafe USD."""
    meta: dict[str, Any] = {
        "backend": "laya",
        "model": OLLAMA_LAYA_MODEL,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": None,
    }
    if error:
        meta["error_code"] = "laya"
        meta["error_message"] = error
    return meta


def message_state(message: Mapping[str, Any]) -> dict[str, str]:
    """Text fields only. Hit images are fetched later and are not model input."""
    return {
        "text": str(message.get("content") or ""),
        "chat": str(message.get("chat_name") or message.get("chat_id") or ""),
        "sender": str(message.get("sender_name") or ""),
        "time": str(message.get("timestamp") or ""),
    }


def category_question(categories: list[dict[str, str]]) -> dict[str, Any] | None:
    """Same criteria as the Jev Choice, as a plain dict for systemone."""
    choice = category_choice(categories)
    if choice is None:
        return None
    return {
        "type": "choice",
        "instructions": choice.instructions,
        "criteria": {str(key): value for key, value in choice.criteria.items()},
    }


@dataclass(frozen=True)
class _Host:
    base_url: str
    down: str
    missing_model: str
    missing_endpoint: str
    bad_json: str
    bad_answers: str
    name: str


_OLLAMA_HOST = _Host(
    base_url=OLLAMA_BASE_URL,
    down=OLLAMA_DOWN,
    missing_model=OLLAMA_MISSING,
    missing_endpoint="這版 Ollama 沒有 /v1/systemone。請升級到 0.40.0 或更新後再試。",
    bad_json="Ollama 沒有回傳 Laya 的 JSON。",
    bad_answers="Ollama 沒有回傳 Laya 的 answers。",
    name="Ollama",
)
_UNSLOTH_HOST = _Host(
    base_url=UNSLOTH_BASE_URL,
    down=UNSLOTH_DOWN,
    missing_model=UNSLOTH_MISSING,
    missing_endpoint="Unsloth Desktop 沒有 /v1/systemone。請先啟動 Unsloth Desktop，並確認 Laya 可用。",
    bad_json="Unsloth Desktop 沒有回傳 Laya 的 JSON。",
    bad_answers="Unsloth Desktop 沒有回傳 Laya 的 answers。",
    name="Unsloth Desktop",
)


def laya_host(runtime: str | None) -> _Host:
    if str(runtime or "").strip().lower() == "unsloth":
        return _UNSLOTH_HOST
    return _OLLAMA_HOST


def _post_systemone(payload: dict[str, Any], runtime: str = "ollama") -> dict[str, Any]:
    """One `/v1/systemone` call. Connection failures stay a short Chinese error."""
    host = laya_host(runtime)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{host.base_url}/v1/systemone",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LayaError(_http_failure(exc.code, detail, host)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LayaError(host.down) from exc
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LayaError(host.bad_json) from exc
    if not isinstance(parsed, dict):
        raise LayaError(host.bad_answers)
    return parsed


def _http_failure(status: int, body: str, host: _Host) -> str:
    detail = _error_text(body)
    lowered = detail.casefold()
    if status == 404 and "model" in lowered and "not found" in lowered:
        return host.missing_model
    if status == 404:
        return host.missing_endpoint
    if detail:
        return f"{host.name} 拒絕這次 Laya 請求（HTTP {status}）：{detail}"
    return f"{host.name} 拒絕這次 Laya 請求（HTTP {status}）。"


def _error_text(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return " ".join(error.split())[:240]
    return " ".join(body.split())[:240]


def _answer_from(result: Mapping[str, Any], key: str, host: _Host) -> dict[str, Any]:
    answers = result.get("answers")
    answer = answers.get(key) if isinstance(answers, dict) else None
    if not isinstance(answer, dict):
        raise LayaError(host.bad_answers)
    return answer


def _score_laya(
    task_prompt: str,
    messages: list[dict[str, Any]],
    categories: list[dict[str, str]],
    runtime: str,
) -> dict[str, Any]:
    host = laya_host(runtime)
    prompt = task_prompt.strip()
    scored: list[dict[str, Any]] = []
    raw_answers: dict[str, Any] = {}
    for index, message in enumerate(messages, start=1):
        result = _post_systemone(
            {
                "model": OLLAMA_LAYA_MODEL,
                "state": message_state(message),
                "questions": {"hit": {"type": "noul", "instructions": prompt}},
            },
            runtime,
        )
        answer = _answer_from(result, "hit", host)
        scored.append(scored_message(index, message, noul_from_laya_answer(answer)))
        raw_answers[f"m{index}"] = answer

    category = None
    category_confidence = None
    question = category_question(categories)
    if question is not None:
        result = _post_systemone(
            {
                "model": OLLAMA_LAYA_MODEL,
                "state": _category_state(messages),
                "questions": {"category": question},
            },
            runtime,
        )
        choice = _answer_from(result, "category", host)
        if not choice.get("choice"):
            raise LayaError("Laya 未回傳類型 choice")
        category = str(choice.get("choice"))
        if choice.get("confidence") is not None:
            category_confidence = float(choice["confidence"])
        raw_answers["category"] = choice

    return {
        "messages": scored,
        "category": category,
        "category_confidence": category_confidence,
        "tokens": 0,
        "usage_meta": laya_billing_meta(),
        "raw": {"backend": "laya", "model": OLLAMA_LAYA_MODEL, "answers": raw_answers},
    }


async def judge_laya_batch(
    *,
    task_prompt: str,
    messages: list[dict[str, Any]],
    categories: list[dict[str, str]],
    runtime: str = "ollama",
) -> dict[str, Any]:
    """Score one batch on the selected local runtime. Callers limit how many are in flight."""
    host = laya_host(runtime)
    chosen = "unsloth" if host is _UNSLOTH_HOST else "ollama"
    return await asyncio.to_thread(_score_laya, task_prompt, messages, categories, chosen)


def _category_state(messages: list[dict[str, Any]]) -> dict[str, str]:
    parts: list[str] = []
    used = 0
    for index, message in enumerate(messages, start=1):
        piece = f"[{index}] {str(message.get('content') or '').strip()}"
        room = _CATEGORY_CHARS - used
        if room <= 0:
            break
        if len(piece) > room:
            piece = piece[:room]
        parts.append(piece)
        used += len(piece)
    return {"messages": "\n".join(parts)}


def _finite(value: Any, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LayaError(f"Laya 未回傳 {label}") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise LayaError(f"Laya 回傳了無效的 {label}")
    return number


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return float(value)
