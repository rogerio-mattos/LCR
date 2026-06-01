#!/usr/bin/env python3
"""Sync release version from pyproject.toml into AppStream metainfo."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
METAINFO = ROOT / "data" / "com.linuxcustomresolution.LCR.metainfo.xml"


def read_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def update_metainfo(version: str) -> None:
    text = METAINFO.read_text(encoding="utf-8")
    today = date.today().isoformat()

    if re.search(r'<release version="[^"]+" date="[^"]+">', text):
        text = re.sub(
            r'(<release version=")([^"]+)(" date=")([^"]+)(">)',
            rf'\g<1>{version}\g<3>{today}\g<5>',
            text,
            count=1,
        )
    else:
        raise SystemExit("No <release> block found in metainfo.xml")

    METAINFO.write_text(text, encoding="utf-8")
    print(f"Updated metainfo release to {version} ({today})")


def main() -> None:
    version = read_version()
    if len(sys.argv) > 1:
        version = sys.argv[1]
    update_metainfo(version)


if __name__ == "__main__":
    main()
