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


def test_host_console_displays_app_version():
    assert console.APP_VERSION == "0.3.50"
    assert "v__APP_VERSION__" in console.INDEX_HTML
    assert ".app-version" in console.STYLE_CSS


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


def test_build_terminal_status_includes_remote_resources_when_reachable(monkeypatch):
    monkeypatch.setattr(console.Settings, "from_env", classmethod(lambda cls: FakeSettings(hyperv_vm_name="PHRCI")))
    monkeypatch.setattr(console, "is_remote_console_reachable", lambda: True)
    monkeypatch.setattr(
        console,
        "remote_system_resources",
        lambda: {"cpu_count": 8, "memory_available_bytes": 16, "disk_free_bytes": 32},
    )

    assert console.build_terminal_status() == {
        "status": "running",
        "configured": True,
        "reachable": True,
        "resources": {"cpu_count": 8, "memory_available_bytes": 16, "disk_free_bytes": 32},
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
        "terminalCpu",
        "terminalMemory",
        "terminalDisk",
        "startTerminal",
        "stopTerminal",
        "stopTerminalConfirm",
        "stopTerminalConfirmFailed",
        "refreshStatus",
    ):
        assert key in console.APP_JS


def test_terminal_panel_shows_resource_metrics_and_polls_while_building():
    assert 'id="terminalMetrics"' in console.INDEX_HTML
    assert 'id="terminalCpu"' in console.INDEX_HTML
    assert 'id="terminalMemory"' in console.INDEX_HTML
    assert 'id="terminalDisk"' in console.INDEX_HTML
    assert "function renderTerminalResources(resources)" in console.APP_JS
    assert "renderTerminalResources(data.resources)" in console.APP_JS
    assert "(activeBuild || shouldPoll) ? 10000 : 300000" in console.APP_JS
    assert "setInterval(refreshTerminal, nextInterval)" in console.APP_JS
    assert "syncTerminalResourceTimer(false);" in console.APP_JS
    assert "clearInterval(terminalResourceTimer)" in console.APP_JS
    assert ".terminal-metrics" in console.STYLE_CSS


def test_stop_build_terminal_requires_shutdown_keyword():
    assert "window.prompt(t('stopTerminalConfirm'), '')" in console.APP_JS
    assert ".trim().toUpperCase() !== 'SHUTDOWN'" in console.APP_JS
    assert "return;" in console.APP_JS


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
    assert 'id="backend-branches-toggle"' in console.INDEX_HTML
    assert 'id="frontend-branches-toggle"' in console.INDEX_HTML
    assert '<select name="backend_branch"' not in console.INDEX_HTML
    assert '<select name="frontend_release_branch"' not in console.INDEX_HTML
    assert 'id="backend-branches"' in console.INDEX_HTML
    assert 'id="frontend-branches"' in console.INDEX_HTML
    assert "/build-terminal/api/backend-branches" in console.APP_JS
    assert "/build-terminal/api/frontend-branches" in console.APP_JS
    assert "fillBranchSelect('backend-branches'" in console.APP_JS
    assert "fillBranchSelect('frontend-branches'" in console.APP_JS
    assert "toggleComboMenu" in console.APP_JS
    assert "filterComboMenu" in console.APP_JS
    assert "text.includes(keyword)" in console.APP_JS
    assert "comboNoMatches" in console.APP_JS
    assert "branchListRequestSeq" in console.APP_JS
    assert "getProductVariant() !== expectedVariant" in console.APP_JS
    assert "clearBranchInputs()" in console.APP_JS
    assert "/api/nho-material-release-branches" in console.APP_JS
    assert "/api/standard-material-release-branches" in console.APP_JS
    assert "loadMaterialReleaseBranches" in console.APP_JS
    assert "event.key !== 'Enter'" in console.APP_JS
    assert "event.preventDefault()" in console.APP_JS
    assert "chooseComboItem(firstVisible)" in console.APP_JS
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
    assert "organisation_name" in console.INDEX_HTML
    assert "organisation_dstart" in console.INDEX_HTML
    assert "conf_enable_https" in console.INDEX_HTML
    assert "enableHttps" in console.APP_JS
    assert "payload.conf_enable_https" in console.APP_JS
    assert "el.type === 'checkbox'" in console.APP_JS
    assert "firstDayOfCurrentMonth" in console.APP_JS


