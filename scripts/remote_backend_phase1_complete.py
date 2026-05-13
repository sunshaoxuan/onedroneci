#!/usr/bin/env python3
"""
在 Ubuntu 上完成：DNS 修复（多策略）→ Temurin JDK 24 → git → 克隆 ohr-back。
日志固定写入 hv-vm-tools/_subagent_remote_phase1.log
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "_subagent_remote_phase1.log"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402

REMOTE = r"""set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
export GIT_TERMINAL_PROMPT=0

log() { echo "[phase1] $*"; }

iface="$(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}' | head -1)"
log "default iface=$iface"

echo '========== BEFORE =========='
cat /etc/resolv.conf || true
resolvectl status 2>/dev/null || true

# 策略 A：对默认网卡直接指定 DNS（比仅 drop-in 更常生效）
if [ -n "$iface" ]; then
  resolvectl dns "$iface" 223.5.5.5 8.8.8.8 2>/dev/null || true
  resolvectl domain "$iface" "~." 2>/dev/null || true
fi

# 策略 B：systemd-resolved 全局补充
mkdir -p /etc/systemd/resolved.conf.d
cat > /etc/systemd/resolved.conf.d/99-fallback-dns.conf << 'EOF'
[Resolve]
DNS=223.5.5.5 8.8.8.8
FallbackDNS=1.1.1.1
EOF
systemctl restart systemd-resolved || true
sleep 2
resolvectl flush-caches 2>/dev/null || true

echo '========== AFTER DNS TWEAK =========='
resolvectl status 2>/dev/null || true
getent hosts mirrors.aliyun.com || true
getent hosts packages.adoptium.net || true

apt-get update -y
apt-get install -y git wget curl ca-certificates gnupg apt-transport-https

# 清理可能损坏/空的 adoptium key
rm -f /etc/apt/trusted.gpg.d/adoptium.gpg
wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --batch --yes --dearmor -o /etc/apt/trusted.gpg.d/adoptium.gpg
. /etc/os-release
echo "deb https://packages.adoptium.net/artifactory/deb ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/adoptium.list
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

echo '========== /root/ohr-back =========='
ls -la "$CLONE_DIR" | head -n 25
log DONE
"""


def main() -> int:
    load_vm_access_env_files()
    s = Settings.from_env()
    pwd = os.environ.get("HV_VM_SSH_PASSWORD")

    lines: list[str] = []

    def tee(msg: str) -> None:
        lines.append(msg)
        print(msg, flush=True)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    tee(f"Connecting {s.ssh_user}@{s.vm_host}:{s.ssh_port} ...")
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=pwd or None,
        look_for_keys=not bool(pwd),
        allow_agent=not bool(pwd),
        timeout=45,
        banner_timeout=45,
        auth_timeout=45,
    )
    code = 1
    try:
        t = c.get_transport()
        if t:
            t.set_keepalive(25)
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=60 * 60)
        stdin.write(REMOTE.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        tee(out)
        tee("--- STDERR ---")
        tee(err)
        tee(f"--- EXIT {code} ---")
    except Exception as e:
        tee(f"EXCEPTION: {e!r}")
        code = 1
    finally:
        c.close()

    LOG.write_text("\n".join(lines), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
