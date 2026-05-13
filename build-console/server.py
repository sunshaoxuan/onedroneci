#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import signal
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.error
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT))

from drone_adapter import DroneBuildRef, DroneExecutorAdapter

DATA_DIR = Path(os.environ.get("BUILD_CONSOLE_DATA_DIR", ROOT / "builds"))
OHR_BACK_DIR = Path(os.environ.get("OHR_BACK_DIR", "/root/ohr-back"))
ARTIFACT_ROOT = Path(os.environ.get("BUILD_ARTIFACT_ROOT", "/opt/ohr-build-artifacts"))
FRONTEND_WORKSPACE_DIR = Path(os.environ.get("FRONTEND_WORKSPACE_DIR", "/opt/ohr-workspace-src"))
FRONTEND_WORKSPACE_GIT_URL = os.environ.get(
    "FRONTEND_WORKSPACE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-workspace.git"
)
FRONTEND_CHILD_REPOS = {
    "frontend_feelin_branch": os.environ.get("FRONTEND_FEELIN_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-feelin.git"),
    "frontend_lowcode_engine_branch": os.environ.get(
        "FRONTEND_LOWCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-lowcode-engine.git"
    ),
    "frontend_micro_frontends_branch": os.environ.get(
        "FRONTEND_MICRO_FRONTENDS_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-micro-frontends.git"
    ),
    "frontend_nocode_engine_branch": os.environ.get(
        "FRONTEND_NOCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-nocode-engine.git"
    ),
}
FRONTEND_WORKSPACE_BRANCH = os.environ.get("FRONTEND_WORKSPACE_BRANCH", "master")
HOST = os.environ.get("BUILD_CONSOLE_HOST", "0.0.0.0")
PORT = int(os.environ.get("BUILD_CONSOLE_PORT", "8090"))
CONFIG_FILE = Path(os.environ.get("BUILD_CONSOLE_ENV", ROOT / "build-console.env"))
EXECUTOR = os.environ.get("BUILD_EXECUTOR", "direct")
DRONE_SERVER_URL = os.environ.get("DRONE_SERVER_URL", "http://127.0.0.1:8080")
DRONE_TOKEN = os.environ.get("DRONE_TOKEN", "")
DRONE_CONTROL_REPO = os.environ.get("DRONE_CONTROL_REPO", "")
DRONE_CONTROL_BRANCH = os.environ.get("DRONE_CONTROL_BRANCH", "master")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
DIRECT_STEP_IDS = (
    "validate",
    "checkout_backend",
    "build_backend",
    "restore_frontend",
    "build_frontend",
    "collect_artifacts",
)
DRONE_STEP_IDS = ("validate-params", "build-backend-package", "restore-frontend-workspace", "build-frontend-web", "persist-frontend-workspace")
BUILD_LOCK = threading.Lock()
BUILD_THREADS: dict[str, threading.Thread] = {}
BUILD_PROCS: dict[str, subprocess.Popen[str]] = {}
CANCELLED_BUILDS: set[str] = set()


class BuildCancelled(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        os.environ.setdefault(key.strip(), val)


def make_steps(executor: str = "direct") -> list[dict[str, Any]]:
    direct_labels = {
        "validate": "参数校验",
        "checkout_backend": "拉取后端代码",
        "build_backend": "后端打包",
        "restore_frontend": "恢复前端工作区",
        "build_frontend": "前端 web.zip",
        "collect_artifacts": "收集产物",
    }
    drone_labels = {
        "validate-params": "参数校验",
        "build-backend-package": "后端 package.zip",
        "restore-frontend-workspace": "恢复前端工作区",
        "build-frontend-web": "前端 web.zip",
        "persist-frontend-workspace": "持久化前端缓存",
    }
    if executor == "drone":
        order = DRONE_STEP_IDS
        labels = drone_labels
    else:
        order = DIRECT_STEP_IDS
        labels = direct_labels
    return [{"id": step, "label": labels[step], "status": "pending", "started_at": None, "finished_at": None} for step in order]


def now() -> int:
    return int(time.time())


def isoish() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def build_dir(build_id: str) -> Path:
    return DATA_DIR / build_id


def metadata_path(build_id: str) -> Path:
    return build_dir(build_id) / "metadata.json"


def log_path(build_id: str) -> Path:
    return build_dir(build_id) / "build.log"


def artifact_path(build_id: str, name: str = "package.zip") -> Path:
    return build_dir(build_id) / name


def shared_artifact_path(build_id: str, name: str) -> Path:
    return ARTIFACT_ROOT / build_id / name


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_log(build_id: str, line: str) -> None:
    with log_path(build_id).open("a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")


def update_build(build_id: str, **updates: Any) -> dict[str, Any]:
    meta = read_json(metadata_path(build_id))
    meta.update(updates)
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)
    return meta


def update_step(build_id: str, step_id: str, status: str, message: str | None = None) -> None:
    meta = read_json(metadata_path(build_id))
    for step in meta["steps"]:
        if step["id"] == step_id:
            if status == "running" and not step["started_at"]:
                step["started_at"] = now()
            if status in ("success", "failed", "skipped", "cancelled"):
                step["finished_at"] = now()
            step["status"] = status
            if message:
                step["message"] = message
            break
    if status == "cancelled":
        meta["status"] = "cancelled"
    elif status == "failed":
        meta["status"] = "failed"
    elif all(s["status"] in ("success", "skipped") for s in meta["steps"]):
        meta["status"] = "success"
    else:
        meta["status"] = "running"
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)


