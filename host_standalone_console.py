#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hv_vm_tools import hyperv_host
from hv_vm_tools.config import Settings
from standalone_packager import (
    BuildVersion,
    ProductSqlConfig,
    StandaloneConfig,
    build_nho_common_package,
    build_product_package,
    configured_data_sync_branch,
    configured_data_sync_dir,
    configured_data_sync_git_url,
    configured_data_sync_subdir,
    configured_output_dir,
    configured_sql_template_dir,
    configured_sql_svn_url,
    configured_template_zip,
    default_organisation_dstart,
    download_remote_artifact,
    download_remote_file,
    remote_json,
)


APP_VERSION = "0.3.28"
HOST = os.environ.get("HOST_STANDALONE_CONSOLE_HOST", "0.0.0.0")
PORT = int(os.environ.get("HOST_STANDALONE_CONSOLE_PORT", "8091"))
REMOTE_BUILD_CONSOLE_URL = os.environ.get("REMOTE_BUILD_CONSOLE_URL", "http://192.168.250.50:8090")
DATA_DIR = Path(os.environ.get("HOST_STANDALONE_DATA_DIR", "dist/standalone-builds"))
CONFIG_HISTORY_DIR = DATA_DIR / "config-history"
TOKEN_FILE = Path(os.environ.get("HOST_STANDALONE_TOKEN_FILE", DATA_DIR / "management.token"))
TERMINAL_LABELS = {
    "ja-JP": "ビルド端末",
    "zh-CN": "构建终端",
    "en-US": "build terminal",
}

HOST_PROGRESS_STEPS = [
    "terminal_check",
    "terminal_dispatch",
    "terminal_build",
    "download_artifacts",
    "sql_assets",
    "data_sync_assets",
    "account_sql",
    "help_sql",
    "standalone_zip",
    "complete",
]

PACKAGING_STEP_MAP = {
    "sql_svn_download": "sql_assets",
    "sql_template_copy": "sql_assets",
    "data_sync_git_sync": "data_sync_assets",
    "data_sync_copy": "data_sync_assets",
    "account_sql_patch": "account_sql",
    "help_sql_replace": "help_sql",
    "standalone_zip_rebuild": "standalone_zip",
}


def make_progress() -> list[dict[str, Any]]:
    return [{"id": step_id, "status": "pending", "started_at": None, "finished_at": None} for step_id in HOST_PROGRESS_STEPS]

JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.RLock()
CANCELLED: set[str] = set()


class JobCancelled(RuntimeError):
    pass


def load_management_token() -> str:
    env_token = os.environ.get("HOST_STANDALONE_MANAGEMENT_TOKEN")
    if env_token:
        return env_token
    try:
        if TOKEN_FILE.is_file():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if token:
                return token
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(32)
        TOKEN_FILE.write_text(token, encoding="utf-8")
        return token
    except OSError:
        return secrets.token_urlsafe(32)


MANAGEMENT_TOKEN = load_management_token()


def now() -> int:
    return int(time.time())


def new_job_id() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def job_dir(job_id: str) -> Path:
    return DATA_DIR / job_id


def job_metadata_path(job_id: str) -> Path:
    return job_dir(job_id) / "metadata.json"


def job_log_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.log"


def config_history_path(config_id: str) -> Path:
    return CONFIG_HISTORY_DIR / f"{config_id}.json"


def read_job(job_id: str) -> dict[str, Any]:
    with LOCK:
        if job_id in JOBS:
            return dict(JOBS[job_id])
    path = job_metadata_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def write_job(job: dict[str, Any]) -> None:
    path = job_metadata_path(str(job["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    last_error: OSError | None = None
    for _ in range(8):
        try:
            tmp.replace(path)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.08)
    try:
        tmp.unlink()
    except OSError:
        pass
    if last_error:
        raise last_error


def config_history_label(request: dict[str, Any], job_id: str) -> str:
    organisation = str(request.get("organisation_name") or request.get("material_number") or "未設定").strip() or "未設定"
    return f"{organisation} / {job_id}"


def save_config_history(job: dict[str, Any]) -> dict[str, Any]:
    request = dict(job.get("request") or {})
    config_id = str(job["id"])
    item = {
        "id": config_id,
        "job_id": config_id,
        "label": config_history_label(request, config_id),
        "product_variant": str(request.get("product_variant") or "standard"),
        "organisation_name": str(request.get("organisation_name") or ""),
        "material_number": str(request.get("material_number") or ""),
        "created_at": int(job.get("created_at") or now()),
        "updated_at": now(),
        "request": request,
    }
    CONFIG_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    config_history_path(config_id).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return item


def list_config_histories() -> list[dict[str, Any]]:
    CONFIG_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in CONFIG_HISTORY_DIR.glob("*.json"):
        try:
            items.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    items.sort(key=lambda item: (int(item.get("created_at") or 0), str(item.get("id") or "")), reverse=True)
    return items


def delete_config_history(config_id: str) -> dict[str, Any]:
    path = config_history_path(config_id)
    if not path.is_file():
        return {"ok": False, "error": "not_found"}
    path.unlink(missing_ok=True)
    return {"ok": True, "id": config_id}


def list_jobs() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, dict[str, Any]] = {}
    for path in DATA_DIR.iterdir():
        mp = path / "metadata.json"
        if not mp.is_file():
            continue
        try:
            job = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        jobs[str(job["id"])] = job
    with LOCK:
        for job_id, job in JOBS.items():
            jobs[job_id] = dict(job)
    return sorted(jobs.values(), key=lambda item: item.get("created_at", 0), reverse=True)


def remote_base_host() -> str:
    return urllib.parse.urlparse(REMOTE_BUILD_CONSOLE_URL).hostname or ""


def redact_build_terminal(text: str, lang: str = "ja-JP") -> str:
    label = TERMINAL_LABELS.get(lang, TERMINAL_LABELS["ja-JP"])
    redacted = str(text)
    host = remote_base_host()
    if host:
        redacted = redacted.replace(host, label)
    try:
        vm_host = Settings.from_env().vm_host
    except Exception:
        vm_host = ""
    if vm_host:
        redacted = redacted.replace(vm_host, label)
    return redacted


def validate_job_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    product_variant = str(payload.get("product_variant") or "standard").strip().lower()
    if product_variant not in {"standard", "nho"}:
        return payload, "invalid product_variant"
    payload["product_variant"] = product_variant

    if not str(payload.get("material_number") or "").strip():
        return payload, "missing material_number"

    build_backend = bool(str(payload.get("backend_branch") or "").strip())
    build_frontend = bool(str(payload.get("frontend_release_branch") or "").strip())
    if not build_backend and not build_frontend:
        return payload, "missing build target"

    required = ["conf_server_host"] if product_variant == "standard" and build_frontend else []
    if product_variant == "standard" and build_backend and build_frontend:
        required.extend(["postgresql_host", "organisation_name"])
    for key in required:
        if not str(payload.get(key) or "").strip():
            return payload, f"missing {key}"
    return payload, None


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload, error = validate_job_payload(payload)
    if error:
        raise ValueError(error)
    job_id = new_job_id()
    with LOCK:
        while job_id in JOBS or job_metadata_path(job_id).exists():
            job_id = f"{new_job_id()}-{len(JOBS) + 1}"
        job = {
            "id": job_id,
            "status": "queued",
            "created_at": now(),
            "updated_at": now(),
            "remote_build_id": None,
            "remote_log_offset": 0,
            "request": payload,
            "log": [],
            "outputs": {},
            "progress": make_progress(),
        }
        job_dir(job_id).mkdir(parents=True, exist_ok=True)
        job_log_path(job_id).write_text("", encoding="utf-8")
        JOBS[job_id] = job
        write_job(job)
        save_config_history(job)
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return public_job(job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = dict(job)
    result["request"] = dict(job.get("request") or {})
    return result


def append_log(job_id: str, message: str) -> None:
    append_log_lines(job_id, [message])


def append_log_lines(job_id: str, messages: list[str]) -> None:
    if not messages:
        return
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        lang = str((job.get("request") or {}).get("ui_language") or "ja-JP")
        stamp = time.strftime("%H:%M:%S")
        lines = [f"{stamp} {redact_build_terminal(message, lang)}" for message in messages]
        job.setdefault("log", []).extend(lines)
        job["log"] = job["log"][-200:]
        job["updated_at"] = now()
        JOBS[job_id] = job
        write_job(job)
    with job_log_path(job_id).open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def update_job(job_id: str, **updates: Any) -> None:
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        job.update(updates)
        job["updated_at"] = now()
        JOBS[job_id] = job
        write_job(job)


def update_progress(job_id: str, step_id: str, status: str) -> None:
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        progress = list(job.get("progress") or make_progress())
        known = {str(item.get("id")) for item in progress}
        if step_id not in known:
            progress.append({"id": step_id, "status": "pending", "started_at": None, "finished_at": None})
        for step in progress:
            if step.get("id") != step_id:
                continue
            if status == "running" and not step.get("started_at"):
                step["started_at"] = now()
            if status in ("success", "failed", "cancelled", "skipped"):
                if not step.get("started_at"):
                    step["started_at"] = now()
                step["finished_at"] = now()
            step["status"] = status
        job["progress"] = progress
        job["updated_at"] = now()
        JOBS[job_id] = job
        write_job(job)


def finish_progress_before(job_id: str, step_id: str) -> None:
    progress = (JOBS.get(job_id) or read_job(job_id)).get("progress") or make_progress()
    for step in progress:
        if step.get("id") == step_id:
            break
        if step.get("status") in ("pending", "running"):
            update_progress(job_id, str(step.get("id")), "success")


def fail_active_progress(job_id: str, status: str = "failed") -> None:
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        progress = list(job.get("progress") or make_progress())
        active = next((step for step in progress if step.get("status") == "running"), None)
    if active:
        update_progress(job_id, str(active.get("id")), status)


def check_cancelled(job_id: str) -> None:
    with LOCK:
        cancelled = job_id in CANCELLED
    if cancelled:
        raise JobCancelled("cancelled")


def fetch_remote_log(job_id: str, remote_id: str) -> None:
    with LOCK:
        offset = int(JOBS[job_id].get("remote_log_offset") or 0)
    try:
        data = remote_json(REMOTE_BUILD_CONSOLE_URL, f"/api/builds/{remote_id}/log?offset={offset}")
    except Exception as exc:
        append_log(job_id, f"remote_log_unavailable: {exc}")
        return
    text = str(data.get("text") or data.get("log") or "")
    if text:
        append_log_lines(job_id, [line for line in text.splitlines() if line.strip()])
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        job["remote_log_offset"] = int(data.get("next_offset") or data.get("offset") or offset + len(text))
        JOBS[job_id] = job
        write_job(job)


def filter_display_log(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "remote_build_status:" not in line)


def remote_post(path: str) -> dict[str, Any]:
    url = urllib.parse.urljoin(REMOTE_BUILD_CONSOLE_URL.rstrip("/") + "/", path.lstrip("/"))
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def remote_delete(path: str) -> dict[str, Any]:
    url = urllib.parse.urljoin(REMOTE_BUILD_CONSOLE_URL.rstrip("/") + "/", path.lstrip("/"))
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="DELETE")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def remove_path_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    if resolved == resolved_root or resolved_root not in resolved.parents:
        return False
    if resolved.exists():
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=True)
        else:
            resolved.unlink(missing_ok=True)
    return True


def is_remote_console_reachable() -> bool:
    try:
        with urllib.request.urlopen(urllib.parse.urljoin(REMOTE_BUILD_CONSOLE_URL.rstrip("/") + "/", "api/builds"), timeout=5):
            return True
    except Exception:
        return False


def build_terminal_status() -> dict[str, Any]:
    settings = Settings.from_env()
    vm_name = settings.hyperv_vm_name
    reachable = is_remote_console_reachable()
    if reachable:
        return {"status": "running", "configured": bool(vm_name), "reachable": True}
    if not vm_name:
        return {"status": "unconfigured", "configured": False, "reachable": False}

    row, error = hyperv_host.vm_state(vm_name)
    if error:
        lowered = error.lower()
        status = "permission_denied" if "access" in lowered or "denied" in lowered else "unknown"
        return {"status": status, "configured": True, "reachable": False, "message": redact_build_terminal(error)}
    state = str(row.get("State") or row.get("state") or "").lower()
    if state in ("off", "stopped", "3"):
        return {"status": "stopped", "configured": True, "reachable": False}
    if state in ("running", "2"):
        return {"status": "unreachable", "configured": True, "reachable": False}
    if "off" in state or "stopped" in state:
        return {"status": "stopped", "configured": True, "reachable": False}
    if "running" in state:
        return {"status": "unreachable", "configured": True, "reachable": False}
    return {"status": "unknown", "configured": True, "reachable": False}


def build_terminal_action(action: str) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        return {"status": "invalid_action", "ok": False}
    settings = Settings.from_env()
    vm_name = settings.hyperv_vm_name
    if not vm_name:
        return {"status": "unconfigured", "ok": False}
    row, error = hyperv_host.vm_action(vm_name, action)
    if error:
        lowered = error.lower()
        status = "permission_denied" if "access" in lowered or "denied" in lowered else "unknown"
        return {"status": status, "ok": False, "message": redact_build_terminal(error)}
    return {"status": "requested", "ok": True, "result": row}


def cancel_job(job_id: str) -> dict[str, Any]:
    with LOCK:
        try:
            job = JOBS.get(job_id) or read_job(job_id)
        except FileNotFoundError:
            return {"ok": False, "error": "not_found"}
        JOBS[job_id] = job
        CANCELLED.add(job_id)
        remote_id = job.get("remote_build_id")
        status = job.get("status")
    if remote_id and status not in ("success", "failed", "cancelled"):
        try:
            remote_post(f"/api/builds/{remote_id}/cancel")
        except Exception as exc:
            append_log(job_id, f"cancel_remote_failed: {exc}")
    update_job(job_id, status="cancelled")
    append_log(job_id, "cancelled")
    return {"ok": True}


