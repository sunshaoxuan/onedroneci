#!/usr/bin/env python3
"""SSH 诊断：路由、ping、dig、Docker 状态。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko
from hv_vm_tools.config import Settings, load_vm_access_env_files

CMD = r"""set +e
echo '=== ip route ==='
ip -4 route
echo '=== ping gateway (1s) ==='
GW=$(ip -4 route | awk '/default/ {print $3; exit}')
echo GW=$GW
ping -c2 -W2 "$GW" || true
echo '=== ping 8.8.8.8 ==='
ping -c2 -W2 8.8.8.8 || true
echo '=== dig @223.5.5.5 ==='
command -v dig >/dev/null && dig +time=2 +tries=1 @223.5.5.5 mirrors.aliyun.com +short || echo 'no dig'
echo '=== getent ==='
getent hosts mirrors.aliyun.com || echo fail
getent hosts archive.ubuntu.com || echo fail
echo '=== docker ==='
systemctl is-active docker 2>/dev/null || true
ip link show docker0 2>/dev/null | head -2 || true
"""

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
stdin, stdout, stderr = c.exec_command("bash -s", timeout=120)
stdin.write(CMD.encode("utf-8"))
stdin.channel.shutdown_write()
out = stdout.read().decode()
err = stderr.read().decode()
code = stdout.channel.recv_exit_status()
c.close()
Path(ROOT / "_subagent_net_diag.log").write_text(out + "\nERR\n" + err + f"\nexit={code}\n", encoding="utf-8")
print(out)
print(err, file=sys.stderr)
sys.exit(code)
