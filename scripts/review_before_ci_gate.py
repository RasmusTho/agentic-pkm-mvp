#!/usr/bin/env python3
"""Plan the cheap review gate before expensive local validation or CI handoff."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Sequence


DOCS_PREFIXES = ("docs/", "companion-ui/docs/", "companion-ui/design_handoff/")
GOVERNANCE_PREFIXES = (
    ".codex/",
    ".github/",
    "scripts/",
    "tests/governance/",
    "tests/ops/",
    "tests/scripts/",
    "tests/fixtures/",
)
DOCS_GOVERNANCE_LANES = {"docs-authoring", "governance", "direct-repair"}
CANONICAL_LANES = DOCS_GOVERNANCE_LANES | {"implementation"}
RISK_REVIEW_LANES = {"implementation", "governance", "direct-repair"}
RISK_SURFACES = {
    "auth",
    "concurrency",
    "credential-durability",
    "data",
    "external-api",
    "migration",
    "security",
    "state-machine",
}


class ReviewBeforeCiGateError(ValueError):
    """Raised when review-before-CI gate input is malformed."""


@dataclass(frozen=True)
class ReviewBeforeCiGate:
    lane: str
    status: str
    requires_review_gate: bool
    review_gate_complete: bool
    may_handoff_to_ci: bool
    preserves_ci_authority: bool
    bypass_reason: str | None
    changed_files: list[str]
    matched_surfaces: list[str]
    required_local_checks: list[str]
    summary: str


def evaluate_review_before_ci_gate(
    *,
    lane: str,
    changed_files: Sequence[str],
    review_gate_complete: bool = False,
    bypass_reason: str | None = None,
    risk_surfaces: Sequence[str] = (),
    risk_assessment_complete: bool = False,
) -> ReviewBeforeCiGate:
    """Return local review-before-CI gate guidance for a PR prep stage."""

    normalized_lane = lane.strip().lower()
    if not normalized_lane:
        raise ReviewBeforeCiGateError("lane is required")
    if normalized_lane not in CANONICAL_LANES:
        raise ReviewBeforeCiGateError(
            f"unknown lane: {normalized_lane}; allowed: {', '.join(sorted(CANONICAL_LANES))}"
        )
    files = [_normalize_path(path) for path in changed_files]
    if not files:
        raise ReviewBeforeCiGateError("at least one changed file is required")

    risks = _normalize_risk_surfaces(risk_surfaces)
    if risks and normalized_lane not in RISK_REVIEW_LANES:
        raise ReviewBeforeCiGateError(
            "risk_surfaces are valid only for implementation, governance, or direct-repair lanes"
        )
    if normalized_lane in RISK_REVIEW_LANES and not risk_assessment_complete:
        raise ReviewBeforeCiGateError(
            "implementation, governance, and direct-repair lanes require an explicit completed risk assessment, "
            "including when no high-risk surface applies"
        )
    matched = _matched_surfaces(normalized_lane, files, risks)
    required = bool(matched)
    bypass = _clean_text(bypass_reason)
    if bypass and not required:
        raise ReviewBeforeCiGateError("bypass_reason is only valid when the review gate is required")
    if bypass and (normalized_lane != "direct-repair" or risks):
        raise ReviewBeforeCiGateError(
            "bypass_reason is valid only for an emergency direct-repair with no "
            "declared high-risk surface"
        )
    if bypass:
        return _gate(
            normalized_lane,
            "bypassed",
            required,
            review_gate_complete=False,
            may_handoff_to_ci=True,
            bypass_reason=bypass,
            files=files,
            matched=matched,
            summary="local review-before-CI gate bypassed with explicit reason; required GitHub checks still apply",
        )
    if required and not review_gate_complete:
        return _gate(
            normalized_lane,
            "required",
            required,
            review_gate_complete=False,
            may_handoff_to_ci=False,
            bypass_reason=None,
            files=files,
            matched=matched,
            summary="run cheap local review/contract checks before expensive validation or CI",
        )
    if required:
        return _gate(
            normalized_lane,
            "satisfied",
            required,
            review_gate_complete=True,
            may_handoff_to_ci=True,
            bypass_reason=None,
            files=files,
            matched=matched,
            summary="local review-before-CI gate satisfied; continue to GitHub CI handoff",
        )
    return _gate(
        normalized_lane,
        "not_required",
        required,
        review_gate_complete=False,
        may_handoff_to_ci=True,
        bypass_reason=None,
        files=files,
        matched=matched,
        summary="docs/governance review-before-CI gate is not required for this lane/surface",
    )


def _gate(
    lane: str,
    status: str,
    requires_review_gate: bool,
    *,
    review_gate_complete: bool,
    may_handoff_to_ci: bool,
    bypass_reason: str | None,
    files: list[str],
    matched: list[str],
    summary: str,
) -> ReviewBeforeCiGate:
    return ReviewBeforeCiGate(
        lane=lane,
        status=status,
        requires_review_gate=requires_review_gate,
        review_gate_complete=review_gate_complete,
        may_handoff_to_ci=may_handoff_to_ci,
        preserves_ci_authority=True,
        bypass_reason=bypass_reason,
        changed_files=files,
        matched_surfaces=matched,
        required_local_checks=_required_checks(matched),
        summary=summary,
    )


def _matched_surfaces(
    lane: str, files: Sequence[str], risk_surfaces: Sequence[str]
) -> list[str]:
    matched: set[str] = set()
    if lane in DOCS_GOVERNANCE_LANES:
        matched.add(f"lane:{lane}")
    for path in files:
        if path.startswith(DOCS_PREFIXES):
            matched.add("surface:docs")
        if path.startswith(GOVERNANCE_PREFIXES):
            matched.add("surface:governance")
    matched.update(f"risk:{surface}" for surface in risk_surfaces)
    return sorted(matched)


def _required_checks(matched: Sequence[str]) -> list[str]:
    if not matched:
        return []
    checks: list[str] = []
    if any(item.startswith("lane:") or item.startswith("surface:") for item in matched):
        checks.extend(
            [
                "generate or preflight the PR body with scripts/pr_body_generator.py",
                "run python3 scripts/docs_guard.py for docs/governance writeback drift",
            ]
        )
    if any(item.startswith("surface:governance") or item == "lane:governance" for item in matched):
        checks.append("run targeted governance/contract tests for touched surfaces")
    if any(item.startswith("risk:") for item in matched):
        checks.extend(
            [
                "build the mechanism convergence packet (invariants, states, transitions, crash ordering, producers/consumers/recovery, locks, and test map)",
                "run a fresh independent high-capability review of the local publishable SHA and convergence packet before selected expensive validation",
            ]
        )
    return checks


def _normalize_risk_surfaces(values: Sequence[str]) -> list[str]:
    risks = sorted({value.strip().lower() for value in values if value.strip()})
    unknown = sorted(set(risks) - RISK_SURFACES)
    if unknown:
        raise ReviewBeforeCiGateError(
            f"unknown risk surface(s): {', '.join(unknown)}; allowed: {', '.join(sorted(RISK_SURFACES))}"
        )
    return risks


def _normalize_path(path: str) -> str:
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized:
        raise ReviewBeforeCiGateError("changed files must be non-empty paths")
    return normalized


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--review-gate-complete", action="store_true")
    parser.add_argument("--bypass-reason")
    parser.add_argument("--risk-surface", action="append", default=[])
    parser.add_argument("--risk-assessment-complete", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = evaluate_review_before_ci_gate(
            lane=args.lane,
            changed_files=args.changed_file,
            review_gate_complete=args.review_gate_complete,
            bypass_reason=args.bypass_reason,
            risk_surfaces=args.risk_surface,
            risk_assessment_complete=args.risk_assessment_complete,
        )
    except ReviewBeforeCiGateError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **asdict(result)}, sort_keys=True))
    return 0 if result.may_handoff_to_ci else 1


if __name__ == "__main__":
    raise SystemExit(main())
