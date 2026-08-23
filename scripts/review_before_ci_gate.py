#!/usr/bin/env python3
"""Plan the cheap review gate before expensive local validation or CI handoff."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

try:  # Supports both ``python scripts/...`` and package imports in tests.
    from scripts.workflow_review_risk import (
        WorkflowReviewRiskError,
        validate_workflow_review_receipt,
        workflow_risk_evidence_from_git,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script invocation only
    from workflow_review_risk import (  # type: ignore[no-redef]
        WorkflowReviewRiskError,
        validate_workflow_review_receipt,
        workflow_risk_evidence_from_git,
    )


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
PR_SCOPE_REVALIDATION_OUTCOMES = frozenset({"continue_unchanged", "split", "expanded_contract"})


class ReviewBeforeCiGateError(ValueError):
    """Raised when review-before-CI gate input is malformed."""


def validate_pr_scope_revalidation(
    pr_number: int,
    governing_issue: int,
    head_sha: str,
    rejected_rounds: Sequence[Mapping[str, object]],
    receipt: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    """Require an exact authenticated revalidation receipt after two rejections."""
    if sum(1 for round_ in rejected_rounds if round_.get("verdict") == "rejected") < 2:
        return None
    if not isinstance(receipt, Mapping):
        raise ReviewBeforeCiGateError(
            "two rejected independent review rounds require a contract revalidation receipt"
        )
    for field, value in {
        "version": 1,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "governing_issue": governing_issue,
    }.items():
        if receipt.get(field) != value:
            raise ReviewBeforeCiGateError(
                f"contract revalidation receipt {field} does not bind the current PR contract"
            )
    if not _is_sha256(receipt.get("governing_contract_sha256")):
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt requires a canonical governing contract SHA-256"
        )
    outcome = receipt.get("outcome")
    if outcome not in PR_SCOPE_REVALIDATION_OUTCOMES:
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt outcome must be continue_unchanged, split, or expanded_contract"
        )
    authentication = receipt.get("authentication")
    if (
        not isinstance(authentication, Mapping)
        or authentication.get("source") != "github-review"
        or not _nonempty_string(authentication.get("actor"))
        or not _nonempty_string(authentication.get("receipt_url"))
    ):
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt must carry authenticated GitHub review evidence"
        )
    if outcome == "expanded_contract" and (
        receipt.get("expanded_issue") != governing_issue
        or not _is_sha256(receipt.get("expanded_contract_sha256"))
    ):
        raise ReviewBeforeCiGateError(
            "expanded_contract requires the authenticated updated governing Issue and contract SHA-256"
        )
    classifications = receipt.get("finding_classifications", [])
    if not isinstance(classifications, list):
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt finding_classifications must be a list"
        )
    valid_classes = {
        "governing_contract_blocker",
        "pr_introduced_regression",
        "security_authority_scope_expansion",
        "adjacent_pre_existing",
    }
    for finding in classifications:
        if not isinstance(finding, Mapping) or not _nonempty_string(finding.get("finding_id")):
            raise ReviewBeforeCiGateError("each revalidation finding requires an identifier")
        scope_class = finding.get("scope_class")
        if scope_class not in valid_classes:
            raise ReviewBeforeCiGateError(
                "each revalidation finding requires one canonical scope class"
            )
        if outcome == "continue_unchanged" and scope_class not in {
            "governing_contract_blocker",
            "pr_introduced_regression",
        }:
            raise ReviewBeforeCiGateError(
                "continue_unchanged permits only governing-contract blockers and PR-introduced regressions"
            )
        if scope_class == "adjacent_pre_existing" and not isinstance(
            finding.get("follow_up_issue"), int
        ):
            raise ReviewBeforeCiGateError(
                "adjacent/pre-existing findings require a bounded follow-up Issue"
            )
        if scope_class == "security_authority_scope_expansion" and outcome != "expanded_contract":
            raise ReviewBeforeCiGateError(
                "security/authority findings require authenticated expanded_contract scope"
            )
    return receipt


@dataclass(frozen=True)
class ReviewBeforeCiGate:
    lane: str
    status: str
    requires_review_gate: bool
    review_gate_complete: bool
    may_handoff_to_ci: bool
    preserves_ci_authority: bool
    bypass_reason: str | None
    stateful_fallback: bool
    stateful_fallback_matrix_complete: bool
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
    stateful_fallback: bool = False,
    stateful_fallback_matrix_complete: bool = False,
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
    if stateful_fallback_matrix_complete and not stateful_fallback:
        raise ReviewBeforeCiGateError(
            "stateful_fallback_matrix_complete requires stateful_fallback"
        )
    if stateful_fallback and not risks:
        raise ReviewBeforeCiGateError(
            "stateful_fallback requires at least one declared high-risk surface"
        )
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
        raise ReviewBeforeCiGateError(
            "bypass_reason is only valid when the review gate is required"
        )
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
            stateful_fallback=stateful_fallback,
            stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
            files=files,
            matched=matched,
            summary="local review-before-CI gate bypassed with explicit reason; required GitHub checks still apply",
        )
    if stateful_fallback and not stateful_fallback_matrix_complete:
        return _gate(
            normalized_lane,
            "required",
            required,
            review_gate_complete=False,
            may_handoff_to_ci=False,
            bypass_reason=None,
            stateful_fallback=True,
            stateful_fallback_matrix_complete=False,
            files=files,
            matched=matched,
            summary="complete the executable stateful fallback boundary matrix before expensive validation or CI",
        )
    if required and not review_gate_complete:
        return _gate(
            normalized_lane,
            "required",
            required,
            review_gate_complete=False,
            may_handoff_to_ci=False,
            bypass_reason=None,
            stateful_fallback=stateful_fallback,
            stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
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
            stateful_fallback=stateful_fallback,
            stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
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
        stateful_fallback=stateful_fallback,
        stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
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
    stateful_fallback: bool,
    stateful_fallback_matrix_complete: bool,
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
        stateful_fallback=stateful_fallback,
        stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
        changed_files=files,
        matched_surfaces=matched,
        required_local_checks=_required_checks(matched, stateful_fallback=stateful_fallback),
        summary=summary,
    )


def _matched_surfaces(lane: str, files: Sequence[str], risk_surfaces: Sequence[str]) -> list[str]:
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


def _required_checks(matched: Sequence[str], *, stateful_fallback: bool = False) -> list[str]:
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
    if stateful_fallback:
        checks.append(
            "complete one executable stateful fallback boundary matrix (production entrypoints, eligible versus terminal failure classes, effective provider/model identity, current and legacy success/failure resume lineage, and adjacent authority-isolation paths)"
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


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--review-gate-complete", action="store_true")
    parser.add_argument("--bypass-reason")
    parser.add_argument("--risk-surface", action="append", default=[])
    parser.add_argument("--risk-assessment-complete", action="store_true")
    parser.add_argument("--stateful-fallback", action="store_true")
    parser.add_argument("--stateful-fallback-matrix-complete", action="store_true")
    parser.add_argument("--workflow-review-receipt")
    parser.add_argument("--workflow-risk-base", default="origin/main")
    parser.add_argument("--workflow-risk-head", default="HEAD")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--governing-issue", type=int)
    parser.add_argument("--rejected-review-history")
    parser.add_argument("--contract-revalidation-receipt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = workflow_risk_evidence_from_git(
            Path.cwd(), base=args.workflow_risk_base, head=args.workflow_risk_head
        )
        if any(
            value is not None
            for value in (
                args.pr_number,
                args.governing_issue,
                args.rejected_review_history,
                args.contract_revalidation_receipt,
            )
        ):
            if (
                args.pr_number is None
                or args.governing_issue is None
                or not args.rejected_review_history
            ):
                raise ReviewBeforeCiGateError(
                    "PR scope revalidation requires --pr-number, --governing-issue, and --rejected-review-history"
                )
            history = json.loads(Path(args.rejected_review_history).read_text(encoding="utf-8"))
            if not isinstance(history, list) or not all(
                isinstance(item, Mapping) for item in history
            ):
                raise ReviewBeforeCiGateError(
                    "rejected review history must be a JSON list of review receipts"
                )
            receipt = (
                json.loads(Path(args.contract_revalidation_receipt).read_text(encoding="utf-8"))
                if args.contract_revalidation_receipt
                else None
            )
            validate_pr_scope_revalidation(
                args.pr_number, args.governing_issue, evidence.head_sha, history, receipt
            )
        inferred_risks = list(evidence.risks)
        if inferred_risks:
            if not args.workflow_review_receipt:
                raise WorkflowReviewRiskError(
                    "actual workflow risk requires --workflow-review-receipt bound to this Git diff"
                )
            validate_workflow_review_receipt(
                Path(args.workflow_review_receipt).read_text(encoding="utf-8"), evidence
            )
        result = evaluate_review_before_ci_gate(
            lane=args.lane,
            changed_files=args.changed_file,
            review_gate_complete=args.review_gate_complete,
            bypass_reason=args.bypass_reason,
            risk_surfaces=[*args.risk_surface, *inferred_risks],
            risk_assessment_complete=args.risk_assessment_complete,
            stateful_fallback=args.stateful_fallback,
            stateful_fallback_matrix_complete=args.stateful_fallback_matrix_complete,
        )
    except (OSError, ReviewBeforeCiGateError, WorkflowReviewRiskError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **asdict(result)}, sort_keys=True))
    return 0 if result.may_handoff_to_ci else 1


if __name__ == "__main__":
    raise SystemExit(main())
