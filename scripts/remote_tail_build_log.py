#!/usr/bin/env python3
"""SSH 查看远端 build-console 某次构建日志末尾。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def main() -> int:
    bid = sys.argv[1] if len(sys.argv) > 1 else ""
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    if not bid:
        print("usage: remote_tail_build_log.py <build_id> [lines]", file=sys.stderr)
        return 2
    load_vm_access_env_files()
    s = Settings.from_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=os.environ.get("HV_VM_SSH_PASSWORD"),
        look_for_keys=False,
        allow_agent=False,
        timeout=45,
    )
    try:
        _, o, _ = c.exec_command(
            f"bash -lc 'tail -n {n} /opt/ohr-build-console/builds/{bid}/build.log'",
            timeout=60,
        )
        sys.stdout.buffer.write(o.read())
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
