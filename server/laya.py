"""Local Laya multilingual checkpoint. Lazy-loaded; never the English model.

laya 0.3.6 (PyPI). Official call::

    agent = laya.load("convaiinnovations/laya-multilingual")
    result = agent.predict(state, questions)  # alias of Agent.system_one

`predict` returns ``{"answers": {...}, "usage": {...}}``. A noul answer is
``answers[id]["noul"]`` = P(true) in [0, 1]. A choice answer is
``answers[id]["choice"]`` plus ``confidence``. Weights download inside
``laya.load`` on first use (Hugging Face ``convaiinnovations/laya-multilingual``).

The English checkpoint ``convaiinnovations/laya`` is not loaded. The Hub language
list for this checkpoint includes ``zh``; published benchmarks report ``zh-CN``
and ``zh-TW``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from server.jev import category_choice, scored_message

# Standalone multilingual repo. Do not pass subfolder="multilingual" on the English bundle.
LAYA_CHECKPOINT = "convaiinnovations/laya-multilingual"
_CATEGORY_CHARS = 4_000

_agent: Any = None
_infer_lock = asyncio.Lock()


class LayaError(RuntimeError):
    """One Laya batch failed. The worker records the error and does not retry it."""


def reset_agent() -> None:
    """Drop the cached agent. Tests use this so a mock cannot leak into another case."""
    global _agent
    _agent = None


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
        "model": LAYA_CHECKPOINT,
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
    """Same criteria as the Jev Choice, as a plain dict for `agent.predict`."""
    choice = category_choice(categories)
    if choice is None:
        return None
    return {
        "type": "choice",
        "instructions": choice.instructions,
        "criteria": {str(key): value for key, value in choice.criteria.items()},
    }


def _load_agent() -> Any:
    global _agent
    if _agent is not None:
        return _agent
    try:
        import laya
    except ImportError as exc:
        raise LayaError(
            "Laya 套件未安裝。請執行 uv sync --extra laya（laya==0.3.6）。"
            "權重未下載也不會擋住伺服器啟動。"
        ) from exc
    try:
        agent = laya.load(LAYA_CHECKPOINT)
    except Exception as exc:
        raise LayaError(f"無法載入 Laya 多語權重 {LAYA_CHECKPOINT}：{exc}") from exc
    _agent = agent
    return _agent


def _score_sync(
    agent: Any,
    task_prompt: str,
    messages: list[dict[str, Any]],
    categories: list[dict[str, str]],
) -> dict[str, Any]:
    prompt = task_prompt.strip()
    scored: list[dict[str, Any]] = []
    raw_answers: dict[str, Any] = {}
    for index, message in enumerate(messages, start=1):
        state = message_state(message)
        result = agent.predict(
            state,
            {"hit": {"type": "noul", "instructions": prompt}},
        )
        answers = result.get("answers") if isinstance(result, dict) else None
        answer = answers.get("hit") if isinstance(answers, dict) else None
        if not isinstance(answer, dict):
            raise LayaError(f"Laya 未回傳訊息 {index} 的 noul")
        scored.append(scored_message(index, message, noul_from_laya_answer(answer)))
        raw_answers[f"m{index}"] = answer

    category = None
    category_confidence = None
    question = category_question(categories)
    if question is not None:
        result = agent.predict(_category_state(messages), {"category": question})
        answers = result.get("answers") if isinstance(result, dict) else None
        choice = answers.get("category") if isinstance(answers, dict) else None
        if not isinstance(choice, dict) or not choice.get("choice"):
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
        "raw": {"backend": "laya", "model": LAYA_CHECKPOINT, "answers": raw_answers},
    }


async def judge_laya_batch(
    *,
    task_prompt: str,
    messages: list[dict[str, Any]],
    categories: list[dict[str, str]],
) -> dict[str, Any]:
    """Score one batch on the single cached multilingual agent."""
    async with _infer_lock:
        agent = await asyncio.to_thread(_load_agent)
        return await asyncio.to_thread(_score_sync, agent, task_prompt, messages, categories)


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
