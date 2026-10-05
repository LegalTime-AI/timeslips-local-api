from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from .config import Settings, appdata_dir, persist_lan
from .discovery import helper_http_url
from .health import probe_database
from .runtime import autostart_enabled, release_single_instance, set_autostart

CREATE_NO_WINDOW = 0x08000000


def bundled_icon_path() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidate = meipass / "pack" / "timeslips-icon.png"
        if candidate.is_file():
            return candidate
        return Path(sys.executable).resolve().parent / "timeslips-icon.png"
    return Path(__file__).resolve().parents[2] / "pack" / "timeslips-icon.png"


def copy_text(text: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Set-Clipboard -Value $env:CLIP"],
        env={**os.environ, "CLIP": text},
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )


def show_error(message: str) -> None:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Timeslips helper", 0x10)
    logging.error(message)


def run_tray(settings: Settings, on_stop=None, request_exit: threading.Event | None = None) -> None:
    import pystray
    from PIL import Image

    icon_path = bundled_icon_path()
    image = Image.open(icon_path) if icon_path.is_file() else Image.new("RGB", (64, 64), "#00D639")
    db_label = {"text": "Database: checking"}

    def on_copy(_icon: object, _item: object) -> None:
        if settings.token:
            copy_text(settings.token)

    def on_copy_address(_icon: object, _item: object) -> None:
        copy_text(helper_http_url(settings))

    def on_share(_icon: object, _item: object) -> None:
        enabled = not settings.lan
        persist_lan(enabled)
        if on_stop:
            on_stop()
        release_single_instance()
        env = os.environ.copy()
        env["TIMESLIPS_LAN"] = "1" if enabled else "0"
        cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "timeslips_local_api"]
        kwargs: dict = {"env": env, "cwd": os.getcwd(), "start_new_session": True}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        subprocess.Popen(cmd, **kwargs)
        os._exit(0)

    def on_quit(icon: pystray.Icon, _item: object) -> None:
        if on_stop:
            on_stop()
        icon.stop()

    def on_open_logs(_icon: object, _item: object) -> None:
        folder = appdata_dir()
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)

    def on_autostart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        set_autostart(not item.checked)
        icon.update_menu()

    def database_item(_icon: object) -> str:
        return db_label["text"]

    items: list = [
        pystray.MenuItem(
            lambda _: f"Running on {helper_http_url(settings)}",
            lambda: None,
            enabled=False,
        ),
        pystray.MenuItem(database_item, lambda: None, enabled=False),
    ]
    items.append(
        pystray.MenuItem(
            "Share with other computers",
            on_share,
            checked=lambda _: settings.lan,
        )
    )
    if settings.lan:
        items.append(pystray.MenuItem("Copy address", on_copy_address))
    items.extend(
        [
            pystray.MenuItem("Copy token", on_copy, enabled=bool(settings.token)),
            pystray.MenuItem("Start with Windows", on_autostart, checked=lambda _: autostart_enabled()),
            pystray.MenuItem("Open logs", on_open_logs),
            pystray.MenuItem("Quit", on_quit),
        ]
    )
    menu = pystray.Menu(*items)
    icon = pystray.Icon("TimeslipsHelper", image, "Timeslips helper", menu)
    stop = threading.Event()

    def poll_database() -> None:
        while not stop.wait(30):
            reachable, reason = probe_database(settings)
            db_label["text"] = "Database: OK" if reachable else f"Database: {reason or 'down'}"
            try:
                icon.update_menu()
            except Exception:  # noqa: BLE001
                return

    reachable, reason = probe_database(settings)
    db_label["text"] = "Database: OK" if reachable else f"Database: {reason or 'down'}"
    threading.Thread(target=poll_database, daemon=True).start()

    def watch_exit() -> None:
        if request_exit is None:
            return
        request_exit.wait()
        try:
            icon.stop()
        except Exception:  # noqa: BLE001
            return

    if request_exit is not None:
        threading.Thread(target=watch_exit, daemon=True).start()
    try:
        icon.run()
    finally:
        stop.set()
