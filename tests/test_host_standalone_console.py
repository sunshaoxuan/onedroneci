from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import host_standalone_console as console


@dataclass(frozen=True)
class FakeSettings:
    vm_host: str = "build-host.example"
    ssh_user: str | None = None
    ssh_port: int = 22
    hyperv_vm_name: str | None = None


def test_default_host_console_bind_is_fixed():
    assert console.HOST == "0.0.0.0"
    assert console.PORT == 8091


def test_start_script_stops_process_occupying_fixed_port():
    script = Path("scripts/start_host_standalone_console.ps1").read_text(encoding="utf-8")
    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in script
    assert "Stop-Process -Id $Owner -Force" in script
    assert "HOST_STANDALONE_CONSOLE_HOST" in script
    assert "0.0.0.0" in script
    assert "8091" in script


def test_build_terminal_status_is_safe_when_vm_name_is_missing(monkeypatch):
    monkeypatch.setattr(console.Settings, "from_env", classmethod(lambda cls: FakeSettings()))
    monkeypatch.setattr(console, "is_remote_console_reachable", lambda: False)

    assert console.build_terminal_status() == {
        "status": "unconfigured",
        "configured": False,
        "reachable": False,
    }


def test_build_terminal_status_reports_stopped_when_configured_vm_is_off(monkeypatch):
    monkeypatch.setattr(
        console.Settings,
        "from_env",
        classmethod(lambda cls: FakeSettings(hyperv_vm_name="PHRCI")),
    )
    monkeypatch.setattr(console, "is_remote_console_reachable", lambda: False)
    monkeypatch.setattr(console.hyperv_host, "vm_state", lambda name: ({"Name": name, "State": "Off"}, ""))

    assert console.build_terminal_status() == {
        "status": "stopped",
        "configured": True,
        "reachable": False,
    }

    monkeypatch.setattr(console.hyperv_host, "vm_state", lambda name: ({"Name": name, "State": 3}, ""))
    assert console.build_terminal_status()["status"] == "stopped"


def test_management_token_is_persisted_between_restarts(tmp_path, monkeypatch):
    token_file = tmp_path / "management.token"
    monkeypatch.delenv("HOST_STANDALONE_MANAGEMENT_TOKEN", raising=False)
    monkeypatch.setattr(console, "TOKEN_FILE", token_file)

    first = console.load_management_token()
    second = console.load_management_token()

    assert first == second
    assert token_file.read_text(encoding="utf-8") == first


def test_build_terminal_action_does_not_accept_page_vm_name(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        console.Settings,
        "from_env",
        classmethod(lambda cls: FakeSettings(hyperv_vm_name="OnlyAllowedVm")),
    )
    monkeypatch.setattr(console.hyperv_host, "vm_action", lambda name, action: (calls.append((name, action)) or ({}, "")))

    result = console.build_terminal_action("start")

    assert result["ok"] is True
    assert calls == [("OnlyAllowedVm", "start")]
    assert console.build_terminal_action("restart") == {"status": "invalid_action", "ok": False}


def test_build_terminal_action_reports_permission_error(monkeypatch):
    monkeypatch.setattr(
        console.Settings,
        "from_env",
        classmethod(lambda cls: FakeSettings(hyperv_vm_name="OnlyAllowedVm")),
    )
    monkeypatch.setattr(console.hyperv_host, "vm_action", lambda name, action: (None, "Access is denied"))

    result = console.build_terminal_action("stop")

    assert result["ok"] is False
    assert result["status"] == "permission_denied"


def test_page_assets_do_not_expose_build_terminal_address():
    assert "192.168.250.50" not in console.INDEX_HTML
    assert "192.168.250.50" not in console.APP_JS
    assert "250.50" not in console.INDEX_HTML
    assert "250.50" not in console.APP_JS


def test_i18n_contains_terminal_controls_and_statuses():
    for lang in ("ja-JP", "zh-CN", "en-US"):
        assert f"'{lang}'" in console.APP_JS
    for key in (
        "terminalRunning",
        "terminalStopped",
        "terminalUnreachable",
        "terminalPermissionDenied",
        "terminalUnconfigured",
        "terminalHeartbeat",
        "startTerminal",
        "stopTerminal",
        "refreshStatus",
    ):
        assert key in console.APP_JS


def test_host_console_localizes_database_and_service_labels():
    assert "PostgreSQL ホスト" in console.APP_JS
    assert "PostgreSQL ポート" in console.APP_JS
    assert "PostgreSQL ユーザー" in console.APP_JS
    assert "PostgreSQL パスワード" in console.APP_JS
    assert "OHR サービスポート" in console.APP_JS
    assert "PostgreSQL 主机" in console.APP_JS
    assert "OHR 服务端口" in console.APP_JS