def delete_job(job_id: str) -> dict[str, Any]:
    try:
        job = read_job(job_id)
    except FileNotFoundError:
        return {"ok": False, "error": "not_found"}
    if job.get("status") in ("queued", "running"):
        return {"ok": False, "error": "job_running"}

    remote_id = job.get("remote_build_id")
    if remote_id:
        try:
            remote_delete(f"/api/builds/{remote_id}")
        except urllib.error.HTTPError as exc:
            if exc.code not in (HTTPStatus.NOT_FOUND,):
                return {"ok": False, "error": f"remote_delete_failed:{exc.code}"}
        except Exception as exc:
            return {"ok": False, "error": f"remote_delete_failed:{redact_build_terminal(str(exc))}"}

    output_root = configured_output_dir()
    outputs = job.get("outputs") or {}
    product_dir = str(outputs.get("product_dir") or "")
    if product_dir:
        product_path = Path(product_dir)
        candidate = product_path.parent if product_path.name == "製品" else product_path
        remove_path_inside(candidate, output_root)
    remove_path_inside(output_root / job_id, output_root)
    if remote_id:
        remove_path_inside(output_root / str(remote_id), output_root)

    with LOCK:
        JOBS.pop(job_id, None)
        CANCELLED.discard(job_id)
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    return {"ok": True, "id": job_id, "remote_build_id": remote_id}


def run_job(job_id: str) -> None:
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        req = dict(job["request"])
        remote_id = job.get("remote_build_id")
    product_variant = str(req.get("product_variant") or "standard").lower()
    material_number = str(req.get("material_number") or "").strip()
    build_backend = bool(str(req.get("backend_branch") or "").strip())
    build_frontend = bool(str(req.get("frontend_release_branch") or "").strip())
    work_dir = job_dir(job_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id, status="running")
        update_progress(job_id, "terminal_check", "running")
        terminal = build_terminal_status()
        if terminal["status"] != "running":
            raise RuntimeError("build_terminal_unavailable")
        update_progress(job_id, "terminal_check", "success")

        if remote_id:
            append_log(job_id, f"resume_remote_build: {remote_id}")
            update_progress(job_id, "terminal_dispatch", "success")
            update_progress(job_id, "terminal_build", "running")
        else:
            update_progress(job_id, "terminal_dispatch", "running")
            append_log(job_id, "build_terminal_dispatch")
            remote_payload = {
                "product_variant": product_variant,
                "build_backend": build_backend,
                "build_frontend": build_frontend,
                "backend_branch": req.get("backend_branch") or "",
                "frontend_release_branch": req.get("frontend_release_branch") or "",
                "help_docs_branch": req.get("help_docs_branch") or "release_ci",
                "conf_server_host": req.get("conf_server_host") or "",
                "conf_web_port": int(req.get("conf_web_port") or 80),
                "conf_enable_https": bool(req.get("conf_enable_https")),
                "conf_worker_processes": int(req.get("conf_worker_processes") or 1),
                "conf_worker_connections": int(req.get("conf_worker_connections") or 1024),
                "note": req.get("note") or f"standalone package {job_id}",
            }
            check_cancelled(job_id)
            remote_build = remote_json(REMOTE_BUILD_CONSOLE_URL, "/api/builds", remote_payload)
            remote_id = remote_build["id"]
            update_job(job_id, remote_build_id=remote_id)
            update_progress(job_id, "terminal_dispatch", "success")
            update_progress(job_id, "terminal_build", "running")
            append_log(job_id, f"remote_build_id: {remote_id}")

        while True:
            check_cancelled(job_id)
            fetch_remote_log(job_id, remote_id)
            status = remote_json(REMOTE_BUILD_CONSOLE_URL, f"/api/builds/{remote_id}")
            if status["status"] in ("success", "failed", "cancelled"):
                fetch_remote_log(job_id, remote_id)
                if status["status"] != "success":
                    raise RuntimeError(f"remote_build_not_success: {status['status']}")
                break
            update_job(job_id, remote_build_status=status["status"], heartbeat_at=now())
            time.sleep(5)
        update_progress(job_id, "terminal_build", "success")

        check_cancelled(job_id)
        update_progress(job_id, "download_artifacts", "running")
        append_log(job_id, "download_artifacts")
        package_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "package.zip", work_dir / "package.zip") if build_backend else None
        web_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "web.zip", work_dir / "web.zip") if build_frontend else None
        partial_outputs = {
            "package_zip": str(package_zip) if package_zip else "",
            "web_zip": str(web_zip) if web_zip else "",
        }
        update_progress(job_id, "download_artifacts", "success")
        if product_variant == "nho":
            check_cancelled(job_id)
            update_progress(job_id, "sql_assets", "running")
            append_log(job_id, "sql_svn_download")
            database_assets_zip = download_remote_file(
                REMOTE_BUILD_CONSOLE_URL,
                f"/api/nho-material-database-assets?material_number={urllib.parse.quote(material_number)}",
                work_dir / "nho_database_assets.zip",
            )
            partial_outputs["database_assets_zip"] = str(database_assets_zip)
            update_progress(job_id, "sql_assets", "success")
            for step_id in ("data_sync_assets", "account_sql", "help_sql"):
                update_progress(job_id, step_id, "skipped")
            update_progress(job_id, "standalone_zip", "running")
            def nho_package_log(message: str) -> None:
                append_log(job_id, message)

            outputs = build_nho_common_package(
                output_root=configured_output_dir(),
                build_id=job_id,
                package_zip=package_zip,
                web_zip=web_zip,
                database_assets_zip=database_assets_zip,
                version=BuildVersion(
                    build_id=job_id,
                    material_number=material_number,
                    backend_branch=req.get("backend_branch") or "-",
                    frontend_branch=req.get("frontend_release_branch") or "-",
                ),
                logger=nho_package_log,
            )
            update_progress(job_id, "standalone_zip", "success")
            update_progress(job_id, "complete", "success")
            update_job(job_id, status="success", outputs=outputs)
            append_log(job_id, "nho_common_package_done")
            return

        if not (build_backend and build_frontend):
            for step_id in ("sql_assets", "data_sync_assets", "account_sql", "help_sql", "standalone_zip"):
                update_progress(job_id, step_id, "skipped")
            update_progress(job_id, "complete", "success")
            update_job(job_id, status="success", outputs=partial_outputs)
            append_log(job_id, "selected_artifacts_done")
            return

        check_cancelled(job_id)
        append_log(job_id, "standalone_packaging")
        def package_log(message: str) -> None:
            step_id = PACKAGING_STEP_MAP.get(message)
            if step_id:
                finish_progress_before(job_id, step_id)
                update_progress(job_id, step_id, "running")
            append_log(job_id, message)

        outputs = build_product_package(
            template_zip=configured_template_zip(),
            sql_template_dir=configured_sql_template_dir(),
            output_root=configured_output_dir(),
            package_zip=package_zip,
            web_zip=web_zip,
            version=BuildVersion(
                build_id=remote_id,
                material_number=material_number,
                backend_branch=req.get("backend_branch") or "-",
                frontend_branch=req.get("frontend_release_branch") or "-",
            ),
            config=StandaloneConfig(
                postgresql_host=req["postgresql_host"],
                postgresql_port=int(req.get("postgresql_port") or 5432),
                postgresql_user=req.get("postgresql_user") or "postgres",
                postgresql_password=req.get("postgresql_password") or "password",
                ohr_host_address=req.get("ohr_host_address") or req["conf_server_host"],
                ohr_service_port=int(req.get("ohr_service_port") or 3198),
            ),
            sql_config=ProductSqlConfig(
                organisation_name=req["organisation_name"],
                organisation_dstart=req.get("organisation_dstart") or default_organisation_dstart(),
            ),
            sql_svn_url=configured_sql_svn_url(),
            data_sync_git_url=configured_data_sync_git_url(),
            data_sync_branch=configured_data_sync_branch(),
            data_sync_dir=configured_data_sync_dir(),
            data_sync_subdir=configured_data_sync_subdir(),
            logger=package_log,
        )
        outputs.update(partial_outputs)
        for step_id in ("sql_assets", "data_sync_assets", "account_sql", "help_sql", "standalone_zip"):
            current = next((step for step in (read_job(job_id).get("progress") or []) if step.get("id") == step_id), {})
            if current.get("status") in ("pending", "running"):
                update_progress(job_id, step_id, "success")
        update_progress(job_id, "complete", "success")
        update_job(job_id, status="success", outputs=outputs)
        append_log(job_id, "standalone_package_done")
    except JobCancelled:
        fail_active_progress(job_id, "cancelled")
        update_job(job_id, status="cancelled")
        append_log(job_id, "cancelled")
    except Exception as exc:
        fail_active_progress(job_id, "failed")
        update_job(job_id, status="failed", error=redact_build_terminal(str(exc)))
        append_log(job_id, f"failed: {exc}")


def resume_unfinished_jobs() -> None:
    for job in list_jobs():
        if job.get("status") not in ("queued", "running"):
            continue
        if not job.get("remote_build_id"):
            update_job(str(job["id"]), status="failed", error="host_console_restarted_before_build_terminal_dispatch")
            append_log(str(job["id"]), "failed: host_console_restarted_before_build_terminal_dispatch")
            continue
        job_id = str(job["id"])
        with LOCK:
            JOBS[job_id] = job
        thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
        thread.start()


