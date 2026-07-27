#!/usr/bin/env python3
"""Prepare a deterministic issue-set merge plan from authenticated snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.dispatcher.verified_merge import prepare_verified_merge


def _mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-json", type=Path, required=True)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--live-closing-json", type=Path, required=True)
    parser.add_argument(
        "--merge-readiness-json",
        type=Path,
        required=True,
        help=(
            "head-bound verified_issue_set_merge_readiness.v1 statement that CI "
            "and review are green and no further commits are anticipated"
        ),
    )
    parser.add_argument("--output-json", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    plan = prepare_verified_merge(
        context=_mapping(args.context_json),
        pr=_mapping(args.pr_json),
        live_closing_issues=_json(args.live_closing_json),
        merge_readiness=_mapping(args.merge_readiness_json),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
