"""Telethon StringSession persistence."""

from __future__ import annotations

from pathlib import Path

from telethon.sessions import StringSession


def session_path(session_dir: Path, source_id: str) -> Path:
    return Path(session_dir) / f"{source_id}.session.txt"


def persist_string_session_token(session_dir: Path, source_id: str, token: str) -> Path:
    cleaned = (token or "").strip()
    if not cleaned:
        raise ValueError(f"Refusing to persist empty Telegram session for {source_id}")
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    path = session_path(session_dir, source_id)
    path.write_text(cleaned, encoding="utf-8")
    return path


def load_string_session(session_dir: Path, source_id: str) -> StringSession:
    Path(session_dir).mkdir(parents=True, exist_ok=True)
    token_file = session_path(session_dir, source_id)
    if token_file.exists():
        token = token_file.read_text(encoding="utf-8").strip()
        if token:
            return StringSession(token)
    return StringSession()
