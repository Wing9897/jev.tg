"""Tray helpers that do not open a real icon or bind the user's server port."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from server.paths import page_url
from server.tray import (
    _FADE_FRAME_COUNT,
    _GRACEFUL_SHUTDOWN_SECONDS,
    _STOP_TIMEOUT_SECONDS,
    MENU_OPEN,
    MENU_QUIT,
    RunningServer,
    begin_quit,
    exit_if_threads_remain,
    perform_quit,
    port_in_use,
    quit_steps,
    request_quit,
    stop_server,
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


class _TrayIcon:
    def __init__(self, image: Image.Image) -> None:
        self._icon = image
        self.frames: list[Image.Image] = []
        self.title = "JEV Telegram Filter"
        self.menu = "open-and-quit"
        self.visible = True
        self.notify_calls: list[object] = []
        self._fail_on: int | None = None
        self._attempts = 0

    @property
    def icon(self) -> Image.Image:
        return self._icon

    @icon.setter
    def icon(self, value: Image.Image) -> None:
        attempt = self._attempts
        self._attempts += 1
        if self._fail_on is not None and attempt == self._fail_on:
            raise RuntimeError("frame")
        self._icon = value
        self.frames.append(value)

    def notify(self, *args: object, **kwargs: object) -> None:
        self.notify_calls.append((args, kwargs))

    def stop(self) -> None:
        return None


def _logo() -> Image.Image:
    return Image.new("RGBA", (4, 4), (15, 118, 110, 255))


def _install_instant_fade(monkeypatch) -> list[float]:
    slept: list[float] = []

    def pause(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("server.tray._fade_sleep", pause)
    return slept


def _join_quit_threads() -> None:
    for thread in threading.enumerate():
        if thread.name in {"jev-tray-quit", "jev-tray-fade"}:
            thread.join(timeout=2)


def test_menu_labels() -> None:
    assert MENU_OPEN == "開啟頁面"
    assert MENU_QUIT == "結束"
    assert page_url() == "http://127.0.0.1:18721/"


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


def test_quit_fades_the_logo_without_notifying(monkeypatch) -> None:
    slept = _install_instant_fade(monkeypatch)
    icon = _TrayIcon(_logo())
    seen = threading.Event()
    during: dict[str, object] = {}

    def slow_stop(running: object, **kwargs: object) -> None:
        deadline = time.monotonic() + 1
        while len(icon.frames) < _FADE_FRAME_COUNT and time.monotonic() < deadline:
            time.sleep(0.001)
        during["frames"] = len(icon.frames)
        during["notify"] = list(icon.notify_calls)
        during["title"] = icon.title
        during["menu"] = icon.menu
        seen.set()

    monkeypatch.setattr("server.tray.stop_server", slow_stop)
    monkeypatch.setattr("server.tray.stop_tray_icon", lambda tray_icon: None)
    monkeypatch.setattr("server.tray.exit_if_threads_remain", lambda **kwargs: None)
    started = time.perf_counter()
    begin_quit(icon, object())
    assert seen.wait(timeout=2)
    _join_quit_threads()
    assert time.perf_counter() - started < 1.0
    assert during["notify"] == []
    assert icon.notify_calls == []
    assert during["title"] == "JEV Telegram Filter"
    assert during["menu"] == "open-and-quit"
    assert during["frames"] == _FADE_FRAME_COUNT
    alphas = [frame.getchannel("A").getpixel((0, 0)) for frame in icon.frames]
    assert alphas[0] > alphas[-1]
    assert alphas == sorted(alphas, reverse=True)
    assert slept
    assert all(seconds <= _STOP_TIMEOUT_SECONDS for seconds in slept)
    assert sum(slept) <= _STOP_TIMEOUT_SECONDS


def test_quit_fades_briefly_when_this_process_does_not_own_the_server(monkeypatch) -> None:
    slept = _install_instant_fade(monkeypatch)
    icon = _TrayIcon(_logo())
    order: list[str] = []
    done = threading.Event()
    join_timeout: list[object] = []

    def finish(**kwargs: object) -> None:
        order.append("exit")
        join_timeout.append(kwargs.get("join_timeout"))
        done.set()

    monkeypatch.setattr("server.tray.stop_server", lambda *_args, **_kwargs: order.append("stop_server"))
    monkeypatch.setattr("server.tray.stop_tray_icon", lambda _icon: order.append("stop_icon"))
    monkeypatch.setattr("server.tray.exit_if_threads_remain", finish)
    started = time.perf_counter()
    begin_quit(icon, None)
    assert done.wait(timeout=2)
    _join_quit_threads()
    assert time.perf_counter() - started < 1.0
    assert icon.notify_calls == []
    assert icon.title == "JEV Telegram Filter"
    assert icon.menu == "open-and-quit"
    assert len(icon.frames) == _FADE_FRAME_COUNT
    assert order == ["stop_icon", "exit"]
    assert join_timeout == [0]
    assert slept
    assert sum(slept) < _STOP_TIMEOUT_SECONDS


def test_quit_skips_a_bad_fade_frame_and_still_exits(monkeypatch) -> None:
    _install_instant_fade(monkeypatch)
    icon = _TrayIcon(_logo())
    icon._fail_on = 1
    done = threading.Event()

    def finish(**kwargs: object) -> None:
        done.set()

    monkeypatch.setattr("server.tray.stop_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("server.tray.stop_tray_icon", lambda _icon: None)
    monkeypatch.setattr("server.tray.exit_if_threads_remain", finish)
    begin_quit(icon, object())
    assert done.wait(timeout=2)
    _join_quit_threads()
    assert icon.notify_calls == []
    assert icon.frames
    assert icon.icon is icon.frames[-1]


def test_stop_server_wait_is_bounded() -> None:
    assert _STOP_TIMEOUT_SECONDS == 2.0
    assert _GRACEFUL_SHUTDOWN_SECONDS < _STOP_TIMEOUT_SECONDS
    clock = {"t": 0.0}

    def monotonic() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        clock["t"] += seconds

    starting = RunningServer(
        server=SimpleNamespace(started=False, should_exit=False),
        thread=_FakeThread(alive=True, daemon=False, name="jev-uvicorn"),
    )
    started_at = time.perf_counter()
    stop_server(starting, monotonic=monotonic, sleep=sleep)
    assert time.perf_counter() - started_at < 1.0
    assert starting.server.should_exit is True
    assert clock["t"] <= _STOP_TIMEOUT_SECONDS + 1e-9
    assert starting.thread.join_timeout is None or starting.thread.join_timeout <= 1e-6

    clock["t"] = 50.0
    serving = RunningServer(
        server=SimpleNamespace(started=True, should_exit=False),
        thread=_FakeThread(alive=True, daemon=False, name="jev-uvicorn"),
    )
    started_at = time.perf_counter()
    stop_server(serving, monotonic=monotonic, sleep=sleep)
    assert time.perf_counter() - started_at < 1.0
    assert serving.server.should_exit is True
    assert serving.thread.join_timeout == _STOP_TIMEOUT_SECONDS
    assert clock["t"] == 50.0


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
