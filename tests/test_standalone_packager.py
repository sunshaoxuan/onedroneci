from __future__ import annotations

import zipfile
from pathlib import Path

from standalone_packager import (
    CONFIG_IN_STANDALONE_ZIP,
    PACKAGE_IN_STANDALONE_ZIP,
    WEB_IN_STANDALONE_ZIP,
    BuildVersion,
    ProductSqlConfig,
    StandaloneConfig,
    build_product_package,
    default_organisation_dstart,
    patch_account_sql,
    render_version_txt,
    update_config_ini,
)


CONFIG = """; env
[env]
MINIO_HOST=localhost
MINIO_PORT=19000
POSTGRESQL_HOST=192.168.10.209
POSTGRESQL_PORT=5432
POSTGRESQL_USER=postgres
POSTGRESQL_PASS=password
OHR_HOST_ADDRESS=OLD-HOST
OHR_SERVICE_PORT=3198
"""


def make_template(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(CONFIG_IN_STANDALONE_ZIP, CONFIG)
        z.writestr(PACKAGE_IN_STANDALONE_ZIP, b"old-package")
        z.writestr(WEB_IN_STANDALONE_ZIP, b"old-web")
        z.writestr("OneHrStandalone/software/jdk.zip", b"fixed-jdk")
        z.writestr("OneHrStandalone/bin/kernel/start.ps1", "start")


def make_sql_templates(path: Path) -> None:
    (path / "1.tenant").mkdir(parents=True)
    (path / "2.ohr").mkdir(parents=True)
    (path / "1.tenant" / "ohr_help.sql").write_text("old help", encoding="utf-8")
    (path / "1.tenant" / "url_info.sql").write_text("select '/api/x';", encoding="utf-8")
    (path / "2.ohr" / "4.account.sql").write_text(
        """INSERT INTO "mdm_organisation" ("szk_code", "dstart", "dend", "sname", "rname", "parent_id", "data_kbn", "comment", "create_user", "create_time", "update_user", "update_time", "delete_flag", "hierarchy", "campus", "hierarchy_name", "campus_name", "szk_bu_ka", "record") VALUES ('000000', '2025-07-01', '2222-12-31', '{"ja-JP": "OLD"}', '{"ja-JP": "OLD"}', NULL, '1', NULL, 'RENKEI', '2025-05-13 12:54:15.945549+00', 'RENKEI', '2025-05-13 12:54:15.945549+00', 'f', '\\000000', NULL, '{"ja-JP": "\\OLD"}', NULL, '{"ja-JP": "OLD"}', NULL);
""",
        encoding="utf-8",
    )
    (path / "2.ohr" / "5.ohr.sql").write_text("update ohr_menu set urls = null;", encoding="utf-8")


def test_render_version_txt_records_branches():
    assert render_version_txt(BuildVersion("b1", "release_back", "release_front")) == (
        "資材:b1\n前台分支：release_front\n后台分支：release_back\n"
    )


def test_update_config_ini_replaces_database_and_ohr_values():
    text = update_config_ini(
        CONFIG,
        StandaloneConfig(
            postgresql_host="10.0.0.8",
            postgresql_port=15432,
            postgresql_user="ohr",
            postgresql_password="secret",
            ohr_host_address="OHR-HOST",
            ohr_service_port=33198,
        ),
    )
    assert "POSTGRESQL_HOST=10.0.0.8" in text
    assert "POSTGRESQL_PORT=15432" in text
    assert "POSTGRESQL_USER=ohr" in text
    assert "POSTGRESQL_PASS=secret" in text
    assert "OHR_HOST_ADDRESS=OHR-HOST" in text
    assert "OHR_SERVICE_PORT=33198" in text
    assert "MINIO_HOST=localhost" in text


def test_build_product_package_replaces_only_dynamic_zip_members_and_help_sql(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    data_sync_repo = tmp_path / "data-sync-repo"
    data_sync_work = tmp_path / "data-sync-work"
    make_template(template)
    make_sql_templates(sql_dir)
    (data_sync_repo / "updsv7phr" / "PHR").mkdir(parents=True)
    (data_sync_repo / "updsv7phr" / "PHR" / "00_all_updsv7tophr.sql").write_text("data sync", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init", "-b", "master"], cwd=data_sync_repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.local"], cwd=data_sync_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=data_sync_repo, check=True)
    subprocess.run(["git", "add", "."], cwd=data_sync_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=data_sync_repo, check=True)
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", "new help sql")
        z.writestr("ohr-cicd/web_prod/meta.json", "{}")

    result = build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-1", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        data_sync_git_url=str(data_sync_repo),
        data_sync_dir=data_sync_work,
    )

    delivery_root = Path(result["product_dir"])
    product_dir = delivery_root / "製品"
    assert delivery_root == output / "build-1"
    assert product_dir.is_dir()
    assert (delivery_root / "データ連携" / "00_all_updsv7tophr.sql").read_text(encoding="utf-8") == "data sync"
    assert (product_dir / "version.txt").read_text(encoding="utf-8") == (
        "資材:build-1\n前台分支：release_front\n后台分支：release_back\n"
    )
    assert (product_dir / "1.tenant" / "ohr_help.sql").read_text(encoding="utf-8") == "new help sql"
    account_sql = (product_dir / "2.ohr" / "4.account.sql").read_text(encoding="utf-8")
    assert "'2026-05-01'" in account_sql
    assert '{"ja-JP": "テスト大学"}' in account_sql
    assert '{"ja-JP": "\\\\テスト大学"}' in account_sql
    assert "10.0.0.8" not in (product_dir / "1.tenant" / "url_info.sql").read_text(encoding="utf-8")

    with zipfile.ZipFile(result["standalone_zip"]) as z:
        assert z.read(PACKAGE_IN_STANDALONE_ZIP) == b"new-package"
        assert z.read(WEB_IN_STANDALONE_ZIP) == web_zip.read_bytes()
        assert z.read("OneHrStandalone/software/jdk.zip") == b"fixed-jdk"
        config = z.read(CONFIG_IN_STANDALONE_ZIP).decode("utf-8")
        assert "POSTGRESQL_HOST=10.0.0.8" in config
        assert "OHR_HOST_ADDRESS=OHR-HOST" in config


