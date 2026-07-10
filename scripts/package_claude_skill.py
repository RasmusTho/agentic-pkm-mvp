#!/usr/bin/env python3
"""Build the portable Claude custom-skill ZIP deterministically."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

SKILL_NAME = "start-model-inquiry"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def package_skill(repo_root: Path, output: Path) -> Path:
    source = repo_root / "claude-skills" / SKILL_NAME
    skill_md = source / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"Claude skill source is missing: {skill_md}")
    output.parent.mkdir(parents=True, exist_ok=True)
    info = zipfile.ZipInfo(f"{SKILL_NAME}/SKILL.md", date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(info, skill_md.read_bytes())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/start-model-inquiry.zip"))
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    print(package_skill(repo_root, args.output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
