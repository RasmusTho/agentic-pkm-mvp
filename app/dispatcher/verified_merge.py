"""Deterministic issue-set merge planning and reconciliation.

This module performs no GitHub writes. It binds a live PR snapshot to the
authenticated verification-closer context, prepares a reversible body with no
automatic closing keywords, and computes the only safe post-merge issue-state
mutations. The verification-and-closure skill owns the surrounding gates and
the explicit GitHub operations.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from app.dispatcher.verification_contract import (
    MAX_CLOSING_ISSUES,
    has_closing_issue_attempt,
    neutralize_closing_issue_references,
    resolve_issue_authority,
    resolve_neutralized_issue_authority,
)


VERIFIED_MERGE_AUTHORITY_CONTRACT = "verified_issue_set_merge_authority.v1"
VERIFIED_MERGE_AUTHORITY_MARKER = "verified issue-set merge authority:"
_CONTEXT_CONTRACT = "verification_closer_dispatch_context.v2"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _issue_tuple(
    value: object,
    *,
    field: str,
    allow_empty: bool,
    maximum: int | None = None,
) -> tuple[int, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not _positive_int(item) for item in value)
        or len(set(value)) != len(value)
        or value != sorted(value)
        or (maximum is not None and len(value) > maximum)
    ):
        raise ValueError(f"verified merge {field} is malformed")
    return tuple(value)


def _live_closing_issues(value: object, *, repository: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ValueError("verified merge live closing issues are malformed")
    numbers: list[int] = []
    for item in value:
        if _positive_int(item):
            numbers.append(item)
            continue
        if not isinstance(item, Mapping) or not _positive_int(item.get("number")):
            raise ValueError("verified merge live closing issues are malformed")
        item_repository = item.get("repository")
        if item_repository is not None and item_repository != repository:
            raise ValueError("verified merge live closing issue crossed repository authority")
        number = item["number"]
        assert isinstance(number, int)
        numbers.append(number)
    if len(set(numbers)) != len(numbers) or len(numbers) > MAX_CLOSING_ISSUES:
        raise ValueError("verified merge live closing issues are malformed")
    return tuple(sorted(numbers))


def _body_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def prepare_verified_merge(
    *,
    context: Mapping[str, object],
    pr: Mapping[str, object],
    live_closing_issues: object,
) -> dict[str, object]:
    """Build the exact, reversible merge plan for one verified PR head."""
    repository = context.get("repository")
    pr_number = context.get("pr_number")
    governing_issue = context.get("governing_issue")
    head_sha = context.get("head_sha")
    run_id = context.get("run_id")
    repair_budget = context.get("repair_budget")
    if (
        context.get("contract") != _CONTEXT_CONTRACT
        or not isinstance(repository, str)
        or not repository
        or not _positive_int(pr_number)
        or not _positive_int(governing_issue)
        or not isinstance(head_sha, str)
        or _SHA_PATTERN.fullmatch(head_sha) is None
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(repair_budget, Mapping)
    ):
        raise ValueError("verified merge context is malformed")

    closing = _issue_tuple(
        context.get("closing_issues"),
        field="closing issues",
        allow_empty=False,
        maximum=MAX_CLOSING_ISSUES,
    )
    supporting = _issue_tuple(
        context.get("supporting_issues"),
        field="supporting issues",
        allow_empty=True,
    )
    assert isinstance(governing_issue, int)
    if not set(closing).issubset({governing_issue, *supporting}):
        raise ValueError("verified merge closing authority is not supported")

    pr_head = pr.get("head")
    body = pr.get("body")
    title = pr.get("title")
    if (
        pr.get("number") != pr_number
        or pr.get("state") != "open"
        or pr.get("merged_at") is not None
        or pr.get("draft") is not False
        or not isinstance(pr_head, Mapping)
        or pr_head.get("sha") != head_sha
        or not isinstance(body, str)
        or not isinstance(title, str)
        or has_closing_issue_attempt(title)
    ):
        raise ValueError("verified merge live PR snapshot is ineligible")

    authority = resolve_issue_authority(body)
    if (
        authority is None
        or authority.governing_issue != governing_issue
        or authority.closing_issues != closing
        or not set(supporting).issubset(authority.supporting_issues)
    ):
        raise ValueError("verified merge live PR authority changed")
    observed_closing = _live_closing_issues(
        live_closing_issues,
        repository=repository,
    )
    if observed_closing != closing:
        raise ValueError("verified merge GitHub closing links changed")

    neutralized_body = neutralize_closing_issue_references(body, authority)
    if resolve_neutralized_issue_authority(neutralized_body) != authority:
        raise ValueError("verified merge neutralized authority is malformed")
    receipt = {
        "authenticated_supporting_issues": list(supporting),
        "body_sha256": _body_digest(body),
        "closing_issues": list(closing),
        "contract": VERIFIED_MERGE_AUTHORITY_CONTRACT,
        "governing_issue": governing_issue,
        "head_sha": head_sha,
        "live_supporting_issues": list(authority.supporting_issues),
        "neutralized_body_sha256": _body_digest(neutralized_body),
        "pr_number": pr_number,
        "repair_budget": dict(repair_budget),
        "repository": repository,
        "run_id": run_id,
    }
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return {
        "authority_receipt": receipt,
        "authority_receipt_comment": (
            f"{VERIFIED_MERGE_AUTHORITY_MARKER}\n```json\n{receipt_json}\n```"
        ),
        "fixed_commit_message": (
            "Exact-head delivery; issue closure is performed explicitly from the "
            "authenticated issue-set receipt."
        ),
        "fixed_commit_title": f"PR #{pr_number} verified delivery",
        "neutralized_body": neutralized_body,
        "original_body": body,
    }


def plan_post_merge_reconciliation(
    *,
    pr_number: int,
    authenticated_closing_issues: Sequence[int],
    observed_closing_issues: Sequence[int],
    issue_evidence: Sequence[Mapping[str, object]],
) -> dict[str, list[int]]:
    """Plan explicit closes and safe reopening after a mutable-body race.

    Unauthorized issues are reopened only when GitHub attributes their closure
    to this PR. An independently closed issue is never reopened by inference;
    it is returned as unresolved evidence and blocks the final receipt.
    """
    expected = tuple(authenticated_closing_issues)
    observed = tuple(observed_closing_issues)
    if (
        not _positive_int(pr_number)
        or not expected
        or len(expected) > MAX_CLOSING_ISSUES
        or any(not _positive_int(item) for item in expected)
        or len(set(expected)) != len(expected)
        or any(not _positive_int(item) for item in observed)
        or len(set(observed)) != len(observed)
    ):
        raise ValueError("post-merge reconciliation authority is malformed")

    by_number: dict[int, Mapping[str, object]] = {}
    for item in issue_evidence:
        number = item.get("number")
        state = item.get("state")
        closed_by = item.get("closed_by_pull_requests")
        if (
            not _positive_int(number)
            or state not in {"open", "closed"}
            or not isinstance(closed_by, list)
            or any(not _positive_int(value) for value in closed_by)
            or len(set(closed_by)) != len(closed_by)
            or number in by_number
        ):
            raise ValueError("post-merge issue evidence is malformed")
        assert isinstance(number, int)
        by_number[number] = item

    relevant = set(expected) | set(observed)
    if not relevant.issubset(by_number):
        raise ValueError("post-merge issue evidence is incomplete")

    unauthorized = sorted(set(observed) - set(expected))
    reopen: list[int] = []
    unresolved: list[int] = []
    for number in unauthorized:
        evidence = by_number[number]
        if evidence["state"] == "closed":
            closed_by = evidence["closed_by_pull_requests"]
            assert isinstance(closed_by, list)
            if pr_number in closed_by:
                reopen.append(number)
            else:
                unresolved.append(number)

    return {
        "explicitly_close": sorted(expected),
        "reopen_unauthorized": reopen,
        "unexpected_open_references": [
            number for number in unauthorized if by_number[number]["state"] == "open"
        ],
        "unresolved_unauthorized_closures": unresolved,
    }
