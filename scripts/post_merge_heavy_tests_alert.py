"""Render the rolling alert Issue for a red post-merge heavy-tests run (#6154).

`.github/workflows/post-merge-heavy-tests.yml` runs the heavy test targets that
`scripts/select_pr_tests.py` defers from the PR path. When that run is red on
`main`, the workflow opens one rolling `type:bug` + `prio:high` Issue with this
body (or comments on the open one), and a later green run closes it. The body
follows the canonical Issue contract so the alert is directly pickup-ready.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ALERT_TITLE = "bug: post-merge heavy tests are red on main"
ALERT_LABELS = ("type:bug", "prio:high", "agent:ready")
ALERT_MARKER = "<!-- post-merge-heavy-tests-alert:v1 -->"


def render_alert_body(*, sha: str, run_url: str, targets: str) -> str:
    return f"""{ALERT_MARKER}
## Context

The post-merge heavy-tests workflow failed on `main` at `{sha}`: {run_url}

These heavy targets are deferred from the required PR check `Unit tests (not pg)` unless a PR changes a source they exercise (owner decision 2026-10-16, #6154). This run is their authoritative signal, so a red result means a regression may already be on `main`. Later red runs comment on this Issue. The next green run closes it.

Heavy targets: `{targets}`

## Scope

Find the failing tests in the run log, identify the merged change that broke them, and repair the code or the test on `main`.

## Source Anchors

- `.github/workflows/post-merge-heavy-tests.yml`
- `scripts/select_pr_tests.py :: HEAVY_PR_DEFERRED_TARGETS`
- `docs/development/TEST_STRATEGY_HOT_PATH.md`

## SBS Impact

Depends on the failing suite. Classify it from the failing tests' owning subsystem before repair.

## Constraints

- Do not remove, skip, or weaken a failing heavy test to turn the run green. Repair the regression.
- Do not move the target back onto the PR path as a workaround.

## Acceptance Criteria

- [ ] AC1: The post-merge heavy-tests workflow is green on `main` at a commit containing the repair. Verify: `docs/development/TEST_STRATEGY_HOT_PATH.md :: Post-merge heavy tests`

## Out of Scope

- Changing which targets are heavy. That needs its own Issue with a timing receipt.

## Suggested Validation

- Rerun the failing heavy target locally or with the workflow's `workflow_dispatch`.

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
    parser.add_argument("--output", required=True, help="Path to write the Issue body to.")
    args = parser.parse_args()
    Path(args.output).write_text(
        render_alert_body(sha=args.sha, run_url=args.run_url, targets=args.targets),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
