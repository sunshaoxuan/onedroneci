from __future__ import annotations

import json
import io
import os
import re
import signal
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "standalone"
DEFAULT_TEMPLATE_ROOT = ROOT / ".standalone-template"
DEFAULT_TEMPLATE_ZIP = DEFAULT_TEMPLATE_ROOT / "OneHrStandalone.zip"
DEFAULT_SQL_TEMPLATE_DIR = DEFAULT_TEMPLATE_ROOT / "sql"
DEFAULT_SQL_SVN_URL = "http://192.168.21.111/svn/PHR1.5/98.環境構築手順書/1.構築製品共通"
DEFAULT_DATA_SYNC_GIT_URL = "https://upds7.ujob100.com/ohr/data-synchronization.git"
DEFAULT_DATA_SYNC_BRANCH = "master"
DEFAULT_DATA_SYNC_DIR = DEFAULT_TEMPLATE_ROOT / "data-synchronization"
DEFAULT_DATA_SYNC_SUBDIR = "updsv7phr/PHR"
DEFAULT_DATA_SYNC_CUSTOM_SUBDIR = ""
DATA_SYNC_RUNNER_TEMPLATE = ROOT / "scripts" / "templates" / "run_all_sql.ps1"
DEFAULT_DATA_SYNC_GIT_TIMEOUT = int(os.environ.get("DATA_SYNC_GIT_TIMEOUT", "300"))
DATA_SYNC_ALLOWED_DIRS = ("ForeignTable", "Function", "Procedure", "Sequence", "Table", "View")
HELP_SQL_IN_WEB_ZIP = "ohr-cicd/web_prod/help/insert_ohr_help.sql"
HELP_SQL_RESET_PREFIX = "DELETE FROM ohr_help;\n"
HELP_DOC_PATH_RE = re.compile(r"docs/[0-9a-fA-F-]{36}/[^'\"\s]*")
HELP_DOC_UUID_RE = re.compile(r"docs/([0-9a-fA-F-]{36})/")
CONFIG_IN_STANDALONE_ZIP = "OneHrStandalone/bin/kernel/config.ini"
PACKAGE_IN_STANDALONE_ZIP = "OneHrStandalone/software/package.zip"
WEB_IN_STANDALONE_ZIP = "OneHrStandalone/software/web.zip"
MIDDLEWARE_IN_STANDALONE_ZIP = {
    "nginx": "OneHrStandalone/software/nginx.zip",
    "redis": "OneHrStandalone/software/redis.zip",
    "minio": "OneHrStandalone/software/minio.zip",
}
MIDDLEWARE_VERSION_METADATA = ".ohr-builder-version.json"
DEFAULT_MIDDLEWARE_CACHE_DIR = DEFAULT_TEMPLATE_ROOT / "middleware-cache"
DEFAULT_MIDDLEWARE_ADDONS_DIR = ROOT / "addons"
NGINX_DOWNLOAD_INDEX = "https://nginx.org/download/"
NGINX_DOWNLOAD_BASE = "https://nginx.org/download"
REDIS_WINDOWS_RELEASES_API = "https://api.github.com/repos/redis-windows/redis-windows/releases"
MINIO_WINDOWS_ARCHIVE_URL = "https://dl.min.io/server/minio/release/windows-amd64/archive/"
MIDDLEWARE_BUNDLED_VERSION = "bundled"


@dataclass(frozen=True)
class StandaloneConfig:
    postgresql_host: str
    postgresql_port: int = 5432
    postgresql_user: str = "postgres"
    postgresql_password: str = "password"
    ohr_host_address: str = ""
    ohr_service_port: int = 3198


@dataclass(frozen=True)
class DataSyncSqlRunnerConfig:
    ohr_host: str
    ohr_port: int = 5432
    ohr_user: str = "postgres"
    ohr_password: str = ""
    upds_host: str = ""
    upds_port: int = 5432
    upds_database: str = ""
    upds_user: str = "postgres"
    upds_password: str = ""


@dataclass(frozen=True)
class BuildVersion:
    build_id: str
    material_number: str
    backend_branch: str
    frontend_branch: str


@dataclass(frozen=True)
class CustomPackageSelection:
    backend: bool = True
    frontend: bool = True
    help: bool = True
    conf_prod: bool = True
    sql_assets: bool = True
    data_sync: bool = True
    import_plan: bool = True
    runtime: bool = True

    def any_selected(self) -> bool:
        return any(
            (
                self.backend,
                self.frontend,
                self.help,
                self.conf_prod,
                self.sql_assets,
                self.data_sync,
                self.import_plan,
                self.runtime,
            )
        )


@dataclass(frozen=True)
class ProductSqlConfig:
    organisation_name: str
    organisation_dstart: str


@dataclass(frozen=True)
class TenantImportConfig:
    support_applications: tuple[str, ...]
    enable_email: bool = False
    enable_transport_setting: bool = False
    enable_lecture: bool = False


@dataclass(frozen=True)
class OhrMenuDisable:
    label: str
    application_name: str
    menu_code: str
    enabled: bool = False


@dataclass(frozen=True)
class OhrScheduledTaskDisable:
    label: str
    uuid: str
    code: str
    name_i18n_key: str
    application_name: str
    enabled: bool = False


@dataclass(frozen=True)
class OhrImportConfig:
    disabled_menus: tuple[OhrMenuDisable, ...] = ()
    disabled_scheduled_tasks: tuple[OhrScheduledTaskDisable, ...] = ()


@dataclass(frozen=True)
class MiddlewareRelease:
    product: str
    version: str
    url: str


@dataclass(frozen=True)
class MiddlewareSelection:
    product: str
    version: str = MIDDLEWARE_BUNDLED_VERSION


