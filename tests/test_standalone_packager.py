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
    make_template(template)
    make_sql_templates(sql_dir)
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
    )

    product_dir = Path(result["product_dir"])
    assert product_dir == output / "製品"
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


def test_default_organisation_dstart_uses_first_day_of_month():
    from datetime import date

    assert default_organisation_dstart(date(2026, 5, 14)) == "2026-05-01"
