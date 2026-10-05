from pathlib import Path

import pytest

from timeslips_local_api.config import Settings, fdb_is_explicit, lan_is_explicit, persist_database_setup
from timeslips_local_api.install import (
    configure_first_run,
    configure_installed_database,
    database_candidates,
    database_needs_setup,
    elevated_firewall_script,
    firewall_add_args,
    is_sample_database,
    select_database,
)


def test_registry_folder_resolves_to_main_fdb(tmp_path: Path) -> None:
    folder = tmp_path / "Firm"
    folder.mkdir()
    database = folder / "MAIN.FDB"
    database.write_bytes(b"x")
    assert database_candidates(str(folder), []) == [database.resolve()]


def test_missing_paths_are_skipped(tmp_path: Path) -> None:
    present = tmp_path / "MAIN_COPY.FDB"
    present.write_bytes(b"x")
    assert database_candidates(str(tmp_path / "missing"), [present, tmp_path / "gone.fdb"]) == [present.resolve()]


def test_copy_is_preferred_over_the_live_firm_file(tmp_path: Path) -> None:
    copy = tmp_path / "MAIN_COPY.FDB"
    copy.write_bytes(b"x")
    firm = tmp_path / "Databases" / "Firm" / "MAIN.FDB"
    firm.parent.mkdir(parents=True)
    firm.write_bytes(b"x")
    chosen, allow = select_database([firm, copy], confirm_production=lambda _path: True)
    assert chosen == copy
    assert allow is False


def test_live_firm_file_needs_a_yes(tmp_path: Path) -> None:
    firm = tmp_path / "Databases" / "Firm" / "MAIN.FDB"
    firm.parent.mkdir(parents=True)
    firm.write_bytes(b"x")
    chosen, allow = select_database([firm], confirm_production=lambda _path: True)
    assert chosen == firm
    assert allow is True
    declined, _allow = select_database([firm], confirm_production=lambda _path: False)
    assert declined is None


def test_cancelled_picker_does_not_save_a_database(tmp_path: Path) -> None:
    firm = tmp_path / "Databases" / "Firm" / "MAIN.FDB"
    firm.parent.mkdir(parents=True)
    firm.write_bytes(b"x")
    assert configure_installed_database(
        candidates=[firm],
        confirm_production=lambda _path: False,
        pick_file=lambda: None,
        enable_lan=True,
    ) is None


def test_picked_live_file_allows_production_writes(tmp_path: Path) -> None:
    firm = tmp_path / "Databases" / "Firm" / "MAIN.FDB"
    firm.parent.mkdir(parents=True)
    firm.write_bytes(b"x")
    assert configure_installed_database(
        candidates=[],
        confirm_production=lambda _path: False,
        pick_file=lambda: firm,
        enable_lan=True,
    ) == (str(firm), True, True)


def test_first_setup_saves_database_sharing_and_production_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    monkeypatch.delenv("TIMESLIPS_LAN", raising=False)
    firm = tmp_path / "Databases" / "Firm" / "MAIN.FDB"
    persist_database_setup(str(firm), allow_production=True, enable_lan=True)
    text = env.read_text(encoding="utf-8")
    assert f"TIMESLIPS_FDB={firm}" in text
    assert "TIMESLIPS_ALLOW_PRODUCTION=1" in text
    assert "TIMESLIPS_LAN=1" in text
    assert "SYSDBA" not in text


