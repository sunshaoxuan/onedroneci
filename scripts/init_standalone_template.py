#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from standalone_packager import configured_sql_template_dir, configured_template_zip, init_template_cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the host-side OneHrStandalone fixed template cache.")
    parser.add_argument("--source", type=Path, default=Path("tests") / "製品", help="Directory containing OneHrStandalone.zip, 1.tenant and 2.ohr")
    parser.add_argument("--template-zip", type=Path, default=configured_template_zip())
    parser.add_argument("--sql-template-dir", type=Path, default=configured_sql_template_dir())
    args = parser.parse_args()
    init_template_cache(args.source, args.template_zip, args.sql_template_dir)
    print(f"template zip: {args.template_zip}")
    print(f"sql templates: {args.sql_template_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
