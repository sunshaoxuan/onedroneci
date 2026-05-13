#!/usr/bin/env python3
"""在 Drone 服务器上通过本地 API 激活仓库并开启 trusted。

优先使用 /opt/ohr-build-console/build-console.env 中的 DRONE_TOKEN（与 build-console 一致）；
若未配置则回退到 drone-server 容器日志里的 bootstrap token（通常不能用于 /api/user/repos）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else "sunshaoxuan/ohr-build-control"
    if "/" not in repo:
        print("usage: remote_drone_enable_repo.py [namespace/name]", file=sys.stderr)
        return 2
    owner, name = repo.split("/", 1)
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
        env_raw = run(
            c,
            "test -f /opt/ohr-build-console/build-console.env && "
            "cat /opt/ohr-build-console/build-console.env || true",
        )
        token_source = "none"
        token = parse_env_value(env_raw, "DRONE_TOKEN")
        if token:
            token_source = "build-console.env"
        base = parse_env_value(env_raw, "DRONE_SERVER_URL") or "http://127.0.0.1:8080"
        base = base.rstrip("/")
        if not token:
            logs = run(c, "docker logs drone-server 2>&1 || true")
            token = extract_token(logs)
            if token:
                token_source = "drone-server bootstrap logs"
        print(f"# token 来源: {token_source}", file=sys.stderr)
        if token_source == "drone-server bootstrap logs":
            print(
                "# 提示：bootstrap token 通常无法调用 /api/user/repos；"
                "请在 /opt/ohr-build-console/build-console.env 写入个人 DRONE_TOKEN。",
                file=sys.stderr,
            )
        if not token:
            print(
                "未找到 DRONE_TOKEN：请在远端 /opt/ohr-build-console/build-console.env 配置，"
                "或确保 drone-server 日志含 bootstrap token。",
                file=sys.stderr,
            )
            return 2
        hdr = f"-H 'Authorization: Bearer {token}' -H 'Content-Type: application/json'"
        # 同步 SCM 仓库列表（Drone：POST /api/user/repos）
        sync_out = run(c, f"curl -sS -w '\\nHTTP:%{{http_code}}' -X POST {hdr} {base}/api/user/repos || true")
        print("sync:", redact(sync_out, token))

        enable_out = run(
            c,
            f"curl -sS -w '\\nHTTP:%{{http_code}}' -X POST {hdr} {base}/api/repos/{owner}/{name} || true",
        )
        print("enable:", redact(enable_out, token))

        patch_body = json.dumps({"trusted": True})
        trust_out = run(
            c,
            f"curl -sS -w '\\nHTTP:%{{http_code}}' -X PATCH {hdr} "
            f"-d {quote_json_for_shell(patch_body)} {base}/api/repos/{owner}/{name} || true",
        )
        print("trusted:", redact(trust_out, token))

        info = run(c, f"curl -sS {hdr} {base}/api/repos/{owner}/{name} || true")
        print("get:", redact(info, token))
    finally:
        c.close()
    return 0


def quote_json_for_shell(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def redact(text: str, token: str) -> str:
    return text.replace(token, "<redacted>")


def parse_env_value(raw: str, key: str) -> str | None:
    prefix = key + "="
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith(prefix):
            continue
        val = line[len(prefix) :].strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        return val or None
    return None


def extract_token(logs: str) -> str | None:
    for line in logs.splitlines():
        if '"token"' not in line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            m = re.search(r'"token":"([^"]+)"', line)
            if m:
                return m.group(1)
            continue
        tok = data.get("token")
        if isinstance(tok, str) and tok:
            return tok
    return None


def run(client: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = client.exec_command("bash -lc " + quote(command), timeout=120)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise RuntimeError(f"remote command failed ({code})\n{out}\n{err}")
    return out + (("\n--- STDERR ---\n" + err) if err else "")


def quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