INDEX_HTML = """<!doctype html>
<html lang="ja-JP">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>庶務事務システム构造器</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">SHOMU JIMU SYSTEM BUILDER</p>
        <h1><span data-i18n="title">庶務事務システム构造器</span><span class="app-version">v__APP_VERSION__</span></h1>
        <p class="subcopy" data-i18n="subtitle">構築成果物と固定資材を組み合わせ、正式な製品交付パッケージを生成します。</p>
      </div>
      <div class="hero-actions">
        <label class="lang-label" for="language" data-i18n="language">表示言語</label>
        <select id="language" aria-label="language">
          <option value="ja-JP">日本語</option>
          <option value="zh-CN">中文</option>
          <option value="en-US">English</option>
        </select>
      </div>
    </header>

    <section class="terminal-panel">
      <div>
        <p class="section-kicker" data-i18n="terminalTitle">ビルド端末</p>
        <h2 id="terminalStatus" data-i18n="terminalUnknown">状態不明</h2>
        <p id="terminalHint" data-i18n="terminalHint">状態を更新してから開始してください。</p>
      </div>
      <div class="terminal-actions">
        <button class="secondary" id="refreshTerminal" type="button" data-i18n="refreshStatus">状態更新</button>
        <button class="secondary" id="startTerminal" type="button" data-i18n="startTerminal">ビルド端末を起動</button>
        <button class="danger-lite" id="stopTerminal" type="button" data-i18n="stopTerminal">ビルド端末を停止</button>
      </div>
    </section>

    <form id="form" class="panel form-panel">
      <div class="panel-heading">
        <div>
          <p class="section-kicker" data-i18n="formKicker">構造設定</p>
          <h2 data-i18n="formTitle">構成パラメータ</h2>
        </div>
        <div class="run-actions">
          <button id="stopJob" class="danger" type="button" disabled data-i18n="stopJob">停止</button>
          <button id="startJob" type="submit" data-i18n="startJob">構造を開始</button>
        </div>
      </div>
      <div class="grid">
        <fieldset class="variant-field">
          <legend data-i18n="productVariant">製品バージョン</legend>
          <label class="radio-pill"><input name="product_variant" type="radio" value="standard" checked><span data-i18n="variantStandard">標準版</span></label>
          <label class="radio-pill"><input name="product_variant" type="radio" value="nho"><span data-i18n="variantNho">NHO版</span></label>
        </fieldset>
        <div class="standard-only standard-tabs" role="tablist" aria-label="standard settings tabs">
          <button class="standard-tab active" type="button" data-standard-tab="prep" data-i18n="tabPreparation">事前準備</button>
          <button class="standard-tab" type="button" data-standard-tab="import" data-i18n="tabImportPlan">導入計画</button>
        </div>
        <label class="required-field material-field"><span data-i18n="materialNumber">資材番号</span><div class="material-combo"><input name="material_number" required data-i18n-placeholder="materialNumberPlaceholder" placeholder="例：20260520"><button id="material-number-toggle" class="material-toggle nho-only" type="button" aria-label="NHO material number candidates" aria-expanded="false">⌄</button><div id="material-number-menu" class="material-menu" hidden></div></div></label>
        <label><span data-i18n="backendBranch">バックエンドブランチ</span><div class="material-combo"><input name="backend_branch" id="backend-branches" autocomplete="off"><button id="backend-branches-toggle" class="material-toggle" type="button" aria-label="backend branch candidates" aria-expanded="false">⌄</button><div id="backend-branches-menu" class="material-menu" hidden></div></div></label>
        <label><span data-i18n="frontendBranch">フロントエンドブランチ</span><div class="material-combo"><input name="frontend_release_branch" id="frontend-branches" autocomplete="off"><button id="frontend-branches-toggle" class="material-toggle" type="button" aria-label="frontend branch candidates" aria-expanded="false">⌄</button><div id="frontend-branches-menu" class="material-menu" hidden></div></div></label>
        <section class="standard-only standard-tab-panel" data-standard-tab-panel="prep">
          <fieldset class="form-section">
            <legend data-i18n="basicBuildInfo">構築パラメータ</legend>
            <label class="standard-only"><span data-i18n="helpBranch">ヘルプブランチ</span><input name="help_docs_branch" value="release_ci"></label>
            <label class="standard-only"><span data-i18n="organisationName">顧客機関名</span><input name="organisation_name" data-i18n-placeholder="organisationNamePlaceholder" placeholder="例：学校法人サンプル"></label>
            <label class="standard-only"><span data-i18n="organisationDstart">機関開始日</span><input name="organisation_dstart" id="organisation-dstart" type="date"></label>
            <label class="standard-only"><span data-i18n="employeeNumberDigits">職員番号桁数</span><input name="employee_number_digits" type="number" min="1" max="20" placeholder="8"></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="apHostInfo">AP 主機情報</legend>
            <label class="standard-only"><span data-i18n="appHostName">AP 主機名</span><input name="ohr_host_address" data-i18n-placeholder="appHostPlaceholder" placeholder="顧客アクセスアドレスを使用"></label>
            <label class="standard-only required-field"><span data-i18n="apHostIp">AP 主機 IP</span><input name="conf_server_host" required placeholder="192.168.70.136"></label>
            <label class="standard-only"><span data-i18n="apCpuCount">AP CPU 数</span><input name="ap_cpu_count" type="number" min="1" placeholder="8"></label>
            <label class="standard-only"><span data-i18n="apMemoryGb">AP メモリ GB</span><input name="ap_memory_gb" type="number" min="1" placeholder="32"></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="dbHostInfo">DB 主機情報</legend>
            <label class="standard-only required-field"><span data-i18n="postgresHost">DB 主機名</span><input name="postgresql_host" required placeholder="192.168.10.209"></label>
            <label class="standard-only"><span data-i18n="postgresUser">DB ユーザー</span><input name="postgresql_user" value="postgres"></label>
            <label class="standard-only"><span data-i18n="postgresPassword">DB パスワード</span><input name="postgresql_password" value="password"></label>
            <label class="standard-only"><span data-i18n="postgresPort">DB ポート</span><input name="postgresql_port" type="number" value="5432"></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="webHostInfo">WEB 主機情報</legend>
            <label class="standard-only"><span data-i18n="webHostName">WEB 主機名</span><input name="web_host_name" data-i18n-placeholder="appHostPlaceholder" placeholder="顧客アクセスアドレスを使用"></label>
            <label class="standard-only"><span data-i18n="webPort">WEB ポート</span><input name="conf_web_port" type="number" value="80" min="1" max="65535"></label>
            <label class="standard-only"><span data-i18n="webCertName">WEB 証明書名</span><input name="web_cert_name" value="Server.pem"></label>
            <label class="standard-only"><span data-i18n="webKeyName">WEB Key 名</span><input name="web_key_name" value="Server.key"></label>
            <label class="check-row standard-only"><input name="conf_enable_https" type="checkbox"><span data-i18n="enableHttps">HTTPS / 443 設定を生成</span></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="mailServiceInfo">メールサービス情報</legend>
            <label class="standard-only"><span data-i18n="mailHostIp">メール主機 IP</span><input name="mail_host_ip"></label>
            <label class="standard-only"><span data-i18n="mailPort">メールポート</span><input name="mail_port" type="number" min="1" max="65535"></label>
            <label class="standard-only"><span data-i18n="mailEncryption">暗号化方式</span><select name="mail_encryption"><option value=""></option><option>none</option><option>SSL</option><option>TLS</option><option>STARTTLS</option></select></label>
            <label class="standard-only"><span data-i18n="mailAuthMethod">認証方式</span><select name="mail_auth_method"><option value=""></option><option>none</option><option>plain</option><option>login</option></select></label>
            <label class="standard-only"><span data-i18n="mailUser">メールユーザー</span><input name="mail_user"></label>
            <label class="standard-only"><span data-i18n="mailPassword">メールパスワード</span><input name="mail_password"></label>
            <label class="standard-only section-wide"><span data-i18n="mailNote">メール備考</span><input name="mail_note"></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="updsServiceInfo">UPDS サービス情報</legend>
            <label class="standard-only"><span data-i18n="updsHostName">UPDS 主機名</span><input name="upds_host_name"></label>
            <label class="standard-only"><span data-i18n="updsUser">UPDS ユーザー</span><input name="upds_user"></label>
            <label class="standard-only"><span data-i18n="updsPassword">UPDS パスワード</span><input name="upds_password"></label>
            <label class="standard-only"><span data-i18n="updsPort">UPDS ポート</span><input name="upds_port" type="number" min="1" max="65535"></label>
            <label class="standard-only"><span data-i18n="updsDbName">UPDS DB 名</span><input name="upds_db_name"></label>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="ekispertInfo">駅すぱあと情報</legend>
            <label class="standard-only section-wide"><span data-i18n="ekispertUrl">駅すぱあと URL</span><input name="ekispert_url" placeholder="https://"></label>
          </fieldset>
        </section>
        <section class="standard-only standard-tab-panel" data-standard-tab-panel="import" hidden>
          <fieldset class="form-section">
            <legend data-i18n="customerSituation">お客様の実績状況収集</legend>
            <div class="option-matrix">
              <label><span data-i18n="facilitySituation">施設状況</span><select name="facility_situation"><option value="single" data-i18n="singleFacility">単施設（一つ給与計算センター）</option><option value="multiple" data-i18n="multipleFacilities">複数施設（複数給与計算センター）</option></select></label>
              <label><span data-i18n="mailUsage">メール利用</span><select name="mail_usage"><option value="use" data-i18n="use">利用</option><option value="none" data-i18n="notUse">利用しない</option></select></label>
              <label><span data-i18n="ekispertServer">駅すぱあとサーバ</span><select name="ekispert_usage"><option value="use" data-i18n="use">利用</option><option value="none" data-i18n="notUse">利用しない</option></select></label>
              <label><span data-i18n="courseLecture">係・講座</span><select name="course_usage"><option value="use" data-i18n="use">利用</option><option value="none" data-i18n="notUse">利用しない</option></select></label>
              <label><span data-i18n="workflowUpds">ワークフロー申請 UPDSへ連携</span><select name="workflow_upds_usage"><option value="use" data-i18n="use">利用</option><option value="none" data-i18n="notUse">利用しない</option></select></label>
              <label><span data-i18n="personalNumber">個人識別番号</span><select name="personal_number_usage"><option value="use" data-i18n="use">利用</option><option value="none" data-i18n="notUse">利用しない</option></select></label>
            </div>
          </fieldset>
          <fieldset class="form-section">
            <legend data-i18n="screenPublishPlan">画面公開計画</legend>
            <div class="tag-tree">
              <details open><summary data-i18n="shomuSystem">庶務事務</summary><label><input type="checkbox" name="publish_shomu_portal" checked><span>トップページ</span></label><label><input type="checkbox" name="publish_shomu_profile"><span>プロフィール</span></label><label><input type="checkbox" name="publish_shomu_payroll"><span>給与明細</span></label><label><input type="checkbox" name="publish_shomu_source_tax"><span>源泉徴収票</span></label><label><input type="checkbox" name="publish_shomu_issue_info"><span>発令情報</span></label><label><input type="checkbox" name="publish_shomu_staff_admin" checked><span>職員管理</span></label><label><input type="checkbox" name="publish_shomu_salary_reservation"><span>電子交付承諾状況</span></label><label><input type="checkbox" name="publish_shomu_payroll_admin"><span>給与明細管理</span></label><label><input type="checkbox" name="publish_shomu_source_tax_admin"><span>源泉徴収票管理</span></label><label><input type="checkbox" name="publish_shomu_issue_admin"><span>発令情報管理</span></label><label><input type="checkbox" name="publish_shomu_initial_login"><span>初期ログイン設定</span></label><label><input type="checkbox" name="publish_shomu_notification" checked><span>通知設定</span></label><label><input type="checkbox" name="publish_shomu_group" checked><span>グループ設定</span></label><label><input type="checkbox" name="publish_shomu_role" checked><span>ロール管理</span></label><label><input type="checkbox" name="publish_shomu_generic_master" checked><span>汎用マスタ</span></label></details>
              <details open><summary data-i18n="yearEndAdjustment">年末調整</summary><label><input type="checkbox" name="publish_nencho_portal" checked><span>トップページ</span></label><label><input type="checkbox" name="publish_nencho_tax"><span>税法扶養申請</span></label><label><input type="checkbox" name="publish_nencho_home"><span>住宅利用申請</span></label><label><input type="checkbox" name="publish_nencho_admin"><span>年末調整管理</span></label><label><input type="checkbox" name="publish_nencho_tax_admin"><span>税法扶養申請管理</span></label><label><input type="checkbox" name="publish_nencho_home_admin"><span>住宅利用申請管理</span></label><label><input type="checkbox" name="publish_nencho_mail_template" checked><span>メールテンプレート設定</span></label><label><input type="checkbox" name="publish_nencho_notification" checked><span>通知設定</span></label><label><input type="checkbox" name="publish_nencho_group" checked><span>グループ設定</span></label><label><input type="checkbox" name="publish_nencho_role" checked><span>ロール管理</span></label><label><input type="checkbox" name="publish_nencho_generic_master" checked><span>汎用マスタ</span></label></details>
              <details open><summary data-i18n="applications">各種申請</summary><label><input type="checkbox" name="publish_apps_portal" checked><span>トップページ</span></label><label><input type="checkbox" name="publish_apps_status" checked><span>申請状況</span></label><label><input type="checkbox" name="publish_apps_agent"><span>代理申請</span></label><label><input type="checkbox" name="publish_apps_license"><span>免許取得届</span></label><label><input type="checkbox" name="publish_apps_address"><span>住所届</span></label><label><input type="checkbox" name="publish_apps_account"><span>給与口座届</span></label><label><input type="checkbox" name="publish_apps_old_name"><span>旧姓使用</span></label><label><input type="checkbox" name="publish_apps_name_change"><span>氏名変更届</span></label><label><input type="checkbox" name="publish_apps_mail_template" checked><span>メールテンプレート設定</span></label><label><input type="checkbox" name="publish_apps_workflow" checked><span>ワークフロー設定</span></label><label><input type="checkbox" name="publish_apps_comment_limit" checked><span>コメント文字列の上限設定</span></label><label><input type="checkbox" name="publish_apps_notification" checked><span>通知設定</span></label><label><input type="checkbox" name="publish_apps_group" checked><span>グループ設定</span></label><label><input type="checkbox" name="publish_apps_role" checked><span>ロール管理</span></label><label><input type="checkbox" name="publish_apps_generic_master" checked><span>汎用マスタ</span></label></details>
              <details open><summary data-i18n="allowances">諸手当</summary><label><input type="checkbox" name="publish_allowance_portal" checked><span>トップページ</span></label><label><input type="checkbox" name="publish_allowance_status" checked><span>申請状況</span></label><label><input type="checkbox" name="publish_allowance_agent"><span>代理状況</span></label><label><input type="checkbox" name="publish_allowance_current"><span>現状確認</span></label><label><input type="checkbox" name="publish_allowance_family"><span>扶養手当</span></label><label><input type="checkbox" name="publish_allowance_commute"><span>通勤手当</span></label><label><input type="checkbox" name="publish_allowance_single"><span>単身赴任手当</span></label><label><input type="checkbox" name="publish_allowance_housing"><span>住居手当申請</span></label></details>
              <details open><summary data-i18n="commonSettings">共通設定</summary><label><input type="checkbox" name="publish_common_portal" checked><span>トップページ</span></label><label><input type="checkbox" name="publish_common_account" checked><span>アカウント管理</span></label><label><input type="checkbox" name="publish_common_staff"><span>職員管理</span></label><label><input type="checkbox" name="publish_common_customer"><span>顧客管理</span></label><label><input type="checkbox" name="publish_common_notice" checked><span>お知らせ管理</span></label><label><input type="checkbox" name="publish_common_salary_owner" checked><span>給与支払者情報管理</span></label><label><input type="checkbox" name="publish_common_mail_send"><span>メール送信管理</span></label><label><input type="checkbox" name="publish_common_history" checked><span>利用履歴参照</span></label><label><input type="checkbox" name="publish_common_notification" checked><span>通知設定</span></label><label><input type="checkbox" name="publish_common_data_sheet"><span>データシート設定</span></label><label><input type="checkbox" name="publish_common_group" checked><span>グループ設定</span></label><label><input type="checkbox" name="publish_common_role" checked><span>ロール管理</span></label><label><input type="checkbox" name="publish_common_retiree"><span>退職者参照設定</span></label><label><input type="checkbox" name="publish_common_belong_master" checked><span>所属マスタ</span></label><label><input type="checkbox" name="publish_common_job_master" checked><span>職種マスタ</span></label><label><input type="checkbox" name="publish_common_generic_master" checked><span>汎用マスタ</span></label><label><input type="checkbox" name="publish_common_system" checked><span>共通システム設定</span></label><label><input type="checkbox" name="publish_common_mail_setting"><span>メール設定</span></label><label><input type="checkbox" name="publish_common_scheduler" checked><span>スケジュールタスク</span></label><label><input type="checkbox" name="publish_common_route_search"><span>交通経路検索設定</span></label><label><input type="checkbox" name="publish_common_dictionary" checked><span>データ辞書</span></label><label><input type="checkbox" name="publish_common_report_template" checked><span>帳票テンプレート管理</span></label><label><input type="checkbox" name="publish_common_log" checked><span>ログ管理</span></label></details>
            </div>
          </fieldset>
        </section>
      </div>
    </form>

    <section class="panel config-history-panel">
      <div class="panel-heading">
        <div>
          <p class="section-kicker" data-i18n="configHistoryKicker">設定履歴</p>
          <h2 data-i18n="configHistoryTitle">構成設定履歴</h2>
        </div>
      </div>
      <div id="configHistory" class="config-history-list"></div>
    </section>

    <section class="workbench">
      <section class="panel history-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker" data-i18n="historyKicker">履歴</p>
            <h2 data-i18n="historyTitle">構造履歴</h2>
          </div>
          <button id="newJobMode" class="secondary" type="button" data-i18n="newBuild">新規構造</button>
        </div>
        <div id="jobs" class="jobs"></div>
      </section>

      <section class="panel result-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker" data-i18n="resultKicker">結果</p>
            <h2 data-i18n="resultTitle">成果物</h2>
          </div>
        </div>
        <div id="result" class="empty-state" data-i18n="selectTask">タスクを選択してください。</div>
      </section>
    </section>

    <section class="panel terminal-frame-panel">
      <details id="terminalConsoleDetails">
        <summary data-i18n="terminalConsole">ビルド端末コンソール</summary>
        <iframe id="terminalFrame" title="build terminal console" data-src="/build-terminal/"></iframe>
      </details>
    </section>

    <section class="panel log-panel">
      <div class="panel-heading">
        <div>
          <p class="section-kicker" data-i18n="logKicker">ログ</p>
          <h2 data-i18n="logTitle">実行ログ</h2>
        </div>
        <span class="muted" data-i18n="autoScroll">自動スクロール</span>
      </div>
      <pre id="log"></pre>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_JS = r"""
