#!/usr/bin/env python3
from __future__ import annotations

import base64
import io
import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT))

from drone_adapter import DroneBuildRef, DroneExecutorAdapter

DATA_DIR = Path(os.environ.get("BUILD_CONSOLE_DATA_DIR", ROOT / "builds"))
OHR_BACK_DIR = Path(os.environ.get("OHR_BACK_DIR", "/root/ohr-back"))
OHR_BACK_GIT_URL = os.environ.get("OHR_BACK_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-back.git")
ARTIFACT_ROOT = Path(os.environ.get("BUILD_ARTIFACT_ROOT", "/opt/ohr-build-artifacts"))
PRODUCT_VARIANTS = ("standard", "nho")
NHO_BACK_DIR = Path(os.environ.get("NHO_BACK_DIR", "/root/nho-ohr-back"))
NHO_BACK_GIT_URL = os.environ.get("NHO_BACK_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-back.git")
NHO_FRONTEND_WORKSPACE_DIR = Path(os.environ.get("NHO_FRONTEND_WORKSPACE_DIR", "/opt/nho-ohr-workspace-src"))
NHO_FRONTEND_WORKSPACE_GIT_URL = os.environ.get(
    "NHO_FRONTEND_WORKSPACE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-workspace.git"
)
NHO_FRONTEND_CHILD_REPOS = {
    "frontend_micro_frontends_branch": os.environ.get(
        "NHO_FRONTEND_MICRO_FRONTENDS_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-micro-frontends.git"
    ),
    "frontend_lowcode_engine_branch": os.environ.get(
        "NHO_FRONTEND_LOWCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-lowcode-engine.git"
    ),
    "frontend_nocode_engine_branch": os.environ.get(
        "NHO_FRONTEND_NOCODE_ENGINE_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-nocode-engine.git"
    ),
    "frontend_nencho_branch": os.environ.get(
        "NHO_FRONTEND_NENCHO_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-web-nencho.git"
    ),
}
NHO_FRONTEND_FEELIN_GIT_URL = os.environ.get("NHO_FRONTEND_FEELIN_GIT_URL", "https://upds7.ujob100.com/nhophr/ohr-feelin.git")
NHO_FRONTEND_WORKSPACE_BRANCH = os.environ.get("NHO_FRONTEND_WORKSPACE_BRANCH", "master")
NHO_FRONTEND_FEELIN_BRANCH = os.environ.get("NHO_FRONTEND_FEELIN_BRANCH", "master")
NHO_PNPM_CACHE_DIR = os.environ.get("NHO_PNPM_CACHE_DIR", "/opt/nho-pnpm-cache")
NHO_YARN_CACHE_DIR = os.environ.get("NHO_YARN_CACHE_DIR", "/opt/nho-yarn-cache")
NHO_MAVEN_CACHE_DIR = os.environ.get("NHO_MAVEN_CACHE_DIR", "/opt/nho-maven-cache")
NHO_BACK_MAVEN_IMAGE = os.environ.get("NHO_BACK_MAVEN_IMAGE", "maven:3.9.6-eclipse-temurin-22")
NHO_MATERIAL_SVN_URL = os.environ.get(
    "NHO_MATERIAL_SVN_URL",
    "http://3.115.155.21/svn/nho4phr/大連側/97.リリース作業",
)
NHO_MATERIAL_SVN_USERNAME = os.environ.get("NHO_MATERIAL_SVN_USERNAME", "")
NHO_MATERIAL_SVN_PASSWORD = os.environ.get("NHO_MATERIAL_SVN_PASSWORD", "")
NHO_MATERIAL_CACHE_SECONDS = int(os.environ.get("NHO_MATERIAL_CACHE_SECONDS", "300"))
STANDARD_MATERIAL_SVN_URL = os.environ.get(
    "STANDARD_MATERIAL_SVN_URL",
    "http://192.168.21.111/svn/PHR1.5/98.環境構築手順書/お客様環境",
)
STANDARD_MATERIAL_SVN_USERNAME = os.environ.get("STANDARD_MATERIAL_SVN_USERNAME", "")
STANDARD_MATERIAL_SVN_PASSWORD = os.environ.get("STANDARD_MATERIAL_SVN_PASSWORD", "")
STANDARD_MATERIAL_CACHE_SECONDS = int(os.environ.get("STANDARD_MATERIAL_CACHE_SECONDS", "300"))
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
HELP_DOCS_GIT_URL = os.environ.get("HELP_DOCS_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-help-docs.git")
HELP_DOCS_BRANCH = os.environ.get("HELP_DOCS_BRANCH", "release_ci")
HELP_DOCS_DIR = Path(os.environ.get("HELP_DOCS_DIR", "/opt/ohr-help-docs-src"))
HELP_DOCS_SVN_URL = os.environ.get(
    "HELP_DOCS_SVN_URL",
    "http://192.168.21.111/svn/PHR1.5/30.マニュアル/マニュアル(日本語版)",
)
HELP_DOCS_SVN_DIR = Path(os.environ.get("HELP_DOCS_SVN_DIR", "/opt/ohr-help-docs-svn"))
HELP_DOCS_SVN_USERNAME = os.environ.get("HELP_DOCS_SVN_USERNAME", "")
HELP_DOCS_SVN_PASSWORD = os.environ.get("HELP_DOCS_SVN_PASSWORD", "")
HELP_DOCS_SVN_REVISION_RE = re.compile(r"^\d+$")
CONF_PROD_TEMPLATE_DIR = Path(os.environ.get("CONF_PROD_TEMPLATE_DIR", "/opt/ohr-build-console/conf_prod_template"))
OHR_CICD_GIT_URL = os.environ.get("OHR_CICD_GIT_URL", "https://upds7.ujob100.com/ohr/ohr-cicd.git")
OHR_CICD_BRANCH = os.environ.get("OHR_CICD_BRANCH", "master")
OHR_CICD_DIR = Path(os.environ.get("OHR_CICD_DIR", "/opt/ohr-cicd-src"))
OHR_CICD_ENV = os.environ.get("OHR_CICD_ENV", "direct_prod")
OHR_CICD_SERVICE_GATEWAY = os.environ.get("OHR_CICD_SERVICE_GATEWAY", "http://localhost:3198/")
OHR_CICD_MINIO_SERVER = os.environ.get("OHR_CICD_MINIO_SERVER", "http://localhost:19000")
OHR_CICD_MINIO_HOST = os.environ.get("OHR_CICD_MINIO_HOST", "localhost:19000")
OHR_CICD_RUSTFS_SERVER = os.environ.get("OHR_CICD_RUSTFS_SERVER", "http://127.0.0.1:12345")
OHR_CICD_RUSTFS_HOST = os.environ.get("OHR_CICD_RUSTFS_HOST", "127.0.0.1:12345")
DATA_SYNC_GIT_URL = os.environ.get("DATA_SYNC_GIT_URL", "https://upds7.ujob100.com/ohr/data-synchronization.git")
DATA_SYNC_BRANCH = os.environ.get("DATA_SYNC_BRANCH", "master")
DATA_SYNC_DIR = Path(os.environ.get("DATA_SYNC_DIR", "/opt/ohr-build-console/data-synchronization"))
HOST = os.environ.get("BUILD_CONSOLE_HOST", "0.0.0.0")
PORT = int(os.environ.get("BUILD_CONSOLE_PORT", "8090"))
CONFIG_FILE = Path(os.environ.get("BUILD_CONSOLE_ENV", ROOT / "build-console.env"))
EXECUTOR = os.environ.get("BUILD_EXECUTOR", "direct")
DRONE_SERVER_URL = os.environ.get("DRONE_SERVER_URL", "http://127.0.0.1:8080")
DRONE_TOKEN = os.environ.get("DRONE_TOKEN", "")
DRONE_CONTROL_REPO = os.environ.get("DRONE_CONTROL_REPO", "")
DRONE_CONTROL_BRANCH = os.environ.get("DRONE_CONTROL_BRANCH", "master")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
CONF_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
NHO_MATERIAL_RE = re.compile(r"^(\d{8})リリース作業$")
STANDARD_MATERIAL_RE = re.compile(r"^資材[-_](\d{8})$")
XLSX_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
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
NHO_MATERIAL_CACHE: dict[str, Any] = {"expires_at": 0.0, "numbers": []}
STANDARD_MATERIAL_CACHE: dict[str, Any] = {"expires_at": 0.0, "numbers": [], "dirs": {}}
DATA_SYNC_VALIDATE_LOCK = threading.Lock()


class SvnIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


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


def normalise_product_variant(product_variant: str | None) -> str:
    value = str(product_variant or "standard").strip().lower()
    return value if value in PRODUCT_VARIANTS else "standard"


def variant_build_root(product_variant: str) -> Path:
    return DATA_DIR / normalise_product_variant(product_variant)


def variant_artifact_root(product_variant: str) -> Path:
    return ARTIFACT_ROOT / normalise_product_variant(product_variant)


def build_dir(build_id: str, product_variant: str | None = None) -> Path:
    if product_variant:
        return variant_build_root(product_variant) / build_id
    for variant in PRODUCT_VARIANTS:
        candidate = variant_build_root(variant) / build_id
        if candidate.exists():
            return candidate
    legacy = DATA_DIR / build_id
    if legacy.exists():
        return legacy
    return DATA_DIR / build_id


def metadata_path(build_id: str, product_variant: str | None = None) -> Path:
    return build_dir(build_id, product_variant) / "metadata.json"


def log_path(build_id: str, product_variant: str | None = None) -> Path:
    return build_dir(build_id, product_variant) / "build.log"


def artifact_path(build_id: str, name: str = "package.zip", product_variant: str | None = None) -> Path:
    return build_dir(build_id, product_variant) / name


def shared_artifact_path(build_id: str, name: str, product_variant: str | None = None) -> Path:
    if product_variant:
        return variant_artifact_root(product_variant) / build_id / name
    for variant in PRODUCT_VARIANTS:
        candidate = variant_artifact_root(variant) / build_id / name
        if candidate.exists():
            return candidate
    legacy = ARTIFACT_ROOT / build_id / name
    if legacy.exists():
        return legacy
    return ARTIFACT_ROOT / build_id / name


def cleanup_previous_build_outputs(product_variant: str, current_build_id: str) -> int:
    variant = normalise_product_variant(product_variant)
    freed_bytes = 0
    artifact_root = variant_artifact_root(variant)
    if artifact_root.exists():
        for child in artifact_root.iterdir():
            if child.name != current_build_id:
                freed_bytes += path_size_bytes(child)
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
    current_shared = artifact_root / current_build_id
    freed_bytes += path_size_bytes(current_shared)
    shutil.rmtree(current_shared, ignore_errors=True)
    current_shared.mkdir(parents=True, exist_ok=True)

    for root in (variant_build_root(variant), DATA_DIR):
        if not root.exists():
            continue
        for build_root in root.iterdir():
            if not build_root.is_dir() or build_root.name == current_build_id:
                continue
            for name in ("package.zip", "web.zip"):
                artifact = build_root / name
                freed_bytes += path_size_bytes(artifact)
                artifact.unlink(missing_ok=True)

    if ARTIFACT_ROOT.exists():
        for child in ARTIFACT_ROOT.iterdir():
            if child.name in PRODUCT_VARIANTS or child.name == current_build_id:
                continue
            if child.is_dir():
                freed_bytes += path_size_bytes(child)
                shutil.rmtree(child, ignore_errors=True)
    freed_bytes += cleanup_workspace_build_outputs(variant)
    return freed_bytes


def cleanup_workspace_build_outputs(product_variant: str) -> int:
    variant = normalise_product_variant(product_variant)
    targets: list[Path] = []
    back_dir = NHO_BACK_DIR if variant == "nho" else OHR_BACK_DIR
    frontend_dir = NHO_FRONTEND_WORKSPACE_DIR if variant == "nho" else FRONTEND_WORKSPACE_DIR
    targets.extend([back_dir / "package.zip", back_dir / "package"])
    if frontend_dir.exists():
        targets.extend(frontend_dir.glob("release_*.zip"))
        targets.extend(path for path in frontend_dir.glob("release_*") if path.is_dir())
    if variant == "standard":
        for work_dir in (HELP_DOCS_DIR, OHR_CICD_DIR):
            if work_dir.exists():
                targets.extend(work_dir.glob("ohr_help_docs_release_*.zip"))
                targets.extend(path for path in work_dir.glob("ohr_help_docs_release_*") if path.is_dir())
        targets.extend([HELP_DOCS_DIR / "build", HELP_DOCS_DIR / "markdowns"])

    freed_bytes = 0
    for target in targets:
        freed_bytes += path_size_bytes(target)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    return freed_bytes


def path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def disk_free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024


def memory_available_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return None
    for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1]) * 1024
    return None


def system_resource_status() -> dict[str, Any]:
    return {
        "cpu_count": os.cpu_count() or 0,
        "memory_available_bytes": memory_available_bytes(),
        "disk_free_bytes": disk_free_bytes(ARTIFACT_ROOT),
    }


def build_id_exists(build_id: str) -> bool:
    if (DATA_DIR / build_id).exists():
        return True
    return any((variant_build_root(variant) / build_id).exists() for variant in PRODUCT_VARIANTS)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_int_field(payload: dict[str, Any], key: str, default: int) -> int:
    raw = payload.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"{key} 必须是数字") from exc


