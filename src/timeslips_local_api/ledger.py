from __future__ import annotations

import sqlite3
from pathlib import Path


class Ledger:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS slip_ids (
              external_id TEXT PRIMARY KEY,
              record_id TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, external_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT record_id FROM slip_ids WHERE external_id = ?",
            [external_id],
        ).fetchone()
        return str(row[0]) if row else None

    def put(self, external_id: str, record_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO slip_ids (external_id, record_id) VALUES (?, ?)",
            [external_id, record_id],
        )
        self._conn.commit()

    def find_external(self, record_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT external_id FROM slip_ids WHERE record_id = ?",
            [record_id],
        ).fetchone()
        return str(row[0]) if row else None

    def delete_record(self, record_id: str) -> None:
        self._conn.execute("DELETE FROM slip_ids WHERE record_id = ?", [record_id])
        self._conn.commit()
