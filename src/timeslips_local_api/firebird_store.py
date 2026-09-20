from __future__ import annotations

from .config import Settings, looks_like_production_fdb
from .dates import delphi_to_date
from .errors import ApiError, NotFoundError
from .firebird import as_text, connect
from .ledger import Ledger
from .models import (
    NameKind,
    NameRecord,
    Slip,
    SlipCreate,
    SlipPatch,
    Status,
    VerifyResult,
)
from .writes.dll import DllSlipWriter
from .writes.sql import SqlSlipWriter
from .writes.tsimport import TsimportSlipWriter

KIND_TO_NAMETYPE = {"timekeeper": 0, "client": 1, "activity": 3}
NAMETYPE_TO_KIND = {0: "timekeeper", 1: "client", 3: "activity"}
CAPABILITIES = ["slips", "clients", "timekeepers", "activities"]
RESERVED = ["expenses", "references", "invoices"]

SLIP_SELECT = """
SELECT s.RECORDID, s.TRANSID, s.STARTDATE, s.TIMESPENT, s.TRANSVALUE, s.RATEVALUE,
       s.BILLED, s.BILLSTATUS, s.INVOICEID, s.DESCRIPTION, s.CUSTOMTEXT,
       c.NICKNAME1 AS CLIENT_NICK, u.NICKNAME1 AS TK_NICK, a.NICKNAME1 AS ACT_NICK
FROM SLPTRANS s
JOIN NAME c ON c.RECORDID = s.CLIENTID
JOIN NAME u ON u.RECORDID = s.USERID
JOIN NAME a ON a.RECORDID = s.ACTYEXPID
WHERE s.TRANSTYPE = 1
"""


def _classification_status(value: object) -> str:
    code = int(value or 0)
    if code == 1:
        return "open"
    if code == 3:
        return "inactive"
    if code == 10:
        return "template"
    return "other"


def _row_to_slip(row: tuple, external_id: str | None) -> Slip:
    (
        record_id,
        trans_id,
        start,
        timespent,
        transvalue,
        ratevalue,
        billed,
        billstatus,
        _invoice,
        description,
        _custom,
        client_nick,
        tk_nick,
        act_nick,
    ) = row
    seconds = int(timespent or 0)
    day = delphi_to_date(start)
    rate = float(ratevalue or 0)
    amount = float(transvalue or 0)
    return Slip(
        id=str(record_id),
        transId=str(trans_id),
        timekeeperNickname=as_text(tk_nick),
        clientNickname=as_text(client_nick),
        activityNickname=as_text(act_nick),
        date=day.isoformat() if day else "",
        durationSeconds=seconds,
        hours=round(seconds / 3600.0, 6),
        rate=rate,
        amount=amount,
        billable=int(billstatus or 0) == 1,
        billed=bool(int(billed or 0)),
        description=as_text(description),
        externalId=external_id,
    )