def parse_bool_field(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    raw = payload.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def append_log(build_id: str, line: str) -> None:
    with log_path(build_id).open("a", encoding="utf-8") as f:
        f.write(strip_ansi_escape(line).rstrip("\n") + "\n")


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi_escape(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


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
    product_variant = str(payload.get("product_variant") or "standard").strip().lower()
    if product_variant not in ("standard", "nho"):
        raise ValueError("product_variant 仅允许 standard 或 nho")
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
    help_docs_branch = HELP_DOCS_BRANCH.strip()
    help_docs_svn_revision = str(payload.get("help_docs_svn_revision") or "").strip()
    build_help = parse_bool_field(payload, "build_help", True)
    build_conf_prod = parse_bool_field(payload, "build_conf_prod", True)
    conf_server_host = str(payload.get("conf_server_host") or "").strip()
    conf_web_port = parse_int_field(payload, "conf_web_port", 80)
    conf_enable_https = parse_bool_field(payload, "conf_enable_https", False)
    conf_worker_processes = parse_int_field(payload, "conf_worker_processes", 1)
    conf_worker_connections = parse_int_field(payload, "conf_worker_connections", 1024)
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
    if product_variant == "standard" and build_frontend and not help_docs_branch:
        raise ValueError("请填写 Help 文档分支")
    if product_variant == "standard" and help_docs_branch and not BRANCH_RE.fullmatch(help_docs_branch):
        raise ValueError("Help 文档分支名仅允许字母、数字、._/-")
    if product_variant == "standard" and help_docs_svn_revision and not HELP_DOCS_SVN_REVISION_RE.fullmatch(help_docs_svn_revision):
        raise ValueError("Help SVN revision 仅允许数字")
    if product_variant == "standard" and build_frontend and build_help and help_docs_svn_revision:
        revision_check = validate_help_docs_svn_revision(help_docs_svn_revision)
        if not revision_check.get("ok"):
            raise ValueError("Help SVN revision 不存在")
    if build_conf_prod and build_frontend and not conf_server_host:
        raise ValueError("请填写客户访问地址")
    if conf_server_host and not CONF_HOST_RE.fullmatch(conf_server_host):
        raise ValueError("客户访问地址仅允许字母、数字、点和中划线")
    if build_conf_prod and build_frontend and not (1 <= conf_web_port <= 65535):
        raise ValueError("Web 端口必须在 1-65535 之间")
    if build_conf_prod and build_frontend and conf_worker_processes < 1:
        raise ValueError("worker_processes 必须大于 0")
    if build_conf_prod and build_frontend and conf_worker_connections < 1:
        raise ValueError("worker_connections 必须大于 0")
    # ohr-workspace 不跟随 release_*；它固定使用配置分支。用户选择的是四个子项目共同存在的版本分支。
    frontend_workspace_branch = NHO_FRONTEND_WORKSPACE_BRANCH if product_variant == "nho" else FRONTEND_WORKSPACE_BRANCH
    frontend_feelin_branch = NHO_FRONTEND_FEELIN_BRANCH if product_variant == "nho" else frontend_release_branch
    frontend_lowcode_engine_branch = frontend_release_branch
    frontend_micro_frontends_branch = frontend_release_branch
    frontend_nocode_engine_branch = frontend_release_branch
    frontend_nencho_branch = frontend_release_branch

    if EXECUTOR == "drone":
        if not DRONE_CONTROL_REPO or not DRONE_TOKEN:
            raise ValueError("Drone 执行器未配置 DRONE_CONTROL_REPO 或 DRONE_TOKEN")

    build_id = isoish()
    suffix = 1
    while build_id_exists(build_id):
        suffix += 1
        build_id = f"{isoish()}-{suffix}"

    build_dir(build_id, product_variant).mkdir(parents=True, exist_ok=False)
    log_path(build_id, product_variant).write_text("", encoding="utf-8")
    meta = {
        "id": build_id,
        "executor": EXECUTOR,
        "status": "queued",
        "created_at": now(),
        "updated_at": now(),
        "request": {
            "product_variant": product_variant,
            "backend_branch": backend_branch,
            "frontend_workspace_branch": frontend_workspace_branch,
            "frontend_release_branch": frontend_release_branch,
            "frontend_feelin_branch": frontend_feelin_branch,
            "frontend_lowcode_engine_branch": frontend_lowcode_engine_branch,
            "frontend_micro_frontends_branch": frontend_micro_frontends_branch,
            "frontend_nocode_engine_branch": frontend_nocode_engine_branch,
            "frontend_nencho_branch": frontend_nencho_branch,
            "help_docs_branch": help_docs_branch,
            "help_docs_svn_revision": help_docs_svn_revision,
            "build_help": build_help,
            "build_conf_prod": build_conf_prod,
            "conf_server_host": conf_server_host,
            "conf_web_port": conf_web_port,
            "conf_enable_https": conf_enable_https,
            "conf_worker_processes": conf_worker_processes,
            "conf_worker_connections": conf_worker_connections,
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
        product_variant = request.get("product_variant") or "standard"
        build_backend = bool(request.get("build_backend", True))
        build_frontend = bool(request.get("build_frontend", True))
        branch = request["backend_branch"]
        append_log(
            build_id,
            f"构建开始：product_variant={product_variant}, build_backend={build_backend}, build_frontend={build_frontend}, "
            f"backend_branch={branch or '-'}, frontend_release_branch={request.get('frontend_release_branch') or '-'}",
        )
        cleanup_previous_build_outputs(product_variant, build_id)

        update_step(build_id, "validate", "running")
        back_dir = NHO_BACK_DIR if product_variant == "nho" else OHR_BACK_DIR
        if product_variant == "standard" and build_backend and not back_dir.is_dir():
            raise RuntimeError(f"后端目录不存在：{OHR_BACK_DIR}")
        if build_frontend and not os.environ.get("OHR_BACK_GIT_TOKEN") and not os.environ.get("FRONTEND_GIT_TOKEN"):
            raise RuntimeError("需配置 OHR_BACK_GIT_TOKEN 或 FRONTEND_GIT_TOKEN 以克隆前端 workspace")
        update_step(build_id, "validate", "success")

        if build_backend:
            update_step(build_id, "checkout_backend", "running")
            checkout = nho_checkout_command(branch) if product_variant == "nho" else checkout_command(branch)
            back_dir.mkdir(parents=True, exist_ok=True)
            rc = run_command(build_id, checkout, cwd=back_dir)
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("后端代码检出失败")
            update_step(build_id, "checkout_backend", "success")

            update_step(build_id, "build_backend", "running")
            build_script = nho_build_command() if product_variant == "nho" else build_command()
            rc = run_command(build_id, build_script, cwd=back_dir, timeout=None)
            ensure_not_cancelled(build_id)
            if rc != 0:
                raise RuntimeError("后端打包失败")
            update_step(build_id, "build_backend", "success")
        else:
            update_step(build_id, "checkout_backend", "skipped", "未选择后端构建")
            update_step(build_id, "build_backend", "skipped", "未选择后端构建")

        variant_artifact_root(product_variant).joinpath(build_id).mkdir(parents=True, exist_ok=True)
        if build_frontend:
            fe_env = nho_frontend_env(request, build_id) if product_variant == "nho" else direct_frontend_env(request, build_id)
            restore_script = NHO_FRONTEND_RESTORE_SCRIPT if product_variant == "nho" else DIRECT_FRONTEND_RESTORE_SCRIPT
            build_script = NHO_FRONTEND_BUILD_SCRIPT if product_variant == "nho" else DIRECT_FRONTEND_BUILD_SCRIPT

            update_step(build_id, "restore_frontend", "running")
            rc = run_command(
                build_id,
                restore_script,
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
                build_script,
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
        pkg_src = back_dir / "package.zip"
        web_src = shared_artifact_path(build_id, "web.zip", product_variant)
        if build_backend and not pkg_src.is_file():
            raise RuntimeError(f"未找到产物：{pkg_src}")
        if build_frontend and not web_src.is_file():
            raise RuntimeError(f"未找到产物：{web_src}")
        if build_backend:
            shutil.copy2(pkg_src, artifact_path(build_id, "package.zip", product_variant))
            shutil.copy2(pkg_src, shared_artifact_path(build_id, "package.zip", product_variant))
        if build_frontend:
            shutil.copy2(web_src, artifact_path(build_id, "web.zip", product_variant))
        artifacts = []
        for name in ("package.zip", "web.zip"):
            p = artifact_path(build_id, name, product_variant)
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
    product_variant = normalise_product_variant((meta.get("request") or {}).get("product_variant"))
    artifacts = []
    for name in ("package.zip", "web.zip"):
        path = shared_artifact_path(build_id, name, product_variant)
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


def delete_build(build_id: str) -> dict[str, Any]:
    path = metadata_path(build_id)
    if not path.is_file():
        raise FileNotFoundError(build_id)
    meta = read_json(path)
    product_variant = normalise_product_variant((meta.get("request") or {}).get("product_variant"))
    if meta.get("status") in ("queued", "running"):
        return {"ok": False, "error": "build_running"}
    BUILD_THREADS.pop(build_id, None)
    BUILD_PROCS.pop(build_id, None)
    CANCELLED_BUILDS.discard(build_id)
    shutil.rmtree(build_dir(build_id, product_variant), ignore_errors=True)
    shutil.rmtree(DATA_DIR / build_id, ignore_errors=True)
    shutil.rmtree(variant_artifact_root(product_variant) / build_id, ignore_errors=True)
    shutil.rmtree(ARTIFACT_ROOT / build_id, ignore_errors=True)
    return {"ok": True, "id": build_id}


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


def nho_checkout_command(branch: str) -> str:
    repo = shell_quote(git_url_with_token(NHO_BACK_GIT_URL))
    b = shell_quote(branch)
    return f"""set -euo pipefail
if [ -d .git ]; then
  git remote set-url origin {repo}
  git fetch origin {b} --prune
  git checkout -B {b} FETCH_HEAD
  git reset --hard FETCH_HEAD
  git clean -fd
else
  find . -mindepth 1 -maxdepth 1 -exec rm -rf {{}} +
  git clone --depth=1 -b {b} {repo} .
fi
git rev-parse --short HEAD
"""


def nho_build_command() -> str:
    cache_dir = shell_quote(NHO_MAVEN_CACHE_DIR)
    image = shell_quote(NHO_BACK_MAVEN_IMAGE)
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
mkdir -p {cache_dir}
mkdir -p .ci-cache
cat > .ci-cache/nho-maven-settings.xml <<'EOF'
{settings}
EOF
chmod 600 .ci-cache/nho-maven-settings.xml
rm -rf ./package ./package.zip
docker run --rm \\
  -e MAVEN_OPTS="-Xmx2048m -Xms256m -XX:+UseG1GC -Dmaven.compiler.fork=true -Dmaven.compiler.meminitial=256m -Dmaven.compiler.maxmem=1536m" \\
  -v "$PWD":/workspace \\
  -v {cache_dir}:/root/.m2/repository \\
  -v "$PWD/.ci-cache/nho-maven-settings.xml":/root/.m2/settings.xml:ro \\
  -w /workspace \\
  {image} \\
  bash -lc 'java -version && mvn -version | head -8 && chmod +x ./collect-pkg.sh && ./collect-pkg.sh'
if [ ! -d ./package ]; then
  echo "NHO package directory was not generated: ./package"
  exit 8
fi
if ! find ./package -maxdepth 1 -type f -name '*.jar' | grep -q .; then
  echo "NHO package directory has no jar files; collect-pkg.sh likely failed."
  exit 9
fi
zip -r package.zip ./package
ls -lh package.zip
sha256sum package.zip | head -1
"""


def workspace_git_url_with_token() -> str:
    return git_url_with_token(FRONTEND_WORKSPACE_GIT_URL)


def nho_workspace_git_url_with_token() -> str:
    return git_url_with_token(NHO_FRONTEND_WORKSPACE_GIT_URL)


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


def data_sync_git_url_with_token() -> str:
    token = os.environ.get("DATA_SYNC_GIT_TOKEN") or os.environ.get("FRONTEND_GIT_TOKEN") or os.environ.get("OHR_BACK_GIT_TOKEN", "")
    if not token:
        return DATA_SYNC_GIT_URL
    u = urllib.parse.urlparse(DATA_SYNC_GIT_URL)
    host = u.hostname or ""
    netloc = f"oauth2:{urllib.parse.quote(token, safe='')}@{host}"
    if u.port:
        netloc += f":{u.port}"
    return urllib.parse.urlunparse((u.scheme or "https", netloc, u.path, u.params, u.query, u.fragment))


def safe_repo_subdir(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    parts = Path(normalized).parts
    if normalized.startswith("/") or ":" in normalized or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe repository subdir: {value}")
    return normalized


def data_sync_subdir_from_input(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme:
        return safe_repo_subdir(raw)
    repo = urllib.parse.urlparse(DATA_SYNC_GIT_URL)
    if (parsed.hostname or "").lower() != (repo.hostname or "").lower():
        raise ValueError("URL host does not match data-synchronization repository")
    repo_path = (repo.path or "").rstrip("/")
    input_path = (parsed.path or "").rstrip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    marker = repo_path + "/-/tree/"
    if not input_path.startswith(marker):
        raise ValueError("URL must point to data-synchronization tree")
    remainder = input_path[len(marker) :]
    url_branch, _, subdir = remainder.partition("/")
    if urllib.parse.unquote(url_branch) != DATA_SYNC_BRANCH or not subdir:
        raise ValueError("URL must use configured branch and include a directory")
    return safe_repo_subdir(urllib.parse.unquote(subdir))


def validate_data_sync_custom_source(value: str) -> dict[str, Any]:
    subdir = data_sync_subdir_from_input(value)
    if not subdir:
        return {"ok": True, "path": ""}
    with DATA_SYNC_VALIDATE_LOCK:
        sync_data_sync_validation_tree(subdir)
        if not (DATA_SYNC_DIR / subdir).is_dir():
            return {"ok": False, "path": subdir, "error": "not_found"}
    return {"ok": True, "path": subdir}


def svn_auth_args(username: str = HELP_DOCS_SVN_USERNAME, password: str = HELP_DOCS_SVN_PASSWORD) -> list[str]:
    args: list[str] = []
    if username:
        args.extend(["--username", username])
    if password:
        args.extend(["--password", password])
    return args


def validate_help_docs_svn_revision(value: str) -> dict[str, Any]:
    revision = str(value or "").strip()
    if not revision:
        return {"ok": True, "revision": ""}
    if not HELP_DOCS_SVN_REVISION_RE.fullmatch(revision):
        return {"ok": False, "revision": revision, "error": "invalid_revision"}
    proc = subprocess.run(
        [
            "svn",
            "info",
            HELP_DOCS_SVN_URL,
            "-r",
            revision,
            *svn_auth_args(),
            "--non-interactive",
            "--trust-server-cert",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=45,
    )
    if proc.returncode != 0:
        return {"ok": False, "revision": revision, "error": "not_found"}
    return {"ok": True, "revision": revision}


def sync_data_sync_validation_tree(subdir: str) -> None:
    DATA_SYNC_DIR.parent.mkdir(parents=True, exist_ok=True)
    url = data_sync_git_url_with_token()
    if (DATA_SYNC_DIR / ".git").is_dir():
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "remote", "set-url", "origin", url], check=True, timeout=45)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "fetch", "origin", DATA_SYNC_BRANCH, "--prune", "--depth", "1"], check=True, timeout=90)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "sparse-checkout", "init", "--cone"], check=True, timeout=45)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "sparse-checkout", "set", subdir], check=True, timeout=45)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "checkout", "-B", DATA_SYNC_BRANCH, f"origin/{DATA_SYNC_BRANCH}"], check=True, timeout=90)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "reset", "--hard", f"origin/{DATA_SYNC_BRANCH}"], check=True, timeout=90)
        subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "clean", "-fd"], check=True, timeout=45)
        return
    if DATA_SYNC_DIR.exists():
        shutil.rmtree(DATA_SYNC_DIR)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--filter=blob:none",
            "--sparse",
            "--branch",
            DATA_SYNC_BRANCH,
            url,
            str(DATA_SYNC_DIR),
        ],
        check=True,
        timeout=120,
    )
    subprocess.run(["git", "-C", str(DATA_SYNC_DIR), "sparse-checkout", "set", subdir], check=True, timeout=45)


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
git clean -fd -e node_modules -e .ci-cache -e .cache -e .turbo -e .vite
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
pnpm_install_cached() {
  local dir="${1:-.}"
  local name="${2:-$dir}"
  (
    cd "$dir"
    mkdir -p .ci-cache
    local hash_file=".ci-cache/pnpm-install.hash"
    local input_hash
    input_hash="$( { [ -f package.json ] && sha256sum package.json; [ -f pnpm-lock.yaml ] && sha256sum pnpm-lock.yaml; } | sha256sum | awk '{print $1}' )"
    if [ -d node_modules ] && [ -f "$hash_file" ] && [ "$(cat "$hash_file")" = "$input_hash" ]; then
      echo "[cache pnpm] $name unchanged; skip pnpm i"
      return 0
    fi
    echo "[cache pnpm] install $name"
    pnpm i --frozen-lockfile --prefer-offline || pnpm i --prefer-offline || pnpm i
    echo "$input_hash" > "$hash_file"
  )
}
pnpm_install_cached . ohr-workspace
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
    git -C "$repo_dir" fetch origin "+refs/heads/$repo_branch:refs/remotes/origin/$repo_branch" --prune
    git -C "$repo_dir" reset --hard HEAD
    git -C "$repo_dir" checkout -B "$repo_branch" "origin/$repo_branch"
    git -C "$repo_dir" reset --hard "origin/$repo_branch"
    git -C "$repo_dir" clean -fd -e node_modules -e .ci-cache -e .cache -e .turbo -e .vite
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


NHO_FRONTEND_RESTORE_SCRIPT = r"""set -euo pipefail
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
git fetch origin "+refs/heads/$FRONTEND_WS_BRANCH:refs/remotes/origin/$FRONTEND_WS_BRANCH" --prune
git reset --hard HEAD
git checkout -B "$FRONTEND_WS_BRANCH" "origin/$FRONTEND_WS_BRANCH"
git reset --hard "origin/$FRONTEND_WS_BRANCH"
git clean -fd -e node_modules -e .ci-cache -e .cache -e .turbo -e .vite
npm i -g pnpm@9.4.0 --registry=https://registry.npmmirror.com/
npm i -g yarn@1.22.22 --registry=https://registry.npmmirror.com/
pnpm config set store-dir "$NHO_PNPM_CACHE_DIR" || true
mkdir -p "$NHO_YARN_CACHE_DIR"
yarn config set cache-folder "$NHO_YARN_CACHE_DIR" || true
npm config set registry https://registry.smartcompany.cn/repository/npm-group/
npm config set //registry.smartcompany.cn/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-group/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-hosted/:_auth "$NPM_AUTH_B64"
npm uninstall -g ohr-cli || true
npm install -g ohr-cli --registry=https://registry.smartcompany.cn/repository/npm-group/
if [ -n "${FRONTEND_GIT_TOKEN:-}" ]; then
  git config --global url."https://oauth2:${FRONTEND_GIT_TOKEN}@${FRONTEND_GIT_HOST}/".insteadOf "https://${FRONTEND_GIT_HOST}/"
fi
sync_nho_repo() {
  repo_dir="$1"
  repo_url="$2"
  repo_branch="$3"
  if [ -d "$repo_dir/.git" ]; then
    echo "[sync nho $repo_dir] fetch $repo_branch"
    git -C "$repo_dir" remote set-url origin "$repo_url"
    git -C "$repo_dir" fetch origin "+refs/heads/$repo_branch:refs/remotes/origin/$repo_branch" --prune
    git -C "$repo_dir" reset --hard HEAD
    git -C "$repo_dir" checkout -B "$repo_branch" "origin/$repo_branch"
    git -C "$repo_dir" reset --hard "origin/$repo_branch"
    git -C "$repo_dir" clean -fd -e node_modules -e .ci-cache -e .cache -e .turbo -e .vite
  else
    rm -rf "$repo_dir"
    echo "[sync nho $repo_dir] clone $repo_branch"
    git clone --depth=1 -b "$repo_branch" "$repo_url" "$repo_dir"
  fi
}
sync_nho_repo ohr-feelin "$NHO_FRONTEND_FEELIN_GIT_URL" "$FRONTEND_FEELIN_BRANCH"
sync_nho_repo ohr-micro-frontends "$NHO_FRONTEND_MICRO_FRONTENDS_GIT_URL" "$FRONTEND_MF_BRANCH"
sync_nho_repo ohr-lowcode-engine "$NHO_FRONTEND_LOWCODE_ENGINE_GIT_URL" "$FRONTEND_LOWCODE_BRANCH"
sync_nho_repo ohr-nocode-engine "$NHO_FRONTEND_NOCODE_ENGINE_GIT_URL" "$FRONTEND_NOCODE_BRANCH"
sync_nho_repo ohr-web-nencho "$NHO_FRONTEND_NENCHO_GIT_URL" "$FRONTEND_NENCHO_BRANCH"
write_nho_npmrc() {
  target_dir="$1"
  mkdir -p "$target_dir"
  cat >> "$target_dir/.npmrc" <<EOF

@omf:registry=https://registry.smartcompany.cn/repository/npm-group/
@one:registry=https://registry.smartcompany.cn/repository/npm-group/
@ole:registry=https://registry.smartcompany.cn/repository/npm-group/
@ohr:registry=https://registry.smartcompany.cn/repository/npm-group/
//registry.smartcompany.cn/:_auth=$NPM_AUTH_B64
//registry.smartcompany.cn/repository/npm-group/:_auth=$NPM_AUTH_B64
//registry.smartcompany.cn/repository/npm-hosted/:_auth=$NPM_AUTH_B64
always-auth=true
EOF
}
write_nho_npmrc .
write_nho_npmrc ohr-feelin
write_nho_npmrc ohr-micro-frontends
write_nho_npmrc ohr-lowcode-engine
write_nho_npmrc ohr-nocode-engine
write_nho_npmrc ohr-web-nencho
"""


NHO_FRONTEND_BUILD_SCRIPT = r"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"
export NODE_OPTIONS="${NHO_NODE_OPTIONS:---max-old-space-size=1536}"
cd "$OHR_FRONTEND_WORKDIR"
npm i -g pnpm@9.4.0 --registry=https://registry.npmmirror.com/
npm i -g yarn@1.22.22 --registry=https://registry.npmmirror.com/
pnpm config set store-dir "$NHO_PNPM_CACHE_DIR" || true
mkdir -p "$NHO_YARN_CACHE_DIR"
yarn config set cache-folder "$NHO_YARN_CACHE_DIR" || true
npm config set registry https://registry.smartcompany.cn/repository/npm-group/
npm config set //registry.smartcompany.cn/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-group/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-hosted/:_auth "$NPM_AUTH_B64"
npm uninstall -g ohr-cli || true
npm install -g ohr-cli --registry=https://registry.smartcompany.cn/repository/npm-group/
yarn config set registry https://registry.npmjs.org
yarn config set cache-folder "$NHO_YARN_CACHE_DIR" || true
yarn config set enableMirror false || true
yarn config set checksumBehavior ignore || true
write_nho_npmrc() {
  target_dir="$1"
  mkdir -p "$target_dir"
  cat >> "$target_dir/.npmrc" <<EOF

@omf:registry=https://registry.smartcompany.cn/repository/npm-group/
@one:registry=https://registry.smartcompany.cn/repository/npm-group/
@ole:registry=https://registry.smartcompany.cn/repository/npm-group/
@ohr:registry=https://registry.smartcompany.cn/repository/npm-group/
//registry.smartcompany.cn/:_auth=$NPM_AUTH_B64
//registry.smartcompany.cn/repository/npm-group/:_auth=$NPM_AUTH_B64
//registry.smartcompany.cn/repository/npm-hosted/:_auth=$NPM_AUTH_B64
always-auth=true
EOF
}
rewrite_nho_public_lock_urls() {
  target_dir="$1"
  [ -f "$target_dir/yarn.lock" ] || return 0
  python3 - "$target_dir/yarn.lock" <<'PY'
import sys
from pathlib import Path

lock_path = Path(sys.argv[1])
private_scopes = ("/@omf/", "/@one/", "/@ole/", "/@ohr/")
old = "https://registry.smartcompany.cn/repository/npm-group/"
new = "https://registry.npmmirror.com/"
lines = []
changed = 0
for line in lock_path.read_text(encoding="utf-8").splitlines(True):
    if old in line and not any(scope in line for scope in private_scopes):
        line = line.replace(old, new)
        changed += 1
    lines.append(line)
if changed:
    lock_path.write_text("".join(lines), encoding="utf-8")
    print(f"[nho yarn] rewrote {changed} public resolved urls in {lock_path}")
PY
}
apply_nho_low_memory_overrides() {
  python3 - <<'PY'
import json
from pathlib import Path

script_files = [
    "package.json",
    "ohr-micro-frontends/package.json",
    "ohr-lowcode-engine/package.json",
    "ohr-nocode-engine/package.json",
]
for package_json in Path("ohr-lowcode-engine/packages").glob("*/package.json"):
    script_files.append(str(package_json))
for package_json in Path("ohr-nocode-engine/packages").glob("*/package.json"):
    script_files.append(str(package_json))

for name in script_files:
    path = Path(name)
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = []
    for key, value in list(data.get("scripts", {}).items()):
        new_value = value
        new_value = new_value.replace("yarn build:parallel", "yarn build")
        new_value = new_value.replace("ohr-cli mono-build --parallel", "ohr-cli mono-build")
        new_value = new_value.replace(" --parallel", "")
        new_value = new_value.replace("NODE_OPTIONS=--max_old_space_size=8192", "NODE_OPTIONS=--max_old_space_size=1536")
        new_value = new_value.replace("NODE_OPTIONS=--max-old-space-size=8192", "NODE_OPTIONS=--max-old-space-size=1536")
        if name.startswith("ohr-nocode-engine/packages/"):
            new_value = new_value.replace("yarn set-env-prod build-scripts build", "yarn set-env-prod NODE_OPTIONS=--max_old_space_size=2048 build-scripts build")
            new_value = new_value.replace("yarn set-env-dev build-scripts build", "yarn set-env-dev NODE_OPTIONS=--max_old_space_size=2048 build-scripts build")
        if new_value != value:
            data["scripts"][key] = new_value
            changed.append(key)
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[nho low-memory] {name}: {', '.join(changed)}")

for script_name in ("ohr-lowcode-engine/scripts/build.sh", "ohr-lowcode-engine/scripts/build-parallel.sh"):
    path = Path(script_name)
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    new_text = text.replace("--stream\n", "--stream \\\n  --concurrency 1\n")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"[nho low-memory] {script_name}: lerna concurrency=1")
PY
}
run_nho_setup_sequential() {
  echo "Running NHO dependency setup sequentially to avoid OOM"
  (cd ohr-web-nencho && pnpm run yalc:remove || true)
  (cd ohr-lowcode-engine && yarn yalc:remove || true)
  (cd ohr-micro-frontends && yarn yalc:remove || true)
  (cd ohr-nocode-engine && yarn yalc:remove || true)
  (cd ohr-feelin && yarn install --ignore-scripts)
  (cd ohr-micro-frontends && yarn install --ignore-scripts)
  (cd ohr-lowcode-engine && yarn install --ignore-scripts)
  (cd ohr-nocode-engine && yarn install --ignore-scripts)
  (cd ohr-web-nencho && pnpm install)
}
patch_nho_react_pdf_exports() {
  node <<'NODE'
const fs = require('fs');
const packagePath = 'ohr-micro-frontends/node_modules/react-pdf/package.json';
if (fs.existsSync(packagePath)) {
  const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  if (pkg.exports) {
    delete pkg.exports;
    fs.writeFileSync(packagePath, JSON.stringify(pkg, null, 2) + '\n');
    console.log('[nho compat] removed react-pdf exports for legacy internal imports');
  }
  const compatDir = 'ohr-micro-frontends/node_modules/react-pdf/dist/Page';
  const sourceDir = 'ohr-micro-frontends/node_modules/react-pdf/dist/esm/Page';
  if (!fs.existsSync(compatDir) && fs.existsSync(sourceDir)) {
    fs.mkdirSync(compatDir, {recursive: true});
    for (const name of fs.readdirSync(sourceDir)) {
      if (name.endsWith('.css')) {
        fs.copyFileSync(`${sourceDir}/${name}`, `${compatDir}/${name}`);
      }
    }
    console.log('[nho compat] copied react-pdf dist/esm/Page css to legacy dist/Page path');
  }
}
NODE
}
write_nho_npmrc .
write_nho_npmrc ohr-feelin
write_nho_npmrc ohr-micro-frontends
write_nho_npmrc ohr-lowcode-engine
write_nho_npmrc ohr-nocode-engine
write_nho_npmrc ohr-web-nencho
rewrite_nho_public_lock_urls .
rewrite_nho_public_lock_urls ohr-feelin
rewrite_nho_public_lock_urls ohr-micro-frontends
rewrite_nho_public_lock_urls ohr-lowcode-engine
rewrite_nho_public_lock_urls ohr-nocode-engine
rewrite_nho_public_lock_urls ohr-web-nencho
apply_nho_low_memory_overrides
find . -maxdepth 1 -type f -name 'release_*.zip' -delete
find . -maxdepth 1 -type d -name 'release_*' -exec rm -rf {} +
run_nho_setup_sequential
patch_nho_react_pdf_exports
yarn build
yarn bundle
bundle_zip="$(find . -maxdepth 1 -type f -name 'release_*.zip' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {print $2}')"
if [ -z "$bundle_zip" ] || [ ! -f "$bundle_zip" ]; then
  echo "NHO 前端发布包生成失败：yarn bundle 未生成 release_*.zip"
  exit 7
fi
mkdir -p "$(dirname "$OUT_WEB_ZIP")"
publish_root="$(dirname "$OUT_WEB_ZIP")/nho-webzip-root"
rm -rf "$publish_root"
mkdir -p "$publish_root/ohr-cicd/web_prod"
unzip -q "$bundle_zip" -d "$publish_root/ohr-cicd/web_prod"
if [ "${BUILD_CONF_PROD:-true}" = "true" ]; then
  if [ ! -d "$CONF_PROD_TEMPLATE_DIR" ]; then
    echo "NHO conf_prod 生成失败：$CONF_PROD_TEMPLATE_DIR 不存在"
    exit 8
  fi
  cp -a "$CONF_PROD_TEMPLATE_DIR" "$publish_root/ohr-cicd/conf_prod"
  rm -f "$publish_root/ohr-cicd/conf_prod"/*.crt "$publish_root/ohr-cicd/conf_prod"/*.key "$publish_root/ohr-cicd/conf_prod"/TODO.md
else
  echo "NHO conf_prod 生成已跳过"
fi
rm -f "$OUT_WEB_ZIP"
(
  cd "$publish_root"
  zip -qr "$OUT_WEB_ZIP" ohr-cicd
)
rm -rf "$publish_root"
ls -lh "$OUT_WEB_ZIP"
"""


DIRECT_FRONTEND_BUILD_SCRIPT = r"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"
export NODE_OPTIONS="${STANDARD_NODE_OPTIONS:---max-old-space-size=4096}"
cd "$OHR_FRONTEND_WORKDIR"
npm i -g pnpm@10.22.0 --registry=https://registry.npmmirror.com/
npm i -g yarn@1.22.22 --registry=https://registry.npmmirror.com/
pnpm config set store-dir /opt/pnpm-cache || true
npm i yalc -g --registry=https://registry.npmmirror.com/
npm config set registry https://registry.smartcompany.cn/repository/npm-group/
npm config set //registry.smartcompany.cn/:_auth "$NPM_AUTH_B64"
npm config set //registry.smartcompany.cn/repository/npm-group/:_auth "$NPM_AUTH_B64"
npm i -g ohr-cli --registry=https://registry.smartcompany.cn/repository/npm-group/
apt-get update -qy && apt-get install -y zip unzip subversion
CICD_DIR="$OHR_CICD_WORKDIR"
if [[ ! "$OHR_CICD_ENV" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ohr-cicd 环境名不合法：$OHR_CICD_ENV"
  exit 6
fi
mkdir -p "$(dirname "$CICD_DIR")"
if [ -d "$CICD_DIR/.git" ]; then
  echo "[sync ohr-cicd] fetch $OHR_CICD_BRANCH"
  git -C "$CICD_DIR" remote set-url origin "$OHR_CICD_GIT_URL"
  git -C "$CICD_DIR" fetch origin "$OHR_CICD_BRANCH" --prune
  git -C "$CICD_DIR" checkout -B "$OHR_CICD_BRANCH" "origin/$OHR_CICD_BRANCH"
  git -C "$CICD_DIR" reset --hard "origin/$OHR_CICD_BRANCH"
  git -C "$CICD_DIR" clean -fd -e node_modules -e .ci-cache -e .cache -e .yarn-cache
else
  rm -rf "$CICD_DIR"
  echo "[sync ohr-cicd] clone $OHR_CICD_BRANCH"
  git clone -b "$OHR_CICD_BRANCH" "$OHR_CICD_GIT_URL" "$CICD_DIR"
fi
cd "$CICD_DIR"
yarn_install_cached() {
  mkdir -p .ci-cache
  local hash_file=".ci-cache/yarn-install.hash"
  local input_hash
  input_hash="$( { [ -f package.json ] && sha256sum package.json; [ -f yarn.lock ] && sha256sum yarn.lock; } | sha256sum | awk '{print $1}' )"
  if [ -d node_modules ] && [ -f "$hash_file" ] && [ "$(cat "$hash_file")" = "$input_hash" ]; then
    echo "[cache yarn] ohr-cicd unchanged; skip yarn install"
    return 0
  fi
  echo "[cache yarn] install ohr-cicd"
  yarn install --frozen-lockfile --cache-folder /opt/yarn-cache || yarn install --cache-folder /opt/yarn-cache
  echo "$input_hash" > "$hash_file"
}
yarn_install_cached
cat > "config.$OHR_CICD_ENV.js" <<'JS'
const getSharedConfig = require('./sharedConfig');

const ENV = process.env.OHR_CICD_ENV || 'direct_prod';
const PORT_PORTAL = Number(process.env.CONF_WEB_PORT || 80);
const ENABLE_HTTPS = process.env.CONF_ENABLE_HTTPS === 'true';
const HTTPS_PORT = Number(process.env.CONF_HTTPS_PORT || 443);
const HOST_NAME = `${ENABLE_HTTPS ? 'https' : 'http'}://${process.env.CONF_SERVER_HOST}`;
const HOST_PORTAL = ENABLE_HTTPS
  ? (HTTPS_PORT === 443 ? HOST_NAME : `${HOST_NAME}:${HTTPS_PORT}`)
  : (PORT_PORTAL === 80 ? HOST_NAME : `${HOST_NAME}:${PORT_PORTAL}`);
const SERVICE_GATEWAY = process.env.OHR_CICD_SERVICE_GATEWAY || 'http://localhost:3198/';

module.exports = {
  ...getSharedConfig({
    HOST_PORTAL,
    PORT_PORTAL,
    ENV,
    ENV_TYPE: 'windows',
    PORT_DUMI_BASIC: Number(process.env.OHR_CICD_DUMI_BASIC_PORT || 8005),
    PORT_DUMI_NOCODE: Number(process.env.OHR_CICD_DUMI_NOCODE_PORT || 8006),
    SERVER_GATEWAY: SERVICE_GATEWAY.endsWith('/') ? SERVICE_GATEWAY : `${SERVICE_GATEWAY}/`,
    NGINX_SERVER_NAME: `localhost ${process.env.CONF_SERVER_HOST}`,
    MINIO_SERVER: process.env.OHR_CICD_MINIO_SERVER || 'http://localhost:19000',
    MINIO_HOST: process.env.OHR_CICD_MINIO_HOST || 'localhost:19000',
    RUSTFS_SERVER: process.env.OHR_CICD_RUSTFS_SERVER || 'http://127.0.0.1:12345',
    RUSTFS_HOST: process.env.OHR_CICD_RUSTFS_HOST || '127.0.0.1:12345',
    AZURE_SERVER: process.env.OHR_CICD_AZURE_SERVER || 'undefined',
    AZURE_HOST: process.env.OHR_CICD_AZURE_HOST || 'undefined',
    CONF_WEB_DIR: 'ohr-cicd/web_prod',
    CONF_CONF_DIR: 'conf_prod',
    CONF_TEMPLATE_DIR: 'conf-template',
    WORKER_PROCESSES: Number(process.env.CONF_WORKER_PROCESSES || 1),
    WORKER_CONNS: Number(process.env.CONF_WORKER_CONNECTIONS || 1024),
    ENABLE_HTTPS,
    PORT_HTTPS: HTTPS_PORT,
    SSL_CERTIFICATE: 'server.crt',
    SSL_CERTIFICATE_KEY: 'server.key',
    ENABLE_DEBUG: false,
  }),
};
JS
env="$OHR_CICD_ENV" node ./src/generateConf.js
if [ ! -d "$CICD_DIR/conf_$OHR_CICD_ENV" ]; then
  echo "ohr-cicd conf_prod 生成失败：$CICD_DIR/conf_$OHR_CICD_ENV 不存在"
  exit 6
fi
if [ "${CONF_ENABLE_HTTPS:-false}" = "true" ]; then
  conf_out="$CICD_DIR/conf_$OHR_CICD_ENV"
  if [ -f "$conf_out/nginx_https.conf" ]; then
    cp "$conf_out/nginx_https.conf" "$conf_out/nginx.conf"
  fi
  if ! grep -q "listen[[:space:]]*443[[:space:]]*ssl" "$conf_out/nginx.conf"; then
    echo "HTTPS が有効ですが、ohr-cicd が 443 ssl 用 nginx.conf を生成していません"
    exit 6
  fi
  python3 - "$conf_out/nginx.conf" "$conf_out/common-settings.conf" "$CONF_SERVER_HOST" <<'PY'
import re
import sys
from pathlib import Path

nginx_path = Path(sys.argv[1])
settings_path = Path(sys.argv[2])
host = sys.argv[3]
nginx = nginx_path.read_text(encoding="utf-8")
nginx = re.sub(r"ssl_certificate\s+[^;]+;", "ssl_certificate server.crt;", nginx)
nginx = re.sub(r"ssl_certificate_key\s+[^;]+;", "ssl_certificate_key server.key;", nginx)
nginx_path.write_text(nginx, encoding="utf-8")
settings = settings_path.read_text(encoding="utf-8")
settings = re.sub(r'set \$ohr_portal_origin "[^"]+";', f'set $ohr_portal_origin "https://{host}";', settings)
settings_path.write_text(settings, encoding="utf-8")
PY
fi
help_zip=""
if [ "${BUILD_HELP:-true}" = "true" ]; then
HELP_DIR="$HELP_DOCS_WORKDIR"
mkdir -p "$(dirname "$HELP_DIR")"
if [ -d "$HELP_DIR/.git" ]; then
  echo "[sync ohr-help-docs] fetch $HELP_DOCS_BRANCH"
  git -C "$HELP_DIR" remote set-url origin "$HELP_DOCS_GIT_URL"
  git -C "$HELP_DIR" fetch origin "$HELP_DOCS_BRANCH" --prune
  git -C "$HELP_DIR" checkout -B "$HELP_DOCS_BRANCH" "origin/$HELP_DOCS_BRANCH"
  git -C "$HELP_DIR" reset --hard "origin/$HELP_DOCS_BRANCH"
  git -C "$HELP_DIR" clean -fd -e node_modules -e .ci-cache -e .cache
else
  rm -rf "$HELP_DIR"
  echo "[sync ohr-help-docs] clone $HELP_DOCS_BRANCH"
  git clone -b "$HELP_DOCS_BRANCH" "$HELP_DOCS_GIT_URL" "$HELP_DIR"
fi
cd "$HELP_DIR"
SVN_AUTH_ARGS=()
if [ -n "${HELP_DOCS_SVN_USERNAME:-}" ]; then
  SVN_AUTH_ARGS+=(--username "$HELP_DOCS_SVN_USERNAME")
fi
if [ -n "${HELP_DOCS_SVN_PASSWORD:-}" ]; then
  SVN_AUTH_ARGS+=(--password "$HELP_DOCS_SVN_PASSWORD")
fi
SVN_REV_ARGS=()
if [ -n "${HELP_DOCS_SVN_REVISION:-}" ]; then
  if [[ ! "$HELP_DOCS_SVN_REVISION" =~ ^[0-9]+$ ]]; then
    echo "Help SVN revision 仅允许数字：$HELP_DOCS_SVN_REVISION"
    exit 4
  fi
  SVN_REV_ARGS=(-r "$HELP_DOCS_SVN_REVISION")
fi
mkdir -p "$(dirname "$HELP_DOCS_SVN_WORKDIR")"
if [ -d "$HELP_DOCS_SVN_WORKDIR/.svn" ]; then
  echo "[sync help svn] update $HELP_DOCS_SVN_WORKDIR ${HELP_DOCS_SVN_REVISION:+revision $HELP_DOCS_SVN_REVISION}"
  svn cleanup "$HELP_DOCS_SVN_WORKDIR" "${SVN_AUTH_ARGS[@]}" --non-interactive --trust-server-cert || true
  svn update "$HELP_DOCS_SVN_WORKDIR" "${SVN_REV_ARGS[@]}" "${SVN_AUTH_ARGS[@]}" --non-interactive --trust-server-cert
else
  rm -rf "$HELP_DOCS_SVN_WORKDIR"
  echo "[sync help svn] checkout $HELP_DOCS_SVN_URL ${HELP_DOCS_SVN_REVISION:+revision $HELP_DOCS_SVN_REVISION}"
  svn checkout "$HELP_DOCS_SVN_URL" "$HELP_DOCS_SVN_WORKDIR" "${SVN_REV_ARGS[@]}" "${SVN_AUTH_ARGS[@]}" --non-interactive --trust-server-cert
fi
rm -rf markdowns
mkdir -p markdowns
shopt -s dotglob nullglob
for item in "$HELP_DOCS_SVN_WORKDIR"/*; do
  [ "$(basename "$item")" = ".svn" ] && continue
  cp -a "$item" markdowns/
done
shopt -u dotglob nullglob
if [ -z "$(find markdowns -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Help SVN 文档内容为空：$HELP_DOCS_SVN_URL"
  exit 4
fi
HELP_GIT_REV="$(git rev-parse HEAD)"
HELP_SVN_REV="$(svn info --show-item revision "$HELP_DOCS_SVN_WORKDIR" "${SVN_AUTH_ARGS[@]}" --non-interactive --trust-server-cert 2>/dev/null || svn info "$HELP_DOCS_SVN_WORKDIR" "${SVN_AUTH_ARGS[@]}" --non-interactive --trust-server-cert | awk -F': ' '/^Revision:/ {print $2; exit}')"
HELP_LOCK_HASH="$( { [ -f package.json ] && sha256sum package.json; [ -f pnpm-lock.yaml ] && sha256sum pnpm-lock.yaml; } | sha256sum | awk '{print $1}' )"
HELP_CACHE_DIR="$HELP_DIR/.ci-cache/help"
HELP_CACHE_KEY="$(printf '%s\n%s\n%s\n%s\n' "$HELP_DOCS_BRANCH" "$HELP_GIT_REV" "$HELP_SVN_REV" "$HELP_LOCK_HASH" | sha256sum | awk '{print $1}')"
HELP_CACHED_ZIP="$HELP_CACHE_DIR/$HELP_CACHE_KEY.zip"
mkdir -p "$HELP_CACHE_DIR"
if [ -f "$HELP_CACHED_ZIP" ]; then
  echo "[cache help] reuse help bundle git=$HELP_GIT_REV svn=$HELP_SVN_REV"
  help_zip="$HELP_CACHED_ZIP"
else
pnpm config set store-dir /opt/pnpm-cache || true
pnpm_install_cached() {
  mkdir -p .ci-cache
  local hash_file=".ci-cache/pnpm-install.hash"
  local input_hash="$HELP_LOCK_HASH"
  if [ -d node_modules ] && [ -f "$hash_file" ] && [ "$(cat "$hash_file")" = "$input_hash" ]; then
    echo "[cache pnpm] ohr-help-docs unchanged; skip pnpm i"
    return 0
  fi
  echo "[cache pnpm] install ohr-help-docs"
  pnpm i --frozen-lockfile --prefer-offline || pnpm i --prefer-offline || pnpm i
  echo "$input_hash" > "$hash_file"
}
pnpm_install_cached
echo "使用 SVN 文档源构建 Help：$HELP_DOCS_SVN_URL"
echo "使用 Help SVN revision：$HELP_SVN_REV"
find . -maxdepth 1 -type f -name 'ohr_help_docs_release_*.zip' -delete
find . -maxdepth 1 -type d -name 'ohr_help_docs_release_*' -exec rm -rf {} +
rm -rf build
npm run copy-images
npm run build
npm run bundle
help_zip="$(find . -maxdepth 1 -type f -name 'ohr_help_docs_release_*.zip' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {print $2}')"
if [ -z "$help_zip" ] || [ ! -f "$help_zip" ]; then
  echo "Help 发布包生成失败：npm run bundle 未生成 ohr_help_docs_release_*.zip"
  exit 5
fi
help_zip="$(readlink -f "$help_zip")"
cp "$help_zip" "$HELP_CACHED_ZIP"
fi
else
  echo "Help 构建已跳过"
fi
cd "$OHR_FRONTEND_WORKDIR"
apply_standard_low_memory_overrides() {
  python3 - <<'PY'
import json
import re
from pathlib import Path

script_files = [
    "package.json",
    "ohr-micro-frontends/package.json",
    "ohr-lowcode-engine/package.json",
    "ohr-nocode-engine/package.json",
]
for package_json in Path("ohr-lowcode-engine/packages").glob("*/package.json"):
    script_files.append(str(package_json))
for package_json in Path("ohr-nocode-engine/packages").glob("*/package.json"):
    script_files.append(str(package_json))

for name in script_files:
    path = Path(name)
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = []
    for key, value in list(data.get("scripts", {}).items()):
        new_value = value
        new_value = new_value.replace("npm run build:parallel", "npm run build")
        new_value = new_value.replace("yarn build:parallel", "yarn build")
        new_value = new_value.replace("ohr-cli mono-build --parallel", "ohr-cli mono-build")
        new_value = new_value.replace(" --parallel", "")
        new_value = new_value.replace("NODE_OPTIONS=--max_old_space_size=8192", "NODE_OPTIONS=--max_old_space_size=4096")
        new_value = new_value.replace("NODE_OPTIONS=--max-old-space-size=8192", "NODE_OPTIONS=--max-old-space-size=4096")
        new_value = re.sub(r"(lerna run build --stream)(?!\s+--concurrency)", r"\1 --concurrency 1", new_value)
        new_value = re.sub(r"(lerna run build --scope=@omf/subsys-\*)(?!\s+--concurrency)", r"\1 --concurrency 1", new_value)
        if name.startswith("ohr-nocode-engine/packages/"):
            new_value = new_value.replace("yarn set-env-prod build-scripts build", "yarn set-env-prod NODE_OPTIONS=--max_old_space_size=4096 build-scripts build")
            new_value = new_value.replace("yarn set-env-dev build-scripts build", "yarn set-env-dev NODE_OPTIONS=--max_old_space_size=4096 build-scripts build")
        if new_value != value:
            data["scripts"][key] = new_value
            changed.append(key)
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[standard low-memory] {name}: {', '.join(changed)}")

for script_name in ("ohr-lowcode-engine/scripts/build.sh", "ohr-lowcode-engine/scripts/build-parallel.sh"):
    path = Path(script_name)
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8")
    new_text = text.replace("--stream\n", "--stream \\\n  --concurrency 1\n")
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        print(f"[standard low-memory] {script_name}: lerna concurrency=1")
PY
}
apply_standard_low_memory_overrides
find . -maxdepth 1 -type f -name 'release_*.zip' -delete
find . -maxdepth 1 -type d -name 'release_*' -exec rm -rf {} +
npm run build
npm run bundle
mkdir -p "$(dirname "$OUT_WEB_ZIP")" "$OUT_TMP_DIR"
rm -f "$OUT_WEB_ZIP"
bundle_zip="$(find . -maxdepth 1 -type f -name 'release_*.zip' -printf '%T@ %p\n' | sort -nr | awk 'NR==1 {print $2}')"
if [ -z "$bundle_zip" ] || [ ! -f "$bundle_zip" ]; then
  echo "前端发布包生成失败：npm run bundle 未生成 release_*.zip"
  exit 3
fi
publish_root="$(mktemp -d "$OUT_TMP_DIR/publish.XXXXXX")"
cleanup_publish_root() {
  rm -rf "$publish_root"
}
trap cleanup_publish_root EXIT
mkdir -p "$publish_root/ohr-cicd/web_prod"
unzip -q "$bundle_zip" -d "$publish_root/ohr-cicd/web_prod"
if [ -n "$help_zip" ]; then
  mkdir -p "$publish_root/ohr-cicd/web_prod/help"
  unzip -q "$help_zip" -d "$publish_root/ohr-cicd/web_prod/help"
fi
if [ "${BUILD_CONF_PROD:-true}" = "true" ]; then
  conf_dir="$publish_root/ohr-cicd/conf_prod"
  rm -rf "$conf_dir"
  cp -a "$CICD_DIR/conf_$OHR_CICD_ENV" "$conf_dir"
  rm -f "$conf_dir"/*.crt "$conf_dir"/*.key "$conf_dir"/TODO.md
else
  echo "conf_prod 生成已跳过"
fi
(
  cd "$publish_root"
  zip -qr "$OUT_WEB_ZIP" ohr-cicd
)
bundle_dir="${bundle_zip%.zip}"
rm -rf "$bundle_zip" "$bundle_dir"
if [ -n "$help_zip" ] && [[ "$help_zip" == "$HELP_DIR"/ohr_help_docs_release_*.zip ]]; then
  help_dir="${help_zip%.zip}"
  rm -rf "$help_zip" "$help_dir"
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
        "HELP_DOCS_GIT_URL": git_url_with_token(HELP_DOCS_GIT_URL),
        "HELP_DOCS_BRANCH": HELP_DOCS_BRANCH,
        "HELP_DOCS_WORKDIR": str(HELP_DOCS_DIR),
        "HELP_DOCS_SVN_URL": HELP_DOCS_SVN_URL,
        "HELP_DOCS_SVN_WORKDIR": str(HELP_DOCS_SVN_DIR),
        "HELP_DOCS_SVN_USERNAME": HELP_DOCS_SVN_USERNAME,
        "HELP_DOCS_SVN_PASSWORD": HELP_DOCS_SVN_PASSWORD,
        "HELP_DOCS_SVN_REVISION": req.get("help_docs_svn_revision") or "",
        "BUILD_HELP": "true" if req.get("build_help", True) else "false",
        "BUILD_CONF_PROD": "true" if req.get("build_conf_prod", True) else "false",
        "CONF_PROD_TEMPLATE_DIR": str(CONF_PROD_TEMPLATE_DIR),
        "OHR_CICD_GIT_URL": git_url_with_token(OHR_CICD_GIT_URL),
        "OHR_CICD_BRANCH": OHR_CICD_BRANCH,
        "OHR_CICD_WORKDIR": str(OHR_CICD_DIR),
        "OHR_CICD_ENV": OHR_CICD_ENV,
        "OHR_CICD_SERVICE_GATEWAY": OHR_CICD_SERVICE_GATEWAY,
        "OHR_CICD_MINIO_SERVER": OHR_CICD_MINIO_SERVER,
        "OHR_CICD_MINIO_HOST": OHR_CICD_MINIO_HOST,
        "OHR_CICD_RUSTFS_SERVER": OHR_CICD_RUSTFS_SERVER,
        "OHR_CICD_RUSTFS_HOST": OHR_CICD_RUSTFS_HOST,
        "CONF_SERVER_HOST": req.get("conf_server_host") or "",
        "CONF_WEB_PORT": str(req.get("conf_web_port") or 80),
        "CONF_ENABLE_HTTPS": "true" if req.get("conf_enable_https") else "false",
        "CONF_HTTPS_PORT": "443",
        "CONF_WORKER_PROCESSES": str(req.get("conf_worker_processes") or 1),
        "CONF_WORKER_CONNECTIONS": str(req.get("conf_worker_connections") or 1024),
        "OHR_BUILD_ID": build_id,
        "OUT_TMP_DIR": str(variant_artifact_root("standard") / build_id / "tmp"),
        "OUT_WEB_ZIP": str(shared_artifact_path(build_id, "web.zip", "standard")),
    }


def nho_frontend_env(req: dict[str, Any], build_id: str) -> dict[str, str]:
    rel = req["frontend_release_branch"]
    token = os.environ.get("FRONTEND_GIT_TOKEN") or os.environ.get("OHR_BACK_GIT_TOKEN", "")
    host = urllib.parse.urlparse(NHO_FRONTEND_WORKSPACE_GIT_URL).hostname or "upds7.ujob100.com"
    return {
        "GIT_SYNC_URL": nho_workspace_git_url_with_token(),
        "FRONTEND_GIT_TOKEN": token,
        "FRONTEND_GIT_HOST": host,
        "NPM_AUTH_B64": npm_auth_b64_value(),
        "OHR_FRONTEND_WORKDIR": str(NHO_FRONTEND_WORKSPACE_DIR),
        "FRONTEND_WS_BRANCH": req.get("frontend_workspace_branch") or NHO_FRONTEND_WORKSPACE_BRANCH,
        "FRONTEND_REL_BRANCH": rel,
        "FRONTEND_FEELIN_BRANCH": req.get("frontend_feelin_branch") or NHO_FRONTEND_FEELIN_BRANCH,
        "FRONTEND_LOWCODE_BRANCH": req.get("frontend_lowcode_engine_branch") or rel,
        "FRONTEND_MF_BRANCH": req.get("frontend_micro_frontends_branch") or rel,
        "FRONTEND_NOCODE_BRANCH": req.get("frontend_nocode_engine_branch") or rel,
        "FRONTEND_NENCHO_BRANCH": req.get("frontend_nencho_branch") or rel,
        "NHO_FRONTEND_FEELIN_GIT_URL": git_url_with_token(NHO_FRONTEND_FEELIN_GIT_URL),
        "NHO_FRONTEND_MICRO_FRONTENDS_GIT_URL": git_url_with_token(NHO_FRONTEND_CHILD_REPOS["frontend_micro_frontends_branch"]),
        "NHO_FRONTEND_LOWCODE_ENGINE_GIT_URL": git_url_with_token(NHO_FRONTEND_CHILD_REPOS["frontend_lowcode_engine_branch"]),
        "NHO_FRONTEND_NOCODE_ENGINE_GIT_URL": git_url_with_token(NHO_FRONTEND_CHILD_REPOS["frontend_nocode_engine_branch"]),
        "NHO_FRONTEND_NENCHO_GIT_URL": git_url_with_token(NHO_FRONTEND_CHILD_REPOS["frontend_nencho_branch"]),
        "NHO_PNPM_CACHE_DIR": NHO_PNPM_CACHE_DIR,
        "NHO_YARN_CACHE_DIR": NHO_YARN_CACHE_DIR,
        "BUILD_CONF_PROD": "true" if req.get("build_conf_prod", True) else "false",
        "CONF_PROD_TEMPLATE_DIR": str(CONF_PROD_TEMPLATE_DIR),
        "OHR_BUILD_ID": build_id,
        "OUT_WEB_ZIP": str(shared_artifact_path(build_id, "web.zip", "nho")),
    }


def list_backend_release_branches(product_variant: str = "standard", limit: int = 200) -> list[str]:
    repo_url = NHO_BACK_GIT_URL if product_variant == "nho" else OHR_BACK_GIT_URL
    return list_release_branches_for_url(repo_url, limit)


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


def list_frontend_release_branches(product_variant: str = "standard", limit: int = 200) -> list[str]:
    """列出四个前端子项目共同存在的 release_* 分支；ohr-workspace 使用 FRONTEND_WORKSPACE_BRANCH。"""
    repo_urls = NHO_FRONTEND_CHILD_REPOS.values() if product_variant == "nho" else FRONTEND_CHILD_REPOS.values()
    branch_sets = [set(list_release_branches_for_url(url)) for url in repo_urls]
    if not branch_sets:
        return []
    common = set.intersection(*branch_sets)
    return sorted(common, reverse=True)[:limit]


def list_frontend_workspace_branches(product_variant: str = "standard", limit: int = 200) -> list[str]:
    return list_frontend_release_branches(product_variant, limit)


def quote_url(url: str) -> str:
    return urllib.parse.quote(url, safe="/:%#?&=@[]!$&'()*+,;")


def parse_nho_material_names(names: list[str], limit: int = 200) -> list[str]:
    numbers: list[str] = []
    for raw_name in names:
        name = urllib.parse.unquote(raw_name.strip().rstrip("/"))
        if not name or name in ("..", ".") or "/" in name or "\\" in name:
            continue
        match = NHO_MATERIAL_RE.fullmatch(name)
        if match:
            numbers.append(match.group(1))
    return sorted(set(numbers), reverse=True)[:limit]


def parse_standard_material_names(names: list[str], limit: int = 200) -> tuple[list[str], dict[str, str]]:
    dirs: dict[str, str] = {}
    for raw_name in names:
        name = urllib.parse.unquote(raw_name.strip().rstrip("/"))
        if not name or name in ("..", ".") or "/" in name or "\\" in name:
            continue
        match = STANDARD_MATERIAL_RE.fullmatch(name)
        if match:
            dirs[match.group(1)] = name
    numbers = sorted(dirs, reverse=True)[:limit]
    return numbers, {number: dirs[number] for number in numbers}


def list_nho_material_numbers_with_svn(
    svn_url: str,
    svn_username: str,
    svn_password: str,
    limit: int = 200,
) -> list[str]:
    svn_bin = shutil.which("svn")
    if not svn_bin:
        raise RuntimeError("svn command is not available")
    command = [
        svn_bin,
        "ls",
        "--non-interactive",
        "--trust-server-cert",
        "--no-auth-cache",
    ]
    if svn_username:
        command.extend(["--username", svn_username])
    if svn_password:
        command.extend(["--password", svn_password])
    command.append(svn_url.rstrip("/"))
    proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "svn ls failed").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "svn ls failed")
    return parse_nho_material_names(proc.stdout.splitlines(), limit)


def list_standard_material_numbers_with_svn(
    svn_url: str,
    svn_username: str,
    svn_password: str,
    limit: int = 200,
) -> tuple[list[str], dict[str, str]]:
    svn_bin = shutil.which("svn")
    if not svn_bin:
        raise RuntimeError("svn command is not available")
    command = svn_auth_command(["ls"], svn_username, svn_password)
    command.append(svn_url.rstrip("/"))
    proc = subprocess.run([svn_bin, *command], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "svn ls failed").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "svn ls failed")
    return parse_standard_material_names(proc.stdout.splitlines(), limit)


def list_nho_material_numbers(force_refresh: bool = False, limit: int = 200) -> list[str]:
    now_ts = time.time()
    cached = list(NHO_MATERIAL_CACHE.get("numbers") or [])
    if cached and not force_refresh and now_ts < float(NHO_MATERIAL_CACHE.get("expires_at") or 0):
        return cached[:limit]

    svn_url = os.environ.get("NHO_MATERIAL_SVN_URL", NHO_MATERIAL_SVN_URL)
    svn_username = os.environ.get("NHO_MATERIAL_SVN_USERNAME", NHO_MATERIAL_SVN_USERNAME)
    svn_password = os.environ.get("NHO_MATERIAL_SVN_PASSWORD", NHO_MATERIAL_SVN_PASSWORD)
    try:
        numbers = list_nho_material_numbers_with_svn(svn_url, svn_username, svn_password, limit)
        NHO_MATERIAL_CACHE["numbers"] = numbers
        NHO_MATERIAL_CACHE["expires_at"] = now_ts + int(os.environ.get("NHO_MATERIAL_CACHE_SECONDS", str(NHO_MATERIAL_CACHE_SECONDS)))
        return numbers[:limit]
    except RuntimeError:
        if svn_username or svn_password:
            raise

    headers = {}
    if svn_username or svn_password:
        token = f"{svn_username}:{svn_password}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(token).decode("ascii")
    req = urllib.request.Request(quote_url(svn_url.rstrip("/") + "/"), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    parser = SvnIndexParser()
    parser.feed(html)
    numbers = parse_nho_material_names(parser.hrefs, limit)
    NHO_MATERIAL_CACHE["numbers"] = numbers
    NHO_MATERIAL_CACHE["expires_at"] = now_ts + int(os.environ.get("NHO_MATERIAL_CACHE_SECONDS", str(NHO_MATERIAL_CACHE_SECONDS)))
    return numbers[:limit]


def list_standard_material_numbers(force_refresh: bool = False, limit: int = 200) -> list[str]:
    now_ts = time.time()
    cached = list(STANDARD_MATERIAL_CACHE.get("numbers") or [])
    if cached and not force_refresh and now_ts < float(STANDARD_MATERIAL_CACHE.get("expires_at") or 0):
        return cached[:limit]

    svn_url = os.environ.get("STANDARD_MATERIAL_SVN_URL", STANDARD_MATERIAL_SVN_URL)
    svn_username = os.environ.get("STANDARD_MATERIAL_SVN_USERNAME", STANDARD_MATERIAL_SVN_USERNAME)
    svn_password = os.environ.get("STANDARD_MATERIAL_SVN_PASSWORD", STANDARD_MATERIAL_SVN_PASSWORD)
    try:
        numbers, dirs = list_standard_material_numbers_with_svn(svn_url, svn_username, svn_password, limit)
        STANDARD_MATERIAL_CACHE["numbers"] = numbers
        STANDARD_MATERIAL_CACHE["dirs"] = dirs
        STANDARD_MATERIAL_CACHE["expires_at"] = now_ts + int(os.environ.get("STANDARD_MATERIAL_CACHE_SECONDS", str(STANDARD_MATERIAL_CACHE_SECONDS)))
        return numbers[:limit]
    except RuntimeError:
        if svn_username or svn_password:
            raise

    headers = {}
    if svn_username or svn_password:
        token = f"{svn_username}:{svn_password}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(token).decode("ascii")
    req = urllib.request.Request(quote_url(svn_url.rstrip("/") + "/"), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    parser = SvnIndexParser()
    parser.feed(html)
    numbers, dirs = parse_standard_material_names(parser.hrefs, limit)
    STANDARD_MATERIAL_CACHE["numbers"] = numbers
    STANDARD_MATERIAL_CACHE["dirs"] = dirs
    STANDARD_MATERIAL_CACHE["expires_at"] = now_ts + int(os.environ.get("STANDARD_MATERIAL_CACHE_SECONDS", str(STANDARD_MATERIAL_CACHE_SECONDS)))
    return numbers[:limit]


def svn_auth_command(base: list[str], svn_username: str, svn_password: str) -> list[str]:
    command = [*base, "--non-interactive", "--trust-server-cert", "--no-auth-cache"]
    if svn_username:
        command.extend(["--username", svn_username])
    if svn_password:
        command.extend(["--password", svn_password])
    return command


def require_nho_material_svn_credentials(svn_username: str, svn_password: str) -> None:
    if not svn_username or not svn_password:
        raise RuntimeError("NHO material SVN credentials are missing on build terminal: set NHO_MATERIAL_SVN_USERNAME and NHO_MATERIAL_SVN_PASSWORD")


def run_svn_text(args: list[str], timeout: int = 60) -> str:
    svn_bin = shutil.which("svn")
    if not svn_bin:
        raise RuntimeError("svn command is not available")
    proc = subprocess.run([svn_bin, *args], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "svn command failed").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "svn command failed")
    return proc.stdout


def run_svn_binary(args: list[str], timeout: int = 120) -> bytes:
    svn_bin = shutil.which("svn")
    if not svn_bin:
        raise RuntimeError("svn command is not available")
    proc = subprocess.run([svn_bin, *args], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or b"svn command failed")
        text = detail.decode("utf-8", "replace") if isinstance(detail, bytes) else str(detail)
        lines = text.strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "svn command failed")
    return proc.stdout


def cell_ref_to_row_col(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not match:
        return 0, 0
    col = 0
    for ch in match.group(1):
        col = col * 26 + ord(ch) - ord("A") + 1
    return int(match.group(2)), col


def read_xlsx_sheet_rows(xlsx_bytes: bytes, sheet_name: str) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        sheet_target = ""
        rel_key = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        for sheet in workbook.findall("a:sheets/a:sheet", XLSX_NS):
            if sheet.attrib.get("name") == sheet_name:
                sheet_target = rel_map[sheet.attrib[rel_key]].lstrip("/")
                break
        if not sheet_target:
            raise RuntimeError(f"sheet not found: {sheet_name}")

        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in shared_root.findall("a:si", XLSX_NS):
                shared_strings.append("".join(t.text or "" for t in si.findall(".//a:t", XLSX_NS)))

        sheet_path = "xl/" + sheet_target
        sheet_root = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str]] = []
        for row in sheet_root.findall("a:sheetData/a:row", XLSX_NS):
            values: dict[int, str] = {}
            for cell in row.findall("a:c", XLSX_NS):
                _, col = cell_ref_to_row_col(cell.attrib.get("r", ""))
                value_node = cell.find("a:v", XLSX_NS)
                value = ""
                if value_node is not None and value_node.text is not None:
                    value = value_node.text
                    if cell.attrib.get("t") == "s":
                        value = shared_strings[int(value)]
                if col:
                    values[col] = str(value).strip()
            max_col = max(values) if values else 0
            rows.append([values.get(idx, "") for idx in range(1, max_col + 1)])
        return rows


def normalize_release_branch(value: str) -> str:
    text = str(value or "").strip()
    return "" if text in {"無し", "なし", "無", "无", "None", "none"} else text


def branch_from_release_section(rows: list[list[str]], section_marker: str) -> str:
    section_re = re.compile(rf"^[①②③④⑤⑥⑦⑧⑨⑩]\s*{re.escape(section_marker)}\b")
    start_idx = next((idx for idx, row in enumerate(rows) if any(section_re.search(cell or "") for cell in row)), -1)
    if start_idx < 0:
        return ""
    end_idx = len(rows)
    for idx in range(start_idx + 1, len(rows)):
        if any(re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", cell or "") for cell in rows[idx]):
            end_idx = idx
            break
    for idx in range(start_idx + 1, end_idx):
        row = rows[idx]
        try:
            branch_col = row.index("gitlab-branch")
        except ValueError:
            continue
        for value_row in rows[idx + 1 : end_idx]:
            if branch_col < len(value_row):
                branch = normalize_release_branch(value_row[branch_col])
                if branch or value_row[branch_col].strip() in {"無し", "なし", "無", "无"}:
                    return branch
    return ""


def extract_nho_release_branches_from_xlsx(xlsx_bytes: bytes) -> dict[str, str]:
    rows = read_xlsx_sheet_rows(xlsx_bytes, "リリース作業")
    return {
        "frontend_branch": branch_from_release_section(rows, "Frontend"),
        "backend_branch": branch_from_release_section(rows, "Backend"),
    }


def find_nho_release_checklist_path(material_url: str, svn_username: str, svn_password: str) -> str:
    ls_args = svn_auth_command(["ls", "-R"], svn_username, svn_password)
    files = run_svn_text([*ls_args, material_url], timeout=120).splitlines()
    candidates = [
        name.strip().rstrip("/")
        for name in files
        if "リリースチェックリスト" in name and name.lower().endswith((".xlsx", ".xlsm"))
    ]
    if not candidates:
        raise RuntimeError("リリースチェックリスト Excel が見つかりません")
    return sorted(
        candidates,
        key=lambda name: (
            Path(name).name not in {"リリースチェックリスト.xlsx", "リリースチェックリスト.xlsm"},
            name.count("/"),
            name.lower(),
        ),
    )[0]


def get_nho_material_release_branches(material_number: str) -> dict[str, str]:
    if not re.fullmatch(r"\d{8}", material_number or ""):
        raise RuntimeError("invalid material_number")
    svn_url = os.environ.get("NHO_MATERIAL_SVN_URL", NHO_MATERIAL_SVN_URL).rstrip("/")
    svn_username = os.environ.get("NHO_MATERIAL_SVN_USERNAME", NHO_MATERIAL_SVN_USERNAME)
    svn_password = os.environ.get("NHO_MATERIAL_SVN_PASSWORD", NHO_MATERIAL_SVN_PASSWORD)
    require_nho_material_svn_credentials(svn_username, svn_password)
    material_url = f"{svn_url}/{material_number}リリース作業"
    checklist = find_nho_release_checklist_path(material_url, svn_username, svn_password)
    cat_args = svn_auth_command(["cat"], svn_username, svn_password)
    source_url = f"{material_url}/{checklist}"
    result = extract_nho_release_branches_from_xlsx(run_svn_binary([*cat_args, source_url]))
    result["material_number"] = material_number
    result["source"] = source_url
    return result


def parse_standard_version_txt(text: str) -> dict[str, str]:
    result = {"frontend_branch": "", "backend_branch": "", "help_docs_svn_revision": ""}
    for raw in text.replace("\r", "\n").splitlines():
        line = raw.strip()
        if not line or ("：" not in line and ":" not in line):
            continue
        key, _, value = line.replace("：", ":", 1).partition(":")
        key_lower = key.strip().lower()
        value = value.strip()
        if not value or value in ("-", "無し"):
            value = ""
        if "前台" in key or "frontend" in key_lower or "front" in key_lower:
            result["frontend_branch"] = value
        elif "后台" in key or "backend" in key_lower or "back" in key_lower:
            result["backend_branch"] = value
        elif "help" in key_lower and ("revision" in key_lower or "version" in key_lower or "rev" in key_lower):
            result["help_docs_svn_revision"] = value if re.fullmatch(r"\d+", value or "") else ""
    return result


def standard_material_dir_name(material_number: str) -> str:
    if not re.fullmatch(r"\d{8}", material_number or ""):
        raise RuntimeError("invalid material_number")
    cached_dirs = dict(STANDARD_MATERIAL_CACHE.get("dirs") or {})
    if material_number in cached_dirs:
        return cached_dirs[material_number]
    list_standard_material_numbers(force_refresh=True)
    cached_dirs = dict(STANDARD_MATERIAL_CACHE.get("dirs") or {})
    if material_number in cached_dirs:
        return cached_dirs[material_number]
    raise RuntimeError("standard material directory not found")


def get_standard_material_release_branches(material_number: str) -> dict[str, str]:
    svn_url = os.environ.get("STANDARD_MATERIAL_SVN_URL", STANDARD_MATERIAL_SVN_URL).rstrip("/")
    svn_username = os.environ.get("STANDARD_MATERIAL_SVN_USERNAME", STANDARD_MATERIAL_SVN_USERNAME)
    svn_password = os.environ.get("STANDARD_MATERIAL_SVN_PASSWORD", STANDARD_MATERIAL_SVN_PASSWORD)
    material_dir = standard_material_dir_name(material_number)
    source_url = f"{svn_url}/{material_dir}/version.txt"
    cat_args = svn_auth_command(["cat"], svn_username, svn_password)
    result = parse_standard_version_txt(run_svn_text([*cat_args, source_url], timeout=60))
    result["material_number"] = material_number
    result["source"] = source_url
    return result


def export_nho_material_database_assets_zip(material_number: str) -> bytes:
    if not re.fullmatch(r"\d{8}", material_number or ""):
        raise RuntimeError("invalid material_number")
    svn_url = os.environ.get("NHO_MATERIAL_SVN_URL", NHO_MATERIAL_SVN_URL).rstrip("/")
    svn_username = os.environ.get("NHO_MATERIAL_SVN_USERNAME", NHO_MATERIAL_SVN_USERNAME)
    svn_password = os.environ.get("NHO_MATERIAL_SVN_PASSWORD", NHO_MATERIAL_SVN_PASSWORD)
    require_nho_material_svn_credentials(svn_username, svn_password)
    export_args = svn_auth_command(["export", "--force"], svn_username, svn_password)
    material_url = f"{svn_url}/{material_number}リリース作業"
    with tempfile.TemporaryDirectory(prefix=f"nho-material-{material_number}-") as tmp:
        root = Path(tmp)
        for dirname in ("データ連携", "製品"):
            source_url = f"{material_url}/{dirname}"
            target_dir = root / dirname
            run_svn_text([*export_args, source_url, str(target_dir)], timeout=300)
            if not target_dir.exists():
                raise RuntimeError(f"NHO material folder was not exported: {dirname}")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for source_dir in (root / "データ連携", root / "製品"):
                for path in sorted(source_dir.rglob("*")):
                    arcname = path.relative_to(root).as_posix()
                    if path.is_dir():
                        zf.writestr(arcname.rstrip("/") + "/", b"")
                    elif path.suffix.lower() == ".sql":
                        zf.write(path, arcname)
        return buffer.getvalue()


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
    metadata_files: list[Path] = []
    for path in DATA_DIR.iterdir():
        if path.name in PRODUCT_VARIANTS and path.is_dir():
            metadata_files.extend(child / "metadata.json" for child in path.iterdir())
            continue
        metadata_files.append(path / "metadata.json")
    for mp in metadata_files:
        if mp.is_file():
            try:
                builds.append(read_json(mp))
            except json.JSONDecodeError:
                continue
    return sorted(builds, key=lambda item: item.get("created_at") or item.get("id") or "", reverse=True)


def mark_unfinished_builds_failed(reason: str = "build_console_restarted_while_running") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    metadata_files: list[Path] = []
    for path in DATA_DIR.iterdir():
        if path.name in PRODUCT_VARIANTS and path.is_dir():
            metadata_files.extend(child / "metadata.json" for child in path.iterdir())
            continue
        metadata_files.append(path / "metadata.json")
    for mp in metadata_files:
        if not mp.is_file():
            continue
        try:
            meta = read_json(mp)
        except json.JSONDecodeError:
            continue
        if meta.get("status") not in ("queued", "running"):
            continue
        build_id = str(meta.get("id") or path.name)
        meta["status"] = "failed"
        meta["error"] = reason
        meta["updated_at"] = now()
        for step in meta.get("steps", []):
            if step.get("status") == "running":
                step["status"] = "failed"
                step["message"] = reason
                step["finished_at"] = now()
            elif step.get("status") == "pending":
                step["status"] = "skipped"
                step["message"] = reason
        write_json(mp, meta)
        append_log(build_id, f"构建失败：{reason}")


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
            qs = urllib.parse.parse_qs(parsed.query)
            product_variant = str(qs.get("product_variant", ["standard"])[0] or "standard").lower()
            return self.send_json({"branches": list_backend_release_branches(product_variant)})
        if path == "/api/frontend-branches":
            qs = urllib.parse.parse_qs(parsed.query)
            product_variant = str(qs.get("product_variant", ["standard"])[0] or "standard").lower()
            return self.send_json({"branches": list_frontend_workspace_branches(product_variant)})
        if path == "/api/data-sync-custom-source/validate":
            qs = urllib.parse.parse_qs(parsed.query)
            value = str(qs.get("value", [""])[0] or "").strip()
            try:
                return self.send_json(validate_data_sync_custom_source(value))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/help-docs-svn-revision/validate":
            qs = urllib.parse.parse_qs(parsed.query)
            value = str(qs.get("value", [""])[0] or "").strip()
            try:
                return self.send_json(validate_help_docs_svn_revision(value))
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/nho-material-numbers":
            qs = urllib.parse.parse_qs(parsed.query)
            force = str(qs.get("refresh", [""])[0]).lower() in ("1", "true", "yes")
            try:
                return self.send_json({"material_numbers": list_nho_material_numbers(force_refresh=force)})
            except Exception as exc:
                return self.send_json({"material_numbers": [], "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        if path == "/api/standard-material-numbers":
            qs = urllib.parse.parse_qs(parsed.query)
            force = str(qs.get("refresh", [""])[0]).lower() in ("1", "true", "yes")
            try:
                return self.send_json({"material_numbers": list_standard_material_numbers(force_refresh=force)})
            except Exception as exc:
                return self.send_json({"material_numbers": [], "error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        if path == "/api/nho-material-release-branches":
            qs = urllib.parse.parse_qs(parsed.query)
            material_number = str(qs.get("material_number", [""])[0] or "").strip()
            try:
                return self.send_json(get_nho_material_release_branches(material_number))
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        if path == "/api/standard-material-release-branches":
            qs = urllib.parse.parse_qs(parsed.query)
            material_number = str(qs.get("material_number", [""])[0] or "").strip()
            try:
                return self.send_json(get_standard_material_release_branches(material_number))
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
        if path == "/api/nho-material-database-assets":
            qs = urllib.parse.parse_qs(parsed.query)
            material_number = str(qs.get("material_number", [""])[0] or "").strip()
            try:
                data = export_nho_material_database_assets_zip(material_number)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)
            filename = f"nho-material-{material_number}-database-assets.zip"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/system-resources":
            return self.send_json(system_resource_status())
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

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        m = re.fullmatch(r"/api/builds/([^/]+)", parsed.path)
        if not m:
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            result = delete_build(m.group(1))
        except FileNotFoundError:
            return self.send_error(HTTPStatus.NOT_FOUND)
        status = HTTPStatus.CONFLICT if result.get("error") == "build_running" else HTTPStatus.OK
        return self.send_json(result, status)

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
        product_variant = None
        if metadata_path(build_id).is_file():
            meta = sync_drone_build(build_id)
            product_variant = (meta.get("request") or {}).get("product_variant")
        path = shared_artifact_path(build_id, name, product_variant)
        if not path.is_file():
            path = artifact_path(build_id, name, product_variant)
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
<html lang="ja-JP">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OHR Build Console</title>
  <link rel="stylesheet" href="/style.css?v=4">
</head>
<body>
  <main>
    <section class="hero">
      <div>
        <div class="eyebrow">OHR Build Console</div>
        <h1 data-i18n="title">OHR ビルドコンソール</h1>
        <p class="muted" data-i18n="subtitle">前後端の分岐と顧客設定を指定し、ビルド端末で package.zip と web.zip を生成します。</p>
      </div>
      <div class="language-box">
        <label for="language" data-i18n="language">表示言語</label>
        <select id="language">
          <option value="ja-JP">日本語</option>
          <option value="zh-CN">中文</option>
          <option value="en-US">English</option>
        </select>
      </div>
      <div class="hero-panel">
        <span class="status-dot"></span>
        <div>
          <strong data-i18n="modeTitle">ローカルビルドモード</strong>
          <small data-i18n="modeDesc">direct：ビルド端末上で package.zip と web.zip を生成します</small>
        </div>
      </div>
    </section>
    <section class="card form-card">
      <div class="section-title">
        <div>
          <h2 data-i18n="paramsTitle">ビルドパラメータ</h2>
          <p class="muted" data-i18n="paramsDesc">バックエンド分岐はバックエンドリポジトリから取得し、フロントエンド版本分岐は四つの子プロジェクトに共通する release_* 分岐を使用します。ohr-workspace は master 固定です。</p>
        </div>
      </div>
      <form id="build-form">
        <div class="target-row">
          <span class="field-caption" data-i18n="productVariant">製品バージョン</span>
          <label class="toggle-option"><input name="product_variant" type="radio" value="standard" checked> <span data-i18n="variantStandard">標準版</span></label>
          <label class="toggle-option"><input name="product_variant" type="radio" value="nho"> <span data-i18n="variantNho">NHO版</span></label>
        </div>
        <div class="target-row">
          <label class="toggle-option"><input id="toggle-backend" type="checkbox" checked> <span data-i18n="buildBackend">バックエンド package.zip を構築</span></label>
          <label class="toggle-option"><input id="toggle-frontend" type="checkbox" checked> <span data-i18n="buildFrontend">フロントエンド web.zip を構築</span></label>
        </div>
        <div class="form-grid three">
          <div class="field-block">
            <label for="input-backend-branch" data-i18n="backendBranch">バックエンドブランチ</label>
            <input id="input-backend-branch" name="backend_branch" list="backend-branches" placeholder="例如 release_20260129" autocomplete="off">
            <datalist id="backend-branches"></datalist>
          </div>
          <div class="field-block">
            <label for="input-frontend-release" data-i18n="frontendBranch">フロントエンド版本分岐（四つの子プロジェクト共通）</label>
            <input id="input-frontend-release" list="frontend-branches" placeholder="例如 release_20260325" autocomplete="off">
            <datalist id="frontend-branches"></datalist>
          </div>
          <div class="field-block standard-only">
            <label for="input-help-docs-revision" data-i18n="helpSvnRevision">Help SVN Revision</label>
            <input id="input-help-docs-revision" name="help_docs_svn_revision" data-i18n-placeholder="helpSvnRevisionPlaceholder" autocomplete="off">
          </div>
          <label class="toggle-option standard-only"><input id="toggle-help" name="build_help" type="checkbox" checked> <span data-i18n="buildHelp">Help パッケージと関連資材を生成</span></label>
        </div>
        <details class="sync-hint standard-only">
          <summary data-i18n="frontendRuleTitle">フロントエンド分岐ルール</summary>
          <p class="muted" data-i18n="frontendRuleDesc">ohr-workspace は release_* 分岐を使用せず、構築時は master 固定です。選択した版本分岐は ohr-feelin、ohr-lowcode-engine、ohr-nocode-engine、ohr-micro-frontends に使用します。</p>
        </details>
        <p class="muted source-note standard-only" data-i18n="directSourceDesc">Direct 方式：conf_prod は ohr-cicd から生成し、help は ohr-help-docs + SVN から生成します。</p>
        <div class="subsection-title standard-only" data-i18n="customerConfig">顧客設定</div>
        <div class="form-grid four standard-only">
          <div class="field-block">
            <label for="input-conf-server-host" data-i18n="customerHost">顧客アクセスアドレス</label>
            <input id="input-conf-server-host" name="conf_server_host" placeholder="例如 192.168.70.136" autocomplete="off">
          </div>
          <div class="field-block">
            <label for="input-conf-web-port" data-i18n="webPort">Web ポート</label>
            <input id="input-conf-web-port" name="conf_web_port" type="number" min="1" max="65535" value="80" autocomplete="off">
          </div>
          <label class="toggle-card inline-toggle">
            <input id="input-conf-enable-https" name="conf_enable_https" type="checkbox">
            <span data-i18n="enableHttps">HTTPS / 443 設定を生成</span>
          </label>
          <div class="field-block">
            <label for="input-conf-worker-processes">worker_processes</label>
            <input id="input-conf-worker-processes" name="conf_worker_processes" type="number" min="1" value="1" autocomplete="off">
          </div>
          <div class="field-block">
            <label for="input-conf-worker-connections">worker_connections</label>
            <input id="input-conf-worker-connections" name="conf_worker_connections" type="number" min="1" value="1024" autocomplete="off">
          </div>
        </div>
        <div class="form-grid">
          <label><span data-i18n="note">備考</span> <input name="note" data-i18n-placeholder="notePlaceholder" placeholder="例：検証環境初回構築"></label>
        </div>
        <div class="form-grid">
          <div class="submit-row">
            <button id="start-button" type="submit" data-i18n="startBuild">ビルド開始</button>
            <button id="stop-button" class="danger" type="button" hidden data-i18n="stopBuild">ビルド停止</button>
          </div>
        </div>
      </form>
    </section>
    <section class="grid">
      <div class="card history-card">
        <div class="section-title compact">
          <h2 data-i18n="historyTitle">ビルド履歴</h2>
          <span class="muted" data-i18n="recentTasks">最近のタスク</span>
        </div>
        <div id="build-list"></div>
      </div>
      <div class="card">
        <div class="section-title compact">
          <h2 data-i18n="stepsTitle">ビルドステップ</h2>
          <span class="muted" data-i18n="statusTrace">状態追跡</span>
        </div>
        <div id="build-detail" class="empty-state" data-i18n="selectBuild">ビルドを選択または開始してください。</div>
      </div>
    </section>
    <section class="card">
      <div class="section-title compact">
        <h2 data-i18n="logTitle">リアルタイムログ</h2>
        <span class="muted" data-i18n="autoScroll">自動スクロール</span>
      </div>
      <pre id="log"></pre>
    </section>
  </main>
  <script src="/app.js?v=9"></script>
</body>
</html>
"""


APP_JS = r"""
const I18N = {
  'ja-JP': {
    title: 'OHR ビルドコンソール',
    subtitle: '前後端の分岐と顧客設定を指定し、ビルド端末で package.zip と web.zip を生成します。',
    language: '表示言語',
    modeTitle: 'ローカルビルドモード',
    modeDesc: 'direct：ビルド端末上で package.zip と web.zip を生成します',
    paramsTitle: 'ビルドパラメータ',
    paramsDesc: 'バックエンド分岐はバックエンドリポジトリから取得し、フロントエンド版本分岐は四つの子プロジェクトに共通する release_* 分岐を使用します。ohr-workspace は master 固定です。',
    productVariant: '製品バージョン',
    variantStandard: '標準版',
    variantNho: 'NHO版',
    buildBackend: 'バックエンド package.zip を構築',
    buildFrontend: 'フロントエンド web.zip を構築',
    buildHelp: 'Help パッケージと関連資材を生成',
    backendBranch: 'バックエンドブランチ',
    frontendBranch: 'フロントエンド版本分岐（四つの子プロジェクト共通）',
    helpBranch: 'Help 文書ブランチ',
    helpSvnRevision: 'Help SVN Revision',
    helpSvnRevisionPlaceholder: '空欄の場合は最新 revision',
    frontendRuleTitle: 'フロントエンド分岐ルール',
    frontendRuleDesc: 'ohr-workspace は release_* 分岐を使用せず、構築時は master 固定です。選択した版本分岐は ohr-feelin、ohr-lowcode-engine、ohr-nocode-engine、ohr-micro-frontends に使用します。',
    directSourceDesc: 'Direct 方式：conf_prod は ohr-cicd から生成し、help は ohr-help-docs + SVN から生成します。',
    customerConfig: '顧客設定',
    customerHost: '顧客アクセスアドレス',
    webPort: 'Web ポート',
    enableHttps: 'HTTPS / 443 設定を生成',
    note: '備考',
    notePlaceholder: '例：検証環境初回構築',
    startBuild: 'ビルド開始',
    stopBuild: 'ビルド停止',
    stopping: '停止中...',
    historyTitle: 'ビルド履歴',
    recentTasks: '最近のタスク',
    stepsTitle: 'ビルドステップ',
    statusTrace: '状態追跡',
    selectBuild: 'ビルドを選択または開始してください。',
    noBuilds: 'ビルド履歴はありません。',
    logTitle: 'リアルタイムログ',
    autoScroll: '自動スクロール',
    createFailed: 'ビルド作成に失敗しました',
    needTarget: '少なくとも一つの構築対象を選択してください',
    needBackend: 'バックエンドブランチを入力してください',
    needFrontend: 'フロントエンド版本分岐を入力してください',
    needHelp: 'Help SVN revision は数字で入力してください',
    needCustomer: '顧客アクセスアドレスを入力してください',
    badPort: 'Web ポートは 1-65535 の範囲で入力してください',
    badWorker: 'worker 設定は 1 以上の整数で入力してください',
    download: 'ダウンロード',
    buildId: 'ビルド番号',
    executor: '実行方式',
    httpsMode: 'HTTPS 設定',
    workspaceBranch: 'workspace ブランチ',
    worker: 'worker',
    status: {queued:'待機中', running:'実行中', success:'成功', failed:'失敗', cancelled:'停止済み', pending:'待機', skipped:'スキップ'},
    steps: {validate:'パラメータ検証', checkout_backend:'バックエンド取得', build_backend:'バックエンド package.zip', restore_frontend:'フロントエンド作業区復元', build_frontend:'フロントエンド web.zip', collect_artifacts:'成果物収集'}
  },
  'zh-CN': {
    title: 'OHR 构建入口',
    subtitle: '填写前后端分支参数，在构建终端生成 package.zip 和 web.zip。',
    language: '显示语言',
    modeTitle: '本机构建模式',
    modeDesc: 'direct：由构建终端直接构建并产出 package.zip + web.zip',
    paramsTitle: '构建参数',
    paramsDesc: '后端分支来自后端仓库；前端版本分支来自四个子项目共同存在的 release_* 分支。ohr-workspace 固定使用 master。',
    productVariant: '产品版本',
    variantStandard: '标准版',
    variantNho: 'NHO版',
    buildBackend: '构建后端 package.zip',
    buildFrontend: '构建前端 web.zip',
    buildHelp: '生成 Help 包及相关资源',
    backendBranch: '后端分支',
    frontendBranch: '前端版本分支（四个子项目共同存在）',
    helpBranch: 'Help 文档分支',
    helpSvnRevision: 'Help SVN Revision',
    helpSvnRevisionPlaceholder: '不填则使用最新 revision',
    frontendRuleTitle: '前端分支规则',
    frontendRuleDesc: 'ohr-workspace 不使用 release_* 分支，构建时固定检出 master；上方选择的版本分支会同时用于四个子项目。',
    directSourceDesc: 'Direct 方式：conf_prod 来自 ohr-cicd 生成，help 来自 ohr-help-docs + SVN 生成。',
    customerConfig: '客户配置区',
    customerHost: '客户访问地址',
    webPort: 'Web 端口',
    enableHttps: '生成 HTTPS / 443 配置',
    note: '备注',
    notePlaceholder: '例如：测试环境首次打包',
    startBuild: '开始构建',
    stopBuild: '停止构建',
    stopping: '正在停止...',
    historyTitle: '构建记录',
    recentTasks: '最近任务',
    stepsTitle: '构建步骤',
    statusTrace: '状态追踪',
    selectBuild: '请选择或启动一个构建。',
    noBuilds: '还没有构建记录。',
    logTitle: '实时日志',
    autoScroll: '自动滚动',
    createFailed: '创建构建失败',
    needTarget: '请至少选择一个构建目标',
    needBackend: '请选择或填写后端分支',
    needFrontend: '请选择或填写前端版本分支',
    needHelp: 'Help SVN revision 只能填写数字',
    needCustomer: '请填写客户访问地址',
    badPort: 'Web 端口必须在 1-65535 之间',
    badWorker: 'worker 配置必须是大于 0 的整数',
    download: '下载',
    buildId: '构建编号',
    executor: '执行器',
    httpsMode: 'HTTPS 配置',
    workspaceBranch: 'workspace 分支',
    worker: 'worker',
    status: {queued:'排队中', running:'运行中', success:'成功', failed:'失败', cancelled:'已停止', pending:'等待', skipped:'跳过'},
    steps: {validate:'参数校验', checkout_backend:'拉取后端代码', build_backend:'后端打包', restore_frontend:'恢复前端工作区', build_frontend:'前端 web.zip', collect_artifacts:'收集产物'}
  },
  'en-US': {
    title: 'OHR Build Console',
    subtitle: 'Provide backend/frontend branches and customer settings to generate package.zip and web.zip on the build terminal.',
    language: 'Language',
    modeTitle: 'Local build mode',
    modeDesc: 'direct: package.zip and web.zip are built on the build terminal',
    paramsTitle: 'Build parameters',
    paramsDesc: 'The backend branch comes from the backend repository; the frontend release branch must exist in the four frontend child projects. ohr-workspace uses master.',
    productVariant: 'Product version',
    variantStandard: 'Standard',
    variantNho: 'NHO',
    buildBackend: 'Build backend package.zip',
    buildFrontend: 'Build frontend web.zip',
    buildHelp: 'Build Help package and resources',
    backendBranch: 'Backend branch',
    frontendBranch: 'Frontend release branch',
    helpBranch: 'Help docs branch',
    helpSvnRevision: 'Help SVN Revision',
    helpSvnRevisionPlaceholder: 'Leave empty to use the latest revision',
    frontendRuleTitle: 'Frontend branch rule',
    frontendRuleDesc: 'ohr-workspace does not use release_* branches and stays on master. The selected release branch is used for the four frontend child projects.',
    directSourceDesc: 'Direct mode: conf_prod is generated from ohr-cicd; help is generated from ohr-help-docs + SVN.',
    customerConfig: 'Customer configuration',
    customerHost: 'Customer access address',
    webPort: 'Web port',
    enableHttps: 'Generate HTTPS / 443 configuration',
    note: 'Note',
    notePlaceholder: 'Example: first test build',
    startBuild: 'Start build',
    stopBuild: 'Stop build',
    stopping: 'Stopping...',
    historyTitle: 'Build history',
    recentTasks: 'Recent tasks',
    stepsTitle: 'Build steps',
    statusTrace: 'Status tracking',
    selectBuild: 'Select or start a build.',
    noBuilds: 'No builds yet.',
    logTitle: 'Live log',
    autoScroll: 'Auto scroll',
    createFailed: 'Failed to create build',
    needTarget: 'Select at least one build target',
    needBackend: 'Enter a backend branch',
    needFrontend: 'Enter a frontend release branch',
    needHelp: 'Help SVN revision must be numeric',
    needCustomer: 'Enter a customer access address',
    badPort: 'Web port must be between 1 and 65535',
    badWorker: 'Worker settings must be integers greater than 0',
    download: 'Download',
    buildId: 'Build ID',
    executor: 'Executor',
    httpsMode: 'HTTPS configuration',
    workspaceBranch: 'Workspace branch',
    worker: 'worker',
    status: {queued:'Queued', running:'Running', success:'Success', failed:'Failed', cancelled:'Stopped', pending:'Pending', skipped:'Skipped'},
    steps: {validate:'Validate parameters', checkout_backend:'Checkout backend', build_backend:'Backend package.zip', restore_frontend:'Restore frontend workspace', build_frontend:'Frontend web.zip', collect_artifacts:'Collect artifacts'}
  }
};

let lang = localStorage.getItem('buildConsoleLang') || 'ja-JP';
function t(key) {
  const parts = key.split('.');
  let value = I18N[lang] || I18N['ja-JP'];
  for (const part of parts) value = value && value[part];
  return value || key;
}
function applyI18n() {
  document.documentElement.lang = lang;
  document.title = t('title');
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  const selector = document.getElementById('language');
  if (selector) selector.value = lang;
}
function translateLogText(text) {
  const maps = {
    'ja-JP': {
      '构建开始': '構築開始',
      '参数校验': 'パラメータ検証',
      '拉取后端代码': 'バックエンド取得',
      '后端打包': 'バックエンド package.zip',
      '恢复前端工作区': 'フロントエンド作業区復元',
      '前端 web.zip': 'フロントエンド web.zip',
      '收集产物': '成果物収集',
      '产物已收集': '成果物を収集しました',
      '构建成功': '構築成功',
      '构建失败': '構築失敗',
      '构建已停止': '構築を停止しました',
      '收到停止请求': '停止要求を受け付けました',
      '另一个构建正在运行': '別の構築が実行中です'
    },
    'en-US': {
      '构建开始': 'Build started',
      '参数校验': 'Validate parameters',
      '拉取后端代码': 'Checkout backend',
      '后端打包': 'Backend package.zip',
      '恢复前端工作区': 'Restore frontend workspace',
      '前端 web.zip': 'Frontend web.zip',
      '收集产物': 'Collect artifacts',
      '产物已收集': 'Artifacts collected',
      '构建成功': 'Build succeeded',
      '构建失败': 'Build failed',
      '构建已停止': 'Build stopped',
      '收到停止请求': 'Stop requested',
      '另一个构建正在运行': 'Another build is running'
    }
  };
  const map = maps[lang] || {};
  let result = text || '';
  Object.entries(map).forEach(([from, to]) => { result = result.split(from).join(to); });
  return result;
}

let currentBuild = null;
let logOffset = 0;
let logLines = [];
let timer = null;
const params = new URLSearchParams(window.location.search);
const embeddedMode = params.get('embedded') === '1';
const embeddedBuildId = params.get('build_id') || '';
const MAX_LOG_LINES = embeddedMode ? 900 : 1600;

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
  const productVariant = getProductVariant();
  const isNho = productVariant === 'nho';
  const buildBackend = document.getElementById('toggle-backend').checked;
  const buildFrontend = document.getElementById('toggle-frontend').checked;
  const buildHelp = document.getElementById('toggle-help') ? document.getElementById('toggle-help').checked : true;
  const backendBranch = (form.get('backend_branch') || '').trim();
  const ws = getFrontendWorkspaceBranch();
  const helpDocsRevision = (form.get('help_docs_svn_revision') || '').trim();
  const confServerHost = (form.get('conf_server_host') || '').trim();
  const confWebPort = Number(form.get('conf_web_port') || 80);
  const confEnableHttps = document.getElementById('input-conf-enable-https').checked;
  const confWorkerProcesses = Number(form.get('conf_worker_processes') || 1);
  const confWorkerConnections = Number(form.get('conf_worker_connections') || 1024);
  if (!buildBackend && !buildFrontend) {
    setFormLocked(false);
    alert(t('needTarget'));
    return;
  }
  if (buildBackend && !backendBranch) {
    setFormLocked(false);
    alert(t('needBackend'));
    return;
  }
  if (buildFrontend && !ws) {
    setFormLocked(false);
    alert(t('needFrontend'));
    return;
  }
  if (!isNho && buildFrontend && buildHelp && helpDocsRevision && !/^\d+$/.test(helpDocsRevision)) {
    setFormLocked(false);
    alert(t('needHelp'));
    return;
  }
  if (!isNho && buildFrontend && !confServerHost) {
    setFormLocked(false);
    alert(t('needCustomer'));
    return;
  }
  if (!isNho && buildFrontend && (!Number.isInteger(confWebPort) || confWebPort < 1 || confWebPort > 65535)) {
    setFormLocked(false);
    alert(t('badPort'));
    return;
  }
  if (!isNho && buildFrontend && (!Number.isInteger(confWorkerProcesses) || confWorkerProcesses < 1 || !Number.isInteger(confWorkerConnections) || confWorkerConnections < 1)) {
    setFormLocked(false);
    alert(t('badWorker'));
    return;
  }
  setFormLocked(true);
  const payload = {
    product_variant: productVariant,
    build_backend: buildBackend,
    build_frontend: buildFrontend,
    build_help: buildHelp,
    backend_branch: backendBranch,
    frontend_release_branch: ws,
    help_docs_svn_revision: helpDocsRevision,
    conf_server_host: confServerHost,
    conf_web_port: confWebPort,
    conf_enable_https: confEnableHttps,
    conf_worker_processes: confWorkerProcesses,
    conf_worker_connections: confWorkerConnections,
    note: form.get('note')
  };
  const res = await fetch('/api/builds', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const data = await res.json();
  if (!res.ok) {
    setFormLocked(false);
    alert(data.error || t('createFailed'));
    return;
  }
  selectBuild(data.id);
});

document.getElementById('stop-button').addEventListener('click', async () => {
  if (embeddedMode) return;
  if (!currentBuild) return;
  const btn = document.getElementById('stop-button');
  btn.disabled = true;
  btn.textContent = t('stopping');
  try {
    await fetch(`/api/builds/${currentBuild}/cancel`, { method: 'POST' });
    await refreshCurrent();
  } finally {
    btn.textContent = t('stopBuild');
  }
});

document.getElementById('language').addEventListener('change', event => {
  lang = event.target.value;
  localStorage.setItem('buildConsoleLang', lang);
  applyI18n();
  loadBuilds();
  if (currentBuild) refreshCurrent();
});

function applyEmbeddedMode() {
  if (!embeddedMode) return;
  document.body.classList.add('embedded');
  document.getElementById('stop-button').hidden = true;
  if (embeddedBuildId) selectBuild(embeddedBuildId);
}

function setFormLocked(locked) {
  document.querySelectorAll('#build-form input, #build-form button').forEach(el => {
    if (el.id !== 'stop-button') el.disabled = locked;
  });
  if (embeddedMode) {
    document.getElementById('start-button').hidden = true;
    document.getElementById('stop-button').hidden = true;
    return;
  }
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
  const helpDocsInput = document.getElementById('input-help-docs-revision');
  const helpToggle = document.getElementById('toggle-help');
  const confInputs = [
    document.getElementById('input-conf-server-host'),
    document.getElementById('input-conf-web-port'),
    document.getElementById('input-conf-enable-https'),
    document.getElementById('input-conf-worker-processes'),
    document.getElementById('input-conf-worker-connections')
  ];
  backendInput.disabled = !backendToggle.checked;
  frontendInput.disabled = !frontendToggle.checked;
  const isNho = getProductVariant() === 'nho';
  if (helpToggle) helpToggle.disabled = isNho || !frontendToggle.checked;
  helpDocsInput.disabled = isNho || !frontendToggle.checked || (helpToggle && !helpToggle.checked);
  confInputs.forEach(input => { input.disabled = isNho || !frontendToggle.checked; });
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
  const helpToggle = document.getElementById('toggle-help');
  if (helpToggle) helpToggle.addEventListener('change', syncIfEditable);
  syncBuildTargetInputs();
})();

function getProductVariant() {
  const checked = document.querySelector('input[name="product_variant"]:checked');
  return checked ? checked.value : 'standard';
}

function applyVariantVisibility() {
  const isNho = getProductVariant() === 'nho';
  document.querySelectorAll('.standard-only').forEach(el => { el.hidden = isNho; });
  syncBuildTargetInputs();
}

document.querySelectorAll('input[name="product_variant"]').forEach(el => {
  el.addEventListener('change', () => {
    applyVariantVisibility();
    loadBranchLists();
  });
});

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
    const variant = encodeURIComponent(getProductVariant());
    const [be, fe] = await Promise.all([
      fetch(`/api/backend-branches?product_variant=${variant}`).then(r => r.json()),
      fetch(`/api/frontend-branches?product_variant=${variant}`).then(r => r.json())
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
  const builds = embeddedMode && embeddedBuildId ? data.builds.filter(build => build.id === embeddedBuildId) : data.builds;
  if (!builds.length) {
    list.innerHTML = `<div class="empty-state small">${t('noBuilds')}</div>`;
    return;
  }
  builds.forEach(build => {
    const item = document.createElement('button');
    item.className = 'build-item ' + build.status;
    item.innerHTML = `
      <span>
        <strong>${build.request.backend_branch}</strong>
        <small>${build.request.frontend_release_branch || build.request.frontend_workspace_branch || ''} · ${build.id}</small>
      </span>
      <em>${t('status.' + build.status) || build.status}</em>
    `;
    item.onclick = () => {
      if (!embeddedMode) selectBuild(build.id);
    };
    list.appendChild(item);
  });
}

function selectBuild(id) {
  currentBuild = id;
  logOffset = 0;
  logLines = [];
  document.getElementById('log').textContent = '';
  if (timer) clearInterval(timer);
  refreshCurrent();
  timer = setInterval(refreshCurrent, 2000);
}

function appendLogText(text) {
  if (!text) return;
  const normalized = translateLogText(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const incoming = normalized.split('\n');
  if (incoming.length && incoming[incoming.length - 1] === '') incoming.pop();
  logLines.push(...incoming);
  if (logLines.length > MAX_LOG_LINES) {
    logLines = logLines.slice(logLines.length - MAX_LOG_LINES);
  }
}

function renderLog() {
  const pre = document.getElementById('log');
  const shouldStickToBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
  pre.textContent = logLines.join('\n');
  if (shouldStickToBottom) pre.scrollTop = pre.scrollHeight;
}

async function refreshCurrent() {
  if (!embeddedMode) await loadBuilds();
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
    appendLogText(logData.text);
    renderLog();
  }
  if (terminalStatuses.includes(build.status) && timer) {
    clearInterval(timer);
    timer = null;
  }
}

function renderDetail(build) {
  const box = document.getElementById('build-detail');
  const artifactLinks = (build.artifacts || (build.artifact ? [build.artifact] : [])).map(item => (
    `<a class="artifact-link" href="/api/builds/${build.id}/artifact/${item.name}">${t('download')} ${item.name}</a>`
  )).join('');
  box.innerHTML = `
    <div class="summary-panel">
      <div>
        <div class="muted">${t('buildId')}</div>
        <strong>${build.id}</strong>
      </div>
      <div>
        <div class="muted">${t('backendBranch')}</div>
        <strong>${build.request.backend_branch}</strong>
      </div>
      <div>
        <div class="muted">${t('frontendBranch')}</div>
        <strong>${build.request.frontend_release_branch || build.request.frontend_workspace_branch || ''}</strong>
      </div>
      <div>
        <div class="muted">${t('workspaceBranch')}</div>
        <strong>${build.request.frontend_workspace_branch || ''}</strong>
      </div>
      <div>
        <div class="muted">${t('helpSvnRevision')}</div>
        <strong>${build.request.help_docs_svn_revision || 'HEAD'}</strong>
      </div>
      <div>
        <div class="muted">${t('customerHost')}</div>
        <strong>${build.request.conf_server_host || ''}</strong>
      </div>
      <div>
        <div class="muted">${t('webPort')}</div>
        <strong>${build.request.conf_web_port || ''}</strong>
      </div>
      <div>
        <div class="muted">${t('httpsMode')}</div>
        <strong>${build.request.conf_enable_https ? '443 / server.crt / server.key' : '-'}</strong>
      </div>
      <div>
        <div class="muted">${t('worker')}</div>
        <strong>${build.request.conf_worker_processes || ''}/${build.request.conf_worker_connections || ''}</strong>
      </div>
      <div>
        <div class="muted">${t('executor')}</div>
        <strong>${build.executor}</strong>
      </div>
      <span class="pill ${build.status}">${t('status.' + build.status) || build.status}</span>
      ${artifactLinks}
    </div>
    <ol class="steps">
      ${build.steps.map((step, index) => `
        <li class="${step.status}">
          <span class="step-index">${index + 1}</span>
          <span class="step-main">
            <strong>${t('steps.' + step.id) || step.label}</strong>
            <small>${step.message || statusLabel[step.status] || step.status}</small>
          </span>
          <em>${t('status.' + step.status) || step.status}</em>
        </li>
      `).join('')}
    </ol>
  `;
}

applyI18n();
applyVariantVisibility();
loadBranchLists();
applyEmbeddedMode();
if (!embeddedMode) {
  loadBuilds();
  setInterval(loadBuilds, 5000);
}
"""


STYLE_CSS = """
:root {
  --bg: #ffffff;
  --panel: #ffffff;
  --panel-strong: #ffffff;
  --line: #e5e5e5;
  --line-strong: #d4d4d4;
  --text: #111111;
  --muted: #6f6f6f;
  --blue: #111111;
  --blue-soft: #f5f5f5;
  --green: #067647;
  --green-soft: #f4fbf6;
  --red: #b42318;
  --red-soft: #fff7f6;
  --amber: #b54708;
  --amber-soft: #fffaf0;
  --shadow: 0 1px 2px rgba(0, 0, 0, .03);
  --focus: rgba(17, 17, 17, .12);
}
[hidden], .standard-only[hidden] { display: none !important; }
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
body.embedded .hero,
body.embedded .form-card {
  display: none;
}
body.embedded main {
  max-width: none;
  padding: 14px;
}
body.embedded .grid {
  grid-template-columns: minmax(0, 1fr);
}
body.embedded .history-card {
  display: none;
}
body.embedded #stop-button {
  display: none !important;
}
main { max-width: 1220px; margin: 0 auto; padding: 28px 26px 42px; }
h1, h2 { margin: 0; letter-spacing: 0; }
h1 { font-size: clamp(34px, 5vw, 48px); line-height: 1.05; font-weight: 760; }
h2 { font-size: 19px; font-weight: 720; }
.muted { color: var(--muted); font-size: 13px; }
.hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 24px;
  margin-bottom: 24px;
  padding: 18px 0 28px;
  border-bottom: 1px solid var(--line);
}
.hero p { max-width: 700px; margin: 14px 0 0; color: var(--muted); font-size: 16px; line-height: 1.7; }
.eyebrow {
  display: inline-flex;
  margin-bottom: 14px;
  padding: 0;
  border: 0;
  border-radius: 0;
  color: var(--muted);
  background: transparent;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.hero-panel {
  min-width: 245px;
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.language-box {
  min-width: 150px;
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.language-box label { color: var(--muted); font-size: 12px; font-weight: 800; }
.language-box select {
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0 10px;
  background: #fff;
}
.hero-panel small { display: block; margin-top: 4px; color: var(--muted); }
.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: var(--green);
  box-shadow: 0 0 0 5px rgba(6, 118, 71, .10);
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-bottom: 16px;
  box-shadow: var(--shadow);
}
.form-card { padding: 18px; }
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
.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid.four { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.subsection-title { margin: 18px 0 10px; font-weight: 760; color: #111; }
.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.field-block > label:first-child {
  margin: 0;
}
label { display: block; color: #262626; font-size: 13px; font-weight: 760; margin: 0 0 16px; }
input, textarea, select {
  width: 100%;
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  min-height: 40px;
  padding: 9px 11px;
  color: var(--text);
  background: #fff;
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
  background-color: #fff;
}
input:focus, textarea:focus, select:focus {
  border-color: #111;
  box-shadow: 0 0 0 3px var(--focus);
  background: #fff;
}
textarea { resize: vertical; line-height: 1.55; }
details.sync-hint {
  margin: 14px 0 4px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fafafa;
}
details.sync-hint summary {
  cursor: pointer;
  font-weight: 800;
  font-size: 13px;
  color: #262626;
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
  border-radius: 8px;
  background: #fafafa;
}
.toggle-option input {
  width: auto;
  margin: 0;
}
.inline-toggle {
  display: flex;
  align-items: center;
  gap: 9px;
  align-self: end;
  min-height: 45px;
  margin: 0;
  padding: 0 13px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fafafa;
}
.inline-toggle input {
  width: auto;
  margin: 0;
}
.field-block input:disabled {
  color: #8a8a8a;
  background: #f5f5f5;
  cursor: not-allowed;
}
.submit-row { display: flex; align-items: flex-end; justify-content: flex-end; padding-bottom: 16px; }
button {
  border: 1px solid #111;
  border-radius: 8px;
  padding: 10px 15px;
  background: #111;
  color: white;
  cursor: pointer;
  font-weight: 760;
  box-shadow: none;
  transition: background .14s ease, border-color .14s ease, box-shadow .14s ease, color .14s ease;
}
button:hover { background: #000; box-shadow: 0 0 0 3px var(--focus); }
button:disabled {
  cursor: not-allowed;
  opacity: .65;
}
button.danger {
  color: var(--red);
  background: #fff;
  border-color: #f0b8b2;
  box-shadow: none;
}
button.danger:hover {
  background: #fff7f6;
  box-shadow: 0 0 0 3px rgba(180, 35, 24, .10);
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
  border-radius: 8px;
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
.build-item.success { background: var(--green-soft); border-color: #b7e3c7; }
.build-item.failed { background: var(--red-soft); border-color: #f0b8b2; }
.build-item.cancelled { background: #fafafa; border-color: var(--line-strong); }
.build-item.running, .build-item.queued { background: var(--blue-soft); border-color: #111; }
.summary-panel {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  align-items: center;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-strong);
}
.summary-panel strong { display: block; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pill {
  justify-self: start;
  border-radius: 999px;
  padding: 7px 11px;
  color: #525252;
  background: #f5f5f5;
  font-size: 12px;
  font-weight: 900;
}
.pill.running, .pill.queued { color: #111; background: #ededed; }
.pill.success { color: var(--green); background: #e8f7ed; }
.pill.failed { color: var(--red); background: #fff1f0; }
.pill.cancelled { color: #525252; background: #ededed; }
.artifact-link {
  color: #111;
  font-weight: 900;
  text-decoration: underline;
  text-underline-offset: 3px;
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
  border-radius: 8px;
  background: var(--panel-strong);
}
.step-index {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #f5f5f5;
  color: #737373;
  font-weight: 900;
}
.step-main strong { display: block; }
.step-main small { display: block; margin-top: 4px; color: var(--muted); }
.steps li.running { border-color: #111; background: var(--blue-soft); }
.steps li.running .step-index { color: #fff; background: #111; }
.steps li.success { border-color: #b7e3c7; background: var(--green-soft); }
.steps li.success .step-index { color: var(--green); background: #e8f7ed; }
.steps li.failed { border-color: #f0b8b2; background: var(--red-soft); }
.steps li.failed .step-index { color: var(--red); background: #fff1f0; }
.steps li.cancelled { border-color: var(--line-strong); background: #fafafa; }
.steps li.cancelled .step-index { color: #525252; background: #ededed; }
.steps li.skipped { border-color: #efd29b; background: var(--amber-soft); }
.steps li.skipped .step-index { color: var(--amber); background: #fff2d5; }
.empty-state {
  padding: 34px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  color: var(--muted);
  text-align: center;
  background: #fff;
}
.empty-state.small { padding: 20px; }
pre {
  height: 430px;
  overflow: auto;
  margin: 0;
  background: #111;
  color: #f5f5f5;
  border: 1px solid #262626;
  border-radius: 8px;
  padding: 18px;
  white-space: pre-wrap;
  font: 13px/1.65 "SFMono-Regular", Consolas, "Liberation Mono", monospace;
  box-shadow: none;
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
    mark_unfinished_builds_failed()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"build-console listening on http://{HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
