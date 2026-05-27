#!/usr/bin/env python3
"""Deploy build-console to the Ubuntu CI VM."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import paramiko  # noqa: E402
from hv_vm_tools.config import Settings, load_vm_access_env_files  # noqa: E402


REMOTE_DIR = "/opt/ohr-build-console"
REMOTE_SERVICE = "/etc/systemd/system/ohr-build-console.service"


def load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        data[key.strip()] = val
    return data


def render_env() -> str:
    base = load_env_file(ROOT / "build-console" / "build-console.env")
    git = load_env_file(ROOT / "git-access.env")
    values = {
        "BUILD_CONSOLE_HOST": base.get("BUILD_CONSOLE_HOST", "0.0.0.0"),
        "BUILD_CONSOLE_PORT": base.get("BUILD_CONSOLE_PORT", "8090"),
        "BUILD_CONSOLE_DATA_DIR": base.get("BUILD_CONSOLE_DATA_DIR", "/opt/ohr-build-console/builds"),
        "BUILD_ARTIFACT_ROOT": base.get("BUILD_ARTIFACT_ROOT", "/opt/ohr-build-artifacts"),
        "BUILD_EXECUTOR": base.get("BUILD_EXECUTOR", "direct"),
        "OHR_BACK_DIR": base.get("OHR_BACK_DIR", "/root/ohr-back"),
        "DEFAULT_BACKEND_BRANCH": git.get("OHR_BACK_BRANCH", base.get("DEFAULT_BACKEND_BRANCH", "release_20260129")),
        "OHR_BACK_GIT_TOKEN": git.get("OHR_BACK_GIT_TOKEN", base.get("OHR_BACK_GIT_TOKEN", "")),
        "MAVEN_ONEHR_USERNAME": git.get("MAVEN_ONEHR_USERNAME", base.get("MAVEN_ONEHR_USERNAME", "admin")),
        "MAVEN_ONEHR_PASSWORD": git.get("MAVEN_ONEHR_PASSWORD", base.get("MAVEN_ONEHR_PASSWORD", "")),
        "DRONE_SERVER_URL": base.get("DRONE_SERVER_URL", "http://127.0.0.1:8080"),
        "DRONE_TOKEN": base.get("DRONE_TOKEN", ""),
        "DRONE_CONTROL_REPO": base.get("DRONE_CONTROL_REPO", ""),
        "DRONE_CONTROL_BRANCH": base.get("DRONE_CONTROL_BRANCH", "master"),
        "FRONTEND_WORKSPACE_GIT_URL": base.get("FRONTEND_WORKSPACE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-workspace.git"),
        "FRONTEND_WORKSPACE_BRANCH": base.get("FRONTEND_WORKSPACE_BRANCH", "master"),
        "FRONTEND_WORKSPACE_DIR": base.get("FRONTEND_WORKSPACE_DIR", "/opt/ohr-workspace-src"),
        "FRONTEND_FEELIN_GIT_URL": base.get("FRONTEND_FEELIN_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-feelin.git"),
        "FRONTEND_LOWCODE_ENGINE_GIT_URL": base.get("FRONTEND_LOWCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-lowcode-engine.git"),
        "FRONTEND_MICRO_FRONTENDS_GIT_URL": base.get("FRONTEND_MICRO_FRONTENDS_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-micro-frontends.git"),
        "FRONTEND_NOCODE_ENGINE_GIT_URL": base.get("FRONTEND_NOCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-nocode-engine.git"),
        "NHO_BACK_DIR": base.get("NHO_BACK_DIR", "/root/nho-ohr-back"),
        "NHO_BACK_GIT_URL": base.get("NHO_BACK_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-back.git"),
        "NHO_FRONTEND_WORKSPACE_GIT_URL": base.get("NHO_FRONTEND_WORKSPACE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-workspace.git"),
        "NHO_FRONTEND_WORKSPACE_BRANCH": base.get("NHO_FRONTEND_WORKSPACE_BRANCH", "master"),
        "NHO_FRONTEND_WORKSPACE_DIR": base.get("NHO_FRONTEND_WORKSPACE_DIR", "/opt/nho-ohr-workspace-src"),
        "NHO_FRONTEND_FEELIN_GIT_URL": base.get("NHO_FRONTEND_FEELIN_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-feelin.git"),
        "NHO_FRONTEND_FEELIN_BRANCH": base.get("NHO_FRONTEND_FEELIN_BRANCH", "master"),
        "NHO_FRONTEND_MICRO_FRONTENDS_GIT_URL": base.get("NHO_FRONTEND_MICRO_FRONTENDS_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-micro-frontends.git"),
        "NHO_FRONTEND_LOWCODE_ENGINE_GIT_URL": base.get("NHO_FRONTEND_LOWCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-lowcode-engine.git"),
        "NHO_FRONTEND_NOCODE_ENGINE_GIT_URL": base.get("NHO_FRONTEND_NOCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-nocode-engine.git"),
        "NHO_FRONTEND_NENCHO_GIT_URL": base.get("NHO_FRONTEND_NENCHO_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-web-nencho.git"),
        "NHO_PNPM_CACHE_DIR": base.get("NHO_PNPM_CACHE_DIR", "/opt/nho-pnpm-cache"),
        "NHO_YARN_CACHE_DIR": base.get("NHO_YARN_CACHE_DIR", "/opt/nho-yarn-cache"),
        "NHO_MAVEN_CACHE_DIR": base.get("NHO_MAVEN_CACHE_DIR", "/opt/nho-maven-cache"),
        "NHO_BACK_MAVEN_IMAGE": base.get("NHO_BACK_MAVEN_IMAGE", "maven:3.9.6-eclipse-temurin-22"),
        "NHO_MATERIAL_SVN_URL": base.get("NHO_MATERIAL_SVN_URL", "http://3.115.155.21/svn/nho4phr/大連側/97.リリース作業"),
        "NHO_MATERIAL_SVN_USERNAME": base.get("NHO_MATERIAL_SVN_USERNAME", ""),
        "NHO_MATERIAL_SVN_PASSWORD": base.get("NHO_MATERIAL_SVN_PASSWORD", ""),
        "NHO_MATERIAL_CACHE_SECONDS": base.get("NHO_MATERIAL_CACHE_SECONDS", "300"),
        "STANDARD_MATERIAL_SVN_URL": base.get(
            "STANDARD_MATERIAL_SVN_URL",
            "http://192.168.21.111/svn/PHR1.5/98.環境構築手順書/お客様環境",
        ),
        "STANDARD_MATERIAL_SVN_USERNAME": base.get("STANDARD_MATERIAL_SVN_USERNAME", ""),
        "STANDARD_MATERIAL_SVN_PASSWORD": base.get("STANDARD_MATERIAL_SVN_PASSWORD", ""),
        "STANDARD_MATERIAL_CACHE_SECONDS": base.get("STANDARD_MATERIAL_CACHE_SECONDS", "300"),
        "HELP_DOCS_GIT_URL": base.get("HELP_DOCS_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-help-docs.git"),
        "HELP_DOCS_BRANCH": base.get("HELP_DOCS_BRANCH", "release_ci"),
        "HELP_DOCS_DIR": base.get("HELP_DOCS_DIR", "/opt/ohr-help-docs-src"),
        "HELP_DOCS_SVN_URL": base.get(
            "HELP_DOCS_SVN_URL",
            "http://192.168.21.111/svn/PHR1.5/30.マニュアル/マニュアル(日本語版)",
        ),
        "HELP_DOCS_SVN_DIR": base.get("HELP_DOCS_SVN_DIR", "/opt/ohr-help-docs-svn"),
        "HELP_DOCS_SVN_USERNAME": base.get("HELP_DOCS_SVN_USERNAME", ""),
        "HELP_DOCS_SVN_PASSWORD": base.get("HELP_DOCS_SVN_PASSWORD", ""),
        "CONF_PROD_TEMPLATE_DIR": base.get("CONF_PROD_TEMPLATE_DIR", f"{REMOTE_DIR}/conf_prod_template"),
        "OHR_CICD_GIT_URL": base.get("OHR_CICD_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-cicd.git"),
        "OHR_CICD_BRANCH": base.get("OHR_CICD_BRANCH", "master"),
        "OHR_CICD_DIR": base.get("OHR_CICD_DIR", "/opt/ohr-cicd-src"),
        "OHR_CICD_ENV": base.get("OHR_CICD_ENV", "direct_prod"),
        "OHR_CICD_SERVICE_GATEWAY": base.get("OHR_CICD_SERVICE_GATEWAY", "http://localhost:3198/"),
        "OHR_CICD_MINIO_SERVER": base.get("OHR_CICD_MINIO_SERVER", "http://localhost:19000"),
        "OHR_CICD_MINIO_HOST": base.get("OHR_CICD_MINIO_HOST", "localhost:19000"),
        "OHR_CICD_RUSTFS_SERVER": base.get("OHR_CICD_RUSTFS_SERVER", "http://127.0.0.1:12345"),
        "OHR_CICD_RUSTFS_HOST": base.get("OHR_CICD_RUSTFS_HOST", "127.0.0.1:12345"),
        "FRONTEND_GIT_TOKEN": base.get("FRONTEND_GIT_TOKEN", git.get("OHR_BACK_GIT_TOKEN", "")),
        "NPM_AUTH_B64": base.get("NPM_AUTH_B64", ""),
        "STANDARD_NODE_OPTIONS": base.get("STANDARD_NODE_OPTIONS", "--max-old-space-size=4096"),
    }
    return "".join(f"{key}={quote_env(value)}\n" for key, value in values.items())


def quote_env(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def main() -> int:
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
        _run(client, f"mkdir -p {REMOTE_DIR}/builds /opt/ohr-build-artifacts /opt/pnpm-cache /opt/nho-pnpm-cache /opt/yarn-cache /opt/nho-yarn-cache /opt/nho-maven-cache /opt/workspace-cache-ohr /opt/ohr-backend/.m2 /opt/ohr-workspace-src /opt/nho-ohr-workspace-src /root/nho-ohr-back /opt/ohr-help-docs-src /opt/ohr-help-docs-svn && rm -rf {REMOTE_DIR}/conf_prod_template && mkdir -p {REMOTE_DIR}/conf_prod_template && chmod 700 {REMOTE_DIR}")
        with client.open_sftp() as sftp:
            sftp.put(str(ROOT / "build-console" / "server.py"), f"{REMOTE_DIR}/server.py")
            sftp.put(str(ROOT / "build-console" / "drone_adapter.py"), f"{REMOTE_DIR}/drone_adapter.py")
            _upload_dir(sftp, ROOT / "build-console" / "conf_prod_template", f"{REMOTE_DIR}/conf_prod_template")
            _write_sftp(sftp, f"{REMOTE_DIR}/build-console.env", render_env())
            sftp.put(str(ROOT / "deploy" / "build-console" / "ohr-build-console.service"), REMOTE_SERVICE)
        _run(
            client,
            f"""set -euo pipefail