def test_create_job_persists_metadata_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    monkeypatch.setattr(console, "run_job", lambda job_id: None)
    console.JOBS.clear()

    job = console.create_job(
        {
            "material_number": "20260520",
            "backend_branch": "release_back",
            "frontend_release_branch": "release_front",
            "conf_server_host": "example.local",
            "postgresql_host": "db.local",
            "organisation_name": "Example Org",
            "ui_language": "zh-CN",
        }
    )
    console.append_log(job["id"], "hello")

    stored = console.read_job(job["id"])
    assert [step["id"] for step in stored["progress"]] == console.HOST_PROGRESS_STEPS
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
            "material_number": "20260520",
            "backend_branch": "release_back",
            "frontend_release_branch": "release_front",
            "conf_server_host": "example.local",
            "postgresql_host": "db.local",
            "organisation_name": "Example Org",
        }
    )

    console.append_log_lines(job["id"], [f"line-{idx}" for idx in range(250)])

    stored = console.read_job(job["id"])
    assert len(stored["log"]) == 200
    assert stored["log"][0].endswith("line-50")
    assert "line-0" in (tmp_path / job["id"] / "job.log").read_text(encoding="utf-8")


def test_material_number_is_required_for_standard_and_nho_jobs():
    for product_variant in ("standard", "nho"):
        payload, error = console.validate_job_payload(
            {
                "product_variant": product_variant,
                "backend_branch": "release_back",
                "frontend_release_branch": "",
                "material_number": " ",
            }
        )
        assert error == "missing material_number"

        payload, error = console.validate_job_payload(
            {
                "product_variant": product_variant,
                "backend_branch": "release_back",
                "frontend_release_branch": "",
                "material_number": "20260520",
            }
        )
        assert error is None
        assert payload["product_variant"] == product_variant


def test_delete_finished_job_removes_host_and_remote_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path / "jobs")
    monkeypatch.setattr(console, "JOBS", {})
    monkeypatch.setattr(console, "CANCELLED", set())
    output_root = tmp_path / "dist"
    monkeypatch.setattr(console, "configured_output_dir", lambda: output_root)
    remote_deleted: list[str] = []
    monkeypatch.setattr(console, "remote_delete", lambda path: remote_deleted.append(path) or {"ok": True})

    job_id = "20260514111111"
    product_dir = output_root / job_id / "製品"
    product_dir.mkdir(parents=True)
    (product_dir / "OneHrStandalone.zip").write_text("zip", encoding="utf-8")
    job_dir = console.job_dir(job_id)
    job_dir.mkdir(parents=True)
    (job_dir / "package.zip").write_text("pkg", encoding="utf-8")
    console.write_job(
        {
            "id": job_id,
            "status": "success",
            "created_at": 1,
            "updated_at": 1,
            "remote_build_id": "remote-1",
            "request": {},
            "outputs": {"product_dir": str(product_dir)},
        }
    )

    result = console.delete_job(job_id)

    assert result["ok"] is True
    assert remote_deleted == ["/api/builds/remote-1"]
    assert not job_dir.exists()
    assert not (output_root / job_id).exists()


def test_delete_running_job_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    monkeypatch.setattr(console, "JOBS", {})
    job_id = "20260514111112"
    console.write_job({"id": job_id, "status": "running", "created_at": 1, "updated_at": 1, "request": {}})

    assert console.delete_job(job_id) == {"ok": False, "error": "job_running"}
    assert console.job_metadata_path(job_id).is_file()


