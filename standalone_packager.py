from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "standalone"
DEFAULT_TEMPLATE_ROOT = ROOT / ".standalone-template"
DEFAULT_TEMPLATE_ZIP = DEFAULT_TEMPLATE_ROOT / "OneHrStandalone.zip"
DEFAULT_SQL_TEMPLATE_DIR = DEFAULT_TEMPLATE_ROOT / "sql"
HELP_SQL_IN_WEB_ZIP = "ohr-cicd/web_prod/help/insert_ohr_help.sql"
CONFIG_IN_STANDALONE_ZIP = "OneHrStandalone/bin/kernel/config.ini"
PACKAGE_IN_STANDALONE_ZIP = "OneHrStandalone/software/package.zip"
WEB_IN_STANDALONE_ZIP = "OneHrStandalone/software/web.zip"


@dataclass(frozen=True)
class StandaloneConfig:
    postgresql_host: str
    postgresql_port: int = 5432
    postgresql_user: str = "postgres"
    postgresql_password: str = "password"
    ohr_host_address: str = ""
    ohr_service_port: int = 3198


@dataclass(frozen=True)
class BuildVersion:
    build_id: str
    backend_branch: str
    frontend_branch: str


def configured_output_dir() -> Path:
    return Path(os.environ.get("STANDALONE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))


def configured_template_zip() -> Path:
    return Path(os.environ.get("STANDALONE_TEMPLATE_ZIP", str(DEFAULT_TEMPLATE_ZIP)))


def configured_sql_template_dir() -> Path:
    return Path(os.environ.get("STANDALONE_SQL_TEMPLATE_DIR", str(DEFAULT_SQL_TEMPLATE_DIR)))


def init_template_cache(source_product_dir: Path, template_zip: Path | None = None, sql_template_dir: Path | None = None) -> None:
    template_zip = template_zip or configured_template_zip()
    sql_template_dir = sql_template_dir or configured_sql_template_dir()
    source_zip = source_product_dir / "OneHrStandalone.zip"
    source_tenant = source_product_dir / "1.tenant"
    source_ohr = source_product_dir / "2.ohr"
    if not source_zip.is_file():
        raise FileNotFoundError(f"missing template zip: {source_zip}")
    if not source_tenant.is_dir() or not source_ohr.is_dir():
        raise FileNotFoundError(f"missing SQL template directories under: {source_product_dir}")
    template_zip.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_zip, template_zip)
    if sql_template_dir.exists():
        shutil.rmtree(sql_template_dir)
    shutil.copytree(source_product_dir, sql_template_dir, ignore=shutil.ignore_patterns("OneHrStandalone.zip", "version.txt"))


def render_version_txt(version: BuildVersion) -> str:
    return "\n".join(
        [
            f"資材:{version.build_id}",
            f"前台分支：{version.frontend_branch}",
            f"后台分支：{version.backend_branch}",
            "",
        ]
    )


def update_config_ini(text: str, config: StandaloneConfig) -> str:
    values = {
        "POSTGRESQL_HOST": config.postgresql_host,
        "POSTGRESQL_PORT": str(config.postgresql_port),
        "POSTGRESQL_USER": config.postgresql_user,
        "POSTGRESQL_PASS": config.postgresql_password,
        "OHR_HOST_ADDRESS": config.ohr_host_address or config.postgresql_host,
        "OHR_SERVICE_PORT": str(config.ohr_service_port),
    }
    lines: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(";") and "=" in line:
            key, _, _ = line.partition("=")
            key = key.strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
                continue
        lines.append(line)
    missing = [key for key in values if key not in seen]
    if missing:
        raise ValueError("config.ini missing keys: " + ", ".join(missing))
    return "\n".join(lines) + "\n"


def build_product_package(
    *,
    template_zip: Path,
    sql_template_dir: Path,
    output_root: Path,
    package_zip: Path,
    web_zip: Path,
    version: BuildVersion,
    config: StandaloneConfig,
) -> dict[str, Any]:
    if not template_zip.is_file():
        raise FileNotFoundError(f"missing standalone template: {template_zip}")
    if not package_zip.is_file():
        raise FileNotFoundError(f"missing package.zip: {package_zip}")
    if not web_zip.is_file():
        raise FileNotFoundError(f"missing web.zip: {web_zip}")
    if not (sql_template_dir / "1.tenant").is_dir() or not (sql_template_dir / "2.ohr").is_dir():
        raise FileNotFoundError(f"missing SQL templates under: {sql_template_dir}")

    product_dir = output_root / f"{version.build_id}_製品"
    if product_dir.exists():
        shutil.rmtree(product_dir)
    product_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(sql_template_dir / "1.tenant", product_dir / "1.tenant")
    shutil.copytree(sql_template_dir / "2.ohr", product_dir / "2.ohr")
    _replace_help_sql_if_present(web_zip, product_dir / "1.tenant" / "ohr_help.sql")
    (product_dir / "version.txt").write_text(render_version_txt(version), encoding="utf-8")

    final_zip = product_dir / "OneHrStandalone.zip"
    _rebuild_standalone_zip(template_zip, final_zip, package_zip, web_zip, config)
    return {
        "product_dir": str(product_dir),
        "standalone_zip": str(final_zip),
        "version_txt": str(product_dir / "version.txt"),
        "size": final_zip.stat().st_size,
    }


def _replace_help_sql_if_present(web_zip: Path, target: Path) -> None:
    with zipfile.ZipFile(web_zip) as zf:
        try:
            data = zf.read(HELP_SQL_IN_WEB_ZIP)
        except KeyError:
            return
    target.write_bytes(data)


def _rebuild_standalone_zip(
    template_zip: Path,
    final_zip: Path,
    package_zip: Path,
    web_zip: Path,
    config: StandaloneConfig,
) -> None:
    final_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=final_zip.parent, suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(template_zip, "r") as zin, zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zout:
            for item in zin.infolist():
                if item.filename in {PACKAGE_IN_STANDALONE_ZIP, WEB_IN_STANDALONE_ZIP}:
                    continue
                if item.filename == CONFIG_IN_STANDALONE_ZIP:
                    original = zin.read(item).decode("utf-8-sig", "replace")
                    zout.writestr(item, update_config_ini(original, config).encode("utf-8"))
                    continue
                zout.writestr(item, zin.read(item))
            zout.write(package_zip, PACKAGE_IN_STANDALONE_ZIP)
            zout.write(web_zip, WEB_IN_STANDALONE_ZIP)
        tmp_path.replace(final_zip)
    finally:
        tmp_path.unlink(missing_ok=True)


def download_remote_artifact(remote_base_url: str, build_id: str, name: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{remote_base_url.rstrip('/')}/api/builds/{build_id}/artifact/{name}"
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as f:
        shutil.copyfileobj(response, f)
    return destination


def remote_json(remote_base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(remote_base_url.rstrip("/") + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"remote request failed {exc.code}: {body}") from exc
