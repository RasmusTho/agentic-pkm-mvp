#!/usr/bin/env python3
"""Run the governed normal-path publication plan/apply adapter."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.publication import CommandExecutor, cli_main


def main(
    argv: Sequence[str] | None = None,
    *,
    executor: CommandExecutor | None = None,
) -> int:
    return cli_main(argv, executor=executor)


if __name__ == "__main__":
    raise SystemExit(main())
