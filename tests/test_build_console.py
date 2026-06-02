from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pytest


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


def test_build_console_validates_data_sync_custom_source(monkeypatch):
    server = load_server()
    calls: list[str] = []

    def fake_sync(subdir):
        calls.append(subdir)
        (server.DATA_SYNC_DIR / subdir).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(server, "sync_data_sync_validation_tree", fake_sync)
    monkeypatch.setattr(server, "DATA_SYNC_DIR", Path("build-console-test-data-sync-validation"))

    result = server.validate_data_sync_custom_source(
        "https://upds7.ujob100.com/ohr/data-synchronization/-/tree/master/tsukubav7phr/PHR"
    )

    assert result == {"ok": True, "path": "tsukubav7phr/PHR"}
    assert calls == ["tsukubav7phr/PHR"]


def test_build_console_rejects_data_sync_custom_source_from_other_repo():
    server = load_server()

    try:
        server.validate_data_sync_custom_source("https://upds7.ujob100.com/ohr/other/-/tree/master/tsukubav7phr/PHR")
    except ValueError as exc:
        assert "data-synchronization tree" in str(exc)
    else:
        raise AssertionError("other repository URL should be rejected")


def test_build_console_validates_help_docs_svn_revision(monkeypatch):
    server = load_server()
    calls: list[list[str]] = []

    class Proc:
        returncode = 0
        stdout = "Revision: 12345\n"
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append(args)
        return Proc()

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server.validate_help_docs_svn_revision("") == {"ok": True, "revision": ""}
    assert server.validate_help_docs_svn_revision("abc") == {
        "ok": False,
        "revision": "abc",
        "error": "invalid_revision",
    }
    assert server.validate_help_docs_svn_revision("12345") == {"ok": True, "revision": "12345"}
    assert calls[0][:4] == ["svn", "info", server.HELP_DOCS_SVN_URL, "-r"]
    assert calls[0][4] == "12345"