const I18N = {
  'ja-JP': {
    title: '庶務事務システム构造器',
    subtitle: '構築成果物と固定資材を組み合わせ、正式な製品交付パッケージを生成します。',
    language: '表示言語',
    terminalTitle: 'ビルド端末',
    terminalUnknown: '状態不明',
    terminalHint: '状態を更新してから開始してください。',
    terminalRunning: '稼働中',
    terminalStopped: '停止中',
    terminalUnreachable: '到達不可',
    terminalPermissionDenied: '権限不足',
    terminalUnconfigured: 'ビルド端末制御が未設定',
    refreshStatus: '状態更新',
    startTerminal: 'ビルド端末を起動',
    stopTerminal: 'ビルド端末を停止',
    stopTerminalConfirm: 'ビルド端末を停止するには SHUTDOWN と入力してください。',
    stopTerminalConfirmFailed: '入力が一致しないため、ビルド端末の停止を中止しました。',
    formKicker: '構造設定',
    formTitle: '構成パラメータ',
    productVariant: '製品バージョン',
    variantStandard: '標準版',
    variantNho: 'NHO版',
    materialNumber: '資材番号',
    materialNumberPlaceholder: '例：2026-05-20-001',
    materialNumberSelect: '候補から選択',
    materialNumberLoadFailed: '候補を取得できません。手入力してください',
    comboNoMatches: '一致する候補がありません',
    stopJob: '停止',
    startJob: '構造を開始',
    backendBranch: 'バックエンドブランチ',
    frontendBranch: 'フロントエンドブランチ',
    tabPreparation: '事前準備',
    tabImportPlan: '導入計画',
    basicBuildInfo: '構築パラメータ',
    helpBranch: 'ヘルプブランチ',
    customerHost: '顧客アクセスアドレス',
    webPort: 'Web ポート',
    enableHttps: 'HTTPS / 443 設定を生成',
    apHostInfo: 'AP 主機情報',
    apHostIp: 'AP 主機 IP',
    apCpuCount: 'AP CPU 数',
    apMemoryGb: 'AP メモリ GB',
    dbHostInfo: 'DB 主機情報',
    postgresHost: 'PostgreSQL ホスト',
    postgresPort: 'PostgreSQL ポート',
    postgresUser: 'PostgreSQL ユーザー',
    postgresPassword: 'PostgreSQL パスワード',
    webHostInfo: 'WEB 主機情報',
    webHostName: 'WEB 主機名',
    webCertName: 'WEB 証明書名',
    webKeyName: 'WEB Key 名',
    mailServiceInfo: 'メールサービス情報',
    mailHostIp: 'メール主機 IP',
    mailPort: 'メールポート',
    mailEncryption: '暗号化方式',
    mailAuthMethod: '認証方式',
    mailUser: 'メールユーザー',
    mailPassword: 'メールパスワード',
    mailNote: 'メール備考',
    updsServiceInfo: 'UPDS サービス情報',
    updsHostName: 'UPDS 主機名',
    updsUser: 'UPDS ユーザー',
    updsPassword: 'UPDS パスワード',
    updsPort: 'UPDS ポート',
    updsDbName: 'UPDS DB 名',
    ekispertInfo: '駅すぱあと情報',
    ekispertUrl: '駅すぱあと URL',
    appHostName: 'アプリケーションサービスホスト名',
    appHostPlaceholder: '顧客アクセスアドレスを使用',
    ohrServicePort: 'OHR サービスポート',
    organisationName: '顧客機関名',
    organisationNamePlaceholder: '例：学校法人サンプル',
    organisationDstart: '機関開始日',
    employeeNumberDigits: '職員番号桁数',
    customerSituation: 'お客様の実績状況収集',
    facilitySituation: '施設状況',
    singleFacility: '単施設（一つ給与計算センター）',
    multipleFacilities: '複数施設（複数給与計算センター）',
    mailUsage: 'メール利用',
    ekispertServer: '駅すぱあとサーバ',
    courseLecture: '係・講座',
    workflowUpds: 'ワークフロー申請 UPDSへ連携',
    personalNumber: '個人識別番号',
    use: '利用',
    notUse: '利用しない',
    screenPublishPlan: '画面公開計画',
    shomuSystem: '庶務事務',
    yearEndAdjustment: '年末調整',
    applications: '各種申請',
    allowances: '諸手当',
    commonSettings: '共通設定',
    configHistoryKicker: '設定履歴',
    configHistoryTitle: '構成設定履歴',
    configHistoryLoad: '読み込み',
    configHistoryDelete: '削除',
    noConfigHistory: '保存された設定履歴はありません。',
    historyKicker: '履歴',
    historyTitle: '構造履歴',
    resultKicker: '結果',
    resultTitle: '成果物',
    logKicker: 'ログ',
    logTitle: '実行ログ',
    terminalConsole: 'ビルド端末コンソール',
    terminalConsoleLocked: '構造開始後に表示できます',
    terminalHeartbeat: 'ビルド端末稼働中',
    progressTitle: '全体進捗',
    progressSteps: {
      terminal_check: '端末確認',
      terminal_dispatch: '端末依頼',
      terminal_build: '端末構築',
      download_artifacts: '成果物取得',
      sql_assets: 'SQL 資材',
      data_sync_assets: 'データ連携',
      account_sql: '4.account.sql',
      help_sql: 'Help SQL',
      standalone_zip: '最終 ZIP',
      complete: '完了'
    },
    autoScroll: '自動スクロール',
    selectTask: 'タスクを選択してください。',
    noTask: 'タスク未選択',
    newBuild: '新規構造',
    newBuildReady: '新しい構造を開始できます。構造パラメータを入力してください。',
    hostTaskId: '主控タスク',
    statusLabel: '状態',
    productDir: '交付ディレクトリ',
    commonZip: '共通.zip',
    productDirHint: 'このパスは Web サイトを動かしている宿主機上の場所です。閲覧している端末のローカルパスではありません。',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: 'コピー',
    copied: 'コピーしました',
    copyFailed: 'コピー失敗',
    deleteJob: '削除',
    deleteConfirm: 'このタスクと対応する成果物を削除しますか？',
    deleteFailed: '削除失敗',
    remoteBuild: 'ビルド端末番号',
    error: 'エラー',
    terminalFirst: 'ビルド端末を起動してから開始してください。',
    cancelled: '停止しました'
  },
  'zh-CN': {
    title: '庶务事务系统构造器',
    subtitle: '组合构建成果物与固定资源，生成正式产品交付包。',
    language: '显示语言',
    terminalTitle: '构建终端',
    terminalUnknown: '状态未知',
    terminalHint: '请先刷新状态，再开始构建。',
    terminalRunning: '运行中',
    terminalStopped: '已关闭',
    terminalUnreachable: '不可达',
    terminalPermissionDenied: '权限不足',
    terminalUnconfigured: '未配置构建终端控制',
    refreshStatus: '刷新状态',
    startTerminal: '启动构建终端',
    stopTerminal: '关闭构建终端',
    stopTerminalConfirm: '如需关闭构建终端，请输入 SHUTDOWN。',
    stopTerminalConfirmFailed: '输入不一致，已取消关闭构建终端。',
    formKicker: '打包设置',
    formTitle: '构造参数',
    productVariant: '产品版本',
    variantStandard: '标准版',
    variantNho: 'NHO版',
    materialNumber: '资材编号',
    materialNumberPlaceholder: '例如：2026-05-20-001',
    materialNumberSelect: '从候选中选择',
    materialNumberLoadFailed: '候选取得失败，请手工输入',
    comboNoMatches: '没有匹配的候选',
    stopJob: '停止',
    startJob: '开始构造',
    backendBranch: '后端分支',
    frontendBranch: '前端分支',
    tabPreparation: '事前准备',
    tabImportPlan: '导入计划',
    basicBuildInfo: '构建参数',
    helpBranch: 'Help 分支',
    customerHost: '客户访问地址',
    webPort: 'Web 端口',
    enableHttps: '生成 HTTPS / 443 配置',
    apHostInfo: 'AP 主机信息',
    apHostIp: 'AP 主机 IP',
    apCpuCount: 'AP CPU 数',
    apMemoryGb: 'AP 内存 GB',
    dbHostInfo: 'DB 主机信息',
    postgresHost: 'PostgreSQL 主机',
    postgresPort: 'PostgreSQL 端口',
    postgresUser: 'PostgreSQL 用户',
    postgresPassword: 'PostgreSQL 密码',
    webHostInfo: 'WEB 主机信息',
    webHostName: 'WEB 主机名',
    webCertName: 'WEB 证书名',
    webKeyName: 'WEB Key 名',
    mailServiceInfo: '邮件服务信息',
    mailHostIp: '邮件主机 IP',
    mailPort: '邮件端口',
    mailEncryption: '加密方式',
    mailAuthMethod: '认证方式',
    mailUser: '邮件用户名',
    mailPassword: '邮件密码',
    mailNote: '邮件备注',
    updsServiceInfo: 'UPDS 服务信息',
    updsHostName: 'UPDS 主机名',
    updsUser: 'UPDS 用户名',
    updsPassword: 'UPDS 密码',
    updsPort: 'UPDS 端口',
    updsDbName: 'UPDS DB 名',
    ekispertInfo: '駅すぱあと信息',
    ekispertUrl: '駅すぱあと URL',
    appHostName: '应用服务主机名',
    appHostPlaceholder: '默认取客户访问地址',
    ohrServicePort: 'OHR 服务端口',
    organisationName: '客户机构名称',
    organisationNamePlaceholder: '例如：学校法人サンプル',
    organisationDstart: '机构开始日',
    employeeNumberDigits: '职员番号位数',
    customerSituation: '客户实际情况收集',
    facilitySituation: '设施情况',
    singleFacility: '单设施（一个工资计算中心）',
    multipleFacilities: '多设施（多个工资计算中心）',
    mailUsage: '邮件利用',
    ekispertServer: '駅すぱあと服务器',
    courseLecture: '系・讲座',
    workflowUpds: '工作流申请向 UPDS 连携',
    personalNumber: '个人识别番号',
    use: '利用',
    notUse: '不利用',
    screenPublishPlan: '画面公开计划',
    shomuSystem: '庶务事务',
    yearEndAdjustment: '年末调整',
    applications: '各类申请',
    allowances: '诸手当',
    commonSettings: '共通设定',
    configHistoryKicker: '配置历史',
    configHistoryTitle: '构造配置历史',
    configHistoryLoad: '加载',
    configHistoryDelete: '删除',
    noConfigHistory: '还没有保存的配置历史。',
    historyKicker: '历史',
    historyTitle: '构造历史',
    resultKicker: '结果',
    resultTitle: '成果物',
    logKicker: '日志',
    logTitle: '执行日志',
    terminalConsole: '构建终端控制台',
    terminalConsoleLocked: '开始构造后可打开',
    terminalHeartbeat: '构建终端运行中',
    progressTitle: '整体进度',
    progressSteps: {
      terminal_check: '终端确认',
      terminal_dispatch: '终端派发',
      terminal_build: '终端构建',
      download_artifacts: '下载成果物',
      sql_assets: 'SQL 资材',
      data_sync_assets: '数据连携',
      account_sql: '4.account.sql',
      help_sql: 'Help SQL',
      standalone_zip: '最终 ZIP',
      complete: '完成'
    },
    autoScroll: '自动滚动',
    selectTask: '请选择任务。',
    noTask: '未选择任务',
    newBuild: '新建构造',
    newBuildReady: '可以开始新的构造。请填写构造参数。',
    hostTaskId: '主控任务',
    statusLabel: '状态',
    productDir: '交付目录',
    commonZip: '共通.zip',
    productDirHint: '这个路径是在网站宿主机上的位置，不是当前浏览器所在电脑的本地路径。',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: '复制',
    copied: '已复制',
    copyFailed: '复制失败',
    deleteJob: '删除',
    deleteConfirm: '要删除这个任务和对应产物吗？',
    deleteFailed: '删除失败',
    remoteBuild: '构建终端编号',
    error: '错误',
    terminalFirst: '请先启动构建终端再开始。',
    cancelled: '已停止'
  },
  'en-US': {
    title: 'Shomu Jimu System Builder',
    subtitle: 'Assemble build artifacts and static resources into a formal product delivery package.',
    language: 'Language',
    terminalTitle: 'Build terminal',
    terminalUnknown: 'Unknown',
    terminalHint: 'Refresh the status before starting.',
    terminalRunning: 'Running',
    terminalStopped: 'Stopped',
    terminalUnreachable: 'Unreachable',
    terminalPermissionDenied: 'Permission denied',
    terminalUnconfigured: 'Build terminal control is not configured',
    refreshStatus: 'Refresh status',
    startTerminal: 'Start build terminal',
    stopTerminal: 'Stop build terminal',
    stopTerminalConfirm: 'Type SHUTDOWN to stop the build terminal.',
    stopTerminalConfirmFailed: 'Input did not match; build terminal stop was cancelled.',
    formKicker: 'Build settings',
    formTitle: 'Build parameters',
    productVariant: 'Product version',
    variantStandard: 'Standard',
    variantNho: 'NHO',
    materialNumber: 'Material number',
    materialNumberPlaceholder: 'Example: 2026-05-20-001',
    materialNumberSelect: 'Select candidate',
    materialNumberLoadFailed: 'Could not load candidates; enter manually',
    comboNoMatches: 'No matching candidates',
    stopJob: 'Stop',
    startJob: 'Start build',
    backendBranch: 'Backend branch',
    frontendBranch: 'Frontend branch',
    tabPreparation: 'Preparation',
    tabImportPlan: 'Import plan',
    basicBuildInfo: 'Build parameters',
    helpBranch: 'Help branch',
    customerHost: 'Customer access address',
    webPort: 'Web port',
    enableHttps: 'Generate HTTPS / 443 configuration',
    apHostInfo: 'AP host information',
    apHostIp: 'AP host IP',
    apCpuCount: 'AP CPU count',
    apMemoryGb: 'AP memory GB',
    dbHostInfo: 'DB host information',
    postgresHost: 'PostgreSQL Host',
    postgresPort: 'PostgreSQL Port',
    postgresUser: 'PostgreSQL User',
    postgresPassword: 'PostgreSQL Password',
    webHostInfo: 'WEB host information',
    webHostName: 'WEB host name',
    webCertName: 'WEB certificate name',
    webKeyName: 'WEB key name',
    mailServiceInfo: 'Mail service information',
    mailHostIp: 'Mail host IP',
    mailPort: 'Mail port',
    mailEncryption: 'Encryption',
    mailAuthMethod: 'Authentication',
    mailUser: 'Mail user',
    mailPassword: 'Mail password',
    mailNote: 'Mail notes',
    updsServiceInfo: 'UPDS service information',
    updsHostName: 'UPDS host name',
    updsUser: 'UPDS user',
    updsPassword: 'UPDS password',
    updsPort: 'UPDS port',
    updsDbName: 'UPDS DB name',
    ekispertInfo: 'Ekispert information',
    ekispertUrl: 'Ekispert URL',
    appHostName: 'Application service host name',
    appHostPlaceholder: 'Use customer access address',
    ohrServicePort: 'OHR Service Port',
    organisationName: 'Customer organisation name',
    organisationNamePlaceholder: 'Example: Sample University',
    organisationDstart: 'Organisation start date',
    employeeNumberDigits: 'Employee number digits',
    customerSituation: 'Customer usage profile',
    facilitySituation: 'Facility situation',
    singleFacility: 'Single facility (one payroll center)',
    multipleFacilities: 'Multiple facilities (multiple payroll centers)',
    mailUsage: 'Mail usage',
    ekispertServer: 'Ekispert server',
    courseLecture: 'Section / lecture',
    workflowUpds: 'Workflow application UPDS linkage',
    personalNumber: 'Personal identification number',
    use: 'Use',
    notUse: 'Do not use',
    screenPublishPlan: 'Screen publish plan',
    shomuSystem: 'Shomu Jimu',
    yearEndAdjustment: 'Year-end adjustment',
    applications: 'Applications',
    allowances: 'Allowances',
    commonSettings: 'Common settings',
    configHistoryKicker: 'Configuration history',
    configHistoryTitle: 'Build configuration history',
    configHistoryLoad: 'Load',
    configHistoryDelete: 'Delete',
    noConfigHistory: 'No saved configuration history.',
    historyKicker: 'History',
    historyTitle: 'Build history',
    resultKicker: 'Result',
    resultTitle: 'Artifacts',
    logKicker: 'Log',
    logTitle: 'Execution log',
    terminalConsole: 'Build terminal console',
    terminalConsoleLocked: 'Available after build starts',
    terminalHeartbeat: 'Build terminal active',
    progressTitle: 'Overall progress',
    progressSteps: {
      terminal_check: 'Check terminal',
      terminal_dispatch: 'Dispatch',
      terminal_build: 'Terminal build',
      download_artifacts: 'Download artifacts',
      sql_assets: 'SQL assets',
      data_sync_assets: 'Data sync',
      account_sql: '4.account.sql',
      help_sql: 'Help SQL',
      standalone_zip: 'Final ZIP',
      complete: 'Complete'
    },
    autoScroll: 'Auto scroll',
    selectTask: 'Select a task.',
    noTask: 'No task selected',
    newBuild: 'New build',
    newBuildReady: 'Ready to start a new build. Fill in the build parameters.',
    hostTaskId: 'Host task',
    statusLabel: 'Status',
    productDir: 'Delivery directory',
    commonZip: '共通.zip',
    productDirHint: 'This path is on the web host machine, not on the local computer running this browser.',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: 'Copy',
    copied: 'Copied',
    copyFailed: 'Copy failed',
    deleteJob: 'Delete',
    deleteConfirm: 'Delete this task and its artifacts?',
    deleteFailed: 'Delete failed',
    remoteBuild: 'Build terminal ID',
    error: 'Error',
    terminalFirst: 'Start the build terminal first.',
    cancelled: 'Stopped'
  }
};

