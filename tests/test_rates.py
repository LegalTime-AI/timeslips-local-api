from __future__ import annotations

import struct

import pytest

from timeslips_local_api.writes.rates import (
    MissingRateError,
    RateChoice,
    decode_rate_levels,
    resolve_rate,
)


def levels_blob(rates: dict[int, float]) -> bytes:
    """RATELEVL.LEVELS as Timeslips writes it (header, then t' level-1 rate*10000)."""
    out = bytearray(b"u'\x01\x01" + bytes([len(rates)]) + b"\x00")
    for level, value in sorted(rates.items()):
        out += b"t'" + bytes([level - 1]) + struct.pack("<i", int(round(value * 10000)))
    return bytes(out)


NO_EXCEPTIONS = bytes.fromhex("7f270101000000")
WITH_EXCEPTIONS = bytes.fromhex("7f27010101007e2705000000000000000101000000000102")


class FakeCursor:
    """Answers the three queries resolve_rate makes."""

    def __init__(self, tables, rules, native=None):
        self.tables = tables
        self.rules = rules
        self.native = native or {}
        self._row = None

    def execute(self, sql, params):
        if "FROM RATELEVL" in sql:
            blob = self.tables.get(params[0])
            self._row = (blob,) if blob is not None else None
        elif "FROM RATEEXC" in sql:
            self._row = self.rules.get(params[0])
        elif "FROM SLPTRANS" in sql:
            key = tuple(params)
            self._row = self.native.get(key)
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self._row


JFC, JDP, CLIENT_L5, CLIENT_OWN, CLIENT_EXC, CLIENT_CUSTOM, ACT = 5, 5167, 2546, 1081, 470, 900, 39
TABLES = {
    JFC: levels_blob({1: 100, 5: 475, 13: 595}),
    JDP: levels_blob({}),
    CLIENT_OWN: levels_blob({13: 300}),
}
RULES = {
    CLIENT_L5: (1, 5, NO_EXCEPTIONS),
    CLIENT_OWN: (2, 13, NO_EXCEPTIONS),
    CLIENT_EXC: (1, 1, WITH_EXCEPTIONS),
    CLIENT_CUSTOM: (2, 0, NO_EXCEPTIONS),
}


def test_decode_rate_levels_matches_timeslips_stream() -> None:
    # Real JFC stream from a firm copy: level 13 is $595.
    real = bytes.fromhex("75270101" "0e00" "742700" "40420f00" "74270c" "30ca5a00" "742713" "40420f00")
    assert decode_rate_levels(real) == {1: 100.0, 13: 595.0, 20: 100.0}
    assert decode_rate_levels(None) == {}


def test_timekeeper_rate_at_client_level() -> None:
    cur = FakeCursor(TABLES, RULES)
    assert resolve_rate(cur, JFC, CLIENT_L5, ACT) == RateChoice(1, 5, 475.0)


def test_client_own_rate_table() -> None:
    cur = FakeCursor(TABLES, RULES)
    assert resolve_rate(cur, JFC, CLIENT_OWN, ACT) == RateChoice(2, 13, 300.0)


def test_client_table_without_level_falls_back_to_timekeeper_rate() -> None:
    rules = dict(RULES)
    rules[CLIENT_OWN] = (2, 5, NO_EXCEPTIONS)  # client table only has level 13
    cur = FakeCursor(TABLES, rules)
    assert resolve_rate(cur, JFC, CLIENT_OWN, ACT) == RateChoice(2, 0, 475.0)


def test_timekeeper_missing_level_uses_next_higher_level() -> None:
    rules = dict(RULES)
    rules[CLIENT_L5] = (1, 4, NO_EXCEPTIONS)  # JFC has 1, 5, 13 -> 5
    cur = FakeCursor(TABLES, rules)
    assert resolve_rate(cur, JFC, CLIENT_L5, ACT) == RateChoice(1, 5, 475.0)


def test_timekeeper_without_rate_is_missing_not_copied() -> None:
    cur = FakeCursor(TABLES, RULES)
    with pytest.raises(MissingRateError) as err:
        resolve_rate(cur, JDP, CLIENT_L5, ACT)
    assert (err.value.source, err.value.level) == (1, 5)


def test_rate_exceptions_reuse_timeslips_choice() -> None:
    native = {(JFC, CLIENT_EXC, ACT): (1, 0, 300, 1)}
    cur = FakeCursor(TABLES, RULES, native)
    assert resolve_rate(cur, JFC, CLIENT_EXC, ACT) == RateChoice(1, 0, 300.0, 1)


def test_custom_level_reuses_timeslips_choice_for_same_timekeeper_and_client() -> None:
    native = {(JFC, CLIENT_CUSTOM): (2, 0, 595, 1)}
    cur = FakeCursor(TABLES, RULES, native)
    assert resolve_rate(cur, JFC, CLIENT_CUSTOM, ACT) == RateChoice(2, 0, 595.0, 1)


def test_custom_level_without_history_is_missing() -> None:
    cur = FakeCursor(TABLES, RULES)
    with pytest.raises(MissingRateError):
        resolve_rate(cur, JFC, CLIENT_CUSTOM, ACT)
