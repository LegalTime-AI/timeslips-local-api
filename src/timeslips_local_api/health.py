from __future__ import annotations

import threading
from pathlib import Path

from . import API_VERSION, HELPER_VERSION
from .config import Settings
from .errors import ApiError
from .firebird import connect

# Finite reasons only. LegalTime maps these onto Sentry diagnostic_code.
# Never put paths, SYSDBA, SQLSTATE, or exception text here.
DATABASE_REASONS = frozenset(
    {
        "file_missing",
        "not_configured",
        "firebird_unreachable",
        "firebird_timeout",
        "firebird_auth_failed",
    }
)

_cache_lock = threading.Lock()
_cache: dict[str, object] | None = None


def classify_database_failure(settings: Settings, exc: BaseException | None = None) -> str:
    fdb = (settings.fdb or "").strip()
    if not fdb:
        return "not_configured"
    try:
        if not Path(fdb).is_file():
            return "file_missing"
    except OSError:
        return "file_missing"
    text = str(exc or "").lower()
    if "timed out" in text or "timeout" in text:
        return "firebird_timeout"
    if "password" in text or "user name" in text:
        return "firebird_auth_failed"
    return "firebird_unreachable"


def cheap_database_check(settings: Settings) -> tuple[bool, str] | None:
    """Return a verdict that does not talk to Firebird, or None if the file exists."""
    fdb = (settings.fdb or "").strip()
    if not fdb:
        return False, "not_configured"
    try:
        if not Path(fdb).is_file():
            return False, "file_missing"
    except OSError:
        return False, "file_missing"
    return None


def probe_database(settings: Settings, timeout_seconds: float = 3) -> tuple[bool, str | None]:
    cheap = cheap_database_check(settings)
    if cheap is not None:
        return cheap
    try:
        con = connect(settings, timeout_seconds=timeout_seconds)
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM SLPTRANS")
            cur.fetchone()
        finally:
            con.close()
        return True, None
    except ApiError as exc:
        return False, classify_database_failure(settings, exc)
    except Exception as exc:  # noqa: BLE001
        return False, classify_database_failure(settings, exc)


def set_database_snapshot(reachable: bool, reason: str | None) -> None:
    global _cache
    if reason and reason not in DATABASE_REASONS:
        reason = "firebird_unreachable"
    with _cache_lock:
        _cache = {"reachable": reachable, "reason": reason}


def database_watch(settings: Settings, stop: threading.Event, interval_seconds: float = 30) -> None:
    while True:
        reachable, reason = probe_database(settings)
        set_database_snapshot(reachable, reason)
        if stop.wait(interval_seconds):
            return


def health_payload(settings: Settings) -> dict:
    cheap = cheap_database_check(settings)
    with _cache_lock:
        cached = dict(_cache) if _cache is not None else None
    if cheap is not None:
        reachable, reason = cheap
    elif cached is not None:
        reachable = bool(cached["reachable"])
        reason = cached["reason"] if isinstance(cached["reason"], str) else None
    else:
        reachable, reason = True, None
    if reason and reason not in DATABASE_REASONS:
        reason = "firebird_unreachable"
    return {
        "ok": True,
        "service": "timeslips-local-api",
        "apiVersion": API_VERSION,
        "helperVersion": HELPER_VERSION,
        "database": {
            "reachable": reachable,
            "reason": reason,
        },
    }
