"""Utility to bump ``settings.app_version`` and related documentation."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "app" / "settings" / "__init__.py"
DOC_PATHS = (
    ROOT / "README.md",
    ROOT / "docs" / "OPERATIONS.md",
    ROOT / "docs" / "PROJECT_OVERVIEW.md",
)
ALIGNMENT_PATH = ROOT / "docs" / "ALIGNMENT.md"
PROJECTS_PATH = ROOT / "data" / "context" / "projects.json"

VERSION_REGEX = re.compile(r"app_version: str = \"(?P<version>[^\"]+)\"")


def read_current_version() -> str:
    text = SETTINGS_PATH.read_text(encoding="utf-8")
    match = VERSION_REGEX.search(text)
    if not match:
        raise ValueError("app_version not found in app.settings")
    return match.group("version")


def build_updates(new_version: str) -> tuple[str, dict[Path, str]]:
    current = read_current_version()
    if new_version == current:
        raise SystemExit("New version is the same as current version")

    updates: dict[Path, str] = {}

    settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
    updates[SETTINGS_PATH] = VERSION_REGEX.sub(
        lambda match: match.group(0).replace(current, new_version),
        settings_text,
    )

    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        updates[path] = text.replace(current, new_version)

    updates[ALIGNMENT_PATH] = _alignment_text(new_version)
    updates[PROJECTS_PATH] = _project_context_text(new_version)

    return current, updates


def _alignment_text(new_version: str) -> str:
    text = ALIGNMENT_PATH.read_text(encoding="utf-8")
    note = f"- {new_version}: Version bump via scripts/bump_version.py\n"
    if note not in text:
        text = text.replace("## Decision Log\n", f"## Decision Log\n{note}")
    return text


def _project_context_text(new_version: str) -> str:
    data: dict[str, Any] = json.loads(PROJECTS_PATH.read_text(encoding="utf-8"))
    for project in data.get("projects", []):
        actions = project.get("next_actions", [])
        for idx, action in enumerate(actions):
            if "Automatisera versionsflöde" in action:
                actions[idx] = f"Automatisera versionsflöde automatiserad i {new_version}"
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def apply_updates(updates: dict[Path, str]) -> None:
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump app version")
    parser.add_argument("new_version", help="Semantic version string, e.g. 0.2.0")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show files that would change without writing them",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current, updates = build_updates(args.new_version)
    if args.dry_run:
        print(f"Dry run: would bump version from {current} to {args.new_version}.")
        for path in updates:
            print(f" - {path.relative_to(ROOT)}")
        return

    apply_updates(updates)
    print(f"Version bumped from {current} to {args.new_version}")


if __name__ == "__main__":
    main()