def test_build_console_supports_nho_variant_scripts_and_ui(monkeypatch):
    monkeypatch.setenv("MAVEN_ONEHR_PASSWORD", "test-password")
    server = load_server()

    assert "product_variant" in server.INDEX_HTML
    assert "variantNho" in server.APP_JS
    assert "getProductVariant()" in server.APP_JS
    assert "product_variant=${variant}" in server.APP_JS
    assert "collect-pkg.sh" in server.nho_build_command()
    assert "maven:3.9.6-eclipse-temurin-22" in server.nho_build_command()
    assert "docker run --rm" in server.nho_build_command()
    assert "/opt/nho-maven-cache" in server.nho_build_command()
    assert ":/root/.m2/repository" in server.nho_build_command()
    assert "/root/.m2/settings.xml:ro" in server.nho_build_command()
    assert "NHO package directory has no jar files" in server.nho_build_command()
    assert "[hidden], .standard-only[hidden] { display: none !important; }" in server.STYLE_CSS
    assert "zip -r package.zip ./package" in server.nho_build_command()
    assert "ohr-web-nencho" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "+refs/heads/$FRONTEND_WS_BRANCH:refs/remotes/origin/$FRONTEND_WS_BRANCH" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "+refs/heads/$repo_branch:refs/remotes/origin/$repo_branch" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "+refs/heads/$repo_branch:refs/remotes/origin/$repo_branch" in server.DIRECT_FRONTEND_RESTORE_SCRIPT
    assert 'git reset --hard HEAD\ngit checkout -B "$FRONTEND_WS_BRANCH"' in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert 'git -C "$repo_dir" reset --hard HEAD\n    git -C "$repo_dir" checkout -B "$repo_branch"' in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "NHO_PNPM_CACHE_DIR" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "NHO_YARN_CACHE_DIR" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "NHO_YARN_CACHE_DIR" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "write_nho_npmrc ohr-lowcode-engine" in server.NHO_FRONTEND_RESTORE_SCRIPT
    assert "write_nho_npmrc ohr-lowcode-engine" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "always-auth=true" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "//registry.smartcompany.cn/repository/npm-group/:_auth=$NPM_AUTH_B64" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "rewrite_nho_public_lock_urls ohr-lowcode-engine" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "apply_nho_low_memory_overrides" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "run_nho_setup_sequential" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "patch_nho_react_pdf_exports" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "removed react-pdf exports" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "dist/esm/Page css to legacy dist/Page path" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert 'replace("yarn build:parallel", "yarn build")' in server.NHO_FRONTEND_BUILD_SCRIPT
    assert 'replace(" --parallel", "")' in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "NODE_OPTIONS=--max_old_space_size=1536" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "NODE_OPTIONS=--max_old_space_size=2048" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "Path(\"ohr-nocode-engine/packages\").glob" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "--concurrency 1" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "NHO_NODE_OPTIONS" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "https://registry.npmmirror.com/" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert 'private_scopes = ("/@omf/", "/@one/", "/@ole/", "/@ohr/")' in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "yarn setup" not in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "yarn build" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "yarn bundle" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "ohr-cicd/web_prod" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert 'zip -qr "$OUT_WEB_ZIP" ohr-cicd' in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "HELP_DOCS" not in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "BUILD_CONF_PROD" in server.NHO_FRONTEND_BUILD_SCRIPT
    assert "ohr-cicd/conf_prod" in server.NHO_FRONTEND_BUILD_SCRIPT


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
            "build_conf_prod": False,
        }
    )

    assert meta["request"]["product_variant"] == "nho"
    assert meta["request"]["build_conf_prod"] is False
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
    assert meta["request"]["help_docs_svn_revision"] == ""
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
    assert meta["request"]["help_docs_svn_revision"] == ""
    assert meta["request"]["conf_server_host"] == "192.168.70.136"
    assert meta["request"]["conf_web_port"] == 40443
    assert meta["request"]["conf_enable_https"] is True
    assert meta["request"]["conf_worker_processes"] == 1
    assert meta["request"]["conf_worker_connections"] == 1024
    assert (tmp_path / "standard" / meta["id"] / "metadata.json").is_file()
    assert [step["id"] for step in meta["steps"]] == list(server.DIRECT_STEP_IDS)


def test_create_build_rejects_missing_help_svn_revision(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "validate_help_docs_svn_revision", lambda value: {"ok": False, "revision": value, "error": "not_found"})

    try:
        server.create_build(
            {
                "backend_branch": "release_20260129",
                "frontend_release_branch": "release_front",
                "help_docs_svn_revision": "999999",
                "conf_server_host": "192.168.70.136",
            }
        )
    except ValueError as exc:
        assert "Help SVN revision 不存在" in str(exc)
    else:
        raise AssertionError("missing Help SVN revision should fail")


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


