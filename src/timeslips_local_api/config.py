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
    # Opt-in. Listens on every interface so another laptop on a private network
    # can call the helper. Public port forwards are out of scope.
    lan: bool = False
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


LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})


def resolve_bind(settings: Settings) -> str:
    """Return the address uvicorn should bind.

    TIMESLIPS_LAN=1 listens on 0.0.0.0. Any other non-loopback bind is refused,
    including when LAN mode is on, so a public address cannot be selected by
    setting TIMESLIPS_BIND alone.
    """
    bind = (settings.bind or "").strip()
    if settings.lan:
        if bind not in LOOPBACK_BINDS and bind != "0.0.0.0":
            raise ValueError("TIMESLIPS_BIND must be a loopback address")
        return "0.0.0.0"
    if bind not in LOOPBACK_BINDS:
        raise ValueError("TIMESLIPS_BIND must be a loopback address")
    return bind


def load_settings() -> Settings:
    files = _env_files()
    if files:
        return Settings(_env_file=files, _env_file_encoding="utf-8")
    return Settings()


def _upsert_env_token(path: Path, token: str, overwrite: bool = False) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    rewritten = False
    out: list[str] = []
    for line in lines:
        if line.startswith("TIMESLIPS_TOKEN="):
            current = line.split("=", 1)[1].strip()
            if current and not overwrite:
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


def _upsert_env_value(path: Path, key: str, value: str) -> None:
    prefix = f"{key}="
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    rewritten = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            out.append(f"{prefix}{value}")
            rewritten = True
        else:
            out.append(line)
    if not rewritten:
        out.append(f"{prefix}{value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _persist_both(key: str, value: str) -> None:
    _upsert_env_value(appdata_env_file(), key, value)
    sidecar = sidecar_env_file()
    if sidecar != appdata_env_file():
        _upsert_env_value(sidecar, key, value)


def _env_value_is_set(key: str) -> bool:
    if os.environ.get(key, "").strip():
        return True
    prefix = f"{key}="
    for path in _env_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if any(line.startswith(prefix) and line.split("=", 1)[1].strip() for line in lines):
            return True
    return False


def lan_is_explicit() -> bool:
    """True when this PC already chose sharing on or off."""
    return _env_value_is_set("TIMESLIPS_LAN")


def fdb_is_explicit() -> bool:
    """True when a database path was saved. A missing file then stays a tray error."""
    return _env_value_is_set("TIMESLIPS_FDB")


def persist_lan(enabled: bool) -> None:
    """Remember whether other computers on this network may connect. Takes effect on the next launch."""
    _persist_both("TIMESLIPS_LAN", "1" if enabled else "0")


def persist_database_setup(path: str, *, allow_production: bool, enable_lan: bool) -> None:
    """Save the database chosen at first launch."""
    _persist_both("TIMESLIPS_FDB", path)
    if allow_production:
        _persist_both("TIMESLIPS_ALLOW_PRODUCTION", "1")
    if enable_lan:
        persist_lan(True)


def persist_running_token(token: str) -> None:
    """Write the live helper token so LegalTime can call /v1/clients."""
    if not token:
        return
    _upsert_env_token(appdata_env_file(), token, overwrite=True)
    sidecar = sidecar_env_file()
    if sidecar != appdata_env_file():
        _upsert_env_token(sidecar, token, overwrite=True)
