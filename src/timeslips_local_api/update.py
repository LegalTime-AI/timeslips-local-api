from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import HELPER_VERSION
from .config import appdata_dir, frozen_exe_path

RELEASES_URL = "https://api.github.com/repos/LegalTime-AI/timeslips-local-api/releases/latest"
ASSET_NAME = "TimeslipsHelper.exe"
SUMS_NAME = "SHA256SUMS"
CHECK_INTERVAL_SECONDS = 6 * 60 * 60
PROBLEM_CHECK_SECONDS = 15 * 60
_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200
_NO_WINDOW = 0x08000000


def updates_enabled() -> bool:
    if os.environ.get("TIMESLIPS_NO_UPDATE") == "1":
        return False
    return frozen_exe_path() is not None


def version_tuple(value: str) -> tuple[int, ...]:
    text = value.strip().lstrip("vV")
    parts: list[int] = []
    for piece in text.split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def release_is_newer(tag: str, current: str = HELPER_VERSION) -> bool:
    latest = version_tuple(tag)
    installed = version_tuple(current)
    if not latest or not installed:
        return False
    return latest > installed


def parse_sha256_sums(text: str, filename: str = ASSET_NAME) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) != 2:
            continue
        digest, name = parts
        if name.lstrip("*") != filename:
            continue
        if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
            return digest.lower()
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_matches(path: Path, sums_text: str) -> bool:
    expected = parse_sha256_sums(sums_text)
    if not expected:
        return False
    return file_sha256(path) == expected


def asset_url(release: dict, name: str) -> str | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == name:
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url.startswith("https://"):
                return url
    return None


def _get(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"timeslips-local-api/{HELPER_VERSION}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": f"timeslips-local-api/{HELPER_VERSION}"})
    with urllib.request.urlopen(request, timeout=120) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    os.replace(tmp, dest)


def stop_for_update(shutdown) -> None:
    """Stop HTTP, then end this process so the replacer can swap the exe.

    Process exit releases the single-instance mutex. Releasing that mutex
    from the update thread can stall before the process exits, which closes
    port 3051 while the replacer is still waiting.
    """
    shutdown()
    os._exit(0)


def apply_command(downloaded: str, dest: str, parent_pid: int) -> list[str]:
    return ["--apply-update", downloaded, dest, str(parent_pid)]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return bool(ok) and code.value == 259


def wait_for_exit(pid: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.25)
    return not _pid_alive(pid)


def _start_helper(target: Path) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED | _NEW_GROUP
    subprocess.Popen([str(target)], close_fds=True, creationflags=flags)


def apply_update(
    downloaded: str,
    dest: str,
    parent_pid: int | None = None,
    *,
    wait_timeout: float = 45,
    replace_timeout: float = 30,
) -> None:
    """Replace the exe only after the running helper has exited, then start it.

    If the new file cannot be swapped in, start the exe that is still on disk
    so the helper does not stay silent.
    """
    source = Path(downloaded)
    target = Path(dest)
    if parent_pid and not wait_for_exit(parent_pid, wait_timeout):
        logging.error("helper update parent %s did not exit; leaving it running", parent_pid)
        raise SystemExit(1)
    deadline = time.time() + replace_timeout
    replaced = False
    while True:
        try:
            os.replace(source, target)
            replaced = True
            break
        except OSError:
            if time.time() > deadline:
                logging.exception("helper update could not replace %s", target)
                break
            time.sleep(0.25)
    if target.is_file():
        _start_helper(target)
    if not replaced:
        raise SystemExit(1)


def _spawn_apply(downloaded: Path, dest: Path) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = _DETACHED | _NEW_GROUP | _NO_WINDOW
    subprocess.Popen(
        [sys.executable, *apply_command(str(downloaded), str(dest), os.getpid())],
        close_fds=True,
        creationflags=flags,
    )


def check_for_update() -> bool:
    """Download a newer release when the checksum matches. Return True if spawned."""
    dest = frozen_exe_path()
    if dest is None:
        return False
    try:
        release = json.loads(_get(RELEASES_URL).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        logging.warning("helper update check failed", exc_info=True)
        return False
    if not isinstance(release, dict):
        return False
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not release_is_newer(tag):
        return False
    exe_url = asset_url(release, ASSET_NAME)
    sums_url = asset_url(release, SUMS_NAME)
    if not exe_url or not sums_url:
        logging.warning("helper update %s is missing the exe or SHA256SUMS", tag)
        return False
    folder = appdata_dir() / "update"
    downloaded = folder / ASSET_NAME
    try:
        sums = _get(sums_url).decode("utf-8")
        _download(exe_url, downloaded)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError):
        logging.warning("helper update download failed", exc_info=True)
        return False
    if not checksum_matches(downloaded, sums):
        logging.error("helper update checksum mismatch for %s", tag)
        downloaded.unlink(missing_ok=True)
        return False
    logging.info("helper update %s verified; replacing %s", tag, dest)
    _spawn_apply(downloaded, dest)
    return True


def update_due(*, now: float, next_regular: float, next_problem: float, database_down: bool) -> bool:
    """A healthy helper checks on the long interval. A down database checks sooner."""
    return now >= next_regular or (database_down and now >= next_problem)


def update_watch(
    stop: threading.Event,
    on_ready,
    database_down: threading.Event | None = None,
) -> None:
    down = database_down or threading.Event()
    next_regular = 0.0
    next_problem = 0.0
    while not stop.is_set():
        now = time.monotonic()
        is_down = down.is_set()
        if update_due(
            now=now,
            next_regular=next_regular,
            next_problem=next_problem,
            database_down=is_down,
        ):
            try:
                if check_for_update():
                    on_ready()
                    return
            except Exception:
                logging.exception("helper update failed")
            checked = time.monotonic()
            if now >= next_regular:
                next_regular = checked + CHECK_INTERVAL_SECONDS
            if is_down:
                next_problem = checked + PROBLEM_CHECK_SECONDS
        if stop.wait(5):
            return
