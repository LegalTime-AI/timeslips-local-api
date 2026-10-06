from __future__ import annotations

import logging
import multiprocessing
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from .app import app, get_settings
from .config import frozen_exe_path, load_settings, persist_running_token, resolve_bind
from .discovery import advertise
from .health import database_watch
from .install import configure_first_run, ensure_private_firewall
from .runtime import (
    acquire_single_instance,
    configure_file_logging,
    enable_autostart_once,
)
from .tray import run_tray, show_error
from .update import apply_update, stop_for_update, update_watch, updates_enabled


def _server(settings, bind: str) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            app,
            host=bind,
            port=settings.port,
            reload=False,
            access_log=False,
            log_config=None,
        )
    )


def _health_host(bind: str) -> str:
    if bind in {"0.0.0.0", "::", "localhost"}:
        return "127.0.0.1"
    return bind


def _existing_helper_healthy(settings, bind: str) -> bool:
    url = f"http://{_health_host(bind)}:{settings.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _serve_until_stop(settings, bind: str, stop: threading.Event, holder: list) -> None:
    backoff = 1.0
    while not stop.is_set():
        server = _server(settings, bind)
        holder[:] = [server]
        try:
            server.run()
        except Exception:
            logging.exception("http server crashed")
        if stop.is_set():
            break
        if getattr(server, "should_exit", False):
            break
        logging.warning("http server stopped; restarting in %.0fs", backoff)
        if stop.wait(backoff):
            break
        backoff = min(backoff * 2, 30.0)


def main() -> None:
    multiprocessing.freeze_support()
    if len(sys.argv) >= 2 and sys.argv[1] == "--apply-update":
        if len(sys.argv) not in (4, 5):
            raise SystemExit("usage: TimeslipsHelper --apply-update <downloaded> <dest> [parent-pid]")
        parent = int(sys.argv[4]) if len(sys.argv) == 5 else None
        apply_update(sys.argv[2], sys.argv[3], parent)
        return
    frozen = getattr(sys, "frozen", False)
    if frozen:
        configure_file_logging()
    settings = load_settings()
    if not acquire_single_instance():
        try:
            bind = resolve_bind(settings)
        except ValueError:
            bind = "127.0.0.1"
        if _existing_helper_healthy(settings, bind):
            raise SystemExit(0)
        show_error("Timeslips helper is already running.")
        raise SystemExit(0)
    prepared = configure_first_run(settings)
    if prepared is None:
        show_error("Choose the Timeslips database (MAIN.FDB) to continue.")
        raise SystemExit(1)
    settings = prepared
    try:
        bind = resolve_bind(settings)
    except ValueError as exc:
        show_error(str(exc))
        raise SystemExit(str(exc)) from exc
    if not settings.token:
        token = secrets.token_hex(24)
        os.environ["TIMESLIPS_TOKEN"] = token
        persist_running_token(token)
        get_settings.cache_clear()
        settings = load_settings()
        logging.info("generated helper token")
    else:
        persist_running_token(settings.token)
    logging.info(
        "listening on %s:%s lan=%s write_backend=%s production_blocked=%s",
        bind,
        settings.port,
        settings.lan,
        settings.write_backend,
        settings.production_blocked,
    )
    if frozen:
        enable_autostart_once()
        if settings.lan:
            exe = frozen_exe_path()
            if exe is not None:
                ensure_private_firewall(exe)

    stop = threading.Event()
    holder: list = []
    request_exit = threading.Event()
    database_down = threading.Event()

    def on_database(reachable: bool, reason: str | None) -> None:
        if reachable:
            database_down.clear()
            return
        if not database_down.is_set():
            logging.info("database unavailable (%s); checking for a helper update", reason or "down")
        database_down.set()

    threading.Thread(
        target=database_watch,
        args=(settings, stop),
        kwargs={"on_result": on_database},
        daemon=True,
    ).start()
    if settings.lan:
        threading.Thread(target=advertise, args=(settings, stop), daemon=True).start()
    worker = threading.Thread(
        target=_serve_until_stop,
        args=(settings, bind, stop, holder),
        daemon=True,
    )

    def shutdown() -> None:
        stop.set()
        request_exit.set()
        if holder:
            holder[0].should_exit = True

    def exit_for_update() -> None:
        stop_for_update(shutdown)

    if updates_enabled():
        threading.Thread(
            target=update_watch,
            args=(stop, exit_for_update, database_down),
            daemon=True,
        ).start()

    no_tray = os.environ.get("TIMESLIPS_NO_TRAY") == "1"
    if no_tray or (
        not frozen
        and _missing_tray_deps()
    ):
        _serve_until_stop(settings, bind, stop, holder)
        return

    worker.start()
    deadline = time.time() + 2
    while time.time() < deadline and not _existing_helper_healthy(settings, bind):
        time.sleep(0.1)
    if not worker.is_alive():
        show_error(
            "Timeslips helper could not start. Check %LOCALAPPDATA%\\TimeslipsHelper\\helper.log."
        )
        raise SystemExit(1)

    try:
        run_tray(settings, on_stop=shutdown, request_exit=request_exit)
    except Exception as exc:
        logging.exception("tray failed")
        show_error(f"Timeslips helper is running, but the tray icon could not start.\n{exc}")
        worker.join()
        return
    shutdown()
    worker.join(5)


def _missing_tray_deps() -> bool:
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return True
    return False


if __name__ == "__main__":
    main()
