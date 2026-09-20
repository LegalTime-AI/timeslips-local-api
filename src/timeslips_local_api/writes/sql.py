from __future__ import annotations

from datetime import date

from timeslips_local_api.dates import date_to_delphi
from timeslips_local_api.errors import ApiError, BadRequestError, ConflictError, NotFoundError
from timeslips_local_api.firebird import as_text  # noqa: F401
from timeslips_local_api.ledger import Ledger
from timeslips_local_api.models import SlipCreate, SlipPatch

COUNTER_RECORD = 100060
COUNTER_TRANS = 5
NAME_TIMEKEEPER = 0
NAME_CLIENT = 1
NAME_ACTIVITY = 3


def _hours(duration_seconds: int) -> float:
    return round(duration_seconds / 3600.0, 6)


def _name_id(cur, nickname: str, nametype: int) -> int:
    cur.execute(
        "SELECT RECORDID FROM NAME WHERE NICKNAME1 = ? AND NAMETYPE = ?",
        [nickname, nametype],
    )
    row = cur.fetchone()
    if not row:
        raise BadRequestError(f"unknown nickname {nickname!r}")
    return int(row[0])


def _ticks_per_hour(cur) -> int:
    cur.execute(
        """
        SELECT FIRST 10 TIMESPENT, TRANSVALUE, RATEVALUE
        FROM SLPTRANS
        WHERE TRANSTYPE = 1 AND TIMESPENT > 0 AND RATEVALUE > 0 AND TRANSVALUE > 0
        ORDER BY RECORDID DESC
        """
    )
    rows = cur.fetchall()
    if not rows:
        return 3600
    timespent, transvalue, ratevalue = rows[0]
    hours = float(transvalue) / float(ratevalue) if ratevalue else 0
    ticks = float(timespent) / hours if hours else 3600
    if 3500 <= ticks <= 3700:
        return 3600
    return int(round(ticks)) or 3600


def _template_row(cur) -> dict:
    cur.execute(
        """
        SELECT FIRST 1 *
        FROM SLPTRANS
        WHERE TRANSTYPE = 1 AND BILLED = 0 AND INVOICEID = 0
        ORDER BY RECORDID DESC
        """
    )
    row = cur.fetchone()
    if not row:
        raise ApiError(503, "no native unbilled time slip to clone rates from")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _next_ids(cur) -> tuple[int, int]:
    cur.execute("SELECT COUNTERVAL FROM COUNTERS WHERE RECORDID = ?", [COUNTER_RECORD])
    record = int(cur.fetchone()[0]) + 1
    cur.execute("SELECT COUNTERVAL FROM COUNTERS WHERE RECORDID = ?", [COUNTER_TRANS])
    trans = int(cur.fetchone()[0]) + 1
    return record, trans


def _apply_time(row: dict, duration_seconds: int, rate: float, billable: bool, day: date) -> None:
    hours = _hours(duration_seconds)
    row["STARTDATE"] = date_to_delphi(day)
    row["ENDDATE"] = date_to_delphi(day)
    row["TIMESPENT"] = duration_seconds
    row["TIMEUNBILLABLE"] = 0 if billable else duration_seconds
    row["TRANSVALUE"] = round(rate * hours, 4) if billable else 0
    row["BILLSTATUS"] = 1 if billable else 3
    row["BILLED"] = 0
    row["INVOICEID"] = 0
    row["INVOICENUM"] = 0
    row["INVOICEDATE"] = 0
    row["FINALIZEID"] = 0


