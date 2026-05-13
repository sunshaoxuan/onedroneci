#!/usr/bin/env python3
"""Clone from the VM through an SSH reverse tunnel to the host CONNECT proxy."""
from __future__ import annotations

import os
import select
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402

REMOTE_PORT = 3129
HOST_PROXY = ("127.0.0.1", 3128)
DEFAULT_REPO_URL = "https://upds7.ujob100.com/ohr/ohr-back.git"


def load_git_access_env() -> None:
    path = ROOT / "git-access.env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def build_remote_clone(repo_url: str, git_username: str | None, git_token: str | None) -> str:
    askpass_setup = ""
    askpass_env = ""
    if git_token:
        username = git_username or "oauth2"
        askpass_setup = f"""cat > /tmp/ohr-git-askpass.sh <<'ASKPASS'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\\n' {username!r} ;;
  *Password*) printf '%s\\n' {git_token!r} ;;
  *) printf '\\n' ;;
esac
ASKPASS
chmod 700 /tmp/ohr-git-askpass.sh
"""
        askpass_env = "export GIT_ASKPASS=/tmp/ohr-git-askpass.sh\n"

    return f"""set -euo pipefail
export GIT_TERMINAL_PROMPT=0
export HTTPS_PROXY=http://127.0.0.1:{REMOTE_PORT}
export HTTP_PROXY=http://127.0.0.1:{REMOTE_PORT}
export https_proxy="$HTTPS_PROXY"
export http_proxy="$HTTP_PROXY"
{askpass_env}

python3 - <<'PY'
import socket
s = socket.create_connection(("127.0.0.1", {REMOTE_PORT}), timeout=8)
s.close()
print("reverse_proxy_port_open")
PY

curl -x "$HTTPS_PROXY" -vkI --connect-timeout 20 --max-time 60 https://upds7.ujob100.com/ || true
{askpass_setup}
rm -rf /root/ohr-back
git -c http.proxy="$HTTPS_PROXY" \
    -c https.proxy="$HTTPS_PROXY" \
    -c http.sslVerify=false \
    -c http.lowSpeedLimit=1 \
    -c http.lowSpeedTime=60 \
    clone {repo_url!r} /root/ohr-back
rm -f /tmp/ohr-git-askpass.sh
git -C /root/ohr-back remote -v
ls -la /root/ohr-back | head -n 30
"""


def bridge(chan: paramiko.Channel, dest: tuple[str, int]) -> None:
    try:
        sock = socket.create_connection(dest, timeout=20)
    except OSError:
        chan.close()
        return
    with sock, chan:
        while True:
            readable, _, _ = select.select([sock, chan], [], [], 60)
            if not readable:
                return
            for src in readable:
                dst = chan if src is sock else sock
                data = src.recv(65536)
                if not data:
                    return
                dst.sendall(data)


def forward_loop(transport: paramiko.Transport, stop: threading.Event) -> None:
    while not stop.is_set() and transport.is_active():
        chan = transport.accept(1.0)
        if chan is None:
            continue
        threading.Thread(target=bridge, args=(chan, HOST_PROXY), daemon=True).start()


def main() -> int:
    load_vm_access_env_files()
    load_git_access_env()
    s = Settings.from_env()
    pwd = os.environ.get("HV_VM_SSH_PASSWORD")
    repo_url = os.environ.get("OHR_BACK_CLONE_URL", DEFAULT_REPO_URL)
    git_username = os.environ.get("OHR_BACK_GIT_USERNAME")
    git_token = os.environ.get("OHR_BACK_GIT_TOKEN")
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

    stop = threading.Event()
    try:
        transport = c.get_transport()
        if transport is None:
            raise RuntimeError("no SSH transport")
        transport.set_keepalive(15)
        transport.request_port_forward("127.0.0.1", REMOTE_PORT)
        t = threading.Thread(target=forward_loop, args=(transport, stop), daemon=True)
        t.start()
        time.sleep(1)

        stdin, stdout, stderr = c.exec_command("bash -s", timeout=900)
        stdin.write(build_remote_clone(repo_url, git_username, git_token).encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    finally:
        stop.set()
        try:
            tr = c.get_transport()
            if tr is not None:
                tr.cancel_port_forward("127.0.0.1", REMOTE_PORT)
        except Exception:
            pass
        c.close()

    (ROOT / "_remote_reverse_clone_stdout.txt").write_text(out, encoding="utf-8")
    (ROOT / "_remote_reverse_clone_stderr.txt").write_text(err, encoding="utf-8")
    sys.stdout.write(out)
    sys.stderr.write(err)
    print(f"exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