def test_host_console_uses_build_terminal_branch_lists_via_proxy():
    assert 'name="backend_branch" id="backend-branches"' in console.INDEX_HTML
    assert 'name="frontend_release_branch" id="frontend-branches"' in console.INDEX_HTML
    assert 'name="backend_branch" id="backend-branches" required' not in console.INDEX_HTML
    assert 'name="frontend_release_branch" id="frontend-branches" required' not in console.INDEX_HTML
    assert 'id="backend-branches"' in console.INDEX_HTML
    assert 'id="frontend-branches"' in console.INDEX_HTML
    assert "/build-terminal/api/backend-branches" in console.APP_JS
    assert "/build-terminal/api/frontend-branches" in console.APP_JS
    assert "fillBranchSelect('backend-branches'" in console.APP_JS
    assert "fillBranchSelect('frontend-branches'" in console.APP_JS
    assert "if (data.status === 'running') loadBranchLists();" in console.APP_JS
    assert "select.value = preferred" not in console.APP_JS


def test_placeholder_text_is_visually_subtle():
    assert "input::placeholder" in console.STYLE_CSS
    assert "color: #aeb8c6" in console.STYLE_CSS
    assert "font-weight: 500" in console.STYLE_CSS


def test_console_uses_commercial_delivery_package_naming():
    assert "庶務事務システム构造器" in console.INDEX_HTML
    assert "庶务事务系统构造器" in console.APP_JS
    assert "Shomu Jimu System Builder" in console.APP_JS
    assert "最终安装包" not in console.APP_JS
    assert "最終インストールパッケージ" not in console.APP_JS


def test_create_job_persists_metadata_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    monkeypatch.setattr(console, "run_job", lambda job_id: None)
    console.JOBS.clear()

    job = console.create_job(
        {
            "backend_branch": "release_back",
            "frontend_release_branch": "release_front",
            "conf_server_host": "example.local",
            "postgresql_host": "db.local",
            "ui_language": "zh-CN",
        }
    )
    console.append_log(job["id"], "hello")

    assert (tmp_path / job["id"] / "metadata.json").is_file()
    assert (tmp_path / job["id"] / "job.log").read_text(encoding="utf-8").strip().endswith("hello")
    console.JOBS.clear()
    jobs = console.list_jobs()
    assert jobs[0]["id"] == job["id"]
    assert jobs[0]["request"]["backend_branch"] == "release_back"
    assert not list((tmp_path / job["id"]).glob("*.tmp"))


