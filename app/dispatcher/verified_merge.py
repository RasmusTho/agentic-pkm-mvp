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
from typing import Final, cast

from app.dispatcher.verification_contract import (
    IssueAuthority,
    MAX_CLOSING_ISSUES,
    has_closing_issue_attempt,
    neutralize_closing_issue_references,
    resolve_issue_authority,
    resolve_neutralized_issue_authority,
)


VERIFIED_MERGE_AUTHORITY_CONTRACT = "verified_issue_set_merge_authority.v1"
VERIFIED_MERGE_AUTHORITY_MARKER = "verified issue-set merge authority:"
VERIFIED_MERGE_PHASE_CONTRACT = "verified_issue_set_merge_phase.v1"
VERIFIED_MERGE_PHASE_MARKER = "verified issue-set merge phase:"
_CONTEXT_CONTRACT = "verification_closer_dispatch_context.v2"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_TRUSTED_AUTHOR_ASSOCIATIONS: Final = frozenset(
    {"OWNER", "MEMBER", "COLLABORATOR"}
)
_PHASES: Final = ("prepared", "merged", "reconciled", "restored")
_AUTHORITY_RECEIPT_FIELDS: Final = frozenset(
    {
        "authenticated_supporting_issues",
        "body_sha256",
        "closing_issues",
        "contract",
        "governing_issue",
        "head_sha",
        "live_supporting_issues",
        "neutralized_body_sha256",
        "pr_number",
        "repair_budget",
        "repository",
        "run_id",
    }
)
_PHASE_RECEIPT_FIELDS: Final = frozenset(
    {
        "authority_sha256",
        "body_sha256",
        "closed_issues",
        "contract",
        "head_sha",
        "merge_commit_sha",
        "phase",
        "pr_number",
        "reopened_unauthorized_issues",
        "repository",
        "run_id",
    }
)


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


def _canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _comment_receipts(
    comments: Sequence[Mapping[str, object]], marker: str
) -> list[Mapping[str, object]]:
    pattern = re.compile(
        re.escape(marker) + r"\s*```json\s*([\s\S]*?)\s*```",
        re.MULTILINE,
    )
    receipts: list[Mapping[str, object]] = []
    for comment in comments:
        if comment.get("author_association") not in _TRUSTED_AUTHOR_ASSOCIATIONS:
            continue
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        matches = pattern.findall(body)
        if len(matches) != 1:
            continue
        try:
            value = json.loads(matches[0])
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            receipts.append(value)
    return receipts


def _body_authority(body: object) -> IssueAuthority | None:
    if not isinstance(body, str):
        return None
    return resolve_issue_authority(body) or resolve_neutralized_issue_authority(body)


def _complete_merged_identity(pr: Mapping[str, object]) -> bool:
    merge_commit_sha = pr.get("merge_commit_sha")
    return bool(
        pr.get("state") == "closed"
        and pr.get("merged") is True
        and isinstance(pr.get("merged_at"), str)
        and pr.get("merged_at")
        and isinstance(merge_commit_sha, str)
        and _SHA_PATTERN.fullmatch(merge_commit_sha) is not None
    )


