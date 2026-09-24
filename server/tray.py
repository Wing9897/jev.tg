"""System-tray launcher for the local web app.

Dev::

    uv run --extra tray python -m server.tray

The frozen executable uses the same entry. It binds the existing FastAPI app
on 127.0.0.1 and shows only a tray icon. Choosing 結束 fades the tray logo
once, on another thread, then stops uvicorn. That wait is capped so a slow
Telegram disconnect cannot leave the icon looking frozen. There is no balloon
and no menu status text. The process then exits even if the MTProto connection
is still closing.
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
# Hard cap for the tray's server join. Telethon disconnect can outlive this;
# the quit thread then removes the icon and exits anyway.
_STOP_TIMEOUT_SECONDS = 2.0
_FADE_FRAME_COUNT = 5
# One fade across the shutdown window. The last frame lands before the cap.
_FADE_INTERVAL_SECONDS = 0.4
# When this process does not own the server, play the same fade briefly.
_FADE_BRIEF_INTERVAL_SECONDS = 0.08
# Uvicorn spends this long closing HTTP/SSE, then runs the FastAPI lifespan
# (stop workers, disconnect Telegram, close SQLite). It must be shorter than
# the join cap so that lifespan starts before the tray gives up.
_GRACEFUL_SHUTDOWN_SECONDS = 1
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
        timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_SECONDS,
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


def stop_server(
    running: RunningServer | None,
    *,
    timeout: float = _STOP_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Stop accepting work, then wait at most ``timeout`` seconds.

    ``should_exit`` closes the listener before the wait, so new HTTP and
    worker jobs are not taken. The FastAPI lifespan still runs inside that
    window (stop workers, disconnect Telegram, close SQLite). A stuck MTProto
    disconnect does not extend the wait: callers remove the icon and exit
    with whatever is already committed.
    """
    if running is None or running.stopped:
        return
    now = monotonic or time.monotonic
    pause = sleep or time.sleep
    running.stopped = True
    # Wait until startup has finished, but only inside the same budget.
    # Setting should_exit before that makes uvicorn return without the
    # lifespan shutdown.
    deadline = now() + timeout
    while not running.server.started and running.thread.is_alive() and now() < deadline:
        left = deadline - now()
        if left <= 0:
            break
        pause(min(0.05, left))
    running.server.should_exit = True
    remaining = deadline - now()
    if running.thread.is_alive() and remaining > 0:
        running.thread.join(timeout=remaining)
    if running.thread.is_alive():
        logger.error(
            "Server thread still running after %.1fs; exiting without waiting for Telegram",
            timeout,
        )


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


def fade_frames(image: object, count: int = _FADE_FRAME_COUNT) -> list:
    """Copies of ``image`` from full opacity down toward transparent.

    Frames stay in memory. A missing or unreadable logo yields no frames,
    and the quit path still exits.
    """
    if count < 1 or image is None or not hasattr(image, "convert"):
        return []
    try:
        from PIL import Image

        base = image.convert("RGBA")  # type: ignore[attr-defined]
    except Exception:
        logger.debug("Tray logo could not be faded", exc_info=True)
        return []
    if count == 1:
        return [base]
    floor = 0.15
    frames = []
    for index in range(count):
        factor = 1.0 - (index / (count - 1)) * (1.0 - floor)
        red, green, blue, alpha = base.split()
        scaled = alpha.point(lambda value, scale=factor: int(value * scale))
        frames.append(Image.merge("RGBA", (red, green, blue, scaled)))
    return frames


def _fade_sleep(seconds: float) -> None:
    time.sleep(seconds)


class _IconFade:
    """One fade cycle. The worker is a daemon so it cannot outlive quit."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start(
        self,
        icon: object,
        frames: list,
        interval: float,
        pause: Callable[[float], None],
    ) -> None:
        if frames:
            self._show(icon, frames[0])
        if len(frames) < 2:
            return

        def run() -> None:
            for frame in frames[1:]:
                if self._stop.is_set():
                    return
                pause(interval)
                if self._stop.is_set():
                    return
                self._show(icon, frame)

        self.thread = threading.Thread(target=run, name="jev-tray-fade", daemon=True)
        self.thread.start()

    def finish(self) -> None:
        """Wait out the one cycle, but never longer than the quit cap."""
        if self.thread is not None:
            self.thread.join(timeout=_STOP_TIMEOUT_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.1)

    @staticmethod
    def _show(icon: object, frame: object) -> None:
        try:
            icon.icon = frame  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Skipped a tray fade frame", exc_info=True)


def start_icon_fade(icon: object, *, brief: bool = False) -> _IconFade:
    """Start a single logo fade. The first frame is applied on this thread."""
    interval = _FADE_BRIEF_INTERVAL_SECONDS if brief else _FADE_INTERVAL_SECONDS
    animation = _IconFade()
    animation.start(icon, fade_frames(getattr(icon, "icon", None)), interval, _fade_sleep)
    return animation


def begin_quit(icon: object, running: RunningServer | None) -> None:
    """Fade the logo, then shut down off the tray thread.

    The menu callback must return quickly. Further 結束 and 開啟頁面 clicks
    are ignored by the guard in :func:`run_tray`; the menu text stays put.
    """
    fade = start_icon_fade(icon, brief=running is None)
    request_quit(icon, running, fade)


def request_quit(
    icon: object,
    running: RunningServer | None,
    fade: _IconFade | None = None,
) -> None:
    """Schedule 結束 and return.

    On Windows the menu callback is the tray thread. ``Icon.stop()`` only posts
    a quit message; the loop cannot remove the icon until that callback returns.
    Stopping the server or joining threads here wedges that loop, so the
    notification icon stays after the page is already dead.
    """

    def run() -> None:
        perform_quit(icon, running, fade=fade)

    threading.Thread(target=run, name="jev-tray-quit", daemon=True).start()


def perform_quit(
    icon: object,
    running: RunningServer | None,
    *,
    exit_process: Callable[[int], None] = os._exit,
    fade: _IconFade | None = None,
) -> None:
    """Run :func:`quit_steps` off the tray thread."""
    animation = fade if fade is not None else start_icon_fade(icon, brief=running is None)
    try:
        for step in quit_steps(owns_server=running is not None):
            try:
                if step == "stop_server":
                    stop_server(running)
                elif step == "stop_icon":
                    if running is None:
                        animation.finish()
                    animation.stop()
                    stop_tray_icon(icon)
                elif step == "exit_if_threads_remain":
                    animation.stop()
                    # The server join, when this process owns one, already used the
                    # 2s cap. Do not block again on Telethon or the tray thread.
                    exit_if_threads_remain(exit_process=exit_process, join_timeout=0)
            except Exception:
                logger.exception("Tray quit step %s failed", step)
                animation.stop()
                if step == "exit_if_threads_remain":
                    exit_process(0)
    finally:
        animation.stop()


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
        if scheduled:
            return
        webbrowser.open(url)

    scheduled = False

    def quit_app(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        nonlocal scheduled
        if scheduled:
            return
        scheduled = True
        begin_quit(icon, running)

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
