from pathlib import Path


def test_secret_env_encrypt_and_restore_roundtrip(tmp_path, monkeypatch):
    import scripts.secret_env as secret_env

    root = tmp_path
    monkeypatch.setattr(secret_env, "ROOT", root)
    monkeypatch.setattr(secret_env, "KEY_FILE", root / ".secrets.key")
    monkeypatch.setattr(secret_env, "MANIFEST_FILE", root / "secrets" / "manifest.json")
    monkeypatch.delenv("OHR_SECRET_KEY", raising=False)

    plain = root / "vm-access.env"
    encrypted = root / "secrets" / "vm-access.env.enc"
    plain.write_text("HV_VM_HOST=example\nHV_VM_SSH_PASSWORD=secret\n", encoding="utf-8")

    key = secret_env.load_key(create=True)
    crypt = secret_env.Fernet(key)
    item = secret_env.SecretItem("vm-access", plain, encrypted)

    assert secret_env.encrypt_item(item, crypt)
    assert encrypted.read_text(encoding="utf-8") != plain.read_text(encoding="utf-8")

    plain.unlink()
    assert secret_env.restore_item(item, crypt)
    assert plain.read_text(encoding="utf-8") == "HV_VM_HOST=example\nHV_VM_SSH_PASSWORD=secret\n"


def test_secret_env_manifest_paths_are_relative(tmp_path, monkeypatch):
    import scripts.secret_env as secret_env

    root = tmp_path
    monkeypatch.setattr(secret_env, "ROOT", root)
    monkeypatch.setattr(secret_env, "MANIFEST_FILE", root / "secrets" / "manifest.json")

    secret_env.write_default_manifest()

    text = (root / "secrets" / "manifest.json").read_text(encoding="utf-8")
    assert "vm-access.env" in text
    assert str(root) not in text
