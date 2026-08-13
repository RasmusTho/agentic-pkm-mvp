#!/usr/bin/env python3
"""Build one authority-bound, idempotent verified-merge phase receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.dispatcher.verified_merge import build_verified_merge_phase


def _mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _issue_numbers(path: Path | None) -> list[int]:
    if path is None:
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-json", type=Path, required=True)
    parser.add_argument("--authority-comment-json", type=Path)
    parser.add_argument(
        "--phase",
        choices=("prepared", "merged", "reconciled", "restored"),
        required=True,
    )
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--post-effect-json", type=Path)
    parser.add_argument("--closed-issues-json", type=Path)
    parser.add_argument("--reopened-issues-json", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = build_verified_merge_phase(
        authority_receipt=_mapping(args.authority_json),
        authority_comment=(
            _mapping(args.authority_comment_json)
            if args.authority_comment_json is not None
            else None
        ),
        phase=args.phase,
        pr=_mapping(args.pr_json),
        post_effect_reconciliation=(
            _mapping(args.post_effect_json)
            if args.post_effect_json is not None
            else None
        ),
        closed_issues=_issue_numbers(args.closed_issues_json),
        reopened_unauthorized_issues=_issue_numbers(args.reopened_issues_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
