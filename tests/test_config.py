import pytest
from pathlib import Path

from timeslips_local_api.config import looks_like_production_fdb
from timeslips_local_api.errors import ApiError, NotImplementedCapability
from timeslips_local_api.writes.dll import DllSlipWriter


def test_production_path_detected() -> None:
    assert looks_like_production_fdb(r"C:\ProgramData\Sage\Timeslips\Databases\Firm\MAIN.FDB")
    assert not looks_like_production_fdb(r"C:\TimeslipsExplore\MAIN_COPY.FDB")
    assert not looks_like_production_fdb(r"C:\TimeslipsExplore\MAIN_RESTORE_TEST.FDB")


def test_dll_backend_unused() -> None:
    writer = DllSlipWriter()
    with pytest.raises(NotImplementedCapability) as exc:
        writer.create(None, None, None)  # type: ignore[arg-type]
    assert exc.value.status_code == 501


def test_production_writes_guard(tmp_path) -> None:
    from timeslips_local_api.config import Settings
    from timeslips_local_api.firebird_store import FirebirdStore
    from timeslips_local_api.ledger import Ledger

    settings = Settings(
        fdb=r"C:\ProgramData\Sage\Timeslips\Databases\Firm\MAIN.FDB",
        allow_production=False,
        token="x",
        ledger_path=str(tmp_path / "ledger.sqlite"),
    )
    store = FirebirdStore(settings, Ledger(settings.ledger_file()))
    with pytest.raises(ApiError) as exc:
        store._guard_write()
    assert exc.value.status_code == 403
    assert "SYSDBA" not in exc.value.message


def test_sidecar_env_file_sets_database_path(tmp_path, monkeypatch) -> None:
    from timeslips_local_api import config as cfg

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TIMESLIPS_FDB", raising=False)
    monkeypatch.delenv("TIMESLIPS_TOKEN", raising=False)
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: tmp_path / "missing-appdata.env")
    (tmp_path / "timeslips-helper.env").write_text(
        "TIMESLIPS_FDB=C:/TimeslipsExplore/MAIN_COPY.FDB\nTIMESLIPS_TOKEN=sidecar-token\n",
        encoding="utf-8",
    )
    settings = cfg.load_settings()
    assert settings.fdb.endswith("MAIN_COPY.FDB")
    assert settings.token == "sidecar-token"
    assert "SYSDBA" not in settings.fdb


def test_dll_export_snapshot_has_no_create_slip() -> None:
    text = (Path(__file__).resolve().parents[1] / "docs" / "tsdbap32-exports.txt").read_text(encoding="utf-8")
    assert "DB_NewRecord" in text
    assert "DB_SaveRecord" in text
    assert "DB_TSNewTransKey" in text
    assert "CreateSlip" not in text
    assert "InsertSlip" not in text
