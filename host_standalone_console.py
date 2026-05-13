#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

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
JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()


def now() -> int:
    return int(time.time())


def new_job_id() -> str:
    return time.strftime("%Y%m%d%H%M%S")


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
            "request": payload,
            "log": [],
            "outputs": {},
        }
        JOBS[job_id] = job
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
    return job


def append_log(job_id: str, message: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        job["log"].append(f"{time.strftime('%H:%M:%S')} {message}")
        job["updated_at"] = now()


def update_job(job_id: str, **updates: Any) -> None:
    with LOCK:
        job = JOBS[job_id]
        job.update(updates)
        job["updated_at"] = now()


def run_job(job_id: str) -> None:
    job = JOBS[job_id]
    req = job["request"]
    work_dir = DATA_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        update_job(job_id, status="running")
        append_log(job_id, "触发 250.50 direct 构建")
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
        remote_build = remote_json(REMOTE_BUILD_CONSOLE_URL, "/api/builds", remote_payload)
        remote_id = remote_build["id"]
        update_job(job_id, remote_build_id=remote_id)
        append_log(job_id, f"远端构建编号：{remote_id}")

        while True:
            status = remote_json(REMOTE_BUILD_CONSOLE_URL, f"/api/builds/{remote_id}")
            if status["status"] in ("success", "failed", "cancelled"):
                if status["status"] != "success":
                    raise RuntimeError(f"远端构建未成功：{status['status']}")
                break
            append_log(job_id, f"远端构建状态：{status['status']}")
            time.sleep(10)

        append_log(job_id, "下载 package.zip / web.zip")
        package_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "package.zip", work_dir / "package.zip")
        web_zip = download_remote_artifact(REMOTE_BUILD_CONSOLE_URL, remote_id, "web.zip", work_dir / "web.zip")

        append_log(job_id, "宿主机二次打包 OneHrStandalone.zip")
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
        append_log(job_id, "最终安装包生成完成")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_log(job_id, f"失败：{exc}")


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OHR 最终安装包</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main>
    <section class="card">
      <h1>最终安装包打包</h1>
      <p>宿主机负责保存固定外壳，250.50 只生成 package.zip 与 web.zip。</p>
      <form id="form">
        <div class="grid">
          <label>后端分支 <input name="backend_branch" required placeholder="release_20260325"></label>
          <label>前端分支 <input name="frontend_release_branch" required placeholder="release_20260325"></label>
          <label>Help 分支 <input name="help_docs_branch" value="release_ci"></label>
          <label>客户访问地址 <input name="conf_server_host" required placeholder="192.168.70.136"></label>
          <label>Web 端口 <input name="conf_web_port" type="number" value="80" min="1" max="65535"></label>
          <label>PostgreSQL Host <input name="postgresql_host" required placeholder="192.168.10.209"></label>
          <label>PostgreSQL Port <input name="postgresql_port" type="number" value="5432"></label>
          <label>PostgreSQL User <input name="postgresql_user" value="postgres"></label>
          <label>PostgreSQL Password <input name="postgresql_password" value="password"></label>
          <label>应用服务主机名 <input name="ohr_host_address" placeholder="默认取客户访问地址"></label>
          <label>OHR Service Port <input name="ohr_service_port" type="number" value="3198"></label>
        </div>
        <button type="submit">开始最终打包</button>
      </form>
    </section>
    <section class="card">
      <h2>任务</h2>
      <div id="jobs"></div>
      <pre id="log"></pre>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


APP_JS = r"""
let selected = null;
let timer = null;
document.getElementById('form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target).entries());
  const res = await fetch('/api/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  const job = await res.json();
  selected = job.id;
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
    btn.textContent = `${job.id} ${job.status} ${job.remote_build_id || ''}`;
    btn.onclick = () => { selected = job.id; render(job); };
    jobs.appendChild(btn);
    if (job.id === selected) render(job);
  });
}
function render(job) {
  const lines = [...(job.log || [])];
  if (job.outputs && job.outputs.product_dir) lines.push(`输出目录: ${job.outputs.product_dir}`);
  if (job.error) lines.push(`错误: ${job.error}`);
  document.getElementById('log').textContent = lines.join('\n');
}
refresh();
timer = setInterval(refresh, 5000);
"""


STYLE_CSS = """
body { margin: 0; font-family: Arial, sans-serif; background: #eef3f8; color: #172033; }
main { max-width: 1180px; margin: 32px auto; padding: 0 20px; }
.card { background: #fff; border: 1px solid #d8e1ee; border-radius: 8px; padding: 22px; margin-bottom: 18px; }
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 6px; font-weight: 700; }
input { padding: 10px 12px; border: 1px solid #c9d5e7; border-radius: 8px; }
button { margin: 14px 8px 0 0; padding: 10px 14px; border: 0; border-radius: 8px; background: #2563eb; color: #fff; font-weight: 800; cursor: pointer; }
pre { min-height: 220px; background: #101827; color: #e5eefc; padding: 14px; border-radius: 8px; overflow: auto; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            return self.send_text(INDEX_HTML, "text/html; charset=utf-8")
        if parsed.path == "/app.js":
            return self.send_text(APP_JS, "application/javascript; charset=utf-8")
        if parsed.path == "/style.css":
            return self.send_text(STYLE_CSS, "text/css; charset=utf-8")
        if parsed.path == "/api/jobs":
            with LOCK:
                jobs = sorted(JOBS.values(), key=lambda item: item["created_at"], reverse=True)
            return self.send_json({"jobs": jobs})
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/jobs":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        for key in ("backend_branch", "frontend_release_branch", "conf_server_host", "postgresql_host"):
            if not str(payload.get(key) or "").strip():
                self.send_json({"error": f"missing {key}"}, HTTPStatus.BAD_REQUEST)
                return
        job = create_job(payload)
        self.send_json(job)

    def send_text(self, text: str, content_type: str) -> None:
        data = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"host standalone console listening on http://{HOST}:{PORT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
