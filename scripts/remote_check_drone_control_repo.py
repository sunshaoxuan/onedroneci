#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else "sunshaoxuan/ohr-build-control"
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
        logs = run(c, "docker logs drone-server 2>&1 || true")
        token = extract_token(logs)
        if not token:
            print("no token")
            return 2
        out = run(c, f"curl -sS -H 'Authorization: Bearer {token}' http://127.0.0.1:8080/api/repos/{repo} || true")
        print(out.replace(token, "<redacted>"))
    finally:
        c.close()
    return 0


def extract_token(logs: str) -> str | None:
    for line in logs.splitlines():
        if '"token"' not in line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            m = re.search(r'"token":"([^"]+)"', line)
            if m:
                return m.group(1)
            continue
        token = data.get("token")
        if isinstance(token, str) and token:
            return token
    return None


def run(client: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = client.exec_command("bash -lc " + quote(command), timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"remote command failed ({code})\n{out}\n{err}")
    return out + (("\n--- STDERR ---\n" + err) if err else "")


def quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