def test_batch_log_write_keeps_metadata_small(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    monkeypatch.setattr(console, "run_job", lambda job_id: None)
    console.JOBS.clear()
    job = console.create_job(
        {
            "backend_branch": "release_back",
            "frontend_release_branch": "release_front",
            "conf_server_host": "example.local",
            "postgresql_host": "db.local",
        }
    )

    console.append_log_lines(job["id"], [f"line-{idx}" for idx in range(250)])

    stored = console.read_job(job["id"])
    assert len(stored["log"]) == 200
    assert stored["log"][0].endswith("line-50")
    assert "line-0" in (tmp_path / job["id"] / "job.log").read_text(encoding="utf-8")


def test_resume_unfinished_jobs_restarts_monitor_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    console.JOBS.clear()
    started: list[tuple[object, tuple[object, ...]]] = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            started.append((target, args))

        def start(self):
            return None

    job_id = "20260514000102"
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "metadata.json").write_text(
        console.json.dumps(
            {
                "id": job_id,
                "status": "running",
                "created_at": 1,
                "updated_at": 1,
                "remote_build_id": "20260514000101",
                "remote_log_offset": 10,
                "request": {"backend_branch": "b", "frontend_release_branch": "f"},
                "log": [],
                "outputs": {},
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "job.log").write_text("", encoding="utf-8")
    monkeypatch.setattr(console.threading, "Thread", FakeThread)

    console.resume_unfinished_jobs()

    assert started == [(console.run_job, (job_id,))]


def test_host_console_renders_outputs_and_bottom_log_layout():
    assert "product_dir" in console.APP_JS
    assert "outputs.package_zip" in console.APP_JS
    assert "outputs.web_zip" in console.APP_JS
    assert "const pathList = outputs.product_dir ? pathRow(t('productDir'), outputs.product_dir)" in console.APP_JS
    assert "${pathRow(t('standaloneZip'), outputs.standalone_zip)}" not in console.APP_JS
    assert "${pathRow(t('versionTxt'), outputs.version_txt)}" not in console.APP_JS
    assert "async function copyText(text)" in console.APP_JS
    assert "navigator.clipboard.writeText" in console.APP_JS
    assert "document.execCommand('copy')" in console.APP_JS
    assert "copyFailed" in console.APP_JS
    assert ".workbench" in console.STYLE_CSS
    assert ".log-panel" in console.STYLE_CSS
    assert "min-height: 560px" in console.STYLE_CSS


def test_frontend_only_job_builds_only_web_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    console.JOBS.clear()
    job_id = "20260514000103"
    job = {
        "id": job_id,
        "status": "queued",
        "created_at": 1,
        "updated_at": 1,
        "remote_build_id": None,
        "remote_log_offset": 0,
        "request": {
            "backend_branch": "",
            "frontend_release_branch": "release_front",
            "help_docs_branch": "release_ci",
            "conf_server_host": "customer.local",
        },
        "log": [],
        "outputs": {},
    }
    console.job_dir(job_id).mkdir(parents=True)
    console.job_log_path(job_id).write_text("", encoding="utf-8")
    console.write_job(job)
    console.JOBS[job_id] = job
    payloads: list[dict] = []

    def fake_remote_json(base, path, payload=None):
        if path == "/api/builds":
            payloads.append(payload)
            return {"id": "remote-web"}
        if path == "/api/builds/remote-web":
            return {"status": "success"}
        if path.endswith("/log?offset=0"):
            return {"text": "", "offset": 0}
        return {"text": "", "offset": 0}

    def fake_download(base, build_id, name, destination):
        destination.write_bytes(name.encode("utf-8"))
        return destination

    monkeypatch.setattr(console, "build_terminal_status", lambda: {"status": "running"})
    monkeypatch.setattr(console, "remote_json", fake_remote_json)
    monkeypatch.setattr(console, "download_remote_artifact", fake_download)
    monkeypatch.setattr(console, "build_product_package", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not package")))

    console.run_job(job_id)

    stored = console.read_job(job_id)
    assert stored["status"] == "success"
    assert stored["outputs"]["web_zip"].endswith("web.zip")
    assert stored["outputs"]["package_zip"] == ""
    assert payloads[0]["build_backend"] is False
    assert payloads[0]["build_frontend"] is True


def test_running_status_uses_single_animated_heartbeat_not_log_spam():
    source = Path("host_standalone_console.py").read_text(encoding="utf-8")
    assert "remote_build_status=status[\"status\"]" in source
    assert "append_log(job_id, f\"remote_build_status" not in source
    assert "function heartbeatLine(job)" in console.APP_JS
    assert "const phase = heartbeatTick % 72" in console.APP_JS
    assert "const indent = Math.floor(phase / 6)" in console.APP_JS
    assert "'.'.repeat(dots)" in console.APP_JS
    assert "logLines.join('\\n')" in console.APP_JS
    assert "const MAX_LOG_LINES = 1600" in console.APP_JS
    assert "logLines = logLines.slice(logLines.length - MAX_LOG_LINES)" in console.APP_JS
    assert "shouldStickToBottom" in console.APP_JS
    assert console.filter_display_log("a\nremote_build_status: running\nb") == "a\nb"


def test_build_terminal_iframe_uses_host_proxy_not_direct_url():
    assert 'data-src="/build-terminal/"' in console.INDEX_HTML
    assert "/build-terminal/" in console.APP_JS or "/build-terminal/" in console.INDEX_HTML
    assert "REMOTE_BUILD_CONSOLE_URL" not in console.INDEX_HTML


def test_embedded_build_terminal_unlocks_only_after_remote_build_starts():
    assert "terminalConsoleLocked" in console.APP_JS
    assert "frame.dataset.ready" in console.APP_JS
    assert "event.target.open = false" in console.APP_JS
    assert "embedded=1&build_id=" in console.APP_JS
    assert "job.remote_build_id" in console.APP_JS
    assert "function unloadTerminalFrame()" in console.APP_JS
    assert "frame.cloneNode(false)" in console.APP_JS
    assert "frame.replaceWith(replacement)" in console.APP_JS


def test_form_is_locked_unless_build_terminal_is_running():
    assert "const terminalLocked = lastTerminalStatus !== 'running'" in console.APP_JS
    assert "el.disabled = locked || terminalLocked" in console.APP_JS
    assert "if (!res.ok)" in console.APP_JS


def test_build_terminal_proxy_rewrites_absolute_assets():
    class Dummy(console.Handler):
        def __init__(self):
            pass

    body = b'<link href="/style.css?v=4"><script src="/app.js?v=9"></script><script>fetch(`/api/builds`);</script>'
    rewritten = Dummy().rewrite_build_terminal_asset(body, "text/html; charset=utf-8").decode("utf-8")

    assert 'href="/build-terminal/style.css?v=4"' in rewritten
    assert 'src="/build-terminal/app.js?v=9"' in rewritten
    assert "fetch(`/build-terminal/api/builds`)" in rewritten
