"""Choose a slip's rate the way Timeslips does.

A client's rate rule (RATEEXC.DEFRATESOURCE / DEFRATELEVEL) names a rate table
and a level. Source 1 is the timekeeper's table, 2 the client's own table and
3 the activity's table. RATELEVL.LEVELS holds that table: entries
``74 27 <level-1> <int32 rate * 10000>``. On a copy of a real firm database,
97% of native unbilled time slips carry exactly this rate; the rest predate a
later change to the client's level.

Copying the rate of whichever slip happens to be newest gives a new slip
another timekeeper's or client's rate, or a 0 rate that Timeslips shows as
``!Rate`` / ``!Value`` on Slip List.

When the client's own (or the activity's) table has no rate at the client's
level, Timeslips falls back to the timekeeper's rate at that level and stores
level 0. When the timekeeper's own table has no rate at the client's level,
native slips carry the timekeeper's next higher level that has one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

RATE_SOURCE_TIMEKEEPER = 1
RATE_SOURCE_CLIENT = 2
RATE_SOURCE_ACTIVITY = 3
RATE_TYPE_HOURLY = 1
_LEVEL_TAG = b"t'"
_EXCEPTIONS_EMPTY_LEN = 7


@dataclass(frozen=True)
class RateChoice:
    source: int
    level: int
    value: float
    rate_type: int = RATE_TYPE_HOURLY


class MissingRateError(Exception):
    """No usable hourly rate for this timekeeper, client and activity."""

    def __init__(self, source: int | None, level: int | None) -> None:
        super().__init__("missing rate")
        self.source = source
        self.level = level


def _blob_bytes(value) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    reader = getattr(value, "read", None)
    if callable(reader):
        data = reader()
        return data if isinstance(data, bytes) else bytes(data or b"")
    return b""


def decode_rate_levels(blob) -> dict[int, float]:
    """Return {level (1-20): rate} from a RATELEVL.LEVELS stream."""
    data = _blob_bytes(blob)
    out: dict[int, float] = {}
    i = 0
    while i + 7 <= len(data):
        if data[i : i + 2] == _LEVEL_TAG:
            level = data[i + 2] + 1
            (raw,) = struct.unpack("<i", data[i + 3 : i + 7])
            out[level] = raw / 10000.0
            i += 7
        else:
            i += 1
    return out


def _rate_table(cur, name_id: int) -> dict[int, float]:
    cur.execute("SELECT LEVELS FROM RATELEVL WHERE RECORDID = ?", [name_id])
    row = cur.fetchone()
    return decode_rate_levels(row[0]) if row else {}


def _client_rule(cur, client_id: int) -> tuple[int | None, int | None, bool]:
    cur.execute(
        "SELECT DEFRATESOURCE, DEFRATELEVEL, RATEEXCEPTIONS FROM RATEEXC WHERE RECORDID = ?",
        [client_id],
    )
    row = cur.fetchone()
    if not row:
        return None, None, False
    source, level, exceptions = row
    has_exceptions = len(_blob_bytes(exceptions)) > _EXCEPTIONS_EMPTY_LEN
    return (
        int(source) if source is not None else None,
        int(level) if level is not None else None,
        has_exceptions,
    )


def _last_native_rate(cur, user_id: int, client_id: int, activity_id: int) -> RateChoice | None:
    """Rate Timeslips itself last put on a slip for this timekeeper and client."""
    for with_activity in (True, False):
        sql = (
            "SELECT FIRST 1 RATESOURCE, RATELEVEL, RATEVALUE, RATETYPE FROM SLPTRANS "
            "WHERE TRANSTYPE = 1 AND USERID = ? AND CLIENTID = ? AND RATEVALUE > 0 "
            "AND SLIPSOURCE IS DISTINCT FROM 1"
        )
        params: list[object] = [user_id, client_id]
        if with_activity:
            sql += " AND ACTYEXPID = ?"
            params.append(activity_id)
        cur.execute(sql + " ORDER BY RECORDID DESC", params)
        row = cur.fetchone()
        if row:
            source, level, value, rate_type = row
            return RateChoice(int(source or 0), int(level or 0), float(value), int(rate_type or RATE_TYPE_HOURLY))
    return None


def resolve_rate(cur, user_id: int, client_id: int, activity_id: int) -> RateChoice:
    """Rate for a new time slip, or MissingRateError when Timeslips has none."""
    source, level, has_exceptions = _client_rule(cur, client_id)
    if has_exceptions:
        # Per-client exceptions override the table; reuse what Timeslips chose.
        native = _last_native_rate(cur, user_id, client_id, activity_id)
        if native is not None:
            return native
    owner = {
        RATE_SOURCE_TIMEKEEPER: user_id,
        RATE_SOURCE_CLIENT: client_id,
        RATE_SOURCE_ACTIVITY: activity_id,
    }.get(source or 0)
    if owner is not None and level and 1 <= level <= 20:
        value = _rate_table(cur, owner).get(level)
        if value is not None and value > 0:
            return RateChoice(int(source), int(level), float(value))
        if owner == user_id:
            # The timekeeper has no rate at the client's level: native slips
            # use the timekeeper's next higher level that has a rate.
            table = _rate_table(cur, user_id)
            higher = sorted(lvl for lvl, val in table.items() if lvl > level and val > 0)
            if higher:
                return RateChoice(int(source), higher[0], float(table[higher[0]]))
        else:
            # The client's or activity's table has no rate at this level:
            # Timeslips uses the timekeeper's rate at that level and stores
            # level 0 (seen on native slips for such clients).
            value = _rate_table(cur, user_id).get(level)
            if value is not None and value > 0:
                return RateChoice(int(source), 0, float(value))
    elif not has_exceptions:
        # A custom rule (level 0 or an unknown source): reuse Timeslips' own choice.
        native = _last_native_rate(cur, user_id, client_id, activity_id)
        if native is not None:
            return native
    raise MissingRateError(source, level)
