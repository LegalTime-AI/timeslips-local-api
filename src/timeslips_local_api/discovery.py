from __future__ import annotations

import ipaddress
import json
import logging
import socket
import subprocess
import sys
import threading

from . import HELPER_VERSION
from .config import Settings

DISCOVER_PORT = 3052
BEACON_INTERVAL_SECONDS = 5


def machine_host_name() -> str:
    name = socket.gethostname().strip().split(".")[0]
    return name[:64] or "timeslips"


def lan_ipv4() -> str | None:
    """Best-effort private IPv4 for the tray address. No packet is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 1))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if not ip or ip.startswith("127."):
        return None
    return ip


def beacon_payload(settings: Settings) -> dict:
    """Announce the helper. Never include the token, paths, or credentials."""
    return {
        "service": "timeslips-local-api",
        "port": settings.port,
        "hostName": machine_host_name(),
        "helperVersion": HELPER_VERSION,
    }


def ipv4_broadcast_addresses() -> list[str]:
    """Subnet broadcasts for each real IPv4 interface. Never raises."""
    try:
        if sys.platform == "win32":
            return _windows_broadcasts()
        if sys.platform.startswith("linux"):
            return _linux_broadcasts()
    except Exception:
        logging.debug("could not list broadcast addresses", exc_info=True)
    return []


def broadcast_destinations() -> list[str]:
    """Limited broadcast plus each subnet broadcast.

    255.255.255.255 is unreachable on a host with no default route, and some
    networks only deliver the subnet broadcast. Both are attempted.
    """
    dests = ["255.255.255.255"]
    for addr in ipv4_broadcast_addresses():
        if addr not in dests:
            dests.append(addr)
    return dests


def _linux_broadcasts() -> list[str]:
    try:
        out = subprocess.check_output(["ip", "-4", "-j", "addr"], text=True, timeout=5)
        data = json.loads(out)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    found: list[str] = []
    if not isinstance(data, list):
        return found
    for iface in data:
        if not isinstance(iface, dict):
            continue
        for addr in iface.get("addr_info") or []:
            if not isinstance(addr, dict) or addr.get("family") != "inet":
                continue
            local = addr.get("local")
            prefix = addr.get("prefixlen")
            if not isinstance(local, str) or not isinstance(prefix, int):
                continue
            try:
                iface_net = ipaddress.IPv4Interface(f"{local}/{prefix}")
            except ValueError:
                continue
            if iface_net.ip.is_loopback:
                continue
            bcast = str(iface_net.network.broadcast_address)
            if bcast not in found:
                found.append(bcast)
    return found


def _windows_broadcasts() -> list[str]:
    script = (
        "Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | "
        "ForEach-Object { $ips=$_.IPAddress; $masks=$_.IPSubnet; "
        "if ($null -eq $ips) { return }; "
        "for ($i=0; $i -lt $ips.Length; $i++) { "
        "if ($ips[$i] -match '^[0-9.]+$') { Write-Output ($ips[$i] + ',' + $masks[$i]) } } }"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            creationflags=0x08000000,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[str] = []
    for line in out.splitlines():
        if "," not in line:
            continue
        ip, mask = line.strip().split(",", 1)
        try:
            iface = ipaddress.IPv4Interface(f"{ip}/{mask}")
        except ValueError:
            continue
        if iface.ip.is_loopback:
            continue
        addr = str(iface.network.broadcast_address)
        if addr not in found:
            found.append(addr)
    return found


def helper_http_url(settings: Settings) -> str:
    if settings.lan:
        host = lan_ipv4() or "127.0.0.1"
    else:
        host = settings.bind if settings.bind != "0.0.0.0" else "127.0.0.1"
        if host == "localhost":
            host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def advertise(settings: Settings, stop: threading.Event) -> None:
    payload = json.dumps(beacon_payload(settings)).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not stop.is_set():
            sent = False
            for dest in broadcast_destinations():
                try:
                    sock.sendto(payload, (dest, DISCOVER_PORT))
                    sent = True
                except OSError:
                    continue
            if not sent:
                logging.warning("discovery beacon failed")
            if stop.wait(BEACON_INTERVAL_SECONDS):
                return
    finally:
        sock.close()
