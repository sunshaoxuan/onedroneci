#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


REMOTE = r"""set -eux
ip addr show eth0 || true
ip route || true
ping -c 1 -W 2 192.168.250.1 || true
python3 - <<'PY'
import socket, time
for host, port in [("192.168.250.1", 3128), ("192.168.250.1", 22)]:
    start = time.time()
    try:
        s = socket.create_connection((host, port), timeout=6)
        s.close()
        print(host, port, "OPEN", round(time.time() - start, 2))
    except Exception as exc:
        print(host, port, "FAIL", type(exc).__name__, str(exc), round(time.time() - start, 2))
PY
"""


def main() -> int:
    load_vm_access_env_files()
    s = Settings.from_env()
    pwd = os.environ.get("HV_VM_SSH_PASSWORD")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=pwd,
        look_for_keys=False,
        allow_agent=False,
        timeout=30,
    )
    try:
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=60)
        stdin.write(REMOTE.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    finally:
        c.close()

    (ROOT / "_remote_vm_to_host_test_stdout.txt").write_text(out, encoding="utf-8")
    (ROOT / "_remote_vm_to_host_test_stderr.txt").write_text(err, encoding="utf-8")
    sys.stdout.write(out)
    sys.stderr.write(err)
    print(f"exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
