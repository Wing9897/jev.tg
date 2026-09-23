"""System-tray launcher for the local web app.

Dev::

    uv run --extra tray python -m server.tray

The frozen executable uses the same entry. It binds the existing FastAPI app
on 127.0.0.1 and shows only a tray icon. Quitting the tray stops uvicorn so
Telegram disconnects with the server lifespan, then removes the icon and
exits this process. The menu callback only schedules that work.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass

import uvicorn

from server.paths import BIND_HOST, DEFAULT_PORT, data_dir, is_frozen, page_url

MENU_OPEN = "開啟頁面"
MENU_QUIT = "結束"
_TRAY_NAME = "jev_tg"
_START_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 30.0
_QUIT_JOIN_SECONDS = 0.5

logger = logging.getLogger(__name__)


def port_in_use(host: str, port: int, timeout: float = 0.4) -> bool:
    """True when something is already accepting connections on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def configure_logging() -> None:
    handlers: list[logging.Handler] = []
    if is_frozen():
        handlers.append(logging.FileHandler(data_dir() / "jev-tg.log", encoding="utf-8"))
    else:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def load_icon():
    """Tray image from the bundled PNG, or a small generated mark if it is missing."""
    from PIL import Image, ImageDraw

    from server.paths import bundle_root

    candidate = bundle_root() / "assets" / "tray.png"
    if candidate.is_file():
        return Image.open(candidate).convert("RGBA")

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=12, fill=(15, 118, 110, 255))
    draw.rounded_rectangle((18, 20, 46, 26), radius=3, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((22, 32, 42, 38), radius=3, fill=(255, 255, 255, 255))
    draw.rounded_rectangle((26, 44, 38, 50), radius=3, fill=(255, 255, 255, 255))
    return image


@dataclass
class RunningServer:
    server: uvicorn.Server
    thread: threading.Thread
    stopped: bool = False


def start_server() -> RunningServer | None:
    """Start uvicorn on the tray thread's sibling. Return None when the port is taken."""
    url = page_url()
    if port_in_use(BIND_HOST, DEFAULT_PORT):
        logger.info("Port %s is already in use; opening %s on the existing server", DEFAULT_PORT, url)
        return None

    from server.main import app

    config = uvicorn.Config(
        app,
        host=BIND_HOST,
        port=DEFAULT_PORT,
        log_level="info",
        use_colors=not is_frozen(),
        timeout_graceful_shutdown=int(_STOP_TIMEOUT_SECONDS),
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="jev-uvicorn", daemon=False)
    thread.start()
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.started:
            logger.info("JEV Telegram Filter at %s", url)
            return RunningServer(server=server, thread=thread)
        if not thread.is_alive():
            logger.error("Server stopped before it accepted connections on %s", url)
            return None
        time.sleep(0.05)
    logger.error("Server did not start within %.0fs", _START_TIMEOUT_SECONDS)
    server.should_exit = True
    thread.join(timeout=5)
    return None


def stop_server(running: RunningServer | None) -> None:
    """Ask uvicorn to shut down so the FastAPI lifespan disconnects Telegram."""
    if running is None or running.stopped:
        return
    running.stopped = True
    # Wait until startup has finished. Setting should_exit before that makes
    # uvicorn return without the lifespan shutdown.
    deadline = time.monotonic() + _STOP_TIMEOUT_SECONDS
    while not running.server.started and running.thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    running.server.should_exit = True
    if running.thread.is_alive():
        running.thread.join(timeout=_STOP_TIMEOUT_SECONDS)
        if running.thread.is_alive():
            logger.error("Server thread did not exit after the tray quit")


def quit_steps(owns_server: bool) -> tuple[str, ...]:
    """Order of work for 結束.

    ``owns_server`` is false when this process found the port already taken and
    must not stop the other server. ``stop_icon`` and the process exit still run
    so Windows can drop this tray icon.
    """
    steps: list[str] = []
    if owns_server:
        steps.append("stop_server")
    steps.append("stop_icon")
    steps.append("exit_if_threads_remain")
    return tuple(steps)


def request_quit(icon: object, running: RunningServer | None) -> None:
    """Schedule 結束 and return.

    On Windows the menu callback is the tray thread. ``Icon.stop()`` only posts
    a quit message; the loop cannot remove the icon until that callback returns.
    Stopping the server or joining threads here wedges that loop, so the
    notification icon stays after the page is already dead.
    """
    threading.Thread(
        target=perform_quit,
        args=(icon, running),
        name="jev-tray-quit",
        daemon=True,
    ).start()


def perform_quit(
    icon: object,
    running: RunningServer | None,
    *,
    exit_process: Callable[[int], None] = os._exit,
) -> None:
    """Run :func:`quit_steps` off the tray thread."""
    for step in quit_steps(owns_server=running is not None):
        try:
            if step == "stop_server":
                stop_server(running)
            elif step == "stop_icon":
                stop_tray_icon(icon)
            elif step == "exit_if_threads_remain":
                exit_if_threads_remain(exit_process=exit_process)
        except Exception:
            logger.exception("Tray quit step %s failed", step)
            if step == "exit_if_threads_remain":
                exit_process(0)


def stop_tray_icon(icon: object) -> None:
    """Ask pystray to delete the notification icon, then leave its loop."""
    try:
        icon.visible = False  # type: ignore[attr-defined]
    except Exception:
        logger.exception("Could not hide the tray icon")
    icon.stop()  # type: ignore[attr-defined]


def exit_if_threads_remain(
    *,
    exit_process: Callable[[int], None] = os._exit,
    join_timeout: float = _QUIT_JOIN_SECONDS,
) -> bool:
    """Join non-daemon threads briefly, then force-exit if any are still alive.

    Uvicorn and Telethon threads are non-daemon. If they outlive the icon loop,
    the process never ends and Windows keeps the tray icon. Returns True when
    ``exit_process`` was called.
    """
    current = threading.current_thread()
    blockers = [
        thread
        for thread in threading.enumerate()
        if thread is not current and thread.is_alive() and not thread.daemon
    ]
    deadline = time.monotonic() + join_timeout
    for thread in blockers:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)
    still_alive = [thread for thread in blockers if thread.is_alive()]
    if not still_alive:
        return False
    logger.warning(
        "Tray process still has non-daemon threads after quit: %s",
        ", ".join(thread.name for thread in still_alive),
    )
    exit_process(0)
    return True


def run_tray(running: RunningServer | None) -> None:
    import pystray

    url = page_url()

    def open_page(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(url)

    scheduled = False

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        nonlocal scheduled
        if scheduled:
            return
        scheduled = True
        request_quit(icon, running)

    menu = pystray.Menu(
        pystray.MenuItem(MENU_OPEN, open_page, default=True),
        pystray.MenuItem(MENU_QUIT, quit_app),
    )
    icon = pystray.Icon(_TRAY_NAME, load_icon(), "JEV Telegram Filter", menu)
    icon.run()


def main() -> None:
    multiprocessing.freeze_support()
    configure_logging()
    running: RunningServer | None = None
    code = 0
    try:
        running = start_server()
        run_tray(running)
    except Exception:
        logger.exception("Tray launcher failed")
        code = 1
    finally:
        stop_server(running)
    # 結束 normally force-exits from the quit thread. This covers the path
    # where the icon loop returned and leftover non-daemon threads would
    # otherwise keep the notification icon on screen.
    os._exit(code)


if __name__ == "__main__":
    main()
