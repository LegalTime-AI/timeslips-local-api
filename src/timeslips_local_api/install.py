"""First launch on a Timeslips PC: find the database, share it, open the firewall."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import (
    Settings,
    appdata_dir,
    fdb_is_explicit,
    frozen_exe_path,
    helper_child_env,
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


def select_database(candidates: list[Path], confirm) -> tuple[Path | None, bool]:
    """Pick a copy when one exists, else the live firm file. Every pick needs a yes.

    The live-firm check only recognises the standard ``Databases\\Firm`` folder, so a
    firm that bills from a file somewhere else (Documents, another drive) would
    otherwise be treated as a copy and used without asking.
    """
    candidates = [path for path in candidates if not is_sample_database(path)]
    if not candidates:
        return None, False
    copies = [path for path in candidates if not looks_like_production_fdb(str(path))]
    chosen = copies[0] if copies else candidates[0]
    if not confirm(chosen):
        return None, False
    return chosen, looks_like_production_fdb(str(chosen))


def _version_rank(name: str) -> tuple[int, ...]:
    digits = [int(part) for part in re.findall(r"\d+", name)]
    return tuple(digits) or (0,)


def timeslips_registry_subkeys(names: list[str]) -> list[str]:
    """Where Timeslips keeps DatabasePath: newest version first, then the old flat key.

    Timeslips 2016+ writes ``Software\\Sage\\Timeslips\\v30\\General``; older
    releases wrote ``Software\\Sage\\Timeslips`` directly.
    """
    versions = sorted(
        (name for name in names if re.fullmatch(r"[vV]\d+(\.\d+)*", name)),
        key=_version_rank,
        reverse=True,
    )
    out: list[str] = []
    for version in versions:
        out.extend([f"{version}\\General", version])
    out.append("")
    return out


def read_timeslips_database_path() -> str | None:
    if sys.platform != "win32":
        return None
    import winreg

    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Sage\Timeslips"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Sage\Timeslips"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Sage\Timeslips"),
    )
    for hive, root in roots:
        try:
            with winreg.OpenKey(hive, root) as key:
                names: list[str] = []
                index = 0
                while True:
                    try:
                        names.append(winreg.EnumKey(key, index))
                    except OSError:
                        break
                    index += 1
        except OSError:
            continue
        for sub in timeslips_registry_subkeys(names):
            name = f"{root}\\{sub}" if sub else root
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


def describe_database(path: Path) -> str:
    """Size and last change, so a stale copy is easy to tell from the file in use."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    import datetime

    size_mb = stat.st_size / (1024 * 1024)
    changed = datetime.datetime.fromtimestamp(stat.st_mtime)
    when = changed.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    return f"Size: {size_mb:,.0f} MB\nLast changed: {when}"


def database_confirm_message(path: Path) -> str:
    details = describe_database(path)
    return (
        "Timeslips helper will send time slips to this database:\n\n"
        f"{path}\n"
        + (f"\n{details}\n" if details else "")
        + "\nIs this the database your firm bills from?\n\n"
        "Yes: use it. No: choose a different file."
    )


