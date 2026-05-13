#!/usr/bin/env python3
"""从本机读取 git-access.env 分支配置，在 CI 机上触发一次 direct 全量构建并轮询状态。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def load_git_access() -> dict[str, str]:
    p = ROOT / "git-access.env"
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def load_branches_for_build() -> tuple[str, str]:
    g = load_git_access()
    default = "release_20260129"
    back = g.get("OHR_BACK_BRANCH") or default
    fws = g.get("FRONTEND_WORKSPACE_BRANCH") or g.get("FRONTEND_DEFAULT_WORKSPACE_BRANCH") or back or default
    return back, fws


def main() -> int:
    back, fws = load_branches_for_build()
    body = json.dumps(
        {
            "backend_branch": back,
            "frontend_workspace_branch": fws,
            "note": "remote_smoke_full_build",
        },
        ensure_ascii=False,
    )
    load_vm_access_env_files()
    s = Settings.from_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        hostname=s.vm_host,
        port=s.ssh_port,
        username=s.ssh_user,
        password=os.environ.get("HV_VM_SSH_PASSWORD"),
        look_for_keys=False,
        allow_agent=False,
        timeout=45,
    )
    try:
        payload = body.replace("'", "'\"'\"'")
        out = run(
            c,
            f"curl -sS -X POST http://127.0.0.1:8090/api/builds -H 'Content-Type: application/json' -d '{payload}'",
        )
        data = json.loads(out)
        print("created", json.dumps({"id": data.get("id"), "status": data.get("status")}, ensure_ascii=True))
        bid = data.get("id")
        if not bid:
            return 1
        for _ in range(80):
            time.sleep(30)
            st = run(c, f"curl -sS http://127.0.0.1:8090/api/builds/{bid}")
            meta = json.loads(st)
            print(
                json.dumps(
                    {"status": meta.get("status"), "steps": [(s["id"], s["status"]) for s in meta.get("steps", [])]},
                    ensure_ascii=True,
                ),
                flush=True,
            )
            if meta.get("status") in ("success", "failed"):
                return 0 if meta.get("status") == "success" else 1
    finally:
        c.close()
    return 2


def run(client: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = client.exec_command("bash -lc " + quote(command), timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(out + err)
    return out


def quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
