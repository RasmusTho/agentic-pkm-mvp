"""Create an annotated git tag based on the current app version."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "app" / "settings.py"
VERSION_REGEX = re.compile(r'app_version: str = "(?P<version>[^"]+)"')


def read_current_version() -> str:
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    match = VERSION_REGEX.search(text)
    if not match:
        raise RuntimeError("Unable to locate app_version in settings.py")
    return match.group("version")


def git_status_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git status failed: {result.stderr.strip()}")
    return result.stdout.strip() == ""


def tag_exists(tag_name: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", tag_name],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create git tag from current app version")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow tagging even when the worktree is dirty",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push the created tag to origin after creation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show actions without executing git commands",
    )
    parser.add_argument(
        "--tag-prefix",
        default="v",
        help='Prefix used for tag name (default: "v")',
    )
    return parser.parse_args()


def build_tag_name(prefix: str, version: str) -> str:
    return f"{prefix}{version}"


def run_git(args: list[str], dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] git {' '.join(args)}")
        return
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    args = parse_args()
    version = read_current_version()
    tag_name = build_tag_name(args.tag_prefix, version)

    if not args.force and not git_status_clean():
        raise SystemExit("Working tree is dirty; commit changes or pass --force.")

    if tag_exists(tag_name):
        raise SystemExit(f"Tag {tag_name} already exists.")

    run_git(["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"], dry_run=args.dry_run)

    if args.push:
        run_git(["git", "push", "origin", tag_name], dry_run=args.dry_run)

    if args.dry_run:
        print(f"Tag {tag_name} would be created.")
    else:
        print(f"Tag {tag_name} created.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as err:
        print(f"Command failed: {' '.join(err.cmd)}", file=sys.stderr)
        raise SystemExit(err.returncode) from err
