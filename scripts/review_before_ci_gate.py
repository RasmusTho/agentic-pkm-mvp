#!/usr/bin/env python3
"""Plan the cheap review gate before expensive local validation or CI handoff.

GitHub Actions event-admission and concurrency semantics are inferred from the
actual workflow diff. When that inference finds a high-risk workflow change, a
local review receipt bound to the exact head, base, and canonical diff is
required before handoff. The receipt is ordering evidence only: current-head
hosted CI and the final independent review remain the merge authorities.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__:
    from scripts.workflow_review_risk import (
        DEFAULT_RECEIPT_DIR,
        WORKFLOW_PREFIX,
        WORKFLOW_INFERRED_RISKS,
        WORKFLOW_REVIEW_SCENARIOS,
        WorkflowReviewRiskError,
        build_workflow_review_receipt_template,
        canonical_diff_sha256,
        infer_workflow_risk_surfaces,
        is_workflow_path,
        validate_workflow_review_receipt,
    )
else:
    from workflow_review_risk import (
        DEFAULT_RECEIPT_DIR,
        WORKFLOW_PREFIX,
        WORKFLOW_INFERRED_RISKS,
        WORKFLOW_REVIEW_SCENARIOS,
        WorkflowReviewRiskError,
        build_workflow_review_receipt_template,
        canonical_diff_sha256,
        infer_workflow_risk_surfaces,
        is_workflow_path,
        validate_workflow_review_receipt,
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
CANONICAL_WORKFLOW_BASE_REF = "origin/main"

__all__ = ["WORKFLOW_REVIEW_SCENARIOS"]


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
    stateful_fallback: bool
    stateful_fallback_matrix_complete: bool
    changed_files: list[str]
    matched_surfaces: list[str]
    declared_risk_surfaces: list[str]
    inferred_risk_surfaces: list[str]
    workflow_review_receipt_required: bool
    workflow_review_receipt_valid: bool
    workflow_review_receipt_errors: list[str]
    workflow_diff_sha256: str | None
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
    workflow_diff: str | None = None,
    head_sha: str | None = None,
    base_sha: str | None = None,
    workflow_review_receipt: Mapping[str, Any] | None = None,
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

    declared_risks = _normalize_risk_surfaces(risk_surfaces)
    inferred_risks = infer_workflow_risk_surfaces(files, workflow_diff)
    risks = sorted(set(declared_risks) | set(inferred_risks))

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
            "risk surfaces are valid only for implementation, governance, or direct-repair lanes"
        )
    if normalized_lane in RISK_REVIEW_LANES and not risk_assessment_complete:
        raise ReviewBeforeCiGateError(
            "implementation, governance, and direct-repair lanes require an explicit completed risk assessment, "
            "including when no high-risk surface applies"
        )

    workflow_diff_sha256 = (
        canonical_diff_sha256(workflow_diff) if workflow_diff is not None else None
    )
    receipt_required = bool(set(inferred_risks) & WORKFLOW_INFERRED_RISKS)
    receipt_errors: list[str] = []
    receipt_valid = False
    if receipt_required:
        receipt_errors = validate_workflow_review_receipt(
            workflow_review_receipt,
            head_sha=head_sha,
            base_sha=base_sha,
            diff_sha256=workflow_diff_sha256,
            inferred_risks=inferred_risks,
        )
        receipt_valid = not receipt_errors

    matched = _matched_surfaces(normalized_lane, files, risks)
    required = bool(matched)
    bypass = _clean_text(bypass_reason)
    if bypass and not required:
        raise ReviewBeforeCiGateError("bypass_reason is only valid when the review gate is required")
    if bypass and (normalized_lane != "direct-repair" or risks):
        raise ReviewBeforeCiGateError(
            "bypass_reason is valid only for an emergency direct-repair with no "
            "declared high-risk surface and no inferred high-risk surface"
        )
    common = dict(
        declared_risks=declared_risks,
        inferred_risks=inferred_risks,
        receipt_required=receipt_required,
        receipt_valid=receipt_valid,
        receipt_errors=receipt_errors,
        workflow_diff_sha256=workflow_diff_sha256,
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
            **common,
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
            **common,
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
            **common,
        )
    if receipt_required and not receipt_valid:
        return _gate(
            normalized_lane,
            "required",
            required,
            review_gate_complete=review_gate_complete,
            may_handoff_to_ci=False,
            bypass_reason=None,
            stateful_fallback=stateful_fallback,
            stateful_fallback_matrix_complete=stateful_fallback_matrix_complete,
            files=files,
            matched=matched,
            summary=(
                "workflow event/concurrency risk was inferred from the diff; record a clean exact-bound "
                "local review receipt before expensive validation or CI"
            ),
            **common,
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
            **common,
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
        **common,
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
    declared_risks: list[str],
    inferred_risks: list[str],
    receipt_required: bool,
    receipt_valid: bool,
    receipt_errors: list[str],
    workflow_diff_sha256: str | None,
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
        declared_risk_surfaces=declared_risks,
        inferred_risk_surfaces=inferred_risks,
        workflow_review_receipt_required=receipt_required,
        workflow_review_receipt_valid=receipt_valid,
        workflow_review_receipt_errors=receipt_errors,
        workflow_diff_sha256=workflow_diff_sha256,
        required_local_checks=_required_checks(
            matched,
            stateful_fallback=stateful_fallback,
            workflow_receipt_required=receipt_required,
        ),
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


def _required_checks(
    matched: Sequence[str],
    *,
    stateful_fallback: bool = False,
    workflow_receipt_required: bool = False,
) -> list[str]:
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
    if workflow_receipt_required:
        checks.append(
            "record a clean review-before-ci-workflow-risk.v1 receipt bound to the exact head, base, diff digest, inferred risks, and closed workflow scenario matrix"
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


def _git_output(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise ReviewBeforeCiGateError(
            f"failed to resolve Git context: {detail.strip()}"
        ) from exc
    return result.stdout.strip()


def _changed_workflow_paths() -> list[str]:
    output = _git_output(
        [
            "diff",
            "--name-only",
            f"{CANONICAL_WORKFLOW_BASE_REF}...HEAD",
            "--",
            WORKFLOW_PREFIX,
        ]
    )
    return [path for path in output.splitlines() if is_workflow_path(path)]


def _load_workflow_diff(workflow_paths: Sequence[str]) -> str | None:
    if not workflow_paths:
        return None
    return _git_output(
        [
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--unified=3",
            f"{CANONICAL_WORKFLOW_BASE_REF}...HEAD",
            "--",
            *workflow_paths,
        ]
    )


def _load_receipt(path: str | None) -> Mapping[str, Any] | None:
    if not path:
        return None
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewBeforeCiGateError(
            f"failed to read workflow review receipt {path}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ReviewBeforeCiGateError("workflow review receipt root must be an object")
    return payload


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
    parser.add_argument("--write-workflow-review-template")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        files = [_normalize_path(path) for path in args.changed_file]
        workflow_paths = _changed_workflow_paths()
        files = sorted(set(files) | set(workflow_paths))
        workflow_diff = _load_workflow_diff(workflow_paths)
        inferred_risks = infer_workflow_risk_surfaces(files, workflow_diff)
        needs_git_identity = bool(set(inferred_risks) & WORKFLOW_INFERRED_RISKS)
        head_sha = None
        base_sha = None
        if needs_git_identity:
            head_sha = _git_output(["rev-parse", "HEAD"])
            base_sha = _git_output(["rev-parse", CANONICAL_WORKFLOW_BASE_REF])

        receipt_path = args.workflow_review_receipt
        if needs_git_identity and not receipt_path and head_sha:
            default_path = DEFAULT_RECEIPT_DIR / f"{head_sha}.json"
            if default_path.exists():
                receipt_path = str(default_path)
        receipt = _load_receipt(receipt_path)

        if args.write_workflow_review_template:
            if workflow_diff is None or head_sha is None or base_sha is None:
                raise ReviewBeforeCiGateError(
                    "workflow review templates require an inferred workflow diff and exact Git identity"
                )
            template = build_workflow_review_receipt_template(
                head_sha=head_sha,
                base_sha=base_sha,
                workflow_diff=workflow_diff,
                inferred_risks=inferred_risks,
            )
            output = Path(args.write_workflow_review_template)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            receipt = template

        result = evaluate_review_before_ci_gate(
            lane=args.lane,
            changed_files=files,
            review_gate_complete=args.review_gate_complete,
            bypass_reason=args.bypass_reason,
            risk_surfaces=args.risk_surface,
            risk_assessment_complete=args.risk_assessment_complete,
            stateful_fallback=args.stateful_fallback,
            stateful_fallback_matrix_complete=args.stateful_fallback_matrix_complete,
            workflow_diff=workflow_diff,
            head_sha=head_sha,
            base_sha=base_sha,
            workflow_review_receipt=receipt,
        )
    except (ReviewBeforeCiGateError, WorkflowReviewRiskError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **asdict(result)}, sort_keys=True))
    return 0 if result.may_handoff_to_ci else 1


if __name__ == "__main__":
    raise SystemExit(main())
