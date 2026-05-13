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
cmd = """java -version 2>&1 | head -3; git --version 2>&1; javac -version 2>&1; pgrep -a apt || true; test -d /root/ohr-back/.git && (echo CLONE_OK; ls /root/ohr-back | head) || echo no_clone; tail -8 /etc/hosts"""
i,o,e = c.exec_command(cmd, timeout=60)
print(o.read().decode())
print(e.read().decode(), file=sys.stderr)
c.close()