let lang = localStorage.getItem('hostConsoleLang') || 'ja-JP';
let selected = null;
let timer = null;
let logOffset = 0;
let logLines = [];
let selectedJob = null;
let mode = 'create';
let heartbeatTick = 0;
let lastTerminalStatus = 'unknown';
let lastRenderedResultSignature = '';
let lastFilledJobId = null;
let branchListRequestSeq = 0;
let configHistories = [];
const MAX_LOG_LINES = 1600;

function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N['ja-JP'][key] || key; }
function firstDayOfCurrentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
}
function token() {
  const found = document.cookie.split('; ').find(row => row.startsWith('host_console_token='));
  return found ? decodeURIComponent(found.split('=').slice(1).join('=')) : '';
}
function authHeaders(extra = {}) { return {...extra, 'X-Management-Token': token()}; }
function comboInputForMenu(menu) {
  const combo = menu && menu.closest('.material-combo');
  return combo ? combo.querySelector('input') : null;
}
function filterComboMenu(menu) {
  const input = comboInputForMenu(menu);
  if (!menu || !input) return;
  const keyword = String(input.value || '').trim().toLowerCase();
  let visibleCount = 0;
  menu.querySelectorAll('.material-menu-item').forEach(item => {
    const text = String(item.dataset.value || item.textContent || '').toLowerCase();
    const visible = !keyword || text.includes(keyword);
    item.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  let empty = menu.querySelector('.material-menu-filter-empty');
  if (!empty) {
    empty = document.createElement('div');
    empty.className = 'material-menu-empty material-menu-filter-empty';
    empty.textContent = t('comboNoMatches');
    menu.appendChild(empty);
  }
  empty.hidden = visibleCount !== 0 || !keyword;
}
function chooseComboItem(item) {
  if (!item) return;
  const target = item.dataset.target || 'material_number';
  const input = target === 'material_number'
    ? document.querySelector('input[name="material_number"]')
    : document.getElementById(target);
  if (input) input.value = item.dataset.value || item.textContent || '';
  closeMaterialMenu();
  if (target === 'material_number') loadNhoMaterialReleaseBranches(input && input.value);
}
function fillBranchSelect(id, branches) {
  const input = document.getElementById(id);
  const menu = document.getElementById(`${id}-menu`);
  if (!input || !menu) return;
  menu.innerHTML = '';
  (branches || []).forEach(branch => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'material-menu-item';
    item.textContent = branch;
    item.dataset.value = branch;
    item.dataset.target = id;
    menu.appendChild(item);
  });
  if (!(branches || []).length) {
    const empty = document.createElement('div');
    empty.className = 'material-menu-empty';
    empty.textContent = '';
    menu.appendChild(empty);
  }
  filterComboMenu(menu);
}
function clearBranchInputs() {
  ['backend-branches', 'frontend-branches'].forEach(id => {
    const input = document.getElementById(id);
    const menu = document.getElementById(`${id}-menu`);
    if (input) input.value = '';
    if (menu) menu.innerHTML = '';
  });
  closeMaterialMenu();
}
function fillDatalist(id, values) {
  return;
}
function closeMaterialMenu() {
  document.querySelectorAll('.material-menu').forEach(menu => { menu.hidden = true; });
  document.querySelectorAll('.material-toggle').forEach(toggle => { toggle.setAttribute('aria-expanded', 'false'); });
}
function toggleComboMenu(toggleId, menuId) {
  const menu = document.getElementById(menuId);
  const toggle = document.getElementById(toggleId);
  if (!menu || !toggle || toggle.disabled) return;
  const willOpen = menu.hidden;
  closeMaterialMenu();
  filterComboMenu(menu);
  menu.hidden = !willOpen;
  toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
}
function fillMaterialSelect(values, failed = false) {
  const menu = document.getElementById('material-number-menu');
  if (!menu) return;
  menu.innerHTML = '';
  const items = values || [];
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'material-menu-empty';
    empty.textContent = failed ? t('materialNumberLoadFailed') : t('materialNumberSelect');
    menu.appendChild(empty);
    closeMaterialMenu();
    return;
  }
  items.forEach(value => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'material-menu-item';
    item.textContent = value;
    item.dataset.value = value;
    item.dataset.target = 'material_number';
    menu.appendChild(item);
  });
  filterComboMenu(menu);
}
function getProductVariant() {
  const checked = document.querySelector('input[name="product_variant"]:checked');
  return checked ? checked.value : 'standard';
}
function applyVariantVisibility() {
  const isNho = getProductVariant() === 'nho';
  document.querySelectorAll('.standard-only').forEach(el => { el.hidden = isNho; });
  document.querySelectorAll('.nho-only').forEach(el => { el.hidden = !isNho; });
  if (!isNho) {
    const active = document.querySelector('.standard-tab.active');
    switchStandardTab(active ? active.dataset.standardTab : 'prep');
  }
}
function switchStandardTab(tabName) {
  document.querySelectorAll('.standard-tab').forEach(button => {
    const active = button.dataset.standardTab === tabName;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-standard-tab-panel]').forEach(panel => {
    panel.hidden = panel.dataset.standardTabPanel !== tabName;
  });
}
function initializeFixedPublishItems() {
  document.querySelectorAll('.tag-tree input[type="checkbox"][checked]').forEach(input => {
    input.dataset.fixedRequired = 'true';
    input.checked = true;
    input.disabled = true;
    input.setAttribute('aria-disabled', 'true');
    const label = input.closest('label');
    if (label) label.classList.add('fixed-required');
    if (!input.parentElement.querySelector(`input[type="hidden"][data-fixed-mirror="true"][name="${input.name}"]`)) {
      const mirror = document.createElement('input');
      mirror.type = 'hidden';
      mirror.name = input.name;
      mirror.value = 'on';
      mirror.dataset.fixedMirror = 'true';
      input.after(mirror);
    }
  });
}
function enforceFixedPublishItems() {
  document.querySelectorAll('.tag-tree input[type="checkbox"][data-fixed-required="true"]').forEach(input => {
    input.checked = true;
    input.disabled = true;
  });
}
function publishMenuGroupName(details) {
  const summary = details.querySelector('summary');
  return `publish_group_${(summary && summary.dataset.i18n) || 'menu'}`;
}
function applyPublishMenuGroupState(details) {
  const toggle = details.querySelector('.publish-menu-toggle');
  const enabled = !toggle || toggle.checked;
  details.classList.toggle('publish-menu-disabled', !enabled);
  details.dataset.menuDisabled = enabled ? 'false' : 'true';
  details.querySelectorAll('input').forEach(input => {
    if (input === toggle) return;
    if (input.dataset.fixedMirror === 'true') {
      input.disabled = !enabled;
      return;
    }
    if (!enabled) {
      input.disabled = true;
      return;
    }
    if (input.dataset.fixedRequired === 'true') {
      input.checked = true;
      input.disabled = true;
    }
  });
}
function initializePublishMenuGroups() {
  document.querySelectorAll('.tag-tree details').forEach(details => {
    const summary = details.querySelector('summary');
    if (!summary || summary.querySelector('.publish-menu-toggle')) return;
    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.name = publishMenuGroupName(details);
    toggle.checked = true;
    toggle.className = 'publish-menu-toggle';
    toggle.addEventListener('click', event => event.stopPropagation());
    toggle.addEventListener('change', () => applyPublishMenuGroupState(details));
    summary.prepend(toggle);
    applyPublishMenuGroupState(details);
  });
}
function enforcePublishMenuGroups() {
  document.querySelectorAll('.tag-tree details').forEach(applyPublishMenuGroupState);
}
async function loadBranchLists() {
  const expectedVariant = getProductVariant();
  const requestSeq = ++branchListRequestSeq;
  fillBranchSelect('backend-branches', []);
  fillBranchSelect('frontend-branches', []);
  try {
    const variant = encodeURIComponent(expectedVariant);
    const [backend, frontend] = await Promise.all([
      fetch(`/build-terminal/api/backend-branches?product_variant=${variant}`).then(res => res.json()),
      fetch(`/build-terminal/api/frontend-branches?product_variant=${variant}`).then(res => res.json())
    ]);
    if (requestSeq !== branchListRequestSeq || getProductVariant() !== expectedVariant) return;
    fillBranchSelect('backend-branches', backend.branches);
    fillBranchSelect('frontend-branches', frontend.branches);
  } catch (error) {
    console.warn('failed to load branch lists', error);
  }
}
async function loadMaterialNumbers() {
  if (getProductVariant() !== 'nho') {
    fillDatalist('material-numbers', []);
    fillMaterialSelect([]);
    return;
  }
  try {
    const res = await fetch('/build-terminal/api/nho-material-numbers');
    const data = await res.json();
    const values = data.material_numbers || [];
    fillDatalist('material-numbers', values);
    fillMaterialSelect(values, !values.length && Boolean(data.error));
  } catch (error) {
    console.warn('failed to load NHO material numbers', error);
    fillDatalist('material-numbers', []);
    fillMaterialSelect([], true);
  }
}
async function loadNhoMaterialReleaseBranches(materialNumber) {
  if (getProductVariant() !== 'nho') return;
  const value = String(materialNumber || '').trim();
  if (!/^\d{8}$/.test(value)) return;
  try {
    const res = await fetch(`/api/nho-material-release-branches?material_number=${encodeURIComponent(value)}`);
    const data = await res.json();
    if (data.error) {
      console.warn('failed to load NHO release branches', data.error);
      return;
    }
    document.getElementById('backend-branches').value = data.backend_branch || '';
    document.getElementById('frontend-branches').value = data.frontend_branch || '';
  } catch (error) {
    console.warn('failed to load NHO release branches', error);
  }
}
function translateLogText(text) {
  const maps = {
    'ja-JP': {
      'build_terminal_dispatch': 'ビルド端末へ構築を依頼しました',
      'remote_build_id': 'ビルド端末番号',
      'remote_build_status': 'ビルド端末状態',
      'download_artifacts': 'package.zip / web.zip を取得しています',
      'selected_artifacts_done': '選択した成果物の取得が完了しました',
      'standalone_packaging': '製品交付パッケージを生成しています',
      'sql_svn_download': 'SQL 資材を取得しています',
      'sql_template_copy': 'SQL 資材を配置しています',
      'data_sync_git_sync': 'データ連携資材を取得しています',
      'data_sync_cache_fallback': 'データ連携資材の取得に失敗したため、ローカルキャッシュを使用します',
      'data_sync_copy': 'データ連携資材を配置しています',
      'account_sql_patch': '4.account.sql を反映しています',
      'help_sql_replace': 'Help SQL を反映しています',
      'standalone_zip_rebuild': 'OneHrStandalone.zip を生成しています',
      'standalone_package_done': '製品交付パッケージの生成が完了しました',
      'cancelled': '停止しました',
      'failed': '失敗',
      '构建开始': '構築開始',
      '参数校验': 'パラメータ検証',
      '恢复前端工作区': 'フロントエンド作業区復元',
      '收集产物': '成果物収集',
      '产物已收集': '成果物収集完了',
      '构建成功': '構築成功',
      '构建失败': '構築失敗',
      '构建已停止': '構築を停止しました',
      'running': '実行中',
      'success': '成功',
      'failed': '失敗',
      'cancelled': '停止済み'
    },
    'en-US': {
      'build_terminal_dispatch': 'Build terminal dispatched',
      'remote_build_id': 'Build terminal ID',
      'remote_build_status': 'Build terminal status',
      'download_artifacts': 'Downloading package.zip / web.zip',
      'selected_artifacts_done': 'Selected artifacts downloaded',
      'standalone_packaging': 'Generating delivery package',
      'sql_svn_download': 'Downloading SQL assets',
      'sql_template_copy': 'Copying SQL assets',
      'data_sync_git_sync': 'Fetching data synchronization assets',
      'data_sync_cache_fallback': 'Data synchronization fetch failed; using local cache',
      'data_sync_copy': 'Copying data synchronization assets',
      'account_sql_patch': 'Applying 4.account.sql changes',
      'help_sql_replace': 'Applying Help SQL',
      'standalone_zip_rebuild': 'Generating OneHrStandalone.zip',
      'standalone_package_done': 'Delivery package generated',
      'cancelled': 'Stopped',
      'failed': 'Failed',
      '构建开始': 'Build started',
      '参数校验': 'Validate parameters',
      '恢复前端工作区': 'Restore frontend workspace',
      '收集产物': 'Collect artifacts',
      '产物已收集': 'Artifacts collected',
      '构建成功': 'Build succeeded',
      '构建失败': 'Build failed',
      '构建已停止': 'Build stopped'
    },
    'zh-CN': {
      'build_terminal_dispatch': '已派发到构建终端',
      'remote_build_id': '构建终端编号',
      'remote_build_status': '构建终端状态',
      'download_artifacts': '正在获取 package.zip / web.zip',
      'selected_artifacts_done': '选定成果物下载完成',
      'standalone_packaging': '正在生成产品交付包',
      'sql_svn_download': '正在获取 SQL 资材',
      'sql_template_copy': '正在配置 SQL 资材',
      'data_sync_git_sync': '正在获取数据连携资材',
      'data_sync_cache_fallback': '数据连携资材获取失败，使用本地缓存继续',
      'data_sync_copy': '正在配置数据连携资材',
      'account_sql_patch': '正在修改 4.account.sql',
      'help_sql_replace': '正在反映 Help SQL',
      'standalone_zip_rebuild': '正在生成 OneHrStandalone.zip',
      'standalone_package_done': '产品交付包生成完成',
      '构建开始': '构建开始',
      '参数校验': '参数校验',
      '恢复前端工作区': '恢复前端工作区',
      '收集产物': '收集产物',
      '产物已收集': '产物已收集',
      '构建成功': '构建成功',
      '构建失败': '构建失败',
      '构建已停止': '构建已停止',
      'running': '运行中',
      'success': '成功',
      'failed': '失败',
      'cancelled': '已停止'
    }
  };
  const map = maps[lang] || {};
  let result = text || '';
  Object.entries(map).forEach(([from, to]) => { result = result.split(from).join(to); });
  return result;
}