def test_cleanup_previous_build_outputs_keeps_cache_and_current_metadata(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path / "builds")
    monkeypatch.setattr(server, "ARTIFACT_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(server, "OHR_BACK_DIR", tmp_path / "back")
    monkeypatch.setattr(server, "FRONTEND_WORKSPACE_DIR", tmp_path / "frontend")
    monkeypatch.setattr(server, "HELP_DOCS_DIR", tmp_path / "help")
    monkeypatch.setattr(server, "OHR_CICD_DIR", tmp_path / "cicd")

    old_build = server.build_dir("old1", "standard")
    old_build.mkdir(parents=True)
    (old_build / "metadata.json").write_text("{}", encoding="utf-8")
    (old_build / "build.log").write_text("log", encoding="utf-8")
    (old_build / "web.zip").write_text("web", encoding="utf-8")
    (old_build / "package.zip").write_text("pkg", encoding="utf-8")

    current_build = server.build_dir("new1", "standard")
    current_build.mkdir(parents=True)
    (current_build / "metadata.json").write_text("{}", encoding="utf-8")
    (current_build / "build.log").write_text("log", encoding="utf-8")

    old_artifact = server.variant_artifact_root("standard") / "old1"
    old_artifact.mkdir(parents=True)
    (old_artifact / "web.zip").write_text("web", encoding="utf-8")
    cache_dir = tmp_path / "pnpm-cache"
    cache_dir.mkdir()
    server.OHR_BACK_DIR.mkdir()
    (server.OHR_BACK_DIR / "package.zip").write_text("backend", encoding="utf-8")
    (server.OHR_BACK_DIR / "package").mkdir()
    (server.OHR_BACK_DIR / "package" / "app.jar").write_text("jar", encoding="utf-8")
    server.FRONTEND_WORKSPACE_DIR.mkdir()
    (server.FRONTEND_WORKSPACE_DIR / "release_old.zip").write_text("frontend", encoding="utf-8")
    (server.FRONTEND_WORKSPACE_DIR / "node_modules").mkdir()
    server.HELP_DOCS_DIR.mkdir()
    (server.HELP_DOCS_DIR / ".ci-cache").mkdir()
    (server.HELP_DOCS_DIR / "build").mkdir()
    (server.HELP_DOCS_DIR / "build" / "asset.js").write_text("asset", encoding="utf-8")

    released = server.cleanup_previous_build_outputs("standard", "new1")

    assert (old_build / "metadata.json").is_file()
    assert (old_build / "build.log").is_file()
    assert not (old_build / "web.zip").exists()
    assert not (old_build / "package.zip").exists()
    assert not old_artifact.exists()
    assert (server.variant_artifact_root("standard") / "new1").is_dir()
    assert cache_dir.is_dir()
    assert not (server.OHR_BACK_DIR / "package.zip").exists()
    assert not (server.OHR_BACK_DIR / "package").exists()
    assert not (server.FRONTEND_WORKSPACE_DIR / "release_old.zip").exists()
    assert (server.FRONTEND_WORKSPACE_DIR / "node_modules").is_dir()
    assert not (server.HELP_DOCS_DIR / "build").exists()
    assert (server.HELP_DOCS_DIR / ".ci-cache").is_dir()
    assert released == 32


def test_system_resource_status_reports_build_terminal_capacity(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "ARTIFACT_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(server.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(server, "memory_available_bytes", lambda: 32 * 1024 * 1024)

    status = server.system_resource_status()

    assert status["cpu_count"] == 8
    assert status["memory_available_bytes"] == 32 * 1024 * 1024
    assert status["disk_free_bytes"] > 0


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


def test_variant_branch_lists_use_variant_gitlab_projects(monkeypatch):
    server = load_server()

    calls: list[str] = []

    def fake_list(url, limit=500):
        calls.append(url)
        return ["release_common"]

    monkeypatch.setattr(server, "list_release_branches_for_url", fake_list)

    assert server.list_backend_release_branches("standard") == ["release_common"]
    assert calls[-1] == server.OHR_BACK_GIT_URL

    assert server.list_backend_release_branches("nho") == ["release_common"]
    assert calls[-1] == server.NHO_BACK_GIT_URL

    calls.clear()
    assert server.list_frontend_release_branches("standard") == ["release_common"]
    assert calls == list(server.FRONTEND_CHILD_REPOS.values())

    calls.clear()
    assert server.list_frontend_release_branches("nho") == ["release_common"]
    assert calls == list(server.NHO_FRONTEND_CHILD_REPOS.values())


def test_nho_material_numbers_are_loaded_from_build_terminal_svn(monkeypatch):
    server = load_server()
    server.NHO_MATERIAL_CACHE["numbers"] = []
    server.NHO_MATERIAL_CACHE["expires_at"] = 0

    called = []

    class Proc:
        returncode = 0
        stdout = "20260316リリース作業/\nmemo/\n20260325リリース作業/\n"
        stderr = ""

    def fake_run(command, capture_output=True, text=True, timeout=60):
        called.append(command)
        return Proc()

    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/svn")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_URL", "http://example.test/svn/大連側/97.リリース作業")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_USERNAME", "svn-user")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_PASSWORD", "svn-pass")

    assert server.list_nho_material_numbers(force_refresh=True) == ["20260325", "20260316"]
    assert called and called[0][:4] == ["/usr/bin/svn", "ls", "--non-interactive", "--trust-server-cert"]
    assert "--username" in called[0]
    assert "svn-user" in called[0]