def create_build(payload: dict[str, Any]) -> dict[str, Any]:
    build_backend = bool(payload.get("build_backend", True))
    build_frontend = bool(payload.get("build_frontend", True))
    backend_branch = str(payload.get("backend_branch") or "").strip()
    frontend_release_branch = str(
        payload.get("frontend_release_branch")
        or payload.get("frontend_version_branch")
        or payload.get("frontend_workspace_branch")
        or payload.get("frontend_bootstrap_branch")
        or ""
    ).strip()
    note = str(payload.get("note") or "").strip()

    if not build_backend and not build_frontend:
        raise ValueError("请至少选择一个构建目标")
    if build_backend and not backend_branch:
        raise ValueError("请填写后端分支")
    if backend_branch and not BRANCH_RE.fullmatch(backend_branch):
        raise ValueError("后端分支名仅允许字母、数字、._/-")
    if build_frontend and not frontend_release_branch:
        raise ValueError("请填写前端版本分支")
    if frontend_release_branch and not BRANCH_RE.fullmatch(frontend_release_branch):
        raise ValueError("前端版本分支名仅允许字母、数字、._/-")
    # ohr-workspace 不跟随 release_*；它固定使用配置分支。用户选择的是四个子项目共同存在的版本分支。
    frontend_workspace_branch = FRONTEND_WORKSPACE_BRANCH
    frontend_feelin_branch = frontend_release_branch
    frontend_lowcode_engine_branch = frontend_release_branch
    frontend_micro_frontends_branch = frontend_release_branch
    frontend_nocode_engine_branch = frontend_release_branch

    if EXECUTOR == "drone":
        if not DRONE_CONTROL_REPO or not DRONE_TOKEN:
            raise ValueError("Drone 执行器未配置 DRONE_CONTROL_REPO 或 DRONE_TOKEN")

    build_id = isoish()
    suffix = 1
    while build_dir(build_id).exists():
        suffix += 1
        build_id = f"{isoish()}-{suffix}"

    build_dir(build_id).mkdir(parents=True, exist_ok=False)
    log_path(build_id).write_text("", encoding="utf-8")
    meta = {
        "id": build_id,
        "executor": EXECUTOR,
        "status": "queued",
        "created_at": now(),
        "updated_at": now(),
        "request": {
            "backend_branch": backend_branch,
            "frontend_workspace_branch": frontend_workspace_branch,
            "frontend_release_branch": frontend_release_branch,
            "frontend_feelin_branch": frontend_feelin_branch,
            "frontend_lowcode_engine_branch": frontend_lowcode_engine_branch,
            "frontend_micro_frontends_branch": frontend_micro_frontends_branch,
            "frontend_nocode_engine_branch": frontend_nocode_engine_branch,
            "build_backend": build_backend,
            "build_frontend": build_frontend,
            "note": note,
        },
        "steps": make_steps(EXECUTOR),
        "artifacts": [],
        "artifact": None,
        "drone": None,
    }
    write_json(metadata_path(build_id), meta)
    if EXECUTOR == "drone":
        trigger_drone_build(build_id)
    else:
        thread = threading.Thread(target=run_direct_build, args=(build_id,), daemon=True)
        BUILD_THREADS[build_id] = thread
        thread.start()
    return meta


def run_direct_build(build_id: str) -> None:
    if not BUILD_LOCK.acquire(blocking=False):
        append_log(build_id, "另一个构建正在运行，本次构建失败。第一版暂时只允许同时运行一个构建。")
        update_build(build_id, status="failed", error="another build is running")
        update_step(build_id, "validate", "failed", "已有构建运行中")
        return
    try:
        if build_id in CANCELLED_BUILDS:
            raise BuildCancelled("构建已取消")
        meta = update_build(build_id, status="running")
        request = meta["request"]
        build_backend = bool(request.get("build_backend", True))
        build_frontend = bool(request.get("build_frontend", True))
        branch = request["backend_branch"]
        append_log(
            build_id,
            f"构建开始：build_backend={build_backend}, build_frontend={build_frontend}, "
            f"backend_branch={branch or '-'}, frontend_release_branch={request.get('frontend_release_branch') or '-'}",
        )

        update_step(build_id, "validate", "running")
        if build_backend and not OHR_BACK_DIR.is_dir():
            raise RuntimeError(f"后端目录不存在：{OHR_BACK_DIR}")
        if build_frontend and not os.environ.get("OHR_BACK_GIT_TOKEN") and not os.environ.get("FRONTEND_GIT_TOKEN"):
            raise RuntimeError("需配置 OHR_BACK_GIT_TOKEN 或 FRONTEND_GIT_TOKEN 以克隆前端 workspace")
        update_step(build_id, "validate", "success")

        if build_backend:
            update_step(build_id, "checkout_backend", "running")
            rc = run_command(build_id, checkout_command(branch), cwd=OHR_BACK_DIR)
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("后端代码检出失败")
            update_step(build_id, "checkout_backend", "success")

            update_step(build_id, "build_backend", "running")
            rc = run_command(build_id, build_command(), cwd=OHR_BACK_DIR, timeout=None)
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("后端打包失败")
            update_step(build_id, "build_backend", "success")
        else:
            update_step(build_id, "checkout_backend", "skipped", "未选择后端构建")
            update_step(build_id, "build_backend", "skipped", "未选择后端构建")

        (ARTIFACT_ROOT / build_id).mkdir(parents=True, exist_ok=True)
        if build_frontend:
            fe_env = direct_frontend_env(request, build_id)

            update_step(build_id, "restore_frontend", "running")
            rc = run_command(
                build_id,
                DIRECT_FRONTEND_RESTORE_SCRIPT,
                cwd=Path("/"),
                timeout=None,
                extra_env=fe_env,
            )
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("前端工作区恢复失败")
            update_step(build_id, "restore_frontend", "success")

            update_step(build_id, "build_frontend", "running")
            rc = run_command(
                build_id,
                DIRECT_FRONTEND_BUILD_SCRIPT,
                cwd=Path("/"),
                timeout=None,
                extra_env=fe_env,
            )
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("前端构建失败")
            update_step(build_id, "build_frontend", "success")
        else:
            update_step(build_id, "restore_frontend", "skipped", "未选择前端构建")
            update_step(build_id, "build_frontend", "skipped", "未选择前端构建")

        update_step(build_id, "collect_artifacts", "running")
        pkg_src = OHR_BACK_DIR / "package.zip"
        web_src = ARTIFACT_ROOT / build_id / "web.zip"
        if build_backend and not pkg_src.is_file():
            raise RuntimeError(f"未找到产物：{pkg_src}")
        if build_frontend and not web_src.is_file():
            raise RuntimeError(f"未找到产物：{web_src}")
        if build_backend:
            shutil.copy2(pkg_src, artifact_path(build_id, "package.zip"))
            shutil.copy2(pkg_src, shared_artifact_path(build_id, "package.zip"))
        if build_frontend:
            shutil.copy2(web_src, artifact_path(build_id, "web.zip"))
        artifacts = []
        for name in ("package.zip", "web.zip"):
            p = artifact_path(build_id, name)
            if p.is_file():
                artifacts.append({"name": name, "size": p.stat().st_size, "path": str(p)})
        update_build(build_id, artifact=artifacts[0] if artifacts else None, artifacts=artifacts)
        append_log(build_id, "产物已收集：" + ", ".join(item["name"] for item in artifacts))
        update_step(build_id, "collect_artifacts", "success")
        update_build(build_id, status="success")
        append_log(build_id, "构建成功。")
    except BuildCancelled as exc:
        append_log(build_id, f"构建已停止：{exc}")
        cancel_running_step(build_id, str(exc))
        update_build(build_id, status="cancelled", error=str(exc))
    except Exception as exc:
        append_log(build_id, f"构建失败：{exc}")
        fail_running_step(build_id, str(exc))
        update_build(build_id, status="failed", error=str(exc))
    finally:
        BUILD_THREADS.pop(build_id, None)
        BUILD_PROCS.pop(build_id, None)
        CANCELLED_BUILDS.discard(build_id)
        BUILD_LOCK.release()


