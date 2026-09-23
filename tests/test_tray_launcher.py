"""Tray helpers that do not open a real icon or bind the user's server port."""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from types import SimpleNamespace

from server.tray import (
    MENU_OPEN,
    MENU_QUIT,
    exit_if_threads_remain,
    perform_quit,
    port_in_use,
    quit_steps,
    request_quit,
)


class _FakeThread:
    def __init__(self, *, alive: bool, daemon: bool, name: str) -> None:
        self.daemon = daemon
        self.name = name
        self._alive = alive
        self.join_timeout: float | None = None

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self.join_timeout = timeout


def test_menu_labels() -> None:
    assert MENU_OPEN == "開啟頁面"
    assert MENU_QUIT == "結束"


def test_quit_steps_stop_owned_server_before_the_icon() -> None:
    assert quit_steps(owns_server=True) == ("stop_server", "stop_icon", "exit_if_threads_remain")


def test_quit_steps_leave_a_server_this_process_did_not_start() -> None:
    steps = quit_steps(owns_server=False)
    assert steps == ("stop_icon", "exit_if_threads_remain")
    assert "stop_server" not in steps


def test_perform_quit_follows_the_owned_server_order(monkeypatch) -> None:
    order: list[object] = []
    running = object()
    monkeypatch.setattr("server.tray.stop_server", lambda server: order.append(("stop_server", server)))
    monkeypatch.setattr("server.tray.stop_tray_icon", lambda icon: order.append(("stop_icon", icon)))
    monkeypatch.setattr(
        "server.tray.exit_if_threads_remain",
        lambda **kwargs: order.append("exit_if_threads_remain"),
    )
    icon = object()
    perform_quit(icon, running)
    assert order == [("stop_server", running), ("stop_icon", icon), "exit_if_threads_remain"]


def test_perform_quit_does_not_stop_a_foreign_server(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr("server.tray.stop_server", lambda server: order.append("stop_server"))
    monkeypatch.setattr("server.tray.stop_tray_icon", lambda icon: order.append("stop_icon"))
    monkeypatch.setattr(
        "server.tray.exit_if_threads_remain",
        lambda **kwargs: order.append("exit_if_threads_remain"),
    )
    perform_quit(object(), None)
    assert order == ["stop_icon", "exit_if_threads_remain"]


def test_request_quit_stops_the_icon_off_the_caller_thread(monkeypatch) -> None:
    caller = threading.current_thread()
    stopped_on: list[threading.Thread] = []
    started = threading.Event()

    def stop() -> None:
        stopped_on.append(threading.current_thread())
        started.set()

    monkeypatch.setattr("server.tray.exit_if_threads_remain", lambda **kwargs: None)
    icon = SimpleNamespace(stop=stop, visible=True)
    request_quit(icon, None)
    assert started.wait(timeout=2)
    quit_thread = stopped_on[0]
    assert quit_thread is not caller
    assert quit_thread.name == "jev-tray-quit"
    assert quit_thread.daemon is True
    assert icon.visible is False
    quit_thread.join(timeout=2)
    assert not quit_thread.is_alive()


def test_exit_when_a_non_daemon_thread_survives_the_join(monkeypatch) -> None:
    current = threading.current_thread()
    stuck = _FakeThread(alive=True, daemon=False, name="jev-uvicorn")
    monkeypatch.setattr("server.tray.threading.enumerate", lambda: [current, stuck])
    codes: list[int] = []
    assert exit_if_threads_remain(exit_process=codes.append, join_timeout=0.25) is True
    assert codes == [0]
    assert stuck.join_timeout is not None
    assert 0 < stuck.join_timeout <= 0.25


def test_no_exit_when_blockers_finish_during_the_join(monkeypatch) -> None:
    current = threading.current_thread()

    class _Finishes(_FakeThread):
        def join(self, timeout: float | None = None) -> None:
            super().join(timeout)
            self._alive = False

    finished = _Finishes(alive=True, daemon=False, name="jev-uvicorn")
    daemon = _FakeThread(alive=True, daemon=True, name="pystray")
    monkeypatch.setattr("server.tray.threading.enumerate", lambda: [current, finished, daemon])
    codes: list[int] = []
    assert exit_if_threads_remain(exit_process=codes.append, join_timeout=0.25) is False
    assert codes == []


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
