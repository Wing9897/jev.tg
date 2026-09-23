"""Frozen data directory stays out of the PyInstaller temp folder."""

from __future__ import annotations

from pathlib import Path

from server import paths


def test_dev_data_dir_stays_in_the_repo(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("JEV_TG_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths.sys, "frozen", False, raising=False)
    assert paths.data_dir() == paths.ROOT / "data"


def test_override_wins_over_frozen_user_dir(monkeypatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    monkeypatch.setenv("JEV_TG_DATA_DIR", str(custom))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.data_dir() == custom


def test_frozen_windows_uses_appdata(monkeypatch, tmp_path: Path) -> None:
    meipass = tmp_path / "meipass"
    meipass.mkdir()
    appdata = tmp_path / "Roaming"
    monkeypatch.delenv("JEV_TG_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    got = paths.data_dir()
    assert got == appdata / "jev_tg"
    assert paths._inside(got, meipass) is False


def test_frozen_macos_uses_application_support(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("JEV_TG_DATA_DIR", raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: tmp_path))
    assert paths.data_dir() == tmp_path / "Library" / "Application Support" / "jev_tg"


def test_path_inside_pyinstaller_temp_is_redirected(monkeypatch, tmp_path: Path) -> None:
    meipass = tmp_path / "meipass"
    meipass.mkdir()
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("JEV_TG_DATA_DIR", str(meipass / "data"))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.data_dir() == appdata / "jev_tg"


def test_page_url_uses_the_service_port() -> None:
    assert paths.DEFAULT_PORT == 18721
    assert paths.BIND_HOST == "127.0.0.1"
    assert paths.page_url() == "http://127.0.0.1:18721/"
