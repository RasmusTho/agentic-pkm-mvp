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
from datetime import datetime, timezone
from typing import Final, cast

from app.dispatcher.verification_contract import (
    IssueAuthority,
    MAX_CLOSING_ISSUES,
    has_closing_issue_attempt,
    has_neutralized_closing_marker,
    neutralize_closing_issue_references,
    resolve_builderops_routing_status,
    resolve_final_review_rounds,
    resolve_issue_authority,
    resolve_neutralized_issue_authority,
)


VERIFIED_MERGE_AUTHORITY_CONTRACT = "verified_issue_set_merge_authority.v1"
VERIFIED_MERGE_AUTHORITY_MARKER = "verified issue-set merge authority:"
VERIFIED_MERGE_PHASE_CONTRACT = "verified_issue_set_merge_phase.v1"
VERIFIED_MERGE_PHASE_MARKER = "verified issue-set merge phase:"
VERIFIED_MERGE_READINESS_CONTRACT = "verified_issue_set_merge_readiness.v1"
ISSUE_FREE_REVIEWED_LANE_RECEIPT_CONTRACT = "issue_free_reviewed_lane_receipt.v1"
ISSUE_FREE_REVIEWED_LANE_RECEIPT_MARKER = "issue-free reviewed lane receipt:"
FIXED_VERIFIED_MERGE_COMMIT_MESSAGE = (
    "Exact-head delivery; issue closure is performed explicitly from the "
    "authenticated issue-set receipt."
)
ISSUE_FREE_REVIEWED_LANE_MERGE_COMMIT_MESSAGE = (
    "Exact-head delivery for an authenticated issue-free reviewed lane."
)
NEUTRALIZED_BODY_RESTORATION_CONTRACT = (
    "verified_issue_set_neutralized_body_restoration.v1"
)
_CONTEXT_CONTRACT = "verification_closer_dispatch_context.v2"
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_CANONICAL_UTC_TIMESTAMP_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
_TRUSTED_AUTHOR_ASSOCIATIONS: Final = frozenset(
    {"OWNER", "MEMBER", "COLLABORATOR"}
)


def fixed_verified_merge_commit_title(pr_number: object) -> str:
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number < 1:
        raise ValueError("verified merge PR number is malformed")
    return f"PR #{pr_number} verified delivery"


