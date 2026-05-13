#!/usr/bin/env python3
"""在 Ubuntu CI 上生成 ohr-back 的 package.zip（collect-ohr.sh）。

分支：环境变量 OHR_BACK_BRANCH，或命令行 --branch=xxx / --branch xxx。
未设置时默认 release_02060507152438（测试用，可自行改 git-access.env）。
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def load_git_access_env() -> None:
    p = ROOT / "git-access.env"
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="在 Ubuntu 上按分支打包 ohr-back -> package.zip")
    p.add_argument(
        "--branch",
        dest="branch",
        default=None,
        help="Git 分支名（默认读 OHR_BACK_BRANCH，再默认 release_02060507152438）",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    load_vm_access_env_files()
    load_git_access_env()
    branch = (
        args.branch
        or os.environ.get("OHR_BACK_BRANCH")
        or "release_02060507152438"
    )
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        print("分支名仅允许字母、数字、._/-", file=sys.stderr)
        return 2

    user = os.environ.get("MAVEN_ONEHR_USERNAME", "admin")
    pwd = os.environ.get("MAVEN_ONEHR_PASSWORD", "")
    if not pwd:
        raise RuntimeError("MAVEN_ONEHR_PASSWORD is required")
    git_token = os.environ.get("OHR_BACK_GIT_TOKEN", "")

    set_origin = ""
    if git_token:
        u = "https://oauth2:" + urllib.parse.quote(git_token, safe="") + "@upds7.ujob100.com/ohr/ohr-back.git"
        set_origin = "git remote set-url origin " + shlex.quote(u)

    bq = shlex.quote(branch)

    s = Settings.from_env()
    pw = os.environ.get("HV_VM_SSH_PASSWORD")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=pw,
        look_for_keys=False,
        allow_agent=False,
        timeout=45,
    )
    settings_xml = f"""<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <servers>
    <server><id>onehr</id><username>{_xml_esc(user)}</username><password>{_xml_esc(pwd)}</password></server>
    <server><id>onehr-releases</id><username>{_xml_esc(user)}</username><password>{_xml_esc(pwd)}</password></server>
    <server><id>onehr-snapshots</id><username>{_xml_esc(user)}</username><password>{_xml_esc(pwd)}</password></server>
  </servers>
</settings>
"""
    remote = f"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qy
apt-get install -y zip

# 约 1.7GiB 物理内存：加临时 swap，避免大模块 javac/Lombok OOM
if ! swapon --show | grep -q swap_ci_build; then
  if [ ! -f /swap_ci_build ]; then
    dd if=/dev/zero of=/swap_ci_build bs=1M count=6144 status=progress
    chmod 600 /swap_ci_build
    mkswap /swap_ci_build
  fi
  swapon /swap_ci_build || true
fi
free -h

mkdir -p /root/.m2
cat > /root/.m2/settings.xml <<'EOF'
{settings_xml}
EOF
chmod 600 /root/.m2/settings.xml
cd /root/ohr-back
{set_origin}
git fetch origin {bq}
git checkout -f {bq}
git rev-parse --short HEAD
export MAVEN_OPTS="-Xmx2048m -Xms256m -XX:+UseG1GC \\
  -Dmaven.wagon.http.ssl.insecure=true \\
  -Dmaven.wagon.http.ssl.allowall=true \\
  -Dmaven.wagon.http.ssl.ignore.validity.dates=true \\
  -Dmaven.compiler.fork=true \\
  -Dmaven.compiler.meminitial=256m \\
  -Dmaven.compiler.maxmem=1536m"
if [ -x ./collect-ohr.sh ]; then
  bash ./collect-ohr.sh
else
  mvn -s /root/.m2/settings.xml -B -DskipTests clean package
  zip -r package.zip $(find . -path '*/target/*.jar' | head -n 50) 2>/dev/null || true
fi
ls -la /root/ohr-back/package.zip
sha256sum /root/ohr-back/package.zip | head -1
"""
    try:
        _, stdout, stderr = c.exec_command(f"bash -lc {_sh_quote(remote)}", timeout=7200)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
    finally:
        c.close()

    log = ROOT / "_remote_collect_package_log.txt"
    log.write_text(out + "\n--- STDERR ---\n" + err + f"\nexit={code}\n", encoding="utf-8")
    print(out)
    print(err, file=sys.stderr)
    print("exit", code)
    return code


def _xml_esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _sh_quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
