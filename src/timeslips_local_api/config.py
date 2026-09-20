from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_COPY_FDB = r"C:\TimeslipsExplore\MAIN_COPY.FDB"
SIDECAR_ENV_NAME = "timeslips-helper.env"
APPDATA_DIR_NAME = "TimeslipsHelper"


def looks_like_production_fdb(path: str) -> bool:
    parts = Path(path).resolve().parts
    upper = tuple(p.upper() for p in parts)
    return (
        upper[-3:] == ("DATABASES", "FIRM", "MAIN.FDB")
        or (len(upper) >= 2 and upper[-2:] == ("FIRM", "MAIN.FDB") and "DATABASES" in upper)
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIMESLIPS_", extra="ignore")

    fdb: str = DEFAULT_COPY_FDB
    host: str = "localhost"
    fb_port: int = 3050
    user: str = "SYSDBA"
    password: str = "ts_2O17p"
    bind: str = "127.0.0.1"
    port: int = 3051
    token: str = ""
    write_backend: str = "sql"
    allow_production: bool = False
    ledger_path: str = ""

    @property
    def production_blocked(self) -> bool:
        return looks_like_production_fdb(self.fdb) and not self.allow_production

    def ledger_file(self) -> Path:
        if self.ledger_path:
            return Path(self.ledger_path)
        return Path(self.fdb).resolve().parent / "timeslips-local-api-ledger.sqlite"


def frozen_exe_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def appdata_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APPDATA_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def appdata_env_file() -> Path:
    return appdata_dir() / SIDECAR_ENV_NAME


def sidecar_env_file() -> Path:
    exe = frozen_exe_path()
    if exe is not None:
        return exe.parent / SIDECAR_ENV_NAME
    return Path.cwd() / SIDECAR_ENV_NAME


def _env_files() -> tuple[Path, ...]:
    files = []
    sidecar = sidecar_env_file()
    appdata = appdata_env_file()
    if sidecar.is_file():
        files.append(sidecar)
    if appdata.is_file() and appdata != sidecar:
        files.append(appdata)
    return tuple(files)


def load_settings() -> Settings:
    files = _env_files()
    if files:
        return Settings(_env_file=files, _env_file_encoding="utf-8")
    return Settings()


def _upsert_env_token(path: Path, token: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    rewritten = False
    out: list[str] = []
    for line in lines:
        if line.startswith("TIMESLIPS_TOKEN="):
            current = line.split("=", 1)[1].strip()
            if current:
                return
            out.append(f"TIMESLIPS_TOKEN={token}")
            rewritten = True
        else:
            out.append(line)
    if not rewritten:
        out.append(f"TIMESLIPS_TOKEN={token}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def persist_token_if_missing(token: str) -> None:
    if not token:
        return
    _upsert_env_token(appdata_env_file(), token)
    sidecar = sidecar_env_file()
    if sidecar != appdata_env_file():
        _upsert_env_token(sidecar, token)
