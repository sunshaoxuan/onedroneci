from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _strip_env_value(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_env_value(val))


def load_vm_access_env_files() -> None:
    """从当前工作目录或项目根目录加载 vm-access.env（不覆盖已有环境变量）。"""
    project_root = Path(__file__).resolve().parents[1]
    for base in (Path.cwd(), project_root):
        _load_env_file(base / "vm-access.env")


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else default


@dataclass(frozen=True)
class Settings:
    """从环境变量读取，便于 CI / 本机 shell 配置。"""

    vm_host: str
    ssh_user: str | None
    ssh_port: int
    hyperv_vm_name: str | None

    @classmethod
    def from_env(cls) -> Settings:
        load_vm_access_env_files()
        return cls(
            vm_host=_env("HV_VM_HOST", "192.168.250.50"),
            ssh_user=os.environ.get("HV_VM_SSH_USER"),
            ssh_port=int(_env("HV_VM_SSH_PORT", "22")),
            hyperv_vm_name=os.environ.get("HV_HYPERV_VM_NAME"),
        )
