#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
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
    StandaloneConfig,
    build_product_package,
    configured_output_dir,
    configured_sql_template_dir,
    configured_template_zip,
    download_remote_artifact,
    remote_json,
)


HOST = os.environ.get("HOST_STANDALONE_CONSOLE_HOST", "0.0.0.0")
PORT = int(os.environ.get("HOST_STANDALONE_CONSOLE_PORT", "8091"))
REMOTE_BUILD_CONSOLE_URL = os.environ.get("REMOTE_BUILD_CONSOLE_URL", "http://192.168.250.50:8090")
DATA_DIR = Path(os.environ.get("HOST_STANDALONE_DATA_DIR", "dist/standalone-builds"))
TOKEN_FILE = Path(os.environ.get("HOST_STANDALONE_TOKEN_FILE", DATA_DIR / "management.token"))
TERMINAL_LABELS = {
    "ja-JP": "ビルド端末",
    "zh-CN": "构建终端",
    "en-US": "build terminal",
}

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


def create_job(payload: dict[str, Any]) -> dict[str, Any]:
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
        }
        job_dir(job_id).mkdir(parents=True, exist_ok=True)
        job_log_path(job_id).write_text("", encoding="utf-8")
        JOBS[job_id] = job
        write_job(job)
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


def run_job(job_id: str) -> None:
    with LOCK:
        job = JOBS.get(job_id) or read_job(job_id)
        req = dict(job["request"])
        remote_id = job.get("remote_build_id")
    build_backend = bool(str(req.get("backend_branch") or "").strip())
    build_frontend = bool(str(req.get("frontend_release_branch") or "").strip())
    work_dir = job_dir(job_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id, status="running")
        terminal = build_terminal_status()
        if terminal["status"] != "running":
            raise RuntimeError("build_terminal_unavailable")

        if remote_id:
            append_log(job_id, f"resume_remote_build: {remote_id}")
        else:
            append_log(job_id, "build_terminal_dispatch")
            remote_payload = {
                "build_backend": build_backend,
                "build_frontend": build_frontend,
                "backend_branch": req.get("backend_branch") or "",
                "frontend_release_branch": req.get("frontend_release_branch") or "",
                "help_docs_branch": req.get("help_docs_branch") or "release_ci",
                "conf_server_host": req.get("conf_server_host") or "",
                "conf_web_port": int(req.get("conf_web_port") or 80),
                "conf_worker_processes": int(req.get("conf_worker_processes") or 1),
                "conf_worker_connections": int(req.get("conf_worker_connections") or 1024),
                "note": req.get("note") or f"standalone package {job_id}",
            }
            check_cancelled(job_id)
            remote_build = remote_json(REMOTE_BUILD_CONSOLE_URL, "/api/builds", remote_payload)
            remote_id = remote_build["id"]
            update_job(job_id, remote_build_id=remote_id)
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

        check_cancelled(job_id)
        append_log(job_id, "download_artifacts")
        package_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "package.zip", work_dir / "package.zip") if build_backend else None
        web_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "web.zip", work_dir / "web.zip") if build_frontend else None
        partial_outputs = {
            "package_zip": str(package_zip) if package_zip else "",
            "web_zip": str(web_zip) if web_zip else "",
        }
        if not (build_backend and build_frontend):
            update_job(job_id, status="success", outputs=partial_outputs)
            append_log(job_id, "selected_artifacts_done")
            return

        check_cancelled(job_id)
        append_log(job_id, "standalone_packaging")
        outputs = build_product_package(
            template_zip=configured_template_zip(),
            sql_template_dir=configured_sql_template_dir(),
            output_root=configured_output_dir(),
            package_zip=package_zip,
            web_zip=web_zip,
            version=BuildVersion(
                build_id=remote_id,
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
        )
        outputs.update(partial_outputs)
        update_job(job_id, status="success", outputs=outputs)
        append_log(job_id, "standalone_package_done")
    except JobCancelled:
        update_job(job_id, status="cancelled")
        append_log(job_id, "cancelled")
    except Exception as exc:
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
        <h1 data-i18n="title">庶務事務システム构造器</h1>
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
        <label><span data-i18n="backendBranch">バックエンドブランチ</span><select name="backend_branch" id="backend-branches"><option value=""></option></select></label>
        <label><span data-i18n="frontendBranch">フロントエンドブランチ</span><select name="frontend_release_branch" id="frontend-branches"><option value=""></option></select></label>
        <label><span data-i18n="helpBranch">ヘルプブランチ</span><input name="help_docs_branch" value="release_ci"></label>
        <label><span data-i18n="customerHost">顧客アクセスアドレス</span><input name="conf_server_host" required placeholder="192.168.70.136"></label>
        <label><span data-i18n="webPort">Web ポート</span><input name="conf_web_port" type="number" value="80" min="1" max="65535"></label>
        <label><span data-i18n="postgresHost">PostgreSQL Host</span><input name="postgresql_host" required placeholder="192.168.10.209"></label>
        <label><span data-i18n="postgresPort">PostgreSQL Port</span><input name="postgresql_port" type="number" value="5432"></label>
        <label><span data-i18n="postgresUser">PostgreSQL User</span><input name="postgresql_user" value="postgres"></label>
        <label><span data-i18n="postgresPassword">PostgreSQL Password</span><input name="postgresql_password" value="password"></label>
        <label><span data-i18n="appHostName">アプリケーションサービスホスト名</span><input name="ohr_host_address" data-i18n-placeholder="appHostPlaceholder" placeholder="顧客アクセスアドレスを使用"></label>
        <label><span data-i18n="ohrServicePort">OHR Service Port</span><input name="ohr_service_port" type="number" value="3198"></label>
      </div>
    </form>

    <section class="workbench">
      <section class="panel history-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker" data-i18n="historyKicker">履歴</p>
            <h2 data-i18n="historyTitle">構造履歴</h2>
          </div>
          <div id="jobBadge" class="badge" data-i18n="noTask">タスク未選択</div>
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
    formKicker: '構造設定',
    formTitle: '構成パラメータ',
    stopJob: '停止',
    startJob: '構造を開始',
    backendBranch: 'バックエンドブランチ',
    frontendBranch: 'フロントエンドブランチ',
    helpBranch: 'ヘルプブランチ',
    customerHost: '顧客アクセスアドレス',
    webPort: 'Web ポート',
    postgresHost: 'PostgreSQL ホスト',
    postgresPort: 'PostgreSQL ポート',
    postgresUser: 'PostgreSQL ユーザー',
    postgresPassword: 'PostgreSQL パスワード',
    appHostName: 'アプリケーションサービスホスト名',
    appHostPlaceholder: '顧客アクセスアドレスを使用',
    ohrServicePort: 'OHR サービスポート',
    historyKicker: '履歴',
    historyTitle: '構造履歴',
    resultKicker: '結果',
    resultTitle: '成果物',
    logKicker: 'ログ',
    logTitle: '実行ログ',
    terminalConsole: 'ビルド端末コンソール',
    terminalConsoleLocked: '構造開始後に表示できます',
    terminalHeartbeat: 'ビルド端末稼働中',
    autoScroll: '自動スクロール',
    selectTask: 'タスクを選択してください。',
    noTask: 'タスク未選択',
    productDir: '交付ディレクトリ',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: 'コピー',
    copied: 'コピーしました',
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
    formKicker: '打包设置',
    formTitle: '构造参数',
    stopJob: '停止',
    startJob: '开始构造',
    backendBranch: '后端分支',
    frontendBranch: '前端分支',
    helpBranch: 'Help 分支',
    customerHost: '客户访问地址',
    webPort: 'Web 端口',
    postgresHost: 'PostgreSQL 主机',
    postgresPort: 'PostgreSQL 端口',
    postgresUser: 'PostgreSQL 用户',
    postgresPassword: 'PostgreSQL 密码',
    appHostName: '应用服务主机名',
    appHostPlaceholder: '默认取客户访问地址',
    ohrServicePort: 'OHR 服务端口',
    historyKicker: '历史',
    historyTitle: '构造历史',
    resultKicker: '结果',
    resultTitle: '成果物',
    logKicker: '日志',
    logTitle: '执行日志',
    terminalConsole: '构建终端控制台',
    terminalConsoleLocked: '开始构造后可打开',
    terminalHeartbeat: '构建终端运行中',
    autoScroll: '自动滚动',
    selectTask: '请选择任务。',
    noTask: '未选择任务',
    productDir: '交付目录',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: '复制',
    copied: '已复制',
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
    formKicker: 'Build settings',
    formTitle: 'Build parameters',
    stopJob: 'Stop',
    startJob: 'Start build',
    backendBranch: 'Backend branch',
    frontendBranch: 'Frontend branch',
    helpBranch: 'Help branch',
    customerHost: 'Customer access address',
    webPort: 'Web port',
    postgresHost: 'PostgreSQL Host',
    postgresPort: 'PostgreSQL Port',
    postgresUser: 'PostgreSQL User',
    postgresPassword: 'PostgreSQL Password',
    appHostName: 'Application service host name',
    appHostPlaceholder: 'Use customer access address',
    ohrServicePort: 'OHR Service Port',
    historyKicker: 'History',
    historyTitle: 'Build history',
    resultKicker: 'Result',
    resultTitle: 'Artifacts',
    logKicker: 'Log',
    logTitle: 'Execution log',
    terminalConsole: 'Build terminal console',
    terminalConsoleLocked: 'Available after build starts',
    terminalHeartbeat: 'Build terminal active',
    autoScroll: 'Auto scroll',
    selectTask: 'Select a task.',
    noTask: 'No task selected',
    productDir: 'Delivery directory',
    standaloneZip: 'OneHrStandalone.zip',
    versionTxt: 'version.txt',
    copy: 'Copy',
    copied: 'Copied',
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
let heartbeatTick = 0;
let lastTerminalStatus = 'unknown';
const MAX_LOG_LINES = 1600;

function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N['ja-JP'][key] || key; }
function token() {
  const found = document.cookie.split('; ').find(row => row.startsWith('host_console_token='));
  return found ? decodeURIComponent(found.split('=').slice(1).join('=')) : '';
}
function authHeaders(extra = {}) { return {...extra, 'X-Management-Token': token()}; }
function fillBranchSelect(id, branches) {
  const select = document.getElementById(id);
  if (!select) return;
  const previous = select.value;
  select.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '';
  placeholder.selected = true;
  select.appendChild(placeholder);
  (branches || []).forEach(branch => {
    const option = document.createElement('option');
    option.value = branch;
    option.textContent = branch;
    select.appendChild(option);
  });
  if (previous && (branches || []).includes(previous)) {
    select.value = previous;
  }
}
async function loadBranchLists() {
  try {
    const [backend, frontend] = await Promise.all([
      fetch('/build-terminal/api/backend-branches').then(res => res.json()),
      fetch('/build-terminal/api/frontend-branches').then(res => res.json())
    ]);
    fillBranchSelect('backend-branches', backend.branches);
    fillBranchSelect('frontend-branches', frontend.branches);
  } catch (error) {
    console.warn('failed to load branch lists', error);
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
      'standalone_package_done': '製品交付パッケージの生成が完了しました',
      'cancelled': '停止しました',
      'failed': '失敗',
      '构建开始': '構築開始',
      '参数校验': 'パラメータ検証',
      '恢复前端工作区': 'フロントエンド作業区復元',
      '收集产物': '成果物収集',
      '构建成功': '構築成功',
      '构建失败': '構築失敗',
      '构建已停止': '構築を停止しました'
    },
    'en-US': {
      'build_terminal_dispatch': 'Build terminal dispatched',
      'remote_build_id': 'Build terminal ID',
      'remote_build_status': 'Build terminal status',
      'download_artifacts': 'Downloading package.zip / web.zip',
      'selected_artifacts_done': 'Selected artifacts downloaded',
      'standalone_packaging': 'Generating delivery package',
      'standalone_package_done': 'Delivery package generated',
      'cancelled': 'Stopped',
      'failed': 'Failed',
      '构建开始': 'Build started',
      '参数校验': 'Validate parameters',
      '恢复前端工作区': 'Restore frontend workspace',
      '收集产物': 'Collect artifacts',
      '构建成功': 'Build succeeded',
      '构建失败': 'Build failed',
      '构建已停止': 'Build stopped'
    }
  };
  const map = maps[lang] || {};
  let result = text || '';
  Object.entries(map).forEach(([from, to]) => { result = result.split(from).join(to); });
  return result;
}

