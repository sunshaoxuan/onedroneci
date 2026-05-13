from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import host_standalone_console as console


@dataclass(frozen=True)
class FakeSettings:
    vm_host: str = "build-host.example"
    ssh_user: str | None = None
    ssh_port: int = 22
    hyperv_vm_name: str | None = None


def test_default_host_console_bind_is_fixed():
    assert console.HOST == "0.0.0.0"
    assert console.PORT == 8091


def test_start_script_stops_process_occupying_fixed_port():
    script = Path("scripts/start_host_standalone_console.ps1").read_text(encoding="utf-8")
    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in script
    assert "Stop-Process -Id $Owner -Force" in script
    assert "HOST_STANDALONE_CONSOLE_HOST" in script
    assert "0.0.0.0" in script
    assert "8091" in script


def test_build_terminal_status_is_safe_when_vm_name_is_missing(monkeypatch):
    monkeypatch.setattr(console.Settings, "from_env", classmethod(lambda cls: FakeSettings()))
    monkeypatch.setattr(console, "is_remote_console_reachable", lambda: False)

    assert console.build_terminal_status() == {
        "status": "unconfigured",
        "configured": False,
        "reachable": False,
    }


def test_build_terminal_action_does_not_accept_page_vm_name(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        console.Settings,
        "from_env",
        classmethod(lambda cls: FakeSettings(hyperv_vm_name="OnlyAllowedVm")),
    )
    monkeypatch.setattr(console.hyperv_host, "vm_action", lambda name, action: (calls.append((name, action)) or ({}, "")))

    result = console.build_terminal_action("start")

    assert result["ok"] is True
    assert calls == [("OnlyAllowedVm", "start")]
    assert console.build_terminal_action("restart") == {"status": "invalid_action", "ok": False}


def test_build_terminal_action_reports_permission_error(monkeypatch):
    monkeypatch.setattr(
        console.Settings,
        "from_env",
        classmethod(lambda cls: FakeSettings(hyperv_vm_name="OnlyAllowedVm")),
    )
    monkeypatch.setattr(console.hyperv_host, "vm_action", lambda name, action: (None, "Access is denied"))

    result = console.build_terminal_action("stop")

    assert result["ok"] is False
    assert result["status"] == "permission_denied"


def test_page_assets_do_not_expose_build_terminal_address():
    assert "192.168.250.50" not in console.INDEX_HTML
    assert "192.168.250.50" not in console.APP_JS
    assert "250.50" not in console.INDEX_HTML
    assert "250.50" not in console.APP_JS


def test_i18n_contains_terminal_controls_and_statuses():
    for lang in ("ja-JP", "zh-CN", "en-US"):
        assert f"'{lang}'" in console.APP_JS
    for key in (
        "terminalRunning",
        "terminalStopped",
        "terminalUnreachable",
        "terminalPermissionDenied",
        "terminalUnconfigured",
        "startTerminal",
        "stopTerminal",
        "refreshStatus",
    ):
        assert key in console.APP_JS
