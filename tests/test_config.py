import os

from hv_vm_tools.config import Settings, load_vm_access_env_files


def test_settings_defaults(monkeypatch):
    monkeypatch.setattr("hv_vm_tools.config.load_vm_access_env_files", lambda: None)
    monkeypatch.delenv("HV_VM_HOST", raising=False)
    s = Settings.from_env()
    assert s.vm_host == "192.168.250.50"
    assert s.ssh_user is None
    assert s.ssh_port == 22


def test_settings_env(monkeypatch):
    monkeypatch.setattr("hv_vm_tools.config.load_vm_access_env_files", lambda: None)
    monkeypatch.setenv("HV_VM_HOST", "10.0.0.1")
    monkeypatch.setenv("HV_VM_SSH_USER", "root")
    monkeypatch.setenv("HV_VM_SSH_PORT", "2222")
    monkeypatch.setenv("HV_HYPERV_VM_NAME", "lab")
    s = Settings.from_env()
    assert s.vm_host == "10.0.0.1"
    assert s.ssh_user == "root"
    assert s.ssh_port == 2222
    assert s.hyperv_vm_name == "lab"


def test_vm_access_env_file_parsing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("HV_UNIQUE_X", "HV_UNIQUE_Y", "HV_UNIQUE_Z"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "vm-access.env").write_text(
        "# comment\nHV_UNIQUE_X=1\nHV_UNIQUE_Y=\"a#b\"\nexport HV_UNIQUE_Z = z\n",
        encoding="utf-8",
    )
    load_vm_access_env_files()
    assert os.environ.get("HV_UNIQUE_X") == "1"
    assert os.environ.get("HV_UNIQUE_Y") == "a#b"
    assert os.environ.get("HV_UNIQUE_Z") == "z"


def test_setdefault_does_not_override(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HV_UNIQUE_PRESET", "from-shell")
    (tmp_path / "vm-access.env").write_text("HV_UNIQUE_PRESET=file\n", encoding="utf-8")
    load_vm_access_env_files()
    assert os.environ.get("HV_UNIQUE_PRESET") == "from-shell"