def test_saved_database_is_not_asked_for_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    missing = tmp_path / "missing.fdb"
    env.write_text(f"TIMESLIPS_FDB={missing}\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    monkeypatch.delenv("TIMESLIPS_FDB", raising=False)
    assert fdb_is_explicit() is True
    assert database_needs_setup(Settings(fdb=str(missing), token="x")) is False


def test_explicit_sharing_choice_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    env.write_text("TIMESLIPS_LAN=0\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    monkeypatch.delenv("TIMESLIPS_LAN", raising=False)
    assert lan_is_explicit() is True


def test_explore_sample_and_sample_fdb_are_skipped(tmp_path: Path) -> None:
    sample = tmp_path / "Timeslips" / "Explore" / "MAIN.FDB"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"x")
    named = tmp_path / "Sample.FDB"
    named.write_bytes(b"x")
    firm = tmp_path / "cotedata" / "MAIN.FDB"
    firm.parent.mkdir()
    firm.write_bytes(b"x")
    assert is_sample_database(sample) is True
    assert is_sample_database(named) is True
    assert is_sample_database(firm) is False
    assert database_candidates(str(sample.parent), [named, firm]) == [firm.resolve()]
    chosen, allow = select_database([sample, named], confirm_production=lambda _path: True)
    assert chosen is None
    assert allow is False
    assert configure_installed_database(
        candidates=[],
        confirm_production=lambda _path: True,
        pick_file=lambda: sample,
        enable_lan=True,
    ) is None


def test_update_keeps_a_command_line_database_token_and_sharing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exe next to the old env file must not ask for setup or mint a new token."""
    from timeslips_local_api import config as cfg
    from timeslips_local_api.config import load_settings

    sidecar = tmp_path / "install" / "timeslips-helper.env"
    appdata = tmp_path / "appdata" / "timeslips-helper.env"
    sidecar.parent.mkdir()
    appdata.parent.mkdir()
    firm = tmp_path / "cotedata" / "MAIN.FDB"
    firm.parent.mkdir()
    firm.write_bytes(b"x")
    sidecar.write_text(
        f"TIMESLIPS_FDB={firm}\nTIMESLIPS_LAN=1\nTIMESLIPS_TOKEN=\n",
        encoding="utf-8",
    )
    appdata.write_text("TIMESLIPS_TOKEN=kept-token\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: sidecar)
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: appdata)
    monkeypatch.delenv("TIMESLIPS_FDB", raising=False)
    monkeypatch.delenv("TIMESLIPS_LAN", raising=False)
    monkeypatch.delenv("TIMESLIPS_TOKEN", raising=False)
    monkeypatch.setattr(
        "timeslips_local_api.install.confirm_live_database",
        lambda _path: (_ for _ in ()).throw(AssertionError("update asked for setup")),
    )
    settings = load_settings()
    assert settings.fdb == str(firm)
    assert settings.lan is True
    assert settings.token == "kept-token"
    assert configure_first_run(settings) is settings
    assert sidecar.read_text(encoding="utf-8").count("TIMESLIPS_FDB=") == 1
    assert "kept-token" in appdata.read_text(encoding="utf-8")


def test_command_line_install_skips_the_first_run_wizard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from timeslips_local_api import config as cfg

    env = tmp_path / "timeslips-helper.env"
    firm = tmp_path / "cotedata" / "MAIN.FDB"
    firm.parent.mkdir()
    firm.write_bytes(b"x")
    env.write_text(
        f"TIMESLIPS_FDB={firm}\nTIMESLIPS_TOKEN=kept\nTIMESLIPS_LAN=1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "appdata_env_file", lambda: env)
    monkeypatch.setattr(cfg, "sidecar_env_file", lambda: env)
    monkeypatch.delenv("TIMESLIPS_FDB", raising=False)
    monkeypatch.setattr(
        "timeslips_local_api.install.confirm_live_database",
        lambda _path: (_ for _ in ()).throw(AssertionError("wizard ran")),
    )
    settings = Settings(fdb=str(firm), token="kept", lan=True)
    assert configure_first_run(settings) is settings
    assert "TIMESLIPS_TOKEN=kept" in env.read_text(encoding="utf-8")


def test_firewall_rule_is_private_and_quotes_spaces() -> None:
    args = firewall_add_args(Path(r"C:\Program Files\TimeslipsHelper.exe"))
    assert "profile=private" in args
    assert 'name="Timeslips helper"' in args
    assert r'program="C:\Program Files\TimeslipsHelper.exe"' in args
    assert "profile=any" not in args
    assert "profile=public" not in args
    script = elevated_firewall_script(Path(r"C:\Program Files\TimeslipsHelper.exe"))
    assert 'program="C:\\Program Files\\TimeslipsHelper.exe"' in script
    assert "profile=private" in script
    assert "profile=public" not in script