def trigger_drone_build(build_id: str) -> None:
    meta = read_json(metadata_path(build_id))
    adapter = make_drone_adapter()
    try:
        ref = adapter.trigger(meta["request"], build_id)
    except Exception as exc:
        append_log(build_id, f"触发 Drone 构建失败：{exc}")
        update_build(build_id, status="failed", error=str(exc))
        return
    meta["drone"] = {"repo": ref.repo, "build_number": ref.build_number, "url": ref.url, "log_positions": {}}
    meta["status"] = "queued"
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)
    append_log(build_id, f"已触发 Drone 构建：{ref.repo} #{ref.build_number}")


def make_drone_adapter() -> DroneExecutorAdapter:
    return DroneExecutorAdapter(DRONE_SERVER_URL, DRONE_TOKEN, DRONE_CONTROL_REPO, DRONE_CONTROL_BRANCH)


def sync_drone_build(build_id: str) -> dict[str, Any]:
    meta = read_json(metadata_path(build_id))
    drone = meta.get("drone")
    if meta.get("executor") != "drone" or not drone:
        return meta
    ref = DroneBuildRef(repo=drone["repo"], build_number=int(drone["build_number"]), url=drone.get("url"))
    adapter = make_drone_adapter()
    try:
        build = adapter.get_build(ref)
    except Exception as exc:
        meta["error"] = f"读取 Drone 状态失败：{exc}"
        meta["updated_at"] = now()
        write_json(metadata_path(build_id), meta)
        return meta

    meta["status"] = drone_status(build.get("status", "pending"))
    meta["steps"] = steps_from_drone_build(build)
    sync_artifacts(meta)
    sync_drone_logs(build_id, meta, adapter, ref, build)
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)
    return meta


def drone_status(status: str) -> str:
    if status in ("pending", "waiting", "blocked"):
        return "queued"
    if status in ("running",):
        return "running"
    if status in ("success", "failure", "killed", "error"):
        return "success" if status == "success" else "failed"
    return status or "queued"


def steps_from_drone_build(build: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for stage in build.get("stages") or []:
        for step in stage.get("steps") or []:
            name = step.get("name") or f"step-{step.get('number')}"
            steps.append(
                {
                    "id": name,
                    "label": name,
                    "status": drone_status(step.get("status", "pending")),
                    "started_at": step.get("started") or None,
                    "finished_at": step.get("stopped") or None,
                    "message": f"stage {stage.get('number')} / step {step.get('number')}",
                }
            )
    return steps or make_steps("drone")


def sync_artifacts(meta: dict[str, Any]) -> None:
    build_id = meta["id"]
    artifacts = []
    for name in ("package.zip", "web.zip"):
        path = shared_artifact_path(build_id, name)
        if path.is_file():
            artifacts.append({"name": name, "size": path.stat().st_size, "path": str(path)})
    meta["artifacts"] = artifacts
    meta["artifact"] = next((item for item in artifacts if item["name"] == "package.zip"), None)


def sync_drone_logs(build_id: str, meta: dict[str, Any], adapter: DroneExecutorAdapter, ref: DroneBuildRef, build: dict[str, Any]) -> None:
    positions = meta.setdefault("drone", {}).setdefault("log_positions", {})
    for stage in build.get("stages") or []:
        stage_no = int(stage.get("number") or 1)
        for step in stage.get("steps") or []:
            step_no = int(step.get("number") or 1)
            key = f"{stage_no}/{step_no}"
            last_pos = int(positions.get(key, -1))
            try:
                entries = adapter.get_logs(ref, stage_no, step_no)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
                continue
            new_entries = [entry for entry in entries if int(entry.get("pos", -1)) > last_pos]
            if not new_entries:
                continue
            append_log(build_id, f"--- Drone {stage.get('name', stage_no)} / {step.get('name', step_no)} ---")
            for entry in new_entries:
                append_log(build_id, redact_secrets(str(entry.get("out", ""))))
            positions[key] = max(int(entry.get("pos", last_pos)) for entry in new_entries)


def fail_running_step(build_id: str, message: str) -> None:
    meta = read_json(metadata_path(build_id))
    for step in meta["steps"]:
        if step["status"] == "running":
            step["status"] = "failed"
            step["finished_at"] = now()
            step["message"] = message
            break
    meta["status"] = "failed"
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)


def cancel_running_step(build_id: str, message: str) -> None:
    meta = read_json(metadata_path(build_id))
    for step in meta["steps"]:
        if step["status"] == "running":
            step["status"] = "cancelled"
            step["finished_at"] = now()
            step["message"] = message
        elif step["status"] == "pending":
            step["status"] = "skipped"
            step["finished_at"] = now()
            step["message"] = "构建已停止"
    meta["status"] = "cancelled"
    meta["updated_at"] = now()
    write_json(metadata_path(build_id), meta)


def ensure_not_cancelled(build_id: str) -> None:
    if build_id in CANCELLED_BUILDS:
        raise BuildCancelled("用户停止了构建")


def cancel_build(build_id: str) -> dict[str, Any]:
    path = metadata_path(build_id)
    if not path.is_file():
        raise FileNotFoundError(build_id)
    meta = read_json(path)
    if meta.get("status") in ("success", "failed", "cancelled"):
        return meta
    CANCELLED_BUILDS.add(build_id)
    append_log(build_id, "收到停止请求，正在终止当前步骤...")
    proc = BUILD_PROCS.get(build_id)
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.kill()
    cancel_running_step(build_id, "用户停止了构建")
    return read_json(path)


def checkout_command(branch: str) -> str:
    git_token = os.environ.get("OHR_BACK_GIT_TOKEN", "")
    set_origin = ""
    if git_token:
        url = "https://oauth2:" + urllib.parse.quote(git_token, safe="") + "@upds7.ujob100.com/ohr/ohr-back.git"
        set_origin = f"git remote set-url origin {shell_quote(url)} && "
    b = shell_quote(branch)
    return f"set -euo pipefail; {set_origin}git fetch origin {b}; git checkout -B {b} FETCH_HEAD; git rev-parse --short HEAD"


def build_command() -> str:
    user = xml_escape(os.environ.get("MAVEN_ONEHR_USERNAME", "admin"))
    raw_pwd = os.environ.get("MAVEN_ONEHR_PASSWORD", "")
    if not raw_pwd:
        raise RuntimeError("需配置 MAVEN_ONEHR_PASSWORD")
    pwd = xml_escape(raw_pwd)
    settings = f"""<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <servers>
    <server><id>onehr</id><username>{user}</username><password>{pwd}</password></server>
    <server><id>onehr-releases</id><username>{user}</username><password>{pwd}</password></server>
    <server><id>onehr-snapshots</id><username>{user}</username><password>{pwd}</password></server>
  </servers>
</settings>
"""
    return f"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! command -v zip >/dev/null 2>&1; then apt-get update -qy && apt-get install -y zip; fi
if ! swapon --show | grep -q swap_ci_build; then
  if [ ! -f /swap_ci_build ]; then
    dd if=/dev/zero of=/swap_ci_build bs=1M count=6144 status=progress
    chmod 600 /swap_ci_build
    mkswap /swap_ci_build
  fi
  swapon /swap_ci_build || true
