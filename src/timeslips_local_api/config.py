from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_COPY_FDB = r"C:\TimeslipsExplore\MAIN_COPY.FDB"
PRODUCTION_MARKER = ("Databases", "Firm", "MAIN.FDB")


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