def test_standard_material_numbers_are_loaded_from_customer_environment_svn(monkeypatch):
    server = load_server()
    server.STANDARD_MATERIAL_CACHE["numbers"] = []
    server.STANDARD_MATERIAL_CACHE["dirs"] = {}
    server.STANDARD_MATERIAL_CACHE["expires_at"] = 0

    called = []

    class Proc:
        returncode = 0
        stdout = "資材-20260527/\n資材_20260424/\n資材-次回リリース/\n初期構築/\n"
        stderr = ""

    def fake_run(command, capture_output=True, text=True, timeout=60):
        called.append(command)
        return Proc()

    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/svn")
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "STANDARD_MATERIAL_SVN_URL", "http://example.test/svn/お客様環境")

    assert server.list_standard_material_numbers(force_refresh=True) == ["20260527", "20260424"]
    assert server.STANDARD_MATERIAL_CACHE["dirs"]["20260527"] == "資材-20260527"
    assert called and called[0][-1] == "http://example.test/svn/お客様環境"


def test_standard_material_release_branches_are_loaded_from_version_txt(monkeypatch):
    server = load_server()
    calls = []
    server.STANDARD_MATERIAL_CACHE["numbers"] = ["20260527"]
    server.STANDARD_MATERIAL_CACHE["dirs"] = {"20260527": "資材-20260527"}
    server.STANDARD_MATERIAL_CACHE["expires_at"] = 9999999999

    def fake_run_svn_text(args, timeout=60):
        calls.append(args)
        return "后台分支：release_20260527\r\n前台分支：release_20260527\r\nhelp version：2024\r\n"

    monkeypatch.setattr(server, "run_svn_text", fake_run_svn_text)
    monkeypatch.setattr(server, "STANDARD_MATERIAL_SVN_URL", "http://example.test/svn/お客様環境")

    result = server.get_standard_material_release_branches("20260527")

    assert result["backend_branch"] == "release_20260527"
    assert result["frontend_branch"] == "release_20260527"
    assert result["help_docs_svn_revision"] == "2024"
    assert result["source"] == "http://example.test/svn/お客様環境/資材-20260527/version.txt"
    assert calls[0][-1] == result["source"]


def test_extract_nho_release_branches_from_rows():
    server = load_server()
    rows = [
        ["①Frontend"],
        ["No", "gitlab-branch", "tag名"],
        ["1", "release_20260316", ""],
        ["②Backend"],
        ["No", "gitlab-branch", "tag名"],
        ["1", "無し", ""],
        ["③汎用マスタデータ"],
    ]

    assert server.branch_from_release_section(rows, "Frontend") == "release_20260316"
    assert server.branch_from_release_section(rows, "Backend") == ""