chmod 755 {REMOTE_DIR}/server.py
chmod 644 {REMOTE_DIR}/drone_adapter.py
chmod 600 {REMOTE_DIR}/build-console.env
chmod 644 {REMOTE_SERVICE}
systemctl daemon-reload
systemctl enable --now ohr-build-console.service
systemctl restart ohr-build-console.service
systemctl --no-pager --full status ohr-build-console.service || true
for i in 1 2 3 4 5; do
  if curl -fsS -I http://127.0.0.1:8090/ >/dev/null; then
    curl -sS -I http://127.0.0.1:8090/ | head -20
    exit 0
  fi
  sleep 1
done
curl -sS -I http://127.0.0.1:8090/ | head -20
""",
        )
        out = _run(client, "journalctl -u ohr-build-console.service -n 80 --no-pager || true")
        (ROOT / "_remote_deploy_build_console_log.txt").write_text(out, encoding="utf-8")
        print(out)
    finally:
        client.close()
    return 0


def _write_sftp(sftp: paramiko.SFTPClient, remote: str, text: str) -> None:
    with sftp.file(remote, "w") as f:
        f.write(text)


def _upload_dir(sftp: paramiko.SFTPClient, local: Path, remote: str) -> None:
    try:
        sftp.mkdir(remote)
    except OSError:
        pass
    for item in local.iterdir():
        target = f"{remote}/{item.name}"
        if item.is_dir():
            _upload_dir(sftp, item, target)
        else:
            sftp.put(str(item), target)


def _run(client: paramiko.SSHClient, command: str) -> str:
    _, stdout, stderr = client.exec_command("bash -lc " + _sh_quote(command), timeout=180)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    combined = out + ("\n--- STDERR ---\n" + err if err else "")
    if code != 0:
        raise RuntimeError(f"remote command failed ({code})\n{combined}")
    return combined


def _sh_quote(script: str) -> str:
    return "'" + script.replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