def confirm_database(path: Path) -> bool:
    return ask_yes_no(database_confirm_message(path))


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
    confirm,
    pick_file,
    enable_lan: bool,
) -> tuple[str, bool, bool] | None:
    """Return (path, allow_production, enable_lan), or None if the user cancelled."""
    path, allow = select_database(candidates, confirm)
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
    """Find MAIN.FDB when no database has been saved. None means the user cancelled.

    An auto-update only replaces the exe. A command-line install already has
    TIMESLIPS_FDB, so this returns the saved settings and does not ask again.
    """
    if not database_needs_setup(settings):
        return settings
    interactive = frozen_exe_path() is not None or os.environ.get("TIMESLIPS_SETUP") == "1"
    if not interactive:
        return settings
    chosen = configure_installed_database(
        candidates=database_candidates(read_timeslips_database_path(), default_search_paths()),
        confirm=confirm_database,
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
        "profile=private,domain",
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
        "'enable=yes','profile=private,domain'"
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


def _same_program(a: str, b: Path) -> bool:
    """Windows path compare (case-insensitive) on every platform so tests match Windows."""
    import ntpath

    try:
        return ntpath.normcase(ntpath.normpath(a.strip().strip('"'))) == ntpath.normcase(
            ntpath.normpath(str(b))
        )
    except (TypeError, ValueError):
        return False


def firewall_rule_rows(output: str) -> list[tuple[bool, str, str]]:
    """Parse ``enabled|action|profile|program`` lines from the rule query."""
    rows: list[tuple[bool, str, str]] = []
    for line in output.splitlines():
        parts = line.strip().split("|", 3)
        if len(parts) != 4:
            continue
        enabled, action, profile, program = parts
        if action.strip().lower() != "allow":
            continue
        rows.append((enabled.strip().lower() == "true", profile.strip(), program.strip()))
    return rows


def firewall_rule_covers(rows: list[tuple[bool, str, str]], exe: Path) -> bool:
    """True when an enabled inbound allow rule for this exact exe covers Private networks."""
    for enabled, profile, program in rows:
        if not enabled or not _same_program(program, exe):
            continue
        profiles = {p.strip().lower() for p in profile.split(",")}
        if profiles & {"private", "any"}:
            return True
    return False


FIREWALL_QUERY = (
    "Get-NetFirewallRule -DisplayName $env:TS_RULE -ErrorAction SilentlyContinue | "
    "Where-Object { $_.Direction -eq 'Inbound' } | ForEach-Object { $app = $_ | Get-NetFirewallApplicationFilter; "
    "'{0}|{1}|{2}|{3}' -f $_.Enabled, $_.Action, $_.Profile, $app.Program }"
)


def read_firewall_rules() -> list[tuple[bool, str, str]] | None:
    """Rules named "Timeslips helper", or None when Windows could not be asked."""
    if sys.platform != "win32":
        return None
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", FIREWALL_QUERY],
            env={**os.environ, "TS_RULE": FIREWALL_RULE_NAME},
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return firewall_rule_rows(completed.stdout or "")


def _firewall_marker_text(status: str, exe: Path) -> str:
    return f"{status}\n{exe}\n"


def _firewall_marker_matches(text: str, exe: Path) -> bool:
    """A marker counts only for the exe it was written for (older markers have no path)."""
    lines = text.splitlines()
    return len(lines) >= 2 and _same_program(lines[1], exe)


def elevated_replace_firewall_script(exe: Path) -> str:
    """One UAC prompt: drop rules with our name that point elsewhere, add one for this exe."""
    import base64

    program = str(exe).replace("'", "''")
    name = FIREWALL_RULE_NAME.replace("'", "''")
    inner = (
        f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue; "
        f"New-NetFirewallRule -DisplayName '{name}' -Direction Inbound -Action Allow "
        f"-Program '{program}' -Profile Private,Domain -Enabled True | Out-Null"
    )
    encoded = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    return (
        "Start-Process -FilePath powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList @('-NoProfile','-EncodedCommand','{encoded}')"
    )


def _replace_firewall_rule(exe: Path) -> bool:
    if _netsh(["advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE_NAME}"]) and _netsh(
        firewall_add_args(exe)
    ):
        return True
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-Command",
                elevated_replace_firewall_script(exe),
            ],
            check=False,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError:
        return False
    return completed.returncode == 0


def ensure_private_firewall(exe: Path) -> None:
    """Allow this exe on Private and office (Domain) networks. One UAC prompt, then remembered.

    A rule with our name is only trusted when it points at this exe. A leftover rule
    from a manual install (or an exe that moved) would otherwise look like success
    while Windows blocks the helper.
    """
    if sys.platform != "win32" or frozen_exe_path() is None:
        return
    marker = appdata_dir() / "firewall-private.ok"
    try:
        saved = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    except OSError:
        saved = ""
    if saved and _firewall_marker_matches(saved, exe):
        return
    rows = read_firewall_rules()
    if rows is not None and firewall_rule_covers(rows, exe):
        marker.write_text(_firewall_marker_text("ok", exe), encoding="utf-8")
        return
    if rows is not None and rows:
        logging.info("firewall rule %r points at another program; replacing it", FIREWALL_RULE_NAME)
        ok = _replace_firewall_rule(exe)
    else:
        ok = _netsh(firewall_add_args(exe)) or _netsh_elevated(exe)
    if ok:
        marker.write_text(_firewall_marker_text("ok", exe), encoding="utf-8")
        return
    logging.warning("Timeslips helper could not add a Private-network firewall rule")
    marker.write_text(_firewall_marker_text("skipped", exe), encoding="utf-8")


