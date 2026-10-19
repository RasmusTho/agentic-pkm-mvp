"""Render the rolling alert Issue for a red dev verification run (#6154, #6158).

The heavy test targets that `scripts/select_pr_tests.py` defers from the PR
path run on the ygg `dev` VM; `.github/workflows/post-merge-heavy-tests.yml`
records the host's verdict, or runs a GitHub-hosted fallback when no verdict
arrives. When a run is red on `main`, the workflow opens one rolling
`type:bug` + `prio:high` Issue with this body (or comments on the open one),
and a later green verdict closes it. The body follows the canonical Issue
contract so the alert is directly pickup-ready.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ALERT_TITLE = "bug: dev verification is red on main"
LEGACY_ALERT_TITLE = "bug: post-merge heavy tests are red on main"
ALERT_LABELS = ("type:bug", "prio:high", "agent:ready")
ALERT_MARKER = "<!-- post-merge-heavy-tests-alert:v1 -->"


def render_alert_body(*, sha: str, run_url: str, targets: str, reason: str = "") -> str:
    reason_line = f"\nReason: {reason}\n" if reason else ""
    return f"""{ALERT_MARKER}
## Context

Dev verification is red on `main` at `{sha}`: {run_url}
{reason_line}
These heavy targets are deferred from the required PR check `Unit tests (not pg)` unless a PR changes a source they exercise (owner decision 2026-10-16, #6154). They run on the ygg `dev` VM after the candidate's native dev deployment, before test promotion (#6227), and the workflow records that verdict as the `post-merge-heavy-tests/ygg` commit status. A red verdict holds this candidate from test promotion while later builds continue. A terminal dev deployment failure is a refused verdict (`dev_deploy_failed`). A red result means a regression may already be on `main`; a missing or refused verdict means the VM path itself is broken. Later red runs comment on this Issue. The next green verdict closes it.

Heavy targets: `{targets}`

## Scope

Find the failing tests (named in the reason above, or in the GitHub-hosted fallback log), identify the merged change that broke them, and repair the code or the test on `main`. For `dev_deploy_failed`, repair the failing native dev gate. For another missing or refused verdict, restore the host controller or VM path instead.

## Source Anchors

- `.github/workflows/post-merge-heavy-tests.yml`
- `scripts/post_merge_heavy_tests_verdict.py`
- `scripts/select_pr_tests.py :: HEAVY_PR_DEFERRED_TARGETS`
- `docs/development/TEST_STRATEGY_HOT_PATH.md`

## SBS Impact

Depends on the failing suite. Classify it from the failing tests' owning subsystem before repair.

## Constraints

- Do not remove, skip, or weaken a failing heavy test to turn the run green. Repair the regression.
- Do not move the target back onto the PR path as a workaround.

## Acceptance Criteria

- [ ] AC1: The dev verification verdict is green on `main` at a commit containing the repair. Verify: `docs/development/TEST_STRATEGY_HOT_PATH.md :: Post-merge heavy tests`

## Out of Scope

- Changing which targets are heavy. That needs its own Issue with a timing receipt.

## Suggested Validation

- Rerun the failing heavy target locally, or dispatch the workflow without a verdict for a GitHub-hosted run.

## Source Docs

- `docs/development/TEST_STRATEGY_HOT_PATH.md`
- `docs/TESTING.md`

## Applies learning (optional)

"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--output", required=True, help="Path to write the Issue body to.")
    args = parser.parse_args()
    Path(args.output).write_text(
        render_alert_body(sha=args.sha, run_url=args.run_url, targets=args.targets, reason=args.reason),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
