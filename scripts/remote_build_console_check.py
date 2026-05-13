#!/usr/bin/env python3
"""Redact build-console logs and inspect the requested backend branch."""
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
        script = r"""set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import os
import re
token = ""
env = Path("/opt/ohr-build-console/build-console.env")
if env.is_file():
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("OHR_BACK_GIT_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"')
for p in Path("/opt/ohr-build-console/builds").glob("*/build.log"):
    text = p.read_text(encoding="utf-8", errors="replace")
    if token:
        text = text.replace(token, "<redacted>")
    text = re.sub(r"https://oauth2:[^@\s'\"<>]+@", "https://oauth2:<redacted>@", text)
    p.write_text(text, encoding="utf-8")
PY
cd /root/ohr-back
echo "=== ls-remote exact branch ==="
git ls-remote --heads origin release_02060507152438 || true
echo "=== local remote branch sample ==="
python3 - <<'PY'
import subprocess
out = subprocess.check_output(["git", "ls-remote", "--heads", "origin"], text=True, stderr=subprocess.STDOUT)
matches = [line for line in out.splitlines() if "release_020605" in line or "02060507152438" in line]
print("\n".join(matches[:80]))
PY
echo "=== current origin ==="
git remote -v | sed 's#oauth2:[^@]*@#oauth2:<redacted>@#g'
"""
        out = run(c, script)
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
