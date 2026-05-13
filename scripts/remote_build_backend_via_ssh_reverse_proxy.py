#!/usr/bin/env python3
"""Try to build /root/ohr-back on the Ubuntu VM through the host CONNECT proxy."""
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

REMOTE_PORT = 3130
HOST_PROXY = ("127.0.0.1", 3128)

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


def build_remote(git_username: str | None, git_token: str | None) -> str:
    settings_setup = ""
    settings_arg = ""
    if git_token:
        username = git_username or "oauth2"
        settings_setup = f"""mkdir -p /root/.m2
cat > /root/.m2/ohr-ci-settings.xml <<'MAVEN_SETTINGS'
<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <servers>
    <server>
      <id>onehr</id>
      <username>{username}</username>
      <password>{git_token}</password>
    </server>
  </servers>
</settings>
MAVEN_SETTINGS
chmod 600 /root/.m2/ohr-ci-settings.xml
"""
        settings_arg = "-s /root/.m2/ohr-ci-settings.xml "

    return f"""set -euo pipefail
cd /root/ohr-back
export HTTP_PROXY=http://127.0.0.1:{REMOTE_PORT}
export HTTPS_PROXY=http://127.0.0.1:{REMOTE_PORT}
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export MAVEN_OPTS="-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort={REMOTE_PORT} -Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort={REMOTE_PORT} -Dhttp.nonProxyHosts=localhost|127.0.0.1 -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true"
{settings_setup}

echo "=== versions ==="
java -version
javac -version
git --version
if command -v mvn >/dev/null 2>&1; then mvn -version; else echo "mvn_missing"; fi
if [ -x ./mvnw ]; then echo "mvnw_present"; fi

echo "=== repo ==="
git remote -v
git rev-parse --abbrev-ref HEAD
git rev-parse --short HEAD
python3 - <<'PY'
from pathlib import Path
root = Path('/root/ohr-back')
for name in ['pom.xml', 'mvnw', 'build.gradle', 'settings.gradle', 'README.md', '.drone.yml']:
    p = root / name
    if p.exists():
        print(f"FOUND {{name}} size={{p.stat().st_size}}")
PY

echo "=== build ==="
if [ -x ./mvnw ]; then
  ./mvnw {settings_arg}-B -DskipTests -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true package
elif command -v mvn >/dev/null 2>&1; then
  mvn {settings_arg}-B -DskipTests -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true package
else
  echo "ERROR: Maven is not installed and ./mvnw is not executable" >&2
  exit 127
fi

echo "=== artifacts ==="
python3 - <<'PY'
from pathlib import Path
for p in Path('/root/ohr-back').rglob('target/*.jar'):
    print(p)
PY
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
        threading.Thread(target=forward_loop, args=(transport, stop), daemon=True).start()
        time.sleep(1)
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=3600)
        stdin.write(build_remote(git_username, git_token).encode("utf-8"))
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

    (ROOT / "_remote_build_backend_stdout.txt").write_text(out, encoding="utf-8")
    (ROOT / "_remote_build_backend_stderr.txt").write_text(err, encoding="utf-8")
    sys.stdout.write(out)
    sys.stderr.write(err)
    print(f"exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