def public_network_names() -> list[str]:
    """Connected networks Windows treats as Public (the firewall rule does not apply there)."""
    if sys.platform != "win32":
        return []
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public' | "
                "ForEach-Object { $_.Name }",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]


def make_networks_private() -> bool:
    """Switch Public networks to Private after one UAC prompt."""
    inner = (
        "Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public' | "
        "Set-NetConnectionProfile -NetworkCategory Private"
    )
    script = (
        "Start-Process -FilePath powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList @('-NoProfile','-Command',\"{inner}\")"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            check=False,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except OSError:
        return False
    return completed.returncode == 0 and not public_network_names()


READY_MESSAGE = (
    "Timeslips helper is ready.\n\n"
    "On each computer that uses LegalTime AI, open LegalTime Settings and click Connect "
    "next to Timeslips computer. A box will appear here: click Yes once for each computer.\n\n"
    "The helper starts by itself when this computer turns on. Keep this computer on "
    "during the work day so time can be sent to Timeslips."
)

PUBLIC_NETWORK_MESSAGE = (
    "Windows has this computer's network set to Public, so other computers in the office "
    "can't reach the Timeslips helper.\n\n"
    "Switch this network to Private? Windows will ask for permission once.\n\n"
    "Only do this on your office network, not on public Wi-Fi."
)


def welcome_after_setup(lan: bool) -> None:
    """First launch only: fix a Public network if needed, then say what to do next."""
    if sys.platform != "win32" or not lan:
        return
    if public_network_names() and ask_yes_no(PUBLIC_NETWORK_MESSAGE):
        if not make_networks_private():
            logging.warning("network is still Public after the switch request")
    import ctypes

    ctypes.windll.user32.MessageBoxW(None, READY_MESSAGE, "Timeslips helper", 0x40 | 0x10000)


INSTALLED_EXE_NAME = "TimeslipsHelper.exe"


def installed_exe_path() -> Path:
    return appdata_dir() / INSTALLED_EXE_NAME


def needs_relocation(exe: Path | None, first_setup: bool, target: Path) -> bool:
    """A first launch from Downloads (or anywhere else) moves into the fixed folder.

    Existing installs keep their place: they already have a saved database and
    may keep a token file next to the exe.
    """
    if exe is None or not first_setup:
        return False
    try:
        return exe.resolve() != target.resolve()
    except OSError:
        return False


def relocate_and_relaunch(exe: Path, target: Path) -> bool:
    """Copy this exe to the fixed folder, add a Start menu shortcut, start the copy.

    True means the copy is running and this process should exit.
    """
    import shutil

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(exe, target)
    except OSError:
        logging.exception("could not copy the helper to %s", target)
        return False
    try:
        os.remove(str(target) + ":Zone.Identifier")
    except OSError:
        pass
    add_start_menu_shortcut(target)
    try:
        subprocess.Popen(
            [str(target)],
            cwd=str(target.parent),
            creationflags=(0x00000008 | 0x00000200) if sys.platform == "win32" else 0,
            close_fds=True,
            env=helper_child_env(),
        )
    except OSError:
        logging.exception("could not start the installed helper")
        return False
    return True


def add_start_menu_shortcut(target: Path) -> None:
    if sys.platform != "win32":
        return
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    link = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Timeslips helper.lnk"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TS_LINK);"
        "$s.TargetPath=$env:TS_TARGET;$s.WorkingDirectory=$env:TS_DIR;$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            env={**os.environ, "TS_LINK": str(link), "TS_TARGET": str(target), "TS_DIR": str(target.parent)},
            check=False,
            capture_output=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        logging.warning("could not add the Start menu shortcut")