def test_delete_failed_job_removes_partial_remote_id_output_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path / "jobs")
    monkeypatch.setattr(console, "JOBS", {})
    monkeypatch.setattr(console, "CANCELLED", set())
    output_root = tmp_path / "dist"
    monkeypatch.setattr(console, "configured_output_dir", lambda: output_root)
    monkeypatch.setattr(console, "remote_delete", lambda path: {"ok": True})

    job_id = "20260514111113"
    remote_id = "20260514100855"
    partial_dir = output_root / remote_id / "製品"
    partial_dir.mkdir(parents=True)
    (partial_dir / "partial.txt").write_text("partial", encoding="utf-8")
    console.write_job(
        {
            "id": job_id,
            "status": "failed",
            "created_at": 1,
            "updated_at": 1,
            "remote_build_id": remote_id,
            "request": {},
            "outputs": {},
        }
    )

    assert console.delete_job(job_id)["ok"] is True
    assert not (output_root / remote_id).exists()


def test_progress_helpers_update_and_fail_active_step(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "DATA_DIR", tmp_path)
    monkeypatch.setattr(console, "JOBS", {})
    job_id = "20260514111114"
    console.write_job(
        {
            "id": job_id,
            "status": "running",
            "created_at": 1,
            "updated_at": 1,
            "request": {},
            "progress": console.make_progress(),
        }
    )

    console.update_progress(job_id, "terminal_build", "running")
    stored = console.read_job(job_id)
    step = next(item for item in stored["progress"] if item["id"] == "terminal_build")
    assert step["status"] == "running"
    assert step["started_at"] is not None

    console.fail_active_progress(job_id)
    stored = console.read_job(job_id)
    step = next(item for item in stored["progress"] if item["id"] == "terminal_build")
    assert step["status"] == "failed"
    assert step["finished_at"] is not None


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
    assert "function renderProgress(job)" in console.APP_JS
    assert "function renderResultIfChanged(job)" in console.APP_JS
    assert "function fillFormFromJob(job)" in console.APP_JS
    assert "let mode = 'create'" in console.APP_JS
    assert "function enterCreateMode()" in console.APP_JS
    assert "function markSelectedJobRow(jobId)" in console.APP_JS
    assert "btn.dataset.jobId = job.id" in console.APP_JS
    assert "markSelectedJobRow(job.id)" in console.APP_JS
    assert "window.requestAnimationFrame(() =>" in console.APP_JS
    assert "mode = 'active'" in console.APP_JS
    assert "mode = ['queued', 'running'].includes(job.status) ? 'active' : 'view'" in console.APP_JS
    assert "if (!selected && data.jobs.length)" not in console.APP_JS
    assert "const activeJob = visibleJobs.find(job => ['queued', 'running'].includes(job.status))" in console.APP_JS
    assert "if (activeJob && (mode !== 'active' || selected !== activeJob.id))" in console.APP_JS
    assert "mode === 'create' && !activeJob" in console.APP_JS
    assert "if (mode !== 'create' && lastFilledJobId !== job.id)" in console.APP_JS
    assert "newBuildReady" in console.APP_JS
    assert "id=\"newJobMode\"" in console.INDEX_HTML
    assert "jobBadge" not in console.APP_JS
    assert "id=\"jobBadge\"" not in console.INDEX_HTML
    assert ".badge" not in console.STYLE_CSS
    assert "function jobMetaLine(job)" in console.APP_JS
    assert "hostTaskId" in console.APP_JS
    assert "statusLabel" in console.APP_JS
    assert "lastRenderedResultSignature" in console.APP_JS
    assert "overall-progress" in console.APP_JS
    assert "function visibleProgressSteps(job)" in console.APP_JS
    assert "product_variant) || 'standard'" in console.APP_JS
    assert "['data_sync_assets', 'account_sql', 'help_sql']" in console.APP_JS
    assert "return progress.filter(step => !hidden.has(step.id))" in console.APP_JS
    assert "const progress = visibleProgressSteps(job)" in console.APP_JS
    assert "progressSteps" in console.APP_JS
    assert "progress-icon" in console.APP_JS
    assert "repeat(10, minmax(0, 1fr))" in console.STYLE_CSS
    assert "@keyframes orbit" in console.STYLE_CSS
    assert ".overall-progress li.running .progress-icon::after" in console.STYLE_CSS
    assert "outputs.common_zip" in console.APP_JS
    assert "pathRow(t('commonZip'), outputs.common_zip)" in console.APP_JS
    assert "${pathRow(t('standaloneZip'), outputs.standalone_zip)}" not in console.APP_JS
    assert "${pathRow(t('versionTxt'), outputs.version_txt)}" not in console.APP_JS
    assert "async function copyText(text)" in console.APP_JS
    assert "navigator.clipboard.writeText" in console.APP_JS
    assert "document.execCommand('copy')" in console.APP_JS
    assert "copyFailed" in console.APP_JS
    assert ".workbench" in console.STYLE_CSS
    assert ".workbench { display: grid; grid-template-columns: 1fr;" in console.STYLE_CSS
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
            "help_docs_svn_revision": "12345",
            "build_help": False,
            "conf_server_host": "customer.local",
            "conf_enable_https": True,
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
    assert payloads[0]["conf_enable_https"] is True
    assert payloads[0]["help_docs_svn_revision"] == "12345"
    assert payloads[0]["build_help"] is False


