import hashlib
from pathlib import Path

import pytest

from timeslips_local_api.config import Settings, persist_lan, resolve_bind
from timeslips_local_api.discovery import beacon_payload, broadcast_destinations
from timeslips_local_api import discovery
from timeslips_local_api.health import health_payload
from timeslips_local_api.update import (
    PROBLEM_CHECK_SECONDS,
    asset_url,
    checksum_matches,
    parse_sha256_sums,
    release_is_newer,
    update_due,
    updates_enabled,
    version_tuple,
)


def test_default_bind_stays_loopback() -> None:
    assert resolve_bind(Settings(token="x")) == "127.0.0.1"


def test_persist_lan_writes_one_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "timeslips-helper.env"
    monkeypatch.setattr("timeslips_local_api.config.appdata_env_file", lambda: target)
    monkeypatch.setattr("timeslips_local_api.config.sidecar_env_file", lambda: target)
    persist_lan(True)
    assert target.read_text(encoding="utf-8") == "TIMESLIPS_LAN=1\n"
    persist_lan(False)
    assert target.read_text(encoding="utf-8") == "TIMESLIPS_LAN=0\n"


def test_lan_mode_listens_on_all_interfaces() -> None:
    assert resolve_bind(Settings(token="x", lan=True)) == "0.0.0.0"
    assert resolve_bind(Settings(token="x", lan=True, bind="0.0.0.0")) == "0.0.0.0"


def test_non_loopback_bind_is_refused() -> None:
    with pytest.raises(ValueError, match="loopback"):
        resolve_bind(Settings(token="x", bind="192.168.1.20"))
    with pytest.raises(ValueError, match="loopback"):
        resolve_bind(Settings(token="x", bind="0.0.0.0"))
    with pytest.raises(ValueError, match="loopback"):
        resolve_bind(Settings(token="x", lan=True, bind="8.8.8.8"))


def test_beacon_has_no_token_or_paths(tmp_path: Path) -> None:
    settings = Settings(
        token="secret-token",
        lan=True,
        fdb=str(tmp_path / "MAIN_COPY.FDB"),
        password="ts_2O17p",
        port=3051,
    )
    payload = beacon_payload(settings)
    assert set(payload) == {"service", "port", "hostName", "helperVersion"}
    assert payload["service"] == "timeslips-local-api"
    assert payload["port"] == 3051
    dumped = str(payload)
    assert "secret-token" not in dumped
    assert "ts_2O17p" not in dumped
    assert "MAIN_COPY" not in dumped


def test_broadcast_includes_subnet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "ipv4_broadcast_addresses", lambda: ["10.88.0.255", "255.255.255.255"])
    assert broadcast_destinations() == ["255.255.255.255", "10.88.0.255"]


def test_health_includes_host_name_without_secrets(tmp_path: Path) -> None:
    settings = Settings(
        fdb=str(tmp_path / "missing.fdb"),
        token="secret-token",
        password="ts_2O17p",
    )
    body = health_payload(settings)
    assert isinstance(body["hostName"], str) and body["hostName"]
    dumped = str(body)
    assert "secret-token" not in dumped
    assert "ts_2O17p" not in dumped


def test_version_compare_ignores_v_prefix() -> None:
    assert version_tuple("v0.3.0") == (0, 3, 0)
    assert release_is_newer("v0.3.1", "0.3.0")
    assert not release_is_newer("v0.3.0", "0.3.0")
    assert not release_is_newer("v0.2.9", "0.3.0")
    assert not release_is_newer("not-a-version", "0.3.0")


def test_checksum_match_does_not_call_github(tmp_path: Path) -> None:
    exe = tmp_path / "TimeslipsHelper.exe"
    exe.write_bytes(b"helper-bytes")
    digest = hashlib.sha256(b"helper-bytes").hexdigest()
    sums = f"{digest}  TimeslipsHelper.exe\n"
    assert parse_sha256_sums(sums) == digest
    assert checksum_matches(exe, sums)
    assert not checksum_matches(exe, f"{'ab' * 32}  TimeslipsHelper.exe\n")
    assert asset_url(
        {"assets": [{"name": "TimeslipsHelper.exe", "browser_download_url": "http://example.test/exe"}]},
        "TimeslipsHelper.exe",
    ) is None
    assert updates_enabled() is False


def test_database_problem_checks_before_the_regular_interval() -> None:
    assert update_due(now=100, next_regular=0, next_problem=0, database_down=False)
    assert not update_due(now=100, next_regular=500, next_problem=0, database_down=False)
    assert update_due(now=100, next_regular=500, next_problem=0, database_down=True)
    assert not update_due(
        now=100,
        next_regular=500,
        next_problem=100 + PROBLEM_CHECK_SECONDS,
        database_down=True,
    )
    assert update_due(
        now=100 + PROBLEM_CHECK_SECONDS,
        next_regular=10_000,
        next_problem=100 + PROBLEM_CHECK_SECONDS,
        database_down=True,
    )
