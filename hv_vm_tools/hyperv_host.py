from __future__ import annotations

import json
import subprocess
from typing import Any


def _ps_json(script: str) -> tuple[int, str, str]:
    full = (
        "$ErrorActionPreference='Stop';"
        "Import-Module Hyper-V -ErrorAction Stop;"
        + script
    )
    p = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", full],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def list_vms() -> tuple[list[dict[str, Any]] | None, str]:
    """返回本机 Hyper-V 上所有 VM 的 Name/State（需模块与权限）。"""
    script = "Get-VM | Select-Object Name,State,Id | ConvertTo-Json -Depth 3 -Compress"
    code, out, err = _ps_json(script)
    if code != 0:
        return None, (err or out or f"exit {code}").strip()
    raw = out.strip()
    if not raw:
        return [], ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}: {raw[:500]}"
    if isinstance(data, dict):
        return [data], ""
    if isinstance(data, list):
        return data, ""
    return None, f"unexpected JSON type: {type(data)}"


def vm_state(name: str) -> tuple[dict[str, Any] | None, str]:
    script = (
        f"$vm = Get-VM -Name {json.dumps(name)} -ErrorAction Stop; "
        "$vm | Select-Object Name,State,ProcessorCount,MemoryStartup,Id | ConvertTo-Json -Compress"
    )
    code, out, err = _ps_json(script)
    if code != 0:
        return None, (err or out or f"exit {code}").strip()
    try:
        return json.loads(out.strip()), ""
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"


def vm_action(name: str, action: str) -> tuple[bool, str]:
    """action: start | stop | restart | save (暂停)"""
    n = json.dumps(name)
    templates = {
        "start": f"Start-VM -Name {n} -ErrorAction Stop",
        "stop": f"Stop-VM -Name {n} -Force -ErrorAction Stop",
        "restart": f"Restart-VM -Name {n} -Force -ErrorAction Stop",
        "save": f"Save-VM -Name {n} -ErrorAction Stop",
    }
    if action not in templates:
        return False, f"unknown action: {action}"
    script = templates[action]
    code, out, err = _ps_json(script)
    if code != 0:
        return False, (err or out or f"exit {code}").strip()
    return True, (out or "ok").strip()
