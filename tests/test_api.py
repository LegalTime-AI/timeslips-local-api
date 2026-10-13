from __future__ import annotations

import os
import uuid
from datetime import date

import pytest

os.environ["TIMESLIPS_TOKEN"] = "test-token"
os.environ.setdefault("TIMESLIPS_FDB", r"C:\TimeslipsExplore\MAIN_COPY.FDB")
os.environ.setdefault("TIMESLIPS_WRITE_BACKEND", "sql")
os.environ.setdefault(
    "TIMESLIPS_LEDGER_PATH",
    r"C:\TimeslipsExplore\timeslips-local-api-ledger.sqlite",
)

from fastapi.testclient import TestClient

from timeslips_local_api.app import app, get_settings
from timeslips_local_api.firebird import connect
from timeslips_local_api.writes.blobs import decode_slip_description

# Names that exist in the copy database. The timekeeper needs an hourly rate at
# the client's rate level, or the helper refuses the slip (see writes/rates.py).
TK = os.environ.get("TIMESLIPS_TEST_TIMEKEEPER", "JDP")
CLIENT_NICK = os.environ.get("TIMESLIPS_TEST_CLIENT", "Labellarte Trusts")
ACT = os.environ.get("TIMESLIPS_TEST_ACTIVITY", "CLE")
NO_RATE_TK = os.environ.get("TIMESLIPS_TEST_NO_RATE_TIMEKEEPER", "")

get_settings.cache_clear()
client = TestClient(app)
AUTH = {"Authorization": "Bearer test-token"}


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["apiVersion"] == 1
    assert body["service"] == "timeslips-local-api"
    dumped = str(body)
    assert "SYSDBA" not in dumped
    assert "ts_2O17p" not in dumped
    assert "MAIN.FDB" not in dumped
    assert "password" not in dumped.lower()


def test_unauthorized() -> None:
    res = client.get("/v1/status")
    assert res.status_code == 401


def test_status_and_catalogs() -> None:
    status = client.get("/v1/status", headers=AUTH)
    assert status.status_code == 200
    body = status.json()
    assert body["connected"] is True
    assert "slips" in body["capabilities"]
    assert body["productionWritesBlocked"] is False
    tks = client.get("/v1/timekeepers", headers=AUTH).json()["timekeepers"]
    assert any(row["nickname"] == TK for row in tks)
    acts = client.get(f"/v1/activities?q={ACT}", headers=AUTH).json()["activities"]
    assert any(row["nickname"] == ACT for row in acts)


def test_reserved_501() -> None:
    res = client.get("/v1/invoices", headers=AUTH)
    assert res.status_code == 501


def test_slip_lifecycle() -> None:
    external = f"test-{uuid.uuid4()}"
    payload = {
        "externalId": external,
        "timekeeperNickname": TK,
        "clientNickname": CLIENT_NICK,
        "activityNickname": ACT,
        "date": date.today().isoformat(),
        "durationSeconds": 600,
        "billable": True,
        "description": (
            "Reviewed the trust file, prepared the certificate of trust, "
            f"and saved the full LegalTime narrative {external} without truncation."
        ),
    }
    created = client.post("/v1/slips", headers=AUTH, json=payload)
    assert created.status_code == 200, created.text
    slip = created.json()
    slip_id = slip["id"]
    assert slip["durationSeconds"] == 600
    assert slip["timekeeperNickname"] == TK
    assert slip["clientNickname"] == CLIENT_NICK
    assert slip["activityNickname"] == ACT
    # Rate comes from Timeslips' rate rules, never 0 (which shows !Rate / !Value).
    assert slip["rate"] > 0
    assert slip["amount"] == pytest.approx(round(slip["rate"] * slip["hours"], 2), abs=0.01)
    assert slip["description"] == payload["description"]
    assert slip["date"] == payload["date"]
    listed = client.get("/v1/slips", headers=AUTH, params={"date": payload["date"]})
    assert listed.status_code == 200
    match = next(row for row in listed.json()["slips"] if row["id"] == slip_id)
    assert match["description"] == payload["description"]
    assert match["durationSeconds"] == 600
    again = client.post("/v1/slips", headers=AUTH, json=payload)
    assert again.status_code == 200
    assert again.json()["id"] == slip_id
    got = client.get(f"/v1/slips/{slip_id}", headers=AUTH)
    assert got.status_code == 200
    verified = client.post("/v1/slips/verify", headers=AUTH, json={"ids": [slip_id, "0"]})
    body = verified.json()
    assert slip_id in body["stillExists"]
    assert "0" in body["missing"]
    patched = client.patch(
        f"/v1/slips/{slip_id}",
        headers=AUTH,
        json={"durationSeconds": 900, "description": payload["description"] + " patched"},
    )
    assert patched.status_code == 200
    assert patched.json()["durationSeconds"] == 900
    assert patched.json()["description"] == payload["description"] + " patched"
    pulled = client.get(f"/v1/slips/{slip_id}", headers=AUTH)
    assert pulled.status_code == 200
    assert pulled.json()["description"] == payload["description"] + " patched"
    assert pulled.json()["durationSeconds"] == 900
    deleted = client.delete(f"/v1/slips/{slip_id}", headers=AUTH)
    assert deleted.status_code == 200
    missing = client.get(f"/v1/slips/{slip_id}", headers=AUTH)
    assert missing.status_code == 404
    after = client.post("/v1/slips/verify", headers=AUTH, json={"ids": [slip_id]})
    assert slip_id in after.json()["missing"]


