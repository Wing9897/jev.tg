"""QR login: tg:// URL, expiry refresh, 2FA, and Chinese errors."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from telethon import TelegramClient, errors
from telethon.tl.custom.qrlogin import QRLogin

from server.telegram_service import TelegramService, login_error_text
from server.telegram_session import session_path


class _FakeQrLogin:
    def __init__(self, *, url: str = "tg://login?token=demo", expires_in: float = 60.0) -> None:
        self.url = url
        self.expires = datetime.now(UTC) + timedelta(seconds=expires_in)
        self.wait = AsyncMock()
        self.recreate = AsyncMock()


def _service() -> TelegramService:
    return TelegramService(MagicMock(), MagicMock(), Path("."))


def _attach(service: TelegramService, fake_qr: _FakeQrLogin) -> None:
    service._client = cast(TelegramClient, object())
    service._qr_login = cast(QRLogin, fake_qr)


class LoginErrorTextTests(unittest.TestCase):
    def test_api_id_error_is_traditional_chinese(self) -> None:
        text = login_error_text(errors.ApiIdInvalidError(request=SimpleNamespace()))
        self.assertIn("api_id", text)
        self.assertNotIn("combination is invalid", text)

    def test_password_error_is_traditional_chinese(self) -> None:
        text = login_error_text(errors.PasswordHashInvalidError(request=SimpleNamespace()))
        self.assertIn("密碼", text)

    def test_runtime_error_is_kept(self) -> None:
        self.assertEqual(login_error_text(RuntimeError("尚未開始 QR 登入")), "尚未開始 QR 登入")


class QrLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_qr_login_returns_tg_url(self) -> None:
        service = _service()
        fake_client = AsyncMock()
        fake_client.is_user_authorized = AsyncMock(return_value=False)
        fake_qr = _FakeQrLogin()
        fake_client.qr_login = AsyncMock(return_value=fake_qr)
        service._resolve_credentials = AsyncMock(return_value=(11, "hash"))  # type: ignore[method-assign]
        service._update_source = AsyncMock()  # type: ignore[method-assign]
        service._drop_client = AsyncMock()  # type: ignore[method-assign]
        service._set_status = AsyncMock()  # type: ignore[method-assign]
        service._create_client = lambda: fake_client  # type: ignore[method-assign]

        result = await service.start_qr_login(11, "hash")

        self.assertEqual(result["next_step"], "qr_required")
        self.assertTrue(str(result["qr_url"]).startswith("tg://login?token="))
        self.assertTrue(str(result["qr_expires_at"]).endswith("Z"))

    async def test_wait_timeout_keeps_same_qr(self) -> None:
        service = _service()
        fake_qr = _FakeQrLogin(expires_in=40)
        fake_qr.wait.side_effect = TimeoutError()
        _attach(service, fake_qr)

        result = await service.wait_qr_login(timeout=5)

        self.assertEqual(result["next_step"], "qr_required")
        self.assertEqual(result["qr_url"], "tg://login?token=demo")
        fake_qr.recreate.assert_not_awaited()

    async def test_wait_expired_recreates_qr(self) -> None:
        service = _service()
        fake_qr = _FakeQrLogin(expires_in=-1)
        fake_qr.wait.side_effect = TimeoutError()

        async def _recreate() -> None:
            fake_qr.url = "tg://login?token=refreshed"
            fake_qr.expires = datetime.now(UTC) + timedelta(seconds=60)

        fake_qr.recreate.side_effect = _recreate
        _attach(service, fake_qr)

        result = await service.wait_qr_login(timeout=5)

        self.assertEqual(result["qr_url"], "tg://login?token=refreshed")
        fake_qr.recreate.assert_awaited_once()

    async def test_wait_requires_2fa_and_second_poll_does_not_wait_again(self) -> None:
        service = _service()
        fake_qr = _FakeQrLogin()
        fake_qr.wait.side_effect = errors.SessionPasswordNeededError(request=SimpleNamespace())
        _attach(service, fake_qr)
        service._set_status = AsyncMock()  # type: ignore[method-assign]

        async def _mark_2fa(status: str, *, last_error: str | None = None) -> None:
            service._status = status

        service._set_status.side_effect = _mark_2fa

        first = await service.wait_qr_login()
        second = await service.wait_qr_login()

        self.assertEqual(first, {"next_step": "2fa_required"})
        self.assertEqual(second, {"next_step": "2fa_required"})
        fake_qr.wait.assert_awaited_once()

    async def test_wait_success_persists_and_syncs_without_auto_subscribe(self) -> None:
        service = _service()
        fake_qr = _FakeQrLogin()
        fake_qr.wait.return_value = SimpleNamespace(id=1)
        _attach(service, fake_qr)
        service._on_login_success = AsyncMock()  # type: ignore[method-assign]

        result = await service.wait_qr_login()

        self.assertEqual(result, {"next_step": "connected"})
        service._on_login_success.assert_awaited_once_with(sync_now=True)

    async def test_phone_login_still_returns_code_hash(self) -> None:
        service = _service()
        fake_client = AsyncMock()
        fake_client.is_user_authorized = AsyncMock(return_value=False)
        fake_client.send_code_request = AsyncMock(return_value=SimpleNamespace(phone_code_hash="hash-1"))
        service._resolve_credentials = AsyncMock(return_value=(7, "secret"))  # type: ignore[method-assign]
        service._update_source = AsyncMock()  # type: ignore[method-assign]
        service._drop_client = AsyncMock()  # type: ignore[method-assign]
        service._set_status = AsyncMock()  # type: ignore[method-assign]
        service._create_client = lambda: fake_client  # type: ignore[method-assign]

        result = await service.start_login(7, "secret", " +886912345678 ")

        self.assertEqual(result["next_step"], "code_required")
        self.assertEqual(result["phone_code_hash"], "hash-1")
        fake_client.send_code_request.assert_awaited_once_with("+886912345678")

    async def test_resolve_credentials_reuses_stored_hash(self) -> None:
        service = _service()
        service.ensure_row = AsyncMock(return_value={"api_id": 11, "api_hash": "stored-hash"})  # type: ignore[method-assign]
        parsed_id, api_hash = await service._resolve_credentials(11, "  ")
        self.assertEqual((parsed_id, api_hash), (11, "stored-hash"))

    async def test_persist_string_session_writes_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = TelegramService(MagicMock(), MagicMock(), Path(tmp))
            service._client = cast(TelegramClient, SimpleNamespace(session=SimpleNamespace(save=lambda: "session-token")))
            service._persist_session()
            self.assertEqual(session_path(Path(tmp), service.source_id).read_text(encoding="utf-8"), "session-token")


if __name__ == "__main__":
    unittest.main()
