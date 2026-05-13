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


def main() -> int:
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
        script = r"""set -e
cd /root/ohr-back
echo '=== package.zip ==='
ls -lh package.zip 2>/dev/null || true
echo '=== package.zip listing ==='
unzip -l package.zip 2>/dev/null | sed -n '1,120p' || true
echo '=== standalone target ==='
ls -lh standalone/target 2>/dev/null || true
echo '=== large target jars ==='
find . -path '*/target/*.jar' -type f -printf '%s %p\n' 2>/dev/null | sort -nr | sed -n '1,40p'
echo '=== collect scripts ==='
for f in collect-ohr.sh collect-standalone.sh collect-pkg.sh; do
  echo "--- $f ---"
  sed -n '1,220p' "$f" 2>/dev/null || true
done
"""
        out = run(c, script)
        (ROOT / "_remote_inspect_ohr_package.txt").write_text(out, encoding="utf-8")
        print(out)
    finally:
        c.close()
    return 0


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
