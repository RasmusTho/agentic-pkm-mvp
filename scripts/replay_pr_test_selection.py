from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__:
    from .select_pr_tests import Selection, select_tests
else:
    from select_pr_tests import Selection, select_tests


SCHEMA_VERSION = "affected-test-selector-replay.v1"
INTERPRETATION = (
    "This report replays the current selector over historical changed-file sets. "
    "It does not reconstruct the selector version used at each commit and does not measure "
    "historical failing-test recall, CI duration, runner cost, review effort, or escaped defects."
)
DEFAULT_SELECTOR_PATH = Path(__file__).with_name("select_pr_tests.py")
DEFAULT_SELECTOR_ID = "scripts/select_pr_tests.py"
GitRunner = Callable[..., str]


class ReplayError(RuntimeError):
    """Raised when a replay cannot produce truthful evidence."""


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _selection_evidence(selection: Selection) -> dict[str, Any]:
    return {
        "full_suite": selection.full_suite,
        "subsystems": list(selection.subsystems),
        "targets": list(selection.targets),
        "reason": selection.reason,
        "unowned_paths": list(selection.unowned_paths),
    }


def _rate(count: int, total: int) -> float:
    return count / total


def _selector_id(selector_path: Path) -> str:
    if selector_path.resolve() == DEFAULT_SELECTOR_PATH.resolve():
        return DEFAULT_SELECTOR_ID
    return str(selector_path)


def build_report(
    *,
    ref: str,
    limit: int,
    selector_path: Path = DEFAULT_SELECTOR_PATH,
    run_git: GitRunner | None = None,
) -> dict[str, Any]:
    git = run_git or _run_git
    if limit < 1:
        raise ReplayError("limit must be a positive integer")
    if not selector_path.is_file():
        raise ReplayError(f"selector source does not exist: {selector_path}")

    resolved_ref = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    commits = [
        line
        for line in git(
            "rev-list",
            "--first-parent",
            f"--max-count={limit}",
            resolved_ref,
        ).splitlines()
        if line
    ]
    if not commits:
        raise ReplayError(f"no first-parent commits found for ref {ref!r}")

    deliveries: list[dict[str, Any]] = []
    for commit in commits:
        parent = git("rev-parse", "--verify", f"{commit}^").strip()
        changed_files = [
            line
            for line in git("diff", "--name-only", parent, commit).splitlines()
            if line
        ]
        selection = select_tests(changed_files)
        deliveries.append(
            {
                "commit": commit,
                "parent": parent,
                "changed_files": changed_files,
                "selection": _selection_evidence(selection),
            }
        )

    total = len(deliveries)
    full_suite_count = sum(
        delivery["selection"]["full_suite"] is True for delivery in deliveries
    )
    unowned_count = sum(
        bool(delivery["selection"]["unowned_paths"]) for delivery in deliveries
    )
    multi_subsystem_count = sum(
        len(delivery["selection"]["subsystems"]) > 1 for delivery in deliveries
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "interpretation": INTERPRETATION,
        "selector": {
            "path": _selector_id(selector_path),
            "sha256": hashlib.sha256(selector_path.read_bytes()).hexdigest(),
        },
        "ref": {"requested": ref, "resolved_sha": resolved_ref},
        "sample": {
            "requested_limit": limit,
            "returned": total,
            "newest_commit": commits[0],
            "oldest_commit": commits[-1],
        },
        "metrics": {
            "deliveries": total,
            "full_suite": {
                "count": full_suite_count,
                "rate": _rate(full_suite_count, total),
            },
            "unowned": {
                "count": unowned_count,
                "rate": _rate(unowned_count, total),
            },
            "multi_subsystem": {
                "count": multi_subsystem_count,
                "rate": _rate(multi_subsystem_count, total),
            },
        },
        "deliveries": deliveries,
    }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay the current affected-test selector over first-parent Git history."
    )
    parser.add_argument("--ref", default="HEAD", help="Git ref whose first-parent history is replayed.")
    parser.add_argument(
        "--limit",
        default=100,
        type=_positive_int,
        help="Maximum number of first-parent commits to replay (default: 100).",
    )
    parser.add_argument("--json", action="store_true", help="Emit the complete JSON evidence report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(ref=args.ref, limit=args.limit)
    except ReplayError as exc:
        print(f"selector replay failed: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(f"selector replay failed: {detail}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        metrics = report["metrics"]
        print(f"ref={report['ref']['resolved_sha']}")
        print(f"deliveries={metrics['deliveries']}")
        for name in ("full_suite", "unowned", "multi_subsystem"):
            print(f"{name}={metrics[name]['count']} ({metrics[name]['rate']:.1%})")
        print(f"interpretation={report['interpretation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
