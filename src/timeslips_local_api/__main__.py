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
from .config import load_settings, persist_running_token
from .health import database_watch
from .runtime import acquire_single_instance, configure_file_logging, enable_autostart_once
from .tray import run_tray, show_error


def _server(settings) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.bind,
            port=settings.port,
            reload=False,
            access_log=False,
            log_config=None,
        )
    )


def _existing_helper_healthy(settings) -> bool:
    url = f"http://{settings.bind}:{settings.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _serve_until_stop(settings, stop: threading.Event, holder: list) -> None:
    backoff = 1.0
    while not stop.is_set():
        server = _server(settings)
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
    frozen = getattr(sys, "frozen", False)
    if frozen:
        configure_file_logging()
    settings = load_settings()
    if settings.bind not in {"127.0.0.1", "localhost", "::1"}:
        show_error("TIMESLIPS_BIND must be a loopback address.")
        raise SystemExit("TIMESLIPS_BIND must be a loopback address")
    if not acquire_single_instance():
        if _existing_helper_healthy(settings):
            raise SystemExit(0)
        show_error("Timeslips helper is already running.")
        raise SystemExit(0)
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
        "listening on %s:%s write_backend=%s production_blocked=%s",
        settings.bind,
        settings.port,
        settings.write_backend,
        settings.production_blocked,
    )
    if frozen:
        enable_autostart_once()

    stop = threading.Event()
    holder: list = []
    threading.Thread(target=database_watch, args=(settings, stop), daemon=True).start()
    worker = threading.Thread(
        target=_serve_until_stop,
        args=(settings, stop, holder),
        daemon=True,
    )
    no_tray = os.environ.get("TIMESLIPS_NO_TRAY") == "1"
    if no_tray or (
        not frozen
        and _missing_tray_deps()
    ):
        _serve_until_stop(settings, stop, holder)
        return

    worker.start()
    deadline = time.time() + 2
    while time.time() < deadline and not _existing_helper_healthy(settings):
        time.sleep(0.1)
    if not worker.is_alive():
        show_error(
            "Timeslips helper could not start. Check %LOCALAPPDATA%\\TimeslipsHelper\\helper.log."
        )
        raise SystemExit(1)

    def shutdown() -> None:
        stop.set()
        if holder:
            holder[0].should_exit = True

    try:
        run_tray(settings, on_stop=shutdown)
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
