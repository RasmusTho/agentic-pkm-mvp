#!/usr/bin/env python3
"""Plan safe post-merge compensation for one issue-free reviewed-lane PR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.dispatcher.verified_merge import plan_issue_free_post_merge_reconciliation


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--observed-closing-json", type=Path, required=True)
    parser.add_argument("--issue-evidence-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    observed = _json(args.observed_closing_json)
    evidence = _json(args.issue_evidence_json)
    if not isinstance(observed, list) or not isinstance(evidence, list):
        raise ValueError("reconciliation inputs must contain JSON arrays")
    plan = plan_issue_free_post_merge_reconciliation(
        pr_number=args.pr_number,
        observed_closing_issues=observed,
        issue_evidence=[item for item in evidence if isinstance(item, dict)],
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
