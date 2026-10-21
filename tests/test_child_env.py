"""Every new copy of the helper must unpack its own files (PyInstaller one-file)."""

from pathlib import Path

import pytest

from timeslips_local_api import update
from timeslips_local_api.config import helper_child_env


def test_child_env_drops_parent_unpack_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI1234")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", r"C:\x\TimeslipsHelper.exe")
    monkeypatch.setenv("_MEIPASS2", r"C:\Temp\_MEI1234")
    monkeypatch.setenv("TIMESLIPS_LAN", "1")
    env = helper_child_env({"TIMESLIPS_LAN": "0"})
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert not any(k.upper().startswith(("_PYI_", "_MEIPASS")) for k in env)
    assert env["TIMESLIPS_LAN"] == "0"
    assert "PATH" in env or "Path" in env


def _capture_popen(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_popen(args, **kwargs):
        calls.append({"args": args, **kwargs})

        class P:
            pid = 1

        return P()

    monkeypatch.setattr(update.subprocess, "Popen", fake_popen)
    return calls


def test_update_replacer_gets_a_clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI1")
    calls = _capture_popen(monkeypatch)
    update._spawn_apply(tmp_path / "new.exe", tmp_path / "TimeslipsHelper.exe")
    assert calls and calls[0]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_APPLICATION_HOME_DIR" not in calls[0]["env"]


def test_restarted_helper_after_update_gets_a_clean_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI2")
    calls = _capture_popen(monkeypatch)
    new = tmp_path / "update" / "TimeslipsHelper.exe"
    new.parent.mkdir()
    new.write_bytes(b"new")
    target = tmp_path / "TimeslipsHelper.exe"
    target.write_bytes(b"old")
    update.apply_update(str(new), str(target), None)
    assert target.read_bytes() == b"new"
    assert calls[-1]["args"] == [str(target)]
    assert calls[-1]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_APPLICATION_HOME_DIR" not in calls[-1]["env"]


def test_first_run_move_starts_the_copy_with_a_clean_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from timeslips_local_api import install

    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\Temp\_MEI3")
    calls: list[dict] = []
    monkeypatch.setattr(install.subprocess, "Popen", lambda args, **kw: calls.append({"args": args, **kw}))
    monkeypatch.setattr(install, "add_start_menu_shortcut", lambda _t: None)
    exe = tmp_path / "Downloads" / "TimeslipsHelper.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    target = tmp_path / "Local" / "TimeslipsHelper" / "TimeslipsHelper.exe"
    assert install.relocate_and_relaunch(exe, target) is True
    assert calls[0]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_APPLICATION_HOME_DIR" not in calls[0]["env"]
