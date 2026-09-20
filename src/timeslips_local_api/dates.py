from __future__ import annotations

from datetime import date, datetime

DELPHI_EPOCH = datetime(1899, 12, 30)


def date_to_delphi(value: date) -> int:
    return (datetime(value.year, value.month, value.day) - DELPHI_EPOCH).days


def delphi_to_date(value: object) -> date | None:
    if value in (None, 0, "0"):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return (DELPHI_EPOCH + __import__("datetime").timedelta(days=days)).date()