@pytest.mark.skipif(
    os.environ.get("TIMESLIPS_TEST_EXPLORE_DB") != "1",
    reason="reads fixed slip ids from the 2026-09 exploration copy; set TIMESLIPS_TEST_EXPLORE_DB=1 there",
)
def test_pull_native_and_legacy_descriptions() -> None:
    native = client.get("/v1/slips/104078", headers=AUTH)
    assert native.status_code == 200
    assert native.json()["description"] == (
        "Review email from David requesting PDFs of new Wills; send with reply."
    )
    legacy = client.get("/v1/slips/104084", headers=AUTH)
    assert legacy.status_code == 200
    assert legacy.json()["description"] == (
        "timeslips-local-api GUI check 2026-09-20 unbilled time slip"
    )


def test_push_writes_native_description_frame() -> None:
    external = f"frame-{uuid.uuid4()}"
    description = (
        "Telephone conference with the trustee about the Oceanfront Property Group "
        "operating agreement, then draft the follow-up letter. " + external
    )
    payload = {
        "externalId": external,
        "timekeeperNickname": TK,
        "clientNickname": CLIENT_NICK,
        "activityNickname": ACT,
        "date": date.today().isoformat(),
        "durationSeconds": 720,
        "billable": True,
        "description": description,
    }
    created = client.post("/v1/slips", headers=AUTH, json=payload)
    assert created.status_code == 200, created.text
    slip_id = int(created.json()["id"])
    assert created.json()["description"] == description
    try:
        con = connect(get_settings())
        cur = con.cursor()
        cur.execute("SELECT DESCRIPTION FROM SLPTRANS WHERE RECORDID = ?", [slip_id])
        blob = cur.fetchone()[0]
        raw = blob if isinstance(blob, bytes) else blob.read()
        con.close()
        assert raw.startswith(bytes.fromhex("470f0100"))
        assert raw.endswith(bytes.fromhex("1e000100000000"))
        assert raw[4:6] == raw[6:8]
        assert decode_slip_description(raw) == description
        pulled = client.get(f"/v1/slips/{slip_id}", headers=AUTH)
        assert pulled.json()["description"] == description
        assert pulled.json()["durationSeconds"] == 720
    finally:
        client.delete(f"/v1/slips/{slip_id}", headers=AUTH)


def test_idempotency_key_header() -> None:
    key = f"hdr-{uuid.uuid4()}"
    payload = {
        "timekeeperNickname": TK,
        "clientNickname": CLIENT_NICK,
        "activityNickname": ACT,
        "date": date.today().isoformat(),
        "durationSeconds": 480,
        "billable": True,
        "description": f"timeslips-local-api idempotency {key}",
    }
    headers = {**AUTH, "Idempotency-Key": key}
    first = client.post("/v1/slips", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    slip_id = first.json()["id"]
    second = client.post("/v1/slips", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == slip_id
    client.delete(f"/v1/slips/{slip_id}", headers=AUTH)


def test_slip_rate_matches_native_rule_and_source() -> None:
    body = {
        "externalId": f"rate-{uuid.uuid4()}",
        "timekeeperNickname": TK,
        "clientNickname": CLIENT_NICK,
        "activityNickname": ACT,
        "date": date.today().isoformat(),
        "durationSeconds": 1800,
        "billable": False,
        "description": "timeslips-local-api rate check (no charge)",
    }
    res = client.post("/v1/slips", headers=AUTH, json=body)
    assert res.status_code == 200, res.text
    slip = res.json()
    try:
        assert slip["billable"] is False
        assert slip["rate"] > 0
        # Native "No Charge" slips keep their value; BILLSTATUS keeps them off the bill.
        assert slip["amount"] == pytest.approx(round(slip["rate"] * 0.5, 2), abs=0.01)
        con = connect(get_settings())
        cur = con.cursor()
        cur.execute(
            "SELECT SLIPSOURCE, TIMEUNBILLABLE, BILLSTATUS FROM SLPTRANS WHERE RECORDID = ?",
            [int(slip["id"])],
        )
        source, unbillable, status = cur.fetchone()
        con.close()
        assert (source, unbillable, status) == (4, 0, 3)
    finally:
        client.delete(f"/v1/slips/{slip['id']}", headers=AUTH)


@pytest.mark.skipif(not NO_RATE_TK, reason="set TIMESLIPS_TEST_NO_RATE_TIMEKEEPER")
def test_timekeeper_without_rate_is_refused() -> None:
    body = {
        "externalId": f"norate-{uuid.uuid4()}",
        "timekeeperNickname": NO_RATE_TK,
        "clientNickname": CLIENT_NICK,
        "activityNickname": ACT,
        "date": date.today().isoformat(),
        "durationSeconds": 600,
        "billable": True,
        "description": "should be refused",
    }
    res = client.post("/v1/slips", headers=AUTH, json=body)
    assert res.status_code == 422
    assert "no hourly rate" in res.json()["error"]
