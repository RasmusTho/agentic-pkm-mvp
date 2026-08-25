#!/usr/bin/env python3
"""Build one authority-bound, idempotent verified-merge phase receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from app.dispatcher.verified_merge import (
    build_verified_merge_phase,
    resolve_verified_merge_projection_convergence_receipt,
)


def _mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _nested_mapping(path: Path, key: str) -> dict[str, object]:
    value = _mapping(path)
    nested = value.get(key)
    if nested is None:
        return value
    if not isinstance(nested, dict):
        raise ValueError(f"{path} field {key} must contain a JSON object")
    return nested


def _issue_numbers(path: Path | None) -> list[int]:
    if path is None:
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def _comments(path: Path) -> list[dict[str, object]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{path} must contain a JSON array of comment objects")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-json", type=Path, required=True)
    parser.add_argument("--authority-comment-json", type=Path)
    parser.add_argument(
        "--comments-json",
        type=Path,
        required=True,
        help="complete bounded PR comments used to authenticate the durable receipt",
    )
    parser.add_argument(
        "--projection-convergence-json",
        type=Path,
        help=(
            "authenticated verified-merge-closing-projection-convergence.v1 "
            "receipt; required for every new phase"
        ),
    )
    parser.add_argument(
        "--final-projection-observation-json",
        type=Path,
        help="fresh same-snapshot empty closing projection; required for prepared",
    )
    parser.add_argument(
        "--phase",
        choices=("prepared", "merged", "reconciled", "restored"),
        required=True,
    )
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--closed-issues-json", type=Path)
    parser.add_argument("--reopened-issues-json", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.projection_convergence_json is None:
        raise ValueError("phase requires projection convergence")
    if (
        args.phase == "prepared"
        and args.final_projection_observation_json is None
    ):
        raise ValueError(
            "prepared phase requires projection convergence and final observation"
        )
    authority_receipt = _mapping(args.authority_json)
    comments = _comments(args.comments_json)
    supplied_convergence = _nested_mapping(
        args.projection_convergence_json, "convergence_receipt"
    )
    supplied_pr_contract = supplied_convergence.get("pr_contract")
    if not isinstance(supplied_pr_contract, Mapping):
        raise ValueError("phase requires a convergence receipt pr-contract")
    durable_convergence = resolve_verified_merge_projection_convergence_receipt(
        comments,
        authority_receipt=authority_receipt,
        pr_contract=supplied_pr_contract,
    )
    if durable_convergence is None or durable_convergence != supplied_convergence:
        raise ValueError("phase requires one authenticated durable projection convergence")
    result = build_verified_merge_phase(
        authority_receipt=authority_receipt,
        authority_comment=(
            _mapping(args.authority_comment_json)
            if args.authority_comment_json is not None
            else None
        ),
        phase=args.phase,
        pr=_mapping(args.pr_json),
        projection_convergence_receipt=durable_convergence,
        final_projection_observation=(
            _nested_mapping(
                args.final_projection_observation_json,
                "final_projection_observation",
            )
            if args.final_projection_observation_json is not None
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
