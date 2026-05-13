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
MANAGEMENT_TOKEN = os.environ.get("HOST_STANDALONE_MANAGEMENT_TOKEN") or secrets.token_urlsafe(32)
TERMINAL_LABELS = {
    "ja-JP": "ビルド端末",
    "zh-CN": "构建终端",
    "en-US": "build terminal",
}

JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()
CANCELLED: set[str] = set()


class JobCancelled(RuntimeError):
    pass


def now() -> int:
    return int(time.time())


def new_job_id() -> str:
    return time.strftime("%Y%m%d%H%M%S")


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
        while job_id in JOBS:
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
        JOBS[job_id] = job
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return public_job(job)


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    result = dict(job)
    result["request"] = dict(job.get("request") or {})
    return result


def append_log(job_id: str, message: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        lang = str((job.get("request") or {}).get("ui_language") or "ja-JP")
        job["log"].append(f"{time.strftime('%H:%M:%S')} {redact_build_terminal(message, lang)}")
        job["updated_at"] = now()


def update_job(job_id: str, **updates: Any) -> None:
    with LOCK:
        job = JOBS[job_id]
        job.update(updates)
        job["updated_at"] = now()


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
        for line in text.splitlines():
            if line.strip():
                append_log(job_id, line)
    with LOCK:
        JOBS[job_id]["remote_log_offset"] = int(data.get("next_offset") or data.get("offset") or offset + len(text))


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
    if state in ("off", "stopped"):
        return {"status": "stopped", "configured": True, "reachable": False}
    if state in ("running", "2"):
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
        job = JOBS.get(job_id)
        if not job:
            return {"ok": False, "error": "not_found"}
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
        req = dict(JOBS[job_id]["request"])
    work_dir = DATA_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id, status="running")
        terminal = build_terminal_status()
        if terminal["status"] != "running":
            raise RuntimeError("build_terminal_unavailable")

        append_log(job_id, "build_terminal_dispatch")
        remote_payload = {
            "build_backend": True,
            "build_frontend": True,
            "backend_branch": req["backend_branch"],
            "frontend_release_branch": req["frontend_release_branch"],
            "help_docs_branch": req.get("help_docs_branch") or "release_ci",
            "conf_server_host": req["conf_server_host"],
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
            append_log(job_id, f"remote_build_status: {status['status']}")
            time.sleep(5)

        check_cancelled(job_id)
        append_log(job_id, "download_artifacts")
        package_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "package.zip", work_dir / "package.zip")
        web_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "web.zip", work_dir / "web.zip")

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
                backend_branch=req["backend_branch"],
                frontend_branch=req["frontend_release_branch"],
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
        update_job(job_id, status="success", outputs=outputs)
        append_log(job_id, "standalone_package_done")
    except JobCancelled:
        update_job(job_id, status="cancelled")
        append_log(job_id, "cancelled")
    except Exception as exc:
        update_job(job_id, status="failed", error=redact_build_terminal(str(exc)))
        append_log(job_id, f"failed: {exc}")


INDEX_HTML = """<!doctype html>
<html lang="ja-JP">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OHR Delivery Package Console</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">OHR Delivery Package Console</p>
        <h1 data-i18n="title">OHR 製品パッケージ生成</h1>
        <p class="subcopy" data-i18n="subtitle">固定資材を宿主機に保持し、ビルド端末の成果物を組み込んだ正式な納品パッケージを生成します。</p>
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

    <section class="workspace">
      <form id="form" class="panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker" data-i18n="formKicker">パッケージ設定</p>
            <h2 data-i18n="formTitle">構成パラメータ</h2>
          </div>
          <div class="run-actions">
            <button id="stopJob" class="danger" type="button" disabled data-i18n="stopJob">停止</button>
            <button id="startJob" type="submit" data-i18n="startJob">交付包生成を開始</button>
          </div>
        </div>
        <div class="grid">
          <label><span data-i18n="backendBranch">バックエンドブランチ</span><input name="backend_branch" required placeholder="release_20260325"></label>
          <label><span data-i18n="frontendBranch">フロントエンドブランチ</span><input name="frontend_release_branch" required placeholder="release_20260325"></label>
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

      <section class="panel log-panel">
        <div class="panel-heading">
          <div>
            <p class="section-kicker" data-i18n="tasksKicker">進行状況</p>
            <h2 data-i18n="tasksTitle">タスクとログ</h2>
          </div>
          <div id="jobBadge" class="badge" data-i18n="noTask">タスク未選択</div>
        </div>
        <div id="jobs" class="jobs"></div>
        <pre id="log"></pre>
      </section>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_JS = r"""