def test_tenant_import_config_is_derived_from_standard_request():
    config = console.tenant_import_config_from_request(
        {
            "publish_group_shomuSystem": "on",
            "publish_group_yearEndAdjustment": "on",
            "publish_group_applications": "",
            "publish_group_allowances": "",
            "publish_group_commonSettings": "on",
            "publish_shomu_portal": "on",
            "mail_usage": "none",
            "ekispert_usage": "none",
            "course_usage": "use",
        }
    )

    assert config.support_applications == ("em", "mdm", "personal-portal", "taxadjustment")
    assert config.enable_email is False
    assert config.enable_transport_setting is False
    assert config.enable_lecture is True


def test_tenant_import_config_enables_business_process_and_service_flags():
    config = console.tenant_import_config_from_request(
        {
            "publish_group_shomuSystem": "",
            "publish_group_yearEndAdjustment": "",
            "publish_group_applications": "on",
            "publish_group_allowances": "on",
            "publish_group_commonSettings": "",
            "publish_apps_portal": "",
            "publish_allowance_portal": "",
            "mail_usage": "use",
            "ekispert_usage": "use",
            "course_usage": "none",
        }
    )

    assert config.support_applications == ("business-process",)
    assert config.enable_email is True
    assert config.enable_transport_setting is True
    assert config.enable_lecture is False


def test_ohr_import_config_is_derived_from_publish_plan():
    config = console.ohr_import_config_from_request(
        {
            "publish_group_shomuSystem": "on",
            "publish_group_yearEndAdjustment": "on",
            "publish_group_applications": "on",
            "publish_group_allowances": "on",
            "publish_group_commonSettings": "on",
            "publish_shomu_profile": "",
            "publish_shomu_source_tax": "",
            "publish_shomu_issue_info": "on",
            "publish_nencho_tax": "",
            "publish_nencho_tax_admin": "on",
            "publish_apps_status": "on",
            "publish_apps_agent": "",
            "publish_allowance_current": "",
        }
    )

    menu_codes = {(item.application_name, item.menu_code) for item in config.disabled_menus if not item.enabled}
    enabled_menu_codes = {(item.application_name, item.menu_code) for item in config.disabled_menus if item.enabled}
    task_codes = {item.code for item in config.disabled_scheduled_tasks if not item.enabled}
    enabled_task_codes = {item.code for item in config.disabled_scheduled_tasks if item.enabled}
    assert ("personal-portal", "EM_PR_MBR") in menu_codes
    assert ("personal-portal", "EM_PR_TXW") in menu_codes
    assert ("taxadjustment", "EMA_PR_PRT") in menu_codes
    assert ("taxadjustment", "EMA_HR_PRT") in enabled_menu_codes
    assert "mdm-data-synchronization-tax-data" in task_codes
    assert "send-tax-mail-batch" in task_codes
    assert "hr-to-upds-getsukazoku" in task_codes
    assert "mdm-data-synchronization-decree-data" in enabled_task_codes


