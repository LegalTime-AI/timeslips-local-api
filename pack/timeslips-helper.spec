# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH).resolve().parent
src = root / "src"

a = Analysis(
    [str(root / "pack" / "run_helper.py")],
    pathex=[str(src)],
    binaries=[],
    datas=[(str(root / "pack" / "timeslips-icon.png"), "pack")],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "timeslips_local_api.app",
        "timeslips_local_api.config",
        "timeslips_local_api.firebird_store",
        "timeslips_local_api.writes.sql",
        "timeslips_local_api.tray",
        "timeslips_local_api.health",
        "timeslips_local_api.runtime",
        "pystray",
        "pystray._win32",
        "PIL",
        "firebirdsql",
        "pydantic_settings",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TimeslipsHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(root / "pack" / "timeslips-helper.ico"),
)
