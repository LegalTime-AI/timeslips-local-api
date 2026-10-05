"""First launch on a Timeslips PC: find the database, share it, open the firewall."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import (
    Settings,
    appdata_dir,
    fdb_is_explicit,
    frozen_exe_path,
    lan_is_explicit,
    load_settings,
    looks_like_production_fdb,
    persist_database_setup,
)

CREATE_NO_WINDOW = 0x08000000
FIREWALL_RULE_NAME = "Timeslips helper"


def default_search_paths() -> list[Path]:
    program_data = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData")
    return [
        program_data / "Sage" / "Timeslips" / "Databases" / "Firm" / "MAIN.FDB",
        Path(r"C:\TimeslipsExplore\CopyFirm\MAIN.FDB"),
        Path(r"C:\TimeslipsExplore\MAIN_COPY.FDB"),
    ]


def is_sample_database(path: Path) -> bool:
    """The Timeslips Explore sample and Sample.FDB are not the firm database."""
    if path.name.upper() == "SAMPLE.FDB":
        return True
    return any(part.upper() == "EXPLORE" for part in path.parts)


def database_candidates(registry_path: str | None, extra: list[Path]) -> list[Path]:
    """Existing .fdb files, registry first. A Timeslips folder becomes its MAIN.FDB."""
    ordered: list[Path] = []

    def add(path: Path) -> None:
        candidate = path
        if candidate.suffix.lower() != ".fdb":
            candidate = candidate / "MAIN.FDB"
        try:
            if not candidate.is_file() or is_sample_database(candidate):
                return
            resolved = candidate.resolve()
        except OSError:
            return
        if is_sample_database(resolved) or resolved in ordered:
            return
        ordered.append(resolved)

    if registry_path and registry_path.strip():
        add(Path(registry_path.strip().strip('"')))
    for path in extra:
        add(path)
    return ordered


def select_database(candidates: list[Path], confirm_production) -> tuple[Path | None, bool]:
    """Pick a copy when one exists. A lone live firm file needs a yes."""
    candidates = [path for path in candidates if not is_sample_database(path)]
    copies = [path for path in candidates if not looks_like_production_fdb(str(path))]
    if copies:
        return copies[0], False
    if not candidates:
        return None, False
    firm = candidates[0]
    if confirm_production(firm):
        return firm, True
    return None, False


def read_timeslips_database_path() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    keys = (
        (winreg.HKEY_CURRENT_USER, r"Software\Sage\Timeslips"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Sage\Timeslips"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Sage\Timeslips"),
    )
    for hive, name in keys:
        try:
            with winreg.OpenKey(hive, name) as key:
                value, _ = winreg.QueryValueEx(key, "DatabasePath")
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def ask_yes_no(message: str) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return ctypes.windll.user32.MessageBoxW(None, message, "Timeslips helper", 0x24) == 6


def confirm_live_database(path: Path) -> bool:
    return ask_yes_no(
        "Timeslips helper found the live firm database.\n\n"
        f"{path}\n\n"
        "LegalTime will create time slips in this file. Continue?"
    )


def pick_database_file() -> Path | None:
    if sys.platform != "win32":
        return None
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(
            title="Choose the Timeslips database",
            filetypes=[("Timeslips database", "*.fdb")],
        )
    finally:
        root.destroy()
    if not chosen:
        return None
    path = Path(chosen)
    try:
        if not path.is_file():
            return None
        return path.resolve()
    except OSError:
        return None


def configure_installed_database(
    *,
    candidates: list[Path],
    confirm_production,
    pick_file,
    enable_lan: bool,
) -> tuple[str, bool, bool] | None:
    """Return (path, allow_production, enable_lan), or None if the user cancelled."""
    path, allow = select_database(candidates, confirm_production)
    if path is None:
        path = pick_file()
        if path is None or is_sample_database(path):
            return None
        allow = looks_like_production_fdb(str(path))
    return str(path), allow, enable_lan


def database_needs_setup(settings: Settings) -> bool:
    """First launch only. A saved path that is missing stays a tray error."""
    if fdb_is_explicit():
        return False
    try:
        return not Path(settings.fdb).is_file()
    except OSError:
        return False


def configure_first_run(settings: Settings) -> Settings | None:
    """Find MAIN.FDB when no database has been saved. None means the user cancelled."""
    if not database_needs_setup(settings):
        return settings
    interactive = frozen_exe_path() is not None or os.environ.get("TIMESLIPS_SETUP") == "1"
    if not interactive:
        return settings
    chosen = configure_installed_database(
        candidates=database_candidates(read_timeslips_database_path(), default_search_paths()),
        confirm_production=confirm_live_database,
        pick_file=pick_database_file,
        enable_lan=not lan_is_explicit(),
    )
    if chosen is None:
        return None
    path, allow_production, enable_lan = chosen
    persist_database_setup(path, allow_production=allow_production, enable_lan=enable_lan)
    from .app import get_settings

    get_settings.cache_clear()
    return load_settings()


def firewall_add_args(exe: Path) -> list[str]:
    program = str(exe)
    if any(char.isspace() for char in program):
        program = f'"{program}"'
    return [
        "advfirewall",
        "firewall",
        "add",
        "rule",
        f'name="{FIREWALL_RULE_NAME}"',
        "dir=in",
        "action=allow",
        f"program={program}",
        "enable=yes",
        "profile=private",
    ]


def _netsh(args: list[str]) -> bool:
    try:
        completed = subprocess.run(
            ["netsh", *args],
            check=False,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError:
        return False
    return completed.returncode == 0


def elevated_firewall_script(exe: Path) -> str:
    """PowerShell that adds the Private-network rule after one UAC prompt."""
    program = str(exe).replace("'", "''")
    if any(char.isspace() for char in str(exe)):
        program_arg = f'program="{program}"'
    else:
        program_arg = f"program={program}"
    return (
        "Start-Process -FilePath netsh -Verb RunAs -Wait -ArgumentList "
        "@("
        "'advfirewall','firewall','add','rule',"
        f"'name=\"{FIREWALL_RULE_NAME}\"',"
        "'dir=in','action=allow',"
        f"'{program_arg}',"
        "'enable=yes','profile=private'"
        ")"
    )


def _netsh_elevated(exe: Path) -> bool:
    script = elevated_firewall_script(exe)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            check=False,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError:
        return False
    return completed.returncode == 0


def ensure_private_firewall(exe: Path) -> None:
    """Allow the helper on Private networks. One UAC prompt, then remembered."""
    if sys.platform != "win32" or frozen_exe_path() is None:
        return
    marker = appdata_dir() / "firewall-private.ok"
    if marker.is_file():
        return
    if _netsh(["advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_NAME}"]) or _netsh(
        firewall_add_args(exe)
    ):
        marker.write_text("ok\n", encoding="utf-8")
        return
    if _netsh_elevated(exe):
        marker.write_text("ok\n", encoding="utf-8")
        return
    logging.warning("Timeslips helper could not add a Private-network firewall rule")
    marker.write_text("skipped\n", encoding="utf-8")
