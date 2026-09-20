from __future__ import annotations

import threading
from typing import Any

import firebirdsql

from .config import Settings
from .errors import ApiError


def connect(settings: Settings, timeout_seconds: float = 8):
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["con"] = firebirdsql.connect(
                host=settings.host,
                port=settings.fb_port,
                database=settings.fdb,
                user=settings.user,
                password=settings.password,
                charset="UTF8",
            )
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise ApiError(503, "Timeslips database unreachable")
    err = box.get("err")
    if err is not None:
        raise ApiError(503, "Timeslips database unreachable") from err
    con = box.get("con")
    if con is None:
        raise ApiError(503, "Timeslips database unreachable")
    return con


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def as_flag(value: Any) -> bool:
    text = as_text(value).upper()
    return text in {"T", "1", "Y", "TRUE"}
