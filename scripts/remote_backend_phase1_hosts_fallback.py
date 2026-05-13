#!/usr/bin/env python3
"""
在无可用 DNS 的 Ubuntu 上：写入静态 /etc/hosts、暂移 docker/nodesource 的 apt 列表，
安装 Temurin 24 JDK、git，并克隆 ohr-back。
IP 由本机解析得到（与 VM 同网时可经 NAT 出网访问 HTTPS）。
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "_subagent_remote_phase1_hosts.log"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def _first_ipv4(host: str) -> str:
    infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    for fam, _, _, _, sa in infos:
        if fam == socket.AF_INET:
            return sa[0]
    raise RuntimeError(f"no IPv4 for {host}")


def main() -> int:
    load_vm_access_env_files()
    s = Settings.from_env()
    pwd = os.environ.get("HV_VM_SSH_PASSWORD")

    adoptium_ip = _first_ipv4("packages.adoptium.net")
    aliyun_ip = _first_ipv4("mirrors.aliyun.com")
    git_ip = _first_ipv4("upds7.ujob100.com")

    # 通过 Python 注入 /etc/hosts 块，避免 shell 引号地狱
    hosts_block = (
        "# hv-vm-tools-static-dns-begin\n"
        f"{adoptium_ip}\tpackages.adoptium.net\n"
        f"{aliyun_ip}\tmirrors.aliyun.com\n"
        f"{git_ip}\tupds7.ujob100.com\n"
        "# hv-vm-tools-static-dns-end\n"
    )

    remote_body = (
        r"""set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
export GIT_TERMINAL_PROMPT=0

MARK_BEGIN="# hv-vm-tools-static-dns-begin"
MARK_END="# hv-vm-tools-static-dns-end"
remove_block() {
  if grep -q "$MARK_BEGIN" /etc/hosts 2>/dev/null; then
    sed -i "/$MARK_BEGIN/,/$MARK_END/d" /etc/hosts
  fi
}
remove_block
cat >> /etc/hosts << 'HOSTSEOF'
"""
        + hosts_block
        + r"""HOSTSEOF

getent hosts packages.adoptium.net
getent hosts mirrors.aliyun.com
getent hosts upds7.ujob100.com

for f in /etc/apt/sources.list.d/docker*.list /etc/apt/sources.list.d/nodesource*.list; do
  [ -f "$f" ] && mv "$f" "$f.bak_hv_vm" || true
done

apt-get update -y
apt-get install -y git wget curl ca-certificates gnupg apt-transport-https

rm -f /etc/apt/trusted.gpg.d/adoptium.gpg
wget -qO- https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /etc/apt/trusted.gpg.d/adoptium.gpg
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
ls -la "$CLONE_DIR" | head -n 20
echo PHASE1_OK
"""
    )

    out_lines: list[str] = [
        f"Resolved: adoptium={adoptium_ip} aliyun={aliyun_ip} git={git_ip}",
    ]

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=pwd or None,
        look_for_keys=not bool(pwd),
        allow_agent=not bool(pwd),
        timeout=45,
    )
    code = 1
    try:
        t = c.get_transport()
        if t:
            t.set_keepalive(20)
        stdin, stdout, stderr = c.exec_command("bash -s", timeout=60 * 45)
        stdin.write(remote_body.encode("utf-8"))
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        out_lines.extend([out, "--- STDERR ---", err, f"--- EXIT {code} ---"])
    except Exception as e:
        out_lines.append(f"EXCEPTION: {e!r}")
        code = 1
    finally:
        c.close()

    text = "\n".join(out_lines)
    LOG.write_text(text, encoding="utf-8")
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