def test_ohr_import_config_disables_children_when_publish_group_is_off():
    config = console.ohr_import_config_from_request(
        {
            "publish_group_shomuSystem": "",
            "publish_group_yearEndAdjustment": "on",
            "publish_group_applications": "on",
            "publish_group_allowances": "on",
            "publish_group_commonSettings": "on",
        }
    )

    menu_codes = {(item.application_name, item.menu_code) for item in config.disabled_menus if not item.enabled}
    assert ("personal-portal", "EM_PR_HRJ") in menu_codes
    assert ("em", "EM_HR_HRJ") in menu_codes


def test_ohr_import_config_keeps_shared_menu_when_any_control_is_enabled():
    config = console.ohr_import_config_from_request(
        {
            "publish_group_applications": "on",
            "publish_group_allowances": "on",
            "publish_apps_status": "",
            "publish_allowance_status": "on",
        }
    )

    menu_states = {(item.application_name, item.menu_code): item.enabled for item in config.disabled_menus}
    assert menu_states[("personal-portal", "BP_PR_ASS")] is True


def test_ohr_import_config_records_enabled_items_too():
    config = console.ohr_import_config_from_request(
        {
            "publish_group_shomuSystem": "on",
            "publish_shomu_profile": "on",
            "publish_shomu_issue_info": "on",
        }
    )

    menu_states = {(item.application_name, item.menu_code): item.enabled for item in config.disabled_menus}
    task_states = {item.code: item.enabled for item in config.disabled_scheduled_tasks}
    assert menu_states[("personal-portal", "EM_PR_MBR")] is True
    assert menu_states[("personal-portal", "EM_PR_TXW")] is False
    assert task_states["mdm-data-synchronization-decree-data"] is True
    assert task_states["mdm-data-synchronization-tax-data"] is False


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
    assert "'产物已收集': '成果物収集完了'" in console.APP_JS
    assert "const status = translateLogText(rawStatus)" in console.APP_JS
    assert console.filter_display_log("a\nremote_build_status: running\nb") == "a\nb"
    assert console.filter_display_log("\x1b[32mdist/static/js/app.js\x1b[39m") == "dist/static/js/app.js"


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
    assert "const modeLocked = mode !== 'create'" in console.APP_JS
    assert "if (el.name === 'product_variant')" in console.APP_JS
    assert "el.disabled = false;" in console.APP_JS
    assert "standardHidden" in console.APP_JS
    assert "nhoHidden" in console.APP_JS
    assert "el.disabled = Boolean(standardHidden) || Boolean(nhoHidden) || locked || modeLocked || terminalLocked" in console.APP_JS
    assert "if (!res.ok)" in console.APP_JS