function heartbeatLine(job) {
  if (!job || !['queued', 'running'].includes(job.status)) return '';
  const status = job.remote_build_status || job.status;
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
  renderTerminal(lastTerminalStatus);
}

function setFormLocked(locked) {
  const terminalLocked = lastTerminalStatus !== 'running';
  document.querySelectorAll('#form input, #form select, #startJob').forEach(el => { el.disabled = locked || terminalLocked; });
  document.getElementById('stopJob').disabled = !locked || !selected;
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
  setFormLocked(['queued', 'running'].includes(selectedJob && selectedJob.status));
  return data;
}

async function terminalAction(action) {
  const res = await fetch(`/api/build-terminal/${action}`, {method: 'POST', headers: authHeaders({'Content-Type': 'application/json'}), body: '{}'});
  const data = await res.json();
  renderTerminal(data.status === 'requested' ? 'unknown' : data.status);
  setTimeout(refreshTerminal, 2500);
}

document.getElementById('language').addEventListener('change', event => {
  lang = event.target.value;
  localStorage.setItem('hostConsoleLang', lang);
  applyI18n();
  refresh();
});
document.getElementById('refreshTerminal').addEventListener('click', refreshTerminal);
document.getElementById('startTerminal').addEventListener('click', () => terminalAction('start'));
document.getElementById('stopTerminal').addEventListener('click', () => terminalAction('stop'));
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