fi
mkdir -p /root/.m2
cat > /root/.m2/settings.xml <<'EOF'
{settings}
EOF
chmod 600 /root/.m2/settings.xml
export MAVEN_OPTS="-Xmx2048m -Xms256m -XX:+UseG1GC -Dmaven.wagon.http.ssl.insecure=true -Dmaven.wagon.http.ssl.allowall=true -Dmaven.wagon.http.ssl.ignore.validity.dates=true -Dmaven.compiler.fork=true -Dmaven.compiler.meminitial=256m -Dmaven.compiler.maxmem=1536m"
rm -rf ./package ./package.zip
mvn -s /root/.m2/settings.xml -B clean package -Dmaven.test.skip
mkdir -p ./package
cp ./standalone/target/standalone*.jar ./package/standalone.jar
zip -r package.zip ./package
ls -la package.zip
ls -lh ./package/standalone.jar
sha256sum package.zip | head -1
"""


def workspace_git_url_with_token() -> str:
    return git_url_with_token(FRONTEND_WORKSPACE_GIT_URL)


def git_url_with_token(base: str) -> str:
    token = os.environ.get("FRONTEND_GIT_TOKEN") or os.environ.get("OHR_BACK_GIT_TOKEN", "")
    if not token:
        return base
    u = urllib.parse.urlparse(base)
    host = u.hostname or ""
    netloc = f"oauth2:{urllib.parse.quote(token, safe='')}@{host}"
    if u.port:
        netloc += f":{u.port}"
    return urllib.parse.urlunparse((u.scheme or "https", netloc, u.path, u.params, u.query, u.fragment))


def npm_auth_b64_value() -> str:
    v = (os.environ.get("NPM_AUTH_B64") or "").strip()
    if v:
        return v
    u = os.environ.get("MAVEN_ONEHR_USERNAME", "admin")
    p = os.environ.get("MAVEN_ONEHR_PASSWORD", "")
    if not p:
        raise RuntimeError("需配置 NPM_AUTH_B64 或 MAVEN_ONEHR_PASSWORD")
    return base64.b64encode(f"{u}:{p}".encode()).decode()


DIRECT_FRONTEND_RESTORE_SCRIPT = r"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"
BASE="$OHR_FRONTEND_WORKDIR"
mkdir -p "$(dirname "$BASE")"
if [ ! -d "$BASE/.git" ]; then
  rm -rf "$BASE"
  git clone "$GIT_SYNC_URL" "$BASE"
fi
cd "$BASE"
git remote set-url origin "$GIT_SYNC_URL"
git fetch --all --prune
git reset --hard HEAD
git clean -fd
if git show-ref --verify --quiet "refs/remotes/origin/$FRONTEND_WS_BRANCH"; then
  git checkout -B "$FRONTEND_WS_BRANCH" "origin/$FRONTEND_WS_BRANCH"
else
  echo "远端 ohr-workspace 不存在分支：$FRONTEND_WS_BRANCH"
  echo "可用分支（前 40 个）："
  git branch -r | sed -n '1,40p'
  exit 2
fi
npm i -g pnpm@10.22.0 --registry=https://registry.npmmirror.com/
npm i -g yarn@1.22.22 --registry=https://registry.npmmirror.com/
pnpm config set store-dir /opt/pnpm-cache || true
npm i yalc -g --registry=https://registry.npmmirror.com/
npm config set registry https://registry.smartcompany.cn/repository/npm-group/
npm config set //registry.smartcompany.cn/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-group/:_auth "$NPM_AUTH_B64"
npm i -g ohr-cli --registry=https://registry.smartcompany.cn/repository/npm-group/
if [ -n "${FRONTEND_GIT_TOKEN:-}" ]; then
  git config --global url."https://oauth2:${FRONTEND_GIT_TOKEN}@${FRONTEND_GIT_HOST}/".insteadOf "https://${FRONTEND_GIT_HOST}/"
fi
pnpm i
export RELEASE_BRANCH="$FRONTEND_REL_BRANCH"
export FEELIN_BRANCH="${FRONTEND_FEELIN_BRANCH:-$FRONTEND_REL_BRANCH}"
export LOWCODE_ENGINE_BRANCH="${FRONTEND_LOWCODE_BRANCH:-$FRONTEND_REL_BRANCH}"
export MICRO_FRONTENDS_BRANCH="${FRONTEND_MF_BRANCH:-$FRONTEND_REL_BRANCH}"
export NOCODE_ENGINE_BRANCH="${FRONTEND_NOCODE_BRANCH:-$FRONTEND_REL_BRANCH}"
sync_frontend_repo() {
  repo_dir="$1"
  repo_url="$2"
  repo_branch="$3"
  if [ -d "$repo_dir/.git" ]; then
    echo "[sync $repo_dir] fetch $repo_branch"
    git -C "$repo_dir" remote set-url origin "$repo_url"
    git -C "$repo_dir" fetch origin "$repo_branch" --prune
    git -C "$repo_dir" checkout -B "$repo_branch" "origin/$repo_branch"
    git -C "$repo_dir" reset --hard "origin/$repo_branch"
    git -C "$repo_dir" clean -fd
  else
    rm -rf "$repo_dir"
    echo "[sync $repo_dir] clone $repo_branch"
    git clone -b "$repo_branch" "$repo_url" "$repo_dir"
  fi
}
sync_frontend_repo ohr-feelin "https://${FRONTEND_GIT_HOST}/ohr/ohr-feelin.git" "$FEELIN_BRANCH"
sync_frontend_repo ohr-lowcode-engine "https://${FRONTEND_GIT_HOST}/ohr/ohr-lowcode-engine.git" "$LOWCODE_ENGINE_BRANCH"
sync_frontend_repo ohr-micro-frontends "https://${FRONTEND_GIT_HOST}/ohr/ohr-micro-frontends.git" "$MICRO_FRONTENDS_BRANCH"
sync_frontend_repo ohr-nocode-engine "https://${FRONTEND_GIT_HOST}/ohr/ohr-nocode-engine.git" "$NOCODE_ENGINE_BRANCH"
ohr-cli run-tasks --task install-modules-ohr
npm run setup:rm-yalc
"""


DIRECT_FRONTEND_BUILD_SCRIPT = r"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=8192}"
cd "$OHR_FRONTEND_WORKDIR"
npm i -g pnpm@10.22.0 --registry=https://registry.npmmirror.com/
npm i -g yarn@1.22.22 --registry=https://registry.npmmirror.com/
pnpm config set store-dir /opt/pnpm-cache || true
npm i yalc -g --registry=https://registry.npmmirror.com/
npm config set registry https://registry.smartcompany.cn/repository/npm-group/
npm config set //registry.smartcompany.cn/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-group/:_auth "$NPM_AUTH_B64"
npm i -g ohr-cli --registry=https://registry.smartcompany.cn/repository/npm-group/
apt-get update -qy && apt-get install -y zip
npm run build
mkdir -p "$(dirname "$OUT_WEB_ZIP")"
rm -f "$OUT_WEB_ZIP"
if [ -d dist ]; then
  zip -r "$OUT_WEB_ZIP" dist
