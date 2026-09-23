# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the tray launcher.

Build from the repository root after ``npm run build`` in ``web/``::

    uv run --extra tray pyinstaller --noconfirm --clean packaging/jev_tg.spec

Windows produces ``dist/jev-tg.exe``. macOS produces
``dist/JEV Telegram Filter.app`` (the workflow wraps that in a DMG).
``data/`` and ``.env`` are not bundled. User data is chosen at runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
DIST = ROOT / "web" / "dist"
ICON_PNG = ROOT / "assets" / "tray.png"
ICON_ICO = ROOT / "assets" / "tray.ico"

if not (DIST / "index.html").is_file():
    raise SystemExit(f"Missing {DIST / 'index.html'}. Run npm run build in web/ first.")
if not ICON_PNG.is_file():
    raise SystemExit(f"Missing tray icon at {ICON_PNG}.")

datas = [
    (str(DIST), "web/dist"),
    (str(ICON_PNG), "assets"),
]
binaries: list = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "server.main",
    "server.tray",
    "server.static_files",
    "fastapi",
    "starlette.staticfiles",
    "telethon",
    "pystray",
    "PIL",
]

for package in (
    "uvicorn",
    "telethon",
    "fastapi",
    "starlette",
    "pystray",
    "cryptography",
    "aiosqlite",
    "sse_starlette",
    "PIL",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas.extend(pkg_datas)
    binaries.extend(pkg_binaries)
    hiddenimports.extend(pkg_hidden)

hiddenimports.extend(collect_submodules("server"))

a = Analysis(
    [str(ROOT / "server" / "tray.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["laya", "torch", "transformers", "huggingface_hub", "safetensors"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="jev-tg",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="jev-tg",
    )
    app = BUNDLE(
        coll,
        name="JEV Telegram Filter.app",
        icon=None,
        bundle_identifier="app.jev.telegram-filter",
        info_plist={
            "CFBundleName": "JEV Telegram Filter",
            "CFBundleDisplayName": "JEV Telegram Filter",
            "CFBundleIdentifier": "app.jev.telegram-filter",
            "LSUIElement": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="jev-tg",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(ICON_ICO) if ICON_ICO.is_file() else None,
    )
