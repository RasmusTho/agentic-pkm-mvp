#!/usr/bin/env python3
"""Deterministic GitHub Known Defects registry intake.

The rolling registry Issue is a container, not an implementation contract. Each
confirmed deferred defect is one schema-marked Issue comment. Promotion creates
a normal bounded bug Issue through the bug-to-issue workflow, then this helper
links that Issue back to the registry entry.

This module is intentionally stdlib-only and uses GitHub's REST API through
``gh api``. It performs no LLM classification or drafting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_issue_readiness import (
    analyze_acceptance_criteria,
)

REGISTRY_LABEL = "state:known-defect"
REGISTRY_LABEL_COLOR = "C5DEF5"
REGISTRY_LABEL_DESCRIPTION = (
    "Rolling registry of confirmed deferred defects; never eligible for agent pickup"
)
REGISTRY_TITLE = "Known Defects Registry (rolling)"
REGISTRY_MARKER = "<!-- known-defects-registry:v1 -->"
REGISTRY_ROLLOUT_MIN_ISSUE = 4162
ENTRY_MARKER_TEMPLATE = (
    "<!-- known-defect-entry:v1 id={defect_id} phase={phase} -->"
)
PROMOTION_MARKER_TEMPLATE = (
    "<!-- known-defect-promotion:v1 id={defect_id} issue={issue_number} "
    "authority_sha256={authority_sha256} phase={phase} -->"
)
ENTRY_ID_RE = re.compile(r"^KD-[0-9A-F]{12}$")
ENTRY_MARKER_RE = re.compile(
    r"<!-- known-defect-entry:v1 id=(KD-[0-9A-F]{12}) "
    r"phase=(pending|final) -->"
)
PROMOTION_MARKER_RE = re.compile(
    r"<!-- known-defect-promotion:v1 id=(KD-[0-9A-F]{12}) issue=([1-9][0-9]*) "
    r"authority_sha256=([0-9a-f]{64}) phase=(pending|final) -->"
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
COMMENT_CREATED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
REPO_PATH_RE = re.compile(
    r"^(?:\.[A-Za-z0-9_-]+|[A-Za-z0-9_-]+)"
    r"(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_-]+$"
)
VAGUE_AUTHORITY_TOKENS = {
    "anchor",
    "heading",
    "later",
    "path",
    "section",
    "tbd",
    "todo",
    "unknown",
}
NORMAL_AGENT_STATES = {
    "agent:ready",
    "agent:blocked",
    "agent:needs-human",
}
PRIORITY_LABELS = {"prio:high", "prio:med", "prio:low"}
ALLOWED_LANE_LABELS = {"lane:governance"}
TRUSTED_AUTHOR_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
REQUIRED_ISSUE_SECTIONS = (
    "Context",
    "Scope",
    "Source Anchors",
    "SBS Impact",
    "Constraints",
    "Acceptance Criteria",
    "Out of Scope",
    "Suggested Validation",
    "Source Docs",
)
OPTIONAL_ISSUE_SECTION = "Applies learning (optional)"
REQUIRED_SBS_FIELDS = (
    "Primary subsystem",
    "Secondary subsystem(s)",
    "Write class",
    "Authority impact",
    "Persistence impact",
    "Derived/rebuildable impact",
    "Human knowledge impact",
    "Memory impact",
    "Retrieval/context impact",
    "Sync/deployment impact",
    "External boundary impact",
    "New or changed contract",
    "Owner-doc impact",
    "Transition debt impact",
    "Fitness rule impact",
)


class KnownDefectsError(RuntimeError):
    """A fail-closed registry contract violation."""


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _require_text(name: str, value: str, *, max_length: int = 4000) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise KnownDefectsError(f"{name} must be non-empty")
    if len(normalized) > max_length:
        raise KnownDefectsError(f"{name} exceeds {max_length} characters")
    return normalized


def _repo_from_remote() -> str:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise KnownDefectsError("cannot infer repository from git remote 'origin'")
    remote = completed.stdout.strip()
    patterns = (
        r"^https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group("repo")
    raise KnownDefectsError(f"unsupported GitHub remote: {remote!r}")


def _validate_repo(repo: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise KnownDefectsError("repo must have GitHub owner/name form")
    return repo


@dataclass(frozen=True)
class KnownDefect:
    repo: str
    source_pr: int
    source_sha: str
    review_url: str
    symptom: str
    evidence: str
    severity: str
    impact: str
    workaround: str
    trigger: str
    defect_key: str | None = None

    @classmethod
    def validated(
        cls,
        *,
        repo: str,
        source_pr: int,
        source_sha: str,
        review_url: str,
        symptom: str,
        evidence: str,
        severity: str,
        impact: str,
        workaround: str,
        trigger: str,
        defect_key: str | None = None,
    ) -> "KnownDefect":
        repo = _validate_repo(repo)
        if source_pr <= 0:
            raise KnownDefectsError("source_pr must be positive")
        if not SHA_RE.fullmatch(source_sha):
            raise KnownDefectsError("source_sha must be the full 40-character commit SHA")
        if severity != "P2":
            raise KnownDefectsError(
                "the deferred registry accepts only confirmed deferred P2 defects"
            )
        parsed = urlparse(review_url)
        expected_path = f"/{repo}/pull/{source_pr}"
        review_path = parsed.path.casefold()
        expected_review_path = expected_path.casefold()
        if (
            parsed.scheme != "https"
            or parsed.netloc.casefold() != "github.com"
            or not (
                review_path == expected_review_path
                or review_path.startswith(expected_review_path + "/")
            )
        ):
            raise KnownDefectsError(
                "review_url must link to the source PR or review thread on github.com"
            )
        canonical_review_url = parsed._replace(
            scheme="https",
            netloc="github.com",
        ).geturl()
        if re.fullmatch(r"https://github\.com/[^()\s]+", canonical_review_url) is None:
            raise KnownDefectsError(
                "review_url contains characters that cannot round-trip through "
                "the registry schema"
            )
        normalized_key = (
            _require_text("defect_key", defect_key, max_length=256)
            if defect_key is not None
            else None
        )
        return cls(
            repo=repo,
            source_pr=source_pr,
            source_sha=source_sha.lower(),
            review_url=canonical_review_url,
            symptom=_require_text("symptom", symptom),
            evidence=_require_text("evidence", evidence),
            severity=severity,
            impact=_require_text("impact", impact),
            workaround=_require_text("workaround", workaround),
            trigger=_require_text("trigger", trigger),
            defect_key=normalized_key,
        )

    @property
    def defect_id(self) -> str:
        if self.defect_key is not None:
            identity = {
                "repo": self.repo.casefold(),
                "defect_key": _normalize_text(self.defect_key),
            }
        else:
            identity = {
                "repo": self.repo.casefold(),
                "source_pr": self.source_pr,
                "source_sha": self.source_sha,
                "review_url": self.review_url,
                "symptom": _normalize_text(self.symptom),
            }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"KD-{digest[:12].upper()}"

    def render_entry(self, *, phase: str = "final") -> str:
        if phase not in {"pending", "final"}:
            raise KnownDefectsError("entry phase must be pending or final")
        return "\n".join(
            (
                ENTRY_MARKER_TEMPLATE.format(
                    defect_id=self.defect_id,
                    phase=phase,
                ),
                f"### {self.defect_id}",
                "",
                "- State: deferred; not an implementation contract",
                (
                    f"- Source: PR #{self.source_pr} @ `{self.source_sha}` "
                    f"([review evidence]({self.review_url}))"
                ),
                f"- Reproducible symptom: {self.symptom}",
                f"- Evidence: {self.evidence}",
                f"- Impact/severity: {self.severity} — {self.impact}",
                f"- Workaround: {self.workaround}",
                f"- Re-evaluation/promotion trigger: {self.trigger}",
            )
        )


class RegistryGateway(Protocol):
    def ensure_registry_label(self) -> None: ...

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]: ...

    def refresh_registry_identities(self) -> None: ...

    def get_issue(self, number: int) -> dict[str, Any]: ...

    def create_registry_issue(self) -> dict[str, Any]: ...

    def lock_registry_issue(self, issue_number: int) -> None: ...

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]: ...

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]: ...

    def delete_comment(self, comment_id: int) -> None: ...

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]: ...


class GhRegistryGateway:
    """Small REST-only GitHub gateway used by the deterministic CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = _validate_repo(repo)
        self._registry_identity_numbers: set[int] | None = None

    def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        command = ["gh", "api", "-X", method, endpoint]
        input_text = None
        if payload is not None:
            command.extend(["--input", "-"])
            input_text = json.dumps(payload, sort_keys=True)
        completed = subprocess.run(
            command,
            input=input_text,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise KnownDefectsError(
                f"GitHub REST request failed ({method} {endpoint}): {message}"
            )
        if not completed.stdout.strip():
            return None
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise KnownDefectsError(
                f"GitHub REST request returned invalid JSON ({method} {endpoint})"
            ) from exc

    def _list_paginated(self, endpoint: str) -> list[dict[str, Any]]:
        separator = "&" if "?" in endpoint else "?"
        rows: list[dict[str, Any]] = []
        for page in range(1, 21):
            batch = self._request("GET", f"{endpoint}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise KnownDefectsError(f"expected list response from {endpoint}")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise KnownDefectsError(f"pagination bound exceeded for {endpoint}")

    def refresh_registry_identities(self) -> None:
        numbers = set(self._registry_identity_numbers or ())
        endpoint = (
            f"repos/{self.repo}/issues?state=all"
            "&sort=created&direction=desc"
        )
        separator = "&"
        for page in range(1, 101):
            batch = self._request(
                "GET",
                f"{endpoint}{separator}per_page=100&page={page}",
            )
            if not isinstance(batch, list):
                raise KnownDefectsError(
                    "expected list response from authoritative registry discovery"
                )
            reached_rollout_boundary = False
            for issue in batch:
                if not isinstance(issue, dict):
                    raise KnownDefectsError(
                        "authoritative registry discovery returned a malformed Issue"
                    )
                number = int(issue.get("number") or 0)
                if number <= 0:
                    raise KnownDefectsError(
                        "authoritative registry discovery returned an invalid "
                        "Issue number"
                    )
                if number < REGISTRY_ROLLOUT_MIN_ISSUE:
                    reached_rollout_boundary = True
                    continue
                labels = _label_names(issue)
                body = str(issue.get("body") or "")
                if (
                    "pull_request" not in issue
                    and (
                        REGISTRY_LABEL in labels
                        or issue.get("title") == REGISTRY_TITLE
                        or body.startswith(f"{REGISTRY_MARKER}\n")
                    )
                ):
                    numbers.add(number)
            if reached_rollout_boundary or len(batch) < 100:
                self._registry_identity_numbers = numbers
                return
        raise KnownDefectsError(
            "pagination bound exceeded for authoritative registry discovery"
        )

    def ensure_registry_label(self) -> None:
        encoded = quote(REGISTRY_LABEL, safe="")
        try:
            self._request("GET", f"repos/{self.repo}/labels/{encoded}")
            return
        except KnownDefectsError as exc:
            if "HTTP 404" not in str(exc):
                raise
        try:
            self._request(
                "POST",
                f"repos/{self.repo}/labels",
                {
                    "name": REGISTRY_LABEL,
                    "color": REGISTRY_LABEL_COLOR,
                    "description": REGISTRY_LABEL_DESCRIPTION,
                },
            )
        except KnownDefectsError as exc:
            # A concurrent creator may have won the race. Read back once.
            if "HTTP 422" not in str(exc):
                raise
            self._request("GET", f"repos/{self.repo}/labels/{encoded}")

    def list_registry_issues(self, state: str) -> list[dict[str, Any]]:
        if state not in {"open", "closed", "all"}:
            raise KnownDefectsError(f"unsupported issue state: {state}")
        encoded_label = quote(REGISTRY_LABEL, safe="")
        labeled_issues = self._list_paginated(
            f"repos/{self.repo}/issues?state={state}&labels={encoded_label}"
        )
        issues_by_number = {
            int(issue["number"]): issue
            for issue in labeled_issues
            if "pull_request" not in issue
        }
        if self._registry_identity_numbers is None:
            self._registry_identity_numbers = set()
        self._registry_identity_numbers.update(issues_by_number)
        for number in self._registry_identity_numbers:
            if number not in issues_by_number:
                issues_by_number[number] = self.get_issue(number)
        return [
            issue
            for issue in issues_by_number.values()
            if state == "all"
            or str(issue.get("state", "")).lower() == state
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = self._request("GET", f"repos/{self.repo}/issues/{number}")
        if "pull_request" in issue:
            raise KnownDefectsError(f"#{number} is a pull request, not an Issue")
        return issue

    def create_registry_issue(self) -> dict[str, Any]:
        issue = self._request(
            "POST",
            f"repos/{self.repo}/issues",
            {
                "title": REGISTRY_TITLE,
                "labels": ["type:bug", REGISTRY_LABEL],
                "body": render_registry_body(),
            },
        )
        if self._registry_identity_numbers is not None:
            self._registry_identity_numbers.add(int(issue["number"]))
        return issue

    def lock_registry_issue(self, issue_number: int) -> None:
        self._request("PUT", f"repos/{self.repo}/issues/{issue_number}/lock")

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]:
        return self._list_paginated(f"repos/{self.repo}/issues/{issue_number}/comments")

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"repos/{self.repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    def delete_comment(self, comment_id: int) -> None:
        self._request(
            "DELETE",
            f"repos/{self.repo}/issues/comments/{comment_id}",
        )

    def update_comment(self, comment_id: int, body: str) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"repos/{self.repo}/issues/comments/{comment_id}",
            {"body": body},
        )


def render_registry_body() -> str:
    return "\n".join(
        (
            REGISTRY_MARKER,
            "# Known Defects Registry",
            "",
            "This rolling Issue is the canonical low-overhead registry for confirmed "
            "deferred P2 defects.",
            "",
            "- Each schema-marked comment is one defect entry.",
            "- This Issue is locked, carries no `agent:*` state, is not an "
            "implementation contract, and must never receive `agent:ready`.",
            "- Maintainability suggestions and unproven observations do not belong here.",
            "- Promotion creates a normal bounded `type:bug` Issue with the canonical "
            "contract, acceptance criteria, `Verify:` targets, and truthful agent state.",
        )
    )


def _label_names(issue: dict[str, Any]) -> set[str]:
    return {
        str(label.get("name") if isinstance(label, dict) else label)
        for label in issue.get("labels", [])
    }


def _validate_registry_issue(
    issue: dict[str, Any],
    *,
    require_open: bool,
    require_locked: bool = True,
) -> None:
    if issue.get("title") != REGISTRY_TITLE:
        raise KnownDefectsError(
            f"Issue #{issue.get('number')} has a malformed Known Defects registry title"
        )
    if (issue.get("body") or "") != render_registry_body():
        raise KnownDefectsError(
            f"Issue #{issue.get('number')} has a malformed Known Defects registry body"
        )
    labels = _label_names(issue)
    required_labels = {"type:bug", REGISTRY_LABEL}
    if not required_labels <= labels:
        missing = ", ".join(sorted(required_labels - labels))
        raise KnownDefectsError(
            f"Issue #{issue.get('number')} lacks canonical label(s): {missing}"
        )
    agent_labels = sorted(label for label in labels if label.startswith("agent:"))
    if agent_labels:
        raise KnownDefectsError(
            f"Issue #{issue.get('number')} must carry no agent state: "
            + ", ".join(agent_labels)
        )
    unexpected_labels = sorted(labels - required_labels)
    if unexpected_labels:
        raise KnownDefectsError(
            f"Issue #{issue.get('number')} has unexpected registry label(s): "
            + ", ".join(unexpected_labels)
        )
    if require_locked and issue.get("locked") is not True:
        raise KnownDefectsError(
            f"registry Issue #{issue.get('number')} must be locked before intake"
        )
    if require_open and str(issue.get("state", "")).lower() != "open":
        raise KnownDefectsError(f"registry Issue #{issue.get('number')} is not open")


def _entry_marker_from_comment(body: str) -> tuple[str, str] | None:
    lines = body.splitlines()
    if not lines or not lines[0].startswith("<!-- known-defect-entry:"):
        return None
    marker = ENTRY_MARKER_RE.fullmatch(lines[0])
    if marker is None:
        raise KnownDefectsError("malformed known-defect entry marker")
    defect_id, phase = marker.groups()
    if len(lines) != 10 or lines[1] != f"### {defect_id}" or lines[2] != "":
        raise KnownDefectsError(f"malformed known-defect entry shape for {defect_id}")
    if lines[3] != "- State: deferred; not an implementation contract":
        raise KnownDefectsError(
            f"malformed known-defect entry {defect_id}: invalid state"
        )
    source = re.fullmatch(
        (
            r"- Source: PR #([1-9][0-9]*) @ `([0-9a-f]{40})` "
            r"\(\[review evidence\]\((https://github\.com/[^()\s]+)\)\)"
        ),
        lines[4],
    )
    if source is None:
        raise KnownDefectsError(
            f"malformed known-defect entry {defect_id}: invalid source"
        )
    source_pr = int(source.group(1))
    review_url = urlparse(source.group(3))
    review_path = review_url.path.casefold()
    if (
        review_url.scheme != "https"
        or review_url.netloc.casefold() != "github.com"
        or re.fullmatch(
            rf"/[^/]+/[^/]+/pull/{source_pr}(?:/.*)?",
            review_path,
        )
        is None
    ):
        raise KnownDefectsError(
            f"malformed known-defect entry {defect_id}: review URL does not match PR"
        )
    value_fields = (
        (lines[5], "- Reproducible symptom: ", "symptom"),
        (lines[6], "- Evidence: ", "evidence"),
        (lines[8], "- Workaround: ", "workaround"),
        (lines[9], "- Re-evaluation/promotion trigger: ", "trigger"),
    )
    for line, prefix, field in value_fields:
        if not line.startswith(prefix):
            raise KnownDefectsError(
                f"malformed known-defect entry {defect_id}: invalid {field}"
            )
        value = line.removeprefix(prefix)
        if not value or value != " ".join(value.split()):
            raise KnownDefectsError(
                f"malformed known-defect entry {defect_id}: invalid {field}"
            )
    impact = re.fullmatch(r"- Impact/severity: (P2) — (.+)", lines[7])
    if (
        impact is None
        or impact.group(2) != " ".join(impact.group(2).split())
    ):
        raise KnownDefectsError(
            f"malformed known-defect entry {defect_id}: invalid impact/severity"
        )
    return defect_id, phase


def _entry_id_from_comment(body: str) -> str | None:
    parsed = _entry_marker_from_comment(body)
    if parsed is None or parsed[1] != "final":
        return None
    return parsed[0]


def _promotion_from_comment(body: str) -> tuple[str, int, str, str] | None:
    lines = body.splitlines()
    if not lines or not lines[0].startswith("<!-- known-defect-promotion:"):
        return None
    marker = PROMOTION_MARKER_RE.fullmatch(lines[0])
    if marker is None:
        raise KnownDefectsError("malformed known-defect promotion marker")
    defect_id, issue_number_text, authority_sha256, phase = marker.groups()
    issue_number = int(issue_number_text)
    expected_receipt = (
        f"Promotion receipt: {defect_id} is now tracked for implementation by "
        f"#{issue_number}."
    )
    expected_authority = (
        "The bounded bug Issue owns scope, acceptance criteria, Verify targets, "
        "and execution state."
    )
    expected_digest = (
        f"Validated target snapshot: sha256:{authority_sha256}."
    )
    if (
        len(lines) != 4
        or lines[1] != expected_receipt
        or lines[2] != expected_digest
        or lines[3] != expected_authority
    ):
        raise KnownDefectsError(
            f"malformed known-defect promotion shape for {defect_id}"
        )
    return defect_id, issue_number, authority_sha256, phase


def _validate_schema_comment(comment: dict[str, Any]) -> None:
    body = comment.get("body") or ""
    lines = body.splitlines()
    if not lines:
        return
    first_line = lines[0]
    is_entry = first_line.startswith("<!-- known-defect-entry:")
    is_promotion = first_line.startswith("<!-- known-defect-promotion:")
    if not is_entry and not is_promotion:
        return
    association = str(comment.get("author_association") or "").upper()
    if association not in TRUSTED_AUTHOR_ASSOCIATIONS:
        raise KnownDefectsError(
            f"schema comment #{comment.get('id')} has untrusted author association "
            f"{association or '<missing>'}"
        )
    _comment_reservation_order(comment)
    if is_entry:
        _entry_marker_from_comment(body)
    else:
        _promotion_from_comment(body)


def _comment_reservation_order(comment: dict[str, Any]) -> tuple[str, int]:
    created_at = str(comment.get("created_at") or "")
    comment_id = int(comment.get("id") or 0)
    if COMMENT_CREATED_AT_RE.fullmatch(created_at) is None or comment_id <= 0:
        raise KnownDefectsError(
            f"schema comment #{comment_id or '<missing>'} lacks canonical "
            "creation authority"
        )
    return created_at, comment_id


def _registry_inventory(
    gateway: RegistryGateway,
    *,
    recover_bootstrap: bool,
    allow_multiple_open: bool = False,
) -> list[dict[str, Any]]:
    issues = sorted(
        gateway.list_registry_issues("all"),
        key=lambda item: int(item["number"]),
    )
    for issue in issues:
        _validate_registry_issue(
            issue,
            require_open=False,
            require_locked=False,
        )
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if len(open_registries) > 1 and not allow_multiple_open:
        numbers = ", ".join(f"#{item['number']}" for item in open_registries)
        raise KnownDefectsError(f"multiple open registries found ({numbers})")
    if (
        recover_bootstrap
        and len(open_registries) == 1
        and open_registries[0].get("locked") is not True
    ):
        issue_number = int(open_registries[0]["number"])
        gateway.lock_registry_issue(issue_number)
        refreshed = gateway.get_issue(issue_number)
        _validate_registry_issue(refreshed, require_open=True)
        issues = [
            refreshed if int(issue["number"]) == issue_number else issue
            for issue in issues
        ]
    for issue in issues:
        _validate_registry_issue(issue, require_open=False)
    return issues


def _inventory_comments(
    gateway: RegistryGateway,
    issue_number: int,
) -> list[dict[str, Any]]:
    comments = sorted(
        gateway.list_comments(issue_number),
        key=lambda item: int(item.get("id") or 0),
    )
    for comment in comments:
        _validate_schema_comment(comment)
    return comments


def _registry_candidates_for_read(
    gateway: RegistryGateway,
) -> list[dict[str, Any]]:
    issues = sorted(
        gateway.list_registry_issues("all"),
        key=lambda item: int(item["number"]),
    )
    for issue in issues:
        labels = _label_names(issue)
        body = issue.get("body") or ""
        if (
            REGISTRY_LABEL not in labels
            or "type:bug" not in labels
            or issue.get("title") != REGISTRY_TITLE
            or not body.startswith(f"{REGISTRY_MARKER}\n")
        ):
            raise KnownDefectsError(
                f"Issue #{issue.get('number')} is not a readable registry container"
            )
    return issues


def _require_expected_single_open_registry(
    gateway: RegistryGateway,
    expected_issue_number: int,
) -> dict[str, Any]:
    issues = _registry_inventory(gateway, recover_bootstrap=False)
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if len(open_registries) != 1:
        rendered = ", ".join(f"#{issue['number']}" for issue in open_registries)
        raise KnownDefectsError(
            f"expected one open registry, found: {rendered or '<none>'}"
        )
    selected = open_registries[0]
    if int(selected["number"]) != expected_issue_number:
        raise KnownDefectsError(
            f"registry authority moved from #{expected_issue_number} "
            f"to #{selected['number']}"
        )
    return selected


def _registry_comment_locations(
    gateway: RegistryGateway,
    *,
    recover_bootstrap: bool,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    locations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    issues = (
        _registry_inventory(
            gateway,
            recover_bootstrap=True,
            allow_multiple_open=True,
        )
        if recover_bootstrap
        else _registry_candidates_for_read(gateway)
    )
    for issue in issues:
        locations.extend(
            (issue, comment)
            for comment in _inventory_comments(gateway, int(issue["number"]))
        )
    return locations


def _canonical_promotion_reservation(
    gateway: RegistryGateway,
    defect_id: str,
) -> tuple[int, str, str, int, dict[str, Any]] | None:
    locations = _registry_comment_locations(
        gateway,
        recover_bootstrap=False,
    )
    reservations: list[
        tuple[int, int, int, str, str, dict[str, Any]]
    ] = []
    for registry, comment in locations:
        parsed = _promotion_from_comment(comment.get("body") or "")
        if parsed is None or parsed[0] != defect_id:
            continue
        reservations.append(
            (
                int(comment.get("id") or 0),
                int(registry["number"]),
                parsed[1],
                parsed[2],
                parsed[3],
                comment,
            )
        )
    if not reservations:
        return None
    reservations.sort(
        key=lambda item: _comment_reservation_order(item[5])
    )
    (
        _comment_id,
        registry_number,
        issue_number,
        authority_sha256,
        phase,
        evidence_comment,
    ) = reservations[0]
    return (
        issue_number,
        authority_sha256,
        phase,
        registry_number,
        evidence_comment,
    )


def _single_committed_promotion(
    gateway: RegistryGateway,
    defect_id: str,
) -> tuple[int, str, int, dict[str, Any]] | None:
    reservation = _canonical_promotion_reservation(gateway, defect_id)
    if reservation is None or reservation[2] != "final":
        return None
    issue_number, authority_sha256, _phase, registry_number, comment = (
        reservation
    )
    return issue_number, authority_sha256, registry_number, comment


def _find_entry(
    gateway: RegistryGateway,
    defect_id: str,
    *,
    recover_bootstrap: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    issues = (
        _registry_inventory(
            gateway,
            recover_bootstrap=True,
            allow_multiple_open=True,
        )
        if recover_bootstrap
        else _registry_candidates_for_read(gateway)
    )
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for issue in issues:
        for comment in _inventory_comments(gateway, int(issue["number"])):
            parsed = _entry_marker_from_comment(comment.get("body") or "")
            if parsed is not None and parsed[0] == defect_id:
                found.append((issue, comment))
    if not found:
        return None
    found.sort(key=lambda item: _comment_reservation_order(item[1]))
    canonical = found[0]
    parsed = _entry_marker_from_comment(canonical[1].get("body") or "")
    if parsed is None or parsed[1] != "final":
        return None
    return canonical


def _select_registry(
    gateway: RegistryGateway,
    registry_issue: int | None,
) -> dict[str, Any]:
    issues = _registry_inventory(gateway, recover_bootstrap=True)
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if registry_issue is not None:
        selected = [
            issue
            for issue in open_registries
            if int(issue["number"]) == registry_issue
        ]
        if len(selected) != 1:
            raise KnownDefectsError(
                f"--registry-issue #{registry_issue} is not the single open registry"
            )
        return selected[0]
    if open_registries:
        return open_registries[0]
    gateway.refresh_registry_identities()
    issues = _registry_inventory(gateway, recover_bootstrap=True)
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if open_registries:
        return open_registries[0]
    created = gateway.create_registry_issue()
    gateway.lock_registry_issue(int(created["number"]))
    issues = _registry_inventory(gateway, recover_bootstrap=True)
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if len(open_registries) != 1:
        numbers = ", ".join(f"#{item['number']}" for item in open_registries)
        raise KnownDefectsError(
            f"registry creation race detected; reconcile open registries: {numbers}"
        )
    selected = open_registries[0]
    if int(selected["number"]) != int(created["number"]):
        raise KnownDefectsError(
            "registry creation response does not match the canonical open registry"
        )
    _inventory_comments(gateway, int(selected["number"]))
    return selected


def _compensate_comment(
    gateway: RegistryGateway,
    issue_number: int,
    comment: dict[str, Any],
) -> None:
    comment_id = int(comment.get("id") or 0)
    if comment_id <= 0:
        raise KnownDefectsError(
            "cannot compensate a stale registry append without a comment id"
        )
    delete_error: KnownDefectsError | None = None
    try:
        gateway.delete_comment(comment_id)
    except KnownDefectsError as exc:
        delete_error = exc
    remaining_ids = {
        int(item.get("id") or 0)
        for item in gateway.list_comments(issue_number)
    }
    if comment_id in remaining_ids:
        if delete_error is not None:
            raise delete_error
        raise KnownDefectsError(
            f"failed to compensate stale registry comment #{comment_id}"
        )


def _closed_canonical_registry(issue: dict[str, Any]) -> bool:
    try:
        _validate_registry_issue(issue, require_open=False)
    except KnownDefectsError:
        return False
    return str(issue.get("state", "")).lower() == "closed"


def _entry_comments(
    gateway: RegistryGateway,
    issue_number: int,
    defect_id: str,
    *,
    phase: str | None = None,
) -> list[dict[str, Any]]:
    matches = []
    for comment in _inventory_comments(gateway, issue_number):
        parsed = _entry_marker_from_comment(comment.get("body") or "")
        if parsed is None or parsed[0] != defect_id:
            continue
        if phase is None or parsed[1] == phase:
            matches.append(comment)
    return matches


def _finalize_pending_entry(
    gateway: RegistryGateway,
    issue: dict[str, Any],
    comment: dict[str, Any],
) -> dict[str, Any]:
    issue_number = int(issue["number"])
    comment_id = int(comment.get("id") or 0)
    if comment_id <= 0:
        raise KnownDefectsError("entry finalization requires a comment id")
    pending_body = comment.get("body") or ""
    parsed = _entry_marker_from_comment(pending_body)
    if parsed is None or parsed[1] != "pending":
        raise KnownDefectsError("entry finalization requires a pending schema comment")
    final_body = pending_body.replace(" phase=pending -->", " phase=final -->", 1)
    # This PATCH commits the already-ordered reservation. It has no cross-Issue
    # predicate: the trusted reservation id, not a stale multi-resource read, wins.
    try:
        gateway.update_comment(comment_id, final_body)
    except KnownDefectsError:
        final_comments = _entry_comments(
            gateway,
            issue_number,
            parsed[0],
            phase="final",
        )
        if not any(
            int(item.get("id") or 0) == comment_id
            for item in final_comments
        ):
            raise
    final_comments = _entry_comments(
        gateway,
        issue_number,
        parsed[0],
        phase="final",
    )
    exact_final = [
        item
        for item in final_comments
        if int(item.get("id") or 0) == comment_id
    ]
    if len(exact_final) != 1:
        raise KnownDefectsError(
            f"entry finalization failed for {parsed[0]}"
        )
    return exact_final[0]


def _reconcile_pending_entries(
    gateway: RegistryGateway,
    defect_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    inventory_error: KnownDefectsError | None = None
    try:
        strict_issues = _registry_inventory(
            gateway,
            recover_bootstrap=True,
        )
        locations = [
            (issue, comment)
            for issue in strict_issues
            for comment in _inventory_comments(
                gateway,
                int(issue["number"]),
            )
        ]
    except KnownDefectsError as exc:
        inventory_error = exc
        locations = _registry_comment_locations(
            gateway,
            recover_bootstrap=False,
        )
    reservations = [
        (issue, comment)
        for issue, comment in locations
        if (
            (parsed := _entry_marker_from_comment(comment.get("body") or ""))
            is not None
            and parsed[0] == defect_id
        )
    ]
    if not reservations:
        if inventory_error is not None:
            raise inventory_error
        return None
    reservations.sort(key=lambda item: _comment_reservation_order(item[1]))
    canonical_issue, canonical_comment = reservations[0]
    canonical_marker = _entry_marker_from_comment(
        canonical_comment.get("body") or ""
    )
    if canonical_marker is None:
        raise KnownDefectsError("canonical entry reservation became malformed")
    if canonical_marker[1] == "final" and inventory_error is not None:
        raise inventory_error
    for issue, comment in reservations[1:]:
        marker = _entry_marker_from_comment(comment.get("body") or "")
        if marker is None or marker[1] != "pending":
            continue
        if int(comment.get("id") or 0) == int(
            canonical_comment.get("id") or 0
        ):
            continue
        _compensate_comment(gateway, int(issue["number"]), comment)
    if canonical_marker[1] == "final":
        return canonical_issue, canonical_comment
    finalized = _finalize_pending_entry(
        gateway,
        canonical_issue,
        canonical_comment,
    )
    return canonical_issue, finalized


def _intake_defect(
    defect: KnownDefect,
    gateway: RegistryGateway,
    *,
    registry_issue: int | None = None,
    allow_lifecycle_retry: bool,
) -> dict[str, Any]:
    gateway.ensure_registry_label()
    reconciled = _reconcile_pending_entries(gateway, defect.defect_id)
    if reconciled is not None:
        issue, comment = reconciled
        return {
            "schema": "known-defect-receipt.v1",
            "status": "duplicate",
            "defect_id": defect.defect_id,
            "registry_issue": int(issue["number"]),
            "url": comment.get("html_url"),
        }
    existing = _find_entry(
        gateway,
        defect.defect_id,
        recover_bootstrap=True,
    )
    if existing is not None:
        issue, comment = existing
        return {
            "schema": "known-defect-receipt.v1",
            "status": "duplicate",
            "defect_id": defect.defect_id,
            "registry_issue": int(issue["number"]),
            "url": comment.get("html_url"),
        }
    issue = _select_registry(gateway, registry_issue)
    existing = _find_entry(
        gateway,
        defect.defect_id,
        recover_bootstrap=True,
    )
    if existing is not None:
        existing_issue, comment = existing
        return {
            "schema": "known-defect-receipt.v1",
            "status": "duplicate",
            "defect_id": defect.defect_id,
            "registry_issue": int(existing_issue["number"]),
            "url": comment.get("html_url"),
        }
    reconciled = _reconcile_pending_entries(gateway, defect.defect_id)
    if reconciled is not None:
        pending_issue, comment = reconciled
        return {
            "schema": "known-defect-receipt.v1",
            "status": "duplicate",
            "defect_id": defect.defect_id,
            "registry_issue": int(pending_issue["number"]),
            "url": comment.get("html_url"),
        }
    _inventory_comments(gateway, int(issue["number"]))
    fresh_issue = gateway.get_issue(int(issue["number"]))
    try:
        _validate_registry_issue(fresh_issue, require_open=True)
    except KnownDefectsError:
        if (
            registry_issue is None
            and allow_lifecycle_retry
            and _closed_canonical_registry(fresh_issue)
        ):
            return _intake_defect(
                defect,
                gateway,
                registry_issue=None,
                allow_lifecycle_retry=False,
            )
        raise
    gateway.refresh_registry_identities()
    try:
        _require_expected_single_open_registry(
            gateway,
            int(issue["number"]),
        )
    except KnownDefectsError:
        current_issue = gateway.get_issue(int(issue["number"]))
        if (
            registry_issue is None
            and allow_lifecycle_retry
            and _closed_canonical_registry(current_issue)
        ):
            return _intake_defect(
                defect,
                gateway,
                registry_issue=None,
                allow_lifecycle_retry=False,
            )
        raise
    try:
        comment = gateway.add_comment(
            int(issue["number"]),
            defect.render_entry(phase="pending"),
        )
    except KnownDefectsError:
        reconciled = _reconcile_pending_entries(gateway, defect.defect_id)
        if reconciled is not None:
            reconciled_issue, canonical_comment = reconciled
            return {
                "schema": "known-defect-receipt.v1",
                "status": "created",
                "defect_id": defect.defect_id,
                "registry_issue": int(reconciled_issue["number"]),
                "url": canonical_comment.get("html_url"),
            }
        current_issue = gateway.get_issue(int(issue["number"]))
        if (
            registry_issue is None
            and allow_lifecycle_retry
            and _closed_canonical_registry(current_issue)
        ):
            return _intake_defect(
                defect,
                gateway,
                registry_issue=None,
                allow_lifecycle_retry=False,
            )
        raise
    reconciled = _reconcile_pending_entries(gateway, defect.defect_id)
    if reconciled is None:
        raise KnownDefectsError(
            f"entry reservation disappeared for {defect.defect_id}"
        )
    reconciled_issue, finalized = reconciled
    created = int(finalized.get("id") or 0) == int(comment.get("id") or 0)
    return {
        "schema": "known-defect-receipt.v1",
        "status": "created" if created else "duplicate",
        "defect_id": defect.defect_id,
        "registry_issue": int(reconciled_issue["number"]),
        "url": finalized.get("html_url"),
    }


def intake_defect(
    defect: KnownDefect,
    gateway: RegistryGateway,
    *,
    registry_issue: int | None = None,
) -> dict[str, Any]:
    gateway.refresh_registry_identities()
    return _intake_defect(
        defect,
        gateway,
        registry_issue=registry_issue,
        allow_lifecycle_retry=True,
    )


def lookup_defect(
    defect_id: str,
    gateway: RegistryGateway,
) -> dict[str, Any]:
    if not ENTRY_ID_RE.fullmatch(defect_id):
        raise KnownDefectsError("defect_id must have form KD-<12 uppercase hex>")
    gateway.refresh_registry_identities()
    found = _find_entry(gateway, defect_id)
    if found is None:
        return {
            "schema": "known-defect-receipt.v1",
            "status": "not_found",
            "defect_id": defect_id,
        }
    issue, comment = found
    promotion = _single_committed_promotion(gateway, defect_id)
    promotion_issue = promotion[0] if promotion is not None else None
    return {
        "schema": "known-defect-receipt.v1",
        "status": "promoted" if promotion_issue is not None else "deferred",
        "defect_id": defect_id,
        "registry_issue": int(issue["number"]),
        "promotion_issue": promotion_issue,
        "url": comment.get("html_url"),
    }


def _top_level_sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##[ \t]+(.+?)[ \t]*$", body, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        if title in sections:
            raise KnownDefectsError(
                f"promotion target repeats canonical section: {title}"
            )
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[title] = body[start:end].strip()
    return sections


def _has_concrete_section_content(value: str) -> bool:
    if not value.strip():
        return False
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        content = re.sub(
            r"^[-*]\s+(?:\[[ xX]\]\s+)?",
            "",
            line,
        ).strip().strip("`").strip()
        if not content or re.search(r"<[^>]+>", content):
            continue
        if content.casefold() in {"tbd", "todo", "n/a"}:
            continue
        return True
    return False


def _is_durable_repo_path(value: str) -> bool:
    path = value.strip()
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    try:
        (REPO_ROOT / path).resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return False
    return (
        REPO_PATH_RE.fullmatch(path) is not None
        and re.search(r"<[^>]+>", path) is None
        and not any(
            (
                segment.casefold() in VAGUE_AUTHORITY_TOKENS
                or Path(segment).stem.casefold() in VAGUE_AUTHORITY_TOKENS
            )
            for segment in Path(path).parts
        )
    )


def _is_durable_anchor(value: str) -> bool:
    anchor = " ".join(value.split())
    return (
        bool(anchor)
        and re.search(r"<[^>]+>", anchor) is None
        and anchor.casefold() not in VAGUE_AUTHORITY_TOKENS
    )


def _acceptance_items(section: str) -> list[str]:
    starts = list(
        re.finditer(r"(?m)^\s*[-*]\s+\[[ xX]\]\s+.+$", section)
    )
    return [
        section[
            match.start():
            starts[index + 1].start() if index + 1 < len(starts) else len(section)
        ].strip()
        for index, match in enumerate(starts)
    ]


def _has_resolvable_verify_target(item: str) -> bool:
    for match in re.finditer(r"(?im)(?:^|\b)Verify:\s*(.+)$", item):
        raw_target = match.group(1).strip()
        target = raw_target.strip("`").strip()
        if re.fullmatch(
            r"tests/[A-Za-z0-9_./-]+::[A-Za-z0-9_.\[\]-]+",
            target,
        ) and _is_durable_repo_path(target.split("::", 1)[0]):
            return True
        doc_writeback = re.fullmatch(
            r"doc writeback at `((?:docs|\.codex)/[^`]+) :: ([^`]+)`",
            raw_target,
            re.IGNORECASE,
        )
        if (
            doc_writeback is not None
            and _is_durable_repo_path(doc_writeback.group(1))
            and _is_durable_anchor(doc_writeback.group(2))
        ):
            return True
        roadmap_diff = re.fullmatch(
            r"roadmap diff:\s+`(docs/[^`]+) :: ([^`]+)`",
            target,
            re.IGNORECASE,
        )
        if (
            roadmap_diff is not None
            and _is_durable_repo_path(roadmap_diff.group(1))
            and _is_durable_anchor(roadmap_diff.group(2))
        ):
            return True
        runtime_receipt = re.fullmatch(
            (
                r"runtime receipt:\s+"
                r"([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)\.v[1-9][0-9]*"
            ),
            target,
            re.IGNORECASE,
        )
        if runtime_receipt is not None and not any(
            token.casefold() in VAGUE_AUTHORITY_TOKENS
            for token in re.split(r"[._-]+", runtime_receipt.group(1))
        ):
            return True
    return False


def _validate_promotion_issue(issue: dict[str, Any]) -> None:
    labels = _label_names(issue)
    if str(issue.get("state", "")).lower() != "open":
        raise KnownDefectsError("promotion target must be an open Issue")
    if REGISTRY_LABEL in labels:
        raise KnownDefectsError("promotion target must not be another registry Issue")
    title = str(issue.get("title") or "")
    if (
        re.fullmatch(r"bug: \S(?:.{0,153}\S)?", title) is None
        or "\n" in title
    ):
        raise KnownDefectsError(
            "promotion target title must have canonical shape "
            "'bug: <short bounded outcome>'"
        )
    type_labels = {label for label in labels if label.startswith("type:")}
    if type_labels != {"type:bug"}:
        raise KnownDefectsError(
            "promotion target must carry exactly one type label: type:bug"
        )
    agent_states = {label for label in labels if label.startswith("agent:")}
    if len(agent_states) != 1 or not agent_states <= NORMAL_AGENT_STATES:
        raise KnownDefectsError(
            "promotion target must carry exactly one truthful normal agent-state label"
        )
    priorities = {label for label in labels if label.startswith("prio:")}
    if len(priorities) != 1 or not priorities <= PRIORITY_LABELS:
        raise KnownDefectsError(
            "promotion target must carry exactly one canonical priority label"
        )
    lane_labels = labels & ALLOWED_LANE_LABELS
    canonical_labels = {"type:bug"} | agent_states | priorities | lane_labels
    unexpected_labels = sorted(labels - canonical_labels)
    if unexpected_labels:
        raise KnownDefectsError(
            "promotion target has unexpected label(s): "
            + ", ".join(unexpected_labels)
        )
    body = issue.get("body") or ""
    sections = _top_level_sections(body)
    required_keys = set(REQUIRED_ISSUE_SECTIONS)
    allowed_keys = required_keys | {OPTIONAL_ISSUE_SECTION}
    missing = [
        heading
        for heading in REQUIRED_ISSUE_SECTIONS
        if heading not in sections
    ]
    if missing:
        raise KnownDefectsError(
            "promotion target lacks canonical section(s): " + ", ".join(missing)
        )
    unexpected = sorted(set(sections) - allowed_keys)
    if unexpected:
        raise KnownDefectsError(
            "promotion target has unexpected top-level section(s): "
            + ", ".join(unexpected)
        )
    empty = [
        heading
        for heading in REQUIRED_ISSUE_SECTIONS
        if not _has_concrete_section_content(sections[heading])
    ]
    if empty:
        raise KnownDefectsError(
            "promotion target has empty or placeholder canonical section(s): "
            + ", ".join(empty)
        )
    source_anchors = re.findall(
        r"(?m)^-\s+`([^`\n]+)::([^`\n]+)`\s*$",
        sections["Source Anchors"],
    )
    if (
        not source_anchors
        or any(
            not _is_durable_repo_path(path)
            or not _is_durable_anchor(anchor)
            for path, anchor in source_anchors
        )
    ):
        raise KnownDefectsError(
            "promotion target Source Anchors must name a durable path and anchor"
        )
    source_docs = re.findall(
        r"(?m)^-\s+`([^`\n]+)`\s*$",
        sections["Source Docs"],
    )
    if (
        not source_docs
        or any(not _is_durable_repo_path(path) for path in source_docs)
    ):
        raise KnownDefectsError(
            "promotion target Source Docs must name a durable repo path"
        )
    sbs = sections["SBS Impact"]
    missing_sbs = []
    for field in REQUIRED_SBS_FIELDS:
        matches = list(re.finditer(
            rf"(?mi)^-\s+{re.escape(field)}:\s*(.+?)\s*$",
            sbs,
        ))
        if (
            len(matches) != 1
            or not _has_concrete_section_content(matches[0].group(1))
        ):
            missing_sbs.append(field)
    if missing_sbs:
        raise KnownDefectsError(
            "promotion target lacks concrete SBS field(s): "
            + ", ".join(missing_sbs)
        )
    acceptance = sections["Acceptance Criteria"]
    report = analyze_acceptance_criteria(acceptance)
    if not report.present or report.malformed:
        raise KnownDefectsError(
            "promotion target must contain at least one well-formed Acceptance Criterion"
        )
    if not report.verify_markers_present:
        missing = "; ".join(report.missing_verify_items)
        raise KnownDefectsError(
            "promotion target Acceptance Criteria lack concrete Verify targets: "
            + missing
        )
    unresolved = [
        item.splitlines()[0].strip()
        for item in _acceptance_items(acceptance)
        if not _has_resolvable_verify_target(item)
    ]
    if unresolved:
        raise KnownDefectsError(
            "promotion target Acceptance Criteria lack resolvable Verify targets: "
            + "; ".join(unresolved)
        )


def _promotion_target_authority_sha256(issue: dict[str, Any]) -> str:
    labels = _label_names(issue)
    priority = next(iter(labels & PRIORITY_LABELS), "")
    agent_state = next(iter(labels & NORMAL_AGENT_STATES), "")
    payload = {
        "agent_state": agent_state,
        "body": issue.get("body") or "",
        "issue_state": str(issue.get("state") or "").lower(),
        "lanes": sorted(labels & ALLOWED_LANE_LABELS),
        "priority": priority,
        "title": issue.get("title") or "",
        "type": "type:bug",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _promotion_comments(
    gateway: RegistryGateway,
    registry_number: int,
    defect_id: str,
    *,
    phase: str,
    issue_number: int | None = None,
    authority_sha256: str | None = None,
) -> list[dict[str, Any]]:
    matches = []
    for comment in _inventory_comments(gateway, registry_number):
        parsed = _promotion_from_comment(comment.get("body") or "")
        if parsed is None or parsed[0] != defect_id or parsed[3] != phase:
            continue
        if issue_number is not None and parsed[1] != issue_number:
            continue
        if authority_sha256 is not None and parsed[2] != authority_sha256:
            continue
        matches.append(comment)
    return matches


def _finalize_pending_promotion(
    gateway: RegistryGateway,
    registry_number: int,
    comment: dict[str, Any],
    defect_id: str,
    issue_number: int,
    authority_sha256: str,
) -> dict[str, Any]:
    comment_id = int(comment.get("id") or 0)
    if comment_id <= 0:
        raise KnownDefectsError("promotion finalization requires a comment id")
    pending_body = comment.get("body") or ""
    expected = (defect_id, issue_number, authority_sha256, "pending")
    if _promotion_from_comment(pending_body) != expected:
        raise KnownDefectsError(
            "promotion finalization requires the exact pending authority"
        )
    final_body = pending_body.replace(" phase=pending -->", " phase=final -->", 1)
    # This PATCH commits the already-ordered validation snapshot. It has no
    # cross-Issue predicate: the trusted reservation id determines authority.
    try:
        gateway.update_comment(comment_id, final_body)
    except KnownDefectsError:
        final_comments = _promotion_comments(
            gateway,
            registry_number,
            defect_id,
            phase="final",
            issue_number=issue_number,
            authority_sha256=authority_sha256,
        )
        if not any(
            int(item.get("id") or 0) == comment_id
            for item in final_comments
        ):
            raise
    final_comments = _promotion_comments(
        gateway,
        registry_number,
        defect_id,
        phase="final",
        issue_number=issue_number,
        authority_sha256=authority_sha256,
    )
    exact_final = [
        item
        for item in final_comments
        if int(item.get("id") or 0) == comment_id
    ]
    if len(exact_final) != 1:
        raise KnownDefectsError(
            f"promotion finalization failed for {defect_id}"
        )
    return exact_final[0]


def _reconcile_pending_promotions(
    gateway: RegistryGateway,
    defect_id: str,
) -> tuple[int, str, int, dict[str, Any]] | None:
    reservation = _canonical_promotion_reservation(gateway, defect_id)
    if reservation is None:
        return None
    (
        issue_number,
        authority_sha256,
        phase,
        registry_number,
        canonical,
    ) = reservation
    locations = _registry_comment_locations(
        gateway,
        recover_bootstrap=False,
    )
    for candidate, comment in locations:
        parsed = _promotion_from_comment(comment.get("body") or "")
        if (
            parsed is None
            or parsed[0] != defect_id
            or parsed[3] != "pending"
            or int(comment.get("id") or 0)
            == int(canonical.get("id") or 0)
        ):
            continue
        _compensate_comment(gateway, int(candidate["number"]), comment)
    if phase == "final":
        return (
            issue_number,
            authority_sha256,
            registry_number,
            canonical,
        )
    finalized = _finalize_pending_promotion(
        gateway,
        registry_number,
        canonical,
        defect_id,
        issue_number,
        authority_sha256,
    )
    return issue_number, authority_sha256, registry_number, finalized


def promote_defect(
    defect_id: str,
    issue_number: int,
    gateway: RegistryGateway,
) -> dict[str, Any]:
    if not ENTRY_ID_RE.fullmatch(defect_id):
        raise KnownDefectsError("defect_id must have form KD-<12 uppercase hex>")
    gateway.refresh_registry_identities()
    found = _find_entry(gateway, defect_id)
    if found is None:
        raise KnownDefectsError(f"known defect {defect_id} was not found")
    entry_registry, _entry_comment = found
    existing = _reconcile_pending_promotions(
        gateway,
        defect_id,
    )
    if existing is not None:
        (
            existing_target,
            _authority_sha256,
            existing_registry,
            evidence_comment,
        ) = existing
        if existing_target == issue_number:
            return {
                "schema": "known-defect-receipt.v1",
                "status": "promotion_duplicate",
                "defect_id": defect_id,
                "registry_issue": existing_registry,
                "promotion_issue": issue_number,
                "url": evidence_comment.get("html_url"),
            }
        raise KnownDefectsError(
            f"{defect_id} is already linked to promotion Issue #{existing_target}"
        )
    if str(entry_registry.get("state", "")).lower() == "open":
        registry = entry_registry
    else:
        registry = _select_registry(gateway, None)
    _require_expected_single_open_registry(
        gateway,
        int(registry["number"]),
    )
    target = gateway.get_issue(issue_number)
    _validate_promotion_issue(target)
    authority_sha256 = _promotion_target_authority_sha256(target)
    marker = PROMOTION_MARKER_TEMPLATE.format(
        defect_id=defect_id,
        issue_number=issue_number,
        authority_sha256=authority_sha256,
        phase="pending",
    )
    registry_number = int(registry["number"])
    promotion_body = "\n".join(
        (
            marker,
            f"Promotion receipt: {defect_id} is now tracked for implementation by "
            f"#{issue_number}.",
            f"Validated target snapshot: sha256:{authority_sha256}.",
            "The bounded bug Issue owns scope, acceptance criteria, Verify targets, "
            "and execution state.",
        )
    )
    comment: dict[str, Any] | None = None
    gateway.refresh_registry_identities()
    _require_expected_single_open_registry(
        gateway,
        registry_number,
    )
    try:
        comment = gateway.add_comment(registry_number, promotion_body)
    except KnownDefectsError:
        reconciled = _reconcile_pending_promotions(
            gateway,
            defect_id,
        )
        if reconciled is None:
            raise
    else:
        reconciled = _reconcile_pending_promotions(
            gateway,
            defect_id,
        )
        if reconciled is None:
            raise KnownDefectsError(
                f"promotion reservation disappeared for {defect_id}"
            )
    (
        reconciled_issue,
        reconciled_digest,
        reconciled_registry,
        canonical_comment,
    ) = reconciled
    if (
        reconciled_issue != issue_number
        or reconciled_digest != authority_sha256
    ):
        raise KnownDefectsError(
            f"{defect_id} is already linked to promotion Issue "
            f"#{reconciled_issue}"
        )
    created = comment is None or int(canonical_comment.get("id") or 0) == int(
        comment.get("id") or 0
    )
    return {
        "schema": "known-defect-receipt.v1",
        "status": "promoted" if created else "promotion_duplicate",
        "defect_id": defect_id,
        "registry_issue": reconciled_registry,
        "promotion_issue": issue_number,
        "url": canonical_comment.get("html_url"),
    }


def _add_common_repo_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        help="GitHub owner/name; defaults to the current origin remote",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    intake = subparsers.add_parser("intake", help="append one confirmed deferred defect")
    _add_common_repo_argument(intake)
    intake.add_argument(
        "--classification",
        required=True,
        choices=("confirmed-defect", "maintainability", "unproven"),
    )
    intake.add_argument("--severity", required=True, choices=("P0", "P1", "P2", "P3"))
    intake.add_argument("--source-pr", required=True, type=int)
    intake.add_argument("--source-sha", required=True)
    intake.add_argument("--review-url", required=True)
    intake.add_argument("--symptom", required=True)
    intake.add_argument("--evidence", required=True)
    intake.add_argument("--impact", required=True)
    intake.add_argument("--workaround", required=True)
    intake.add_argument("--trigger", required=True)
    intake.add_argument(
        "--defect-key",
        help="optional stable dedupe key when evidence wording or source SHA may evolve",
    )
    intake.add_argument("--registry-issue", type=int)

    lookup = subparsers.add_parser("lookup", help="look up one deterministic defect id")
    _add_common_repo_argument(lookup)
    lookup.add_argument("--defect-id", required=True)

    promote = subparsers.add_parser(
        "promote",
        help="link a deferred entry to its normal bounded type:bug Issue",
    )
    _add_common_repo_argument(promote)
    promote.add_argument("--defect-id", required=True)
    promote.add_argument("--issue", required=True, type=int)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = _validate_repo(args.repo or _repo_from_remote())
        if args.command == "intake":
            if args.classification != "confirmed-defect":
                receipt = {
                    "schema": "known-defect-receipt.v1",
                    "status": "excluded",
                    "reason": f"classification:{args.classification}",
                }
            elif args.severity in {"P0", "P1"}:
                receipt = {
                    "schema": "known-defect-receipt.v1",
                    "status": "promotion_required",
                    "reason": f"severity:{args.severity}",
                }
            elif args.severity == "P3":
                receipt = {
                    "schema": "known-defect-receipt.v1",
                    "status": "excluded",
                    "reason": "severity:P3_non_defect",
                }
            else:
                defect = KnownDefect.validated(
                    repo=repo,
                    source_pr=args.source_pr,
                    source_sha=args.source_sha,
                    review_url=args.review_url,
                    symptom=args.symptom,
                    evidence=args.evidence,
                    severity=args.severity,
                    impact=args.impact,
                    workaround=args.workaround,
                    trigger=args.trigger,
                    defect_key=args.defect_key,
                )
                receipt = intake_defect(
                    defect,
                    GhRegistryGateway(repo),
                    registry_issue=args.registry_issue,
                )
        elif args.command == "lookup":
            receipt = lookup_defect(args.defect_id, GhRegistryGateway(repo))
        else:
            receipt = promote_defect(
                args.defect_id,
                args.issue,
                GhRegistryGateway(repo),
            )
    except KnownDefectsError as exc:
        print(
            json.dumps(
                {
                    "schema": "known-defect-receipt.v1",
                    "status": "error",
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
