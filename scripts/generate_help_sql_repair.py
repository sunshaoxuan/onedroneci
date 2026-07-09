from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from standalone_packager import WEB_IN_STANDALONE_ZIP, help_sql_from_web_zip


def resolve_source(source: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if source.is_dir():
        candidates = [
            source / "製品" / "OneHrStandalone.zip",
            source / "OneHrStandalone.zip",
            source / "web.zip",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return resolve_source(candidate)
        raise FileNotFoundError(f"no OneHrStandalone.zip or web.zip found under {source}")

    if source.name.lower() == "web.zip":
        return source, None

    tmp = tempfile.TemporaryDirectory(prefix="ohr_help_repair_")
    web_zip = Path(tmp.name) / "web.zip"
    with zipfile.ZipFile(source) as zf:
        try:
            with zf.open(WEB_IN_STANDALONE_ZIP) as src, web_zip.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        except KeyError:
            tmp.cleanup()
            raise FileNotFoundError(f"missing web.zip in standalone package: {WEB_IN_STANDALONE_ZIP}") from None
    return web_zip, tmp


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate full rebuild SQL for ohr_help from a packaged web.zip.")
    parser.add_argument("source", type=Path, help="web.zip, OneHrStandalone.zip, or a delivery directory")
    parser.add_argument("-o", "--output", type=Path, help="output SQL path")
    args = parser.parse_args()

    web_zip, tmp = resolve_source(args.source)
    try:
        sql = help_sql_from_web_zip(web_zip)
        output = args.output or (args.source if args.source.is_dir() else args.source.parent) / "ohr_help_rebuild.sql"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(sql, encoding="utf-8")
        print(output)
        return 0
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
