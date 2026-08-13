#!/usr/bin/env python3
"""Fail-loud validation for the canonical production devUI gateway producer."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_PUBLISH = '"127.0.0.1:8113:8113"'
_DECLARATION = re.compile(r"^\s+COMPANION_UI_BIND_HOST:\s+127\.0\.0\.1\s*$", re.MULTILINE)


def validate(compose_file: Path) -> None:
    text = compose_file.read_text(encoding="utf-8")
    if text.count(_PUBLISH) != 1:
        raise ValueError("production Companion must publish exactly 127.0.0.1:8113:8113")
    if len(_DECLARATION.findall(text)) != 1:
        raise ValueError("production Companion must declare COMPANION_UI_BIND_HOST=127.0.0.1")
    if "${COMPANION_UI_BIND_HOST" in text:
        raise ValueError("production Companion bind must not depend on ambient interpolation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compose_file", type=Path)
    args = parser.parse_args()
    try:
        validate(args.compose_file)
    except (OSError, ValueError) as exc:
        parser.exit(78, f"prod devUI gateway preflight: blocked: {exc}\n")
    print("prod devUI gateway preflight: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
