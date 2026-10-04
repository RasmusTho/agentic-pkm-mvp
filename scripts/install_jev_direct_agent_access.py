#!/usr/bin/env python3
"""Install the local Jev command and skill for Codex and Claude Code."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "jev-direct"


def _copy_atomically(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise OSError("refusing a symlink destination")
    if destination.exists() and not destination.is_file():
        raise OSError("destination is not a regular file")
    if (
        destination.is_file()
        and destination.read_bytes() == source.read_bytes()
        and stat.S_IMODE(destination.stat().st_mode) == mode
    ):
        return

    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as staged:
            temp_name = staged.name
            with source.open("rb") as source_file:
                shutil.copyfileobj(source_file, staged)
        os.chmod(temp_name, mode)
        os.replace(temp_name, destination)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def install(home: Path) -> None:
    command_source = ROOT / "scripts" / "ygg_jev.py"
    skill_source = ROOT / ".codex" / "skills" / SKILL_NAME / "SKILL.md"
    if not command_source.is_file() or not skill_source.is_file():
        raise FileNotFoundError("Jev direct source files are unavailable")

    _copy_atomically(command_source, home / ".local" / "bin" / "jev-direct", 0o755)
    for agent_dir in (".codex", ".claude"):
        destination = (
            home / agent_dir / "skills" / SKILL_NAME / "SKILL.md"
        )
        _copy_atomically(skill_source, destination, 0o644)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    try:
        install(args.home.expanduser())
    except OSError:
        print("Jev direct installation failed.", file=sys.stderr)
        return 1
    print("Installed Jev direct command and Codex/Claude skill for this user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
