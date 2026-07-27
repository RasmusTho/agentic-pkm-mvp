#!/usr/bin/env python3
"""Detect a neutralized PR body that outlived its own verified-merge attempt.

Read-only detection. It performs no GitHub writes, grants no merge authority,
and never relaxes the exact-head authority binding. Exit ``0`` when no
restoration is needed, ``2`` when the live PR body is neutralized while no
authority receipt covers the current head, so the caller can restore the
canonical body before continuing repair work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.dispatcher.verified_merge import resolve_neutralized_body_restoration


def _mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _comments(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(
        not isinstance(item, dict) for item in value
    ):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--comments-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--expected-run-id")
    parser.add_argument("--output-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    restoration = resolve_neutralized_body_restoration(
        _comments(args.comments_json),
        pr=_mapping(args.pr_json),
        repository=args.repository,
        expected_run_id=args.expected_run_id,
    )
    payload: dict[str, object] = {
        "restoration_required": restoration is not None,
        "restoration": restoration,
    }
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 2 if restoration is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