elif [ -d build ]; then
  zip -r "$OUT_WEB_ZIP" build
else
  zip -r "$OUT_WEB_ZIP" . -x "node_modules/*" ".git/*" "*/node_modules/*" "*/.git/*"
fi
ls -lh "$OUT_WEB_ZIP"
"""


def direct_frontend_env(req: dict[str, Any], build_id: str) -> dict[str, str]:
    rel = req["frontend_release_branch"]
    token = os.environ.get("FRONTEND_GIT_TOKEN") or os.environ.get("OHR_BACK_GIT_TOKEN", "")
    host = urllib.parse.urlparse(FRONTEND_WORKSPACE_GIT_URL).hostname or "upds7.ujob100.com"
    return {
        "GIT_SYNC_URL": workspace_git_url_with_token(),
        "FRONTEND_GIT_TOKEN": token,
        "FRONTEND_GIT_HOST": host,
        "NPM_AUTH_B64": npm_auth_b64_value(),
        "OHR_FRONTEND_WORKDIR": str(FRONTEND_WORKSPACE_DIR),
        "FRONTEND_WS_BRANCH": req["frontend_workspace_branch"],
        "FRONTEND_REL_BRANCH": rel,
        "FRONTEND_FEELIN_BRANCH": req.get("frontend_feelin_branch") or rel,
        "FRONTEND_LOWCODE_BRANCH": req.get("frontend_lowcode_engine_branch") or rel,
        "FRONTEND_MF_BRANCH": req.get("frontend_micro_frontends_branch") or rel,
        "FRONTEND_NOCODE_BRANCH": req.get("frontend_nocode_engine_branch") or rel,
        "OHR_BUILD_ID": build_id,
        "OUT_WEB_ZIP": str(ARTIFACT_ROOT / build_id / "web.zip"),
    }


def list_backend_release_branches(limit: int = 200) -> list[str]:
    git_token = os.environ.get("OHR_BACK_GIT_TOKEN", "")
    remote = "origin"
    if git_token:
        remote = "https://oauth2:" + urllib.parse.quote(git_token, safe="") + "@upds7.ujob100.com/ohr/ohr-back.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", remote, "release_*"],
            cwd=str(OHR_BACK_DIR) if OHR_BACK_DIR.is_dir() else None,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    branches: list[str] = []
    for line in proc.stdout.splitlines():
        _, _, ref = line.partition("\t")
        if not ref.startswith("refs/heads/"):
            continue
        branch = ref.removeprefix("refs/heads/")
        if branch.startswith("release_") and BRANCH_RE.fullmatch(branch):
            branches.append(branch)
    branches = sorted(set(branches), reverse=True)
    return branches[:limit]


def list_release_branches_for_url(url: str, limit: int = 500) -> list[str]:
    if not url:
        return []
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", git_url_with_token(url), "release_*"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    branches: list[str] = []
    for line in proc.stdout.splitlines():
        _, _, ref = line.partition("\t")
        if not ref.startswith("refs/heads/"):
            continue
        branch = ref.removeprefix("refs/heads/")
        if branch.startswith("release_") and BRANCH_RE.fullmatch(branch):
            branches.append(branch)
    branches = sorted(set(branches), reverse=True)
    return branches[:limit]


def list_frontend_release_branches(limit: int = 200) -> list[str]:
    """列出四个前端子项目共同存在的 release_* 分支；ohr-workspace 使用 FRONTEND_WORKSPACE_BRANCH。"""
    branch_sets = [set(list_release_branches_for_url(url)) for url in FRONTEND_CHILD_REPOS.values()]
    if not branch_sets:
        return []
    common = set.intersection(*branch_sets)
    return sorted(common, reverse=True)[:limit]


def list_frontend_workspace_branches(limit: int = 200) -> list[str]:
    return list_frontend_release_branches(limit)


def run_command(
    build_id: str,
    command: str,
    cwd: Path,
    timeout: float | None = 7200,
    extra_env: dict[str, str] | None = None,
) -> int:
    ensure_not_cancelled(build_id)
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    append_log(build_id, f"$ {redact_secrets(command.splitlines()[0])[:200]}")
    proc = subprocess.Popen(
        ["bash", "-lc", command],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    BUILD_PROCS[build_id] = proc
    start = time.time()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            append_log(build_id, redact_secrets(line))
            if build_id in CANCELLED_BUILDS:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    proc.kill()
                raise BuildCancelled("用户停止了构建")
            if timeout is not None and time.time() - start > timeout:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    proc.kill()
                append_log(build_id, "命令超时，已终止。")
                return 124
        return proc.wait()
    finally:
        if BUILD_PROCS.get(build_id) is proc:
            BUILD_PROCS.pop(build_id, None)


def redact_secrets(text: str) -> str:
    for key in ("OHR_BACK_GIT_TOKEN", "FRONTEND_GIT_TOKEN"):
        tok = os.environ.get(key, "")
        if tok:
            text = text.replace(tok, "<redacted>")
    npm = os.environ.get("NPM_AUTH_B64", "")
    if npm:
        text = text.replace(npm, "<redacted>")
    text = re.sub(r"https://oauth2:[^@\s'\"<>]+@", "https://oauth2:<redacted>@", text)
    return text


def list_builds() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    builds = []
    for path in sorted(DATA_DIR.iterdir(), reverse=True):
        mp = path / "metadata.json"
        if mp.is_file():
            try:
                builds.append(read_json(mp))
            except json.JSONDecodeError:
                continue
    return builds


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            return self.send_html(INDEX_HTML)
        if path == "/app.js":
            return self.send_text(APP_JS, "application/javascript", no_cache=True)
        if path == "/style.css":
            return self.send_text(STYLE_CSS, "text/css", no_cache=True)
        if path == "/api/builds":
            return self.send_json({"builds": list_builds()})
        if path == "/api/backend-branches":
            return self.send_json({"branches": list_backend_release_branches()})
        if path == "/api/frontend-branches":
            return self.send_json({"branches": list_frontend_workspace_branches()})
        m = re.fullmatch(r"/api/builds/([^/]+)", path)
        if m:
            return self.send_build(m.group(1))
        m = re.fullmatch(r"/api/builds/([^/]+)/log", path)
        if m:
            qs = urllib.parse.parse_qs(parsed.query)
            offset = int(qs.get("offset", ["0"])[0] or 0)
            return self.send_log(m.group(1), offset)
        m = re.fullmatch(r"/api/builds/([^/]+)/artifact", path)
        if m:
            return self.send_artifact(m.group(1), "package.zip")
        m = re.fullmatch(r"/api/builds/([^/]+)/artifact/([^/]+)", path)
        if m:
            return self.send_artifact(m.group(1), urllib.parse.unquote(m.group(2)))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        m = re.fullmatch(r"/api/builds/([^/]+)/cancel", path)
        if m:
            try:
                meta = cancel_build(m.group(1))
            except FileNotFoundError:
                return self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return self.send_json(meta)
        if path != "/api/builds":
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            meta = create_build(payload)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        self.send_json(meta, HTTPStatus.CREATED)

    def send_build(self, build_id: str) -> None:
        path = metadata_path(build_id)
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_json(sync_drone_build(build_id))

    def send_log(self, build_id: str, offset: int) -> None:
        if metadata_path(build_id).is_file():
            sync_drone_build(build_id)
        path = log_path(build_id)
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        size = path.stat().st_size
        offset = max(0, min(offset, size))
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read().decode("utf-8", "replace")
        self.send_json({"offset": size, "text": chunk})

    def send_artifact(self, build_id: str, name: str) -> None:
        if name not in ("package.zip", "web.zip"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        if metadata_path(build_id).is_file():
            sync_drone_build(build_id)
        path = shared_artifact_path(build_id, name)
        if not path.is_file():
            path = artifact_path(build_id, name)
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        with path.open("rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, text: str) -> None:
        self.send_text(text, "text/html; charset=utf-8", no_cache=True)

    def send_text(self, text: str, content_type: str, no_cache: bool = False) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if no_cache:
            self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OHR 构建入口</title>
  <link rel="stylesheet" href="/style.css?v=3">
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <div class="eyebrow">OHR Build Console</div>
        <h1>统一构建入口</h1>
        <p class="muted">填写前后端分支参数，触发 CI 机上的本机构建流程，并在这里查看构建状态与实时日志。</p>
      </div>
      <div class="hero-panel">
        <span class="status-dot"></span>
        <div>
          <strong>本机构建模式</strong>
          <small>当前为 direct：由 8090 所在机器直接构建并产出 package.zip + web.zip</small>
        </div>
      </div>
    </section>
    <section class="card form-card">
      <div class="section-title">
        <div>
          <h2>构建参数</h2>
          <p class="muted">后端分支来自后端仓库；前端版本分支来自 feelin、lowcode、micro-frontends、nocode 四个子项目共同存在的 release_* 分支。ohr-workspace 固定使用 master。</p>
        </div>
      </div>
      <form id="build-form">
        <div class="target-row">
          <label class="toggle-option"><input id="toggle-backend" type="checkbox" checked> 构建后端 package.zip</label>
          <label class="toggle-option"><input id="toggle-frontend" type="checkbox" checked> 构建前端 web.zip</label>
        </div>
        <div class="form-grid">
          <div class="field-block">
            <label for="input-backend-branch">后端分支</label>
            <input id="input-backend-branch" name="backend_branch" list="backend-branches" placeholder="例如 release_20260129" autocomplete="off">
            <datalist id="backend-branches"></datalist>
          </div>
          <div class="field-block">
            <label for="input-frontend-release">前端版本分支（四个子项目共同存在）</label>
            <input id="input-frontend-release" list="frontend-branches" placeholder="例如 release_20260325" autocomplete="off">
            <datalist id="frontend-branches"></datalist>
          </div>
        </div>
        <details class="sync-hint">
          <summary>前端分支规则</summary>
          <p class="muted">ohr-workspace 不使用 release_* 分支，构建时固定检出 master；上方选择的版本分支会同时用于 ohr-feelin、ohr-lowcode-engine、ohr-nocode-engine、ohr-micro-frontends。若候选列表不全，可直接手输。</p>
        </details>
        <div class="form-grid">
          <label>备注 <input name="note" placeholder="例如：测试环境首次打包"></label>
        </div>
        <div class="form-grid">
          <div class="submit-row">
            <button id="start-button" type="submit">开始构建</button>
            <button id="stop-button" class="danger" type="button" hidden>停止构建</button>
          </div>
        </div>
      </form>
    </section>
    <section class="grid">
      <div class="card">
        <div class="section-title compact">
          <h2>构建记录</h2>
          <span class="muted">最近任务</span>
        </div>
        <div id="build-list"></div>
      </div>
      <div class="card">
        <div class="section-title compact">
          <h2>构建步骤</h2>
          <span class="muted">状态追踪</span>
        </div>
        <div id="build-detail" class="empty-state">请选择或启动一个构建。</div>
      </div>
    </section>
    <section class="card">
      <div class="section-title compact">
        <h2>实时日志</h2>
        <span class="muted">自动滚动</span>
      </div>
      <pre id="log"></pre>
    </section>
  </main>
  <script src="/app.js?v=8"></script>
</body>
</html>
"""


