"""TypeSafe Jev client: one system_one call per batch with token-safe truncation."""

from __future__ import annotations

import json
import logging
from typing import Any

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy

from server.billing import meta_from_result
from server.settings_store import DEFAULT_MODEL

logger = logging.getLogger(__name__)

TOKEN_LIMIT = 64_000
# One short noul per message (about 100) plus an optional Choice. Over budget, shrink text only.
QUESTION_RESERVE = 10_000
CHARS_PER_TOKEN = 4
PER_MESSAGE_CHARS = 400

# 429 / 529 / 5xx plus connection timeouts. SDK default is only 2 retries.
JEV_RETRY = RetryPolicy(
    max_retries=5,
    backoff_initial=0.8,
    backoff_max=12.0,
    http_statuses={408, 409, 425, 429, *range(500, 600)},
)


def estimate_tokens(payload: Any) -> int:
    encoded = json.dumps(payload, ensure_ascii=False)
    return max(1, len(encoded) // CHARS_PER_TOKEN)


def _item_from_message(index: int, message: dict[str, Any], max_chars: int) -> dict[str, Any]:
    text = str(message.get("content") or "")
    if max_chars <= 0:
        text = ""
    elif len(text) > max_chars:
        text = text[:max_chars]
    return {
        "id": str(message.get("id") or ""),
        "i": index,
        "time": message.get("timestamp") or "",
        "chat": message.get("chat_name") or message.get("chat_id") or "",
        "sender": message.get("sender_name") or "",
        "text": text,
    }


def _state_with_cap(task_prompt: str, messages: list[dict[str, Any]], max_chars: int) -> dict[str, Any]:
    items = [_item_from_message(index, message, max_chars) for index, message in enumerate(messages, start=1)]
    return {
        "task_prompt": task_prompt,
        "batch_size": len(items),
        "messages": items,
    }


def build_state(task_prompt: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep all message skeletons (id/time/chat/sender). Shrink text only, never drop rows."""
    budget = TOKEN_LIMIT - QUESTION_RESERVE
    full = _state_with_cap(task_prompt, messages, PER_MESSAGE_CHARS)
    if estimate_tokens(full) <= budget:
        return full

    lo, hi = 0, PER_MESSAGE_CHARS
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        trial = _state_with_cap(task_prompt, messages, mid)
        if estimate_tokens(trial) <= budget:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    state = _state_with_cap(task_prompt, messages, best)
    logger.info(
        "Truncated Jev batch to %s chars/message (%s tokens est., %s messages)",
        best,
        estimate_tokens(state),
        len(messages),
    )
    return state


def noul_confidence(noul: float) -> float:
    return abs(2.0 * float(noul) - 1.0)


def message_question_key(index: int) -> str:
    return f"m{index}"


def build_questions(message_count: int, categories: list[dict[str, str]]) -> dict[str, Any]:
    """N noul questions plus at most one category Choice. Keys are not sent to the model."""
    questions: dict[str, Any] = {}
    for index in range(1, message_count + 1):
        questions[message_question_key(index)] = Noul(
            instructions=f"Is messages item i={index} relevant to task_prompt?",
            criteria={
                "true": "This message is relevant to task_prompt",
                "false": "This message is not relevant to task_prompt",
            },
        )
    choice = category_choice(categories)
    if choice is not None:
        questions["category"] = choice
    return questions


def category_choice(categories: list[dict[str, str]]) -> Choice | None:
    """One batch-level Choice. Laya copies these instructions and criteria."""
    if not categories:
        return None
    criteria: dict[str, str | None] = {}
    for item in categories:
        key = str(item.get("key") or item.get("label") or "").strip()
        if not key or key.casefold() == "other":
            continue
        label = str(item.get("label") or key).strip()
        description = str(item.get("description") or "").strip()
        if description and label and label != description:
            criteria[key] = f"{label}。{description}"
        else:
            criteria[key] = description or label or None
    if not criteria:
        return None
    criteria["other"] = "none of the listed types"
    return Choice(
        instructions="Which listed type best describes this batch as a whole? Use other if none apply.",
        criteria=criteria,
    )


def scored_message(index: int, message: dict[str, Any], noul: float) -> dict[str, Any]:
    """One judged row. Jev and Laya share this shape; only the noul source differs."""
    return {
        "id": str(message.get("id") or ""),
        "i": index,
        "noul": float(noul),
        "chat_id": message.get("chat_id"),
        "platform_message_id": message.get("platform_message_id"),
        "chat_name": message.get("chat_name"),
        "sender_name": message.get("sender_name"),
        "content": message.get("content"),
        "timestamp": message.get("timestamp"),
    }


def batch_score(nouls: list[float], threshold: float) -> dict[str, Any]:
    """Batch noul is the max among hits. A miss stores the highest message noul instead."""
    hits = [value for value in nouls if value >= threshold]
    if hits:
        noul = max(hits)
    elif nouls:
        noul = max(nouls)
    else:
        noul = None
    return {
        "hit": bool(hits),
        "hit_count": len(hits),
        "noul": noul,
        "confidence": noul_confidence(noul) if noul is not None else None,
    }


def _dump_answer(answer: Any) -> dict[str, Any]:
    if hasattr(answer, "model_dump"):
        return answer.model_dump()
    return {"repr": str(answer)}


async def judge_batch(
    *,
    api_key: str,
    model: str | None,
    task_prompt: str,
    messages: list[dict[str, Any]],
    categories: list[dict[str, str]],
) -> dict[str, Any]:
    state = build_state(task_prompt, messages)
    questions = build_questions(len(messages), categories)

    pin = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    async with AsyncTypeSafeClient(api_key=api_key, model=pin, timeout=120.0, retry=JEV_RETRY) as client:
        result = await client.system_one(state=state, questions=questions, model=pin, retry=JEV_RETRY)

    scored: list[dict[str, Any]] = []
    for index, message in enumerate(messages, start=1):
        key = message_question_key(index)
        answer = result.nouls.get(key)
        if answer is None:
            raise RuntimeError(f"Jev 未回傳 {key} noul")
        scored.append(scored_message(index, message, float(answer.noul)))
    category = None
    category_confidence = None
    choice_answer = result.choices.get("category")
    if choice_answer is not None:
        category = choice_answer.choice
        category_confidence = float(choice_answer.confidence)

    usage = result.usage
    usage_meta = meta_from_result(result)
    tokens = int((usage_meta.get("input_tokens") or usage.input_tokens or 0) + (usage_meta.get("output_tokens") or usage.output_tokens or 0))
    raw_usage = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
    }
    if usage_meta.get("cost_usd") is not None:
        raw_usage["cost_usd"] = usage_meta["cost_usd"]
    if usage_meta.get("credits_remaining") is not None:
        raw_usage["credits_remaining"] = usage_meta["credits_remaining"]
    raw = {
        "model": result.model,
        "usage": raw_usage,
        "answers": {name: _dump_answer(answer) for name, answer in result.answers.items()},
    }
    return {
        "messages": scored,
        "category": category,
        "category_confidence": category_confidence,
        "tokens": tokens,
        "usage_meta": usage_meta,
        "raw": raw,
    }
