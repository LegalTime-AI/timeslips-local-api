"""Whole name lists must reach LegalTime: a 500 cap hid Cote's last 8 of 508 clients."""
from __future__ import annotations

from timeslips_local_api import firebird_store
from timeslips_local_api.config import Settings
from timeslips_local_api.firebird_store import NAME_LIST_MAX, FirebirdStore
from timeslips_local_api.ledger import Ledger


class _Cur:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, params):
        self.sql = sql
        cap = int(sql.split("FIRST ", 1)[1].split()[0])
        self.out = self.rows[:cap]

    def fetchall(self):
        return self.out


class _Con:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def close(self):
        pass


def test_client_list_returns_more_than_500(monkeypatch, tmp_path):
    rows = [(i, f"Client {i:04d}", None, f"Client {i:04d}", 0, None) for i in range(508)]
    cur = _Cur(rows)
    monkeypatch.setattr(firebird_store, "connect", lambda settings: _Con(cur))
    settings = Settings(fdb=str(tmp_path / "MAIN.FDB"), token="x", ledger_path=str(tmp_path / "ledger.sqlite"))
    store = FirebirdStore(settings, Ledger(settings.ledger_file()))
    names = store.list_names("client", None, 10000)
    assert len(names) == 508
    assert f"FIRST {NAME_LIST_MAX} " in cur.sql
    assert NAME_LIST_MAX >= 10000