def _valid_authority_receipt(
    receipt: Mapping[str, object],
    *,
    pr: Mapping[str, object],
    repository: str,
    expected_run_id: str | None,
    require_live_body: bool = True,
) -> bool:
    body = pr.get("body")
    head = pr.get("head")
    authority = _body_authority(body)
    if (
        set(receipt) != _AUTHORITY_RECEIPT_FIELDS
        or receipt.get("contract") != VERIFIED_MERGE_AUTHORITY_CONTRACT
        or receipt.get("repository") != repository
        or receipt.get("pr_number") != pr.get("number")
        or not isinstance(head, Mapping)
        or receipt.get("head_sha") != head.get("sha")
        or not isinstance(receipt.get("run_id"), str)
        or not receipt.get("run_id")
        or (
            expected_run_id is not None
            and receipt.get("run_id") != expected_run_id
        )
        or not isinstance(receipt.get("repair_budget"), Mapping)
    ):
        return False
    if require_live_body and (
        authority is None
        or receipt.get("governing_issue") != authority.governing_issue
        or not isinstance(body, str)
        or _body_digest(body)
        not in {
            receipt.get("body_sha256"),
            receipt.get("neutralized_body_sha256"),
        }
    ):
        return False
    try:
        closing = _issue_tuple(
            receipt.get("closing_issues"),
            field="closing issues",
            allow_empty=False,
            maximum=MAX_CLOSING_ISSUES,
        )
        authenticated_supporting = _issue_tuple(
            receipt.get("authenticated_supporting_issues"),
            field="authenticated supporting issues",
            allow_empty=True,
        )
        live_supporting = _issue_tuple(
            receipt.get("live_supporting_issues"),
            field="live supporting issues",
            allow_empty=True,
        )
    except ValueError:
        return False
    governing_issue = receipt.get("governing_issue")
    return bool(
        _positive_int(governing_issue)
        and (
            not require_live_body
            or (
                authority is not None
                and closing == authority.closing_issues
                and live_supporting == authority.supporting_issues
            )
        )
        and set(authenticated_supporting).issubset(live_supporting)
        and (
            not require_live_body
            or (
                authority is not None
                and set(authenticated_supporting).issubset(
                    authority.supporting_issues
                )
            )
        )
        and set(closing).issubset(
            {governing_issue, *authenticated_supporting}
        )
        and receipt.get("body_sha256") != receipt.get("neutralized_body_sha256")
        and all(
            isinstance(receipt.get(field), str)
            and _DIGEST_PATTERN.fullmatch(str(receipt[field])) is not None
            for field in ("body_sha256", "neutralized_body_sha256")
        )
    )


def resolve_verified_merge_authority_receipt(
    comments: Sequence[Mapping[str, object]],
    *,
    pr: Mapping[str, object],
    repository: str,
    expected_run_id: str | None = None,
    expected_repair_budget: Mapping[str, object] | None = None,
) -> dict[str, object] | None:
    """Resolve one trusted exact-head merge receipt without accepting conflicts."""

    receipts = _comment_receipts(comments, VERIFIED_MERGE_AUTHORITY_MARKER)
    valid = [
        dict(receipt)
        for receipt in receipts
        if _valid_authority_receipt(
            receipt,
            pr=pr,
            repository=repository,
            expected_run_id=expected_run_id,
        )
    ]
    if _complete_merged_identity(pr):
        body = pr.get("body")
        if isinstance(body, str):
            live_digest = _body_digest(body)
            valid.extend(
                dict(receipt)
                for receipt in receipts
                if live_digest
                not in {
                    receipt.get("body_sha256"),
                    receipt.get("neutralized_body_sha256"),
                }
                and _valid_authority_receipt(
                    receipt,
                    pr=pr,
                    repository=repository,
                    expected_run_id=expected_run_id,
                    require_live_body=False,
                )
            )
    if not valid:
        return None
    identities = {_canonical_digest(receipt) for receipt in valid}
    if len(identities) != 1:
        return None
    authority_receipt = valid[-1]
    if (
        expected_repair_budget is not None
        and authority_receipt.get("repair_budget") != expected_repair_budget
    ):
        return None
    body = pr.get("body")
    if isinstance(body, str) and _body_digest(body) not in {
        authority_receipt.get("body_sha256"),
        authority_receipt.get("neutralized_body_sha256"),
    }:
        if resolve_verified_merge_phase(
            comments,
            authority_receipt=authority_receipt,
            pr=pr,
            allow_merged_body_drift=True,
        ) is None:
            return None
    return authority_receipt


def resolve_post_merge_governing_issue(
    comments: Sequence[Mapping[str, object]],
    *,
    pr: Mapping[str, object],
    repository: str,
) -> int | None:
    """Compatibility projection for post-merge consumers needing the governor."""

    authority = resolve_post_merge_issue_authority(
        comments,
        pr=pr,
        repository=repository,
    )
    return authority.governing_issue if authority is not None else None


