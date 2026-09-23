"""Tray helpers that do not open a real icon or bind the user's server port."""

from __future__ import annotations

import socket
from pathlib import Path

from server.tray import MENU_OPEN, MENU_QUIT, port_in_use


def test_menu_labels() -> None:
    assert MENU_OPEN == "開啟頁面"
    assert MENU_QUIT == "結束"


def test_port_in_use_sees_a_local_listener() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    assert port != 18721
    try:
        assert port_in_use("127.0.0.1", port) is True
    finally:
        sock.close()
    assert port_in_use("127.0.0.1", port) is False


def test_package_workflow_publishes_branch_builds() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "branches:" in text
    assert "- main" in text
    assert "- master" in text
    assert "v*" not in text
    assert 'tag="v${stamp}"' in text
    assert "+%Y%m%d.%H%M%S" in text
    assert "Both jev-tg.exe and JEV-Telegram-Filter.dmg are required" in text
    assert "pyinstaller" in text
    assert "JEV-Telegram-Filter.dmg" in text
    assert "dist/jev-tg.exe" in text
    spec = (root / "packaging" / "jev_tg.spec").read_text(encoding="utf-8")
    assert "web/dist" in spec
    assert '"tray.py"' in spec
    assert "uvicorn" in spec
    assert "telethon" in spec
    assert "fastapi" in spec
