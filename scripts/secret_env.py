"""Encrypt and restore local environment files.

Encrypted blobs are safe to commit only when the Fernet key is kept outside Git.
The key is read from OHR_SECRET_KEY or from a local .secrets.key file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception as exc:  # pragma: no cover - dependency error path
    raise SystemExit("cryptography is required: python -m pip install cryptography") from exc


ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / ".secrets.key"
MANIFEST_FILE = ROOT / "secrets" / "manifest.json"


@dataclass(frozen=True)
class SecretItem:
    name: str
    plaintext: Path
    encrypted: Path
    required: bool = False


def default_items() -> list[SecretItem]:
    return [
        SecretItem("vm-access", ROOT / "vm-access.env", ROOT / "secrets" / "vm-access.env.enc"),
        SecretItem("git-access", ROOT / "git-access.env", ROOT / "secrets" / "git-access.env.enc"),
        SecretItem(
            "build-console",
            ROOT / "build-console" / "build-console.env",
            ROOT / "secrets" / "build-console.env.enc",
        ),
        SecretItem("drone", ROOT / "deploy" / "drone" / "drone.env", ROOT / "secrets" / "drone.env.enc"),
    ]


def load_key(create: bool = False) -> bytes:
    env_key = os.environ.get("OHR_SECRET_KEY")
    if env_key:
        return env_key.encode("ascii")
    if KEY_FILE.is_file():
        return KEY_FILE.read_text(encoding="utf-8").strip().encode("ascii")
    if not create:
        raise SystemExit("Missing OHR_SECRET_KEY or .secrets.key. Run: python scripts\\secret_env.py init-key")
    key = Fernet.generate_key()
    KEY_FILE.write_text(key.decode("ascii") + "\n", encoding="utf-8")
    return key


def fernet(create_key: bool = False) -> Fernet:
    return Fernet(load_key(create=create_key))


def read_manifest_items() -> list[SecretItem]:
    if not MANIFEST_FILE.is_file():
        return default_items()
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    items = []
    for entry in data.get("items", []):
        items.append(
            SecretItem(
                name=entry["name"],
                plaintext=ROOT / entry["plaintext"],
                encrypted=ROOT / entry["encrypted"],
                required=bool(entry.get("required", False)),
            )
        )
    return items


def write_default_manifest() -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "key": "OHR_SECRET_KEY or local .secrets.key",
        "items": [
            {
                "name": item.name,
                "plaintext": item.plaintext.relative_to(ROOT).as_posix(),
                "encrypted": item.encrypted.relative_to(ROOT).as_posix(),
                "required": item.required,
            }
            for item in default_items()
        ],
    }
    MANIFEST_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def encrypt_item(item: SecretItem, crypt: Fernet) -> bool:
    if not item.plaintext.is_file():
        if item.required:
            raise FileNotFoundError(f"missing required secret file: {item.plaintext}")
        return False
    item.encrypted.parent.mkdir(parents=True, exist_ok=True)
    token = crypt.encrypt(item.plaintext.read_bytes())
    item.encrypted.write_bytes(token + b"\n")
    return True


def restore_item(item: SecretItem, crypt: Fernet, overwrite: bool = False) -> bool:
    if not item.encrypted.is_file():
        if item.required:
            raise FileNotFoundError(f"missing required encrypted file: {item.encrypted}")
        return False
    if item.plaintext.exists() and not overwrite:
        return False
    item.plaintext.parent.mkdir(parents=True, exist_ok=True)
    try:
        plaintext = crypt.decrypt(item.encrypted.read_bytes().strip())
    except InvalidToken as exc:
        raise SystemExit(f"invalid key or corrupted encrypted file: {item.encrypted}") from exc
    item.plaintext.write_bytes(plaintext)
    return True


def decrypt_item_to_stdout(item: SecretItem, crypt: Fernet) -> None:
    if not item.encrypted.is_file():
        raise FileNotFoundError(f"missing encrypted file: {item.encrypted}")
    try:
        plaintext = crypt.decrypt(item.encrypted.read_bytes().strip())
    except InvalidToken as exc:
        raise SystemExit(f"invalid key or corrupted encrypted file: {item.encrypted}") from exc
    sys.stdout.buffer.write(plaintext)


def find_item(name: str) -> SecretItem:
    for item in read_manifest_items():
        if item.name == name:
            return item
    raise SystemExit(f"unknown secret item: {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypt and restore local env secrets.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-key", help="create .secrets.key if no OHR_SECRET_KEY is set")
    sub.add_parser("init-manifest", help="write the default secrets manifest")
    sub.add_parser("encrypt", help="encrypt all configured local secret files")
    restore = sub.add_parser("restore", help="restore encrypted secret files")
    restore.add_argument("--overwrite", action="store_true", help="overwrite existing plaintext files")
    decrypt = sub.add_parser("decrypt", help="decrypt one item to stdout")
    decrypt.add_argument("name", help="item name from secrets/manifest.json")
    args = parser.parse_args(argv)

    if args.cmd == "init-key":
        load_key(create=True)
        print(f"key ready: {KEY_FILE}")
        return 0
    if args.cmd == "init-manifest":
        write_default_manifest()
        print(f"manifest ready: {MANIFEST_FILE}")
        return 0
    if args.cmd == "encrypt":
        if not MANIFEST_FILE.is_file():
            write_default_manifest()
        crypt = fernet(create_key=True)
        count = sum(1 for item in read_manifest_items() if encrypt_item(item, crypt))
        print(f"encrypted {count} file(s)")
        return 0
    if args.cmd == "restore":
        crypt = fernet()
        count = sum(1 for item in read_manifest_items() if restore_item(item, crypt, overwrite=args.overwrite))
        print(f"restored {count} file(s)")
        return 0
    if args.cmd == "decrypt":
        decrypt_item_to_stdout(find_item(args.name), fernet())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
