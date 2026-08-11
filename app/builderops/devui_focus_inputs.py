"""Read one governed Focus subject into inputs for the pure Focus composer.

This adapter deliberately reads only the selected subject.  It does not reuse
or join the root devUI composition payload, and it owns no cache, store, or
workflow transition.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.builderops.cockpit_github_plane import fetch_github_live


_ISSUE_SUBJECT = re.compile(r"github:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)\Z")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITIES: Mapping[str, tuple[str, str, str]] = {
    "devui_focus": (
        "devUI Focus + Conversation Port",
        "docs/DEVUI.md",
        "DEVUI-FCP-BOUNDARY",
    ),
}


class FocusInputError(ValueError):
    """The requested Focus subject cannot be read as a governed subject."""


def _source_ref(*, source_type: str, source_id: str, locator: str, version: str) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "locator": locator,
        "version": version,
    }


def _claim(*, claim_id: str, claim: str, source_ref: Mapping[str, str], captured_at: str) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "claim": claim,
        "source_ref": dict(source_ref),
        "availability": "available",
        "freshness": "fresh",
        "coverage": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": captured_at,
        "limitation": None,
    }


def _common_inputs(*, subject: Mapping[str, Any], source_ref: Mapping[str, str], summary: str, captured_at: str) -> dict[str, Any]:
    return {
        "subject": dict(subject),
        "owner_intent": {"summary": summary, "source_ref": dict(source_ref)},
        "governing_sources": [
            _claim(
                claim_id="governing-subject",
                claim="Selected subject is readable from its governing source.",
                source_ref=source_ref,
                captured_at=captured_at,
            )
        ],
        "evidence": [
            _claim(
                claim_id="subject-read",
                claim="Selected subject read completed for this projection.",
                source_ref=source_ref,
                captured_at=captured_at,
            )
        ],
        "receipts": [],
        "risks": [],
        "next_legal_step": {
            "workflow_ref": None,
            "actor_class": "system",
            "legality": "unavailable",
            "reason": "This read route does not infer a workflow transition.",
        },
        "execution_observations": [],
        "conversation_port": {
            "availability": "unsupported",
            "reason": "Conversation Port runtime is not delivered by this read route.",
        },
        "limitations": [],
    }


def _read_issue_inputs(subject_id: str, match: re.Match[str]) -> dict[str, Any]:
    repository, number_text = match.groups()
    configured_repo = os.environ.get("COCKPIT_GITHUB_REPO")
    if configured_repo != repository:
        raise FocusInputError("requested Issue repository is not configured for the local read")
    result = fetch_github_live(configured_repo)
    if result.snapshot is None:
        raise FocusInputError("selected Issue source is unavailable")
    issue = result.snapshot.issues.get(int(number_text))
    if issue is None:
        raise FocusInputError("selected Issue is unavailable or unsupported")
    source_ref = _source_ref(
        source_type="github_issue",
        source_id=f"{repository}#{issue.number}",
        locator=issue.html_url,
        version=result.snapshot.read_at,
    )
    return _common_inputs(
        subject={
            "kind": "issue",
            "stable_id": subject_id,
            "authority_ref": source_ref,
            "title": issue.title,
        },
        source_ref=source_ref,
        summary=f"Read the governed Issue: {issue.title}",
        captured_at=result.snapshot.read_at,
    )


def _read_capability_inputs(subject_id: str) -> dict[str, Any]:
    capability = _CAPABILITIES.get(subject_id)
    if capability is None:
        raise FocusInputError("selected capability is unsupported")
    title, relative_path, anchor = capability
    path = _REPO_ROOT / relative_path
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FocusInputError("selected capability owner document is unavailable") from exc
    captured_at = datetime.now(timezone.utc).isoformat()
    source_ref = {
        "source_type": "owner_document",
        "source_id": f"{relative_path}#{anchor}",
        "locator": f"{relative_path}#{anchor}",
        "content_hash": hashlib.sha256(content).hexdigest(),
    }
    return _common_inputs(
        subject={
            "kind": "capability",
            "stable_id": subject_id,
            "authority_ref": source_ref,
            "title": title,
        },
        source_ref=source_ref,
        summary=f"Read the governed capability: {title}",
        captured_at=captured_at,
    )


def read_focus_inputs(subject_id: str) -> dict[str, Any]:
    """Return detached composer inputs for exactly one stable governed subject."""

    if not isinstance(subject_id, str) or not subject_id:
        raise FocusInputError("subject must be a stable governed identity")
    match = _ISSUE_SUBJECT.fullmatch(subject_id)
    if match is not None:
        return _read_issue_inputs(subject_id, match)
    return _read_capability_inputs(subject_id)


__all__ = ["FocusInputError", "read_focus_inputs"]