document.getElementById('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const terminal = await refreshTerminal();
  if (terminal.status !== 'running') {
    alert(t('terminalFirst'));
    return;
  }
  const payload = Object.fromEntries(new FormData(event.target).entries());
  payload.ui_language = lang;
  const res = await fetch('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const job = await res.json();
  if (job.error) {
    alert(job.error);
    return;
  }
  selected = job.id;
  logOffset = 0;
  logLines = [];
  setFormLocked(true);
  refresh();
  if (!timer) timer = setInterval(refresh, 3000);
});

async function refresh() {
  const res = await fetch('/api/jobs');
  const data = await res.json();
  const jobs = document.getElementById('jobs');
  jobs.innerHTML = '';
  if (!data.jobs.length) {
    jobs.innerHTML = `<div class="empty-state">${t('noTask')}</div>`;
    return;
  }
  data.jobs.forEach(job => {
    const btn = document.createElement('button');
    btn.className = job.id === selected ? 'job active' : 'job';
    btn.innerHTML = `<strong>${job.id}</strong><span>${job.status}${job.remote_build_id ? ' · ' + job.remote_build_id : ''}</span>`;
    btn.onclick = () => { selected = job.id; logOffset = 0; logLines = []; render(job); fetchJobLog(true); };
    jobs.appendChild(btn);
    if (job.id === selected) render(job);
  });
  if (selected) await fetchJobLog(false);
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
  document.getElementById('jobBadge').textContent = `${job.id} · ${job.status}`;
  const running = ['queued', 'running'].includes(job.status);
  setFormLocked(running);
  syncTerminalConsole(job);
  renderResult(job);
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
  return `<div class="path-row"><span>${label}</span><code>${safe}</code><button type="button" class="copy-path" data-path="${safe}">${t('copy')}</button></div>`;
}