APP_JS = r"""
let currentBuild = null;
let logOffset = 0;
let timer = null;

const statusText = {
  queued: '排队中',
  running: '运行中',
  success: '成功',
  failed: '失败',
  cancelled: '已停止',
  pending: '等待',
  skipped: '跳过'
};

const statusLabel = {
  queued: 'queued',
  running: 'running',
  success: 'success',
  failed: 'failed',
  cancelled: 'cancelled',
  pending: 'pending',
  skipped: 'skipped'
};

const terminalStatuses = ['success', 'failed', 'cancelled'];

document.getElementById('build-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const buildBackend = document.getElementById('toggle-backend').checked;
  const buildFrontend = document.getElementById('toggle-frontend').checked;
  const backendBranch = (form.get('backend_branch') || '').trim();
  const ws = getFrontendWorkspaceBranch();
  if (!buildBackend && !buildFrontend) {
    setFormLocked(false);
    alert('请至少选择一个构建目标');
    return;
  }
  if (buildBackend && !backendBranch) {
    setFormLocked(false);
    alert('请选择或填写后端分支');
    return;
  }
  if (buildFrontend && !ws) {
    setFormLocked(false);
    alert('请选择或填写前端版本分支');
    return;
  }
  setFormLocked(true);
  const payload = {
    build_backend: buildBackend,
    build_frontend: buildFrontend,
    backend_branch: backendBranch,
    frontend_release_branch: ws,
    note: form.get('note')
  };
  const res = await fetch('/api/builds', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await res.json();
  if (!res.ok) {
    setFormLocked(false);
    alert(data.error || '创建构建失败');
    return;
  }
  selectBuild(data.id);
});

document.getElementById('stop-button').addEventListener('click', async () => {
  if (!currentBuild) return;
  const btn = document.getElementById('stop-button');
  btn.disabled = true;
  btn.textContent = '正在停止...';
  try {
    await fetch(`/api/builds/${currentBuild}/cancel`, { method: 'POST' });
    await refreshCurrent();
  } finally {
    btn.textContent = '停止构建';
  }
});

function setFormLocked(locked) {
  document.querySelectorAll('#build-form input, #build-form button').forEach(el => {
    if (el.id !== 'stop-button') el.disabled = locked;
  });
  document.getElementById('start-button').hidden = locked;
  document.getElementById('stop-button').hidden = !locked;
  document.getElementById('stop-button').disabled = false;
  if (!locked) syncBuildTargetInputs();
}

function syncBuildTargetInputs() {
  const backendToggle = document.getElementById('toggle-backend');
  const frontendToggle = document.getElementById('toggle-frontend');
  const backendInput = document.getElementById('input-backend-branch');
  const frontendInput = document.getElementById('input-frontend-release');
  backendInput.disabled = !backendToggle.checked;
  frontendInput.disabled = !frontendToggle.checked;
}

(function wireBuildTargetToggles() {
  const backendToggle = document.getElementById('toggle-backend');
  const frontendToggle = document.getElementById('toggle-frontend');
  function syncIfEditable() {
    if (document.getElementById('start-button').hidden) return;
    syncBuildTargetInputs();
  }
  backendToggle.addEventListener('change', syncIfEditable);
  frontendToggle.addEventListener('change', syncIfEditable);
  syncBuildTargetInputs();
})();

function getFrontendWorkspaceBranch() {
  const input = document.getElementById('input-frontend-release');
  return input ? (input.value || '').trim() : '';
}

function fillDatalist(id, branches) {
  const list = document.getElementById(id);
  if (!list) return;
  list.innerHTML = '';
  (branches || []).forEach(branch => {
    const option = document.createElement('option');
    option.value = branch;
    list.appendChild(option);
  });
}

async function loadBranchLists() {
  try {
    const [be, fe] = await Promise.all([
      fetch('/api/backend-branches').then(r => r.json()),
      fetch('/api/frontend-branches').then(r => r.json())
    ]);
    fillDatalist('backend-branches', be.branches);
    fillDatalist('frontend-branches', fe.branches);
  } catch (error) {
    console.warn('failed to load branch lists', error);
  }
}

async function loadBuilds() {
  const res = await fetch('/api/builds');
  const data = await res.json();
  const list = document.getElementById('build-list');
  list.innerHTML = '';
  if (!data.builds.length) {
    list.innerHTML = '<div class="empty-state small">还没有构建记录。</div>';
    return;
  }
  data.builds.forEach(build => {
    const item = document.createElement('button');
    item.className = 'build-item ' + build.status;
    item.innerHTML = `
      <span>
        <strong>${build.request.backend_branch}</strong>
        <small>${build.request.frontend_release_branch || build.request.frontend_workspace_branch || ''} · ${build.id}</small>
      </span>
      <em>${statusText[build.status] || build.status}</em>
    `;
    item.onclick = () => selectBuild(build.id);
    list.appendChild(item);
  });
}

function selectBuild(id) {
  currentBuild = id;
  logOffset = 0;
  document.getElementById('log').textContent = '';
  if (timer) clearInterval(timer);
  refreshCurrent();
  timer = setInterval(refreshCurrent, 2000);
}

async function refreshCurrent() {
  await loadBuilds();
  if (!currentBuild) return;
  const res = await fetch(`/api/builds/${currentBuild}`);
  if (!res.ok) return;
  const build = await res.json();
  renderDetail(build);
  setFormLocked(!terminalStatuses.includes(build.status));
  const logRes = await fetch(`/api/builds/${currentBuild}/log?offset=${logOffset}`);
  const logData = await logRes.json();
  logOffset = logData.offset;
  if (logData.text) {
    const pre = document.getElementById('log');
    pre.textContent += logData.text;
    pre.scrollTop = pre.scrollHeight;
  }
  if (terminalStatuses.includes(build.status) && timer) {
    clearInterval(timer);
    timer = null;
  }
}

function renderDetail(build) {
  const box = document.getElementById('build-detail');
  const artifactLinks = (build.artifacts || (build.artifact ? [build.artifact] : [])).map(item => (
    `<a class="artifact-link" href="/api/builds/${build.id}/artifact/${item.name}">下载 ${item.name}</a>`
  )).join('');
  box.innerHTML = `
    <div class="summary-panel">
      <div>
        <div class="muted">构建编号</div>
        <strong>${build.id}</strong>
      </div>
      <div>
        <div class="muted">后端分支</div>
        <strong>${build.request.backend_branch}</strong>
      </div>
      <div>
        <div class="muted">前端版本分支</div>
        <strong>${build.request.frontend_release_branch || build.request.frontend_workspace_branch || ''}</strong>
      </div>
      <div>
        <div class="muted">workspace 分支</div>
        <strong>${build.request.frontend_workspace_branch || ''}</strong>
      </div>
      <div>
        <div class="muted">执行器</div>
        <strong>${build.executor}</strong>
      </div>
      <span class="pill ${build.status}">${statusText[build.status] || build.status}</span>
      ${artifactLinks}
    </div>
    <ol class="steps">
      ${build.steps.map((step, index) => `
        <li class="${step.status}">
          <span class="step-index">${index + 1}</span>
          <span class="step-main">
            <strong>${step.label}</strong>
            <small>${step.message || statusLabel[step.status] || step.status}</small>
          </span>
          <em>${statusText[step.status] || step.status}</em>
        </li>
      `).join('')}
    </ol>
  `;
}

loadBranchLists();
loadBuilds();
setInterval(loadBuilds, 5000);
"""