def test_nho_release_checklist_is_found_recursively_from_material_root(monkeypatch):
    server = load_server()
    text_calls = []
    binary_calls = []

    def fake_run_svn_text(args, timeout=60):
        text_calls.append(args)
        return "memo/\n別紙/リリースチェックリスト_old.xlsx\n深い/階層/リリースチェックリスト.xlsx\n製品/リリースチェックリスト.xlsx\n"

    def fake_run_svn_binary(args, timeout=120):
        binary_calls.append(args)
        return b"xlsx"

    monkeypatch.setattr(server, "run_svn_text", fake_run_svn_text)
    monkeypatch.setattr(server, "run_svn_binary", fake_run_svn_binary)
    monkeypatch.setattr(server, "extract_nho_release_branches_from_xlsx", lambda data: {"frontend_branch": "release_fe", "backend_branch": "release_be"})
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_URL", "http://example.test/svn/97.リリース作業")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_USERNAME", "svn-user")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_PASSWORD", "svn-pass")

    result = server.get_nho_material_release_branches("20260325")

    assert result["frontend_branch"] == "release_fe"
    assert result["backend_branch"] == "release_be"
    assert result["source"] == "http://example.test/svn/97.リリース作業/20260325リリース作業/製品/リリースチェックリスト.xlsx"
    assert text_calls[0][-1] == "http://example.test/svn/97.リリース作業/20260325リリース作業"
    assert "-R" in text_calls[0]
    assert binary_calls[0][-1] == result["source"]


def test_nho_material_release_branches_require_build_terminal_svn_credentials(monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_USERNAME", "")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_PASSWORD", "")

    with pytest.raises(RuntimeError, match="NHO material SVN credentials are missing on build terminal"):
        server.get_nho_material_release_branches("20260325")


def test_nho_material_database_assets_are_exported_as_zip(monkeypatch):
    server = load_server()
    calls = []

    def fake_run_svn_text(args, timeout=60):
        calls.append(args)
        target = Path(args[-1])
        target.mkdir(parents=True, exist_ok=True)
        if target.name == "データ連携":
            (target / "ohr").mkdir()
            (target / "ohr" / "upds_in_kihon_joho.sql").write_text("kihon", encoding="utf-8")
            (target / "ohr" / "upds_in_organisation.sql").write_text("organisation", encoding="utf-8")
            (target / "データ連携プロシージャ.xlsx").write_bytes(b"xlsx")
        elif target.name == "製品":
            (target / "ohr").mkdir()
            (target / "tenant").mkdir()
            (target / "ohr" / "ohr_menu_resource.sql").write_text("menu", encoding="utf-8")
            (target / "tenant" / "i18n_web_message.sql").write_text("i18n", encoding="utf-8")
            (target / "リリースチェックリスト.xlsx").write_bytes(b"xlsx")
        return "exported"

    monkeypatch.setattr(server, "run_svn_text", fake_run_svn_text)
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_URL", "http://example.test/svn/大連側/97.リリース作業")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_USERNAME", "svn-user")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_PASSWORD", "svn-pass")

    data = server.export_nho_material_database_assets_zip("20260325")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = set(z.namelist())

    assert len(calls) == 2
    assert "export" in calls[0]
    assert "--force" in calls[0]
    assert "データ連携/ohr/upds_in_kihon_joho.sql" in members
    assert "データ連携/ohr/upds_in_organisation.sql" in members
    assert "製品/ohr/ohr_menu_resource.sql" in members
    assert "製品/tenant/i18n_web_message.sql" in members
    assert "データ連携/データ連携プロシージャ.xlsx" not in members
    assert "製品/リリースチェックリスト.xlsx" not in members