def test_patch_account_sql_replaces_organisation_values():
    source = (Path("tests") / "製品" / "2.ohr" / "4.account.sql").read_text(encoding="utf-8")
    patched = patch_account_sql(source, ProductSqlConfig("学校法人サンプル", "2026-06-01"))

    assert "'2026-06-01'" in patched
    assert '{"ja-JP": "学校法人サンプル"}' in patched
    assert '{"ja-JP": "\\\\学校法人サンプル"}' in patched
    assert "国立大学法人北陸先端科学技術大学院大学" not in patched


def test_data_sync_git_uses_shallow_clone_and_timeout(monkeypatch, tmp_path):
    import standalone_packager as packager

    calls: list[tuple[list[str], int | None]] = []

    def fake_run(cmd, timeout):
        calls.append((cmd, timeout))

    monkeypatch.setattr(packager, "_run_git", fake_run)

    packager.sync_git_tree("https://example.test/data.git", "master", tmp_path / "data-sync", timeout=123)

    assert calls == [
        (
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                "master",
                "https://example.test/data.git",
                str(tmp_path / "data-sync"),
            ],
            123,
        )
    ]


def test_data_sync_git_uses_sparse_clone_for_subdir(monkeypatch, tmp_path):
    import standalone_packager as packager

    calls: list[list[str]] = []

    def fake_run(cmd, timeout):
        calls.append(cmd)

    monkeypatch.setattr(packager, "_run_git", fake_run)

    packager.sync_git_tree(
        "https://example.test/data.git",
        "master",
        tmp_path / "data-sync",
        timeout=123,
        sparse_path="updsv7phr/PHR",
    )

    assert calls[0][:7] == ["git", "clone", "--depth", "1", "--single-branch", "--filter=blob:none", "--sparse"]
    assert calls[1] == ["git", "-C", str(tmp_path / "data-sync"), "sparse-checkout", "set", "updsv7phr/PHR"]


