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
from scripts.validate_issue_readiness import classify_issue_body

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
PROTECTED_REVIEW_FINDING = re.compile(
    r"(?im)^\s*(?:#{1,6}\s+)?(?:(?:[-*+]|\d{1,9}[.)])\s+)?(?:\*\*)?"
    r"(?:severity\s*:\s*(?:\*\*)?)?(?:\[P[01]\]|P[01])(?:\*\*)?"
    r"(?=\s|[:—-]|$)"
)
REVIEW_CONTRACT_DIGEST = re.compile(
    r"(?im)^Governing-Contract-SHA256:\s*([0-9a-f]{64})\s*$"
)
REVIEW_CONTRACT_MARKER = re.compile(
    r"(?im)^\s*(?:>\s*)*Governing-Contract-SHA256\s*:"
)
REVALIDATION_RECEIPT_MARKER = "<!-- pr-scope-revalidation-receipt:v1 -->"
TRUSTED_RECEIPT_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


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
    authenticated_follow_up_issues = _authenticated_follow_up_issue_ids(authenticated_history)
    authenticated_follow_up_routes = _authenticated_follow_up_issue_routes(authenticated_history)
    if outcome == "split" and not _is_bounded_follow_up_issue(
        receipt.get("follow_up_issue"), governing_issue, authenticated_follow_up_issues
    ):
        raise ReviewBeforeCiGateError(
            "split requires a bounded follow-up Issue distinct from the governing Issue"
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
        durable_receipts = authenticated_history.get("durable_receipts")
        if not isinstance(durable_receipts, list):
            raise ReviewBeforeCiGateError("authenticated durable GitHub receipts are malformed")
        relevant_receipts = [
            candidate.get("receipt")
            for candidate in durable_receipts
            if isinstance(candidate, Mapping)
            and isinstance(candidate.get("receipt"), Mapping)
            and all(
                candidate["receipt"].get(field) == value
                for field, value in {
                    "version": 1,
                    "pr_number": pr_number,
                    "head_sha": head_sha,
                    "governing_issue": governing_issue,
                }.items()
            )
        ]
        distinct_receipts = {_canonical_json(candidate) for candidate in relevant_receipts}
        if len(distinct_receipts) > 1:
            raise ReviewBeforeCiGateError(
                "conflicting durable GitHub receipts exist for the same publication candidate"
            )
        if len(distinct_receipts) != 1 or receipt != relevant_receipts[0]:
            raise ReviewBeforeCiGateError(
                "local contract revalidation receipt must match a durable GitHub receipt"
            )
    elif (
        not isinstance(receipt.get("authentication"), Mapping)
        or receipt["authentication"].get("source") != "github-review"
        or not _nonempty_string(receipt["authentication"].get("actor"))
        or not _nonempty_string(receipt["authentication"].get("receipt_url"))
    ):
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt must carry authenticated GitHub review evidence"
        )
    if authenticated_history is not None:
        rejected_round_contracts = authenticated_history.get("rejected_round_contracts")
        if not isinstance(rejected_round_contracts, list):
            raise ReviewBeforeCiGateError("authenticated rejected-round contract lineage is missing")
        if outcome == "expanded_contract":
            if (
                receipt.get("expanded_issue") != governing_issue
                or receipt.get("expanded_contract_sha256") != governing_contract_sha256
            ):
                raise ReviewBeforeCiGateError(
                    "expanded_contract must bind the live governing Issue contract"
                )
            if receipt.get("expanded_from_rounds") != rejected_round_contracts:
                raise ReviewBeforeCiGateError(
                    "expanded_contract must bind every authenticated rejected-round contract/head"
                )
            if not any(
                round_contract.get("governing_contract_sha256") != governing_contract_sha256
                for round_contract in rejected_round_contracts
                if isinstance(round_contract, Mapping)
            ):
                raise ReviewBeforeCiGateError(
                    "expanded_contract requires a changed live governing Issue contract"
                )
        elif any(
            isinstance(round_contract, Mapping)
            and round_contract.get("governing_contract_sha256") != governing_contract_sha256
            for round_contract in rejected_round_contracts
        ):
            raise ReviewBeforeCiGateError(
                "changed governing Issue contract requires expanded_contract lineage"
            )
    elif outcome == "expanded_contract" and (
        receipt.get("expanded_issue") != governing_issue
        or receipt.get("expanded_contract_sha256") != governing_contract_sha256
    ):
        raise ReviewBeforeCiGateError(
            "expanded_contract must bind the live governing Issue contract"
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
    split_has_routed_finding = False
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
        if scope_class == "adjacent_pre_existing" and not _is_bounded_follow_up_issue(
            finding.get("follow_up_issue"), governing_issue, authenticated_follow_up_issues
        ):
            raise ReviewBeforeCiGateError(
                "adjacent/pre-existing findings require a bounded follow-up Issue"
            )
        if (
            scope_class == "adjacent_pre_existing"
            and authenticated_follow_up_routes is not None
            and finding_id
            not in authenticated_follow_up_routes.get(finding.get("follow_up_issue"), set())
        ):
            raise ReviewBeforeCiGateError(
                "adjacent/pre-existing finding is not durably routed by its follow-up Issue"
            )
        if (
            scope_class == "adjacent_pre_existing"
            and finding.get("follow_up_issue") == receipt.get("follow_up_issue")
        ):
            split_has_routed_finding = True
        if scope_class == "security_authority_scope_expansion" and outcome != "expanded_contract":
            raise ReviewBeforeCiGateError(
                "security/authority findings require authenticated expanded_contract scope"
            )
    if expected_finding_ids is not None and classified_finding_ids != expected_finding_ids:
        raise ReviewBeforeCiGateError(
            "contract revalidation receipt must classify every authenticated rejected finding exactly once"
        )
    if outcome == "split" and not split_has_routed_finding:
        raise ReviewBeforeCiGateError(
            "split requires at least one classified finding routed to its follow-up Issue"
        )
    return receipt


def authenticated_pr_scope_revalidation_history(
    *,
    repository: str,
    pr_number: int,
    governing_issue: int,
    head_sha: str,
    expected_base_ref: str | None = None,
    expected_head_ref: str | None = None,
    follow_up_issue_numbers: Sequence[int] = (),
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
    snapshot_requests: list[tuple[str, bool, object]] = [
        (f"repos/{repository}/pulls/{pr_number}", False, pr),
        (f"repos/{repository}/issues/{governing_issue}", False, issue),
        (f"repos/{repository}/pulls/{pr_number}/reviews?per_page=100", True, reviews),
        (f"repos/{repository}/pulls/{pr_number}/comments?per_page=100", True, inline_comments),
        (
            f"repos/{repository}/issues/{pr_number}/comments?per_page=100",
            True,
            conversation_comments,
        ),
    ]
    if not isinstance(pr, Mapping) or not isinstance(issue, Mapping):
        raise ReviewBeforeCiGateError("GitHub PR or governing Issue response is malformed")
    if pr.get("number") != pr_number or issue.get("number") != governing_issue:
        raise ReviewBeforeCiGateError("GitHub evidence does not identify the requested PR and Issue")
    base_repo = _nested_value(pr, "base", "repo", "full_name")
    base_ref = _nested_value(pr, "base", "ref")
    head_repo = _nested_value(pr, "head", "repo", "full_name")
    head_ref = _nested_value(pr, "head", "ref")
    live_head = _nested_value(pr, "head", "sha")
    if pr.get("state") != "open":
        raise ReviewBeforeCiGateError(
            "GitHub scope-revalidation evidence must identify an open PR"
        )
    if base_repo != repository:
        raise ReviewBeforeCiGateError("GitHub PR base repository is foreign")
    if not _nonempty_string(base_ref) or (
        expected_base_ref is not None and base_ref != expected_base_ref
    ):
        raise ReviewBeforeCiGateError(
            "GitHub PR base ref does not match the authenticated publication base"
        )
    if (
        head_repo != repository
        or not _nonempty_string(head_ref)
        or (expected_head_ref is not None and head_ref != expected_head_ref)
    ):
        raise ReviewBeforeCiGateError(
            "GitHub PR head repository/ref does not match the authenticated current branch"
        )
    if not isinstance(live_head, str) or not re.fullmatch(
        r"[0-9a-f]{40}", live_head
    ):
        raise ReviewBeforeCiGateError(
            "GitHub PR evidence is foreign or has no exact live head"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise ReviewBeforeCiGateError("local publication candidate has no exact head")
    if not isinstance(issue.get("body"), str):
        raise ReviewBeforeCiGateError("GitHub governing Issue body is unavailable for contract binding")
    if not isinstance(pr.get("body"), str):
        raise ReviewBeforeCiGateError("GitHub PR body is unavailable for governing Issue binding")
    authority = resolve_issue_authority(pr["body"])
    if authority is None or authority.governing_issue != governing_issue:
        raise ReviewBeforeCiGateError(
            "GitHub PR governing Issue identity is missing, foreign, or stale"
        )
    bounded_follow_up_issues: list[int] = []
    bounded_follow_up_routes: dict[int, list[str]] = {}
    for follow_up_issue in sorted(set(follow_up_issue_numbers)):
        if not _is_bounded_follow_up_issue(follow_up_issue, governing_issue):
            raise ReviewBeforeCiGateError("follow-up Issue identity is invalid")
        follow_up = github_api(f"repos/{repository}/issues/{follow_up_issue}", False)
        if (
            not isinstance(follow_up, Mapping)
            or follow_up.get("number") != follow_up_issue
            or follow_up.get("state") != "open"
            or "pull_request" in follow_up
            or not isinstance(follow_up.get("body"), str)
            or classify_issue_body(follow_up["body"], issue_number=follow_up_issue).readiness_classification
            != "ready_candidate"
        ):
            raise ReviewBeforeCiGateError(
                "follow-up Issue must exist and carry a bounded canonical contract"
            )
        follow_up_body = follow_up["body"]
        source_issue = re.search(r"(?im)^Source-Governing-Issue:\s*#(\d+)\s*$", follow_up_body)
        source_pr = re.search(r"(?im)^Source-PR:\s*#(\d+)\s*$", follow_up_body)
        routed_findings = sorted(
            set(re.findall(r"(?im)^Routed-Finding:\s*([^\s]+)\s*$", follow_up_body))
        )
        if (
            source_issue is None
            or int(source_issue.group(1)) != governing_issue
            or source_pr is None
            or int(source_pr.group(1)) != pr_number
            or not routed_findings
        ):
            raise ReviewBeforeCiGateError(
                "follow-up Issue requires durable source PR/finding routing"
            )
        bounded_follow_up_issues.append(follow_up_issue)
        bounded_follow_up_routes[follow_up_issue] = routed_findings
        snapshot_requests.append(
            (f"repos/{repository}/issues/{follow_up_issue}", False, follow_up)
        )
    if (
        not isinstance(reviews, list)
        or not isinstance(inline_comments, list)
        or not isinstance(conversation_comments, list)
    ):
        raise ReviewBeforeCiGateError("GitHub review history is incomplete")

    pr_author = _nested_value(pr, "user", "login")
    if not _nonempty_string(pr_author):
        raise ReviewBeforeCiGateError("GitHub PR author identity is unavailable")
    reviews_by_id: dict[int, Mapping[str, object]] = {}
    for review in reviews:
        if (
            not isinstance(review, Mapping)
            or not isinstance(review.get("id"), int)
            or not isinstance(review.get("state"), str)
            or not isinstance(review.get("body"), str)
            or not _nonempty_string(_nested_value(review, "user", "login"))
            or not _nonempty_string(review.get("commit_id"))
        ):
            raise ReviewBeforeCiGateError("GitHub review history is malformed")
        reviews_by_id[review["id"]] = review
    finding_ids_by_round: dict[str, set[str]] = {}
    rejected_round_details: dict[str, dict[str, object]] = {}
    for review_id, review in reviews_by_id.items():
        reviewer = _nested_value(review, "user", "login")
        if review.get("state") != "CHANGES_REQUESTED" or reviewer == pr_author:
            continue
        commit_id = review["commit_id"]
        if not isinstance(commit_id, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_id):
            raise ReviewBeforeCiGateError("rejected review round has no exact reviewed head")
        contract_matches = REVIEW_CONTRACT_DIGEST.findall(review["body"])
        contract_markers = REVIEW_CONTRACT_MARKER.findall(review["body"])
        if len(contract_markers) != 1 or len(contract_matches) != 1:
            raise ReviewBeforeCiGateError(
                "rejected review round requires exactly one governing contract SHA-256 lineage marker"
            )
        round_id = f"review:{review_id}"
        finding_ids_by_round[round_id] = {round_id}
        rejected_round_details[round_id] = {
            "round_id": round_id,
            "verdict": "rejected",
            "review_state": "CHANGES_REQUESTED",
            "reviewer": reviewer,
            "head_sha": commit_id,
            "governing_contract_sha256": contract_matches[0],
            "review_body_sha256": _sha256_text(review["body"]),
        }
    for comment in inline_comments:
        if not isinstance(comment, Mapping) or not isinstance(comment.get("id"), int):
            raise ReviewBeforeCiGateError("GitHub review comment history is malformed")
        body = comment.get("body")
        if not isinstance(body, str) or not PROTECTED_REVIEW_FINDING.search(body):
            continue
        review_id = comment.get("pull_request_review_id")
        if isinstance(review_id, int) and review_id not in reviews_by_id:
            raise ReviewBeforeCiGateError("GitHub review comment references an unknown review")
        if not isinstance(review_id, int):
            continue
        round_id = f"review:{review_id}"
        if round_id in finding_ids_by_round:
            finding_ids_by_round[round_id].add(f"comment:{comment['id']}")
            rejected_round_details[round_id].setdefault("finding_body_sha256", {})[
                f"comment:{comment['id']}"
            ] = _sha256_text(body)
    durable_receipts: list[dict[str, object]] = []
    for comment in conversation_comments:
        if not isinstance(comment, Mapping) or not isinstance(comment.get("id"), int):
            raise ReviewBeforeCiGateError("GitHub PR conversation history is malformed")
        body = comment.get("body")
        if not isinstance(body, str) or not body.startswith(REVALIDATION_RECEIPT_MARKER):
            continue
        association = comment.get("author_association")
        author = _nested_value(comment, "user", "login")
        if association not in TRUSTED_RECEIPT_ASSOCIATIONS or not _nonempty_string(author):
            continue
        try:
            parsed_receipt = _load_json_without_duplicate_keys(
                body[len(REVALIDATION_RECEIPT_MARKER) :].strip()
            )
        except json.JSONDecodeError as exc:
            raise ReviewBeforeCiGateError("durable GitHub revalidation receipt is malformed") from exc
        if not isinstance(parsed_receipt, Mapping):
            raise ReviewBeforeCiGateError("durable GitHub revalidation receipt is malformed")
        durable_receipts.append(
            {
                "comment_id": comment["id"],
                "author": author,
                "author_association": association,
                "receipt": parsed_receipt,
            }
        )

    rejected_rounds = []
    for round_id, finding_ids in sorted(finding_ids_by_round.items()):
        round_detail = rejected_round_details[round_id]
        round_detail["finding_ids"] = sorted(finding_ids)
        rejected_rounds.append(round_detail)
    finding_ids = sorted(
        finding_id for finding_set in finding_ids_by_round.values() for finding_id in finding_set
    )
    if any(
        routed_finding not in finding_ids
        for routed_findings in bounded_follow_up_routes.values()
        for routed_finding in routed_findings
    ):
        raise ReviewBeforeCiGateError(
            "follow-up Issue routes a finding outside the authenticated rejected history"
        )
    rejected_round_contracts = [
        {
            "round_id": round_["round_id"],
            "head_sha": round_["head_sha"],
            "governing_contract_sha256": round_["governing_contract_sha256"],
        }
        for round_ in rejected_rounds
    ]
    review_history_sha256 = _sha256_text(_canonical_json(rejected_rounds))
    for path, paginate, initial_payload in snapshot_requests:
        if _canonical_json(github_api(path, paginate)) != _canonical_json(initial_payload):
            raise ReviewBeforeCiGateError(
                "GitHub review authority changed during authenticated snapshot"
            )
    return {
        "rejected_rounds": rejected_rounds,
        "finding_ids": finding_ids,
        "rejected_round_contracts": rejected_round_contracts,
        "durable_receipts": durable_receipts,
        "authentication": {
            "source": "github-api",
            "repository": repository,
            "base_ref": base_ref,
            "head_repository": head_repo,
            "head_ref": head_ref,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "candidate_head_sha": head_sha,
            "live_pr_head_sha": live_head,
            "rejected_round_ids": [round_["round_id"] for round_ in rejected_rounds],
            "finding_ids": finding_ids,
            "review_history_sha256": review_history_sha256,
        },
        "governing_contract_sha256": hashlib.sha256(
            _canonical_contract_body(issue["body"]).encode("utf-8")
        ).hexdigest(),
        "bounded_follow_up_issues": bounded_follow_up_issues,
        "bounded_follow_up_routes": bounded_follow_up_routes,
        "candidate_head_sha": head_sha,
        "live_pr_head_sha": live_head,
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


def _current_branch_open_pr(
    repository: str, *, expected_base_ref: str | None = None
) -> Mapping[str, object] | None:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    if branch.returncode != 0 or not _nonempty_string(branch.stdout):
        raise ReviewBeforeCiGateError(
            "publication requires explicit --publication-mode new or existing; "
            "cannot determine the current branch"
        )
    owner, _, _ = repository.partition("/")
    payload = _github_api(
        "repos/"
        f"{repository}/pulls?state=open&head={quote(owner + ':' + branch.stdout.strip(), safe=':')}&per_page=100",
        False,
    )
    if not isinstance(payload, list) or not all(isinstance(pr, Mapping) for pr in payload):
        raise ReviewBeforeCiGateError("publication cannot authenticate current-branch PR state")
    if len(payload) > 1:
        raise ReviewBeforeCiGateError(
            "publication requires a unique open PR for the current branch"
        )
    if not payload:
        return None
    pr = payload[0]
    if (
        not isinstance(pr.get("number"), int)
        or pr.get("state") != "open"
        or _nested_value(pr, "base", "repo", "full_name") != repository
        or (
            expected_base_ref is not None
            and _nested_value(pr, "base", "ref") != expected_base_ref
        )
        or _nested_value(pr, "head", "repo", "full_name") != repository
        or _nested_value(pr, "head", "ref") != branch.stdout.strip()
    ):
        raise ReviewBeforeCiGateError(
            "open PR evidence does not match the authenticated current branch"
        )
    return pr


def _current_branch_has_open_pr(repository: str) -> bool:
    return _current_branch_open_pr(repository) is not None


def _publication_base_ref(git_base: str) -> str:
    for prefix in ("refs/remotes/origin/", "origin/", "refs/heads/"):
        if git_base.startswith(prefix):
            git_base = git_base[len(prefix) :]
            break
    if not _nonempty_string(git_base) or re.fullmatch(r"[0-9a-f]{40}", git_base):
        raise ReviewBeforeCiGateError(
            "publication base must identify a branch ref for GitHub authentication"
        )
    return git_base


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
        r"(?:git@github\.com:|(?:https?|ssh|git)://(?:git@)?github\.com/)"
        r"([^/\s]+/[^/\s]+?)(?:\.git)?\s*",
        remote.stdout,
    )
    return match.group(1) if match else None


def _canonical_contract_body(body: str) -> str:
    return body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_json_without_duplicate_keys(value: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ReviewBeforeCiGateError(f"durable receipt has duplicate JSON key: {key}")
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=reject_duplicates)


def _git_is_strict_ancestor(ancestor_sha: object, candidate_sha: object) -> bool:
    if not isinstance(ancestor_sha, str) or not isinstance(candidate_sha, str):
        return False
    if ancestor_sha == candidate_sha:
        return False
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_sha, candidate_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _nested_value(payload: Mapping[str, object], *keys: str) -> object:
    value: object = payload
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _follow_up_issue_numbers(receipt: object) -> list[int]:
    if not isinstance(receipt, Mapping):
        return []
    values = [receipt.get("follow_up_issue")]
    classifications = receipt.get("finding_classifications")
    if isinstance(classifications, list):
        values.extend(
            finding.get("follow_up_issue")
            for finding in classifications
            if isinstance(finding, Mapping) and finding.get("follow_up_issue") is not None
        )
    return [value for value in values if isinstance(value, int) and not isinstance(value, bool)]


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


def _authenticated_follow_up_issue_ids(
    authenticated_history: Mapping[str, object] | None,
) -> set[int] | None:
    if authenticated_history is None:
        return None
    values = authenticated_history.get("bounded_follow_up_issues")
    if not isinstance(values, list) or not all(isinstance(value, int) for value in values):
        raise ReviewBeforeCiGateError("authenticated history is missing bounded follow-up Issue evidence")
    return set(values)


def _authenticated_follow_up_issue_routes(
    authenticated_history: Mapping[str, object] | None,
) -> dict[int, set[str]] | None:
    if authenticated_history is None:
        return None
    values = authenticated_history.get("bounded_follow_up_routes")
    if not isinstance(values, Mapping):
        raise ReviewBeforeCiGateError("authenticated history is missing follow-up routing evidence")
    routes: dict[int, set[str]] = {}
    for issue_number, finding_ids in values.items():
        if (
            not isinstance(issue_number, int)
            or not isinstance(finding_ids, list)
            or not all(_nonempty_string(finding_id) for finding_id in finding_ids)
        ):
            raise ReviewBeforeCiGateError("authenticated follow-up routing evidence is malformed")
        routes[issue_number] = set(finding_ids)
    return routes


def _is_bounded_follow_up_issue(
    value: object, governing_issue: int, authenticated_issue_ids: set[int] | None = None
) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        and value != governing_issue
        and (authenticated_issue_ids is None or value in authenticated_issue_ids)
    )


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
        if args.publication_mode is not None and (
            args.workflow_risk_base != "origin/main" or args.workflow_risk_head != "HEAD"
        ):
            raise ReviewBeforeCiGateError(
                "publication must authenticate the canonical origin/main...HEAD selectors"
            )
        evidence = workflow_risk_evidence_from_git(
            Path.cwd(), base=args.workflow_risk_base, head=args.workflow_risk_head
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
        origin_repository = _github_repository_from_origin()
        if args.github_repository is not None and args.github_repository != origin_repository:
            raise ReviewBeforeCiGateError(
                "GitHub repository identity does not match authenticated origin"
            )
        current_branch_pr: Mapping[str, object] | None = None
        current_branch_ref: str | None = None
        publication_base_ref: str | None = None
        if args.publication_mode == "existing":
            if not args.pr_scope_revalidation:
                raise ReviewBeforeCiGateError(
                    "existing-PR publication requires authenticated PR scope revalidation"
                )
            if not args.github_repository or args.pr_number is None:
                raise ReviewBeforeCiGateError(
                    "existing-PR publication requires GitHub repository and PR identity"
                )
            publication_base_ref = _publication_base_ref(args.workflow_risk_base)
            current_branch_pr = _current_branch_open_pr(
                args.github_repository, expected_base_ref=publication_base_ref
            )
            if current_branch_pr is None or current_branch_pr.get("number") != args.pr_number:
                raise ReviewBeforeCiGateError(
                    "existing-PR publication must match the unique open PR for the current branch"
                )
            current_branch_ref_value = _nested_value(current_branch_pr, "head", "ref")
            if not _nonempty_string(current_branch_ref_value):
                raise ReviewBeforeCiGateError(
                    "open PR evidence has no authenticated current branch ref"
                )
            current_branch_ref = current_branch_ref_value
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
        elif origin_repository is not None and _current_branch_has_open_pr(origin_repository):
            raise ReviewBeforeCiGateError(
                "publication requires explicit --publication-mode existing"
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
            receipt = (
                _load_json_without_duplicate_keys(
                    Path(args.contract_revalidation_receipt).read_text(encoding="utf-8")
                )
                if args.contract_revalidation_receipt
                else None
            )
            history = authenticated_pr_scope_revalidation_history(
                repository=args.github_repository,
                pr_number=args.pr_number,
                governing_issue=args.governing_issue,
                head_sha=evidence.head_sha,
                expected_base_ref=publication_base_ref,
                expected_head_ref=current_branch_ref,
                follow_up_issue_numbers=_follow_up_issue_numbers(receipt),
            )
            if not _git_is_strict_ancestor(history["live_pr_head_sha"], evidence.head_sha):
                raise ReviewBeforeCiGateError(
                    "local publication candidate does not strictly descend from the authenticated live PR head"
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