def test_host_console_supports_standard_and_nho_product_variants():
    assert "name=\"product_variant\"" in console.INDEX_HTML
    assert "value=\"standard\"" in console.INDEX_HTML
    assert "value=\"nho\"" in console.INDEX_HTML
    assert 'name="material_number"' in console.INDEX_HTML
    assert 'list="material-numbers"' not in console.INDEX_HTML
    assert "<datalist" not in console.INDEX_HTML
    assert 'id="material-number-toggle"' in console.INDEX_HTML
    assert 'id="material-number-menu"' in console.INDEX_HTML
    assert "required-field material-field" in console.INDEX_HTML
    assert "materialNumber" in console.APP_JS
    assert "/build-terminal/api/nho-material-numbers" in console.APP_JS
    assert "/build-terminal/api/standard-material-numbers" in console.APP_JS
    assert "variant === 'nho' ? '/build-terminal/api/nho-material-numbers'" in console.APP_JS
    assert "fillMaterialSelect" in console.APP_JS
    assert "materialNumberLoadFailed" in console.APP_JS
    assert "input[name=\"material_number\"]" in console.APP_JS
    assert "closeMaterialMenu" in console.APP_JS
    assert "variantStandard" in console.APP_JS
    assert "variantNho" in console.APP_JS
    assert "getProductVariant()" in console.APP_JS
    assert "product_variant=${variant}" in console.APP_JS
    assert "build_nho_common_package" in console.__dict__
    assert "nho-material-database-assets" in Path("host_standalone_console.py").read_text(encoding="utf-8")
    assert "database_assets_zip=database_assets_zip" in Path("host_standalone_console.py").read_text(encoding="utf-8")
    assert "outputs.common_zip" in console.APP_JS
    assert "const visibleJobs = data.jobs.filter" in console.APP_JS
    assert "((job.request && job.request.product_variant) || 'standard') === currentVariant" in console.APP_JS
    assert "visibleJobs.forEach(job =>" in console.APP_JS
    assert "enterCreateMode();" in console.APP_JS
    assert "document.querySelectorAll('.standard-only')" in console.APP_JS
    assert "[hidden], .standard-only[hidden] { display: none !important; }" in console.STYLE_CSS


def test_standard_console_has_preparation_and_import_plan_tabs():
    assert 'data-standard-tab="prep"' in console.INDEX_HTML
    assert 'data-standard-tab="import"' in console.INDEX_HTML
    assert 'data-standard-tab-panel="prep"' in console.INDEX_HTML
    assert 'data-standard-tab-panel="import"' in console.INDEX_HTML
    for name in [
        "employee_number_digits",
        "ap_cpu_count",
        "ap_memory_gb",
        "web_cert_name",
        "web_key_name",
        "mail_host_ip",
        "upds_db_name",
        "data_sync_custom_subdir",
        "ekispert_url",
        "facility_situation",
        "publish_common_log",
    ]:
        assert f'name="{name}"' in console.INDEX_HTML
    assert "function switchStandardTab(tabName)" in console.APP_JS
    assert "document.querySelectorAll('.standard-tab')" in console.APP_JS
    assert ".standard-tab-panel" in console.STYLE_CSS
    assert '.standard-tab-panel[data-standard-tab-panel="import"]' in console.STYLE_CSS
    assert ".tag-tree" in console.STYLE_CSS


def test_usage_options_are_in_preparation_service_sections():
    html = console.INDEX_HTML
    mail_section = html.split('data-i18n="mailServiceInfo"', 1)[1].split("</fieldset>", 1)[0]
    upds_section = html.split('data-i18n="updsServiceInfo"', 1)[1].split("</fieldset>", 1)[0]
    ekispert_section = html.split('data-i18n="ekispertInfo"', 1)[1].split("</fieldset>", 1)[0]
    import_option_matrix = html.split('<div class="option-matrix">', 1)[1].split("</div>", 1)[0]

    assert 'name="mail_usage"' in mail_section
    assert 'name="workflow_upds_usage"' in upds_section
    assert 'name="data_sync_custom_subdir"' in upds_section
    assert 'name="ekispert_usage"' in ekispert_section
    assert 'name="mail_usage"' not in import_option_matrix
    assert 'name="workflow_upds_usage"' not in import_option_matrix
    assert 'name="ekispert_usage"' not in import_option_matrix
    assert ".option-matrix" in console.STYLE_CSS
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in console.STYLE_CSS
    assert 'name="mail_usage"><option value="none"' in console.INDEX_HTML
    assert 'name="workflow_upds_usage"><option value="none"' in console.INDEX_HTML
    assert 'name="ekispert_usage"><option value="none"' in console.INDEX_HTML
    assert "/-/tree/master/" in console.APP_JS
    assert "tsukubav7phr/PHR" not in console.INDEX_HTML
    assert "/api/data-sync-custom-source/validate" in console.APP_JS
    assert "field-invalid" in console.STYLE_CSS
    assert "dataSyncCustomSourceInvalid" in console.APP_JS
    assert "input.value = data.path" in console.APP_JS


