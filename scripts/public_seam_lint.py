#!/usr/bin/env python3
"""Enforce the INV-EF1 public/private seam on repository content.

GATE examines changed tracked files.  DOCTOR examines the full tracked tree and
reports register drift without turning a maintenance report into a CI failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_PATTERNS = "scripts/public_seam_patterns.json"
DEFAULT_REGISTER = "docs/architecture/inv-ef1-register.json"

# Category (i) is deliberately not configurable or suppressible by the register.
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)


@dataclass(frozen=True)
class Hit:
    path: str
    category: str
    pattern: str
    line: int
    value: str


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _patterns(path: Path) -> list[tuple[str, str, re.Pattern[str]]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("patterns"), list):
        raise ValueError("pattern file must contain a patterns list")
    result = []
    for item in payload["patterns"]:
        if not isinstance(item, dict):
            raise ValueError("pattern rows must be objects")
        category, name, expression = item.get("category"), item.get("name"), item.get("regex")
        if category not in {"ii", "iii", "iv", "v"} or not all(isinstance(value, str) for value in (name, expression)):
            raise ValueError("pattern rows require name, regex, and category ii-v")
        result.append((category, name, re.compile(expression, re.IGNORECASE)))
    return result


def _register(path: Path) -> list[dict[str, str]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError("register file must contain a rows list")
    rows: list[dict[str, str]] = []
    required = {"artifact", "category", "why_load_bearing", "disposition", "issue"}
    for row in payload["rows"]:
        if not isinstance(row, dict) or required - row.keys():
            raise ValueError("register rows require artifact, category, why_load_bearing, disposition, issue")
        if row["category"] not in {"ii", "iii", "iv", "v"}:
            raise ValueError("register categories must be ii-v")
        if row["disposition"] not in {"stay", "migrate-to-private-sibling", "parameterize"}:
            raise ValueError("register disposition is invalid")
        rows.append({key: str(value) for key, value in row.items()})
    return rows


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True)
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _changed_files(root: Path, base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return [line for line in result.stdout.splitlines() if line]


def _scan(root: Path, paths: Iterable[str], patterns: list[tuple[str, str, re.Pattern[str]]], excluded: set[str]) -> tuple[list[Hit], list[Hit]]:
    personal, secrets = [], []
    for relative in paths:
        if relative in excluded:
            continue
        file_path = root / relative
        if not file_path.is_file():
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, 1):
            for expression in SECRET_PATTERNS:
                for match in expression.finditer(line):
                    secrets.append(Hit(relative, "i", "secret-shape", number, match.group(0)))
            for category, name, expression in patterns:
                for match in expression.finditer(line):
                    personal.append(Hit(relative, category, name, number, match.group(0)))
    return personal, secrets


def _covered(hit: Hit, rows: list[dict[str, str]]) -> bool:
    return any(row["artifact"] == hit.path and row["category"] == hit.category for row in rows)


def _report(mode: str, personal: list[Hit], secrets: list[Hit], rows: list[dict[str, str]]) -> dict[str, object]:
    uncovered = [hit for hit in personal if not _covered(hit, rows)]
    hit_pairs = {(hit.path, hit.category) for hit in personal}
    stale = [row for row in rows if (row["artifact"], row["category"]) not in hit_pairs]
    migration_pending = [row for row in rows if row["disposition"] != "stay" and (row["artifact"], row["category"]) in hit_pairs]
    return {
        "mode": mode,
        "secret_hits": [hit.__dict__ for hit in secrets],
        "uncovered_hits": [hit.__dict__ for hit in uncovered],
        "stale_rows": stale,
        "migration_pending": migration_pending,
        "ok": not secrets and not uncovered,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("gate", "doctor"), required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--patterns", type=Path, default=Path(DEFAULT_PATTERNS))
    parser.add_argument("--register", type=Path, default=Path(DEFAULT_REGISTER))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    patterns_path = (root / args.patterns).resolve() if not args.patterns.is_absolute() else args.patterns
    register_path = (root / args.register).resolve() if not args.register.is_absolute() else args.register
    try:
        patterns, rows = _patterns(patterns_path), _register(register_path)
        paths = _changed_files(root, args.base_ref) if args.mode == "gate" else _tracked_files(root)
        excluded = {str(patterns_path.relative_to(root)), str(register_path.relative_to(root)), "scripts/public_seam_lint.py"}
        personal, secrets = _scan(root, paths, patterns, excluded)
        report = _report(args.mode, personal, secrets, rows)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"public-seam-lint: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key in ("secret_hits", "uncovered_hits", "stale_rows", "migration_pending"):
            print(f"{key}: {len(report[key])}")
            for item in report[key]:
                print(f"  {item}")
    return 0 if args.mode == "doctor" or report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
