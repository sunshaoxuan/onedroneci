from __future__ import annotations

import importlib.util
from pathlib import Path


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
        }
    )

    assert meta["request"]["build_backend"] is False
    assert meta["request"]["build_frontend"] is True
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
            "note": "smoke",
        }
    )

    assert meta["executor"] == "direct"
    assert meta["request"]["backend_branch"] == "release_20260129"
    assert meta["request"]["frontend_workspace_branch"] == "master"
    assert meta["request"]["frontend_release_branch"] == "release_front"
    assert (tmp_path / meta["id"] / "metadata.json").is_file()
    assert [step["id"] for step in meta["steps"]] == list(server.DIRECT_STEP_IDS)


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
            }
        )
    except ValueError as exc:
        assert "Drone 执行器未配置" in str(exc)
    else:
        raise AssertionError("missing Drone config should fail")


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


def test_list_backend_release_branches_parses_refs(monkeypatch, tmp_path):
    server = load_server()
    monkeypatch.setattr(server, "OHR_BACK_DIR", tmp_path)

    class Result:
        returncode = 0
        stdout = (
            "abc\trefs/heads/release_20260501\n"
            "def\trefs/heads/feature/demo\n"
            "ghi\trefs/heads/release_20260502\n"
        )
        stderr = ""

    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: Result())

    assert server.list_backend_release_branches() == ["release_20260502", "release_20260501"]


def test_direct_frontend_build_uses_bundle_zip_only():
    server = load_server()
    script = server.DIRECT_FRONTEND_BUILD_SCRIPT

    assert "npm run build" in script
    assert "npm run bundle" in script
    assert "release_*.zip" in script
    assert "前端发布包生成失败" in script
    assert 'zip -r "$OUT_WEB_ZIP" .' not in script
    assert "node_modules/*" not in script
