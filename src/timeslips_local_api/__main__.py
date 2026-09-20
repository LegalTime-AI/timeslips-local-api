from __future__ import annotations

import multiprocessing
import os
import secrets

import uvicorn

from .app import app, get_settings
from .config import load_settings


def main() -> None:
    multiprocessing.freeze_support()
    settings = load_settings()
    if settings.bind not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("TIMESLIPS_BIND must be a loopback address")
    if not settings.token:
        token = secrets.token_hex(24)
        os.environ["TIMESLIPS_TOKEN"] = token
        print(f"[timeslips-local-api] generated TIMESLIPS_TOKEN={token}")
        get_settings.cache_clear()
        settings = load_settings()
    print(f"[timeslips-local-api] http://{settings.bind}:{settings.port}")
    print(f"[timeslips-local-api] database={settings.fdb}")
    print(f"[timeslips-local-api] write_backend={settings.write_backend}")
    if settings.production_blocked:
        print("[timeslips-local-api] production writes blocked")
    # Import-string uvicorn targets fail inside a frozen Windows exe.
    uvicorn.run(app, host=settings.bind, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
