#!/usr/bin/env python3
"""一次性：SSH 上诊断 DNS/网络，必要时写入备用 DNS 并重试 phase1。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402

FIX_AND_RETRY = r"""set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

echo '=== resolv / resolvectl ==='
cat /etc/resolv.conf || true
resolvectl status 2>/dev/null || true

echo '=== connectivity ==='
ping -c1 -W2 223.5.5.5 || true
ping -c1 -W2 8.8.8.8 || true
getent hosts packages.adoptium.net || true

# 若完全无法解析外网，为 systemd-resolved 追加公共 DNS（不破坏已有片段）
if [ ! -f /etc/systemd/resolved.conf.d/99-fallback-dns.conf ]; then
  mkdir -p /etc/systemd/resolved.conf.d
  cat > /etc/systemd/resolved.conf.d/99-fallback-dns.conf << 'EOF'
[Resolve]
DNS=223.5.5.5 8.8.8.8
FallbackDNS=1.1.1.1
EOF
  systemctl restart systemd-resolved || true
fi

sleep 2
getent hosts packages.adoptium.net || true

apt-get update -y
apt-get install -y git wget curl ca-certificates gnupg apt-transport-https

KEY=/etc/apt/trusted.gpg.d/adoptium.gpg
wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --batch --yes --dearmor -o "$KEY"
LIST=/etc/apt/sources.list.d/adoptium.list
. /etc/os-release
echo "deb https://packages.adoptium.net/artifactory/deb ${VERSION_CODENAME} main" > "$LIST"
apt-get update -y
apt-get install -y temurin-24-jdk

java -version
javac -version
git --version

CLONE_DIR=/root/ohr-back
REPO_URL='https://upds7.ujob100.com/ohr/ohr-back.git'
if [ -d "$CLONE_DIR/.git" ]; then
  git -C "$CLONE_DIR" remote set-url origin "$REPO_URL" || true
  git -C "$CLONE_DIR" fetch --all --prune
  git -C "$CLONE_DIR" pull --ff-only || git -C "$CLONE_DIR" pull
else
  rm -rf "$CLONE_DIR"
  git clone "$REPO_URL" "$CLONE_DIR"
fi
echo "OK: $CLONE_DIR"
ls -la "$CLONE_DIR" | head -n 20
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
        password=pwd or None,
        look_for_keys=not bool(pwd),
        allow_agent=not bool(pwd),
        timeout=30,
    )
    try:
        t = c.get_transport()
        if t:
            t.set_keepalive(30)
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=60 * 45)
        stdin.write(FIX_AND_RETRY.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
    finally:
        c.close()

    log = ROOT / "_remote_fix_retry_log.txt"
    log.write_text(out + "\n--- STDERR ---\n" + err, encoding="utf-8")
    print(out)
    print(err, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