function heartbeatLine(job) {
  if (!job || !['queued', 'running'].includes(job.status)) return '';
  const rawStatus = job.remote_build_status || job.status;
  const status = translateLogText(rawStatus);
  const phase = heartbeatTick % 72;
  const indent = Math.floor(phase / 6);
  const dots = (phase % 6) + 1;
  heartbeatTick += 1;
  return `${t('terminalHeartbeat')} ${status} ${' '.repeat(indent)}${'.'.repeat(dots)}`;
}

function renderLog() {
  const log = document.getElementById('log');
  const shouldStickToBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  const heartbeat = heartbeatLine(selectedJob);
  const body = logLines.join('\n');
  log.textContent = body + (heartbeat ? `${body ? '\n' : ''}${heartbeat}` : '');
  if (shouldStickToBottom) log.scrollTop = log.scrollHeight;
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

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('language').value = lang;
  if (mode === 'create') {
    document.getElementById('result').innerHTML = `<div class="empty-state">${t('newBuildReady')}</div>`;
  }
  renderTerminal(lastTerminalStatus);
  renderConfigHistory();
}

function setFormLocked(locked) {
  const terminalLocked = lastTerminalStatus !== 'running';
  const modeLocked = mode !== 'create';
  const isNho = getProductVariant() === 'nho';
  document.querySelectorAll('#form input, #form select, #form button.material-toggle, #startJob').forEach(el => {
    if (el.name === 'product_variant') {
      el.disabled = false;
      return;
    }
    if (el.classList && el.classList.contains('publish-menu-toggle')) {
      const standardHidden = isNho && el.closest('.standard-only');
      el.disabled = Boolean(standardHidden) || locked || modeLocked || terminalLocked;
      applyPublishMenuGroupState(el.closest('details'));
      return;
    }
    if (el.dataset.fixedMirror === 'true') {
      const disabledByMenu = el.closest('details') && el.closest('details').dataset.menuDisabled === 'true';
      el.disabled = Boolean(disabledByMenu);
      return;
    }
    const disabledByMenu = el.closest('details') && el.closest('details').dataset.menuDisabled === 'true';
    if (disabledByMenu) {
      el.disabled = true;
      return;
    }
    if (el.dataset.fixedRequired === 'true') {
      el.checked = true;
      el.disabled = true;
      return;
    }
    const standardHidden = isNho && el.closest('.standard-only');
    const nhoHidden = !isNho && el.closest('.nho-only');
    el.disabled = Boolean(standardHidden) || Boolean(nhoHidden) || locked || modeLocked || terminalLocked;
  });
  document.querySelectorAll('#form button.nho-only').forEach(el => {
    const nhoHidden = !isNho;
    el.disabled = Boolean(nhoHidden) || locked || modeLocked || terminalLocked;
  });
  document.getElementById('stopJob').disabled = !(mode === 'active' && selected && locked);
  enforcePublishMenuGroups();
}

function fillFormFromRequest(request) {
  request = request || {};
  const form = document.getElementById('form');
  Array.from(form.elements).forEach(el => {
    if (!el.name || !(el.name in request)) return;
    if (el.type === 'checkbox') {
      if (el.dataset.fixedRequired === 'true') {
        el.checked = true;
        return;
      }
      el.checked = Boolean(request[el.name]);
      return;
    }
    if (el.type === 'radio') {
      el.checked = String(request[el.name]) === el.value;
      return;
    }
    el.value = request[el.name] == null ? '' : request[el.name];
  });
  applyVariantVisibility();
  enforceFixedPublishItems();
  enforcePublishMenuGroups();
}

function fillFormFromJob(job) {
  fillFormFromRequest((job && job.request) || {});
}

function markSelectedJobRow(jobId) {
  document.querySelectorAll('#jobs .job').forEach(row => {
    row.classList.toggle('active', mode !== 'create' && row.dataset.jobId === jobId);
  });
}

function enterCreateMode() {
  mode = 'create';
  selected = null;
  selectedJob = null;
  lastFilledJobId = null;
  lastRenderedResultSignature = '';
  logOffset = 0;
  logLines = [];
  document.getElementById('log').textContent = '';
  document.getElementById('result').innerHTML = `<div class="empty-state">${t('newBuildReady')}</div>`;
  syncTerminalConsole(null);
  markSelectedJobRow(null);
  setFormLocked(false);
}

function jobMetaLine(job) {
  const parts = [`${t('statusLabel')}: ${translateLogText(job.status)}`];
  if (job.remote_build_id) parts.push(`${t('remoteBuild')}: ${job.remote_build_id}`);
  return parts.join(' / ');
}

function statusText(status) {
  return {
    running: t('terminalRunning'),
    stopped: t('terminalStopped'),
    unreachable: t('terminalUnreachable'),
    permission_denied: t('terminalPermissionDenied'),
    unconfigured: t('terminalUnconfigured'),
    unknown: t('terminalUnknown')
  }[status] || t('terminalUnknown');
}

function renderTerminal(status) {
  lastTerminalStatus = status || 'unknown';
  const box = document.querySelector('.terminal-panel');
  box.dataset.status = lastTerminalStatus;
  document.getElementById('terminalStatus').textContent = statusText(lastTerminalStatus);
}

async function refreshTerminal() {
  const res = await fetch('/api/build-terminal/status', {headers: authHeaders()});
  if (!res.ok) {
    renderTerminal('unknown');
    setFormLocked(['queued', 'running'].includes(selectedJob && selectedJob.status));
    return {status: 'unknown'};
  }
  const data = await res.json();
  renderTerminal(data.status);
  if (data.status === 'running') loadBranchLists();
  if (data.status === 'running') loadMaterialNumbers();
  setFormLocked(['queued', 'running'].includes(selectedJob && selectedJob.status));
  return data;
}

async function terminalAction(action) {
  if (action === 'stop') {
    const typed = window.prompt(t('stopTerminalConfirm'), '');
    if ((typed || '').trim().toUpperCase() !== 'SHUTDOWN') {
      alert(t('stopTerminalConfirmFailed'));
      return;
    }
  }
  const res = await fetch(`/api/build-terminal/${action}`, {method: 'POST', headers: authHeaders({'Content-Type': 'application/json'}), body: '{}'});
  const data = await res.json();
  renderTerminal(data.status === 'requested' ? 'unknown' : data.status);
  setTimeout(refreshTerminal, 2500);
}

document.getElementById('language').addEventListener('change', event => {
  lang = event.target.value;
  localStorage.setItem('hostConsoleLang', lang);
  lastRenderedResultSignature = '';
  applyI18n();
  refresh();
});
document.getElementById('refreshTerminal').addEventListener('click', refreshTerminal);
document.getElementById('startTerminal').addEventListener('click', () => terminalAction('start'));
document.getElementById('stopTerminal').addEventListener('click', () => terminalAction('stop'));
document.getElementById('newJobMode').addEventListener('click', () => {
  enterCreateMode();
  refresh();
});
[
  ['material-number-toggle', 'material-number-menu'],
  ['backend-branches-toggle', 'backend-branches-menu'],
  ['frontend-branches-toggle', 'frontend-branches-menu']
].forEach(([toggleId, menuId]) => {
  document.getElementById(toggleId).addEventListener('click', () => toggleComboMenu(toggleId, menuId));
});
document.querySelectorAll('.material-menu').forEach(menu => {
  menu.addEventListener('click', (event) => {
    const item = event.target.closest('.material-menu-item');
    if (!item) return;
    chooseComboItem(item);
  });
});
document.querySelectorAll('.material-combo input').forEach(input => {
  input.addEventListener('input', () => {
    const combo = input.closest('.material-combo');
    const menu = combo && combo.querySelector('.material-menu');
    const toggle = combo && combo.querySelector('.material-toggle');
    if (!menu || !toggle || toggle.hidden || toggle.disabled) return;
    filterComboMenu(menu);
    menu.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
  });
  input.addEventListener('focus', () => {
    const combo = input.closest('.material-combo');
    const menu = combo && combo.querySelector('.material-menu');
    if (menu && !menu.hidden) filterComboMenu(menu);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    const combo = input.closest('.material-combo');
    const menu = combo && combo.querySelector('.material-menu');
    const firstVisible = menu && Array.from(menu.querySelectorAll('.material-menu-item')).find(item => !item.hidden);
    if (firstVisible) {
      event.preventDefault();
      chooseComboItem(firstVisible);
    }
  });
});
document.querySelector('input[name="material_number"]').addEventListener('change', event => {
  loadNhoMaterialReleaseBranches(event.target.value);
});
document.addEventListener('click', (event) => {
  if (!event.target.closest('.material-combo')) closeMaterialMenu();
});
document.querySelectorAll('input[name="product_variant"]').forEach(el => {
  el.addEventListener('change', () => {
    enterCreateMode();
    clearBranchInputs();
    applyVariantVisibility();
    loadBranchLists();
    loadMaterialNumbers();
    renderConfigHistory();
    setFormLocked(false);
    refresh();
  });
});
document.querySelectorAll('.standard-tab').forEach(button => {
  button.addEventListener('click', () => switchStandardTab(button.dataset.standardTab || 'prep'));
});
initializeFixedPublishItems();
initializePublishMenuGroups();
document.getElementById('terminalConsoleDetails').addEventListener('toggle', event => {
  const frame = document.getElementById('terminalFrame');
  if (event.target.open && !frame.dataset.ready) {
    event.target.open = false;
    return;
  }
  if (event.target.open) {
    if (!frame.src) frame.src = frame.dataset.src;
  } else {
    unloadTerminalFrame();
  }
});
document.getElementById('stopJob').addEventListener('click', async () => {
  if (!selected) return;
  await fetch(`/api/jobs/${selected}/cancel`, {method: 'POST', headers: authHeaders({'Content-Type': 'application/json'}), body: '{}'});
  setFormLocked(false);
  refresh();
});

async function deleteSelectedJob(jobId = selected) {
  if (!jobId) return;
  if (!confirm(t('deleteConfirm'))) return;
  const res = await fetch(`/api/jobs/${jobId}`, {method: 'DELETE', headers: authHeaders()});
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    alert(`${t('deleteFailed')}: ${data.error || res.status}`);
    return;
  }
  if (selected === jobId) {
    enterCreateMode();
  }
  await refresh();
}

function renderConfigHistory() {
  const list = document.getElementById('configHistory');
  if (!list) return;
  const currentVariant = getProductVariant();
  const items = configHistories.filter(item => (item.product_variant || 'standard') === currentVariant);
  list.innerHTML = '';
  if (!items.length) {
    list.innerHTML = `<div class="empty-state">${t('noConfigHistory')}</div>`;
    return;
  }
  items.forEach(item => {
    const row = document.createElement('div');
    row.className = 'config-history-item';
    row.innerHTML = `<div><strong>${escapeHtml(item.label || item.id)}</strong><span>${escapeHtml(item.material_number || '')}</span></div><div class="config-history-actions"><button type="button" class="secondary" data-action="load">${t('configHistoryLoad')}</button><button type="button" class="danger-lite" data-action="delete">${t('configHistoryDelete')}</button></div>`;
    row.querySelector('[data-action="load"]').onclick = () => loadConfigHistory(item.id);
    row.querySelector('[data-action="delete"]').onclick = () => deleteConfigHistory(item.id);
    list.appendChild(row);
  });
}

async function refreshConfigHistory() {
  try {
    const res = await fetch('/api/configs');
    const data = await res.json();
    configHistories = data.configs || [];
    renderConfigHistory();
  } catch (error) {
    console.warn('failed to load config history', error);
  }
}

function loadConfigHistory(configId) {
  const item = configHistories.find(entry => entry.id === configId);
  if (!item) return;
  enterCreateMode();
  fillFormFromRequest(item.request || {});
  clearBranchInputs();
  loadBranchLists().then(() => {
    fillFormFromRequest(item.request || {});
  });
  loadMaterialNumbers();
}

async function deleteConfigHistory(configId) {
  const res = await fetch(`/api/configs/${encodeURIComponent(configId)}`, {method: 'DELETE', headers: authHeaders()});
  const result = await res.json();
  if (result.error) {
    alert(result.error);
    return;
  }
  await refreshConfigHistory();
}

