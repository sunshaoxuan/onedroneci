#!/usr/bin/env python3
"""Deploy the first Drone Server + Docker Runner version to the Ubuntu CI VM."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


REMOTE_DIR = "/opt/drone"
FILES = (
    ROOT / "deploy" / "drone" / "docker-compose.yml",
    ROOT / "deploy" / "drone" / "drone.env",
)


def main() -> int:
    missing = [str(p) for p in FILES if not p.is_file()]
    if missing:
        print("missing files: " + ", ".join(missing), file=sys.stderr)
        return 2

    load_vm_access_env_files()
    settings = Settings.from_env()
    password = os.environ.get("HV_VM_SSH_PASSWORD")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=settings.vm_host,
        port=settings.ssh_port,
        username=settings.ssh_user,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=45,
    )

    try:
        _run(client, f"mkdir -p {REMOTE_DIR} && chmod 700 {REMOTE_DIR}")
        with client.open_sftp() as sftp:
            for local in FILES:
                remote = f"{REMOTE_DIR}/{local.name}"
                sftp.put(str(local), remote)
                _run(client, f"chmod 600 {remote}" if local.name.endswith(".env") else f"chmod 644 {remote}")

        cmd = f"""set -euo pipefail
cd {REMOTE_DIR}
if docker compose version >/dev/null 2>&1; then
  docker compose up -d
  docker compose ps
else
  docker-compose up -d
  docker-compose ps
fi
docker logs --tail=80 drone-server || true
docker logs --tail=80 drone-runner-docker || true
"""
        out = _run(client, cmd, timeout=600)
        (ROOT / "_remote_deploy_drone_log.txt").write_text(out, encoding="utf-8")
        print(out)
    finally:
        client.close()

    return 0


def _run(client: paramiko.SSHClient, command: str, timeout: int = 120) -> str:
    _, stdout, stderr = client.exec_command(f"bash -lc {_sh_quote(command)}", timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    combined = out + ("\n--- STDERR ---\n" + err if err else "")
    if code != 0:
        raise RuntimeError(f"remote command failed ({code}): {command}\n{combined}")
    return combined


def _sh_quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
