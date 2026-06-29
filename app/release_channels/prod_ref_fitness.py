"""Prod runtime-ref fitness guard (Issue #2527, AC3).

Read-only check that a prod checkout's HEAD matches the agreed promotion ref
and that its working tree is clean. This backs the reproducibility invariant
that prod must be reconstructible from git alone — no machine-local,
uncommitted state acting as durable truth (the #2527 finding: prod ran a dirty
``main`` checkout with 11 modified tracked files that existed nowhere in git).

Promotion-model authority: ``docs/RELEASE_CHANNELS/README.md`` §"Promotion
model" and ``docs/adr/ADR-0040-prod-promotion-ref-main-interim.md``. Prod
currently tracks ``main`` as an interim baseline; the gated ``stable`` promotion
ref is deferred future hardening. This guard flags when the prod checkout
diverges from the configured promotion ref or runs a dirty tree.

Design constraints (mirror ``channel_isolation_preflight``):
- Read-only: this module NEVER mutates the inspected checkout.
- No network: only local ``git`` plumbing inside the given checkout. Staleness
  relative to ``origin`` (behind the remote tip) is a promotion-process concern,
  not this read-only guard's job, *unless* an already-fetched comparison ref is
  passed explicitly via ``compare_to_ref`` (no fetch is performed here).
- Usable both as a unit-testable function and as an operator CLI on the prod
  host (the AC2 "prod tree clean" receipt is produced by running this).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

#: The agreed prod promotion ref. Prod tracks ``main`` as the interim baseline
#: until a gated ``stable`` ref is restored as future promotion hardening
#: (ADR-0040). Keep this in sync with docs/RELEASE_CHANNELS/README.md.
DEFAULT_PROMOTION_REF = "main"

#: Sentinel branch name git reports for a detached HEAD.
_DETACHED = "HEAD"

GitRunner = Callable[[list[str], Path], str]


def _default_git_runner(args: list[str], checkout: Path) -> str:
    """Run a read-only ``git`` command in ``checkout`` and return stdout.

    Raises ``GitInspectionError`` if git is unavailable or the command fails
    (e.g. the path is not a git work tree).
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - git always present in CI
        raise GitInspectionError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise GitInspectionError(
            f"git {' '.join(args)} failed in {checkout}: {exc.stderr.strip()}"
        ) from exc
    return completed.stdout


class GitInspectionError(RuntimeError):
    """Raised when the checkout cannot be inspected as a git work tree."""


