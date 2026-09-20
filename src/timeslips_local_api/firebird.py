from __future__ import annotations

from typing import Any

import firebirdsql

from .config import Settings
from .errors import ApiError


def connect(settings: Settings):
    try:
        return firebirdsql.connect(
            host=settings.host,
            port=settings.fb_port,
            database=settings.fdb,
            user=settings.user,
            password=settings.password,
            charset="UTF8",
        )
    except Exception as exc:  # noqa: BLE001
        raise ApiError(503, "Timeslips database unreachable") from exc


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def as_flag(value: Any) -> bool:
    text = as_text(value).upper()
    return text in {"T", "1", "Y", "TRUE"}
