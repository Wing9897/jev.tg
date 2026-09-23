"""Telegram login, channel picker, live ingest, and bounded backfill."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any, NoReturn

from telethon import TelegramClient, errors, events
from telethon.tl.custom.qrlogin import QRLogin
from telethon.tl.types import Channel as TgChannel
from telethon.tl.types import Chat

from server.db import Database
from server.hit_images import MAX_IMAGES, encode_jpeg, message_is_photo
from server.paths import DEFAULT_SOURCE_ID
from server.sse import SseBroadcaster
from server.telegram_session import load_string_session, persist_string_session_token, session_path
from server.util import new_id, to_iso_z, utc_now_iso

logger = logging.getLogger(__name__)

QR_WAIT_DEFAULT_SECONDS = 25.0
QR_WAIT_MIN_SECONDS = 5.0
QR_WAIT_MAX_SECONDS = 55.0
BACKFILL_LIMIT_PER_DIALOG = 100
BACKFILL_DIALOG_SLEEP_SECONDS = 0.5
FLOOD_WAIT_ABORT_SECONDS = 120


def login_error_text(exc: BaseException) -> str:
    """Map Telethon login failures to Traditional Chinese for the UI."""
    if isinstance(exc, errors.ApiIdInvalidError):
        return "api_id 或 api_hash 無效，請到 my.telegram.org 核對。"
    if isinstance(exc, errors.ApiIdPublishedFloodError):
        return "這個 api_id 已被公開，Telegram 暫時拒絕使用。"
    if isinstance(exc, errors.PhoneNumberInvalidError):
        return "手機號碼格式不正確，請含國碼（例如 +8869...）。"
    if isinstance(exc, errors.PhoneCodeInvalidError):
        return "驗證碼不正確，請再試一次。"
    if isinstance(exc, errors.PhoneCodeExpiredError):
        return "驗證碼已過期，請重新寄送。"
    if isinstance(exc, errors.PhoneHashExpiredError):
        return "驗證流程已過期，請重新寄送驗證碼。"
    if isinstance(exc, errors.PasswordHashInvalidError):
        return "兩步驟驗證密碼不正確。"
    if isinstance(exc, errors.FloodWaitError):
        seconds = int(getattr(exc, "seconds", 0) or 0)
        return f"Telegram 要求稍候 {seconds} 秒後再試。"
    if isinstance(exc, errors.SessionPasswordNeededError):
        return "需要兩步驟驗證密碼。"
    if isinstance(
        exc,
        (
            errors.AuthTokenExpiredError,
            errors.AuthTokenInvalidError,
            errors.AuthTokenInvalid2Error,
            errors.AuthTokenInvalidxError,
        ),
    ):
        return "QR 登入已過期，請重新產生。"
    message = str(exc).strip()
    if isinstance(exc, RuntimeError) and message:
        return message
    if message and any("\u4e00" <= char <= "\u9fff" for char in message):
        return message
    return "Telegram 登入失敗，請再試一次。"


def _sender_fields(sender: Any) -> tuple[str | None, str | None]:
    if sender is None:
        return None, None
    sender_id = str(getattr(sender, "id", "")) if getattr(sender, "id", None) else None
    sender_name = (
        getattr(sender, "username", None)
        or getattr(sender, "first_name", None)
        or getattr(sender, "title", None)
        or None
    )
    return sender_id, sender_name


class TelegramService:
    def __init__(self, db: Database, sse: SseBroadcaster, session_dir: Path, source_id: str = DEFAULT_SOURCE_ID) -> None:
        self.db = db
        self.sse = sse
        self.session_dir = Path(session_dir)
        self.source_id = source_id
        self._client: TelegramClient | None = None
        self._api_id: int | None = None
        self._api_hash: str | None = None
        self._phone: str | None = None
        self._qr_login: QRLogin | None = None
        self._qr_wait_lock = asyncio.Lock()
        self._startup_task: asyncio.Task[None] | None = None
        self._message_handler: Any = None
        self._message_event_builder: events.NewMessage | None = None
        self._history_backfill_done = False
        self._status = "disconnected"
        self._last_error: str | None = None
        self._user_wants_connected = False
        self._watchdog: asyncio.Task[None] | None = None
        self._reconnect_lock = asyncio.Lock()
        self._ingest_hook: Callable[[], None] | None = None

    async def ensure_row(self) -> dict[str, Any]:
        row = await self.db.fetch_one("SELECT * FROM telegram_sources WHERE id = ?", (self.source_id,))
        if row:
            return row
        now = utc_now_iso()
        await self.db.execute(
            "INSERT INTO telegram_sources (id, name, status, created_at, updated_at) VALUES (?, ?, 'disconnected', ?, ?)",
            (self.source_id, "Telegram", now, now),
        )
        row = await self.db.fetch_one("SELECT * FROM telegram_sources WHERE id = ?", (self.source_id,))
        assert row is not None
        return row

    async def snapshot(self) -> dict[str, Any]:
        row = await self.ensure_row()
        connected = await self.is_connected()
        status = self._status if connected or self._status not in {"connected"} else row.get("status")
        if connected:
            status = "connected"
        return {
            "id": self.source_id,
            "name": row.get("name") or "Telegram",
            "status": status,
            "phone": row.get("phone") or self._phone,
            "api_id": row.get("api_id"),
            "has_api_hash": bool(row.get("api_hash")),
            "last_error": self._last_error or row.get("last_error"),
            "last_connected_at": row.get("last_connected_at"),
            "session_file": str(session_path(self.session_dir, self.source_id)),
        }

    async def is_connected(self) -> bool:
        if self._client is None or not bool(self._client.is_connected()):
            return False
        try:
            return bool(await asyncio.wait_for(self._client.is_user_authorized(), timeout=8))
        except Exception:
            return False

    def set_ingest_hook(self, hook: Callable[[], None] | None) -> None:
        self._ingest_hook = hook

    def _create_client(self) -> TelegramClient:
        assert self._api_id is not None and self._api_hash
        session = load_string_session(self.session_dir, self.source_id)
        return TelegramClient(
            session,
            self._api_id,
            self._api_hash,
            connection_retries=8,
            retry_delay=2,
            auto_reconnect=True,
            request_retries=5,
        )

    async def _update_source(self, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = tuple(fields.values()) + (self.source_id,)
        await self.db.execute(f"UPDATE telegram_sources SET {assignments} WHERE id = ?", values)

    async def _set_status(self, status: str, *, last_error: str | None = None) -> None:
        self._status = status
        self._last_error = last_error
        payload = {"status": status, "last_error": last_error}
        if status == "connected":
            payload["last_connected_at"] = utc_now_iso()
        await self._update_source(**payload)
        self.sse.publish("telegram_status", {"status": status, "last_error": last_error})

    async def restore(self) -> None:
        row = await self.ensure_row()
        api_id = row.get("api_id")
        api_hash = row.get("api_hash")
        token_file = session_path(self.session_dir, self.source_id)
        if not api_id or not api_hash or not token_file.is_file():
            return
        self._api_id = int(api_id)
        self._api_hash = str(api_hash)
        self._phone = row.get("phone")
        try:
            await self.connect_existing()
        except Exception as exc:
            logger.warning("Telegram restore failed: %s", exc)
            await self._set_status("disconnected", last_error=str(exc))

    async def connect_existing(self) -> None:
        await self.disconnect()
        await self._set_status("connecting")
        self._client = self._create_client()
        await self._client.connect()
        if not await self._client.is_user_authorized():
            await self.disconnect()
            raise RuntimeError("Telegram session is not authorized; complete login first")
        await self._on_login_success()

    async def _drop_client(self) -> None:
        """Stop background tasks and drop the Telethon client without publishing a status."""
        self._user_wants_connected = False
        if self._watchdog is not None:
            self._watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await self._watchdog
            self._watchdog = None
        if self._startup_task is not None:
            self._startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._startup_task
            self._startup_task = None
        self._qr_login = None
        if self._client is not None:
            self._clear_message_handlers()
            result = self._client.disconnect()
            if result is not None:
                await result
            self._client = None

    async def disconnect(self) -> None:
        await self._drop_client()
        if self._status != "disconnected":
            await self._set_status("disconnected")

    async def _resolve_credentials(self, api_id: int, api_hash: str) -> tuple[int, str]:
        try:
            parsed_id = int(api_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("api_id 必須是正整數") from exc
        if parsed_id <= 0:
            raise RuntimeError("api_id 必須是正整數")
        cleaned = (api_hash or "").strip()
        row = await self.ensure_row()
        if not cleaned:
            stored_hash = str(row.get("api_hash") or "").strip()
            stored_id = row.get("api_id")
            if stored_hash and stored_id is not None and int(stored_id) == parsed_id:
                cleaned = stored_hash
        if not cleaned:
            raise RuntimeError("請填寫 api_id 與 api_hash")
        return parsed_id, cleaned

    async def _abort_login(self, exc: Exception) -> NoReturn:
        detail = login_error_text(exc)
        logger.warning("Telegram login failed: %s", exc)
        await self._drop_client()
        await self._set_status("error", last_error=detail)
        if isinstance(exc, RuntimeError) and str(exc) == detail:
            raise exc
        raise RuntimeError(detail) from exc

    async def start_login(self, api_id: int, api_hash: str, phone: str) -> dict[str, Any]:
        parsed_id, cleaned_hash = await self._resolve_credentials(api_id, api_hash)
        normalized_phone = (phone or "").strip()
        if not normalized_phone:
            raise RuntimeError("請填寫手機號碼（含國碼）")
        self._api_id = parsed_id
        self._api_hash = cleaned_hash
        self._phone = normalized_phone
        await self._update_source(api_id=self._api_id, api_hash=self._api_hash, phone=self._phone)
        await self._drop_client()
        await self._set_status("connecting")
        try:
            self._client = self._create_client()
            await self._client.connect()
            if await self._client.is_user_authorized():
                await self._on_login_success(sync_now=True)
                return {"next_step": "connected"}
            sent = await self._client.send_code_request(self._phone)
            await self._set_status("code_required")
            return {"next_step": "code_required", "phone_code_hash": sent.phone_code_hash}
        except Exception as exc:
            await self._abort_login(exc)

    async def verify_code(self, code: str, phone_code_hash: str | None) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("尚未開始登入")
        if not self._phone:
            raise RuntimeError("尚未設定手機號碼")
        normalized = (code or "").strip()
        if not normalized:
            raise RuntimeError("請輸入 Telegram 驗證碼")
        try:
            await self._client.sign_in(self._phone, normalized, phone_code_hash=phone_code_hash)
        except errors.SessionPasswordNeededError:
            await self._set_status("2fa_required")
            return {"next_step": "2fa_required"}
        await self._on_login_success(sync_now=True)
        return {"next_step": "connected"}

    async def verify_2fa(self, password: str) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("尚未開始登入")
        if not password or not str(password).strip():
            raise RuntimeError("請輸入兩步驟驗證密碼")
        await self._client.sign_in(password=password)
        await self._on_login_success(sync_now=True)
        return {"next_step": "connected"}

    async def start_qr_login(self, api_id: int, api_hash: str) -> dict[str, Any]:
        parsed_id, cleaned_hash = await self._resolve_credentials(api_id, api_hash)
        self._api_id = parsed_id
        self._api_hash = cleaned_hash
        self._phone = None
        await self._update_source(api_id=self._api_id, api_hash=self._api_hash)
        await self._drop_client()
        await self._set_status("connecting")
        try:
            self._client = self._create_client()
            await self._client.connect()
            if await self._client.is_user_authorized():
                await self._on_login_success(sync_now=True)
                return {"next_step": "connected"}
            self._qr_login = await self._client.qr_login()
            await self._set_status("qr_required")
            return self._qr_payload()
        except Exception as exc:
            await self._abort_login(exc)

    async def wait_qr_login(self, timeout: float | None = None) -> dict[str, Any]:
        wait_seconds = QR_WAIT_DEFAULT_SECONDS if timeout is None else float(timeout)
        wait_seconds = max(QR_WAIT_MIN_SECONDS, min(QR_WAIT_MAX_SECONDS, wait_seconds))
        async with self._qr_wait_lock:
            resumed = self._qr_resume_payload()
            if resumed is not None:
                return resumed
            if self._qr_login is None or self._client is None:
                raise RuntimeError("尚未開始 QR 登入")
            try:
                await self._qr_login.wait(timeout=wait_seconds)
            except errors.SessionPasswordNeededError:
                await self._set_status("2fa_required")
                return {"next_step": "2fa_required"}
            except TimeoutError:
                await self._recreate_qr_if_expired()
                return self._qr_payload()
            except (
                errors.AuthTokenExpiredError,
                errors.AuthTokenInvalidError,
                errors.AuthTokenInvalid2Error,
                errors.AuthTokenInvalidxError,
            ):
                await self._qr_login.recreate()
                return self._qr_payload()
            except TypeError as exc:
                if "Login token response was unexpected" not in str(exc):
                    raise
                return self._qr_payload()
            await self._on_login_success(sync_now=True)
            return {"next_step": "connected"}

    def _qr_resume_payload(self) -> dict[str, Any] | None:
        """Return a terminal step if an earlier wait already finished it.

        A second long-poll (React strict mode, or a response the browser discarded)
        must not call ``wait()`` again after 2FA or a successful scan.
        """
        if self._client is None:
            return None
        if self._status == "2fa_required":
            return {"next_step": "2fa_required"}
        if self._status == "connected":
            return {"next_step": "connected"}
        return None

    async def _recreate_qr_if_expired(self) -> None:
        if self._qr_login is None:
            raise RuntimeError("尚未開始 QR 登入")
        if self._qr_expires_in() <= 1.0:
            await self._qr_login.recreate()

    def _qr_expires_in(self) -> float:
        if self._qr_login is None:
            return 0.0
        expires = self._qr_login.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return (expires - datetime.now(UTC)).total_seconds()

    def _qr_payload(self) -> dict[str, Any]:
        if self._qr_login is None:
            raise RuntimeError("尚未開始 QR 登入")
        expires = self._qr_login.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return {
            "next_step": "qr_required",
            "qr_url": self._qr_login.url,
            "qr_expires_at": to_iso_z(expires),
        }

    def _persist_session(self) -> None:
        if self._client is None or self._client.session is None:
            raise RuntimeError("Telegram client missing; cannot persist session")
        token = self._client.session.save()
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("Telegram session.save() returned an empty token")
        persist_string_session_token(self.session_dir, self.source_id, token)

    async def _apply_profile(self) -> None:
        if self._client is None:
            return
        try:
            me = await self._client.get_me()
        except Exception:
            logger.exception("Failed to fetch Telegram profile")
            return
        phone = getattr(me, "phone", None)
        username = getattr(me, "username", None)
        first = (getattr(me, "first_name", None) or "").strip()
        if phone:
            label = str(phone) if str(phone).startswith("+") else f"+{phone}"
            self._phone = label
        elif username:
            label = f"@{username}"
        elif first:
            label = first
        else:
            return
        await self._update_source(name=label, phone=self._phone)

    def _ensure_watchdog(self) -> None:
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watch_connection(), name="telegram-watchdog")

    async def _on_login_success(self, *, sync_now: bool = False) -> None:
        self._qr_login = None
        if self._client is None:
            raise RuntimeError("Telegram client missing after login")
        await self._apply_profile()
        self._persist_session()
        self._user_wants_connected = True
        sync_error: str | None = None
        if sync_now:
            try:
                await self.sync_dialogs()
            except Exception as exc:
                logger.warning("Dialog sync after login failed: %s", exc)
                sync_error = "已登入，但讀取對話失敗，請按「重新同步對話」。"
        await self._set_status("connected", last_error=sync_error)
        self._ensure_watchdog()
        if self._startup_task is not None:
            self._startup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._startup_task
        self._history_backfill_done = False
        self._startup_task = asyncio.create_task(self._finish_startup())

    async def _finish_startup(self) -> None:
        await asyncio.sleep(1.2)
        try:
            if self._client is not None and await self._client.is_user_authorized():
                await self.sync_dialogs()
            await self._register_message_handlers()
            if not self._history_backfill_done:
                try:
                    await self.backfill_recent_messages()
                finally:
                    self._history_backfill_done = True
            if self._client is not None:
                self._persist_session()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Deferred Telegram startup failed: %s", exc)
            self._last_error = str(exc)
            self.sse.publish("telegram_status", {"status": self._status, "last_error": str(exc)})

    async def _watch_connection(self) -> None:
        delay = 4.0
        while self._user_wants_connected:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            if not self._user_wants_connected:
                return
            if self._status in {"code_required", "qr_required", "2fa_required", "connecting"}:
                continue
            try:
                healthy = await self.is_connected()
            except asyncio.CancelledError:
                raise
            except Exception:
                healthy = False
            if healthy:
                delay = 8.0
                if self._status != "connected":
                    await self._set_status("connected")
                    await self._register_message_handlers()
                continue
            delay = min(max(delay, 3.0) * 1.7, 30.0)
            try:
                await self._reconnect()
                delay = 8.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Telegram reconnect failed: %s", exc)
                await self._set_status("error", last_error=str(exc))

    async def _reconnect(self) -> None:
        async with self._reconnect_lock:
            if not self._user_wants_connected:
                return
            if await self.is_connected():
                await self._register_message_handlers()
                if self._status != "connected":
                    await self._set_status("connected")
                return
            logger.info("Reconnecting Telegram session")
            await self._set_status("connecting", last_error=self._last_error)
            if self._client is not None:
                self._clear_message_handlers()
                result = self._client.disconnect()
                if result is not None:
                    await result
                self._client = None
            self._client = self._create_client()
            await self._client.connect()
            if not await self._client.is_user_authorized():
                self._user_wants_connected = False
                await self._set_status("disconnected", last_error="Telegram session 已失效，請重新登入")
                return
            await self._apply_profile()
            self._persist_session()
            await self._set_status("connected")
            await self._register_message_handlers()
            if not self._history_backfill_done:
                if self._startup_task is not None:
                    self._startup_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._startup_task
                self._startup_task = asyncio.create_task(self._finish_startup())

    async def sync_dialogs(self) -> int:
        if self._client is None or not await self._client.is_user_authorized():
            return 0
        now = utc_now_iso()
        count = 0
        async for dialog in self._client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (TgChannel, Chat)):
                continue
            platform_id = str(dialog.id)
            name = dialog.name or ""
            await self.db.execute(
                "INSERT INTO channels (platform_id, name, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(platform_id) DO UPDATE SET name = excluded.name",
                (platform_id, name, now),
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO channel_subscriptions (platform_id, subscribed) VALUES (?, 0)",
                (platform_id,),
            )
            count += 1
        logger.info("Synced %d Telegram dialogs", count)
        return count

    async def list_channels(self) -> list[dict[str, Any]]:
        rows = await self.db.fetch_all(
            "SELECT c.platform_id, c.name, COALESCE(s.subscribed, 0) AS subscribed "
            "FROM channels c LEFT JOIN channel_subscriptions s ON s.platform_id = c.platform_id "
            "ORDER BY c.name COLLATE NOCASE ASC"
        )
        return [
            {
                "platform_id": row["platform_id"],
                "name": row["name"] or row["platform_id"],
                "subscribed": bool(row["subscribed"]),
            }
            for row in rows
        ]

    async def set_subscriptions(self, platform_ids: list[str]) -> None:
        wanted = {str(item) for item in platform_ids}
        rows = await self.db.fetch_all("SELECT platform_id FROM channels")
        for row in rows:
            pid = str(row["platform_id"])
            await self.db.execute(
                "INSERT INTO channel_subscriptions (platform_id, subscribed) VALUES (?, ?) "
                "ON CONFLICT(platform_id) DO UPDATE SET subscribed = excluded.subscribed",
                (pid, 1 if pid in wanted else 0),
            )
        if self._client is not None and self._client.is_connected():
            await self._register_message_handlers()
            self._history_backfill_done = False
            if self._startup_task is not None:
                self._startup_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._startup_task
            self._startup_task = asyncio.create_task(self._finish_startup())

    async def subscribed_ids(self) -> list[int]:
        rows = await self.db.fetch_all(
            "SELECT platform_id FROM channel_subscriptions WHERE subscribed = 1"
        )
        ids: list[int] = []
        for row in rows:
            try:
                ids.append(int(row["platform_id"]))
            except (TypeError, ValueError):
                continue
        return ids

    def _clear_message_handlers(self) -> None:
        if self._client is not None and self._message_handler is not None and self._message_event_builder is not None:
            self._client.remove_event_handler(self._message_handler, self._message_event_builder)
        self._message_handler = None
        self._message_event_builder = None

    async def _register_message_handlers(self) -> None:
        if self._client is None:
            return
        channel_ids = await self.subscribed_ids()
        self._clear_message_handlers()
        if not channel_ids:
            logger.info("No subscribed Telegram channels; collection disabled")
            return

        async def _handler(event: events.NewMessage.Event) -> None:
            await self._handle_message(event)

        builder = events.NewMessage(chats=channel_ids)
        self._client.add_event_handler(_handler, builder)
        self._message_handler = _handler
        self._message_event_builder = builder

    async def _resolve_channel_name(self, event: Any) -> str:
        try:
            chat = await event.get_chat()
            return getattr(chat, "title", None) or getattr(chat, "username", None) or ""
        except asyncio.CancelledError:
            raise
        except Exception:
            return ""

    async def ingest_message(
        self,
        *,
        message: Any,
        chat_id: int | str,
        channel_name: str = "",
        sender_id: str | None = None,
        sender_name: str | None = None,
    ) -> str | None:
        platform_message_id = str(getattr(message, "id", "") or "")
        if not platform_message_id:
            return None
        chat_key = str(chat_id)
        content = getattr(message, "message", None) or ""
        msg_date = getattr(message, "date", None)
        message_time = to_iso_z(msg_date) if isinstance(msg_date, datetime) else utc_now_iso()
        now = utc_now_iso()
        if channel_name:
            await self.db.execute(
                "INSERT INTO channels (platform_id, name, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(platform_id) DO UPDATE SET name = excluded.name",
                (chat_key, channel_name, now),
            )
        existing = await self.db.fetch_one(
            "SELECT id FROM messages WHERE platform_message_id = ? AND chat_id = ?",
            (platform_message_id, chat_key),
        )
        if existing:
            return str(existing["id"])
        message_id = new_id()
        inserted = await self.db.execute(
            "INSERT OR IGNORE INTO messages "
            "(id, chat_id, platform_message_id, chat_name, sender_id, sender_name, content, timestamp, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (message_id, chat_key, platform_message_id, channel_name, sender_id, sender_name, content, message_time, now),
        )
        if inserted == 0:
            stored = await self.db.fetch_one(
                "SELECT id FROM messages WHERE platform_message_id = ? AND chat_id = ?",
                (platform_message_id, chat_key),
            )
            return str(stored["id"]) if stored else None
        stored = await self.db.fetch_one(
            "SELECT id FROM messages WHERE platform_message_id = ? AND chat_id = ?",
            (platform_message_id, chat_key),
        )
        resolved = str(stored["id"]) if stored else message_id
        self.sse.publish(
            "ingest",
            {
                "message_id": resolved,
                "chat_id": chat_key,
                "chat_name": channel_name,
                "timestamp": message_time,
            },
        )
        if self._ingest_hook is not None:
            try:
                self._ingest_hook()
            except Exception:
                logger.exception("Ingest hook failed")
        return resolved

    async def fetch_hit_images(
        self,
        *,
        chat_id: str | int | None,
        platform_message_id: str | int | None,
    ) -> list[dict[str, str]]:
        """Download photos for one message that already hit. Failure returns no images."""
        if self._client is None or chat_id is None or platform_message_id is None:
            return []
        try:
            chat = int(chat_id)
            message_id = int(platform_message_id)
        except (TypeError, ValueError):
            return []
        if not await self.is_connected():
            return []
        try:
            messages = await self._photo_messages(chat, message_id)
            images: list[dict[str, str]] = []
            for message in messages[:MAX_IMAGES]:
                raw = await self._client.download_media(message, file=bytes)
                if not isinstance(raw, (bytes, bytearray)) or not raw:
                    continue
                encoded = await asyncio.to_thread(encode_jpeg, bytes(raw))
                if encoded:
                    images.append(encoded)
            return images
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Hit image download failed for %s/%s", chat_id, platform_message_id, exc_info=True)
            return []

    async def _photo_messages(self, chat_id: int, message_id: int) -> list[Any]:
        assert self._client is not None
        message = await self._client.get_messages(chat_id, ids=message_id)
        if message is None:
            return []
        group: list[Any] = [message]
        grouped_id = getattr(message, "grouped_id", None)
        if grouped_id:
            window = await self._client.get_messages(
                chat_id,
                min_id=max(0, message_id - 20),
                max_id=message_id + 20,
            )
            siblings = [item for item in list(window or []) if getattr(item, "grouped_id", None) == grouped_id]
            if siblings:
                siblings.sort(key=lambda item: int(getattr(item, "id", 0) or 0))
                group = siblings
        return [item for item in group if message_is_photo(item)][:MAX_IMAGES]

    async def _handle_message(self, event: Any) -> None:
        sender_id, sender_name = _sender_fields(event.sender)
        channel_name = await self._resolve_channel_name(event)
        await self.ingest_message(
            message=event.message,
            chat_id=event.chat_id,
            channel_name=channel_name,
            sender_id=sender_id,
            sender_name=sender_name,
        )

    async def backfill_recent_messages(self, *, limit_per_dialog: int = BACKFILL_LIMIT_PER_DIALOG) -> int:
        if self._client is None or not await self._client.is_user_authorized():
            return 0
        channel_ids = await self.subscribed_ids()
        if not channel_ids:
            return 0
        names = {
            int(row["platform_id"]): str(row["name"] or "")
            for row in await self.db.fetch_all("SELECT platform_id, name FROM channels")
            if str(row["platform_id"]).lstrip("-").isdigit()
        }
        total = 0
        limit = max(1, int(limit_per_dialog))
        for index, chat_id in enumerate(channel_ids):
            try:
                total += await self._backfill_one(chat_id, names.get(chat_id, ""), limit)
            except errors.FloodWaitError as exc:
                wait = int(getattr(exc, "seconds", 0) or 0)
                if wait > FLOOD_WAIT_ABORT_SECONDS:
                    logger.warning("Stopping backfill after FloodWait %ss", wait)
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Backfill failed for %s: %s", chat_id, exc)
            if index + 1 < len(channel_ids):
                await asyncio.sleep(BACKFILL_DIALOG_SLEEP_SECONDS)
        return total

    async def _backfill_one(self, chat_id: int, channel_name: str, limit: int) -> int:
        assert self._client is not None
        ingested = 0
        while True:
            try:
                async for message in self._client.iter_messages(chat_id, limit=limit):
                    if getattr(message, "id", None) is None:
                        continue
                    sender = getattr(message, "sender", None)
                    if sender is None and hasattr(message, "get_sender"):
                        try:
                            sender = await message.get_sender()
                        except Exception:
                            sender = None
                    sender_id, sender_name = _sender_fields(sender)
                    await self.ingest_message(
                        message=message,
                        chat_id=chat_id,
                        channel_name=channel_name,
                        sender_id=sender_id,
                        sender_name=sender_name,
                    )
                    ingested += 1
                return ingested
            except errors.FloodWaitError as exc:
                wait = int(getattr(exc, "seconds", 0) or 0)
                if wait > FLOOD_WAIT_ABORT_SECONDS:
                    raise
                await asyncio.sleep(wait + random.uniform(0.5, 1.5))