class SqlSlipWriter:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def create(self, cur, payload: SlipCreate, con) -> int:
        if payload.externalId:
            existing = self.ledger.get(payload.externalId)
            if existing:
                return int(existing)
        user_id = _name_id(cur, payload.timekeeperNickname, NAME_TIMEKEEPER)
        client_id = _name_id(cur, payload.clientNickname, NAME_CLIENT)
        activity_id = _name_id(cur, payload.activityNickname, NAME_ACTIVITY)
        day = date.fromisoformat(payload.date)
        template = _template_row(cur)
        record_id, trans_id = _next_ids(cur)
        rate = float(template.get("RATEVALUE") or 0)
        row = dict(template)
        _apply_time(row, payload.durationSeconds, rate, payload.billable, day)
        row["RECORDID"] = record_id
        row["TRANSID"] = trans_id
        row["EDITCOUNT"] = 1
        row["CLIENTID"] = client_id
        row["USERID"] = user_id
        row["ACTYEXPID"] = activity_id
        row["REFERENCEID"] = 0
        row["HOLD"] = "F"
        row["RECURRING"] = "F"
        row["EXPORTED"] = "F"
        row["WIP"] = "T"
        row["GOTRANSFERRED"] = "F"
        row["SPLITSLIPID"] = 0
        row["ORIGSLIPID"] = 0
        row["SLIPSOURCE"] = 1
        row["TIMERONDATE"] = 0
        row["TIMERONTOD"] = 0
        row["BILLEDSLIPVALUE"] = 0
        row["UNDOSLIPVALUE"] = 0
        row["DESCRIPTION"] = payload.description
        row["CUSTOMTEXT"] = as_text(template.get("CUSTOMTEXT"))
        cols = list(template.keys())
        cur.execute(
            f"INSERT INTO SLPTRANS ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )
        cur.execute(
            "UPDATE COUNTERS SET COUNTERVAL = ? WHERE RECORDID = ?",
            [record_id, COUNTER_RECORD],
        )
        cur.execute(
            "UPDATE COUNTERS SET COUNTERVAL = ? WHERE RECORDID = ?",
            [trans_id, COUNTER_TRANS],
        )
        con.commit()
        if payload.externalId:
            self.ledger.put(payload.externalId, str(record_id))
        return record_id

    def update(self, cur, slip_id: int, patch: SlipPatch, con) -> int:
        cur.execute("SELECT FIRST 1 * FROM SLPTRANS WHERE RECORDID = ?", [slip_id])
        raw = cur.fetchone()
        if not raw:
            raise NotFoundError("slip not found")
        cols = [d[0] for d in cur.description]
        row = dict(zip(cols, raw))
        if int(row.get("BILLED") or 0) or int(row.get("INVOICEID") or 0):
            raise ConflictError("cannot change a billed or invoiced slip")
        if patch.timekeeperNickname:
            row["USERID"] = _name_id(cur, patch.timekeeperNickname, NAME_TIMEKEEPER)
        if patch.clientNickname:
            row["CLIENTID"] = _name_id(cur, patch.clientNickname, NAME_CLIENT)
        if patch.activityNickname:
            row["ACTYEXPID"] = _name_id(cur, patch.activityNickname, NAME_ACTIVITY)
        duration = patch.durationSeconds if patch.durationSeconds is not None else int(row["TIMESPENT"] or 0)
        billable = patch.billable if patch.billable is not None else int(row.get("BILLSTATUS") or 1) == 1
        if patch.date:
            day = date.fromisoformat(patch.date)
        else:
            from timeslips_local_api.dates import delphi_to_date

            day = delphi_to_date(row["STARTDATE"]) or date.today()
        rate = float(row.get("RATEVALUE") or 0)
        _apply_time(row, duration, rate, billable, day)
        if patch.description is not None:
            row["DESCRIPTION"] = patch.description
        row["EDITCOUNT"] = int(row.get("EDITCOUNT") or 0) + 1
        assignments = ", ".join(f"{c} = ?" for c in cols if c != "RECORDID")
        values = [row[c] for c in cols if c != "RECORDID"]
        values.append(slip_id)
        cur.execute(f"UPDATE SLPTRANS SET {assignments} WHERE RECORDID = ?", values)
        con.commit()
        return slip_id

    def delete(self, cur, slip_id: int, con) -> None:
        cur.execute(
            "SELECT BILLED, INVOICEID FROM SLPTRANS WHERE RECORDID = ?",
            [slip_id],
        )
        raw = cur.fetchone()
        if not raw:
            raise NotFoundError("slip not found")
        billed, invoice_id = raw
        if int(billed or 0) or int(invoice_id or 0):
            raise ConflictError("cannot delete a billed or invoiced slip")
        cur.execute("DELETE FROM SLPTRANS WHERE RECORDID = ?", [slip_id])
        con.commit()
        self.ledger.delete_record(str(slip_id))
