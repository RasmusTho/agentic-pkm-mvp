#!/usr/bin/env python3
"""Plan the cheap review gate before expensive local validation or CI handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from urllib.parse import quote
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

if __package__ in {None, ""}:  # Supports direct ``python scripts/...`` invocation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dispatcher.verification_contract import resolve_issue_authority

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
PROTECTED_REVIEW_SEVERITY = re.compile(r"(?:\bP[01]\b|P[01][ _-]?(?:Badge|blocker))", re.IGNORECASE)


class ReviewBeforeCiGateError(ValueError):
    """Raised when review-before-CI gate input is malformed."""


def validate_pr_scope_revalidation(
    pr_number: int,
    governing_issue: int,
    head_sha: str,
    rejected_rounds: Sequence[Mapping[str, object]],
    receipt: Mapping[str, object] | None,
    *,
    governing_contract_sha256: str | None = None,
    authenticated_history: Mapping[str, object] | None = None,
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
    if (
        governing_contract_sha256 is not None
        and receipt.get("governing_contract_sha256") != governing_contract_sha256
    ):
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt does not bind the current governing Issue contract"
        )
    outcome = receipt.get("outcome")
    if outcome not in PR_SCOPE_REVALIDATION_OUTCOMES:
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt outcome must be continue_unchanged, split, or expanded_contract"
        )
    expected_finding_ids: set[str] | None = None
    if authenticated_history is not None:
        expected_authentication = authenticated_history.get("authentication")
        if receipt.get("authentication") != expected_authentication:
            raise ReviewBeforeCiGateError(
                "contract revalidation receipt GitHub evidence is missing, foreign, or stale"
            )
        raw_finding_ids = authenticated_history.get("finding_ids")
        if not isinstance(raw_finding_ids, list) or not all(
            _nonempty_string(finding_id) for finding_id in raw_finding_ids
        ):
            raise ReviewBeforeCiGateError(
                "authenticated GitHub review history has no exact protected finding set"
            )
        expected_finding_ids = set(raw_finding_ids)
    elif (
        not isinstance(receipt.get("authentication"), Mapping)
        or receipt["authentication"].get("source") != "github-review"
        or not _nonempty_string(receipt["authentication"].get("actor"))
        or not _nonempty_string(receipt["authentication"].get("receipt_url"))
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
    classifications = receipt.get("finding_classifications")
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
    classified_finding_ids: set[str] = set()
    for finding in classifications:
        if not isinstance(finding, Mapping) or not _nonempty_string(finding.get("finding_id")):
            raise ReviewBeforeCiGateError("each revalidation finding requires an identifier")
        finding_id = str(finding["finding_id"])
        if finding_id in classified_finding_ids:
            raise ReviewBeforeCiGateError(
                "each authenticated rejected finding must have exactly one classification"
            )
        classified_finding_ids.add(finding_id)
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
    if expected_finding_ids is not None and classified_finding_ids != expected_finding_ids:
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt must classify every authenticated rejected finding exactly once"
        )
    return receipt


def authenticated_pr_scope_revalidation_history(
    *,
    repository: str,
    pr_number: int,
    governing_issue: int,
    head_sha: str,
    api: Callable[[str, bool], object] | None = None,
) -> Mapping[str, object]:
    """Fetch and bind the complete live GitHub review history for one PR.

    This intentionally does not accept caller-supplied review URLs, actors, or finding IDs.
    A receipt can state a scope disposition, but its evidence set is derived again from
    GitHub immediately before the gate permits another expensive cycle.
    """
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", repository):
        raise ReviewBeforeCiGateError("GitHub repository must be an owner/repository identity")
    if pr_number <= 0 or governing_issue <= 0:
        raise ReviewBeforeCiGateError("GitHub PR and governing Issue numbers must be positive")
    github_api = api or _github_api
    pr = github_api(f"repos/{repository}/pulls/{pr_number}", False)
    issue = github_api(f"repos/{repository}/issues/{governing_issue}", False)
    reviews = github_api(f"repos/{repository}/pulls/{pr_number}/reviews?per_page=100", True)
    inline_comments = github_api(
        f"repos/{repository}/pulls/{pr_number}/comments?per_page=100", True
    )
    conversation_comments = github_api(
        f"repos/{repository}/issues/{pr_number}/comments?per_page=100", True
    )
    if not isinstance(pr, Mapping) or not isinstance(issue, Mapping):
        raise ReviewBeforeCiGateError("GitHub PR or governing Issue response is malformed")
    if pr.get("number") != pr_number or issue.get("number") != governing_issue:
        raise ReviewBeforeCiGateError("GitHub evidence does not identify the requested PR and Issue")
    base_repo = _nested_value(pr, "base", "repo", "full_name")
    live_head = _nested_value(pr, "head", "sha")
    if base_repo != repository or live_head != head_sha:
        raise ReviewBeforeCiGateError(
            "GitHub PR evidence is foreign or stale for the current repository/head"
        )
    if not isinstance(issue.get("body"), str):
        raise ReviewBeforeCiGateError("GitHub governing Issue body is unavailable for contract binding")
    if not isinstance(pr.get("body"), str):
        raise ReviewBeforeCiGateError("GitHub PR body is unavailable for governing Issue binding")
    authority = resolve_issue_authority(pr["body"])
    if authority is None or authority.governing_issue != governing_issue:
        raise ReviewBeforeCiGateError(
            "GitHub PR governing Issue identity is missing, foreign, or stale"
        )
    if (
        not isinstance(reviews, list)
        or not isinstance(inline_comments, list)
        or not isinstance(conversation_comments, list)
    ):
        raise ReviewBeforeCiGateError("GitHub review history is incomplete")

    reviews_by_id: dict[int, Mapping[str, object]] = {}
    for review in reviews:
        if (
            not isinstance(review, Mapping)
            or not isinstance(review.get("id"), int)
            or not isinstance(review.get("state"), str)
            or not isinstance(review.get("body"), str)
        ):
            raise ReviewBeforeCiGateError("GitHub review history is malformed")
        reviews_by_id[review["id"]] = review
    finding_ids_by_round: dict[str, set[str]] = {}
    for review_id, review in reviews_by_id.items():
        if review.get("state") == "CHANGES_REQUESTED":
            finding_ids_by_round.setdefault(f"review:{review_id}", set()).add(f"review:{review_id}")
        if PROTECTED_REVIEW_SEVERITY.search(review["body"]):
            finding_ids_by_round.setdefault(f"review:{review_id}", set()).add(
                f"review:{review_id}"
            )
    for comment in inline_comments:
        if not isinstance(comment, Mapping) or not isinstance(comment.get("id"), int):
            raise ReviewBeforeCiGateError("GitHub review comment history is malformed")
        body = comment.get("body")
        if not isinstance(body, str) or not PROTECTED_REVIEW_SEVERITY.search(body):
            continue
        review_id = comment.get("pull_request_review_id")
        if isinstance(review_id, int) and review_id not in reviews_by_id:
            raise ReviewBeforeCiGateError("GitHub review comment references an unknown review")
        round_id = f"review:{review_id}" if isinstance(review_id, int) else f"comment:{comment['id']}"
        finding_ids_by_round.setdefault(round_id, set()).add(f"comment:{comment['id']}")
    for comment in conversation_comments:
        if not isinstance(comment, Mapping) or not isinstance(comment.get("id"), int):
            raise ReviewBeforeCiGateError("GitHub PR conversation history is malformed")
        body = comment.get("body")
        if not isinstance(body, str) or not PROTECTED_REVIEW_SEVERITY.search(body):
            continue
        round_id = f"issue-comment:{comment['id']}"
        finding_ids_by_round.setdefault(round_id, set()).add(f"issue-comment:{comment['id']}")

    rejected_rounds = [
        {"round_id": round_id, "verdict": "rejected", "finding_ids": sorted(finding_ids)}
        for round_id, finding_ids in sorted(finding_ids_by_round.items())
    ]
    finding_ids = sorted(
        finding_id for finding_set in finding_ids_by_round.values() for finding_id in finding_set
    )
    return {
        "rejected_rounds": rejected_rounds,
        "finding_ids": finding_ids,
        "authentication": {
            "source": "github-api",
            "repository": repository,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "rejected_round_ids": [round_["round_id"] for round_ in rejected_rounds],
            "finding_ids": finding_ids,
        },
        "governing_contract_sha256": hashlib.sha256(
            _canonical_contract_body(issue["body"]).encode("utf-8")
        ).hexdigest(),
    }


def _github_api(path: str, paginate: bool) -> object:
    command = ["gh", "api"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    command.append(path)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ReviewBeforeCiGateError("authenticated GitHub review history is unavailable")
    try:
        payload: object = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewBeforeCiGateError("authenticated GitHub review history is malformed") from exc
    if paginate:
        if not isinstance(payload, list) or not all(isinstance(page, list) for page in payload):
            raise ReviewBeforeCiGateError("authenticated GitHub review pagination is malformed")
        return [item for page in payload for item in page]
    return payload


def _current_branch_has_open_pr(repository: str) -> bool:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0 or not _nonempty_string(branch.stdout):
        raise ReviewBeforeCiGateError("new-PR publication cannot determine the current branch")
    owner, _, _ = repository.partition("/")
    payload = _github_api(
        "repos/"
        f"{repository}/pulls?state=open&head={quote(owner + ':' + branch.stdout.strip(), safe=':')}&per_page=100",
        False,
    )
    if not isinstance(payload, list) or not all(isinstance(pr, Mapping) for pr in payload):
        raise ReviewBeforeCiGateError("new-PR publication cannot authenticate open-PR state")
    return bool(payload)


def _github_repository_from_origin() -> str | None:
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if remote.returncode != 0:
        return None
    match = re.fullmatch(
        r"(?:git@github\.com:|https://github\.com/)([^/\s]+/[^/\s]+?)(?:\.git)?\s*",
        remote.stdout,
    )
    return match.group(1) if match else None


def _canonical_contract_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _nested_value(payload: Mapping[str, object], *keys: str) -> object:
    value: object = payload
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


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
    parser.add_argument("--publication-mode", choices=("new", "existing"))
    parser.add_argument("--pr-scope-revalidation", action="store_true")
    parser.add_argument("--github-repository")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--governing-issue", type=int)
    parser.add_argument("--contract-revalidation-receipt")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = workflow_risk_evidence_from_git(
            Path.cwd(), base=args.workflow_risk_base, head=args.workflow_risk_head
        )
        if args.publication_mode == "existing":
            if not args.pr_scope_revalidation:
                raise ReviewBeforeCiGateError(
                    "existing-PR publication requires authenticated PR scope revalidation"
                )
        elif args.publication_mode == "new":
            if args.pr_scope_revalidation:
                raise ReviewBeforeCiGateError(
                    "new-PR publication cannot claim existing-PR scope revalidation"
                )
            if not args.github_repository:
                raise ReviewBeforeCiGateError(
                    "new-PR publication requires GitHub repository identity"
                )
            if _current_branch_has_open_pr(args.github_repository):
                raise ReviewBeforeCiGateError(
                    "new-PR publication found an existing open PR for the current branch"
                )
        elif (repository := _github_repository_from_origin()) is not None and _current_branch_has_open_pr(
            repository
        ):
            raise ReviewBeforeCiGateError(
                "open PR publication requires explicit --publication-mode existing"
            )
        if args.pr_scope_revalidation:
            if (
                args.pr_number is None
                or args.governing_issue is None
                or not args.github_repository
            ):
                raise ReviewBeforeCiGateError(
                    "PR scope revalidation requires --github-repository, --pr-number, and --governing-issue"
                )
            history = authenticated_pr_scope_revalidation_history(
                repository=args.github_repository,
                pr_number=args.pr_number,
                governing_issue=args.governing_issue,
                head_sha=evidence.head_sha,
            )
            receipt = (
                json.loads(Path(args.contract_revalidation_receipt).read_text(encoding="utf-8"))
                if args.contract_revalidation_receipt
                else None
            )
            validate_pr_scope_revalidation(
                args.pr_number,
                args.governing_issue,
                evidence.head_sha,
                history["rejected_rounds"],
                receipt,
                governing_contract_sha256=history["governing_contract_sha256"],
                authenticated_history=history,
            )
        elif any(
            value is not None
            for value in (
                args.pr_number,
                args.governing_issue,
                args.contract_revalidation_receipt,
            )
        ) or (args.github_repository is not None and args.publication_mode != "new"):
            raise ReviewBeforeCiGateError(
                "PR scope revalidation evidence cannot be omitted; pass --pr-scope-revalidation"
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