document.getElementById('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const terminal = await refreshTerminal();
  if (terminal.status !== 'running') {
    alert(t('terminalFirst'));
    return;
  }
  const payload = Object.fromEntries(new FormData(event.target).entries());
  payload.conf_enable_https = event.target.elements.conf_enable_https.checked;
  payload.ui_language = lang;
  const res = await fetch('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const job = await res.json();
  if (job.error) {
    alert(job.error);
    return;
  }
  mode = 'active';
  selected = job.id;
  selectedJob = job;
  lastFilledJobId = null;
  lastRenderedResultSignature = '';
  logOffset = 0;
  logLines = [];
  setFormLocked(true);
  refreshConfigHistory();
  refresh();
  if (!timer) timer = setInterval(refresh, 3000);
});

async function refresh() {
  const res = await fetch('/api/jobs');
  const data = await res.json();
  const currentVariant = getProductVariant();
  const visibleJobs = data.jobs.filter(job => ((job.request && job.request.product_variant) || 'standard') === currentVariant);
  const jobs = document.getElementById('jobs');
  jobs.innerHTML = '';
  const activeJob = visibleJobs.find(job => ['queued', 'running'].includes(job.status));
  if (!visibleJobs.length) {
    jobs.innerHTML = `<div class="empty-state">${t('noTask')}</div>`;
    if (mode !== 'create') enterCreateMode();
    return;
  }
  if (activeJob && (mode !== 'active' || selected !== activeJob.id)) {
    mode = 'active';
    selected = activeJob.id;
    selectedJob = activeJob;
    lastFilledJobId = null;
    lastRenderedResultSignature = '';
    logOffset = 0;
    logLines = [];
  } else if (!activeJob && mode === 'active') {
    enterCreateMode();
  }
  visibleJobs.forEach(job => {
    const btn = document.createElement('div');
    btn.className = mode !== 'create' && job.id === selected ? 'job active' : 'job';
    btn.dataset.jobId = job.id;
    btn.tabIndex = 0;
    const deletable = !['queued', 'running'].includes(job.status);
    btn.innerHTML = `<strong>${t('hostTaskId')}: ${job.id}</strong><span>${escapeHtml(jobMetaLine(job))}</span>${deletable ? `<button type="button" class="delete-job" data-job-id="${escapeHtml(job.id)}">${t('deleteJob')}</button>` : ''}`;
    btn.onclick = () => {
      mode = ['queued', 'running'].includes(job.status) ? 'active' : 'view';
      selected = job.id;
      lastFilledJobId = null;
      lastRenderedResultSignature = '';
      logOffset = 0;
      logLines = [];
      markSelectedJobRow(job.id);
      window.requestAnimationFrame(() => {
        render(job);
        fetchJobLog(true);
      });
    };
    btn.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') btn.click(); };
    jobs.appendChild(btn);
    const deleteBtn = btn.querySelector('.delete-job');
    if (deleteBtn) {
      deleteBtn.onclick = event => {
        event.stopPropagation();
        deleteSelectedJob(job.id);
      };
    }
    if (mode !== 'create' && job.id === selected) render(job);
  });
  if (mode === 'create' && !activeJob) {
    if (!lastRenderedResultSignature) {
      document.getElementById('result').innerHTML = `<div class="empty-state">${t('newBuildReady')}</div>`;
      lastRenderedResultSignature = 'create';
    }
    setFormLocked(false);
  }
  if (mode !== 'create' && selected) await fetchJobLog(false);
}

async function fetchJobLog(reset) {
  if (!selected) return;
  if (reset) {
    logOffset = 0;
    logLines = [];
  }
  const res = await fetch(`/api/jobs/${selected}/log?offset=${logOffset}`);
  if (!res.ok) return;
  const data = await res.json();
  logOffset = data.next_offset;
  if (data.text) {
    appendLogText(data.text);
  }
  renderLog();
}

function render(job) {
  selectedJob = job;
  if (mode !== 'create' && lastFilledJobId !== job.id) {
    fillFormFromJob(job);
    lastFilledJobId = job.id;
  }
  const running = ['queued', 'running'].includes(job.status);
  setFormLocked(running);
  syncTerminalConsole(job);
  renderResultIfChanged(job);
}

function unloadTerminalFrame() {
  const frame = document.getElementById('terminalFrame');
  if (!frame) return null;
  const replacement = frame.cloneNode(false);
  replacement.removeAttribute('src');
  frame.replaceWith(replacement);
  return replacement;
}

function syncTerminalConsole(job) {
  const details = document.getElementById('terminalConsoleDetails');
  let frame = document.getElementById('terminalFrame');
  const summary = details.querySelector('summary');
  const remoteId = job && job.remote_build_id;
  if (!remoteId) {
    details.open = false;
    details.classList.add('disabled');
    frame.dataset.ready = '';
    frame.dataset.src = '/build-terminal/';
    unloadTerminalFrame();
    summary.textContent = `${t('terminalConsole')} · ${t('terminalConsoleLocked')}`;
    return;
  }
  details.classList.remove('disabled');
  frame.dataset.ready = '1';
  const nextSrc = `/build-terminal/?embedded=1&build_id=${encodeURIComponent(remoteId)}`;
  if (frame.dataset.src !== nextSrc) {
    frame.dataset.src = nextSrc;
    if (details.open) frame.src = nextSrc;
  }
  if (!details.open && frame.src) frame = unloadTerminalFrame() || frame;
  summary.textContent = `${t('terminalConsole')} · ${remoteId}`;
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function pathRow(label, value) {
  if (!value) return '';
  const safe = escapeHtml(value);
  const hint = label === t('productDir')
    ? `<button type="button" class="help-dot" aria-label="${escapeHtml(t('productDirHint'))}" title="${escapeHtml(t('productDirHint'))}">?</button>`
    : '';
  return `<div class="path-row"><span class="path-label">${label}${hint}</span><code>${safe}</code><button type="button" class="copy-path" data-path="${safe}">${t('copy')}</button></div>`;
}

function progressLabel(id) {
  const labels = t('progressSteps');
  return (labels && labels[id]) || id;
}

function visibleProgressSteps(job) {
  const progress = job.progress || [];
  const variant = ((job.request && job.request.product_variant) || 'standard');
  if (variant !== 'nho') return progress;
  const hidden = new Set(['data_sync_assets', 'account_sql', 'help_sql']);
  return progress.filter(step => !hidden.has(step.id));
}

function renderProgress(job) {
  const progress = visibleProgressSteps(job);
  if (!progress.length) return '';
  const items = progress.map((step, index) => {
    const status = step.status || 'pending';
    const icon = status === 'success' ? '✓' : status === 'failed' ? '!' : status === 'cancelled' ? '×' : status === 'pending' ? '◷' : '';
    return `<li class="${escapeHtml(status)}">
      <span class="progress-icon">${icon}</span>
      <span class="progress-name">${escapeHtml(progressLabel(step.id))}</span>
      <span class="progress-index">${index + 1}</span>
    </li>`;
  }).join('');
  return `<section class="overall-progress">
    <h3>${t('progressTitle')}</h3>
    <ol>${items}</ol>
  </section>`;
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '-9999px';
  textarea.style.top = '0';
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  try {
    const ok = document.execCommand('copy');
    if (!ok) throw new Error('execCommand copy returned false');
  } finally {
    textarea.remove();
  }
}

function renderResult(job) {
  const outputs = job.outputs || {};
  const box = document.getElementById('result');
  const pathList = outputs.common_zip ? `
      ${pathRow(t('productDir'), outputs.product_dir)}
      ${pathRow(t('commonZip'), outputs.common_zip)}
  ` : outputs.product_dir ? pathRow(t('productDir'), outputs.product_dir) : `
      ${pathRow('package.zip', outputs.package_zip)}
      ${pathRow('web.zip', outputs.web_zip)}
  `;
  box.innerHTML = `
    ${renderProgress(job)}
    <div class="result-summary">
      <div><span>ID</span><strong>${escapeHtml(job.id)}</strong></div>
      <div><span>Status</span><strong>${escapeHtml(job.status)}</strong></div>
      <div><span>${t('remoteBuild')}</span><strong>${escapeHtml(job.remote_build_id || '-')}</strong></div>
      <div><span>${t('error')}</span><strong>${escapeHtml(job.error || '-')}</strong></div>
    </div>
    <div class="path-list">
      ${pathList}
    </div>
    ${['queued', 'running'].includes(job.status) ? '' : `<div class="result-actions"><button type="button" class="danger-lite" id="deleteSelectedJob">${t('deleteJob')}</button></div>`}
  `;
  const deleteButton = box.querySelector('#deleteSelectedJob');
  if (deleteButton) deleteButton.addEventListener('click', () => deleteSelectedJob(job.id));
  box.querySelectorAll('.copy-path').forEach(btn => {
    btn.addEventListener('click', async () => {
      try {
        await copyText(btn.dataset.path || '');
        btn.textContent = t('copied');
      } catch (error) {
        console.warn('copy failed', error);
        btn.textContent = t('copyFailed');
      }
      setTimeout(() => { btn.textContent = t('copy'); }, 1200);
    });
  });
}

function resultSignature(job) {
  return JSON.stringify({
    id: job && job.id,
    status: job && job.status,
    remote_build_id: job && job.remote_build_id,
    error: job && job.error,
    outputs: job && job.outputs,
    progress: job && job.progress
  });
}

function renderResultIfChanged(job) {
  const signature = resultSignature(job);
  if (signature === lastRenderedResultSignature) return;
  lastRenderedResultSignature = signature;
  renderResult(job);
}

applyI18n();
document.getElementById('organisation-dstart').value = firstDayOfCurrentMonth();
applyVariantVisibility();
refreshTerminal();
loadBranchLists();
loadMaterialNumbers();
refreshConfigHistory();
refresh();
timer = setInterval(refresh, 5000);
"""


STYLE_CSS = """
:root {
  --ink: #111111;
  --muted: #6f6f6f;
  --line: #e5e5e5;
  --line-strong: #d4d4d4;
  --panel: #ffffff;
  --panel-muted: #fafafa;
  --accent: #111111;
  --accent-dark: #000000;
  --danger: #b42318;
  --success: #067647;
  --surface: #ffffff;
  --focus: rgba(17, 17, 17, .12);
}
[hidden], .standard-only[hidden] { display: none !important; }
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Noto Sans JP", "Microsoft YaHei", Arial, sans-serif;
  background: var(--surface);
  color: var(--ink);
}
.shell { max-width: 1180px; margin: 0 auto; padding: 24px 24px 40px; }
.hero {
  min-height: 132px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  padding: 18px 0 28px;
  border-bottom: 1px solid var(--line);
}
.eyebrow, .section-kicker {
  margin: 0 0 8px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .04em;
  text-transform: uppercase;
}
h1, h2 { margin: 0; letter-spacing: 0; }
h1 {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 12px;
  font-size: 42px;
  line-height: 1.05;
  font-weight: 760;
}
.app-version {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 3px 8px;
  color: var(--muted);
  background: #fff;
  font-size: 13px;
  font-weight: 760;
}
h2 { font-size: 20px; font-weight: 720; }
.subcopy { max-width: 720px; margin: 12px 0 0; color: var(--muted); font-size: 15px; line-height: 1.65; }
.hero-actions { display: grid; gap: 8px; min-width: 180px; }
.lang-label { color: var(--muted); font-size: 13px; font-weight: 800; }
select, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  min-height: 40px;
  padding: 9px 11px;
  font: inherit;
  outline: none;
  transition: border-color .14s ease, box-shadow .14s ease, background .14s ease;
}
select:focus, input:focus {
  border-color: #111;
  box-shadow: 0 0 0 3px var(--focus);
}
input::placeholder {
  color: #aeb8c6;
  font-weight: 500;
  opacity: 1;
}
input:disabled, select:disabled { background: #f5f5f5; color: #8a8a8a; }
.terminal-panel, .panel {
  background: var(--panel);
  border: 1px solid var(--line);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .03);
  border-radius: 8px;
}
.terminal-panel {
  margin: 18px 0;
  padding: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}
