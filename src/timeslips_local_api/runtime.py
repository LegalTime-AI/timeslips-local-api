from __future__ import annotations

import ctypes
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import appdata_dir, frozen_exe_path

MUTEX_NAME = "Local\\TimeslipsHelper"
RUN_VALUE_NAME = "TimeslipsHelper"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_mutex_handle = None


def configure_file_logging() -> Path:
    path = appdata_dir() / "helper.log"
    handler = RotatingFileHandler(
        path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    return path


def acquire_single_instance() -> bool:
    """Return True if this process owns the helper. False means another copy is live."""
    global _mutex_handle
    if os.environ.get("TIMESLIPS_SKIP_MUTEX") == "1" or sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    already = ctypes.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    _mutex_handle = handle
    return not already


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
        return bool(str(value).strip())
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    exe = frozen_exe_path()
    if enabled and exe is None:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled and exe is not None:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass


def enable_autostart_once() -> None:
    """First packed launch writes HKCU Run so the helper survives logon."""
    if frozen_exe_path() is None:
        return
    if autostart_enabled():
        return
    set_autostart(True)