class FirebirdStore:
    def __init__(self, settings: Settings, ledger: Ledger) -> None:
        self.settings = settings
        self.ledger = ledger
        backend = settings.write_backend.lower()
        if backend == "dll":
            self.writer = DllSlipWriter()
        elif backend == "tsimport":
            self.writer = TsimportSlipWriter()
        else:
            self.writer = SqlSlipWriter(ledger)

    def _guard_write(self) -> None:
        if self.settings.production_blocked:
            raise ApiError(403, "production Timeslips database writes are blocked")

    def status(self) -> Status:
        connected = False
        version = None
        try:
            con = connect(self.settings)
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM SLPTRANS")
            cur.fetchone()
            connected = True
            con.close()
        except Exception:  # noqa: BLE001
            connected = False
        display_db = self.settings.fdb
        if looks_like_production_fdb(display_db):
            display_db = "(production path hidden)"
        return Status(
            connected=connected,
            database=display_db if not looks_like_production_fdb(self.settings.fdb) else "blocked-production",
            writeBackend=self.settings.write_backend,
            capabilities=list(CAPABILITIES),
            productionWritesBlocked=self.settings.production_blocked,
            timeslipsVersion=version,
        )

    def list_names(self, kind: NameKind, q: str | None = None, limit: int = 100) -> list[NameRecord]:
        nametype = KIND_TO_NAMETYPE[kind]
        con = connect(self.settings)
        cur = con.cursor()
        sql = """
            SELECT n.RECORDID, n.NICKNAME1, n.NICKNAME2, n.FULLNAME, n.CLASSIFICATION, u.EMAIL
            FROM NAME n
            LEFT JOIN USERINFO u ON u.RECORDID = n.RECORDID
            WHERE n.NAMETYPE = ?
        """
        params: list[object] = [nametype]
        if q:
            sql += " AND (n.NICKNAME1 CONTAINING ? OR n.NICKNAME2 CONTAINING ? OR n.FULLNAME CONTAINING ?)"
            params.extend([q, q, q])
        cap = max(1, min(limit, 500))
        sql = sql.replace("SELECT n.RECORDID", f"SELECT FIRST {cap} n.RECORDID", 1)
        sql += " ORDER BY n.NICKNAME1"
        cur.execute(sql, params)
        rows = []
        for record_id, nick1, nick2, full, classification, email in cur.fetchall():
            rows.append(
                NameRecord(
                    id=str(record_id),
                    nickname=as_text(nick1),
                    nickname2=as_text(nick2),
                    fullName=as_text(full),
                    kind=kind,
                    status=_classification_status(classification),
                    email=as_text(email) or None,
                )
            )
        con.close()
        return rows

    def get_slip(self, slip_id: str) -> Slip:
        con = connect(self.settings)
        cur = con.cursor()
        cur.execute(SLIP_SELECT + " AND s.RECORDID = ?", [int(slip_id)])
        row = cur.fetchone()
        con.close()
        if not row:
            raise NotFoundError("slip not found")
        return _row_to_slip(row, self.ledger.find_external(str(row[0])))

    def list_slips(
        self,
        *,
        date: str | None = None,
        client_nickname: str | None = None,
        timekeeper_nickname: str | None = None,
        billed: bool | None = None,
        limit: int = 100,
    ) -> list[Slip]:
        con = connect(self.settings)
        cur = con.cursor()
        sql = SLIP_SELECT
        params: list[object] = []
        if date:
            from .dates import date_to_delphi
            from datetime import date as date_cls

            sql += " AND s.STARTDATE = ?"
            params.append(date_to_delphi(date_cls.fromisoformat(date)))
        if client_nickname:
            sql += " AND c.NICKNAME1 = ?"
            params.append(client_nickname)
        if timekeeper_nickname:
            sql += " AND u.NICKNAME1 = ?"
            params.append(timekeeper_nickname)
        if billed is not None:
            sql += " AND s.BILLED = ?"
            params.append(1 if billed else 0)
        cap = max(1, min(limit, 500))
        sql = sql.replace("SELECT s.RECORDID", f"SELECT FIRST {cap} s.RECORDID", 1)
        sql += " ORDER BY s.RECORDID DESC"
        cur.execute(sql, params)
        out = []
        for row in cur.fetchall():
            out.append(_row_to_slip(row, self.ledger.find_external(str(row[0]))))
        con.close()
        return out

    def create_slip(self, payload: SlipCreate) -> Slip:
        self._guard_write()
        if payload.externalId:
            existing = self.ledger.get(payload.externalId)
            if existing:
                try:
                    return self.get_slip(existing)
                except NotFoundError:
                    pass
        con = connect(self.settings)
        cur = con.cursor()
        try:
            record_id = self.writer.create(cur, payload, con)
        except ApiError:
            con.close()
            raise
        except Exception:
            con.close()
            raise ApiError(500, "slip write failed")
        con.close()
        return self.get_slip(str(record_id))

    def update_slip(self, slip_id: str, patch: SlipPatch) -> Slip:
        self._guard_write()
        con = connect(self.settings)
        cur = con.cursor()
        try:
            self.writer.update(cur, int(slip_id), patch, con)
        except ApiError:
            con.close()
            raise
        except Exception:
            con.close()
            raise ApiError(500, "slip write failed")
        con.close()
        return self.get_slip(slip_id)

    def delete_slip(self, slip_id: str) -> None:
        self._guard_write()
        con = connect(self.settings)
        cur = con.cursor()
        try:
            self.writer.delete(cur, int(slip_id), con)
        except ApiError:
            con.close()
            raise
        except Exception:
            con.close()
            raise ApiError(500, "slip write failed")
        con.close()

    def verify_slips(self, ids: list[str]) -> VerifyResult:
        still: list[str] = []
        missing: list[str] = []
        billed: list[str] = []
        con = connect(self.settings)
        cur = con.cursor()
        for raw_id in ids:
            cur.execute(
                "SELECT BILLED FROM SLPTRANS WHERE RECORDID = ? AND TRANSTYPE = 1",
                [int(raw_id)],
            )
            row = cur.fetchone()
            if not row:
                missing.append(raw_id)
            elif int(row[0] or 0):
                billed.append(raw_id)
                still.append(raw_id)
            else:
                still.append(raw_id)
        con.close()
        return VerifyResult(stillExists=still, missing=missing, billed=billed)
