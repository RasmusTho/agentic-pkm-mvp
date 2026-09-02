#!/usr/bin/env python3
"""Run the governed light-path closure adapter."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Sequence
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from app.builderops.closure import CommandExecutor, cli_main
def main(argv: Sequence[str] | None = None, *, executor: CommandExecutor | None = None) -> int: return cli_main(argv, executor=executor)
if __name__ == "__main__": raise SystemExit(main())
