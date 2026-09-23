"""Paths and process-level defaults."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 18721
DEFAULT_SOURCE_ID = "telegram"
_DATA_DIR_ENV = "JEV_TG_DATA_DIR"
_FRONTEND_DIST_ENV = "JEV_TG_FRONTEND_DIST"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Directory that contains bundled files. Dev runs use the repository root."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return ROOT


def packaged_user_data_dir() -> Path:
    """Per-user data root for a frozen app. Never the PyInstaller temp directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / "jev_tg"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "jev_tg"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "jev_tg"


def _inside(path: Path, parent: Path) -> bool:
    try:
        child = os.path.normcase(str(path.resolve()))
        base = os.path.normcase(str(parent.resolve()))
    except OSError:
        return False
    return child == base or child.startswith(base + os.sep)


def _avoid_bundle_temp(path: Path) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and _inside(path, Path(meipass)):
        return packaged_user_data_dir()
    return path


def data_dir() -> Path:
    """SQLite, Telegram session, and settings.

    Dev (`python -m server`) keeps ``<repo>/data``. A frozen build uses the
    per-user directory, still overridable with ``JEV_TG_DATA_DIR``. A path that
    resolves inside the PyInstaller extraction directory is never used.
    """
    override = os.environ.get(_DATA_DIR_ENV, "").strip()
    if override:
        path = Path(override)
    elif is_frozen():
        path = packaged_user_data_dir()
    else:
        path = ROOT / "data"
    path = _avoid_bundle_temp(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "jev.sqlite"


def sessions_dir() -> Path:
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def page_url(host: str = BIND_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}/"


def frontend_dist() -> Path | None:
    """Built Vite app, if present. An explicit override that is missing stays missing."""
    override = os.environ.get(_FRONTEND_DIST_ENV, "").strip()
    if override:
        path = Path(override)
        if (path / "index.html").is_file():
            return path
        return None
    candidate = bundle_root() / "web" / "dist"
    if (candidate / "index.html").is_file():
        return candidate
    return None
