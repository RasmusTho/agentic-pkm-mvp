#!/usr/bin/env python3
"""Compatibility entrypoint for the git hygiene preflight report."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.git_hygiene import main_with_default_command


if __name__ == "__main__":
    raise SystemExit(main_with_default_command("preflight", sys.argv[1:]))
