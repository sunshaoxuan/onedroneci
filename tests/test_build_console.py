from __future__ import annotations

import importlib.util
from pathlib import Path


def load_server():
    path = Path(__file__).resolve().parents[1] / "build-console" / "server.py"
    spec = importlib.util.spec_from_file_location("build_console_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_create_build_validates_backend_branch(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)

    try:
        server.create_build({"backend_branch": "bad branch;rm -rf /"})
    except ValueError as exc:
        assert "后端分支名" in str(exc)
    else:
        raise AssertionError("invalid branch should fail")


def test_create_build_validates_frontend_release_branch(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)

    try:
        server.create_build(
            {"backend_branch": "release_20260129", "frontend_release_branch": "bad;branch"}
        )
    except ValueError as exc:
        assert "前端版本分支" in str(exc)
    else:
        raise AssertionError("invalid frontend branch should fail")


def test_create_build_requires_backend_branch(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)

    try:
        server.create_build({"backend_branch": ""})
    except ValueError as exc:
        assert "请填写后端分支" in str(exc)
    else:
        raise AssertionError("empty branch should fail")


def test_build_console_page_has_i18n_without_breaking_api():
    server = load_server()

    assert "<html lang=\"ja-JP\">" in server.INDEX_HTML
    assert "data-i18n=\"title\"" in server.INDEX_HTML
    for lang in ("ja-JP", "zh-CN", "en-US"):
        assert f"'{lang}'" in server.APP_JS
    for key in ("startBuild", "stopBuild", "historyTitle", "logTitle", "needBackend"):
        assert key in server.APP_JS
    for step_id in ("validate", "checkout_backend", "build_backend", "restore_frontend", "build_frontend", "collect_artifacts"):
        assert step_id in server.APP_JS


def test_build_console_supports_nho_variant_scripts_and_ui():
    server = load_server()

    assert "product_variant" in server.INDEX_HTML
    assert "variantNho" in server.APP_JS
    assert "getProductVariant()" in server.APP_JS
    assert "product_variant=${variant}" in server.APP_JS
    assert "collect-pkg.sh" in server.nho_build_command()
    assert "zip -r package.zip ./package" in server.nho_build_command()
    assert "ohr-web-nencho" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "yarn setup" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "yarn build" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "yarn bundle" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "ohr-cicd" not in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "HELP_DOCS" not in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "conf_prod" not in server.NHO_FRONTEND_BUILD_SCRIPT


def test_create_nho_build_does_not_require_standard_customer_fields(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    meta = server.create_build(
        {
            "product_variant": "nho",
            "build_backend": False,
            "build_frontend": True,
            "frontend_release_branch": "release_20260316",
        }
    )

    assert meta["request"]["product_variant"] == "nho"
    assert meta["request"]["frontend_workspace_branch"] == server.NHO_FRONTEND_WORKSPACE_BRANCH
    assert meta["request"]["frontend_feelin_branch"] == server.NHO_FRONTEND_FEELIN_BRANCH
    assert meta["request"]["frontend_nencho_branch"] == "release_20260316"


def test_build_console_embedded_mode_is_read_only_current_build_view():
    server = load_server()

    assert "embeddedMode" in server.APP_JS
    assert "embeddedBuildId" in server.APP_JS
    assert "document.body.classList.add('embedded')" in server.APP_JS
    assert "data.builds.filter(build => build.id === embeddedBuildId)" in server.APP_JS
    assert "if (!embeddedMode) await loadBuilds();" in server.APP_JS
    assert "if (!embeddedMode) {" in server.APP_JS
    assert "if (embeddedMode) return;" in server.APP_JS
    assert "body.embedded .hero" in server.STYLE_CSS
    assert "body.embedded .form-card" in server.STYLE_CSS
    assert "body.embedded .history-card" in server.STYLE_CSS
    assert "grid-template-columns: minmax(0, 1fr)" in server.STYLE_CSS
    assert "body.embedded #stop-button" in server.STYLE_CSS


def test_build_console_marks_unfinished_builds_failed_on_startup(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    build_dir = tmp_path / "20260514000101"
    build_dir.mkdir()
    (build_dir / "build.log").write_text("", encoding="utf-8")
    server.write_json(
        build_dir / "metadata.json",
        {
            "id": "20260514000101",
            "status": "running",
            "updated_at": 1,
            "steps": [
                {"id": "build_frontend", "status": "running", "started_at": 1, "finished_at": None},
                {"id": "collect_artifacts", "status": "pending", "started_at": None, "finished_at": None},
            ],
        },
    )

    server.mark_unfinished_builds_failed("restart")

    meta = server.read_json(build_dir / "metadata.json")
    assert meta["status"] == "failed"
    assert meta["error"] == "restart"
    assert meta["steps"][0]["status"] == "failed"
    assert meta["steps"][1]["status"] == "skipped"
    assert "构建失败：restart" in (build_dir / "build.log").read_text(encoding="utf-8")


def test_create_build_requires_frontend_release_branch_when_frontend_enabled(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    try:
        server.create_build(
            {
                "backend_branch": "release_20260129",
                "frontend_release_branch": "",
            }
        )
    except ValueError as exc:
        assert "前端版本分支" in str(exc)
    else:
        raise AssertionError("missing workspace branch should fail")


def test_create_build_allows_frontend_only_without_backend_branch(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    meta = server.create_build(
        {
            "build_backend": False,
            "build_frontend": True,
            "backend_branch": "",
            "frontend_release_branch": "release_front",
            "conf_server_host": "192.168.70.136",
        }
    )

    assert meta["request"]["build_backend"] is False
    assert meta["request"]["build_frontend"] is True
    assert meta["request"]["help_docs_branch"] == "release_ci"
    assert meta["request"]["conf_server_host"] == "192.168.70.136"
    assert meta["request"]["conf_web_port"] == 80
    assert meta["request"]["backend_branch"] == ""


def test_create_build_requires_at_least_one_target(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)

    try:
        server.create_build(
            {
                "build_backend": False,
                "build_frontend": False,
                "backend_branch": "",
                "frontend_release_branch": "",
            }
        )
    except ValueError as exc:
        assert "至少选择" in str(exc)
    else:
        raise AssertionError("missing build target should fail")


def test_create_build_uses_release_for_child_repos_and_configured_workspace(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    meta = server.create_build(
        {
            "backend_branch": "release_20260129",
            "frontend_release_branch": "release_front",
            "conf_server_host": "192.168.70.136",
        }
    )
    req = meta["request"]
    assert req["frontend_workspace_branch"] == "master"
    assert req["frontend_release_branch"] == "release_front"
    assert req["frontend_feelin_branch"] == "release_front"
    assert req["frontend_lowcode_engine_branch"] == "release_front"
    assert req["frontend_micro_frontends_branch"] == "release_front"
    assert req["frontend_nocode_engine_branch"] == "release_front"


def test_create_build_stores_frontend_placeholders(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    meta = server.create_build(
        {
            "backend_branch": "release_20260129",
            "frontend_release_branch": "release_front",
            "conf_server_host": "192.168.70.136",
            "conf_web_port": "40443",
            "conf_enable_https": True,
            "conf_worker_processes": "1",
            "conf_worker_connections": "1024",
            "note": "smoke",
        }
    )

    assert meta["executor"] == "direct"
    assert meta["request"]["backend_branch"] == "release_20260129"
    assert meta["request"]["frontend_workspace_branch"] == "master"
    assert meta["request"]["frontend_release_branch"] == "release_front"
    assert meta["request"]["help_docs_branch"] == "release_ci"
    assert meta["request"]["conf_server_host"] == "192.168.70.136"
    assert meta["request"]["conf_web_port"] == 40443
    assert meta["request"]["conf_enable_https"] is True
    assert meta["request"]["conf_worker_processes"] == 1
    assert meta["request"]["conf_worker_connections"] == 1024
    assert (tmp_path / "standard" / meta["id"] / "metadata.json").is_file()
    assert [step["id"] for step in meta["steps"]] == list(server.DIRECT_STEP_IDS)


def test_create_build_requires_drone_config_when_drone_executor(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "EXECUTOR", "drone")
    monkeypatch.setattr(server, "DRONE_CONTROL_REPO", "")
    monkeypatch.setattr(server, "DRONE_TOKEN", "")

    try:
        server.create_build(
            {
                "backend_branch": "release_back",
                "frontend_release_branch": "release_front",
                "conf_server_host": "192.168.70.136",
            }
        )
    except ValueError as exc:
        assert "Drone 执行器未配置" in str(exc)
    else:
        raise AssertionError("missing Drone config should fail")


def test_delete_finished_build_removes_metadata_and_artifacts(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "builds")
    monkeypatch.setattr(server, "ARTIFACT_ROOT", tmp_path / "artifacts")

    build_id = "20260514121212"
    server.build_dir(build_id).mkdir(parents=True)
    server.write_json(
        server.metadata_path(build_id),
        {"id": build_id, "status": "success", "steps": [], "artifacts": []},
    )
    server.shared_artifact_path(build_id, "web.zip").parent.mkdir(parents=True)
    server.shared_artifact_path(build_id, "web.zip").write_text("web", encoding="utf-8")

    assert server.delete_build(build_id) == {"ok": True, "id": build_id}
    assert not server.build_dir(build_id).exists()
    assert not (server.ARTIFACT_ROOT / build_id).exists()


def test_product_variant_build_and_artifact_roots_are_isolated(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "builds")
    monkeypatch.setattr(server, "ARTIFACT_ROOT", tmp_path / "artifacts")

    assert server.build_dir("b1", "standard") == tmp_path / "builds" / "standard" / "b1"
    assert server.build_dir("b1", "nho") == tmp_path / "builds" / "nho" / "b1"
    assert server.shared_artifact_path("b1", "web.zip", "standard") == tmp_path / "artifacts" / "standard" / "b1" / "web.zip"
    assert server.shared_artifact_path("b1", "web.zip", "nho") == tmp_path / "artifacts" / "nho" / "b1" / "web.zip"


def test_delete_running_build_is_rejected(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    build_id = "20260514121213"
    server.build_dir(build_id).mkdir(parents=True)
    server.write_json(server.metadata_path(build_id), {"id": build_id, "status": "running"})

    assert server.delete_build(build_id) == {"ok": False, "error": "build_running"}
    assert server.metadata_path(build_id).is_file()


def test_list_frontend_release_branches_intersects_child_repos(monkeypatch):
    server = load_server()

    outputs = [
        "a\trefs/heads/release_20260101\nb\trefs/heads/release_20260102\n",
        "c\trefs/heads/release_20260102\nd\trefs/heads/release_20260103\n",
        "e\trefs/heads/release_20260102\nf\trefs/heads/release_20260104\n",
        "g\trefs/heads/release_20260102\nh\trefs/heads/release_20260105\n",
    ]

    def fake_run(*args, **kwargs):
        class Result:
            returncode = 0
            stderr = ""

        result = Result()
        result.stdout = outputs.pop(0)
        return result

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server.list_frontend_release_branches() == ["release_20260102"]


def test_list_backend_release_branches_parses_refs(monkeypatch, tmp_path):
    server = load_server()
    monkeypatch.setattr(server, "OHR_BACK_DIR", tmp_path)

    class Result:
        returncode = 0
        stdout = (
            "abc\trefs/heads/release_20260501\n"
            "def\trefs/heads/feature/demo\n"
            "ghi\trefs/heads/release_20260502\n"
        )
        stderr = ""

    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: Result())

    assert server.list_backend_release_branches() == ["release_20260502", "release_20260501"]


def test_direct_frontend_build_uses_bundle_zip_only():
    server = load_server()
    script = server.DIRECT_FRONTEND_BUILD_SCRIPT

    assert "npm run build" in script
    assert "npm run bundle" in script
    assert "release_*.zip" in script
    assert "ohr-cicd/web_prod" in script
    assert "ohr-cicd/conf_prod" in script
    assert "conf_prod/TODO.md" not in script
    assert "[sync ohr-cicd]" in script
    assert "OHR_CICD_GIT_URL" in script
    assert "OHR_CICD_BRANCH" in script
    assert "config.$OHR_CICD_ENV.js" in script
    assert "node ./src/generateConf.js" in script
    assert "conf_$OHR_CICD_ENV" in script
    assert "CONF_SERVER_HOST" in script
    assert "CONF_WEB_PORT" in script
    assert "CONF_ENABLE_HTTPS" in script
    assert "ENABLE_HTTPS" in script
    assert "PORT_HTTPS: HTTPS_PORT" in script
    assert "SSL_CERTIFICATE: 'server.crt'" in script
    assert "SSL_CERTIFICATE_KEY: 'server.key'" in script
    assert "nginx_https.conf" in script
    assert "ssl_certificate server.crt" in script
    assert "ssl_certificate_key server.key" in script
    assert "listen[[:space:]]*443[[:space:]]*ssl" in script
    assert "const HOST_PORTAL = ENABLE_HTTPS" in script
    assert "CONF_WEB_DIR: 'ohr-cicd/web_prod'" in script
    assert "CONF_CONF_DIR: 'conf_prod'" in script
    assert "web_prod/help" in script
    assert "ohr-help-docs" in script
    assert "svn checkout" in script
    assert "svn update" in script
    assert "svn cleanup" in script
    assert "npm run copy-images" in script
    assert "使用 SVN 文档源构建 Help" in script
    assert "HELP_DOCS_SVN_WORKDIR" in script
    assert "ohr_help_docs_release_*.zip" in script
    assert "HELP_CACHE_KEY" in script
    assert "[cache help] reuse help bundle" in script
    assert "svn info --show-item revision" in script
    assert "pnpm i --frozen-lockfile --prefer-offline" in script
    assert "git -C \"$CICD_DIR\" clean -fd -e node_modules" in script
    assert "-e .ci-cache" in script
    assert "[cache yarn] ohr-cicd unchanged; skip yarn install" in script
    assert "前端发布包生成失败" in script
    assert 'zip -r "$OUT_WEB_ZIP" .' not in script
    assert "node_modules/*" not in script

    restore_script = server.DIRECT_FRONTEND_RESTORE_SCRIPT
    assert "pnpm_install_cached . ohr-workspace" in restore_script
    assert "[cache pnpm] $name unchanged; skip pnpm i" in restore_script
    assert "git clean -fd -e node_modules" in restore_script
    assert "-e .ci-cache" in restore_script


def test_direct_frontend_env_includes_ohr_cicd_config(monkeypatch):
    server = load_server()
    monkeypatch.setenv("NPM_AUTH_B64", "dGVzdDp0ZXN0")
    monkeypatch.setattr(server, "OHR_CICD_GIT_URL", "https://example.test/ohr-cicd.git")
    monkeypatch.setattr(server, "OHR_CICD_BRANCH", "master")
    monkeypatch.setattr(server, "OHR_CICD_ENV", "direct_prod")

    env = server.direct_frontend_env(
        {
            "frontend_release_branch": "release_front",
            "frontend_workspace_branch": "master",
            "help_docs_branch": "release_ci",
            "conf_server_host": "customer.local",
            "conf_web_port": 80,
            "conf_enable_https": True,
            "conf_worker_processes": 1,
            "conf_worker_connections": 1024,
        },
        "20260514120000",
    )

    assert env["OHR_CICD_GIT_URL"] == "https://example.test/ohr-cicd.git"
    assert env["OHR_CICD_BRANCH"] == "master"
    assert env["OHR_CICD_ENV"] == "direct_prod"
    assert env["CONF_SERVER_HOST"] == "customer.local"
    assert env["CONF_ENABLE_HTTPS"] == "true"


def test_build_console_log_rendering_keeps_fixed_line_window():
    server = load_server()

    assert "const MAX_LOG_LINES = embeddedMode ? 900 : 1600" in server.APP_JS
    assert "function appendLogText(text)" in server.APP_JS
    assert "logLines = logLines.slice(logLines.length - MAX_LOG_LINES)" in server.APP_JS
    assert "shouldStickToBottom" in server.APP_JS
    assert "pre.textContent += translateLogText" not in server.APP_JS