.terminal-panel h2::before {
  content: "";
  display: inline-block;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  margin-right: 10px;
  background: #a3a3a3;
}
.terminal-panel[data-status="running"] h2::before { background: var(--success); }
.terminal-panel[data-status="stopped"] h2::before { background: #b54708; }
.terminal-panel[data-status="unreachable"] h2::before,
.terminal-panel[data-status="permission_denied"] h2::before { background: var(--danger); }
#terminalHint { margin: 8px 0 0; color: var(--muted); }
.terminal-actions, .run-actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }
.panel { padding: 18px; margin-bottom: 16px; }
.panel-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
.form-panel .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.standard-tabs {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  border-bottom: 1px solid var(--line);
  margin-top: 2px;
}
.standard-tab {
  border: 1px solid transparent;
  border-radius: 6px 6px 0 0;
  background: transparent;
  color: var(--muted);
  padding: 8px 12px 10px;
  min-height: 34px;
}
.standard-tab.active {
  color: #fff;
  background: #111;
  border-color: #111;
}
.standard-tab-panel {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  align-items: start;
}
.standard-tab-panel[data-standard-tab-panel="import"] {
  grid-template-columns: 1fr;
}
.form-section {
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-content: start;
  align-items: start;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.form-section legend {
  padding: 0 6px;
  color: var(--ink);
  font-size: 13px;
  font-weight: 760;
}
.form-section .section-wide { grid-column: 1 / -1; }
.option-matrix {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: start;
}
.option-matrix label { min-height: 0; }
.option-matrix select { min-height: 38px; padding: 8px 10px; }
.tag-tree {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.tag-tree details {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: #fafafa;
}
.tag-tree summary {
  cursor: pointer;
  font-weight: 760;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 7px;
}
.tag-tree summary input {
  width: auto;
  min-height: auto;
}
.tag-tree label {
  display: flex;
  min-height: 30px;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
  font-size: 13px;
}
.tag-tree input { width: auto; min-height: auto; }
.tag-tree label.fixed-required { color: #111; cursor: not-allowed; }
.tag-tree label.fixed-required input { opacity: 1; accent-color: #111; }
.tag-tree label.fixed-required span::after {
  content: "必須";
  display: inline-block;
  margin-left: 6px;
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 760;
  vertical-align: 1px;
}
.tag-tree details.publish-menu-disabled {
  background: #f5f5f5;
  color: var(--muted);
}
.tag-tree details.publish-menu-disabled label {
  color: var(--muted);
}
.tag-tree details.publish-menu-disabled label.fixed-required span::after {
  background: #fff;
  color: #8a8a8a;
}
.variant-field {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  border: 0;
}
.variant-field legend {
  margin: 0 8px 0 0;
  padding: 0;
  color: var(--muted);
  font-size: 13px;
  font-weight: 760;
}
.radio-pill {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px 0 34px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: #111;
  font-weight: 760;
  cursor: pointer;
  transition: border-color .14s ease, background .14s ease, box-shadow .14s ease;
}
.radio-pill:hover {
  border-color: var(--line-strong);
  background: #fafafa;
}
.radio-pill:has(input:checked) {
  border-color: #111;
  background: #f7f7f7;
  box-shadow: inset 0 0 0 1px #111;
}
.radio-pill:has(input:focus-visible) {
  box-shadow: 0 0 0 3px var(--focus);
}
.radio-pill input {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: 0;
  opacity: 0;
  pointer-events: none;
}
.radio-pill::before {
  content: "";
  position: absolute;
  left: 20px;
  top: 50%;
  width: 13px;
  height: 13px;
  border: 1px solid #a3a3a3;
  border-radius: 999px;
  background: #fff;
  transform: translate(-50%, -50%);
  box-sizing: border-box;
}
.radio-pill::after {
  content: "";
  position: absolute;
  left: 20px;
  top: 50%;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #111;
  transform: translate(-50%, -50%) scale(0);
  transition: transform .12s ease;
}
.radio-pill:has(input:checked)::before {
  border-color: #111;
}
.radio-pill:has(input:checked)::after {
  transform: translate(-50%, -50%) scale(1);
}
label { display: grid; gap: 7px; font-weight: 760; font-size: 13px; color: #262626; }
.required-field > span::after {
  content: " *";
  color: var(--danger);
  font-weight: 900;
}
.material-combo {
  position: relative;
  display: block;
}
.material-combo input {
  padding-right: 44px;
}
.material-toggle {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 30px;
  min-height: 32px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #111;
  box-shadow: none;
  font-size: 16px;
  line-height: 1;
}
.material-toggle:hover {
  background: #f5f5f5;
  box-shadow: none;
}
.material-toggle:focus {
  outline: none;
  box-shadow: 0 0 0 3px var(--focus);
}
.material-toggle[aria-expanded="true"] {
  background: #f5f5f5;
}
.material-toggle[hidden] {
  display: none;
}
.material-combo:has(.material-toggle[hidden]) input {
  padding-right: 11px;
}
.material-menu {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(0, 0, 0, .10);
  padding: 6px;
}
.material-menu[hidden] {
  display: none;
}
.material-menu-item {
  width: 100%;
  min-height: 34px;
  justify-content: flex-start;
  border: 0;
  border-radius: 6px;
  background: #fff;
  color: #111;
  box-shadow: none;
  padding: 7px 10px;
  text-align: left;
  font-weight: 620;
}
.material-menu-item:hover,
.material-menu-item:focus {
  background: #f5f5f5;
  box-shadow: none;
}
.material-menu-empty {
  padding: 9px 10px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
}
.check-row {
  display: flex;
  align-items: center;
  gap: 9px;
  align-self: end;
  min-height: 43px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-muted);
}
.check-row input { width: auto; }
button {
  min-height: 40px;
  border: 1px solid #111;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  padding: 9px 14px;
  font-weight: 760;
  cursor: pointer;
  transition: background .14s ease, border-color .14s ease, box-shadow .14s ease, color .14s ease;
}
button:hover { background: var(--accent-dark); box-shadow: 0 0 0 3px var(--focus); }
button:disabled { opacity: .45; cursor: not-allowed; }
.secondary { background: #fff; color: #111; border: 1px solid var(--line-strong); }
.secondary:hover { background: #f5f5f5; box-shadow: 0 0 0 3px var(--focus); }
.danger { background: #fff; color: var(--danger); border-color: #f0b8b2; }
.danger:hover { background: #fff7f6; box-shadow: 0 0 0 3px rgba(180, 35, 24, .10); }
.danger-lite { background: #fff; color: var(--danger); border: 1px solid #f0b8b2; }
.danger-lite:hover { background: #fff7f6; box-shadow: 0 0 0 3px rgba(180, 35, 24, .10); }
.workbench { display: grid; grid-template-columns: 1fr; gap: 18px; align-items: start; }
.config-history-list {
  display: grid;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
}
.config-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}
.config-history-item strong { display: block; font-size: 13px; }
.config-history-item span { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }
.config-history-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
.config-history-actions button { min-height: 32px; padding: 6px 10px; }
.jobs { display: grid; gap: 8px; max-height: 360px; overflow: auto; }
.job {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
  background: #fff;
  color: #111;
  border: 1px solid var(--line);
  min-height: 42px;
  font-size: 12px;
  cursor: pointer;
  border-radius: 8px;
  padding: 9px 14px;
}
.job span { color: var(--muted); }
.job.active {
  background: #f5f5f5;
  color: #111;
  border-color: #111;
  box-shadow: inset 3px 0 0 #111;
}
.job.active span { color: #525252; }
.delete-job {
  min-height: 30px;
  padding: 5px 9px;
  background: #fff;
  color: var(--danger);
  border: 1px solid #f0b8b2;
}
.job.active .delete-job { background: #fff; }
.result-actions { margin-top: 14px; display: flex; justify-content: flex-end; }
.empty-state { color: var(--muted); border: 1px dashed var(--line-strong); border-radius: 8px; padding: 18px; background: #fff; }
.overall-progress { margin-bottom: 16px; }
.overall-progress h3 { margin: 0 0 10px; font-size: 15px; }
.overall-progress ol {
  display: grid;
  grid-template-columns: repeat(10, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.overall-progress li {
  display: grid;
  grid-template-rows: 24px minmax(28px, auto) 14px;
  justify-items: center;
  align-items: center;
  gap: 3px;
  min-height: 76px;
  padding: 7px 5px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  text-align: center;
}
.progress-icon {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: #f5f5f5;
  color: #737373;
  font-weight: 900;
  font-size: 12px;
}
.progress-name {
  font-weight: 850;
  line-height: 1.2;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.progress-index {
  color: var(--muted);
  font-size: 10px;
  line-height: 1;
}
.overall-progress li.success { border-color: #b7e3c7; background: #f4fbf6; }
.overall-progress li.success .progress-icon { background: #e8f7ed; color: var(--success); }
.overall-progress li.running { border-color: #111; background: #f5f5f5; }
.overall-progress li.running .progress-icon {
  position: relative;
  background: #111;
  color: transparent;
  animation: none;
}
.overall-progress li.running .progress-icon::after {
  content: "";
  position: absolute;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #fff;
  top: 3px;
  left: 8px;
  transform-origin: 4px 9px;
  animation: orbit 1s infinite linear;
}
.overall-progress li.failed { border-color: #f0b8b2; background: #fff7f6; }
.overall-progress li.failed .progress-icon { background: #fff1f0; color: var(--danger); }
.overall-progress li.cancelled,
.overall-progress li.skipped { opacity: .72; }
@keyframes orbit {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.result-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.result-summary div { padding: 10px; background: #fff; border: 1px solid var(--line); border-radius: 8px; }
.result-summary span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.result-summary strong { word-break: break-all; }
.path-list { display: grid; gap: 10px; }
.path-row { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.path-label { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; font-weight: 800; }
.help-dot {
  width: 18px;
  height: 18px;
  min-height: 18px;
  padding: 0;
  border-radius: 999px;
  border: 1px solid var(--line-strong);
  background: #fff;
  color: #525252;
  font-size: 12px;
  line-height: 16px;
  box-shadow: none;
}
.help-dot:hover { background: #f5f5f5; color: #111; transform: none; box-shadow: none; }
.path-row code {
  padding: 10px;
  background: #fafafa;
  color: #111;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: auto;
  white-space: nowrap;
}
.copy-path { min-height: 34px; padding: 7px 10px; }
.terminal-frame-panel details { overflow: hidden; }
.terminal-frame-panel summary { cursor: pointer; font-weight: 900; }
.terminal-frame-panel details.disabled summary { color: var(--muted); cursor: not-allowed; }
iframe {
  width: 100%;
  height: 520px;
  margin-top: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
}
.log-panel { margin-top: 0; }
pre {
  min-height: 560px;
  max-height: 760px;
  margin: 0;
  padding: 16px;
  overflow: auto;
  background: #111;
  color: #f5f5f5;
  border-radius: 8px;
  border: 1px solid #262626;
  line-height: 1.55;
}
.muted { color: var(--muted); font-size: 13px; }
@media (max-width: 980px) {
  .hero, .terminal-panel, .panel-heading { align-items: stretch; flex-direction: column; }
  h1 { font-size: 36px; }
  .workbench, .form-panel .grid, .standard-tab-panel, .form-section, .option-matrix, .tag-tree, .result-summary, .path-row { grid-template-columns: 1fr; }
  .overall-progress ol { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .terminal-actions, .run-actions { justify-content: flex-start; }
}
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            return self.send_text(INDEX_HTML.replace("__APP_VERSION__", APP_VERSION), "text/html; charset=utf-8", set_token=True)
        if parsed.path == "/app.js":
            return self.send_text(APP_JS, "application/javascript; charset=utf-8")
        if parsed.path == "/style.css":
            return self.send_text(STYLE_CSS, "text/css; charset=utf-8")
        if parsed.path.startswith("/build-terminal"):
            return self.proxy_build_terminal("GET", parsed)
        if parsed.path == "/api/configs":
            return self.send_json({"configs": list_config_histories()})
        if parsed.path == "/api/jobs":
            return self.send_json({"jobs": [public_job(job) for job in list_jobs()]})
        if parsed.path == "/api/nho-material-release-branches":
            query = urllib.parse.parse_qs(parsed.query)
            material_number = str((query.get("material_number") or [""])[0]).strip()
            try:
                data = remote_json(
                    REMOTE_BUILD_CONSOLE_URL,
                    f"/api/nho-material-release-branches?material_number={urllib.parse.quote(material_number)}",
                )
                return self.send_json(data)
            except Exception as exc:
                return self.send_json({"error": redact_build_terminal(str(exc))}, HTTPStatus.BAD_GATEWAY)
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/log"):
            job_id = parsed.path.split("/")[3]
            query = urllib.parse.parse_qs(parsed.query)
            offset = int((query.get("offset") or ["0"])[0])
            return self.send_job_log(job_id, offset)
        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.split("/")[3]
            try:
                return self.send_json(public_job(read_job(job_id)))
            except FileNotFoundError:
                return self.send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        if parsed.path == "/api/build-terminal/status":
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return self.send_json(build_terminal_status())
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/build-terminal"):
            return self.proxy_build_terminal("POST", parsed)
        if parsed.path == "/api/jobs":
            return self.create_job()
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            job_id = parsed.path.split("/")[3]
            return self.send_json(cancel_job(job_id))
        if parsed.path in ("/api/build-terminal/start", "/api/build-terminal/stop"):
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            action = parsed.path.rsplit("/", 1)[-1]
            return self.send_json(build_terminal_action(action))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/configs/"):
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            config_id = parsed.path.split("/")[3]
            result = delete_config_history(config_id)
            status = HTTPStatus.NOT_FOUND if result.get("error") == "not_found" else HTTPStatus.OK
            return self.send_json(result, status)
        if parsed.path.startswith("/api/jobs/"):
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            job_id = parsed.path.split("/")[3]
            result = delete_job(job_id)
            status = HTTPStatus.CONFLICT if result.get("error") == "job_running" else HTTPStatus.OK
            if result.get("error") == "not_found":
                status = HTTPStatus.NOT_FOUND
            return self.send_json(result, status)
        self.send_error(HTTPStatus.NOT_FOUND)

    def create_job(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        payload, validation_error = validate_job_payload(payload)
        if validation_error:
            self.send_json({"error": validation_error}, HTTPStatus.BAD_REQUEST)
            return
        try:
            terminal = build_terminal_status()
        except Exception as exc:
            self.send_json({"error": redact_build_terminal(str(exc))}, HTTPStatus.BAD_GATEWAY)
            return
        if terminal["status"] != "running":
            self.send_json({"error": "build_terminal_unavailable", "terminal": terminal}, HTTPStatus.BAD_GATEWAY)
            return
        try:
            job = create_job(payload)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json(job)

    def send_job_log(self, job_id: str, offset: int) -> None:
        path = job_log_path(job_id)
        if not path.is_file():
            return self.send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        raw = path.read_bytes()
        offset = max(0, min(offset, len(raw)))
        chunk = filter_display_log(raw[offset:].decode("utf-8", "replace"))
        if chunk:
            chunk += "\n"
        self.send_json({"text": chunk, "next_offset": len(raw), "offset": len(raw)})

    def proxy_build_terminal(self, method: str, parsed: urllib.parse.ParseResult) -> None:
        suffix = parsed.path[len("/build-terminal") :]
        if suffix in ("", "/"):
            suffix = "/"
        target = REMOTE_BUILD_CONSOLE_URL.rstrip("/") + suffix
        if parsed.query:
            target += "?" + parsed.query
        data = None
        headers = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else b""
            content_type = self.headers.get("Content-Type")
            if content_type:
                headers["Content-Type"] = content_type
        try:
            req = urllib.request.Request(target, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                body = self.rewrite_build_terminal_asset(body, content_type)
                self.send_response(resp.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            content_type = exc.headers.get("Content-Type", "application/json")
            self.send_response(exc.code)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_text(
                "<!doctype html><meta charset='utf-8'><body>ビルド端末コンソールを表示できません。</body>",
                "text/html; charset=utf-8",
                status=HTTPStatus.BAD_GATEWAY,
            )

    def rewrite_build_terminal_asset(self, body: bytes, content_type: str) -> bytes:
        if "text/html" in content_type or "application/javascript" in content_type:
            text = body.decode("utf-8", "replace")
            text = text.replace('href="/style.css', 'href="/build-terminal/style.css')
            text = text.replace('src="/app.js', 'src="/build-terminal/app.js')
            text = text.replace("fetch('/api/", "fetch('/build-terminal/api/")
            text = text.replace("fetch(`/api/", "fetch(`/build-terminal/api/")
            text = text.replace('href="/api/', 'href="/build-terminal/api/')
            text = text.replace("url('/", "url('/build-terminal/")
            return text.encode("utf-8")
        return body

    def authorized(self) -> bool:
        header = self.headers.get("X-Management-Token") or ""
        expected = MANAGEMENT_TOKEN
        return bool(header and secrets.compare_digest(header, expected))

    def send_text(
        self,
        text: str,
        content_type: str,
        set_token: bool = False,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("Content-Length", str(len(data)))
        if set_token:
            self.send_header("Set-Cookie", f"host_console_token={MANAGEMENT_TOKEN}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    resume_unfinished_jobs()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"host standalone console listening on {HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