def resolve_post_merge_issue_authority(
    comments: Sequence[Mapping[str, object]],
    *,
    pr: Mapping[str, object],
    repository: str,
) -> IssueAuthority | None:
    """Resolve full post-merge issue authority from the trusted receipt.

    During the neutralized merge window the body marker is evidence only. It
    cannot replace the collaborator-authored exact-head authority receipt.
    Restored/legacy bodies without a receipt may still use the ordinary PR-body
    authority grammar.
    """

    trusted_attempt = any(
        comment.get("author_association") in _TRUSTED_AUTHOR_ASSOCIATIONS
        and isinstance(comment.get("body"), str)
        and VERIFIED_MERGE_AUTHORITY_MARKER in str(comment["body"])
        for comment in comments
    )
    receipt = resolve_verified_merge_authority_receipt(
        comments, pr=pr, repository=repository
    )
    if receipt is not None:
        governing_issue = receipt.get("governing_issue")
        if not _positive_int(governing_issue):
            raise ValueError("trusted verified merge authority receipt is invalid")
        try:
            closing = _issue_tuple(
                receipt.get("closing_issues"),
                field="closing issues",
                allow_empty=False,
                maximum=MAX_CLOSING_ISSUES,
            )
            supporting = _issue_tuple(
                receipt.get("live_supporting_issues"),
                field="live supporting issues",
                allow_empty=True,
            )
        except ValueError as exc:
            raise ValueError(
                "trusted verified merge authority receipt is invalid"
            ) from exc
        return IssueAuthority(cast(int, governing_issue), closing, supporting)
    if trusted_attempt:
        raise ValueError("trusted verified merge authority receipt is invalid")
    # A neutralized marker is intentionally not standalone post-merge
    # authority. Without a trusted receipt, only the restored canonical body
    # can supply the compatibility fallback.
    return resolve_issue_authority(pr.get("body"))


def build_verified_merge_phase(
    *,
    authority_receipt: Mapping[str, object],
    phase: str,
    pr: Mapping[str, object],
    closed_issues: Sequence[int] = (),
    reopened_unauthorized_issues: Sequence[int] = (),
) -> dict[str, object]:
    """Build one idempotent, authority-bound merge-phase receipt."""

    if set(authority_receipt) != _AUTHORITY_RECEIPT_FIELDS or phase not in _PHASES:
        raise ValueError("verified merge phase authority is malformed")
    body = pr.get("body")
    head = pr.get("head")
    merge_commit_sha = pr.get("merge_commit_sha")
    closing = _issue_tuple(
        authority_receipt.get("closing_issues"),
        field="closing issues",
        allow_empty=False,
        maximum=MAX_CLOSING_ISSUES,
    )
    closed = _issue_tuple(
        list(closed_issues), field="closed issues", allow_empty=True
    )
    reopened = _issue_tuple(
        list(reopened_unauthorized_issues),
        field="reopened unauthorized issues",
        allow_empty=True,
    )
    merged_phase = _PHASES.index(phase) >= _PHASES.index("merged")
    reconciled_phase = _PHASES.index(phase) >= _PHASES.index("reconciled")
    expected_body_digest = (
        authority_receipt.get("body_sha256")
        if phase == "restored"
        else authority_receipt.get("neutralized_body_sha256")
    )
    if (
        not isinstance(body, str)
        or not isinstance(head, Mapping)
        or pr.get("number") != authority_receipt.get("pr_number")
        or head.get("sha") != authority_receipt.get("head_sha")
        or _body_digest(body) != expected_body_digest
        or (
            merged_phase
            and (
                pr.get("state") != "closed"
                or pr.get("merged") is not True
                or not isinstance(pr.get("merged_at"), str)
                or not pr.get("merged_at")
                or not isinstance(merge_commit_sha, str)
                or _SHA_PATTERN.fullmatch(merge_commit_sha) is None
            )
        )
        or (
            not merged_phase
            and (
                pr.get("state") != "open"
                or pr.get("merged_at") is not None
            )
        )
        or (reconciled_phase and closed != closing)
        or (not reconciled_phase and (closed or reopened))
        or bool(set(reopened) & set(closing))
    ):
        raise ValueError("verified merge phase live state is malformed")
    receipt = {
        "authority_sha256": _canonical_digest(authority_receipt),
        "body_sha256": _body_digest(body),
        "closed_issues": list(closed),
        "contract": VERIFIED_MERGE_PHASE_CONTRACT,
        "head_sha": authority_receipt["head_sha"],
        "merge_commit_sha": merge_commit_sha if merged_phase else None,
        "phase": phase,
        "pr_number": authority_receipt["pr_number"],
        "reopened_unauthorized_issues": list(reopened),
        "repository": authority_receipt["repository"],
        "run_id": authority_receipt["run_id"],
    }
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return {
        "phase_receipt": receipt,
        "phase_receipt_comment": (
            f"{VERIFIED_MERGE_PHASE_MARKER}\n```json\n{receipt_json}\n```"
        ),
    }