_PHASES: Final = ("prepared", "merged", "reconciled", "restored")
_LEGACY_TERMINAL_LF_CUTOFF: Final = datetime(
    2026, 7, 21, 16, 32, 11, tzinfo=timezone.utc
)
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
_MERGE_READINESS_FIELDS: Final = frozenset(
    {
        "contract",
        "further_commits_anticipated",
        "head_sha",
        "required_checks_green",
        "review_gate_resolved",
    }
)
_MERGE_READINESS_ASSERTIONS: Final = (
    ("required_checks_green", True),
    ("review_gate_resolved", True),
    ("further_commits_anticipated", False),
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
    """Digest the GitHub PR-body form used by verified-merge authority.

    GitHub may persist a body without one terminal LF that was present when the
    authority receipt was prepared.  That sole representation difference is
    equivalent here; all other bytes, including whitespace, remain exact.
    """

    canonical_body = body[:-1] if body.endswith("\n") else body
    return hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()


def _raw_terminal_lf_digest(body: str) -> str:
    return hashlib.sha256((body + "\n").encode("utf-8")).hexdigest()


def _matches_stored_body_digest(
    body: str,
    stored_digest: object,
    *,
    allow_legacy_terminal_lf: bool = False,
) -> bool:
    """Accept a canonical digest or the one pre-#4010 stored LF form.

    New receipts use :func:`_body_digest`.  A historical receipt may instead
    have stored the raw digest of a body ending in exactly one LF, while GitHub
    now returns that same body without the LF.  Do not turn this into trimming:
    a second LF, whitespace, CRLF, and interior changes remain distinct.
    """

    if (
        not isinstance(stored_digest, str)
        or _DIGEST_PATTERN.fullmatch(stored_digest) is None
    ):
        return False
    # Always preserve the normal #4010 canonical path first. In particular,
    # an unchanged body ending in two LFs canonicalizes to one terminal LF.
    if _body_digest(body) == stored_digest:
        return True
    if (
        not allow_legacy_terminal_lf
        or body.endswith("\n")
        or "\r" in body
    ):
        return False
    return _raw_terminal_lf_digest(body) == stored_digest


def _legacy_terminal_lf_provenance(comment: Mapping[str, object]) -> bool:
    """Authenticate an unedited authority comment predating #4010's merge."""

    timestamps: list[datetime] = []
    for field in ("created_at", "updated_at"):
        value = comment.get(field)
        if (
            not isinstance(value, str)
            or _CANONICAL_UTC_TIMESTAMP_PATTERN.fullmatch(value) is None
        ):
            return False
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return False
        timestamps.append(parsed)
    return bool(
        timestamps[0] <= timestamps[1]
        and all(timestamp < _LEGACY_TERMINAL_LF_CUTOFF for timestamp in timestamps)
    )


def _canonical_digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _comment_receipt_entries(
    comments: Sequence[Mapping[str, object]], marker: str
) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
    pattern = re.compile(
        re.escape(marker) + r"\s*```json\s*([\s\S]*?)\s*```",
        re.MULTILINE,
    )
    receipts: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
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
            receipts.append((value, comment))
    return receipts


def _comment_receipts(
    comments: Sequence[Mapping[str, object]], marker: str
) -> list[Mapping[str, object]]:
    return [receipt for receipt, _ in _comment_receipt_entries(comments, marker)]


def _comment_authenticates_legacy_authority(
    comment: Mapping[str, object], authority_receipt: Mapping[str, object]
) -> bool:
    return bool(
        comment.get("author_association") in _TRUSTED_AUTHOR_ASSOCIATIONS
        and _legacy_terminal_lf_provenance(comment)
        and any(
            receipt == authority_receipt
            for receipt, candidate in _comment_receipt_entries(
                [comment], VERIFIED_MERGE_AUTHORITY_MARKER
            )
            if candidate is comment
        )
    )


def _comments_authenticate_legacy_authority(
    comments: Sequence[Mapping[str, object]],
    authority_receipt: Mapping[str, object],
) -> bool:
    return any(
        _comment_authenticates_legacy_authority(comment, authority_receipt)
        for comment in comments
    )


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


def _assert_neutralization_precondition(
    merge_readiness: object,
    *,
    head_sha: str,
) -> None:
    """Refuse neutralization unless this exact head is the final head.

    Neutralizing a PR body converts durable closing authority into a state that
    is only valid while one exact-head merge attempt is in flight. A neutralized
    body that outlives its attempt deadlocks ``pr-contract`` on every later head,
    so the caller must state, bound to this head, that CI and review are green
    and that no further commits are anticipated.
    """

    if (
        not isinstance(merge_readiness, Mapping)
        or set(merge_readiness) != _MERGE_READINESS_FIELDS
        or merge_readiness.get("contract") != VERIFIED_MERGE_READINESS_CONTRACT
        or merge_readiness.get("head_sha") != head_sha
        or any(
            not isinstance(merge_readiness.get(field), bool)
            for field, _ in _MERGE_READINESS_ASSERTIONS
        )
    ):
        raise ValueError("verified merge readiness is malformed")
    if any(
        merge_readiness[field] is not expected
        for field, expected in _MERGE_READINESS_ASSERTIONS
    ):
        raise ValueError("verified merge neutralization precondition is unmet")


def _valid_authority_receipt(
    receipt: Mapping[str, object],
    *,
    pr: Mapping[str, object],
    repository: str,
    expected_run_id: str | None,
    allow_legacy_terminal_lf: bool = False,
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
        or not any(
            _matches_stored_body_digest(
                body,
                digest,
                allow_legacy_terminal_lf=allow_legacy_terminal_lf,
            )
            for digest in (
                receipt.get("body_sha256"),
                receipt.get("neutralized_body_sha256"),
            )
        )
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

    entries = _comment_receipt_entries(comments, VERIFIED_MERGE_AUTHORITY_MARKER)
    valid_entries = [
        (dict(receipt), comment)
        for receipt, comment in entries
        if _valid_authority_receipt(
            receipt,
            pr=pr,
            repository=repository,
            expected_run_id=expected_run_id,
            allow_legacy_terminal_lf=_legacy_terminal_lf_provenance(comment),
        )
    ]
    if _complete_merged_identity(pr):
        body = pr.get("body")
        if isinstance(body, str):
            valid_entries.extend(
                (dict(receipt), comment)
                for receipt, comment in entries
                if not any(
                    _matches_stored_body_digest(
                        body,
                        digest,
                        allow_legacy_terminal_lf=_legacy_terminal_lf_provenance(
                            comment
                        ),
                    )
                    for digest in (
                        receipt.get("body_sha256"),
                        receipt.get("neutralized_body_sha256"),
                    )
                )
                and not any(
                    not body.endswith("\n")
                    and "\r" not in body
                    and _raw_terminal_lf_digest(body) == digest
                    for digest in (
                        receipt.get("body_sha256"),
                        receipt.get("neutralized_body_sha256"),
                    )
                )
                and _valid_authority_receipt(
                    receipt,
                    pr=pr,
                    repository=repository,
                    expected_run_id=expected_run_id,
                    require_live_body=False,
                )
            )
    if not valid_entries:
        return None
    identities = {_canonical_digest(receipt) for receipt, _ in valid_entries}
    if len(identities) != 1:
        return None
    authority_receipt, authority_comment = valid_entries[-1]
    allow_legacy_terminal_lf = _legacy_terminal_lf_provenance(authority_comment)
    if (
        expected_repair_budget is not None
        and authority_receipt.get("repair_budget") != expected_repair_budget
    ):
        return None
    body = pr.get("body")
    if isinstance(body, str) and not any(
        _matches_stored_body_digest(
            body,
            digest,
            allow_legacy_terminal_lf=allow_legacy_terminal_lf,
        )
        for digest in (
            authority_receipt.get("body_sha256"),
            authority_receipt.get("neutralized_body_sha256"),
        )
    ):
        if resolve_verified_merge_phase(
            comments,
            authority_receipt=authority_receipt,
            pr=pr,
            allow_merged_body_drift=True,
        ) is None:
            return None
    return authority_receipt


def _resolve_merge_state(pr: Mapping[str, object]) -> str:
    """Classify a live PR snapshot as ``open``, ``merged``, or ``unknown``.

    Never guess from a partial or self-contradictory snapshot. A missing or
    unknown ``state``, or a combination such as ``state="open"`` with
    ``merged=True``, resolves to ``unknown`` so callers fail closed instead of
    reading an unestablished snapshot as a safe one.
    """

    state = pr.get("state")
    merged = pr.get("merged")
    merged_at = pr.get("merged_at")
    if state == "open" and merged is not True and merged_at is None:
        return "open"
    if (
        state == "closed"
        and merged is True
        and isinstance(merged_at, str)
        and merged_at
    ):
        return "merged"
    return "unknown"


def resolve_neutralized_body_restoration(
    comments: Sequence[Mapping[str, object]],
    *,
    pr: Mapping[str, object],
    repository: str,
    expected_run_id: str | None = None,
) -> dict[str, object] | None:
    """Surface a neutralized PR body that outlived its own merge attempt.

    A neutralized body is only valid while the exact head it was prepared for is
    still the head being merged. When a further commit lands, the exact-head
    authority receipt no longer resolves, yet the body keeps advertising
    ``Verified-Closing-Issues``; ``pr-contract`` then fails deterministically on
    every later head until the canonical body is restored.

    Return the bounded restoration state for that condition, or ``None`` when it
    does not hold or the evidence is not unambiguous. This is detection only: it
    performs no writes, does not grant merge authority, never relaxes the
    exact-head binding, and deliberately does not accept the pre-#4010 legacy
    terminal-LF digest form, so an ambiguous case fails closed instead of naming
    a restore target it cannot prove.
    """

    body = pr.get("body")
    head = pr.get("head")
    pr_number = pr.get("number")
    if (
        not isinstance(body, str)
        or not isinstance(head, Mapping)
        or not _positive_int(pr_number)
    ):
        return None
    head_sha = head.get("sha")
    if not isinstance(head_sha, str) or _SHA_PATTERN.fullmatch(head_sha) is None:
        return None
    if _resolve_merge_state(pr) != "open":
        # A merged PR is still inside its own attempt; the ``restored`` phase of
        # the merge sequence owns that body, not this recovery path. A snapshot
        # that cannot be positively established never names a restore target.
        return None
    neutralized = resolve_neutralized_issue_authority(body)
    if neutralized is None:
        return None
    if (
        resolve_verified_merge_authority_receipt(
            comments,
            pr=pr,
            repository=repository,
            expected_run_id=expected_run_id,
        )
        is not None
    ):
        return None
    # Any trusted authority evidence naming the live head means a merge for this
    # attempt may still be in flight, so an older head must never name a restore
    # target that could race it. Scan the raw comment text rather than only
    # well-formed receipts: a receipt with an extra key, a missing field, or two
    # fenced blocks in one comment is exactly the evidence a structural filter
    # would silently drop, and dropping it is what re-enables the race.
    if any(
        comment.get("author_association") in _TRUSTED_AUTHOR_ASSOCIATIONS
        and isinstance(comment.get("body"), str)
        and VERIFIED_MERGE_AUTHORITY_MARKER in str(comment["body"])
        and head_sha in str(comment["body"])
        for comment in comments
    ):
        return None
    stale: list[Mapping[str, object]] = []
    for receipt, _ in _comment_receipt_entries(
        comments, VERIFIED_MERGE_AUTHORITY_MARKER
    ):
        stored_head = receipt.get("head_sha")
        if stored_head == head_sha:
            return None
        body_digest = receipt.get("body_sha256")
        if (
            set(receipt) != _AUTHORITY_RECEIPT_FIELDS
            or receipt.get("contract") != VERIFIED_MERGE_AUTHORITY_CONTRACT
            or receipt.get("repository") != repository
            or receipt.get("pr_number") != pr_number
            or receipt.get("governing_issue") != neutralized.governing_issue
            or receipt.get("closing_issues") != list(neutralized.closing_issues)
            or not isinstance(stored_head, str)
            or _SHA_PATTERN.fullmatch(stored_head) is None
            or not isinstance(receipt.get("run_id"), str)
            or not receipt.get("run_id")
            or (
                expected_run_id is not None
                and receipt.get("run_id") != expected_run_id
            )
            or not isinstance(body_digest, str)
            or _DIGEST_PATTERN.fullmatch(body_digest) is None
            or body_digest == receipt.get("neutralized_body_sha256")
            or not _matches_stored_body_digest(
                body, receipt.get("neutralized_body_sha256")
            )
        ):
            continue
        stale.append(receipt)
    if not stale or len({receipt["body_sha256"] for receipt in stale}) != 1:
        return None
    # The restore target is load-bearing and is proven unique above. The
    # provenance fields below describe the last matching attempt in the supplied
    # comment order, which for the GitHub comments API is the most recent one.
    # A restore-then-re-neutralize loop legitimately leaves several attempts
    # matching the same target, so report the count rather than implying the
    # named attempt is the only one.
    authority_receipt = stale[-1]
    return {
        "closing_issues": list(neutralized.closing_issues),
        "contract": NEUTRALIZED_BODY_RESTORATION_CONTRACT,
        "governing_issue": neutralized.governing_issue,
        "head_sha": head_sha,
        "matching_attempts": len(stale),
        "neutralized_body_sha256": authority_receipt["neutralized_body_sha256"],
        "neutralized_head_sha": authority_receipt["head_sha"],
        "pr_number": pr_number,
        "reason": "neutralized-body-outlived-merge-attempt",
        "repository": repository,
        "restore_body_sha256": authority_receipt["body_sha256"],
        "run_id": authority_receipt["run_id"],
    }


def classify_neutralized_body_state(
    comments: Sequence[Mapping[str, object]],
    *,
    pr: Mapping[str, object],
    repository: str,
    expected_run_id: str | None = None,
) -> dict[str, object]:
    """Separate a positively safe body state from an indeterminate one.

    ``resolve_neutralized_body_restoration`` returns ``None`` both when there is
    nothing to restore and when the body is neutralized but no restore target can
    be proven. Those must not collapse into one "all clear" answer, so classify
    the live body into exactly one of:

    * ``no_restoration_required`` -- the body is canonical, or it is neutralized
      on a positively merged PR, or a trusted authority receipt still covers the
      current head, so the merge attempt that neutralized it is in flight.
    * ``restoration_required`` -- the body outlived its attempt and the durable
      receipt names the restore target.
    * ``ambiguous_neutralized_body`` -- the body is neutralized but no restore
      target can be proven, including when the live snapshot is incomplete or
      self-contradictory. Stop and recover evidence; never continue repair work
      on this answer.

    "Canonical" is decided by :func:`has_neutralized_closing_marker`, never by
    the strict resolver. The strict resolver also returns ``None`` for a body
    whose marker survives but whose grammar no longer parses -- a second
    ``Governing-Issue`` line, a duplicated marker, a deleted ``Refs`` line, a
    lone CR -- and that body is a live stranded neutralization, not a clean one.
    Reading it as safe would reproduce the very deadlock this module exists to
    stop.
    """

    body = pr.get("body")
    restoration = resolve_neutralized_body_restoration(
        comments,
        pr=pr,
        repository=repository,
        expected_run_id=expected_run_id,
    )
    merge_state = _resolve_merge_state(pr)
    if restoration is not None:
        status = "restoration_required"
    elif not isinstance(body, str):
        # No body to establish anything from.
        status = "ambiguous_neutralized_body"
    elif not has_neutralized_closing_marker(body):
        status = "no_restoration_required"
    elif merge_state == "merged" or (
        merge_state == "open"
        and resolve_verified_merge_authority_receipt(
            comments,
            pr=pr,
            repository=repository,
            expected_run_id=expected_run_id,
        )
        is not None
    ):
        status = "no_restoration_required"
    else:
        status = "ambiguous_neutralized_body"
    return {
        "restoration": restoration,
        "restoration_required": restoration is not None,
        "status": status,
    }


def restored_body_matches_authority(
    body: object,
    *,
    restoration: Mapping[str, object],
) -> bool:
    """Prove a candidate body is exactly the authenticated pre-neutralization body.

    Restoration is a repair of the mutable body only. It never rewrites the
    durable authority or phase receipt trail, and it is accepted only when the
    candidate reproduces the receipt's original body digest and its governing and
    closing identities.
    """

    if (
        not isinstance(body, str)
        or restoration.get("contract") != NEUTRALIZED_BODY_RESTORATION_CONTRACT
        or not _matches_stored_body_digest(
            body, restoration.get("restore_body_sha256")
        )
    ):
        return False
    authority = resolve_issue_authority(body)
    return bool(
        authority is not None
        and authority.governing_issue == restoration.get("governing_issue")
        and list(authority.closing_issues) == restoration.get("closing_issues")
    )


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
    authority_comment: Mapping[str, object] | None = None,
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
    allow_legacy_terminal_lf = bool(
        authority_comment is not None
        and _comment_authenticates_legacy_authority(
            authority_comment, authority_receipt
        )
    )
    if (
        not isinstance(body, str)
        or not isinstance(head, Mapping)
        or pr.get("number") != authority_receipt.get("pr_number")
        or head.get("sha") != authority_receipt.get("head_sha")
        or not _matches_stored_body_digest(
            body,
            expected_body_digest,
            allow_legacy_terminal_lf=allow_legacy_terminal_lf,
        )
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
        "body_sha256": expected_body_digest,
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
    allow_legacy_terminal_lf = _comments_authenticate_legacy_authority(
        comments, authority_receipt
    )
    if (
        not isinstance(current_body, str)
        or not any(
            _matches_stored_body_digest(
                current_body,
                digest,
                allow_legacy_terminal_lf=allow_legacy_terminal_lf,
            )
            for digest in (
                authority_receipt.get("body_sha256"),
                authority_receipt.get("neutralized_body_sha256"),
            )
        )
    ) and not (allow_merged_body_drift and _complete_merged_identity(pr)):
        return None
    return highest


def prepare_verified_merge(
    *,
    context: Mapping[str, object],
    pr: Mapping[str, object],
    live_closing_issues: object,
    merge_readiness: Mapping[str, object],
) -> dict[str, object]:
    """Build the exact, reversible merge plan for one verified PR head.

    ``merge_readiness`` is the caller's head-bound statement that this is the
    final head: CI and review are green and no further commits are anticipated.
    It is required and has no default, so neutralization cannot be reached by
    forgetting the precondition.
    """
    repository = context.get("repository")
    pr_number = context.get("pr_number")
    governing_issue = context.get("governing_issue")
    head_sha = context.get("head_sha")
    run_id = context.get("run_id")
    repair_budget = context.get("repair_budget")
    context_is_well_formed = (
        context.get("contract") != _CONTEXT_CONTRACT
        or not isinstance(repository, str)
        or not repository
        or not _positive_int(pr_number)
        or not isinstance(head_sha, str)
        or _SHA_PATTERN.fullmatch(head_sha) is None
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(repair_budget, Mapping)
    )
    if context_is_well_formed:
        raise ValueError("verified merge context is malformed")

    assert isinstance(repository, str)
    assert isinstance(pr_number, int)
    assert isinstance(head_sha, str)
    assert isinstance(run_id, str)
    assert isinstance(repair_budget, Mapping)

    if governing_issue is None:
        return _prepare_issue_free_reviewed_lane_merge(
            context=context,
            pr=pr,
            live_closing_issues=live_closing_issues,
            merge_readiness=merge_readiness,
        )
    if not _positive_int(governing_issue):
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

    # Last gate before the body stops carrying its own closing authority: this
    # exact head must be the final head. Everything above only proves the
    # snapshot is internally consistent.
    _assert_neutralization_precondition(merge_readiness, head_sha=head_sha)

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
        "fixed_commit_message": FIXED_VERIFIED_MERGE_COMMIT_MESSAGE,
        "fixed_commit_title": fixed_verified_merge_commit_title(pr_number),
        "neutralized_body": neutralized_body,
        "original_body": body,
    }


def _prepare_issue_free_reviewed_lane_merge(
    *,
    context: Mapping[str, object],
    pr: Mapping[str, object],
    live_closing_issues: object,
    merge_readiness: Mapping[str, object],
) -> dict[str, object]:
    """Bind an issue-free reviewed lane to its exact merge-ready PR head.

    Unlike issue-backed delivery, this path never neutralizes a body or creates
    issue authority.  The PR-thread receipt records the authenticated review
    lane before the ordinary exact-head merge owned by verification-and-closure.
    """

    repository = context["repository"]
    pr_number = context["pr_number"]
    head_sha = context["head_sha"]
    run_id = context["run_id"]
    assert isinstance(repository, str)
    assert isinstance(pr_number, int)
    assert isinstance(head_sha, str)
    assert isinstance(run_id, str)

    try:
        closing = _issue_tuple(
            context.get("closing_issues"), field="closing issues", allow_empty=True
        )
        supporting = _issue_tuple(
            context.get("supporting_issues"),
            field="supporting issues",
            allow_empty=True,
        )
        observed_closing = _live_closing_issues(
            live_closing_issues, repository=repository
        )
    except ValueError as exc:
        raise ValueError("issue-free reviewed lane authority is malformed") from exc
    if closing or supporting or observed_closing:
        raise ValueError("issue-free reviewed lane authority is malformed")

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
        or has_closing_issue_attempt(body)
        or resolve_issue_authority(body) is not None
        or resolve_final_review_rounds(body) != 1
        or not resolve_builderops_routing_status(
            body, has_issue_authority=False
        ).is_tier1_lane
    ):
        raise ValueError("issue-free reviewed lane PR snapshot is ineligible")

    _assert_neutralization_precondition(merge_readiness, head_sha=head_sha)
    receipt = {
        "body_sha256": _body_digest(body),
        "contract": ISSUE_FREE_REVIEWED_LANE_RECEIPT_CONTRACT,
        "head_sha": head_sha,
        "pr_number": pr_number,
        "repository": repository,
        "run_id": run_id,
    }
    receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    return {
        "fixed_commit_message": ISSUE_FREE_REVIEWED_LANE_MERGE_COMMIT_MESSAGE,
        "fixed_commit_title": fixed_verified_merge_commit_title(pr_number),
        "issue_free_receipt": receipt,
        "issue_free_receipt_comment": (
            f"{ISSUE_FREE_REVIEWED_LANE_RECEIPT_MARKER}\n```json\n{receipt_json}\n```"
        ),
        "original_body": body,
    }


def plan_issue_free_post_merge_reconciliation(
    *,
    pr_number: int,
    observed_closing_issues: Sequence[int],
    issue_evidence: Sequence[Mapping[str, object]],
) -> dict[str, list[int]]:
    """Reopen only issue closures GitHub attributes to an issue-free PR.

    An issue-free reviewed lane grants no closure authority.  A PR-body edit can
    race an exact-head merge without changing its SHA, so the closure workflow
    must compensate only the resulting closures GitHub identifies as caused by
    that exact PR.  Other closed Issues remain unresolved evidence, never
    candidates for inferred mutation.
    """

    observed = tuple(observed_closing_issues)
    if (
        not _positive_int(pr_number)
        or len(observed) > MAX_CLOSING_ISSUES
        or any(not _positive_int(item) for item in observed)
        or len(set(observed)) != len(observed)
    ):
        raise ValueError("issue-free post-merge reconciliation is malformed")

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
            raise ValueError("issue-free post-merge evidence is malformed")
        assert isinstance(number, int)
        by_number[number] = item

    if not set(observed).issubset(by_number):
        raise ValueError("issue-free post-merge evidence is incomplete")

    reopen: list[int] = []
    unresolved: list[int] = []
    for number in sorted(observed):
        evidence = by_number[number]
        if evidence["state"] != "closed":
            continue
        closed_by = evidence["closed_by_pull_requests"]
        assert isinstance(closed_by, list)
        if pr_number in closed_by:
            reopen.append(number)
        else:
            unresolved.append(number)
    return {
        "reopen_unauthorized": reopen,
        "unresolved_unauthorized_closures": unresolved,
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
