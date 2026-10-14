"""One-click pairing: a laptop asks, someone at the Timeslips computer clicks Allow.

LegalTime on another computer calls ``POST /pair``. The helper shows a Yes/No
box on this computer. Yes returns the bearer token, so nobody copies or types
it. Only private-network callers can ask, one box shows at a time, and a
computer that was refused waits a few minutes before it can ask again.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import sys
import threading
import time
from typing import Callable

from .errors import ApiError

PROMPT_SECONDS = 120
DENY_COOLDOWN_SECONDS = 300

_prompt_lock = threading.Lock()
_denied: dict[str, float] = {}

Asker = Callable[[str, int], bool | None]


def clean_label(value: object, fallback: str) -> str:
    """Names shown in the box: letters, digits and a little punctuation only."""
    text = value if isinstance(value, str) else ""
    text = re.sub(r"[^\w .'@-]", "", text, flags=re.UNICODE).strip()[:64]
    return text or fallback


def caller_is_private(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10")


def pair_message(user: str, computer: str) -> str:
    who = f"{user} on {computer}" if user != computer else computer
    return (
        f"Allow {who} to send time entries to Timeslips on this computer?\n\n"
        "Click Yes only if you know this person. You only need to do this once per computer."
    )


def ask_windows(message: str, seconds: int) -> bool | None:
    """Topmost Yes/No box. None when nobody answered in time."""
    if sys.platform != "win32":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    # MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2 | MB_SYSTEMMODAL | MB_SETFOREGROUND | MB_TOPMOST
    flags = 0x4 | 0x20 | 0x100 | 0x1000 | 0x10000 | 0x40000
    try:
        result = user32.MessageBoxTimeoutW(None, message, "Timeslips helper", flags, 0, seconds * 1000)
    except AttributeError:
        result = user32.MessageBoxW(None, message, "Timeslips helper", flags)
    if result == 6:
        return True
    if result == 7:
        return False
    return None


def request_pairing(
    *,
    token: str,
    lan: bool,
    client_host: str | None,
    computer: object,
    user: object,
    ask: Asker = ask_windows,
    now: Callable[[], float] = time.monotonic,
) -> str:
    """Return the token after a Yes at this computer, or raise ApiError."""
    if not lan:
        raise ApiError(403, "Sharing with other computers is off on the Timeslips computer.")
    if not caller_is_private(client_host):
        raise ApiError(403, "Only computers on the office network can connect.")
    if not token:
        raise ApiError(503, "The Timeslips helper is still starting. Try again in a minute.")
    computer_label = clean_label(computer, "another computer")
    user_label = clean_label(user, computer_label)
    key = f"{client_host}|{computer_label.lower()}"
    refused_at = _denied.get(key)
    if refused_at is not None and now() - refused_at < DENY_COOLDOWN_SECONDS:
        raise ApiError(403, "This computer was not allowed. Ask again in a few minutes.")
    if not _prompt_lock.acquire(blocking=False):
        raise ApiError(409, "The Timeslips computer is already asking about another computer. Try again in a minute.")
    try:
        logging.info("pairing request from %s", computer_label)
        answer = ask(pair_message(user_label, computer_label), PROMPT_SECONDS)
    finally:
        _prompt_lock.release()
    if answer is True:
        _denied.pop(key, None)
        logging.info("pairing allowed for %s", computer_label)
        return token
    if answer is False:
        _denied[key] = now()
        logging.info("pairing refused for %s", computer_label)
        raise ApiError(403, "The Timeslips computer said no.")
    raise ApiError(408, "Nobody answered on the Timeslips computer. Click Connect again while someone is there.")


def reset_for_tests() -> None:
    _denied.clear()
