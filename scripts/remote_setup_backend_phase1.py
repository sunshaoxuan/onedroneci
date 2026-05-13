#!/usr/bin/env python3
"""
在 Ubuntu 目标机上安装：git、Eclipse Temurin JDK 24，并克隆 ohr-back 仓库。
从本机运行；凭据读取 hv-vm-tools 目录下的 vm-access.env（或环境变量）。

若目标机 DNS 不可用（systemd-resolved 正常但仍无法解析），请改用：
  python scripts/remote_backend_phase1_hosts_fallback.py
该脚本在本机解析域名 IP 后写入 /etc/hosts，并暂移 docker/nodesource 的 apt 列表以减少失败源。

用法（在 hv-vm-tools 目录下）:
  pip install paramiko
  python scripts/remote_setup_backend_phase1.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REMOTE_SCRIPT = r"""set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y git wget curl ca-certificates gnupg apt-transport-https

KEY=/etc/apt/trusted.gpg.d/adoptium.gpg
if [ ! -f "$KEY" ]; then
  wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --batch --yes --dearmor -o "$KEY"
fi
LIST=/etc/apt/sources.list.d/adoptium.list
if [ ! -f "$LIST" ]; then
  . /etc/os-release
  echo "deb https://packages.adoptium.net/artifactory/deb ${VERSION_CODENAME} main" > "$LIST"
fi
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
echo "OK: repo at $CLONE_DIR"
ls -la "$CLONE_DIR" | head
"""


def main() -> int:
    try:
        import paramiko
    except ImportError:
        print("请先安装: pip install paramiko", file=sys.stderr)
        return 1

    os.chdir(ROOT)
    from hv_vm_tools.config import Settings, load_vm_access_env_files

    load_vm_access_env_files()
    s = Settings.from_env()
    if not s.ssh_user:
        print("缺少 HV_VM_SSH_USER", file=sys.stderr)
        return 1

    pwd = os.environ.get("HV_VM_SSH_PASSWORD")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=pwd or None,
        look_for_keys=not bool(pwd),
        allow_agent=not bool(pwd),
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    try:
        t = client.get_transport()
        if t:
            t.set_keepalive(30)
        stdin, stdout, stderr = client.exec_command(
            "bash -s",
            timeout=60 * 30,
        )
        stdin.write(REMOTE_SCRIPT.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
    finally:
        client.close()

    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