@dataclass(frozen=True)
class ProdRefFitnessResult:
    """Outcome of inspecting a prod checkout against the promotion ref."""

    checkout: str
    promotion_ref: str
    head_sha: str
    current_branch: str
    is_clean: bool
    on_promotion_ref: bool
    compare_to_ref: str | None = None
    compare_to_sha: str | None = None
    matches_compare_ref: bool | None = None
    dirty_paths: tuple[str, ...] = ()
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the checkout is clean and on the promotion ref (and, when a
        ``compare_to_ref`` was given, at that ref's commit)."""
        return not self.violations

    def to_receipt(self) -> dict:
        """Machine-readable receipt for the operator AC2 record / promotion log."""
        return {
            "checkout": self.checkout,
            "promotion_ref": self.promotion_ref,
            "head_sha": self.head_sha,
            "current_branch": self.current_branch,
            "is_clean": self.is_clean,
            "on_promotion_ref": self.on_promotion_ref,
            "compare_to_ref": self.compare_to_ref,
            "compare_to_sha": self.compare_to_sha,
            "matches_compare_ref": self.matches_compare_ref,
            "dirty_paths": list(self.dirty_paths),
            "ok": self.ok,
            "violations": list(self.violations),
        }


def check_prod_head_matches_promotion_ref_and_clean(
    checkout: Path | str,
    promotion_ref: str = DEFAULT_PROMOTION_REF,
    *,
    compare_to_ref: str | None = None,
    git_runner: GitRunner = _default_git_runner,
) -> ProdRefFitnessResult:
    """Inspect ``checkout`` and flag prod-HEAD divergence or a dirty tree.

    The guard fail-closes (records a violation) when any of these hold:

    - the working tree is **dirty** (``git status --porcelain`` is non-empty) —
      uncommitted state is not reconstructible from git;
    - the checkout is **not on the promotion ref** (detached HEAD or a different
      branch than ``promotion_ref``);
    - a ``compare_to_ref`` was supplied and HEAD does **not** equal that ref's
      resolved commit (an explicit, no-fetch divergence check against an
      already-known ref such as ``origin/main``).

    It is read-only: no fetch, no checkout, no reset, no mutation of any kind.

    Returns a :class:`ProdRefFitnessResult`; inspect ``.ok`` / ``.violations``.
    Raises :class:`GitInspectionError` if ``checkout`` is not a git work tree.
    """
    checkout_path = Path(checkout)

    head_sha = git_runner(["rev-parse", "HEAD"], checkout_path).strip()
    current_branch = git_runner(
        ["rev-parse", "--abbrev-ref", "HEAD"], checkout_path
    ).strip()
    porcelain = git_runner(["status", "--porcelain"], checkout_path)
    dirty_paths = tuple(
        line[3:] if len(line) > 3 else line
        for line in porcelain.splitlines()
        if line.strip()
    )
    is_clean = not dirty_paths

    on_promotion_ref = current_branch == promotion_ref

    violations: list[str] = []
    if not is_clean:
        violations.append(
            f"prod working tree is dirty: {len(dirty_paths)} uncommitted path(s) "
            f"({', '.join(dirty_paths[:5])}"
            f"{', …' if len(dirty_paths) > 5 else ''}). "
            "Prod must be reconstructible from git alone (Issue #2527)."
        )
    if current_branch == _DETACHED:
        violations.append(
            f"prod checkout is on a detached HEAD ({head_sha[:8]}), not the "
            f"agreed promotion ref '{promotion_ref}' (ADR-0040)."
        )
    elif not on_promotion_ref:
        violations.append(
            f"prod checkout is on branch '{current_branch}', but the agreed "
            f"promotion ref is '{promotion_ref}' (ADR-0040)."
        )

    compare_to_sha: str | None = None
    matches_compare_ref: bool | None = None
    if compare_to_ref is not None:
        compare_to_sha = git_runner(
            ["rev-parse", compare_to_ref], checkout_path
        ).strip()
        matches_compare_ref = head_sha == compare_to_sha
        if not matches_compare_ref:
            violations.append(
                f"prod HEAD ({head_sha[:8]}) diverges from the promotion ref "
                f"'{compare_to_ref}' ({compare_to_sha[:8]})."
            )

    return ProdRefFitnessResult(
        checkout=str(checkout_path),
        promotion_ref=promotion_ref,
        head_sha=head_sha,
        current_branch=current_branch,
        is_clean=is_clean,
        on_promotion_ref=on_promotion_ref,
        compare_to_ref=compare_to_ref,
        compare_to_sha=compare_to_sha,
        matches_compare_ref=matches_compare_ref,
        dirty_paths=dirty_paths,
        violations=violations,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.release_channels.prod_ref_fitness",
        description=(
            "Read-only prod runtime-ref fitness check (Issue #2527 AC3). "
            "Flags a prod checkout that diverges from the promotion ref or "
            "runs a dirty working tree. Exits non-zero on any violation; the "
            "clean run is the AC2 operator receipt."
        ),
    )
    parser.add_argument(
        "checkout",
        help="Path to the prod host checkout (e.g. /Users/rasmus/workspace).",
    )
    parser.add_argument(
        "--promotion-ref",
        default=DEFAULT_PROMOTION_REF,
        help=f"Agreed promotion ref the checkout must be on (default: {DEFAULT_PROMOTION_REF}).",
    )
    parser.add_argument(
        "--compare-to-ref",
        default=None,
        help=(
            "Optional already-known ref (e.g. origin/main) HEAD must equal. "
            "No fetch is performed; compare against what is already local."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        result = check_prod_head_matches_promotion_ref_and_clean(
            args.checkout,
            promotion_ref=args.promotion_ref,
            compare_to_ref=args.compare_to_ref,
        )
    except GitInspectionError as exc:
        print(f"prod-ref-fitness: ERROR — {exc}", file=sys.stderr)
        return 2

    if result.ok:
        print(
            f"prod-ref-fitness: OK — {result.checkout} is clean and on "
            f"'{result.promotion_ref}' (HEAD {result.head_sha[:8]})."
        )
        return 0

    print(
        f"prod-ref-fitness: FAIL — {result.checkout} violates the prod "
        f"promotion-ref / clean-tree invariant:",
        file=sys.stderr,
    )
    for violation in result.violations:
        print(f"  - {violation}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
