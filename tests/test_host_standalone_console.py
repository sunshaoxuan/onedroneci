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


def test_host_console_renders_outputs_and_bottom_log_layout():
    assert "product_dir" in console.APP_JS
    assert "standalone_zip" in console.APP_JS
    assert "version_txt" in console.APP_JS
    assert "navigator.clipboard.writeText" in console.APP_JS
    assert ".workbench" in console.STYLE_CSS
    assert ".log-panel" in console.STYLE_CSS
    assert "min-height: 560px" in console.STYLE_CSS


def test_build_terminal_iframe_uses_host_proxy_not_direct_url():
    assert 'data-src="/build-terminal/"' in console.INDEX_HTML
    assert "/build-terminal/" in console.APP_JS or "/build-terminal/" in console.INDEX_HTML
    assert "REMOTE_BUILD_CONSOLE_URL" not in console.INDEX_HTML


def test_build_terminal_proxy_rewrites_absolute_assets():
    class Dummy(console.Handler):
        def __init__(self):
            pass

    body = b'<link href="/style.css?v=4"><script src="/app.js?v=9"></script><script>fetch(`/api/builds`);</script>'
    rewritten = Dummy().rewrite_build_terminal_asset(body, "text/html; charset=utf-8").decode("utf-8")

    assert 'href="/build-terminal/style.css?v=4"' in rewritten
    assert 'src="/build-terminal/app.js?v=9"' in rewritten
    assert "fetch(`/build-terminal/api/builds`)" in rewritten