def configured_output_dir() -> Path:
    return Path(os.environ.get("STANDALONE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))


def configured_template_zip() -> Path:
    return Path(os.environ.get("STANDALONE_TEMPLATE_ZIP", str(DEFAULT_TEMPLATE_ZIP)))


def configured_middleware_cache_dir() -> Path:
    return Path(os.environ.get("STANDALONE_MIDDLEWARE_CACHE_DIR", str(DEFAULT_MIDDLEWARE_CACHE_DIR)))


def configured_middleware_addons_dir() -> Path:
    return Path(os.environ.get("MIDDLEWARE_ADDONS_DIR", str(DEFAULT_MIDDLEWARE_ADDONS_DIR)))


def configured_sql_template_dir() -> Path:
    return Path(os.environ.get("STANDALONE_SQL_TEMPLATE_DIR", str(DEFAULT_SQL_TEMPLATE_DIR)))


def configured_sql_svn_url() -> str:
    return os.environ.get("STANDALONE_SQL_SVN_URL", DEFAULT_SQL_SVN_URL)


def configured_data_sync_git_url() -> str:
    return git_url_with_token(os.environ.get("DATA_SYNC_GIT_URL", DEFAULT_DATA_SYNC_GIT_URL))


def git_url_with_token(url: str) -> str:
    token = os.environ.get("DATA_SYNC_GIT_TOKEN") or os.environ.get("FRONTEND_GIT_TOKEN") or os.environ.get("OHR_BACK_GIT_TOKEN") or ""
    if not token or "://" not in url or "@" in urllib.parse.urlparse(url).netloc:
        return url
    parsed = urllib.parse.urlparse(url)
    netloc = f"oauth2:{urllib.parse.quote(token, safe='')}@{parsed.hostname or ''}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def configured_data_sync_branch() -> str:
    return os.environ.get("DATA_SYNC_BRANCH", DEFAULT_DATA_SYNC_BRANCH)


def configured_data_sync_dir() -> Path:
    return Path(os.environ.get("DATA_SYNC_DIR", str(DEFAULT_DATA_SYNC_DIR)))


def configured_data_sync_subdir() -> str:
    return os.environ.get("DATA_SYNC_SUBDIR", DEFAULT_DATA_SYNC_SUBDIR)


def configured_data_sync_custom_subdir() -> str:
    return os.environ.get("DATA_SYNC_CUSTOM_SUBDIR", DEFAULT_DATA_SYNC_CUSTOM_SUBDIR)


def default_organisation_dstart(today: date | None = None) -> str:
    today = today or date.today()
    return today.replace(day=1).isoformat()


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


def _read_template_nested_zip(template_zip: Path, product: str) -> bytes | None:
    member = MIDDLEWARE_IN_STANDALONE_ZIP.get(product)
    if not member or not template_zip.is_file():
        return None
    try:
        with zipfile.ZipFile(template_zip) as zf:
            return zf.read(member)
    except (KeyError, zipfile.BadZipFile):
        return None


def detect_template_middleware_versions(template_zip: Path | None = None) -> dict[str, str]:
    template_zip = template_zip or configured_template_zip()
    versions = {name: MIDDLEWARE_BUNDLED_VERSION for name in MIDDLEWARE_IN_STANDALONE_ZIP}
    nginx_zip = _read_template_nested_zip(template_zip, "nginx")
    if nginx_zip:
        versions["nginx"] = _inspect_middleware_zip_bytes("nginx", nginx_zip).get("version") or versions["nginx"]
    redis_zip = _read_template_nested_zip(template_zip, "redis")
    if redis_zip:
        versions["redis"] = _inspect_middleware_zip_bytes("redis", redis_zip).get("version") or versions["redis"]
    minio_zip = _read_template_nested_zip(template_zip, "minio")
    if minio_zip:
        versions["minio"] = _inspect_middleware_zip_bytes("minio", minio_zip).get("version") or versions["minio"]
    return versions


def _zip_read_text(zf: zipfile.ZipFile, name: str, limit: int | None = None) -> str:
    data = zf.read(name)
    if limit is not None:
        data = data[:limit]
    return data.decode("utf-8", "replace")


def _zip_read_json(zf: zipfile.ZipFile, name: str) -> dict[str, Any]:
    return json.loads(_zip_read_text(zf, name))


def _manifest_get(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _inspect_middleware_zip_bytes(product: str, data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"product": product, "version": "", "source": ""}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as nested:
            names = set(nested.namelist())
            metadata_name = f"{product}/{MIDDLEWARE_VERSION_METADATA}"
            if metadata_name in names:
                metadata = _zip_read_json(nested, metadata_name)
                result["version"] = str(metadata.get("version") or "")
                result["source"] = "builder_metadata"
                result["url"] = str(metadata.get("url") or "")
                return result
            if product == "nginx" and "nginx/docs/CHANGES" in names:
                text = _zip_read_text(nested, "nginx/docs/CHANGES", limit=4000)
                match = re.search(r"Changes with nginx\s+([0-9.]+)", text)
                if match:
                    result["version"] = match.group(1)
                    result["source"] = "nginx_changes"
            elif product == "redis":
                for member in ("redis/00-RELEASENOTES", "redis/README.md", "redis/README.zh_CN.md"):
                    if member not in names:
                        continue
                    text = _zip_read_text(nested, member, limit=8000)
                    match = re.search(r"Redis\s+([0-9]+\.[0-9]+\.[0-9]+)", text)
                    if match:
                        result["version"] = match.group(1)
                        result["source"] = member
                        break
                if not result["version"] and "redis/redis-server.exe" in names:
                    binary = nested.read("redis/redis-server.exe")
                    for match in re.finditer(rb"(?<![0-9])([0-9]+\.[0-9]+\.[0-9]+)(?![0-9])", binary):
                        version = match.group(1).decode("ascii", "ignore")
                        if version not in {"0.0.0", "127.0.0"}:
                            result["version"] = version
                            result["source"] = "redis-server.exe"
                            break
            elif product == "minio":
                for name in names:
                    match = re.search(r"RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z", name)
                    if match:
                        result["version"] = match.group(0)
                        result["source"] = "filename"
                        break
                if not result["version"] and "minio/minio.exe" in names:
                    binary = nested.read("minio/minio.exe")
                    match = re.search(rb"RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z", binary)
                    if match:
                        result["version"] = match.group(0).decode("ascii", "ignore")
                        result["source"] = "minio.exe"
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _inspect_package_zip_bytes(data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"version": "", "spring_boot_version": "", "build_jdk_spec": ""}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package_zip:
            jar_name = next((name for name in package_zip.namelist() if name.endswith(".jar")), "")
            if not jar_name:
                return result
            jar_data = package_zip.read(jar_name)
        with zipfile.ZipFile(io.BytesIO(jar_data)) as jar:
            names = set(jar.namelist())
            if "META-INF/MANIFEST.MF" in names:
                manifest = _zip_read_text(jar, "META-INF/MANIFEST.MF")
                result["version"] = _manifest_get(manifest, "Implementation-Version")
                result["spring_boot_version"] = _manifest_get(manifest, "Spring-Boot-Version")
                result["build_jdk_spec"] = _manifest_get(manifest, "Build-Jdk-Spec")
            pom_props = next((name for name in names if name.endswith("/pom.properties") and "/standalone/" in name), "")
            if pom_props and not result["version"]:
                text = _zip_read_text(jar, pom_props)
                match = re.search(r"^version=(.+)$", text, re.MULTILINE)
                if match:
                    result["version"] = match.group(1).strip()
            result["jar"] = jar_name
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _inspect_web_zip_bytes(data: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {"release_timestamp": "", "repositories": [], "help": {}}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as web_zip:
            names = set(web_zip.namelist())
            if "ohr-cicd/web_prod/meta.json" in names:
                meta = _zip_read_json(web_zip, "ohr-cicd/web_prod/meta.json")
                result["release_timestamp"] = str(meta.get("releaseTimestamp") or "")
                git_info = meta.get("gitInfo") or {}
                if isinstance(git_info, dict):
                    repositories = []
                    for repo, info in sorted(git_info.items()):
                        if isinstance(info, dict):
                            repositories.append({
                                "name": str(repo),
                                "branch": str(info.get("branch") or ""),
                                "commit": str(info.get("latestCommit") or ""),
                            })
                    result["repositories"] = repositories
            if "ohr-cicd/web_prod/help/meta.json" in names:
                help_meta = _zip_read_json(web_zip, "ohr-cicd/web_prod/help/meta.json")
                help_info = help_meta.get("gitInfo") or {}
                result["help"] = {
                    "release_timestamp": str(help_meta.get("releaseTimestamp") or ""),
                    "branch": str(help_info.get("branch") or "") if isinstance(help_info, dict) else "",
                    "commit": str(help_info.get("latestCommit") or "") if isinstance(help_info, dict) else "",
                }
    except Exception as exc:
        result["error"] = str(exc)
    return result


def inspect_artifact_versions(product_dir: Path | None = None, standalone_zip: Path | None = None, common_zip: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "type": "",
        "version_txt": "",
        "backend": {},
        "frontend": {},
        "help": {},
        "middleware": {},
    }
    try:
        if common_zip and common_zip.is_file():
            result["type"] = "nho_common"
            result["available"] = True
            with zipfile.ZipFile(common_zip) as common:
                names = set(common.namelist())
                if "共通/version.txt" in names:
                    result["version_txt"] = _zip_read_text(common, "共通/version.txt")
                if "共通/upgrade/実行環境資材/OneHrSuite/software/package.zip" in names:
                    result["backend"] = _inspect_package_zip_bytes(common.read("共通/upgrade/実行環境資材/OneHrSuite/software/package.zip"))
                if "共通/upgrade/実行環境資材/OneHrSuite/software/web.zip" in names:
                    web_info = _inspect_web_zip_bytes(common.read("共通/upgrade/実行環境資材/OneHrSuite/software/web.zip"))
                    result["frontend"] = {key: value for key, value in web_info.items() if key != "help"}
                    result["help"] = web_info.get("help") or {}
            return result

        if product_dir:
            base = product_dir / "製品" if (product_dir / "製品").is_dir() else product_dir
            standalone_zip = standalone_zip or base / "OneHrStandalone.zip"
            version_txt = base / "version.txt"
            if version_txt.is_file():
                result["version_txt"] = version_txt.read_text(encoding="utf-8", errors="replace")
        if not standalone_zip or not standalone_zip.is_file():
            return result
        result["type"] = "standard"
        result["available"] = True
        with zipfile.ZipFile(standalone_zip) as outer:
            names = set(outer.namelist())
            if PACKAGE_IN_STANDALONE_ZIP in names:
                result["backend"] = _inspect_package_zip_bytes(outer.read(PACKAGE_IN_STANDALONE_ZIP))
            if WEB_IN_STANDALONE_ZIP in names:
                web_info = _inspect_web_zip_bytes(outer.read(WEB_IN_STANDALONE_ZIP))
                result["frontend"] = {key: value for key, value in web_info.items() if key != "help"}
                result["help"] = web_info.get("help") or {}
            middleware: dict[str, Any] = {}
            for product, member in MIDDLEWARE_IN_STANDALONE_ZIP.items():
                if member in names:
                    middleware[product] = _inspect_middleware_zip_bytes(product, outer.read(member))
            result["middleware"] = middleware
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _urlopen_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "OHR-Standalone-Builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _urlopen_json(url: str, timeout: int = 20) -> Any:
    return json.loads(_urlopen_text(url, timeout=timeout))


def _dedupe_releases(releases: list[MiddlewareRelease]) -> list[MiddlewareRelease]:
    result: list[MiddlewareRelease] = []
    seen: set[tuple[str, str]] = set()
    for release in releases:
        key = (release.product, release.version)
        if key in seen:
            continue
        result.append(release)
        seen.add(key)
    return result


def fetch_nginx_releases(timeout: int = 20, limit: int = 30) -> list[MiddlewareRelease]:
    html = _urlopen_text(os.environ.get("MIDDLEWARE_NGINX_DOWNLOAD_INDEX", NGINX_DOWNLOAD_INDEX), timeout=timeout)
    releases: list[MiddlewareRelease] = []
    for version in re.findall(r"nginx-([0-9]+\.[0-9]+\.[0-9]+)\.zip", html):
        releases.append(MiddlewareRelease("nginx", version, f"{NGINX_DOWNLOAD_BASE}/nginx-{version}.zip"))
    releases = _dedupe_releases(releases)
    releases.sort(key=lambda release: tuple(int(part) for part in release.version.split(".")), reverse=True)
    return releases[:limit]


def _redis_asset_score(name: str) -> tuple[int, str]:
    lower = name.lower()
    score = 0
    if "windows-x64" in lower:
        score += 10
    if "with-service" in lower:
        score += 6
    if "msys2" in lower:
        score += 4
    if "cygwin" in lower:
        score += 2
    return (-score, lower)


def fetch_redis_releases(timeout: int = 20, limit: int = 30) -> list[MiddlewareRelease]:
    url = os.environ.get("MIDDLEWARE_REDIS_RELEASES_API", REDIS_WINDOWS_RELEASES_API)
    data = _urlopen_json(url, timeout=timeout)
    releases: list[MiddlewareRelease] = []
    for item in data if isinstance(data, list) else []:
        version = str(item.get("tag_name") or item.get("name") or "").lstrip("v")
        assets = item.get("assets") or []
        candidates = [
            asset
            for asset in assets
            if str(asset.get("name") or "").lower().endswith(".zip")
            and "windows-x64" in str(asset.get("name") or "").lower()
        ]
        if not version or not candidates:
            continue
        asset = sorted(candidates, key=lambda candidate: _redis_asset_score(str(candidate.get("name") or "")))[0]
        download_url = str(asset.get("browser_download_url") or "")
        if download_url:
            releases.append(MiddlewareRelease("redis", version, download_url))
    return _dedupe_releases(releases)[:limit]


def fetch_minio_releases(timeout: int = 20, limit: int = 30) -> list[MiddlewareRelease]:
    base = os.environ.get("MIDDLEWARE_MINIO_ARCHIVE_URL", MINIO_WINDOWS_ARCHIVE_URL).rstrip("/") + "/"
    html = _urlopen_text(base, timeout=timeout)
    releases: list[MiddlewareRelease] = []
    for version in re.findall(r"minio\.(RELEASE\.[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2}Z)(?!\.)", html):
        releases.append(MiddlewareRelease("minio", version, urllib.parse.urljoin(base, f"minio.{version}")))
    return _dedupe_releases(releases)[:limit]


def fetch_middleware_catalog(template_zip: Path | None = None, timeout: int = 20, limit: int = 30) -> dict[str, dict[str, Any]]:
    current = detect_template_middleware_versions(template_zip or configured_template_zip())
    fetchers = {
        "nginx": fetch_nginx_releases,
        "redis": fetch_redis_releases,
        "minio": fetch_minio_releases,
    }
    catalog: dict[str, dict[str, Any]] = {}
    for product, fetcher in fetchers.items():
        releases: list[dict[str, str]] = []
        error = ""
        try:
            releases = [release.__dict__ for release in fetcher(timeout=timeout, limit=limit)]
        except Exception as exc:
            error = str(exc)
        catalog[product] = {
            "product": product,
            "current_version": current.get(product, MIDDLEWARE_BUNDLED_VERSION),
            "bundled_value": MIDDLEWARE_BUNDLED_VERSION,
            "releases": releases,
            "error": error,
        }
    return catalog


def _middleware_addon_files(product: str) -> list[tuple[str, Path]]:
    base = configured_middleware_addons_dir() / product
    if not base.is_dir():
        return []
    result: list[tuple[str, Path]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        result.append((f"{product}/{relative}", path))
    return result


def _zip_has_current_addons(zip_path: Path, product: str) -> bool:
    addons = _middleware_addon_files(product)
    if not addons:
        return True
    if not zip_path.is_file():
        return False
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            for name, source in addons:
                if name not in names:
                    return False
                if zf.read(name) != source.read_bytes():
                    return False
        return True
    except Exception:
        return False


def _zip_with_normalized_root(source_zip: Path, target_zip: Path, root_name: str, addons: list[tuple[str, Path]] | None = None) -> None:
    addons = addons or []
    addon_names = {name for name, _ in addons}
    with zipfile.ZipFile(source_zip) as source, zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as target:
        names = [name for name in source.namelist() if name and not name.endswith("/")]
        first_parts = {name.split("/", 1)[0] for name in names if "/" in name}
        strip_root = len(first_parts) == 1
        root_prefix = next(iter(first_parts)) + "/" if strip_root else ""
        written_dirs: set[str] = set()
        for item in source.infolist():
            name = item.filename.replace("\\", "/").lstrip("/")
            if not name:
                continue
            if strip_root and name.startswith(root_prefix):
                name = name[len(root_prefix) :]
            if not name:
                continue
            target_name = f"{root_name}/{name}".rstrip("/")
            if target_name in addon_names:
                continue
            if item.is_dir():
                directory = target_name + "/"
                if directory not in written_dirs:
                    target.writestr(directory, b"")
                    written_dirs.add(directory)
                continue
            directory = target_name.rsplit("/", 1)[0] + "/"
            if directory not in written_dirs:
                target.writestr(directory, b"")
                written_dirs.add(directory)
            target.writestr(target_name, source.read(item.filename))
        for target_name, source_path in addons:
            directory = target_name.rsplit("/", 1)[0] + "/"
            if directory not in written_dirs:
                target.writestr(directory, b"")
                written_dirs.add(directory)
            target.writestr(target_name, source_path.read_bytes())


def _minio_start_bat_from_template(template_zip: Path) -> bytes:
    minio_zip = _read_template_nested_zip(template_zip, "minio")
    if minio_zip:
        try:
            with zipfile.ZipFile(io.BytesIO(minio_zip)) as nested:
                return nested.read("minio/start.bat")
        except Exception:
            pass
    return b"minio.exe server data\r\n"


def _download_file(url: str, destination: Path, timeout: int = 600) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "OHR-Standalone-Builder"})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _write_middleware_version_metadata(zip_path: Path, product: str, version: str, url: str) -> None:
    payload = json.dumps(
        {
            "product": product,
            "version": version,
            "url": url,
        },
        ensure_ascii=False,
        indent=2,
    )
    with zipfile.ZipFile(zip_path, "a", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.writestr(f"{product}/{MIDDLEWARE_VERSION_METADATA}", payload)


def _find_release(product: str, version: str) -> MiddlewareRelease:
    fetchers = {
        "nginx": fetch_nginx_releases,
        "redis": fetch_redis_releases,
        "minio": fetch_minio_releases,
    }
    fetcher = fetchers.get(product)
    if not fetcher:
        raise ValueError(f"unsupported middleware: {product}")
    for release in fetcher(timeout=30, limit=200):
        if release.version == version:
            return release
    raise ValueError(f"middleware release not found: {product} {version}")


def _build_cached_middleware_zip(product: str, version: str, url: str, cache_zip: Path, template_zip: Path) -> None:
    cache_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        raw = tmp / "download"
        normalized = tmp / f"{product}.zip"
        addons = _middleware_addon_files(product)
        _download_file(url, raw)
        if product in {"nginx", "redis"}:
            _zip_with_normalized_root(raw, normalized, product, addons=addons)
        elif product == "minio":
            with zipfile.ZipFile(normalized, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
                zf.writestr("minio/", b"")
                zf.write(raw, "minio/minio.exe")
                zf.writestr("minio/start.bat", _minio_start_bat_from_template(template_zip))
                for target_name, source_path in addons:
                    zf.writestr(target_name, source_path.read_bytes())
        else:
            raise ValueError(f"unsupported middleware: {product}")
        _write_middleware_version_metadata(normalized, product, version, url)
        temp_cache = cache_zip.with_suffix(cache_zip.suffix + ".tmp")
        shutil.copy2(normalized, temp_cache)
        temp_cache.replace(cache_zip)


def prepare_middleware_overrides(
    selections: dict[str, str] | None,
    *,
    template_zip: Path,
    cache_dir: Path | None = None,
    logger: Any | None = None,
) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    if not selections:
        return overrides
    cache_dir = cache_dir or configured_middleware_cache_dir()
    for product, version in selections.items():
        product = product.strip().lower()
        version = str(version or "").strip()
        if product not in MIDDLEWARE_IN_STANDALONE_ZIP or not version or version == MIDDLEWARE_BUNDLED_VERSION:
            continue
        if logger:
            logger("middleware_assets")
        cache_zip = cache_dir / product / version / f"{product}.zip"
        if not cache_zip.is_file() or not _zip_has_current_addons(cache_zip, product):
            release = _find_release(product, version)
            _build_cached_middleware_zip(product, version, release.url, cache_zip, template_zip)
        overrides[MIDDLEWARE_IN_STANDALONE_ZIP[product]] = cache_zip
    return overrides


def render_version_txt(version: BuildVersion) -> str:
    return "\n".join(
        [
            f"資材:{version.material_number}",
            f"前台分支：{version.frontend_branch}",
            f"后台分支：{version.backend_branch}",
            "",
        ]
    )


def render_tenant_import_sql(config: TenantImportConfig) -> str:
    applications = "{" + ",".join(config.support_applications) + "}"
    email_value = "true" if config.enable_email else "false"
    transport_value = "true" if config.enable_transport_setting else "false"
    lecture_value = "true" if config.enable_lecture else "false"
    return "\n".join(
        [
            "-- 導入計画",
            f"UPDATE tenant SET support_applications = {sql_quote(applications)}",
            "WHERE tenant_id='public';",
            "",
            f"-- メール={'利用' if config.enable_email else '利用しない'}",
            f"UPDATE tenant SET system_config= jsonb_set(system_config ::jsonb, '{{enableEmail}}', {sql_quote(email_value)})",
            "WHERE tenant_id='public';",
            "",
            f"-- 駅すぱあと={'利用' if config.enable_transport_setting else '利用しない'}",
            f"UPDATE tenant SET system_config= jsonb_set(system_config ::jsonb, '{{enableTransportSetting}}', {sql_quote(transport_value)})",
            "WHERE tenant_id='public';",
            "",
            f"-- 係・講座={'利用' if config.enable_lecture else '利用しない'}",
            f"UPDATE tenant SET system_config= jsonb_set(system_config ::jsonb, '{{enableLecture}}', {sql_quote(lecture_value)})",
            "WHERE tenant_id='public';",
            "",
        ]
    )


def render_ohr_import_sql(config: OhrImportConfig) -> str:
    lines = ["-- 導入計画", ""]
    if not config.disabled_menus and not config.disabled_scheduled_tasks:
        lines.extend(["-- 画面公開計画による更新対象はありません。", ""])
        return "\n".join(lines)

    for item in config.disabled_menus:
        enabled_value = "true" if item.enabled else "false"
        lines.extend(
            [
                f"-- {item.label}={'公開' if item.enabled else '非公開'}",
                f"update ohr_menu set enable = {enabled_value}",
                f"where application_name = {sql_quote(item.application_name)} and menu_code = {sql_quote(item.menu_code)};",
                "",
            ]
        )
    for item in config.disabled_scheduled_tasks:
        paused_value = "false" if item.enabled else "true"
        display_value = "true" if item.enabled else "false"
        lines.extend(
            [
                f"-- {item.label}={'有効' if item.enabled else '停止'}",
                f'update "ohr_scheduled_task" set paused = {paused_value} where "uuid" = {sql_quote(item.uuid)};',
                "",
                f"update ohr_scheduled_task_type set display_flag = {display_value} "
                f"where code = {sql_quote(item.code)} "
                f'and "name_i18n_key" = {sql_quote(item.name_i18n_key)} '
                f"and application_name = {sql_quote(item.application_name)};",
                "",
            ]
        )
    return "\n".join(lines)


def _include_sql_line(filename: str) -> str:
    if re.search(r"\s", filename):
        return f'\\i "{filename}"'
    return f"\\i {filename}"


def _referenced_sql_filenames(text: str) -> set[str]:
    names: set[str] = set()
    for match in re.finditer(r'(?im)^\s*\\i\s+(?:"([^"]+)"|(\S+))', text):
        reference = (match.group(1) or match.group(2)).replace("\\", "/")
        if reference.lower().endswith(".sql"):
            names.add(reference.rsplit("/", 1)[-1].lower())
    return names


def complete_all_sql_scripts(root: Path, excluded_roots: tuple[Path, ...] = ()) -> dict[str, list[str]]:
    completed: dict[str, list[str]] = {}
    resolved_excluded_roots = tuple(path.resolve() for path in excluded_roots)

    def is_excluded(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == excluded or excluded in resolved.parents for excluded in resolved_excluded_roots)

    script_dirs = sorted(
        {
            item.parent
            for item in root.rglob("*.sql")
            if item.is_file() and item.name.lower() != "all.sql" and not is_excluded(item)
        },
        key=lambda path: str(path).lower(),
    )
    for script_dir in script_dirs:
        all_sql = script_dir / "all.sql"
        sql_files = sorted(
            (
                item.name
                for item in script_dir.iterdir()
                if item.is_file() and item.suffix.lower() == ".sql" and item.name.lower() != "all.sql"
            ),
            key=str.lower,
        )
        if not sql_files:
            continue
        text = all_sql.read_text(encoding="utf-8-sig") if all_sql.exists() else ""
        known = _referenced_sql_filenames(text)
        missing = [name for name in sql_files if name.lower() not in known]
        if not missing:
            continue
        separator = "" if not text or text.endswith(("\n", "\r")) else "\n"
        addition = "\n".join(_include_sql_line(name) for name in missing) + "\n"
        all_sql.write_text(text + separator + addition, encoding="utf-8")
        completed[str(all_sql.relative_to(root)).replace("\\", "/")] = missing
    return completed


def _powershell_single_quoted(value: Any) -> str:
    return str(value or "").replace("'", "''")


def render_data_sync_sql_runner(config: DataSyncSqlRunnerConfig) -> str:
    if not DATA_SYNC_RUNNER_TEMPLATE.is_file():
        raise FileNotFoundError(f"missing data sync runner template: {DATA_SYNC_RUNNER_TEMPLATE}")
    text = DATA_SYNC_RUNNER_TEMPLATE.read_text(encoding="utf-8-sig")
    replacements = {
        "@@OHR_DB_HOST@@": _powershell_single_quoted(config.ohr_host),
        "@@OHR_DB_PORT@@": str(int(config.ohr_port)),
        "@@OHR_DB_USER@@": _powershell_single_quoted(config.ohr_user),
        "@@OHR_DB_PASSWORD@@": _powershell_single_quoted(config.ohr_password),
        "@@UPDS_DB_HOST@@": _powershell_single_quoted(config.upds_host),
        "@@UPDS_DB_PORT@@": str(int(config.upds_port)),
        "@@UPDS_DB_NAME@@": _powershell_single_quoted(config.upds_database),
        "@@UPDS_DB_USER@@": _powershell_single_quoted(config.upds_user),
        "@@UPDS_DB_PASSWORD@@": _powershell_single_quoted(config.upds_password),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    unresolved = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
    if unresolved:
        raise ValueError(f"unresolved data sync runner placeholders: {', '.join(unresolved)}")
    return text


def write_data_sync_sql_runner(target_dir: Path, config: DataSyncSqlRunnerConfig) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "run_all_sql.ps1"
    target.write_text(render_data_sync_sql_runner(config), encoding="utf-8-sig")
    return target


def _safe_zip_member_name(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("/")
    if not normalized or normalized.startswith("/") or ".." in Path(normalized).parts:
        raise ValueError(f"unsafe zip path: {name}")
    return normalized


def _display_db_name(name: str) -> str:
    mapping = {"ohr": "Ohr", "tenant": "Tenant"}
    return mapping.get(name.lower(), name)


def _tree_from_paths(paths: list[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for path in sorted(paths):
        current = root
        for part in path.strip("/").split("/"):
            current = current.setdefault(part, {})
    return root


def _render_tree_lines(tree: dict[str, Any], prefix: str = "") -> list[str]:
    lines: list[str] = []
    items = sorted(tree.items(), key=lambda item: (bool(item[1]), item[0].lower()))
    for index, (name, children) in enumerate(items):
        is_last = index == len(items) - 1
        branch = "└─" if is_last else "├─"
        if children:
            lines.append(f"{prefix}{branch}{name}")
            extension = "    " if is_last else "│  "
            lines.extend(_render_tree_lines(children, prefix + extension))
        else:
            lines.append(f"{prefix}{branch}{name}")
    return lines


def _render_nho_readme(database_asset_paths: list[str], include_package: bool, include_web: bool) -> str:
    lines = ["■■■■■■■■■■■■■■■実行手順■■■■■■■■■■■■■■■"]
    sql_paths = sorted(path for path in database_asset_paths if path.lower().endswith(".sql"))
    if sql_paths:
        lines.extend(["■　【データベース資材】フォルダのSQLスクリプトを実行する", ""])
        groups: dict[str, dict[str, list[str]]] = {}
        for path in sql_paths:
            parts = path.split("/")
            if len(parts) < 3:
                continue
            group, db_name, filename = parts[0], parts[1], parts[-1]
            groups.setdefault(group, {}).setdefault(db_name, []).append(filename)
        for group in sorted(groups):
            lines.append(f"□　【{group}】")
            for db_name in sorted(groups[group]):
                lines.append(f"　　□　【{_display_db_name(db_name)}】データベース")
                for filename in sorted(groups[group][db_name]):
                    lines.append(f"             -{filename}")
                lines.append("")
    if include_package or include_web:
        lines.extend(
            [
                "■　【実行環境資材¥OneHrSuite】フォルダを実行環境（例：C:\\OneHrSuite）に上書きする",
                "　　注意：同名フォルダの上書きです",
                "",
                "■　実行環境の【OneHrSuite\\bin\\cluster\\package.upgrade.ps1】を実行する",
                "　　注意：実行環境のスクリプトであること",
                "　　　　　管理者として実行すること",
                "",
            ]
        )
    asset_paths = ["upgrade/readme.txt"]
    asset_paths.extend(f"upgrade/データベース資材/{path}" for path in sql_paths)
    if include_package:
        asset_paths.append("upgrade/実行環境資材/OneHrSuite/software/package.zip")
    if include_web:
        asset_paths.append("upgrade/実行環境資材/OneHrSuite/software/web.zip")
    lines.extend(["■■■■■■■■■■■■■■■資材一覧■■■■■■■■■■■■■■■", "", "upgrade"])
    tree = _tree_from_paths([path.removeprefix("upgrade/") for path in asset_paths if path != "upgrade"])
    lines.extend(_render_tree_lines(tree))
    return "\n".join(lines).rstrip() + "\n"


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


class _SvnIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def _quote_url(url: str) -> str:
    return urllib.parse.quote(url, safe="/:%#?&=@[]!$&'()*+,;")


def download_svn_http_tree(url: str, target_dir: Path) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    _download_svn_http_dir(url.rstrip("/") + "/", target_dir)


def _download_svn_http_dir(url: str, target_dir: Path) -> None:
    with urllib.request.urlopen(_quote_url(url), timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    parser = _SvnIndexParser()
    parser.feed(html)
    for href in parser.hrefs:
        if href in ("../", "./") or href.startswith("?"):
            continue
        child_url = urllib.parse.urljoin(url, href)
        name = urllib.parse.unquote(href.rstrip("/"))
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            continue
        child_path = target_dir / name
        if href.endswith("/"):
            child_path.mkdir(parents=True, exist_ok=True)
            _download_svn_http_dir(child_url.rstrip("/") + "/", child_path)
        else:
            with urllib.request.urlopen(_quote_url(child_url), timeout=120) as response:
                child_path.write_bytes(response.read())


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def jsonb_ja(value: str) -> str:
    return json.dumps({"ja-JP": value}, ensure_ascii=False)


def split_sql_values(values_text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    i = 0
    while i < len(values_text):
        ch = values_text[i]
        if ch == "'":
            current.append(ch)
            if in_quote and i + 1 < len(values_text) and values_text[i + 1] == "'":
                current.append(values_text[i + 1])
                i += 2
                continue
            in_quote = not in_quote
            i += 1
            continue
        if ch == "," and not in_quote:
            parts.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current).strip())
    return parts


def patch_account_sql(text: str, config: ProductSqlConfig) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", config.organisation_dstart):
        raise ValueError("organisation_dstart must be YYYY-MM-DD")
    name = config.organisation_name.strip()
    if not name:
        raise ValueError("organisation_name is required")

    pattern = re.compile(
        r'(INSERT INTO "mdm_organisation"\s*\((?P<cols>.*?)\)\s*VALUES\s*\()(?P<vals>.*?)(\);)',
        re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        columns = [col.strip().strip('"') for col in match.group("cols").split(",")]
        values = split_sql_values(match.group("vals"))
        if len(columns) != len(values):
            raise ValueError("mdm_organisation column/value count mismatch")
        updates = {
            "dstart": sql_quote(config.organisation_dstart),
            "sname": sql_quote(jsonb_ja(name)),
            "rname": sql_quote(jsonb_ja(name)),
            "hierarchy_name": sql_quote(jsonb_ja("\\" + name)),
            "szk_bu_ka": sql_quote(jsonb_ja(name)),
        }
        for column, value in updates.items():
            values[columns.index(column)] = value
        return match.group(1) + ", ".join(values) + match.group(4)

    patched, count = pattern.subn(replace, text, count=1)
    if count != 1:
        raise ValueError("mdm_organisation insert was not found in 4.account.sql")
    return patched


def _valid_git_worktree(workdir: Path) -> bool:
    if not (workdir / ".git").is_dir():
        return False
    try:
        subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "--is-inside-work-tree"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "--verify", "HEAD"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except Exception:
        return False
    return True


def _run_git(cmd: list[str], timeout: int) -> None:
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                proc.kill()
        raise subprocess.TimeoutExpired(cmd, timeout) from exc
    rc = proc.returncode
    if rc:
        raise subprocess.CalledProcessError(rc, cmd, output=stdout, stderr=redact_url_credentials(stderr.strip()))


def redact_url_credentials(text: str) -> str:
    return re.sub(r"https://([^:@/\s]+):([^@/\s]+)@", r"https://\1:<redacted>@", text)


def format_git_failure(exc: subprocess.CalledProcessError) -> str:
    stderr = redact_url_credentials((exc.stderr or "").strip())
    stdout = redact_url_credentials((exc.output or "").strip())
    detail = stderr or stdout or "no git output"
    return f"git command failed with exit {exc.returncode}: {detail}"


def safe_repo_subdir(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return ""
    parts = Path(normalized).parts
    if normalized.startswith("/") or ":" in normalized or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe repository subdir: {value}")
    return normalized


def repo_subdir_from_input(value: str, *, repo_url: str, branch: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    repo = urllib.parse.urlparse(repo_url)
    repo_host = (repo.hostname or "").lower()
    if not parsed.scheme:
        schemeless = urllib.parse.urlparse(f"https://{raw}")
        if (schemeless.hostname or "").lower() == repo_host and "/-/tree/" in (schemeless.path or ""):
            parsed = schemeless
        else:
            return safe_repo_subdir(raw)
    input_host = (parsed.hostname or "").lower()
    if input_host != repo_host:
        raise ValueError("custom data synchronization URL must use configured repository host")
    repo_path = (repo.path or "").rstrip("/")
    input_path = (parsed.path or "").rstrip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    if not input_path.startswith(repo_path + "/-/tree/"):
        raise ValueError("custom data synchronization URL must point to configured repository tree")
    remainder = input_path[len(repo_path + "/-/tree/") :]
    url_branch, _, subdir = remainder.partition("/")
    if urllib.parse.unquote(url_branch) != branch or not subdir:
        raise ValueError("custom data synchronization URL must use configured branch and include a directory")
    return safe_repo_subdir(urllib.parse.unquote(subdir))


def _sparse_paths(paths: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if paths is None:
        return []
    if isinstance(paths, str):
        paths = [paths]
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = safe_repo_subdir(path)
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def sync_git_tree(
    repo_url: str,
    branch: str,
    workdir: Path,
    timeout: int = DEFAULT_DATA_SYNC_GIT_TIMEOUT,
    sparse_path: str | list[str] | tuple[str, ...] | None = None,
) -> None:
    sparse_paths = _sparse_paths(sparse_path)
    workdir.parent.mkdir(parents=True, exist_ok=True)
    if (workdir / ".git").is_dir() and not _valid_git_worktree(workdir):
        shutil.rmtree(workdir)
    if _valid_git_worktree(workdir):
        _run_git(["git", "-C", str(workdir), "remote", "set-url", "origin", repo_url], timeout)
        _run_git(["git", "-C", str(workdir), "fetch", "origin", branch, "--prune", "--depth", "1"], timeout)
        if sparse_paths:
            _run_git(["git", "-C", str(workdir), "sparse-checkout", "init", "--cone"], timeout)
            _run_git(["git", "-C", str(workdir), "sparse-checkout", "set", *sparse_paths], timeout)
        _run_git(["git", "-C", str(workdir), "checkout", "-B", branch, f"origin/{branch}"], timeout)
        _run_git(["git", "-C", str(workdir), "reset", "--hard", f"origin/{branch}"], timeout)
        _run_git(["git", "-C", str(workdir), "clean", "-fd"], timeout)
        return
    if workdir.exists():
        shutil.rmtree(workdir)
    if sparse_paths:
        _run_git(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                branch,
                repo_url,
                str(workdir),
            ],
            timeout,
        )
        _run_git(["git", "-C", str(workdir), "sparse-checkout", "set", *sparse_paths], timeout)
        return
    _run_git(["git", "clone", "--depth", "1", "--single-branch", "--branch", branch, repo_url, str(workdir)], timeout)


def _copy_allowed_data_sync_dirs(source: Path, target_dir: Path) -> None:
    def ignore_all_sql(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name.lower() == "all.sql"]

    for name in DATA_SYNC_ALLOWED_DIRS:
        child = source / name
        if child.is_dir():
            shutil.copytree(child, target_dir / name, dirs_exist_ok=True, ignore=ignore_all_sql)


def copy_data_sync_assets(
    *,
    repo_url: str,
    branch: str,
    workdir: Path,
    subdir: str,
    target_dir: Path,
    custom_subdir: str = "",
    logger: Any | None = None,
) -> None:
    primary_subdir = repo_subdir_from_input(subdir, repo_url=repo_url, branch=branch)
    overlay_subdir = repo_subdir_from_input(custom_subdir, repo_url=repo_url, branch=branch)
    if not primary_subdir:
        raise ValueError("data synchronization subdir is required")
    if logger:
        logger("data_sync_git_sync")
    source = workdir / Path(primary_subdir)
    overlay_source = workdir / Path(overlay_subdir) if overlay_subdir else None
    sparse_paths = [primary_subdir] + ([overlay_subdir] if overlay_subdir else [])
    try:
        sync_git_tree(repo_url, branch, workdir, sparse_path=sparse_paths)
    except subprocess.CalledProcessError as exc:
        if source.is_dir() and (overlay_source is None or overlay_source.is_dir()):
            if logger:
                logger("data_sync_cache_fallback")
        else:
            raise RuntimeError(format_git_failure(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        if source.is_dir() and (overlay_source is None or overlay_source.is_dir()):
            if logger:
                logger("data_sync_cache_fallback")
        else:
            raise RuntimeError(f"git command timed out after {exc.timeout} seconds") from exc
    if not source.is_dir():
        raise FileNotFoundError(f"missing data synchronization directory: {source}")
    if overlay_source is not None and not overlay_source.is_dir():
        raise FileNotFoundError(f"missing custom data synchronization directory: {overlay_source}")
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if logger:
        logger("data_sync_copy")
    target_dir.mkdir(parents=True, exist_ok=True)
    _copy_allowed_data_sync_dirs(source, target_dir)
    if overlay_source is not None:
        if logger:
            logger("data_sync_custom_copy")
        _copy_allowed_data_sync_dirs(overlay_source, target_dir)


def build_product_package(
    *,
    template_zip: Path,
    sql_template_dir: Path,
    output_root: Path,
    delivery_name: str | None = None,
    package_zip: Path,
    web_zip: Path,
    version: BuildVersion,
    config: StandaloneConfig,
    sql_config: ProductSqlConfig,
    tenant_import_config: TenantImportConfig | None = None,
    ohr_import_config: OhrImportConfig | None = None,
    sql_svn_url: str | None = None,
    data_sync_git_url: str | None = None,
    data_sync_branch: str = DEFAULT_DATA_SYNC_BRANCH,
    data_sync_dir: Path | None = None,
    data_sync_subdir: str = DEFAULT_DATA_SYNC_SUBDIR,
    data_sync_custom_subdir: str = DEFAULT_DATA_SYNC_CUSTOM_SUBDIR,
    data_sync_runner_config: DataSyncSqlRunnerConfig | None = None,
    include_help_sql: bool = True,
    include_minio: bool = False,
    enable_azure_blob_storage: bool = False,
    middleware_versions: dict[str, str] | None = None,
    middleware_cache_dir: Path | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    if not template_zip.is_file():
        raise FileNotFoundError(f"missing standalone template: {template_zip}")
    if not package_zip.is_file():
        raise FileNotFoundError(f"missing package.zip: {package_zip}")
    if not web_zip.is_file():
        raise FileNotFoundError(f"missing web.zip: {web_zip}")
    with tempfile.TemporaryDirectory() as sql_tmp:
        effective_sql_dir = sql_template_dir
        if sql_svn_url:
            effective_sql_dir = Path(sql_tmp) / "sql"
            if logger:
                logger("sql_svn_download")
            download_svn_http_tree(sql_svn_url, effective_sql_dir)
        if not (effective_sql_dir / "1.tenant").is_dir() or not (effective_sql_dir / "2.ohr").is_dir():
            raise FileNotFoundError(f"missing SQL templates under: {effective_sql_dir}")

        delivery_root = output_root / (delivery_name or version.build_id)
        product_dir = delivery_root / "製品"
        data_sync_target = delivery_root / "データ連携"
        if delivery_root.exists():
            shutil.rmtree(delivery_root)
        product_dir.mkdir(parents=True, exist_ok=True)

        if logger:
            logger("sql_template_copy")
        shutil.copytree(effective_sql_dir / "1.tenant", product_dir / "1.tenant")
        shutil.copytree(effective_sql_dir / "2.ohr", product_dir / "2.ohr")
        if data_sync_git_url:
            copy_data_sync_assets(
                repo_url=data_sync_git_url,
                branch=data_sync_branch,
                workdir=data_sync_dir or configured_data_sync_dir(),
                subdir=data_sync_subdir,
                target_dir=data_sync_target,
                custom_subdir=data_sync_custom_subdir,
                logger=logger,
            )
        effective_runner_config = data_sync_runner_config or DataSyncSqlRunnerConfig(
            ohr_host=config.postgresql_host,
            ohr_port=config.postgresql_port,
            ohr_user=config.postgresql_user,
            ohr_password=config.postgresql_password,
        )
        data_sync_runner = write_data_sync_sql_runner(data_sync_target, effective_runner_config)
        account_sql = product_dir / "2.ohr" / "4.account.sql"
        if logger:
            logger("account_sql_patch")
        account_sql.write_text(
            patch_account_sql(account_sql.read_text(encoding="utf-8"), sql_config),
            encoding="utf-8",
        )
        if include_help_sql:
            if logger:
                logger("help_sql_replace")
            _replace_help_sql_if_present(web_zip, product_dir / "1.tenant" / "ohr_help.sql")
        import_dir = delivery_root / "導入"
        if tenant_import_config:
            tenant_import_dir = import_dir / "tenant"
            tenant_import_dir.mkdir(parents=True, exist_ok=True)
            (tenant_import_dir / "import_plan.sql").write_text(
                render_tenant_import_sql(tenant_import_config),
                encoding="utf-8",
            )
        if ohr_import_config:
            ohr_import_dir = import_dir / "ohr"
            ohr_import_dir.mkdir(parents=True, exist_ok=True)
            (ohr_import_dir / "import_plan.sql").write_text(
                render_ohr_import_sql(ohr_import_config),
                encoding="utf-8",
            )
        complete_all_sql_scripts(delivery_root, excluded_roots=(data_sync_target,))
        (product_dir / "version.txt").write_text(render_version_txt(version), encoding="utf-8")

        final_zip = product_dir / "OneHrStandalone.zip"
        if logger:
            logger("standalone_zip_rebuild")
        selected_middleware = dict(middleware_versions or {})
        if not include_minio:
            selected_middleware.pop("minio", None)
        middleware_overrides = prepare_middleware_overrides(
            selected_middleware,
            template_zip=template_zip,
            cache_dir=middleware_cache_dir,
            logger=logger,
        )
        _rebuild_standalone_zip(
            template_zip,
            final_zip,
            package_zip,
            web_zip,
            config,
            middleware_overrides=middleware_overrides,
            include_minio=include_minio,
            enable_azure_blob_storage=enable_azure_blob_storage,
        )
        return {
            "product_dir": str(delivery_root),
            "standalone_zip": str(final_zip),
            "version_txt": str(product_dir / "version.txt"),
            "data_sync_runner": str(data_sync_runner),
            "size": final_zip.stat().st_size,
        }


def build_custom_package(
    *,
    template_zip: Path,
    sql_template_dir: Path,
    output_root: Path,
    delivery_name: str,
    package_zip: Path | None,
    web_zip: Path | None,
    selection: CustomPackageSelection,
    version: BuildVersion,
    config: StandaloneConfig,
    sql_config: ProductSqlConfig,
    tenant_import_config: TenantImportConfig | None = None,
    ohr_import_config: OhrImportConfig | None = None,
    sql_svn_url: str | None = None,
    data_sync_git_url: str | None = None,
    data_sync_branch: str = DEFAULT_DATA_SYNC_BRANCH,
    data_sync_dir: Path | None = None,
    data_sync_subdir: str = DEFAULT_DATA_SYNC_SUBDIR,
    data_sync_custom_subdir: str = DEFAULT_DATA_SYNC_CUSTOM_SUBDIR,
    data_sync_runner_config: DataSyncSqlRunnerConfig | None = None,
    include_minio: bool = False,
    enable_azure_blob_storage: bool = False,
    middleware_versions: dict[str, str] | None = None,
    middleware_cache_dir: Path | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    """Assemble a Standard customer package from explicitly selected components."""
    if not selection.any_selected():
        raise ValueError("custom package requires at least one selected component")
    if selection.backend and (package_zip is None or not package_zip.is_file()):
        raise FileNotFoundError(f"missing selected package.zip: {package_zip}")
    needs_web = selection.frontend or selection.help or selection.conf_prod
    if needs_web and (web_zip is None or not web_zip.is_file()):
        raise FileNotFoundError(f"missing selected web.zip: {web_zip}")
    if selection.runtime and not template_zip.is_file():
        raise FileNotFoundError(f"missing standalone template: {template_zip}")

    delivery_root = output_root / delivery_name
    if delivery_root.exists():
        shutil.rmtree(delivery_root)
    delivery_root.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Any] = {"product_dir": str(delivery_root)}

    if selection.backend and package_zip is not None:
        target = delivery_root / "package.zip"
        shutil.copy2(package_zip, target)
        outputs["package_zip"] = str(target)
    if needs_web and web_zip is not None:
        target = delivery_root / "web.zip"
        if selection.conf_prod or selection.runtime:
            target.write_bytes(_rewrite_web_zip_azure_proxy(web_zip, enable_azure_blob_storage))
        else:
            shutil.copy2(web_zip, target)
        outputs["web_zip"] = str(target)

    product_dir = delivery_root / "製品"
    data_sync_target = delivery_root / "データ連携"
    with tempfile.TemporaryDirectory() as sql_tmp:
        if selection.sql_assets:
            effective_sql_dir = sql_template_dir
            if sql_svn_url:
                effective_sql_dir = Path(sql_tmp) / "sql"
                if logger:
                    logger("sql_svn_download")
                download_svn_http_tree(sql_svn_url, effective_sql_dir)
            if not (effective_sql_dir / "1.tenant").is_dir() or not (effective_sql_dir / "2.ohr").is_dir():
                raise FileNotFoundError(f"missing SQL templates under: {effective_sql_dir}")
            if logger:
                logger("sql_template_copy")
            shutil.copytree(effective_sql_dir / "1.tenant", product_dir / "1.tenant")
            shutil.copytree(effective_sql_dir / "2.ohr", product_dir / "2.ohr")
            help_sql = product_dir / "1.tenant" / "ohr_help.sql"
            help_sql.unlink(missing_ok=True)
            account_sql = product_dir / "2.ohr" / "4.account.sql"
            if logger:
                logger("account_sql_patch")
            account_sql.write_text(
                patch_account_sql(account_sql.read_text(encoding="utf-8"), sql_config),
                encoding="utf-8",
            )
            if selection.help and web_zip is not None:
                if logger:
                    logger("help_sql_replace")
                _replace_help_sql_if_present(web_zip, help_sql)

        if selection.data_sync:
            if not data_sync_git_url:
                raise ValueError("data synchronization source is required when selected")
            copy_data_sync_assets(
                repo_url=data_sync_git_url,
                branch=data_sync_branch,
                workdir=data_sync_dir or configured_data_sync_dir(),
                subdir=data_sync_subdir,
                target_dir=data_sync_target,
                custom_subdir=data_sync_custom_subdir,
                logger=logger,
            )
            effective_runner_config = data_sync_runner_config or DataSyncSqlRunnerConfig(
                ohr_host=config.postgresql_host,
                ohr_port=config.postgresql_port,
                ohr_user=config.postgresql_user,
                ohr_password=config.postgresql_password,
            )
            outputs["data_sync_runner"] = str(write_data_sync_sql_runner(data_sync_target, effective_runner_config))

        if selection.import_plan:
            import_dir = delivery_root / "導入"
            if tenant_import_config:
                tenant_dir = import_dir / "tenant"
                tenant_dir.mkdir(parents=True, exist_ok=True)
                (tenant_dir / "import_plan.sql").write_text(render_tenant_import_sql(tenant_import_config), encoding="utf-8")
            if ohr_import_config:
                ohr_dir = import_dir / "ohr"
                ohr_dir.mkdir(parents=True, exist_ok=True)
                (ohr_dir / "import_plan.sql").write_text(render_ohr_import_sql(ohr_import_config), encoding="utf-8")

    if selection.sql_assets or selection.runtime:
        product_dir.mkdir(parents=True, exist_ok=True)
        version_txt = product_dir / "version.txt"
        version_txt.write_text(render_version_txt(version), encoding="utf-8")
        outputs["version_txt"] = str(version_txt)
    complete_all_sql_scripts(delivery_root, excluded_roots=(data_sync_target,))

    if selection.runtime:
        final_zip = product_dir / "OneHrStandalone.zip"
        if logger:
            logger("standalone_zip_rebuild")
        selected_middleware = dict(middleware_versions or {})
        if not include_minio:
            selected_middleware.pop("minio", None)
        middleware_overrides = prepare_middleware_overrides(
            selected_middleware,
            template_zip=template_zip,
            cache_dir=middleware_cache_dir,
            logger=logger,
        )
        _rebuild_standalone_zip(
            template_zip,
            final_zip,
            package_zip if selection.backend else None,
            web_zip if needs_web else None,
            config,
            middleware_overrides=middleware_overrides,
            include_minio=include_minio,
            enable_azure_blob_storage=enable_azure_blob_storage,
        )
        outputs["standalone_zip"] = str(final_zip)
        outputs["size"] = final_zip.stat().st_size
    return outputs


def build_nho_common_package(
    *,
    output_root: Path,
    build_id: str,
    delivery_name: str | None = None,
    package_zip: Path | None = None,
    web_zip: Path | None = None,
    database_assets_zip: Path | None = None,
    version: BuildVersion | None = None,
    logger: Any | None = None,
) -> dict[str, Any]:
    """Build the NHO common upgrade package.

    NHO does not include customer environment config, help, or the standalone installer shell.
    The output intentionally mirrors the historical upgrade package layout.
    """
    if package_zip is None and web_zip is None:
        raise ValueError("NHO common package requires package.zip or web.zip")
    if package_zip is not None and not package_zip.is_file():
        raise FileNotFoundError(f"missing package.zip: {package_zip}")
    if web_zip is not None and not web_zip.is_file():
        raise FileNotFoundError(f"missing web.zip: {web_zip}")
    if database_assets_zip is not None and not database_assets_zip.is_file():
        raise FileNotFoundError(f"missing NHO database assets zip: {database_assets_zip}")

    delivery_root = output_root / (delivery_name or build_id)
    if delivery_root.exists():
        shutil.rmtree(delivery_root)
    delivery_root.mkdir(parents=True, exist_ok=True)
    common_zip = delivery_root / "共通.zip"
    software_prefix = "共通/upgrade/実行環境資材/OneHrSuite/software/"
    database_asset_items: list[tuple[zipfile.ZipInfo, str]] = []
    database_asset_paths: list[str] = []
    if database_assets_zip is not None:
        with zipfile.ZipFile(database_assets_zip, "r") as assets:
            for item in assets.infolist():
                source = _safe_zip_member_name(item.filename)
                target = "共通/upgrade/データベース資材/" + source
                database_asset_items.append((item, target))
                if not item.is_dir():
                    database_asset_paths.append(source)
    readme = _render_nho_readme(database_asset_paths, package_zip is not None, web_zip is not None)
    version_text = render_version_txt(version) if version else ""

    if logger:
        logger("nho_common_zip_rebuild")
    with zipfile.ZipFile(common_zip, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for dirname in [
            "共通/",
            "共通/upgrade/",
            "共通/upgrade/実行環境資材/",
            "共通/upgrade/実行環境資材/OneHrSuite/",
            software_prefix,
        ]:
            zf.writestr(dirname, b"")
        if database_assets_zip is not None:
            zf.writestr("共通/upgrade/データベース資材/", b"")
            with zipfile.ZipFile(database_assets_zip, "r") as assets:
                for item, target in database_asset_items:
                    if item.is_dir():
                        zf.writestr(target.rstrip("/") + "/", b"")
                    else:
                        zf.writestr(target, assets.read(item))
        zf.writestr("共通/upgrade/readme.txt", readme.encode("utf-8"))
        if version_text:
            zf.writestr("共通/version.txt", version_text.encode("utf-8"))
        if package_zip is not None:
            zf.write(package_zip, software_prefix + "package.zip")
        if web_zip is not None:
            zf.write(web_zip, software_prefix + "web.zip")
    return {
        "product_dir": str(delivery_root),
        "common_zip": str(common_zip),
        "package_zip": str(package_zip) if package_zip else "",
        "web_zip": str(web_zip) if web_zip else "",
        "database_assets_zip": str(database_assets_zip) if database_assets_zip else "",
        "size": common_zip.stat().st_size,
    }


def help_sql_from_web_zip(web_zip: Path) -> str:
    with zipfile.ZipFile(web_zip) as zf:
        try:
            data = zf.read(HELP_SQL_IN_WEB_ZIP)
        except KeyError:
            raise FileNotFoundError(f"missing Help SQL in web.zip: {HELP_SQL_IN_WEB_ZIP}") from None
    text = data.decode("utf-8-sig")
    _validate_help_sql_matches_web_zip(web_zip, text)
    if not text.lstrip().lower().startswith("delete from ohr_help"):
        text = HELP_SQL_RESET_PREFIX + text
    return text


def _replace_help_sql_if_present(web_zip: Path, target: Path) -> None:
    text = help_sql_from_web_zip(web_zip)
    target.write_text(text, encoding="utf-8")


def _extract_help_sql_doc_paths(sql_text: str) -> set[str]:
    paths: set[str] = set()
    for match in HELP_DOC_PATH_RE.finditer(sql_text):
        path = match.group(0).rstrip("/") + "/"
        paths.add(path)
    return paths


def _extract_help_doc_index_paths(zf: zipfile.ZipFile) -> set[str]:
    prefix = "ohr-cicd/web_prod/help/"
    paths: set[str] = set()
    for name in zf.namelist():
        if not name.startswith(prefix) or not name.endswith("/index.html"):
            continue
        rel = name[len(prefix) :]
        if HELP_DOC_UUID_RE.search(rel):
            paths.add(rel.rsplit("/", 1)[0].rstrip("/") + "/")
    return paths


def _validate_help_sql_matches_web_zip(web_zip: Path, sql_text: str) -> None:
    sql_paths = _extract_help_sql_doc_paths(sql_text)
    with zipfile.ZipFile(web_zip) as zf:
        doc_paths = _extract_help_doc_index_paths(zf)
    if not sql_paths and not doc_paths:
        return
    if not sql_paths:
        raise ValueError("Help SQL does not contain docs paths")
    if not doc_paths:
        raise ValueError("web.zip does not contain Help docs index files")
    missing_docs = sorted(sql_paths - doc_paths)
    missing_sql = sorted(doc_paths - sql_paths)
    if missing_docs or missing_sql:
        details = []
        if missing_docs:
            details.append("missing docs for SQL paths: " + ", ".join(missing_docs[:5]))
        if missing_sql:
            details.append("missing SQL rows for docs paths: " + ", ".join(missing_sql[:5]))
        raise ValueError("Help SQL and Help docs are inconsistent; " + "; ".join(details))


def _set_azure_proxy_enabled(text: str, enabled: bool) -> str:
    lines = text.splitlines(keepends=True)
    in_azure_block = False
    found = False
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        normalized = re.sub(r"^\s*#\s?", "", content)
        if not in_azure_block and normalized.startswith("location ~ ^/azure/"):
            in_azure_block = True
            found = True
        if not in_azure_block:
            continue
        if enabled:
            content = re.sub(r"^(\s*)#\s?", r"\1", content)
        elif not re.match(r"^\s*#", content):
            content = f"# {content}"
        lines[index] = content + ending
        if normalized.strip() == "}":
            in_azure_block = False
    if not found:
        return text
    return "".join(lines)


def _rewrite_web_zip_azure_proxy(web_zip: Path, enabled: bool) -> bytes:
    try:
        with zipfile.ZipFile(web_zip, "r") as source:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as target:
                for item in source.infolist():
                    data = source.read(item)
                    if item.filename.lower().endswith(("/api-proxy.conf", "/api-proxy-debug.conf")):
                        text = data.decode("utf-8-sig", "replace")
                        data = _set_azure_proxy_enabled(text, enabled).encode("utf-8")
                    target.writestr(item, data)
            return output.getvalue()
    except zipfile.BadZipFile:
        return web_zip.read_bytes()


def _rebuild_standalone_zip(
    template_zip: Path,
    final_zip: Path,
    package_zip: Path | None,
    web_zip: Path | None,
    config: StandaloneConfig,
    middleware_overrides: dict[str, Path] | None = None,
    include_minio: bool = False,
    enable_azure_blob_storage: bool = False,
) -> None:
    middleware_overrides = middleware_overrides or {}
    minio_member = MIDDLEWARE_IN_STANDALONE_ZIP["minio"]
    final_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=final_zip.parent, suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(template_zip, "r") as zin, zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zout:
            for item in zin.infolist():
                if item.filename in {PACKAGE_IN_STANDALONE_ZIP, WEB_IN_STANDALONE_ZIP} or item.filename in middleware_overrides:
                    continue
                if item.filename == minio_member and not include_minio:
                    continue
                if item.filename == CONFIG_IN_STANDALONE_ZIP:
                    original = zin.read(item).decode("utf-8-sig", "replace")
                    zout.writestr(item, update_config_ini(original, config).encode("utf-8"))
                    continue
                zout.writestr(item, zin.read(item))
            if package_zip is not None:
                zout.write(package_zip, PACKAGE_IN_STANDALONE_ZIP)
            if web_zip is not None:
                zout.writestr(WEB_IN_STANDALONE_ZIP, _rewrite_web_zip_azure_proxy(web_zip, enable_azure_blob_storage))
            for member, source in sorted(middleware_overrides.items()):
                if member == minio_member and not include_minio:
                    continue
                if not source.is_file():
                    raise FileNotFoundError(f"missing middleware cache: {source}")
                zout.write(source, member)
        tmp_path.replace(final_zip)
    finally:
        tmp_path.unlink(missing_ok=True)


def download_remote_artifact(remote_base_url: str, build_id: str, name: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"{remote_base_url.rstrip('/')}/api/builds/{build_id}/artifact/{name}"
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as f:
        shutil.copyfileobj(response, f)
    return destination


def download_remote_file(remote_base_url: str, path: str, destination: Path, timeout: int = 300) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = remote_base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, destination.open("wb") as f:
            shutil.copyfileobj(response, f)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"remote request failed {exc.code}: {body}") from exc
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