def test_data_sync_custom_source_validation_normalizes_full_tree_url(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []

    def fake_remote_json(base_url, path, payload=None):
        calls.append((base_url, path))
        return {"ok": True, "path": "tsukubav7phr/PHR"}

    monkeypatch.setattr(console, "remote_json", fake_remote_json)

    result = console.validate_data_sync_custom_source(
        "https://upds7.ujob100.com/ohr/data-synchronization/-/tree/master/tsukubav7phr/PHR"
    )

    assert result == {"ok": True, "path": "tsukubav7phr/PHR"}
    assert calls[0][0] == console.REMOTE_BUILD_CONSOLE_URL
    assert calls[0][1].startswith("/api/data-sync-custom-source/validate?value=")


def test_help_docs_svn_revision_validation_is_forwarded_to_build_terminal(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_remote_json(base_url, path, payload=None):
        calls.append((base_url, path))
        return {"ok": True, "revision": "12345"}

    monkeypatch.setattr(console, "remote_json", fake_remote_json)

    assert console.validate_help_docs_svn_revision("") == {"ok": True, "revision": ""}
    result = console.validate_help_docs_svn_revision("12345")

    assert result == {"ok": True, "revision": "12345"}
    assert calls[0][0] == console.REMOTE_BUILD_CONSOLE_URL
    assert calls[0][1] == "/api/help-docs-svn-revision/validate?value=12345"
    assert "/api/help-docs-svn-revision/validate" in console.APP_JS


def test_service_usage_requires_related_fields_when_enabled():
    payload, error = console.validate_job_payload(
        {
            "product_variant": "standard",
            "material_number": "20260525",
            "backend_branch": "release_20260525",
            "mail_usage": "use",
        }
    )
    assert error == "missing mail_host_ip"

    payload, error = console.validate_job_payload(
        {
            "product_variant": "standard",
            "material_number": "20260525",
            "backend_branch": "release_20260525",
            "workflow_upds_usage": "use",
            "upds_host_name": "upds",
            "upds_user": "user",
            "upds_password": "secret",
            "upds_port": "5432",
        }
    )
    assert error == "missing upds_db_name"

    payload, error = console.validate_job_payload(
        {
            "product_variant": "standard",
            "material_number": "20260525",
            "backend_branch": "release_20260525",
            "ekispert_usage": "use",
        }
    )
    assert error == "missing ekispert_url"
    assert "function validateConditionalRequiredFields(form)" in console.APP_JS
    assert "markConditionalRequiredFields();" in console.APP_JS
    assert ".conditional-required > span::after" in console.STYLE_CSS


def test_standard_publish_plan_required_items_are_locked_and_submitted():
    assert "function initializeFixedPublishItems()" in console.APP_JS
    assert "input.dataset.fixedRequired = 'true'" in console.APP_JS
    assert 'input[type="hidden"][data-fixed-mirror="true"]' in console.APP_JS
    assert "function enforceFixedPublishItems()" in console.APP_JS
    assert "el.dataset.fixedRequired === 'true'" in console.APP_JS
    assert ".tag-tree label.fixed-required" in console.STYLE_CSS


def test_standard_publish_plan_main_menu_can_disable_children():
    assert "function initializePublishMenuGroups()" in console.APP_JS
    assert "function applyPublishMenuGroupState(details)" in console.APP_JS
    assert "function updatePublishMenuSummaryText(summary)" in console.APP_JS
    assert "publish-menu-toggle" in console.APP_JS
    assert "publish-menu-title" in console.APP_JS
    assert "publish_group_" in console.APP_JS
    assert "details.classList.toggle('publish-menu-disabled', !enabled)" in console.APP_JS
    assert "input.dataset.fixedMirror === 'true'" in console.APP_JS
    assert "enforcePublishMenuGroups();" in console.APP_JS
    assert "document.querySelectorAll('.tag-tree > details')" in console.APP_JS
    assert "if (el.matches('.tag-tree summary'))" in console.APP_JS
    assert ".tag-tree details.publish-menu-disabled" in console.STYLE_CSS


def test_standard_publish_plan_has_three_level_tree():
    assert 'class="publish-category"' in console.INDEX_HTML
    assert '<summary>個人ポータル</summary>' in console.INDEX_HTML
    assert '<summary>身上申告</summary>' in console.INDEX_HTML
    assert '<summary>共通設定</summary>' in console.INDEX_HTML
    assert 'name="publish_shomu_free_search"' in console.INDEX_HTML
    assert 'name="publish_apps_category_limit"' in console.INDEX_HTML
    assert ".tag-tree details.publish-category" in console.STYLE_CSS


def test_container_borders_have_stronger_visual_weight():
    assert "--container-line: #b8b8b8;" in console.STYLE_CSS
    assert "--container-line-strong: #8f8f8f;" in console.STYLE_CSS
    assert "border: 1.5px solid var(--container-line);" in console.STYLE_CSS
    assert "border-left: 1.5px solid var(--container-line-strong);" in console.STYLE_CSS


def test_config_history_is_saved_with_organisation_and_job_id(tmp_path, monkeypatch):
    monkeypatch.setattr(console, "CONFIG_HISTORY_DIR", tmp_path / "config-history")
    job = {
        "id": "20260525010101",
        "created_at": 100,
        "request": {
            "product_variant": "standard",
            "organisation_name": "OneHR",
            "material_number": "20260525",
        },
    }

    item = console.save_config_history(job)
    listed = console.list_config_histories()

    assert item["label"] == "OneHR / 20260525010101"
    assert listed[0]["request"]["organisation_name"] == "OneHR"
    assert console.delete_config_history("20260525010101") == {"ok": True, "id": "20260525010101"}
    assert console.list_config_histories() == []


def test_host_console_has_loadable_config_history_ui_and_api():
    assert 'id="configHistory"' in console.INDEX_HTML
    assert "/api/configs" in console.APP_JS
    assert "function renderConfigHistory()" in console.APP_JS
    assert "function loadConfigHistory(configId)" in console.APP_JS
    assert "function deleteConfigHistory(configId)" in console.APP_JS
    assert "fillFormFromRequest(item.request || {})" in console.APP_JS
    assert "refreshConfigHistory();" in console.APP_JS
    assert "parsed.path == \"/api/configs\"" in Path("host_standalone_console.py").read_text(encoding="utf-8")
    assert "delete_config_history(config_id)" in Path("host_standalone_console.py").read_text(encoding="utf-8")
    assert ".config-history-item" in console.STYLE_CSS


def test_build_terminal_proxy_rewrites_absolute_assets():
    class Dummy(console.Handler):
        def __init__(self):
            pass

    body = b'<link href="/style.css?v=4"><script src="/app.js?v=9"></script><script>fetch(`/api/builds`);</script>'
    rewritten = Dummy().rewrite_build_terminal_asset(body, "text/html; charset=utf-8").decode("utf-8")

    assert 'href="/build-terminal/style.css?v=4"' in rewritten
    assert 'src="/build-terminal/app.js?v=9"' in rewritten
    assert "fetch(`/build-terminal/api/builds`)" in rewritten