const I18N = {
  'ja-JP': {
    title: 'OHR 製品パッケージ生成',
    subtitle: '固定資材を宿主機に保持し、ビルド端末の成果物を組み込んだ正式な納品パッケージを生成します。',
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
    formKicker: 'パッケージ設定',
    formTitle: '構成パラメータ',
    stopJob: '停止',
    startJob: '交付包生成を開始',
    backendBranch: 'バックエンドブランチ',
    frontendBranch: 'フロントエンドブランチ',
    helpBranch: 'ヘルプブランチ',
    customerHost: '顧客アクセスアドレス',
    webPort: 'Web ポート',
    postgresHost: 'PostgreSQL Host',
    postgresPort: 'PostgreSQL Port',
    postgresUser: 'PostgreSQL User',
    postgresPassword: 'PostgreSQL Password',
    appHostName: 'アプリケーションサービスホスト名',
    appHostPlaceholder: '顧客アクセスアドレスを使用',
    ohrServicePort: 'OHR Service Port',
    tasksKicker: '進行状況',
    tasksTitle: 'タスクとログ',
    noTask: 'タスク未選択',
    outputDir: '出力ディレクトリ',
    error: 'エラー',
    terminalFirst: 'ビルド端末を起動してから開始してください。',
    cancelled: '停止しました'
  },
  'zh-CN': {
    title: 'OHR 产品交付包生成',
    subtitle: '固定资源保留在宿主机，将构建终端产出的成果物组装为正式产品交付包。',
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
    startJob: '开始生成交付包',
    backendBranch: '后端分支',
    frontendBranch: '前端分支',
    helpBranch: 'Help 分支',
    customerHost: '客户访问地址',
    webPort: 'Web 端口',
    postgresHost: 'PostgreSQL Host',
    postgresPort: 'PostgreSQL Port',
    postgresUser: 'PostgreSQL User',
    postgresPassword: 'PostgreSQL Password',
    appHostName: '应用服务主机名',
    appHostPlaceholder: '默认取客户访问地址',
    ohrServicePort: 'OHR Service Port',
    tasksKicker: '执行状态',
    tasksTitle: '任务与日志',
    noTask: '未选择任务',
    outputDir: '输出目录',
    error: '错误',
    terminalFirst: '请先启动构建终端再开始。',
    cancelled: '已停止'
  },
  'en-US': {
    title: 'OHR Delivery Package Console',
    subtitle: 'Static resources stay on the host while build terminal artifacts are assembled into a formal product delivery package.',
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
    formKicker: 'Package settings',
    formTitle: 'Build parameters',
    stopJob: 'Stop',
    startJob: 'Generate delivery package',
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
    tasksKicker: 'Progress',
    tasksTitle: 'Tasks and logs',
    noTask: 'No task selected',
    outputDir: 'Output directory',
    error: 'Error',
    terminalFirst: 'Start the build terminal first.',
    cancelled: 'Stopped'
  }
};

let lang = localStorage.getItem('hostConsoleLang') || 'ja-JP';
let selected = null;
let timer = null;
let logOffset = 0;
let lastTerminalStatus = 'unknown';

function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N['ja-JP'][key] || key; }
function token() {
  const found = document.cookie.split('; ').find(row => row.startsWith('host_console_token='));
  return found ? decodeURIComponent(found.split('=').slice(1).join('=')) : '';
}
function authHeaders(extra = {}) { return {...extra, 'X-Management-Token': token()}; }

function applyI18n() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.getElementById('language').value = lang;
  renderTerminal(lastTerminalStatus);
}

function setFormLocked(locked) {
  document.querySelectorAll('#form input, #form select, #startJob').forEach(el => { el.disabled = locked; });
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
  const data = await res.json();
  renderTerminal(data.status);
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
  setFormLocked(true);
  refresh();
  if (!timer) timer = setInterval(refresh, 3000);
});

async function refresh() {
  const res = await fetch('/api/jobs');
  const data = await res.json();
  const jobs = document.getElementById('jobs');
  jobs.innerHTML = '';
  data.jobs.forEach(job => {
    const btn = document.createElement('button');
    btn.className = job.id === selected ? 'job active' : 'job';
    btn.textContent = `${job.id} · ${job.status} ${job.remote_build_id || ''}`;
    btn.onclick = () => { selected = job.id; logOffset = 0; render(job); fetchJobLog(true); };
    jobs.appendChild(btn);
    if (job.id === selected) render(job);
  });
  if (selected) await fetchJobLog(false);
}

async function fetchJobLog(reset) {
  if (!selected) return;
  if (reset) {
    logOffset = 0;
    document.getElementById('log').textContent = '';
  }
  const res = await fetch(`/api/jobs/${selected}/log?offset=${logOffset}`);
  if (!res.ok) return;
  const data = await res.json();
  logOffset = data.next_offset;
  if (data.text) {
    const log = document.getElementById('log');
    log.textContent += data.text;
    log.scrollTop = log.scrollHeight;
  }
}

