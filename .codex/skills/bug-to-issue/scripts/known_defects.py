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
    extract_sections,
)

REGISTRY_LABEL = "state:known-defect"
REGISTRY_LABEL_COLOR = "C5DEF5"
REGISTRY_LABEL_DESCRIPTION = (
    "Rolling registry of confirmed deferred defects; never eligible for agent pickup"
)
REGISTRY_MARKER = "<!-- known-defects-registry:v1 -->"
ENTRY_MARKER_TEMPLATE = "<!-- known-defect-entry:v1 id={defect_id} -->"
PROMOTION_MARKER_TEMPLATE = (
    "<!-- known-defect-promotion:v1 id={defect_id} issue={issue_number} -->"
)
ENTRY_ID_RE = re.compile(r"^KD-[0-9A-F]{12}$")
ENTRY_MARKER_RE = re.compile(
    r"<!-- known-defect-entry:v1 id=(KD-[0-9A-F]{12}) -->"
)
PROMOTION_MARKER_RE = re.compile(
    r"<!-- known-defect-promotion:v1 id=(KD-[0-9A-F]{12}) issue=(\d+) -->"
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NORMAL_AGENT_STATES = {
    "agent:ready",
    "agent:blocked",
    "agent:needs-human",
}
PRIORITY_LABELS = {"prio:high", "prio:med", "prio:low"}
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
        if severity not in {"P2", "P3"}:
            raise KnownDefectsError(
                "the deferred registry accepts only ordinary confirmed P2/P3 defects"
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
        normalized_key = (
            _require_text("defect_key", defect_key, max_length=256)
            if defect_key is not None
            else None
        )
        return cls(
            repo=repo,
            source_pr=source_pr,
            source_sha=source_sha.lower(),
            review_url=review_url,
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

    def render_entry(self) -> str:
        return "\n".join(
            (
                ENTRY_MARKER_TEMPLATE.format(defect_id=self.defect_id),
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

    def get_issue(self, number: int) -> dict[str, Any]: ...

    def create_registry_issue(self) -> dict[str, Any]: ...

    def lock_registry_issue(self, issue_number: int) -> None: ...

    def list_comments(self, issue_number: int) -> list[dict[str, Any]]: ...

    def add_comment(self, issue_number: int, body: str) -> dict[str, Any]: ...


class GhRegistryGateway:
    """Small REST-only GitHub gateway used by the deterministic CLI."""

    def __init__(self, repo: str) -> None:
        self.repo = _validate_repo(repo)

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
        issues = self._list_paginated(
            f"repos/{self.repo}/issues?state={state}&labels={encoded_label}"
        )
        return [
            issue
            for issue in issues
            if "pull_request" not in issue
        ]

    def get_issue(self, number: int) -> dict[str, Any]:
        issue = self._request("GET", f"repos/{self.repo}/issues/{number}")
        if "pull_request" in issue:
            raise KnownDefectsError(f"#{number} is a pull request, not an Issue")
        return issue

    def create_registry_issue(self) -> dict[str, Any]:
        return self._request(
            "POST",
            f"repos/{self.repo}/issues",
            {
                "title": "Known Defects Registry (rolling)",
                "labels": ["type:bug", REGISTRY_LABEL],
                "body": render_registry_body(),
            },
        )

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


def render_registry_body() -> str:
    return "\n".join(
        (
            REGISTRY_MARKER,
            "# Known Defects Registry",
            "",
            "This rolling Issue is the canonical low-overhead registry for confirmed "
            "deferred P2/P3 defects.",
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


def _entry_id_from_comment(body: str) -> str | None:
    lines = body.splitlines()
    if not lines or not lines[0].startswith("<!-- known-defect-entry:"):
        return None
    marker = ENTRY_MARKER_RE.fullmatch(lines[0])
    if marker is None:
        raise KnownDefectsError("malformed known-defect entry marker")
    defect_id = marker.group(1)
    if len(lines) != 10 or lines[1] != f"### {defect_id}" or lines[2] != "":
        raise KnownDefectsError(f"malformed known-defect entry shape for {defect_id}")
    required_prefixes = (
        "- State: deferred; not an implementation contract",
        "- Source: PR #",
        "- Reproducible symptom:",
        "- Evidence:",
        "- Impact/severity:",
        "- Workaround:",
        "- Re-evaluation/promotion trigger:",
    )
    for line, prefix in zip(lines[3:], required_prefixes, strict=True):
        if not line.startswith(prefix):
            raise KnownDefectsError(
                f"malformed known-defect entry {defect_id}: expected one {prefix!r}"
            )
    return defect_id


def _promotion_from_comment(body: str) -> tuple[str, int] | None:
    lines = body.splitlines()
    if not lines or not lines[0].startswith("<!-- known-defect-promotion:"):
        return None
    marker = PROMOTION_MARKER_RE.fullmatch(lines[0])
    if marker is None:
        raise KnownDefectsError("malformed known-defect promotion marker")
    defect_id, issue_number_text = marker.groups()
    issue_number = int(issue_number_text)
    expected_receipt = (
        f"Promotion receipt: {defect_id} is now tracked for implementation by "
        f"#{issue_number}."
    )
    expected_authority = (
        "The bounded bug Issue owns scope, acceptance criteria, Verify targets, "
        "and execution state."
    )
    if (
        len(lines) != 3
        or lines[1] != expected_receipt
        or lines[2] != expected_authority
    ):
        raise KnownDefectsError(
            f"malformed known-defect promotion shape for {defect_id}"
        )
    return defect_id, issue_number


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
    if is_entry:
        _entry_id_from_comment(body)
    else:
        _promotion_from_comment(body)


def _registry_inventory(
    gateway: RegistryGateway,
    *,
    recover_bootstrap: bool,
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
    if len(open_registries) > 1:
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


def _promotion_targets(
    comments: Sequence[dict[str, Any]],
    defect_id: str,
) -> tuple[set[int], dict[int, dict[str, Any]]]:
    targets: set[int] = set()
    evidence: dict[int, dict[str, Any]] = {}
    for comment in comments:
        _validate_schema_comment(comment)
        parsed = _promotion_from_comment(comment.get("body") or "")
        if parsed is None or parsed[0] != defect_id:
            continue
        issue_number = parsed[1]
        targets.add(issue_number)
        evidence.setdefault(issue_number, comment)
    return targets, evidence


def _find_entry(
    gateway: RegistryGateway,
    defect_id: str,
    *,
    recover_bootstrap: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    issues = _registry_inventory(
        gateway,
        recover_bootstrap=recover_bootstrap,
    )
    open_registries = [
        issue for issue in issues if str(issue.get("state", "")).lower() == "open"
    ]
    if len(open_registries) > 1:
        numbers = ", ".join(f"#{item['number']}" for item in open_registries)
        raise KnownDefectsError(f"multiple open registries found ({numbers})")
    found: tuple[dict[str, Any], dict[str, Any]] | None = None
    for issue in issues:
        for comment in _inventory_comments(gateway, int(issue["number"])):
            parsed_id = _entry_id_from_comment(comment.get("body") or "")
            if parsed_id == defect_id and found is None:
                found = (issue, comment)
    return found


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


def intake_defect(
    defect: KnownDefect,
    gateway: RegistryGateway,
    *,
    registry_issue: int | None = None,
) -> dict[str, Any]:
    gateway.ensure_registry_label()
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
    _inventory_comments(gateway, int(issue["number"]))
    comment = gateway.add_comment(int(issue["number"]), defect.render_entry())
    return {
        "schema": "known-defect-receipt.v1",
        "status": "created",
        "defect_id": defect.defect_id,
        "registry_issue": int(issue["number"]),
        "url": comment.get("html_url"),
    }


def lookup_defect(
    defect_id: str,
    gateway: RegistryGateway,
) -> dict[str, Any]:
    if not ENTRY_ID_RE.fullmatch(defect_id):
        raise KnownDefectsError("defect_id must have form KD-<12 uppercase hex>")
    found = _find_entry(gateway, defect_id)
    if found is None:
        return {
            "schema": "known-defect-receipt.v1",
            "status": "not_found",
            "defect_id": defect_id,
        }
    issue, comment = found
    targets, _evidence = _promotion_targets(
        gateway.list_comments(int(issue["number"])),
        defect_id,
    )
    if len(targets) > 1:
        return {
            "schema": "known-defect-receipt.v1",
            "status": "promotion_conflict",
            "defect_id": defect_id,
            "registry_issue": int(issue["number"]),
            "promotion_issues": sorted(targets),
            "promotion_issue": None,
            "url": comment.get("html_url"),
        }
    promotion_issue = next(iter(targets), None)
    return {
        "schema": "known-defect-receipt.v1",
        "status": "promoted" if promotion_issue is not None else "deferred",
        "defect_id": defect_id,
        "registry_issue": int(issue["number"]),
        "promotion_issue": promotion_issue,
        "url": comment.get("html_url"),
    }


def _validate_promotion_issue(issue: dict[str, Any]) -> None:
    labels = _label_names(issue)
    if str(issue.get("state", "")).lower() != "open":
        raise KnownDefectsError("promotion target must be an open Issue")
    type_labels = {label for label in labels if label.startswith("type:")}
    if type_labels != {"type:bug"}:
        raise KnownDefectsError(
            "promotion target must carry exactly one type label: type:bug"
        )
    if REGISTRY_LABEL in labels:
        raise KnownDefectsError("promotion target must not be another registry Issue")
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
    body = issue.get("body") or ""
    missing = [
        heading
        for heading in REQUIRED_ISSUE_SECTIONS
        if not re.search(
            rf"^##\s+{re.escape(heading)}\s*$",
            body,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    ]
    if missing:
        raise KnownDefectsError(
            "promotion target lacks canonical section(s): " + ", ".join(missing)
        )
    acceptance = extract_sections(body).get("acceptance criteria")
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


def promote_defect(
    defect_id: str,
    issue_number: int,
    gateway: RegistryGateway,
) -> dict[str, Any]:
    if not ENTRY_ID_RE.fullmatch(defect_id):
        raise KnownDefectsError("defect_id must have form KD-<12 uppercase hex>")
    found = _find_entry(gateway, defect_id)
    if found is None:
        raise KnownDefectsError(f"known defect {defect_id} was not found")
    registry, _entry_comment = found
    targets, evidence = _promotion_targets(
        gateway.list_comments(int(registry["number"])),
        defect_id,
    )
    if len(targets) > 1:
        raise KnownDefectsError(
            f"{defect_id} has conflicting promotion Issues: "
            + ", ".join(f"#{number}" for number in sorted(targets))
        )
    if targets:
        existing_target = next(iter(targets))
        if existing_target == issue_number:
            return {
                "schema": "known-defect-receipt.v1",
                "status": "promotion_duplicate",
                "defect_id": defect_id,
                "registry_issue": int(registry["number"]),
                "promotion_issue": issue_number,
                "url": evidence[issue_number].get("html_url"),
            }
        raise KnownDefectsError(
            f"{defect_id} is already linked to promotion Issue #{existing_target}"
        )
    target = gateway.get_issue(issue_number)
    _validate_promotion_issue(target)
    marker = PROMOTION_MARKER_TEMPLATE.format(
        defect_id=defect_id,
        issue_number=issue_number,
    )
    comment = gateway.add_comment(
        int(registry["number"]),
        "\n".join(
            (
                marker,
                f"Promotion receipt: {defect_id} is now tracked for implementation by "
                f"#{issue_number}.",
                "The bounded bug Issue owns scope, acceptance criteria, Verify targets, "
                "and execution state.",
            )
        ),
    )
    targets, _evidence = _promotion_targets(
        gateway.list_comments(int(registry["number"])),
        defect_id,
    )
    if targets != {issue_number}:
        rendered_targets = ", ".join(f"#{number}" for number in sorted(targets))
        raise KnownDefectsError(
            f"promotion conflict detected for {defect_id}: {rendered_targets}"
        )
    return {
        "schema": "known-defect-receipt.v1",
        "status": "promoted",
        "defect_id": defect_id,
        "registry_issue": int(registry["number"]),
        "promotion_issue": issue_number,
        "url": comment.get("html_url"),
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
