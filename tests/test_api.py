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
    assert any(row["nickname"] == "JDP" for row in tks)
    acts = client.get("/v1/activities?q=CLE", headers=AUTH).json()["activities"]
    assert any(row["nickname"] == "CLE" for row in acts)


def test_reserved_501() -> None:
    res = client.get("/v1/invoices", headers=AUTH)
    assert res.status_code == 501


def test_slip_lifecycle() -> None:
    external = f"test-{uuid.uuid4()}"
    payload = {
        "externalId": external,
        "timekeeperNickname": "JDP",
        "clientNickname": "Labellarte Trusts",
        "activityNickname": "CLE",
        "date": date.today().isoformat(),
        "durationSeconds": 600,
        "billable": True,
        "description": f"timeslips-local-api test {external}",
    }
    created = client.post("/v1/slips", headers=AUTH, json=payload)
    assert created.status_code == 200, created.text
    slip = created.json()
    slip_id = slip["id"]
    assert slip["durationSeconds"] == 600
    assert slip["timekeeperNickname"] == "JDP"
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
    deleted = client.delete(f"/v1/slips/{slip_id}", headers=AUTH)
    assert deleted.status_code == 200
    missing = client.get(f"/v1/slips/{slip_id}", headers=AUTH)
    assert missing.status_code == 404
    after = client.post("/v1/slips/verify", headers=AUTH, json={"ids": [slip_id]})
    assert slip_id in after.json()["missing"]


def test_idempotency_key_header() -> None:
    key = f"hdr-{uuid.uuid4()}"
    payload = {
        "timekeeperNickname": "JDP",
        "clientNickname": "Labellarte Trusts",
        "activityNickname": "CLE",
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