function renderResult(job) {
  const outputs = job.outputs || {};
  const box = document.getElementById('result');
  const pathList = outputs.product_dir ? pathRow(t('productDir'), outputs.product_dir) : `
      ${pathRow('package.zip', outputs.package_zip)}
      ${pathRow('web.zip', outputs.web_zip)}
  `;
  box.innerHTML = `
    <div class="result-summary">
      <div><span>ID</span><strong>${escapeHtml(job.id)}</strong></div>
      <div><span>Status</span><strong>${escapeHtml(job.status)}</strong></div>
      <div><span>${t('remoteBuild')}</span><strong>${escapeHtml(job.remote_build_id || '-')}</strong></div>
      <div><span>${t('error')}</span><strong>${escapeHtml(job.error || '-')}</strong></div>
    </div>
    <div class="path-list">
      ${pathList}
    </div>
  `;
  box.querySelectorAll('.copy-path').forEach(btn => {
    btn.addEventListener('click', async () => {
      await navigator.clipboard.writeText(btn.dataset.path || '');
      btn.textContent = t('copied');
      setTimeout(() => { btn.textContent = t('copy'); }, 1200);
    });
  });
}

applyI18n();
refreshTerminal();
loadBranchLists();
refresh();
timer = setInterval(refresh, 5000);
"""


STYLE_CSS = """
:root {
  --ink: #111827;
  --muted: #5f6b7a;
  --line: #d9e1ea;
  --panel: rgba(255, 255, 255, 0.94);
  --accent: #176b87;
  --accent-dark: #0f3d4c;
  --danger: #b42318;
  --success: #0f7a47;
  --surface: #eef4f7;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "Noto Sans JP", "Microsoft YaHei", Arial, sans-serif;
  background:
    linear-gradient(120deg, rgba(23, 107, 135, .14), transparent 34%),
    linear-gradient(240deg, rgba(15, 122, 71, .11), transparent 30%),
    var(--surface);
  color: var(--ink);
}
.shell { max-width: 1180px; margin: 0 auto; padding: 24px 20px 38px; }
.hero {
  min-height: 168px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  padding: 28px 0 24px;
  border-bottom: 1px solid rgba(17, 24, 39, .12);
}
.eyebrow, .section-kicker {
  margin: 0 0 8px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
h1, h2 { margin: 0; letter-spacing: 0; }
h1 { font-size: 46px; line-height: 1.05; }
h2 { font-size: 21px; }
.subcopy { max-width: 720px; margin: 14px 0 0; color: var(--muted); font-size: 15px; line-height: 1.65; }
.hero-actions { display: grid; gap: 8px; min-width: 180px; }
.lang-label { color: var(--muted); font-size: 13px; font-weight: 800; }
select, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  padding: 11px 12px;
  font: inherit;
}
input::placeholder {
  color: #aeb8c6;
  font-weight: 500;
  opacity: 1;
}
input:disabled, select:disabled { background: #eef2f5; color: #7b8794; }
.terminal-panel, .panel {
  background: var(--panel);
  border: 1px solid rgba(17, 24, 39, .1);
  box-shadow: 0 16px 54px rgba(25, 42, 70, .1);
  backdrop-filter: blur(14px);
  border-radius: 8px;
}
.terminal-panel {
  margin: 20px 0;
  padding: 18px 20px;
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
  background: #9aa4b2;
}
.terminal-panel[data-status="running"] h2::before { background: var(--success); }
.terminal-panel[data-status="stopped"] h2::before { background: #d97706; }
.terminal-panel[data-status="unreachable"] h2::before,
.terminal-panel[data-status="permission_denied"] h2::before { background: var(--danger); }
#terminalHint { margin: 8px 0 0; color: var(--muted); }
.terminal-actions, .run-actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-end; }
.panel { padding: 20px; margin-bottom: 18px; }
.panel-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
.form-panel .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 7px; font-weight: 800; font-size: 13px; color: #273449; }
button {
  min-height: 40px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  padding: 9px 14px;
  font-weight: 900;
  cursor: pointer;
}
button:hover { background: var(--accent-dark); }
button:disabled { opacity: .45; cursor: not-allowed; }
.secondary { background: #e8f1f4; color: var(--accent-dark); border: 1px solid #c7dce4; }
.secondary:hover { background: #d9eaef; }
.danger, .danger-lite { background: var(--danger); }
.danger-lite { background: #fff1f0; color: var(--danger); border: 1px solid #ffd1cc; }
.danger-lite:hover { background: #ffe4e0; }
.workbench { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 18px; align-items: start; }
.jobs { display: grid; gap: 8px; max-height: 360px; overflow: auto; }
.job {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
  background: #f2f6f9;
  color: #25364a;
  border: 1px solid var(--line);
  min-height: 42px;
  font-size: 12px;
}
.job span { color: var(--muted); }
.job.active { background: var(--ink); color: #fff; }
.job.active span { color: #d8e2ef; }
.badge {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--muted);
  font-size: 13px;
  white-space: nowrap;
}
.empty-state { color: var(--muted); border: 1px dashed var(--line); border-radius: 8px; padding: 18px; }
.result-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.result-summary div { padding: 10px; background: #f5f8fb; border: 1px solid var(--line); border-radius: 8px; }
.result-summary span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.result-summary strong { word-break: break-all; }
.path-list { display: grid; gap: 10px; }
.path-row { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.path-row span { color: var(--muted); font-size: 13px; font-weight: 800; }
.path-row code { padding: 10px; background: #0d1320; color: #d8e8f6; border-radius: 8px; overflow: auto; white-space: nowrap; }
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
  background: #0d1320;
  color: #d8e8f6;
  border-radius: 8px;
  border: 1px solid #1f2c42;
  line-height: 1.55;
}
.muted { color: var(--muted); font-size: 13px; }
@media (max-width: 980px) {
  .hero, .terminal-panel, .panel-heading { align-items: stretch; flex-direction: column; }
  h1 { font-size: 36px; }
  .workbench, .form-panel .grid, .result-summary, .path-row { grid-template-columns: 1fr; }
  .terminal-actions, .run-actions { justify-content: flex-start; }
}
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            return self.send_text(INDEX_HTML, "text/html; charset=utf-8", set_token=True)
        if parsed.path == "/app.js":
            return self.send_text(APP_JS, "application/javascript; charset=utf-8")
        if parsed.path == "/style.css":
            return self.send_text(STYLE_CSS, "text/css; charset=utf-8")
        if parsed.path.startswith("/build-terminal"):
            return self.proxy_build_terminal("GET", parsed)
        if parsed.path == "/api/jobs":
            return self.send_json({"jobs": [public_job(job) for job in list_jobs()]})
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

    def create_job(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        build_backend = bool(str(payload.get("backend_branch") or "").strip())
        build_frontend = bool(str(payload.get("frontend_release_branch") or "").strip())
        if not build_backend and not build_frontend:
            self.send_json({"error": "missing build target"}, HTTPStatus.BAD_REQUEST)
            return
        required = ["conf_server_host"] if build_frontend else []
        if build_backend and build_frontend:
            required.append("postgresql_host")
        for key in required:
            if not str(payload.get(key) or "").strip():
                self.send_json({"error": f"missing {key}"}, HTTPStatus.BAD_REQUEST)
                return
        try:
            terminal = build_terminal_status()
        except Exception as exc:
            self.send_json({"error": redact_build_terminal(str(exc))}, HTTPStatus.BAD_GATEWAY)
            return
        if terminal["status"] != "running":
            self.send_json({"error": "build_terminal_unavailable", "terminal": terminal}, HTTPStatus.BAD_GATEWAY)
            return
        job = create_job(payload)
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
