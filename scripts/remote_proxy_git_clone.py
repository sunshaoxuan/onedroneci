#!/usr/bin/env python3
"""Run git clone on the Ubuntu VM through the host CONNECT proxy."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


REMOTE = r"""set -euxo pipefail
export GIT_TERMINAL_PROMPT=0
export HTTPS_PROXY=http://192.168.250.1:3128
export HTTP_PROXY=http://192.168.250.1:3128
export https_proxy="$HTTPS_PROXY"
export http_proxy="$HTTP_PROXY"

ip route
python3 - <<'PY'
import socket
s = socket.create_connection(("192.168.250.1", 3128), timeout=8)
s.close()
print("proxy_port_open")
PY

curl -x "$HTTPS_PROXY" -vkI --connect-timeout 20 --max-time 60 https://upds7.ujob100.com/ || true
rm -rf /root/ohr-back
git -c http.proxy="$HTTPS_PROXY" \
    -c https.proxy="$HTTPS_PROXY" \
    -c http.lowSpeedLimit=1 \
    -c http.lowSpeedTime=60 \
    clone https://upds7.ujob100.com/ohr/ohr-back.git /root/ohr-back
git -C /root/ohr-back remote -v
ls -la /root/ohr-back | head -n 30
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
        t = c.get_transport()
        if t:
            t.set_keepalive(15)
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=900)
        stdin.write(REMOTE.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    finally:
        c.close()

    (ROOT / "_remote_proxy_clone_stdout.txt").write_text(out, encoding="utf-8")
    (ROOT / "_remote_proxy_clone_stderr.txt").write_text(err, encoding="utf-8")
    sys.stdout.write(out)
    sys.stderr.write(err)
    print(f"exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
