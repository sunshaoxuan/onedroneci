from __future__ import annotations

import json
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
DEFAULT_DATA_SYNC_GIT_TIMEOUT = int(os.environ.get("DATA_SYNC_GIT_TIMEOUT", "300"))
DATA_SYNC_ALLOWED_DIRS = ("ForeignTable", "Function", "Procedure", "Sequence", "Table", "View")
HELP_SQL_IN_WEB_ZIP = "ohr-cicd/web_prod/help/insert_ohr_help.sql"
HELP_SQL_RESET_PREFIX = "DELETE FROM ohr_help;\n"
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
    material_number: str
    backend_branch: str
    frontend_branch: str


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


def configured_output_dir() -> Path:
    return Path(os.environ.get("STANDALONE_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))


def configured_template_zip() -> Path:
    return Path(os.environ.get("STANDALONE_TEMPLATE_ZIP", str(DEFAULT_TEMPLATE_ZIP)))


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


def complete_all_sql_scripts(root: Path) -> dict[str, list[str]]:
    completed: dict[str, list[str]] = {}
    for all_sql in sorted(root.rglob("all.sql"), key=lambda path: str(path).lower()):
        sql_files = sorted(
            (
                item.name
                for item in all_sql.parent.iterdir()
                if item.is_file() and item.suffix.lower() == ".sql" and item.name.lower() != "all.sql"
            ),
            key=str.lower,
        )
        if not sql_files:
            continue
        text = all_sql.read_text(encoding="utf-8-sig")
        known = _referenced_sql_filenames(text)
        missing = [name for name in sql_files if name.lower() not in known]
        if not missing:
            continue
        separator = "" if not text or text.endswith(("\n", "\r")) else "\n"
        addition = "\n".join(_include_sql_line(name) for name in missing) + "\n"
        all_sql.write_text(text + separator + addition, encoding="utf-8")
        completed[str(all_sql.relative_to(root)).replace("\\", "/")] = missing
    return completed


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
    for name in DATA_SYNC_ALLOWED_DIRS:
        child = source / name
        if child.is_dir():
            shutil.copytree(child, target_dir / name, dirs_exist_ok=True)


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
    include_help_sql: bool = True,
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

        delivery_root = output_root / version.build_id
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
        complete_all_sql_scripts(delivery_root)
        (product_dir / "version.txt").write_text(render_version_txt(version), encoding="utf-8")

        final_zip = product_dir / "OneHrStandalone.zip"
        if logger:
            logger("standalone_zip_rebuild")
        _rebuild_standalone_zip(template_zip, final_zip, package_zip, web_zip, config)
        return {
            "product_dir": str(delivery_root),
            "standalone_zip": str(final_zip),
            "version_txt": str(product_dir / "version.txt"),
            "size": final_zip.stat().st_size,
        }


def build_nho_common_package(
    *,
    output_root: Path,
    build_id: str,
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

    delivery_root = output_root / build_id
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


def _replace_help_sql_if_present(web_zip: Path, target: Path) -> None:
    with zipfile.ZipFile(web_zip) as zf:
        try:
            data = zf.read(HELP_SQL_IN_WEB_ZIP)
        except KeyError:
            raise FileNotFoundError(f"missing Help SQL in web.zip: {HELP_SQL_IN_WEB_ZIP}") from None
    text = data.decode("utf-8-sig")
    if not text.lstrip().lower().startswith("delete from ohr_help"):
        text = HELP_SQL_RESET_PREFIX + text
    target.write_text(text, encoding="utf-8")


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