STYLE_CSS = """
:root {
  --bg: #f6f7fb;
  --panel: rgba(255, 255, 255, .86);
  --panel-strong: #ffffff;
  --line: #e5e8ef;
  --text: #111827;
  --muted: #6b7280;
  --blue: #2563eb;
  --blue-soft: #eff6ff;
  --green: #16a34a;
  --green-soft: #ecfdf3;
  --red: #dc2626;
  --red-soft: #fef2f2;
  --amber: #d97706;
  --amber-soft: #fffbeb;
  --shadow: 0 18px 50px rgba(15, 23, 42, .08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 15% 0%, rgba(37, 99, 235, .12), transparent 30%),
    radial-gradient(circle at 85% 10%, rgba(20, 184, 166, .11), transparent 28%),
    linear-gradient(180deg, #f8fafc 0%, var(--bg) 45%, #eef2f7 100%);
  color: var(--text);
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
main { max-width: 1220px; margin: 0 auto; padding: 34px 26px 42px; }
h1, h2 { margin: 0; letter-spacing: -.03em; }
h1 { font-size: clamp(34px, 5vw, 54px); line-height: 1; }
h2 { font-size: 19px; }
.muted { color: var(--muted); font-size: 13px; }
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  margin-bottom: 24px;
  padding: 32px;
  border: 1px solid rgba(255, 255, 255, .65);
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(255,255,255,.94), rgba(255,255,255,.64));
  box-shadow: var(--shadow);
  backdrop-filter: blur(14px);
}
.hero p { max-width: 700px; margin: 16px 0 0; color: #4b5563; font-size: 16px; line-height: 1.7; }
.eyebrow {
  display: inline-flex;
  margin-bottom: 14px;
  padding: 7px 11px;
  border: 1px solid #dbeafe;
  border-radius: 999px;
  color: #1d4ed8;
  background: rgba(239, 246, 255, .8);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.hero-panel {
  min-width: 245px;
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255,255,255,.8);
}
.hero-panel small { display: block; margin-top: 4px; color: var(--muted); }
.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: var(--green);
  box-shadow: 0 0 0 7px rgba(22, 163, 74, .12);
}
.card {
  background: var(--panel);
  border: 1px solid rgba(226, 232, 240, .9);
  border-radius: 24px;
  padding: 22px;
  margin-bottom: 20px;
  box-shadow: 0 10px 32px rgba(15, 23, 42, .06);
  backdrop-filter: blur(10px);
}
.form-card { padding: 26px; }
.grid { display: grid; grid-template-columns: .9fr 1.45fr; gap: 20px; }
.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.section-title p { margin: 7px 0 0; }
.section-title.compact { align-items: center; margin-bottom: 14px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-block > label:first-child {
  margin: 0;
}
label { display: block; color: #374151; font-size: 13px; font-weight: 800; margin: 0 0 16px; }
input, textarea, select {
  width: 100%;
  margin-top: 8px;
  border: 1px solid #d7dce5;
  border-radius: 14px;
  padding: 12px 13px;
  color: var(--text);
  background: rgba(255,255,255,.92);
  font: inherit;
  outline: none;
  transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
}
.field-block input,
.field-block select {
  margin-top: 0;
}
select {
  cursor: pointer;
  background-color: rgba(255, 255, 255, .92);
}
input:focus, textarea:focus, select:focus {
  border-color: rgba(37, 99, 235, .65);
  box-shadow: 0 0 0 4px rgba(37, 99, 235, .10);
  background: #fff;
}
textarea { resize: vertical; line-height: 1.55; }
details.sync-hint {
  margin: 14px 0 4px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: rgba(248, 250, 252, .72);
}
details.sync-hint summary {
  cursor: pointer;
  font-weight: 800;
  font-size: 13px;
  color: #374151;
  user-select: none;
}
details.sync-hint p { margin: 10px 0 0; line-height: 1.6; }
.target-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0 0 16px;
}
.toggle-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: rgba(248, 250, 252, .72);
}
.toggle-option input {
  width: auto;
  margin: 0;
}
.field-block input:disabled {
  color: #94a3b8;
  background: #f1f5f9;
  cursor: not-allowed;
}
.submit-row { display: flex; align-items: flex-end; justify-content: flex-end; padding-bottom: 16px; }
button {
  border: 0;
  border-radius: 14px;
  padding: 12px 17px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: white;
  cursor: pointer;
  font-weight: 800;
  box-shadow: 0 12px 24px rgba(37, 99, 235, .22);
  transition: transform .14s ease, box-shadow .14s ease, filter .14s ease;
}
button:hover { transform: translateY(-1px); filter: brightness(1.03); box-shadow: 0 16px 28px rgba(37, 99, 235, .26); }
button:disabled {
  cursor: not-allowed;
  opacity: .65;
  transform: none;
  filter: none;
}
button.danger {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
  box-shadow: 0 12px 24px rgba(220, 38, 38, .20);
}
.build-item {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin: 9px 0;
  padding: 13px 14px;
  text-align: left;
  color: var(--text);
  background: var(--panel-strong);
  border: 1px solid var(--line);
  box-shadow: none;
}
.build-item strong { display: block; max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.build-item small { display: block; margin-top: 5px; color: var(--muted); font-weight: 600; }
.build-item em, .steps em {
  flex: none;
  font-style: normal;
  font-size: 12px;
  font-weight: 800;
  color: var(--muted);
}
.build-item.success { background: var(--green-soft); border-color: #bbf7d0; }
.build-item.failed { background: var(--red-soft); border-color: #fecaca; }
.build-item.cancelled { background: #f8fafc; border-color: #cbd5e1; }
.build-item.running, .build-item.queued { background: var(--blue-soft); border-color: #bfdbfe; }
.summary-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  align-items: center;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: var(--panel-strong);
}
.summary-panel strong { display: block; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill {
  justify-self: start;
  border-radius: 999px;
  padding: 7px 11px;
  color: #475569;
  background: #f1f5f9;
  font-size: 12px;
  font-weight: 900;
}
.pill.running, .pill.queued { color: #1d4ed8; background: #dbeafe; }
.pill.success { color: #15803d; background: #dcfce7; }
.pill.failed { color: #b91c1c; background: #fee2e2; }
.pill.cancelled { color: #475569; background: #e2e8f0; }
.artifact-link {
  color: #1d4ed8;
  font-weight: 900;
  text-decoration: none;
}
.steps { list-style: none; padding: 0; margin: 18px 0 0; }
.steps li {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: 12px;
  align-items: center;
  padding: 13px 14px;
  margin: 10px 0;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--panel-strong);
}
.step-index {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 10px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 900;
}
.step-main strong { display: block; }
.step-main small { display: block; margin-top: 4px; color: var(--muted); }
.steps li.running { border-color: #bfdbfe; background: var(--blue-soft); }
.steps li.running .step-index { color: #1d4ed8; background: #dbeafe; }
.steps li.success { border-color: #bbf7d0; background: var(--green-soft); }
.steps li.success .step-index { color: #15803d; background: #dcfce7; }
.steps li.failed { border-color: #fecaca; background: var(--red-soft); }
.steps li.failed .step-index { color: #b91c1c; background: #fee2e2; }
.steps li.cancelled { border-color: #cbd5e1; background: #f8fafc; }
.steps li.cancelled .step-index { color: #475569; background: #e2e8f0; }
.steps li.skipped { border-color: #fde68a; background: var(--amber-soft); }
.steps li.skipped .step-index { color: var(--amber); background: #fef3c7; }
.empty-state {
  padding: 34px;
  border: 1px dashed #cbd5e1;
  border-radius: 18px;
  color: var(--muted);
  text-align: center;
  background: rgba(248, 250, 252, .7);
}
.empty-state.small { padding: 20px; }
pre {
  height: 430px;
  overflow: auto;
  margin: 0;
  background: linear-gradient(180deg, #0b1220, #111827);
  color: #d1d5db;
  border: 1px solid rgba(148, 163, 184, .18);
  border-radius: 18px;
  padding: 18px;
  white-space: pre-wrap;
  font: 13px/1.65 "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
}
@media (max-width: 980px) {
  .hero, .grid, .form-grid { grid-template-columns: 1fr; display: grid; }
  .hero { align-items: stretch; }
  .summary-panel { grid-template-columns: 1fr; }
  .submit-row { justify-content: stretch; }
  .submit-row button { width: 100%; }
}
"""


def main() -> int:
    load_env_file(CONFIG_FILE)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"build-console listening on http://{HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
