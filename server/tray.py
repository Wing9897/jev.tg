"""System-tray launcher for the local web app.

Dev::

    uv run --extra tray python -m server.tray

The frozen executable uses the same entry. It binds the existing FastAPI app
on 127.0.0.1 and shows only a tray icon. Quitting the tray stops uvicorn so
Telegram disconnects with the server lifespan.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass

import uvicorn

from server.paths import BIND_HOST, DEFAULT_PORT, data_dir, is_frozen, page_url

MENU_OPEN = "開啟頁面"
MENU_QUIT = "結束"
_TRAY_NAME = "jev_tg"
_START_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 30.0

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


def run_tray(running: RunningServer | None) -> None:
    import pystray

    url = page_url()

    def open_page(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(url)

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        stop_server(running)
        icon.stop()

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
    # pystray can leave a non-daemon thread after the icon stops.
    os._exit(code)


if __name__ == "__main__":
    main()