def test_data_sync_git_url_uses_existing_git_token(monkeypatch):
    import standalone_packager as packager

    monkeypatch.setenv("DATA_SYNC_GIT_URL", "https://example.test/ohr/data-synchronization.git")
    monkeypatch.setenv("OHR_BACK_GIT_TOKEN", "secret token")
    monkeypatch.delenv("DATA_SYNC_GIT_TOKEN", raising=False)
    monkeypatch.delenv("FRONTEND_GIT_TOKEN", raising=False)

    assert packager.configured_data_sync_git_url() == (
        "https://oauth2:secret%20token@example.test/ohr/data-synchronization.git"
    )


def test_git_errors_include_stderr_without_credentials(monkeypatch):
    import subprocess
    import standalone_packager as packager

    class FakeProcess:
        returncode = 128

        def communicate(self, timeout=None):
            return "", "fatal: https://oauth2:secret@example.test/repo.git failed"

    monkeypatch.setattr(packager.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    try:
        packager._run_git(["git", "clone", "https://example.test/repo.git"], timeout=1)
    except subprocess.CalledProcessError as exc:
        assert "<redacted>" in exc.stderr
        assert "secret" not in exc.stderr
    else:
        raise AssertionError("git failure should raise")


def test_git_failure_message_includes_stderr_without_credentials():
    import subprocess
    import standalone_packager as packager

    exc = subprocess.CalledProcessError(
        128,
        ["git", "clone"],
        stderr="fatal: https://oauth2:secret@example.test/repo.git failed",
    )

    message = packager.format_git_failure(exc)

    assert "exit 128" in message
    assert "<redacted>" in message
    assert "secret" not in message


def test_data_sync_uses_existing_cache_when_fetch_fails(monkeypatch, tmp_path):
    import subprocess
    import standalone_packager as packager

    workdir = tmp_path / "data-sync-work"
    target = tmp_path / "target"
    cached = workdir / "updsv7phr" / "PHR"
    cached.mkdir(parents=True)
    (cached / "00_all_updsv7tophr.sql").write_text("cached", encoding="utf-8")

    def fail_sync(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ["git", "fetch"], stderr="fatal: auth failed")

    logs: list[str] = []
    monkeypatch.setattr(packager, "sync_git_tree", fail_sync)

    packager.copy_data_sync_assets(
        repo_url="https://example.test/data.git",
        branch="master",
        workdir=workdir,
        subdir="updsv7phr/PHR",
        target_dir=target,
        logger=logs.append,
    )

    assert (target / "00_all_updsv7tophr.sql").read_text(encoding="utf-8") == "cached"
    assert "data_sync_cache_fallback" in logs


def test_data_sync_raises_git_stderr_when_no_cache(monkeypatch, tmp_path):
    import subprocess
    import standalone_packager as packager

    def fail_sync(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ["git", "clone"], stderr="fatal: auth failed")

    monkeypatch.setattr(packager, "sync_git_tree", fail_sync)

    try:
        packager.copy_data_sync_assets(
            repo_url="https://example.test/data.git",
            branch="master",
            workdir=tmp_path / "data-sync-work",
            subdir="updsv7phr/PHR",
            target_dir=tmp_path / "target",
        )
    except RuntimeError as exc:
        assert "fatal: auth failed" in str(exc)
    else:
        raise AssertionError("missing cache should raise git failure")


def test_build_product_package_emits_stage_logs(tmp_path, monkeypatch):
    import standalone_packager as packager

    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    data_sync_work = tmp_path / "data-sync-work"
    make_template(template)
    make_sql_templates(sql_dir)
    (data_sync_work / "updsv7phr" / "PHR").mkdir(parents=True)
    (data_sync_work / "updsv7phr" / "PHR" / "00_all_updsv7tophr.sql").write_text("sync", encoding="utf-8")
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/meta.json", "{}")
    monkeypatch.setattr(packager, "sync_git_tree", lambda repo_url, branch, workdir, **kwargs: None)
    logs: list[str] = []

    build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-logs", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        data_sync_git_url="https://example.test/data.git",
        data_sync_dir=data_sync_work,
        logger=logs.append,
    )

    assert "data_sync_git_sync" in logs
    assert "data_sync_copy" in logs
    assert "standalone_zip_rebuild" in logs


def test_default_organisation_dstart_uses_first_day_of_month():
    from datetime import date

    assert default_organisation_dstart(date(2026, 5, 14)) == "2026-05-01"
