#!/usr/bin/env python3
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import paramiko
from hv_vm_tools.config import Settings, load_vm_access_env_files
load_vm_access_env_files()
s = Settings.from_env()
pwd = os.environ.get("HV_VM_SSH_PASSWORD")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(hostname=s.vm_host, port=s.ssh_port, username=s.ssh_user, password=pwd,
          look_for_keys=False, allow_agent=False, timeout=30)
t = c.get_transport()
if t:
    t.set_keepalive(15)
cmd = r"""set -eux
export GIT_TERMINAL_PROMPT=0
export DEBIAN_FRONTEND=noninteractive
getent hosts upds7.ujob100.com || true
rm -rf /root/ohr-back
git clone https://upds7.ujob100.com/ohr/ohr-back.git /root/ohr-back
ls -la /root/ohr-back | head -n 25
"""
i,o,e = c.exec_command("bash -s", timeout=600)
i.write(cmd.encode())
i.channel.shutdown_write()
print(o.read().decode())
print("STDERR:", e.read().decode(), file=sys.stderr)
code = o.channel.recv_exit_status()
print("exit", code)
c.close()