function render(job) {
  document.getElementById('jobBadge').textContent = `${job.id} · ${job.status}`;
  const running = ['queued', 'running'].includes(job.status);
  setFormLocked(running);
  const log = document.getElementById('log');
  if (!log.textContent) {
    const lines = [...(job.log || [])];
    if (job.outputs && job.outputs.product_dir) lines.push(`${t('outputDir')}: ${job.outputs.product_dir}`);
    if (job.error) lines.push(`${t('error')}: ${job.error}`);
    log.textContent = lines.join('\n');
  }
}

applyI18n();
refreshTerminal();
refresh();
timer = setInterval(refresh, 5000);
"""


STYLE_CSS = """
:root {
  --ink: #111827;
  --muted: #5f6b7a;
  --line: #d9e1ea;
  --panel: rgba(255, 255, 255, 0.92);
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
    linear-gradient(120deg, rgba(23, 107, 135, .16), transparent 36%),
    linear-gradient(240deg, rgba(15, 122, 71, .12), transparent 32%),
    var(--surface);
  color: var(--ink);
}
.shell { max-width: 1240px; margin: 0 auto; padding: 28px 24px 42px; }
.hero {
  min-height: 210px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
  padding: 34px 0 28px;
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
h1 { font-size: 54px; line-height: 1.03; }
h2 { font-size: 22px; }
.subcopy { max-width: 690px; margin: 16px 0 0; color: var(--muted); font-size: 16px; line-height: 1.7; }
.hero-actions { display: grid; gap: 8px; min-width: 190px; }
.lang-label { color: var(--muted); font-size: 13px; font-weight: 800; }
select, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--ink);
  padding: 12px 13px;
  font: inherit;
}
input:disabled, select:disabled { background: #eef2f5; color: #7b8794; }
.terminal-panel, .panel {
  background: var(--panel);
  border: 1px solid rgba(17, 24, 39, .1);
  box-shadow: 0 20px 70px rgba(25, 42, 70, .12);
  backdrop-filter: blur(14px);
  border-radius: 8px;
}
.terminal-panel {
  margin: 24px 0;
  padding: 22px;
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
.workspace { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(420px, .92fr); gap: 20px; align-items: start; }
.panel { padding: 22px; }
.panel-heading { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
label { display: grid; gap: 7px; font-weight: 800; font-size: 13px; color: #273449; }
button {
  min-height: 42px;
  border: 0;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  padding: 10px 15px;
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
.jobs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.job {
  background: #f2f6f9;
  color: #25364a;
  border: 1px solid var(--line);
  min-height: 36px;
  font-size: 12px;
}
.job.active { background: var(--ink); color: #fff; }
.badge {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--muted);
  font-size: 13px;
  white-space: nowrap;
}
pre {
  min-height: 480px;
  max-height: 680px;
  margin: 0;
  padding: 16px;
  overflow: auto;
  background: #0d1320;
  color: #d8e8f6;
  border-radius: 8px;
  border: 1px solid #1f2c42;
  line-height: 1.55;
}
@media (max-width: 980px) {
  .hero, .terminal-panel, .panel-heading { align-items: stretch; flex-direction: column; }
  h1 { font-size: 40px; }
  .workspace, .grid { grid-template-columns: 1fr; }
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
        if parsed.path == "/api/jobs":
            with LOCK:
                jobs = [public_job(job) for job in sorted(JOBS.values(), key=lambda item: item["created_at"], reverse=True)]
            return self.send_json({"jobs": jobs})
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/log"):
            job_id = parsed.path.split("/")[3]
            query = urllib.parse.parse_qs(parsed.query)
            offset = int((query.get("offset") or ["0"])[0])
            return self.send_job_log(job_id, offset)
        if parsed.path == "/api/build-terminal/status":
            if not self.authorized():
                return self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return self.send_json(build_terminal_status())
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
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
        for key in ("backend_branch", "frontend_release_branch", "conf_server_host", "postgresql_host"):
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
        with LOCK:
            job = JOBS.get(job_id)
            if not job:
                return self.send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            text = "\n".join(job.get("log") or [])
            if text:
                text += "\n"
        chunk = text[offset:]
        self.send_json({"text": chunk, "next_offset": offset + len(chunk)})

    def authorized(self) -> bool:
        header = self.headers.get("X-Management-Token") or ""
        expected = MANAGEMENT_TOKEN
        return bool(header and secrets.compare_digest(header, expected))

    def send_text(self, text: str, content_type: str, set_token: bool = False) -> None:
        data = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
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
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"host standalone console listening on {HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
