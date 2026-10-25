#!/usr/bin/env python3
"""Publish the owner-admitted private CKM snapshot using its fixed operator path."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ops.devui_ckm_snapshot import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