def resolve_verified_merge_phase(
    comments: Sequence[Mapping[str, object]],
    *,
    authority_receipt: Mapping[str, object],
    pr: Mapping[str, object],
    allow_merged_body_drift: bool = False,
) -> dict[str, object] | None:
    """Resolve the highest continuous, non-conflicting durable merge phase."""

    authority_digest = _canonical_digest(authority_receipt)
    expected_closing = authority_receipt.get("closing_issues")
    valid_by_phase: dict[str, list[dict[str, object]]] = {
        phase: [] for phase in _PHASES
    }
    for candidate in _comment_receipts(comments, VERIFIED_MERGE_PHASE_MARKER):
        phase = candidate.get("phase")
        if (
            set(candidate) != _PHASE_RECEIPT_FIELDS
            or candidate.get("contract") != VERIFIED_MERGE_PHASE_CONTRACT
            or phase not in _PHASES
            or candidate.get("authority_sha256") != authority_digest
            or candidate.get("repository") != authority_receipt.get("repository")
            or candidate.get("pr_number") != authority_receipt.get("pr_number")
            or candidate.get("head_sha") != authority_receipt.get("head_sha")
            or candidate.get("run_id") != authority_receipt.get("run_id")
        ):
            continue
        expected_digest = (
            authority_receipt.get("body_sha256")
            if phase == "restored"
            else authority_receipt.get("neutralized_body_sha256")
        )
        merged_phase = _PHASES.index(str(phase)) >= _PHASES.index("merged")
        reconciled_phase = _PHASES.index(str(phase)) >= _PHASES.index(
            "reconciled"
        )
        try:
            closed = _issue_tuple(
                candidate.get("closed_issues"),
                field="closed issues",
                allow_empty=True,
            )
            reopened = _issue_tuple(
                candidate.get("reopened_unauthorized_issues"),
                field="reopened unauthorized issues",
                allow_empty=True,
            )
        except ValueError:
            continue
        if (
            candidate.get("body_sha256") != expected_digest
            or (reconciled_phase and list(closed) != expected_closing)
            or (not reconciled_phase and (closed or reopened))
            or bool(set(closed) & set(reopened))
            or (
                merged_phase
                and candidate.get("merge_commit_sha")
                != pr.get("merge_commit_sha")
            )
            or (not merged_phase and candidate.get("merge_commit_sha") is not None)
        ):
            continue
        valid_by_phase[str(phase)].append(dict(candidate))

    highest: dict[str, object] | None = None
    reconciled_evidence: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    for phase in _PHASES:
        candidates = valid_by_phase[phase]
        if not candidates:
            break
        if len({_canonical_digest(candidate) for candidate in candidates}) != 1:
            return None
        highest = candidates[-1]
        phase_evidence = (
            tuple(cast(Sequence[int], highest["closed_issues"])),
            tuple(
                cast(Sequence[int], highest["reopened_unauthorized_issues"])
            ),
        )
        if phase == "reconciled":
            reconciled_evidence = phase_evidence
        elif phase == "restored" and phase_evidence != reconciled_evidence:
            return None
    if highest is None:
        return None
    current_body = pr.get("body")
    current_digest = _body_digest(current_body) if isinstance(current_body, str) else None
    if current_digest not in {
        authority_receipt.get("body_sha256"),
        authority_receipt.get("neutralized_body_sha256"),
    } and not (allow_merged_body_drift and _complete_merged_identity(pr)):
        return None
    return highest


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
