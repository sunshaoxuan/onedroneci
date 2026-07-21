from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

from standalone_packager import (
    CONFIG_IN_STANDALONE_ZIP,
    MIDDLEWARE_IN_STANDALONE_ZIP,
    PACKAGE_IN_STANDALONE_ZIP,
    WEB_IN_STANDALONE_ZIP,
    BuildVersion,
    CustomPackageSelection,
    DataSyncSqlRunnerConfig,
    OhrImportConfig,
    OhrMenuDisable,
    OhrScheduledTaskDisable,
    ProductSqlConfig,
    StandaloneConfig,
    TenantImportConfig,
    build_nho_common_package,
    build_custom_package,
    build_product_package,
    complete_all_sql_scripts,
    default_organisation_dstart,
    fetch_nginx_releases,
    help_sql_from_web_zip,
    inspect_artifact_versions,
    patch_account_sql,
    render_ohr_import_sql,
    render_tenant_import_sql,
    render_version_txt,
    update_config_ini,
    _set_azure_proxy_enabled,
    _rebuild_standalone_zip,
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


def make_nested_zip(path: Path, root: str, files: dict[str, str | bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{root}/", b"")
        for name, data in files.items():
            payload = data.encode("utf-8") if isinstance(data, str) else data
            z.writestr(f"{root}/{name}", payload)


def make_template(path: Path) -> None:
    temp_dir = path.parent / f"{path.stem}-middleware"
    temp_dir.mkdir(parents=True, exist_ok=True)
    nginx = temp_dir / "nginx.zip"
    redis = temp_dir / "redis.zip"
    minio = temp_dir / "minio.zip"
    make_nested_zip(nginx, "nginx", {"docs/CHANGES": "Changes with nginx 1.26.2\n"})
    make_nested_zip(redis, "redis", {"00-RELEASENOTES": "Redis 5.0.9     Released Thu Apr 17 12:41:00 CET 2020\n"})
    make_nested_zip(minio, "minio", {"minio.exe": b"old-minio", "start.bat": "minio.exe server data\r\n"})
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(CONFIG_IN_STANDALONE_ZIP, CONFIG)
        z.writestr(PACKAGE_IN_STANDALONE_ZIP, b"old-package")
        z.writestr(WEB_IN_STANDALONE_ZIP, b"old-web")
        z.writestr("OneHrStandalone/software/jdk.zip", b"fixed-jdk")
        z.write(nginx, MIDDLEWARE_IN_STANDALONE_ZIP["nginx"])
        z.write(redis, MIDDLEWARE_IN_STANDALONE_ZIP["redis"])
        z.write(minio, MIDDLEWARE_IN_STANDALONE_ZIP["minio"])
        z.writestr("OneHrStandalone/bin/kernel/start.ps1", "start")


def make_backend_package(path: Path) -> None:
    jar_path = path.parent / "standalone.jar"
    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as jar:
        jar.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\n"
            "Implementation-Version: 1.0.0\n"
            "Spring-Boot-Version: 3.5.0\n"
            "Build-Jdk-Spec: 24\n",
        )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.write(jar_path, "package/standalone.jar")


def make_web_package(path: Path, help_sql: str = "new help sql") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as web:
        web.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", help_sql)
        web.writestr(
            "ohr-cicd/web_prod/meta.json",
            '{"releaseTimestamp":"release_2026_01_01_00_00_00","gitInfo":{"ohr-feelin":{"branch":"release_front","latestCommit":"abcdef1234567890"}}}',
        )
        web.writestr(
            "ohr-cicd/web_prod/help/meta.json",
            '{"releaseTimestamp":"ohr_help_docs_release_2026_01_01","gitInfo":{"branch":"release_ci","latestCommit":"1234567890abcdef"}}',
        )
        web.writestr(
            "ohr-cicd/conf_prod/api-proxy.conf",
            "# location ~ ^/azure/(.*)$ {\n# \tproxy_pass undefined;\n# }\n",
        )
        web.writestr(
            "ohr-cicd/conf_prod/api-proxy-debug.conf",
            "location ~ ^/azure/(.*)$ {\n\tproxy_pass undefined;\n}\n",
        )


def zip_members(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as z:
        return set(z.namelist())


def zip_text(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def test_fetch_nginx_releases_uses_download_index_history(monkeypatch):
    import standalone_packager as packager

    html = """
    <a href="nginx-1.30.3.zip">nginx-1.30.3.zip</a>
    <a href="nginx-1.30.2.zip">nginx-1.30.2.zip</a>
    <a href="nginx-1.31.2.zip">nginx-1.31.2.zip</a>
    <a href="nginx-1.30.2.zip.asc">nginx-1.30.2.zip.asc</a>
    """

    def fake_urlopen_text(url: str, timeout: int = 20) -> str:
        assert url == packager.NGINX_DOWNLOAD_INDEX
        return html

    monkeypatch.setattr(packager, "_urlopen_text", fake_urlopen_text)

    releases = fetch_nginx_releases(limit=10)

    assert [release.version for release in releases] == ["1.31.2", "1.30.3", "1.30.2"]
    assert releases[-1].url == "https://nginx.org/download/nginx-1.30.2.zip"


def test_build_cached_middleware_zip_merges_addons(monkeypatch, tmp_path):
    import standalone_packager as packager

    addons = tmp_path / "addons"
    (addons / "redis").mkdir(parents=True)
    (addons / "redis" / "startup.cmd").write_text("addon startup", encoding="utf-8")
    (addons / "redis" / "redis.windows.conf").write_text("addon conf", encoding="utf-8")
    source = tmp_path / "redis-source.zip"
    make_nested_zip(
        source,
        "Redis-x64",
        {
            "redis-server.exe": b"exe",
            "startup.cmd": "source startup",
        },
    )
    template = tmp_path / "template.zip"
    make_template(template)
    cache_zip = tmp_path / "cache" / "redis.zip"
    monkeypatch.setenv("MIDDLEWARE_ADDONS_DIR", str(addons))
    monkeypatch.setattr(packager, "_download_file", lambda url, destination: shutil.copy2(source, destination))

    packager._build_cached_middleware_zip("redis", "8.8.0", "https://example.local/redis.zip", cache_zip, template)

    with zipfile.ZipFile(cache_zip) as z:
        names = z.namelist()
        assert len(names) == len(set(names))
        assert z.read("redis/startup.cmd").decode("utf-8") == "addon startup"
        assert z.read("redis/redis.windows.conf").decode("utf-8") == "addon conf"
        assert z.read("redis/redis-server.exe") == b"exe"
        assert "redis/.ohr-builder-version.json" in names


def test_prepare_middleware_overrides_rebuilds_cache_when_addons_are_missing(monkeypatch, tmp_path):
    import standalone_packager as packager

    addons = tmp_path / "addons"
    (addons / "nginx").mkdir(parents=True)
    (addons / "nginx" / "startup.bat").write_text("addon startup", encoding="utf-8")
    old_cache = tmp_path / "cache" / "nginx" / "1.30.2" / "nginx.zip"
    old_cache.parent.mkdir(parents=True)
    make_nested_zip(old_cache, "nginx", {"nginx.exe": b"old"})
    source = tmp_path / "nginx-source.zip"
    make_nested_zip(source, "nginx-1.30.2", {"nginx.exe": b"new"})
    template = tmp_path / "template.zip"
    make_template(template)
    monkeypatch.setenv("MIDDLEWARE_ADDONS_DIR", str(addons))
    monkeypatch.setattr(packager, "_find_release", lambda product, version: packager.MiddlewareRelease(product, version, "https://example.local/nginx.zip"))
    monkeypatch.setattr(packager, "_download_file", lambda url, destination: shutil.copy2(source, destination))

    overrides = packager.prepare_middleware_overrides(
        {"nginx": "1.30.2"},
        template_zip=template,
        cache_dir=tmp_path / "cache",
    )

    assert overrides[packager.MIDDLEWARE_IN_STANDALONE_ZIP["nginx"]] == old_cache
    with zipfile.ZipFile(old_cache) as z:
        assert z.read("nginx/startup.bat").decode("utf-8") == "addon startup"
        assert z.read("nginx/nginx.exe") == b"new"


def test_build_nho_common_package_frontend_only(tmp_path):
    web_zip = tmp_path / "web.zip"
    web_zip.write_bytes(b"web")

    result = build_nho_common_package(
        output_root=tmp_path / "out",
        build_id="job1",
        web_zip=web_zip,
        version=BuildVersion("job1", "NHO-M-001", "-", "release_front"),
    )

    common_zip = Path(result["common_zip"])
    assert common_zip == tmp_path / "out" / "job1" / "共通.zip"
    assert "version_txt" not in result
    assert not (tmp_path / "out" / "job1" / "version.txt").exists()
    members = zip_members(common_zip)
    assert "共通/upgrade/readme.txt" in members
    assert "共通/version.txt" in members
    assert zip_text(common_zip, "共通/version.txt") == (
        "資材:NHO-M-001\n前台分支：release_front\n后台分支：-\n"
    )
    assert "共通/upgrade/実行環境資材/OneHrSuite/software/web.zip" in members
    assert "共通/upgrade/実行環境資材/OneHrSuite/software/package.zip" not in members
    readme = zip_text(common_zip, "共通/upgrade/readme.txt")
    assert "実行環境資材¥OneHrSuite" in readme
    assert "web.zip" in readme
    assert "package.zip" not in readme


def test_build_nho_common_package_backend_only_and_both(tmp_path):
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    package_zip.write_bytes(b"package")
    web_zip.write_bytes(b"web")

    backend_only = build_nho_common_package(output_root=tmp_path / "out", build_id="backend", package_zip=package_zip)
    assert "共通/upgrade/実行環境資材/OneHrSuite/software/package.zip" in zip_members(Path(backend_only["common_zip"]))

    both = build_nho_common_package(output_root=tmp_path / "out", build_id="both", package_zip=package_zip, web_zip=web_zip)
    members = zip_members(Path(both["common_zip"]))
    assert "共通/upgrade/実行環境資材/OneHrSuite/software/package.zip" in members
    assert "共通/upgrade/実行環境資材/OneHrSuite/software/web.zip" in members


def test_build_nho_common_package_can_use_custom_delivery_name(tmp_path):
    web_zip = tmp_path / "web.zip"
    web_zip.write_bytes(b"web")

    result = build_nho_common_package(
        output_root=tmp_path / "out",
        build_id="job1",
        delivery_name="NHO顧客 20260623000106",
        web_zip=web_zip,
    )

    assert Path(result["product_dir"]) == tmp_path / "out" / "NHO顧客 20260623000106"
    assert Path(result["common_zip"]) == tmp_path / "out" / "NHO顧客 20260623000106" / "共通.zip"


def test_build_nho_common_package_includes_database_assets(tmp_path):
    web_zip = tmp_path / "web.zip"
    web_zip.write_bytes(b"web")
    database_assets_zip = tmp_path / "database-assets.zip"
    with zipfile.ZipFile(database_assets_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("データ連携/ohr/upds_in_kihon_joho.sql", "kihon")
        z.writestr("データ連携/ohr/upds_in_organisation.sql", "organisation")
        z.writestr("製品/ohr/ohr_menu_resource.sql", "menu")
        z.writestr("製品/tenant/i18n_web_message.sql", "i18n")

    result = build_nho_common_package(
        output_root=tmp_path / "out",
        build_id="nho-db",
        web_zip=web_zip,
        database_assets_zip=database_assets_zip,
    )

    members = zip_members(Path(result["common_zip"]))
    assert "共通/upgrade/データベース資材/データ連携/ohr/upds_in_kihon_joho.sql" in members
    assert "共通/upgrade/データベース資材/データ連携/ohr/upds_in_organisation.sql" in members
    assert "共通/upgrade/データベース資材/製品/ohr/ohr_menu_resource.sql" in members
    assert "共通/upgrade/データベース資材/製品/tenant/i18n_web_message.sql" in members
    assert result["database_assets_zip"].endswith("database-assets.zip")
    readme = zip_text(Path(result["common_zip"]), "共通/upgrade/readme.txt")
    assert "■■■■■■■■■■■■■■■実行手順■■■■■■■■■■■■■■■" in readme
    assert "■　【データベース資材】フォルダのSQLスクリプトを実行する" in readme
    assert "□　【データ連携】" in readme
    assert "　　□　【Ohr】データベース" in readme
    assert "-upds_in_kihon_joho.sql" in readme
    assert "-upds_in_organisation.sql" in readme
    assert "□　【製品】" in readme
    assert "　　□　【Tenant】データベース" in readme
    assert "-i18n_web_message.sql" in readme
    assert "実行環境資材¥OneHrSuite" in readme
    assert "■■■■■■■■■■■■■■■資材一覧■■■■■■■■■■■■■■■" in readme
    assert "├─データベース資材" in readme
    assert "upds_in_kihon_joho.sql" in readme
    assert "└─実行環境資材" in readme
    assert "web.zip" in readme


def make_sql_templates(path: Path) -> None:
    (path / "1.tenant").mkdir(parents=True)
    (path / "2.ohr").mkdir(parents=True)
    (path / "1.tenant" / "ohr_help.sql").write_text("old help", encoding="utf-8")
    (path / "1.tenant" / "url_info.sql").write_text("select '/api/x';", encoding="utf-8")
    (path / "1.tenant" / "all.sql").write_text("\\i url_info.sql\n", encoding="utf-8")
    (path / "2.ohr" / "4.account.sql").write_text(
        """INSERT INTO "mdm_organisation" ("szk_code", "dstart", "dend", "sname", "rname", "parent_id", "data_kbn", "comment", "create_user", "create_time", "update_user", "update_time", "delete_flag", "hierarchy", "campus", "hierarchy_name", "campus_name", "szk_bu_ka", "record") VALUES ('000000', '2025-07-01', '2222-12-31', '{"ja-JP": "OLD"}', '{"ja-JP": "OLD"}', NULL, '1', NULL, 'RENKEI', '2025-05-13 12:54:15.945549+00', 'RENKEI', '2025-05-13 12:54:15.945549+00', 'f', '\\000000', NULL, '{"ja-JP": "\\OLD"}', NULL, '{"ja-JP": "OLD"}', NULL);
""",
        encoding="utf-8",
    )
    (path / "2.ohr" / "5.ohr.sql").write_text("update ohr_menu set urls = null;", encoding="utf-8")
    (path / "2.ohr" / "all.sql").write_text("\\i 4.account.sql", encoding="utf-8")


def test_render_version_txt_records_branches():
    assert render_version_txt(BuildVersion("build-1", "M-001", "release_back", "release_front")) == (
        "資材:M-001\n前台分支：release_front\n后台分支：release_back\n"
    )


def test_render_tenant_import_sql_records_import_plan():
    sql = render_tenant_import_sql(
        TenantImportConfig(
            support_applications=("em", "mdm", "personal-portal", "taxadjustment"),
            enable_email=False,
            enable_transport_setting=False,
            enable_lecture=True,
        )
    )

    assert "support_applications = '{em,mdm,personal-portal,taxadjustment}'" in sql
    assert "{enableEmail}', 'false'" in sql
    assert "{enableTransportSetting}', 'false'" in sql
    assert "{enableLecture}', 'true'" in sql


def test_render_ohr_import_sql_records_menu_and_task_updates():
    sql = render_ohr_import_sql(
        OhrImportConfig(
            disabled_menus=(
                OhrMenuDisable("個人ポータル / プロフィール", "personal-portal", "EM_PR_MBR"),
                OhrMenuDisable("個人ポータル / 給与明細", "personal-portal", "EM_PR_PYR", True),
            ),
            disabled_scheduled_tasks=(
                OhrScheduledTaskDisable(
                    "庶務事務 / 公開通知：発令情報",
                    "a690a435-5055-4c7f-80c8-5ea3d717d0cd",
                    "send-de-mail-batch",
                    "stm.em-send-de-mail-batch.label",
                    "em",
                ),
                OhrScheduledTaskDisable(
                    "庶務事務 / データ連携：Public人事給与→発令情報",
                    "604b907c-f82d-4737-9b6f-fefc65c08dc7",
                    "mdm-data-synchronization-decree-data",
                    "stm.mdm-data-synchronization-decree-data.label",
                    "em",
                    True,
                ),
            ),
        )
    )

    assert "update ohr_menu set enable = false" in sql
    assert "application_name = 'personal-portal' and menu_code = 'EM_PR_MBR'" in sql
    assert "update ohr_menu set enable = true" in sql
    assert "application_name = 'personal-portal' and menu_code = 'EM_PR_PYR'" in sql
    assert "\"ohr_scheduled_task\" set paused = true" in sql
    assert "'a690a435-5055-4c7f-80c8-5ea3d717d0cd'" in sql
    assert "display_flag = false" in sql
    assert "code = 'send-de-mail-batch'" in sql
    assert "\"ohr_scheduled_task\" set paused = false" in sql
    assert "display_flag = true" in sql
    assert "code = 'mdm-data-synchronization-decree-data'" in sql


def test_complete_all_sql_scripts_appends_missing_sibling_sql_files(tmp_path):
    scripts = tmp_path / "データ連携" / "Function"
    new_scripts = tmp_path / "データ連携" / "View"
    scripts.mkdir(parents=True)
    new_scripts.mkdir(parents=True)
    (scripts / "all.sql").write_text("\\i existing.sql\n\\i other_missing.sql", encoding="utf-8")
    (scripts / "existing.sql").write_text("select 1;", encoding="utf-8")
    (scripts / "missing.sql").write_text("select 2;", encoding="utf-8")
    (scripts / "space name.sql").write_text("select 3;", encoding="utf-8")
    (scripts / "other_missing.sql").write_text("select 4;", encoding="utf-8")
    (new_scripts / "01_view.sql").write_text("select 5;", encoding="utf-8")
    (new_scripts / "02_view.sql").write_text("select 6;", encoding="utf-8")

    completed = complete_all_sql_scripts(tmp_path)

    assert completed == {
        "データ連携/Function/all.sql": ["missing.sql", "space name.sql"],
        "データ連携/View/all.sql": ["01_view.sql", "02_view.sql"],
    }
    all_sql = (scripts / "all.sql").read_text(encoding="utf-8")
    assert all_sql.count("\\i existing.sql") == 1
    assert "\\i missing.sql" in all_sql
    assert '\\i "space name.sql"' in all_sql
    assert (new_scripts / "all.sql").read_text(encoding="utf-8") == "\\i 01_view.sql\n\\i 02_view.sql\n"


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
    (data_sync_repo / "updsv7phr" / "PHR" / "Table").mkdir()
    (data_sync_repo / "updsv7phr" / "PHR" / "View").mkdir()
    (data_sync_repo / "updsv7phr" / "PHR" / "Ignored").mkdir()
    (data_sync_repo / "updsv7phr" / "PHR" / "Table" / "01_table.sql").write_text("table sync", encoding="utf-8")
    (data_sync_repo / "updsv7phr" / "PHR" / "Table" / "all.sql").write_text("\\i existing.sql\n", encoding="utf-8")
    (data_sync_repo / "updsv7phr" / "PHR" / "Table" / "existing.sql").write_text("existing", encoding="utf-8")
    (data_sync_repo / "updsv7phr" / "PHR" / "View" / "02_view.sql").write_text("view sync", encoding="utf-8")
    (data_sync_repo / "updsv7phr" / "PHR" / "Ignored" / "99_ignore.sql").write_text("ignore", encoding="utf-8")
    (data_sync_repo / "updsv7phr" / "PHR" / "00_all_updsv7tophr.sql").write_text("ignored root file", encoding="utf-8")
    (data_sync_repo / "customv7phr" / "PHR" / "Table").mkdir(parents=True)
    (data_sync_repo / "customv7phr" / "PHR" / "Procedure").mkdir()
    (data_sync_repo / "customv7phr" / "PHR" / "Table" / "01_table.sql").write_text("custom table", encoding="utf-8")
    (data_sync_repo / "customv7phr" / "PHR" / "Procedure" / "02_custom.sql").write_text("custom procedure", encoding="utf-8")
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
        version=BuildVersion("build-1", "M-001", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        tenant_import_config=TenantImportConfig(
            support_applications=("em", "personal-portal"),
            enable_email=True,
            enable_transport_setting=False,
            enable_lecture=True,
        ),
        ohr_import_config=OhrImportConfig(
            disabled_menus=(OhrMenuDisable("個人ポータル / 源泉徴収票", "personal-portal", "EM_PR_TXW"),),
        ),
        data_sync_git_url=str(data_sync_repo),
        data_sync_dir=data_sync_work,
        data_sync_custom_subdir="customv7phr/PHR",
        data_sync_runner_config=DataSyncSqlRunnerConfig(
            ohr_host="10.0.0.8",
            ohr_port=15432,
            ohr_user="ohr_user",
            ohr_password="ohr'password",
            upds_host="10.0.0.9",
            upds_port=25432,
            upds_database="updsv7_customer",
            upds_user="upds_user",
            upds_password="upds_password",
        ),
    )

    delivery_root = Path(result["product_dir"])
    product_dir = delivery_root / "製品"
    assert delivery_root == output / "build-1"
    assert product_dir.is_dir()
    assert (delivery_root / "データ連携" / "Table" / "01_table.sql").read_text(encoding="utf-8") == "custom table"
    assert not (delivery_root / "データ連携" / "Table" / "all.sql").exists()
    assert "\\i 5.ohr.sql" in (product_dir / "2.ohr" / "all.sql").read_text(encoding="utf-8")
    assert "\\i ohr_help.sql" in (product_dir / "1.tenant" / "all.sql").read_text(encoding="utf-8")
    assert not (delivery_root / "データ連携" / "View" / "all.sql").exists()
    assert not (delivery_root / "データ連携" / "Procedure" / "all.sql").exists()
    assert (delivery_root / "データ連携" / "View" / "02_view.sql").read_text(encoding="utf-8") == "view sync"
    assert (delivery_root / "データ連携" / "Procedure" / "02_custom.sql").read_text(encoding="utf-8") == "custom procedure"
    assert not (delivery_root / "データ連携" / "Ignored").exists()
    assert not (delivery_root / "データ連携" / "00_all_updsv7tophr.sql").exists()
    runner_path = delivery_root / "データ連携" / "run_all_sql.ps1"
    runner = runner_path.read_text(encoding="utf-8-sig")
    assert result["data_sync_runner"] == str(runner_path)
    assert "[string]$OhrDbHost = '10.0.0.8'" in runner
    assert "[int]$OhrDbPort = 15432" in runner
    assert "[string]$OhrDbPassword = 'ohr''password'" in runner
    assert "[string]$UpdsDbHost = '10.0.0.9'" in runner
    assert "[int]$UpdsDbPort = 25432" in runner
    assert "[string]$UpdsDbName = 'updsv7_customer'" in runner
    assert "$TnToPhrHost = $OhrDbHost" in runner
    assert "Where-Object { $_.Name -ine 'all.sql' }" in runner
    assert "-Filter '*.sql' -Recurse" in runner
    assert "function Assert-SqlPlanCoverage" in runner
    assert "SQL execution plan coverage passed" in runner
    assert "Ordered SQL is not included in this package and was skipped" in runner
    assert "Where-Object { $_.Order -le 49 }" in runner
    assert "Where-Object { $_.Order -gt 49 }" in runner
    assert "$script:FailedSqlCount++" in runner
    assert 'throw "$($script:FailedSqlCount) SQL file(s) failed.' in runner
    assert "[string]$DjnSelfHostAddr" not in runner
    assert "@@" not in runner
    assert (product_dir / "version.txt").read_text(encoding="utf-8") == (
        "資材:M-001\n前台分支：release_front\n后台分支：release_back\n"
    )
    assert (product_dir / "1.tenant" / "ohr_help.sql").read_text(encoding="utf-8") == "DELETE FROM ohr_help;\nnew help sql"
    import_plan_sql = (delivery_root / "導入" / "tenant" / "import_plan.sql").read_text(encoding="utf-8")
    assert "support_applications = '{em,personal-portal}'" in import_plan_sql
    assert "{enableEmail}', 'true'" in import_plan_sql
    assert "{enableTransportSetting}', 'false'" in import_plan_sql
    assert "{enableLecture}', 'true'" in import_plan_sql
    assert not (product_dir / "1.tenant" / "99.import_plan.sql").exists()
    assert not (product_dir / "2.ohr" / "99.import_plan.sql").exists()
    ohr_import_plan_sql = (delivery_root / "導入" / "ohr" / "import_plan.sql").read_text(encoding="utf-8")
    assert "application_name = 'personal-portal' and menu_code = 'EM_PR_TXW'" in ohr_import_plan_sql
    account_sql = (product_dir / "2.ohr" / "4.account.sql").read_text(encoding="utf-8")
    assert "'2026-05-01'" in account_sql
    assert '{"ja-JP": "テスト大学"}' in account_sql
    assert '{"ja-JP": "\\\\テスト大学"}' in account_sql
    assert "10.0.0.8" not in (product_dir / "1.tenant" / "url_info.sql").read_text(encoding="utf-8")


def test_build_product_package_can_use_custom_delivery_name(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    make_template(template)
    make_sql_templates(sql_dir)
    package_zip.write_bytes(b"new-package")
    make_web_package(web_zip)

    result = build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        delivery_name="顧客A 20260623000105",
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("remote-1", "M-001", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("顧客A", "2026-06-01"),
        data_sync_git_url=None,
    )

    assert Path(result["product_dir"]) == output / "顧客A 20260623000105"
    assert (output / "顧客A 20260623000105" / "製品" / "OneHrStandalone.zip").is_file()


def test_build_custom_package_help_only_contains_only_web_zip(tmp_path):
    web_zip = tmp_path / "web.zip"
    make_web_package(web_zip)

    result = build_custom_package(
        template_zip=tmp_path / "unused-template.zip",
        sql_template_dir=tmp_path / "unused-sql",
        output_root=tmp_path / "out",
        delivery_name="顧客A custom-help",
        package_zip=None,
        web_zip=web_zip,
        selection=CustomPackageSelection(
            backend=False,
            frontend=False,
            help=True,
            conf_prod=False,
            sql_assets=False,
            data_sync=False,
            import_plan=False,
            runtime=False,
        ),
        version=BuildVersion("remote-1", "M-001", "", ""),
        config=StandaloneConfig(postgresql_host=""),
        sql_config=ProductSqlConfig("顧客A", "2026-07-01"),
    )

    delivery_root = Path(result["product_dir"])
    assert set(path.name for path in delivery_root.iterdir()) == {"web.zip"}
    assert Path(result["web_zip"]).read_bytes() == web_zip.read_bytes()
    assert "package_zip" not in result
    assert "standalone_zip" not in result


def test_build_custom_package_backend_runtime_excludes_template_web_zip(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    package_zip = tmp_path / "package.zip"
    make_template(template)
    package_zip.write_bytes(b"selected-package")

    result = build_custom_package(
        template_zip=template,
        sql_template_dir=tmp_path / "unused-sql",
        output_root=tmp_path / "out",
        delivery_name="顧客A custom-backend",
        package_zip=package_zip,
        web_zip=None,
        selection=CustomPackageSelection(
            backend=True,
            frontend=False,
            help=False,
            conf_prod=False,
            sql_assets=False,
            data_sync=False,
            import_plan=False,
            runtime=True,
        ),
        version=BuildVersion("remote-1", "M-001", "release_back", ""),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("顧客A", "2026-07-01"),
        middleware_versions={"nginx": "bundled", "redis": "bundled", "minio": "bundled"},
    )

    with zipfile.ZipFile(Path(result["standalone_zip"])) as outer:
        assert outer.read(PACKAGE_IN_STANDALONE_ZIP) == b"selected-package"
        assert WEB_IN_STANDALONE_ZIP not in outer.namelist()
        assert "OneHrStandalone/software/jdk.zip" in outer.namelist()


def test_build_custom_package_sql_only_removes_unselected_help_sql(tmp_path):
    sql_dir = tmp_path / "sql"
    make_sql_templates(sql_dir)

    result = build_custom_package(
        template_zip=tmp_path / "unused-template.zip",
        sql_template_dir=sql_dir,
        output_root=tmp_path / "out",
        delivery_name="顧客A custom-sql",
        package_zip=None,
        web_zip=None,
        selection=CustomPackageSelection(
            backend=False,
            frontend=False,
            help=False,
            conf_prod=False,
            sql_assets=True,
            data_sync=False,
            import_plan=False,
            runtime=False,
        ),
        version=BuildVersion("remote-1", "M-001", "", ""),
        config=StandaloneConfig(postgresql_host=""),
        sql_config=ProductSqlConfig("顧客A", "2026-07-01"),
    )

    delivery_root = Path(result["product_dir"])
    assert (delivery_root / "製品" / "1.tenant" / "url_info.sql").is_file()
    assert not (delivery_root / "製品" / "1.tenant" / "ohr_help.sql").exists()
    assert not (delivery_root / "package.zip").exists()
    assert not (delivery_root / "web.zip").exists()
    assert "standalone_zip" not in result


def test_rebuild_standalone_zip_can_replace_selected_middleware(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    redis_override = tmp_path / "redis-new.zip"
    final_zip = tmp_path / "final.zip"
    make_template(template)
    package_zip.write_bytes(b"new-package")
    web_zip.write_bytes(b"new-web")
    make_nested_zip(redis_override, "redis", {"redis-server.exe": b"new-redis"})

    _rebuild_standalone_zip(
        template,
        final_zip,
        package_zip,
        web_zip,
        StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        middleware_overrides={MIDDLEWARE_IN_STANDALONE_ZIP["redis"]: redis_override},
        include_minio=True,
    )

    with zipfile.ZipFile(final_zip) as outer:
        assert outer.read(PACKAGE_IN_STANDALONE_ZIP) == b"new-package"
        assert outer.read(WEB_IN_STANDALONE_ZIP) == b"new-web"
        assert outer.read("OneHrStandalone/software/jdk.zip") == b"fixed-jdk"
        redis_data = outer.read(MIDDLEWARE_IN_STANDALONE_ZIP["redis"])
        nginx_data = outer.read(MIDDLEWARE_IN_STANDALONE_ZIP["nginx"])
    with zipfile.ZipFile(redis_override) as expected:
        assert redis_data == redis_override.read_bytes()
        assert "redis/redis-server.exe" in expected.namelist()
    with zipfile.ZipFile(template) as original:
        assert nginx_data == original.read(MIDDLEWARE_IN_STANDALONE_ZIP["nginx"])


def test_rebuild_standalone_zip_disables_optional_storage_by_default(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    web_zip = tmp_path / "web.zip"
    final_zip = tmp_path / "final.zip"
    make_template(template)
    make_web_package(web_zip)

    _rebuild_standalone_zip(
        template,
        final_zip,
        None,
        web_zip,
        StandaloneConfig(postgresql_host="10.0.0.8"),
    )

    with zipfile.ZipFile(final_zip) as outer:
        assert MIDDLEWARE_IN_STANDALONE_ZIP["minio"] not in outer.namelist()
        rewritten_web = outer.read(WEB_IN_STANDALONE_ZIP)
    with zipfile.ZipFile(io.BytesIO(rewritten_web)) as web:
        for name in ("ohr-cicd/conf_prod/api-proxy.conf", "ohr-cicd/conf_prod/api-proxy-debug.conf"):
            assert web.read(name).decode("utf-8").splitlines() == [
                "# location ~ ^/azure/(.*)$ {",
                "# \tproxy_pass undefined;",
                "# }",
            ]


def test_rebuild_standalone_zip_can_enable_optional_storage(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    web_zip = tmp_path / "web.zip"
    final_zip = tmp_path / "final.zip"
    make_template(template)
    make_web_package(web_zip)

    _rebuild_standalone_zip(
        template,
        final_zip,
        None,
        web_zip,
        StandaloneConfig(postgresql_host="10.0.0.8"),
        include_minio=True,
        enable_azure_blob_storage=True,
    )

    with zipfile.ZipFile(final_zip) as outer:
        assert MIDDLEWARE_IN_STANDALONE_ZIP["minio"] in outer.namelist()
        rewritten_web = outer.read(WEB_IN_STANDALONE_ZIP)
    with zipfile.ZipFile(io.BytesIO(rewritten_web)) as web:
        for name in ("ohr-cicd/conf_prod/api-proxy.conf", "ohr-cicd/conf_prod/api-proxy-debug.conf"):
            assert web.read(name).decode("utf-8").splitlines() == [
                "location ~ ^/azure/(.*)$ {",
                "\tproxy_pass undefined;",
                "}",
            ]


def test_set_azure_proxy_enabled_leaves_other_locations_unchanged():
    source = "location ~ ^/minio/(.*)$ {\n\tproxy_pass minio;\n}\n\nlocation ~ ^/azure/(.*)$ {\n\tproxy_pass azure;\n}\n"

    disabled = _set_azure_proxy_enabled(source, False)

    assert disabled.startswith("location ~ ^/minio/(.*)$ {\n\tproxy_pass minio;\n}\n")
    assert "# location ~ ^/azure/(.*)$ {\n# \tproxy_pass azure;\n# }" in disabled


def test_build_product_package_prepares_middleware_versions(monkeypatch, tmp_path):
    import standalone_packager as packager

    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    redis_override = tmp_path / "redis-cache.zip"
    make_template(template)
    make_sql_templates(sql_dir)
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", "new help sql")
    make_nested_zip(redis_override, "redis", {"redis-server.exe": b"cached"})
    calls: list[dict[str, str]] = []

    def fake_prepare(selections, **kwargs):
        calls.append(dict(selections))
        return {MIDDLEWARE_IN_STANDALONE_ZIP["redis"]: redis_override}

    monkeypatch.setattr(packager, "prepare_middleware_overrides", fake_prepare)

    result = packager.build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-mw", "M-001", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        include_minio=True,
        middleware_versions={"nginx": "bundled", "redis": "8.2.7", "minio": "bundled"},
    )

    assert calls == [{"nginx": "bundled", "redis": "8.2.7", "minio": "bundled"}]
    with zipfile.ZipFile(Path(result["standalone_zip"])) as outer:
        assert outer.read(MIDDLEWARE_IN_STANDALONE_ZIP["redis"]) == redis_override.read_bytes()


def test_inspect_artifact_versions_reads_generated_package(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    make_template(template)
    make_sql_templates(sql_dir)
    make_backend_package(package_zip)
    make_web_package(web_zip)

    result = build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=tmp_path / "out",
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-1", "M-001", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
    )

    info = inspect_artifact_versions(product_dir=Path(result["product_dir"]))

    assert info["available"] is True
    assert info["type"] == "standard"
    assert "資材:M-001" in info["version_txt"]
    assert info["backend"]["version"] == "1.0.0"
    assert info["backend"]["spring_boot_version"] == "3.5.0"
    assert info["backend"]["build_jdk_spec"] == "24"
    assert info["frontend"]["release_timestamp"] == "release_2026_01_01_00_00_00"
    assert info["frontend"]["repositories"][0]["branch"] == "release_front"
    assert info["help"]["release_timestamp"] == "ohr_help_docs_release_2026_01_01"
    assert info["middleware"]["nginx"]["version"] == "1.26.2"
    assert info["middleware"]["redis"]["version"] == "5.0.9"


def test_build_product_package_fails_when_help_sql_is_missing(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    make_template(template)
    make_sql_templates(sql_dir)
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/meta.json", "{}")

    try:
        build_product_package(
            template_zip=template,
            sql_template_dir=sql_dir,
            output_root=output,
            package_zip=package_zip,
            web_zip=web_zip,
            version=BuildVersion("build-1", "M-001", "release_back", "release_front"),
            config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
            sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        )
    except FileNotFoundError as exc:
        assert "missing Help SQL in web.zip" in str(exc)
    else:
        raise AssertionError("missing Help SQL should fail")


def test_help_sql_from_web_zip_validates_docs_paths(tmp_path):
    web_zip = tmp_path / "web.zip"
    guid = "11111111-1111-1111-1111-111111111111"
    sql = (
        'INSERT INTO ohr_help ("path", "url_uuid") '
        f"VALUES ('docs/{guid}/portal/sample/', '{guid}');"
    )
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", sql)
        z.writestr(f"ohr-cicd/web_prod/help/docs/{guid}/portal/sample/index.html", "ok")

    assert help_sql_from_web_zip(web_zip) == "DELETE FROM ohr_help;\n" + sql


def test_help_sql_from_web_zip_fails_when_docs_are_missing(tmp_path):
    web_zip = tmp_path / "web.zip"
    guid = "11111111-1111-1111-1111-111111111111"
    sql = (
        'INSERT INTO ohr_help ("path", "url_uuid") '
        f"VALUES ('docs/{guid}/portal/sample/', '{guid}');"
    )
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", sql)

    try:
        help_sql_from_web_zip(web_zip)
    except ValueError as exc:
        assert "Help docs index files" in str(exc)
    else:
        raise AssertionError("missing Help docs should fail")


def test_build_product_package_can_skip_help_sql(tmp_path):
    template = tmp_path / "OneHrStandalone.zip"
    sql_dir = tmp_path / "sql"
    package_zip = tmp_path / "package.zip"
    web_zip = tmp_path / "web.zip"
    output = tmp_path / "out"
    make_template(template)
    make_sql_templates(sql_dir)
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/meta.json", "{}")

    result = build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-1", "M-001", "release_back", "release_front"),
        config=StandaloneConfig(postgresql_host="10.0.0.8", ohr_host_address="OHR-HOST"),
        sql_config=ProductSqlConfig("テスト大学", "2026-05-01"),
        include_help_sql=False,
    )

    product_dir = Path(result["product_dir"]) / "製品"
    assert (product_dir / "1.tenant" / "ohr_help.sql").read_text(encoding="utf-8") == "old help"


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


def test_data_sync_git_uses_sparse_clone_for_multiple_subdirs(monkeypatch, tmp_path):
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
        sparse_path=["updsv7phr/PHR", "tsukubav7phr/PHR"],
    )

    assert calls[1] == [
        "git",
        "-C",
        str(tmp_path / "data-sync"),
        "sparse-checkout",
        "set",
        "updsv7phr/PHR",
        "tsukubav7phr/PHR",
    ]


def test_data_sync_accepts_full_gitlab_tree_url(monkeypatch, tmp_path):
    import standalone_packager as packager

    paths: list[object] = []

    def fake_sync(repo_url, branch, workdir, **kwargs):
        paths.append(kwargs.get("sparse_path"))
        source = workdir / "updsv7phr" / "PHR"
        custom = workdir / "tsukubav7phr" / "PHR"
        (source / "Table").mkdir(parents=True)
        (custom / "Procedure").mkdir(parents=True)
        (source / "Table" / "01_base.sql").write_text("base", encoding="utf-8")
        (custom / "Procedure" / "02_custom.sql").write_text("custom", encoding="utf-8")

    monkeypatch.setattr(packager, "sync_git_tree", fake_sync)
    target = tmp_path / "target"

    packager.copy_data_sync_assets(
        repo_url="https://upds7.ujob100.com/ohr/data-synchronization.git",
        branch="master",
        workdir=tmp_path / "data-sync-work",
        subdir="updsv7phr/PHR",
        custom_subdir="https://upds7.ujob100.com/ohr/data-synchronization/-/tree/master/tsukubav7phr/PHR",
        target_dir=target,
    )

    assert paths == [["updsv7phr/PHR", "tsukubav7phr/PHR"]]
    assert (target / "Table" / "01_base.sql").read_text(encoding="utf-8") == "base"
    assert (target / "Procedure" / "02_custom.sql").read_text(encoding="utf-8") == "custom"


def test_data_sync_rejects_tree_url_for_other_repo(tmp_path):
    import standalone_packager as packager

    try:
        packager.copy_data_sync_assets(
            repo_url="https://upds7.ujob100.com/ohr/data-synchronization.git",
            branch="master",
            workdir=tmp_path / "data-sync-work",
            subdir="updsv7phr/PHR",
            custom_subdir="https://upds7.ujob100.com/ohr/other/-/tree/master/tsukubav7phr/PHR",
            target_dir=tmp_path / "target",
        )
    except ValueError as exc:
        assert "configured repository tree" in str(exc)
    else:
        raise AssertionError("tree URL for another repository should be rejected")


def test_data_sync_rejects_unsafe_custom_subdir(tmp_path):
    import standalone_packager as packager

    try:
        packager.copy_data_sync_assets(
            repo_url="https://example.test/data.git",
            branch="master",
            workdir=tmp_path / "data-sync-work",
            subdir="updsv7phr/PHR",
            custom_subdir="../secret",
            target_dir=tmp_path / "target",
        )
    except ValueError as exc:
        assert "unsafe repository subdir" in str(exc)
    else:
        raise AssertionError("unsafe custom subdir should be rejected")


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
    (cached / "Function").mkdir()
    (cached / "Function" / "01_function.sql").write_text("cached", encoding="utf-8")
    (cached / "Ignored").mkdir()
    (cached / "Ignored" / "99_ignore.sql").write_text("ignore", encoding="utf-8")
    custom_cached = workdir / "customv7phr" / "PHR"
    custom_cached.mkdir(parents=True)
    (custom_cached / "Function").mkdir()
    (custom_cached / "Function" / "01_function.sql").write_text("custom cached", encoding="utf-8")

    def fail_sync(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ["git", "fetch"], stderr="fatal: auth failed")

    logs: list[str] = []
    monkeypatch.setattr(packager, "sync_git_tree", fail_sync)

    packager.copy_data_sync_assets(
        repo_url="https://example.test/data.git",
        branch="master",
        workdir=workdir,
        subdir="updsv7phr/PHR",
        custom_subdir="customv7phr/PHR",
        target_dir=target,
        logger=logs.append,
    )

    assert (target / "Function" / "01_function.sql").read_text(encoding="utf-8") == "custom cached"
    assert not (target / "Ignored").exists()
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
    (data_sync_work / "updsv7phr" / "PHR" / "Procedure").mkdir()
    (data_sync_work / "updsv7phr" / "PHR" / "Procedure" / "01_procedure.sql").write_text("sync", encoding="utf-8")
    package_zip.write_bytes(b"new-package")
    with zipfile.ZipFile(web_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("ohr-cicd/web_prod/meta.json", "{}")
        z.writestr("ohr-cicd/web_prod/help/insert_ohr_help.sql", "help sql")
    monkeypatch.setattr(packager, "sync_git_tree", lambda repo_url, branch, workdir, **kwargs: None)
    logs: list[str] = []

    build_product_package(
        template_zip=template,
        sql_template_dir=sql_dir,
        output_root=output,
        package_zip=package_zip,
        web_zip=web_zip,
        version=BuildVersion("build-logs", "M-LOGS", "release_back", "release_front"),
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
