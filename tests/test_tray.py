from timeslips_local_api.config import Settings, persist_token_if_missing
from timeslips_local_api.health import classify_database_failure, health_payload, probe_database


def test_persist_token_if_missing_fills_empty(tmp_path, monkeypatch) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    env.write_text("TIMESLIPS_FDB=C:/TimeslipsExplore/MAIN_COPY.FDB\nTIMESLIPS_TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    persist_token_if_missing("generated-token")
    text = env.read_text(encoding="utf-8")
    assert "TIMESLIPS_TOKEN=generated-token" in text
    assert "SYSDBA" not in text


def test_persist_token_if_missing_keeps_existing(tmp_path, monkeypatch) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    env.write_text("TIMESLIPS_TOKEN=keep-me\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    persist_token_if_missing("replacement")
    assert env.read_text(encoding="utf-8") == "TIMESLIPS_TOKEN=keep-me\n"


def test_probe_missing_database_file(tmp_path) -> None:
    settings = Settings(fdb=str(tmp_path / "missing.fdb"), token="x")
    assert probe_database(settings) == (False, "file_missing")


def test_health_payload_uses_finite_reasons_and_hides_secrets(tmp_path) -> None:
    settings = Settings(
        fdb=str(tmp_path / "missing.fdb"),
        token="secret-token",
        user="SYSDBA",
        password="ts_2O17p",
    )
    body = health_payload(settings)
    assert body["ok"] is True
    assert body["database"] == {"reachable": False, "reason": "file_missing"}
    dumped = str(body)
    assert "SYSDBA" not in dumped
    assert "ts_2O17p" not in dumped
    assert "secret-token" not in dumped
    assert str(tmp_path) not in dumped


def test_classify_auth_failure_stays_finite(tmp_path) -> None:
    fdb = tmp_path / "MAIN_COPY.FDB"
    fdb.write_bytes(b"x")
    settings = Settings(fdb=str(fdb), token="x")
    reason = classify_database_failure(settings, Exception("Your user name and password are not defined"))
    assert reason == "firebird_auth_failed"
