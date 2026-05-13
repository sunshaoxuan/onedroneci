from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class PingResult:
    host: str
    ok: bool
    detail: str


def ping_host(host: str, count: int = 2) -> PingResult:
    """ICMP 探测（Windows: ping -n）。"""
    if sys.platform == "win32":
        cmd = ["ping", "-n", str(count), host]
    else:
        cmd = ["ping", "-c", str(count), host]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30 + count * 5,
            check=False,
        )
        ok = p.returncode == 0
        tail = (p.stdout or p.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit {p.returncode}"
        return PingResult(host, ok, detail)
    except subprocess.TimeoutExpired:
        return PingResult(host, False, "timeout")
    except OSError as e:
        return PingResult(host, False, str(e))


def tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False