def test_nho_material_database_assets_require_build_terminal_svn_credentials(monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_USERNAME", "")
    monkeypatch.setattr(server, "NHO_MATERIAL_SVN_PASSWORD", "")

    with pytest.raises(RuntimeError, match="NHO material SVN credentials are missing on build terminal"):
        server.export_nho_material_database_assets_zip("20260325")


def test_list_release_branches_for_url_parses_refs(monkeypatch):
    server = load_server()

    class Result:
        returncode = 0
        stdout = (
            "abc\trefs/heads/release_20260501\n"
            "def\trefs/heads/feature/demo\n"
            "ghi\trefs/heads/release_20260502\n"
        )
        stderr = ""

    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: Result())

    assert server.list_release_branches_for_url("https://example.test/repo.git") == [
        "release_20260502",
        "release_20260501",
    ]


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
    assert "HELP_DOCS_SVN_REVISION" in script
    assert 'SVN_REV_ARGS=(-r "$HELP_DOCS_SVN_REVISION")' in script
    assert 'if [ "${BUILD_HELP:-true}" = "true" ]; then' in script
    assert "Help 构建已跳过" in script
    assert "pnpm i --frozen-lockfile --prefer-offline" in script
    assert "git -C \"$CICD_DIR\" clean -fd -e node_modules" in script
    assert "-e .ci-cache" in script
    assert "[cache yarn] ohr-cicd unchanged; skip yarn install" in script
    assert "STANDARD_NODE_OPTIONS" in script
    assert "--max-old-space-size=4096" in script
    assert "NODE_OPTIONS=--max_old_space_size=4096" in script
    assert "apply_standard_low_memory_overrides" in script
    assert 'replace("npm run build:parallel", "npm run build")' in script
    assert 'replace("ohr-cli mono-build --parallel", "ohr-cli mono-build")' in script
    assert "--concurrency 1" in script
    assert "前端发布包生成失败" in script
    assert 'zip -r "$OUT_WEB_ZIP" .' not in script
    assert "node_modules/*" not in script
    assert 'mkdir -p "$(dirname "$OUT_WEB_ZIP")" "$OUT_TMP_DIR"' in script
    assert 'publish_root="$(mktemp -d "$OUT_TMP_DIR/publish.XXXXXX")' in script

    restore_script = server.DIRECT_FRONTEND_RESTORE_SCRIPT
    assert "pnpm_install_cached . ohr-workspace" in restore_script
    assert "[cache pnpm] $name unchanged; skip pnpm i" in restore_script
    assert "git clean -fd -e node_modules" in restore_script
    assert "-e .ci-cache" in restore_script


def test_build_console_service_keeps_api_alive_on_child_oom():
    root = Path(__file__).resolve().parents[1]
    service = (root / "deploy" / "build-console" / "ohr-build-console.service").read_text(encoding="utf-8")

    assert "OOMPolicy=continue" in service


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
            "help_docs_svn_revision": "12345",
            "build_help": False,
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
    assert Path(env["OUT_TMP_DIR"]).parts[-3:] == ("standard", "20260514120000", "tmp")
    assert env["HELP_DOCS_BRANCH"] == "release_ci"
    assert env["HELP_DOCS_SVN_REVISION"] == "12345"
    assert env["BUILD_HELP"] == "false"
    assert env["BUILD_CONF_PROD"] == "true"
    assert env["CONF_SERVER_HOST"] == "customer.local"
    assert env["CONF_ENABLE_HTTPS"] == "true"


def test_build_conf_prod_can_be_disabled_for_frontend_builds(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server, "run_direct_build", lambda build_id: None)
    monkeypatch.setattr(server, "EXECUTOR", "direct")

    meta = server.create_build(
        {
            "product_variant": "nho",
            "build_backend": False,
            "build_frontend": True,
            "frontend_release_branch": "release_20260522",
            "build_conf_prod": False,
        }
    )

    assert meta["request"]["build_conf_prod"] is False
    assert meta["request"]["conf_server_host"] == ""


def test_build_console_log_rendering_keeps_fixed_line_window():
    server = load_server()

    assert "const MAX_LOG_LINES = embeddedMode ? 900 : 1600" in server.APP_JS
    assert "function appendLogText(text)" in server.APP_JS
    assert "logLines = logLines.slice(logLines.length - MAX_LOG_LINES)" in server.APP_JS
    assert "shouldStickToBottom" in server.APP_JS
    assert "pre.textContent += translateLogText" not in server.APP_JS


def test_append_log_strips_ansi_escape_sequences(tmp_path, monkeypatch):
    server = load_server()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    build_id = "20260527000102"
    server.build_dir(build_id).mkdir(parents=True)

    server.append_log(build_id, "\x1b[36mdist/static/js/app.js\x1b[39m")

    assert server.log_path(build_id).read_text(encoding="utf-8") == "dist/static/js/app.js\n"
