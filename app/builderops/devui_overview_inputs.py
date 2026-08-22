"""Pure Cockpit working-band inputs for the devUI Overview.

This module deliberately consumes the contribution already composed for the
``work`` provider.  It never re-reads the Cockpit, GitHub, or any cache, and
it returns no candidate when that contribution cannot establish the narrow
source/trust contract required for a source-owned ``Now`` item.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


_RFC3339_TIMESTAMP = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-[0-9]{2}T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z",
    re.ASCII,
)
_GITHUB_REPOSITORY = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z",
    re.ASCII,
)


def _object(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        return None
    return value


def _nonblank(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _timestamp(value: Any) -> str | None:
    raw = _nonblank(value)
    if raw is None or _RFC3339_TIMESTAMP.fullmatch(raw) is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return raw if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _items(value: Any) -> Sequence[Any] | None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return None
    return value


def _trusted_working_items(work_provider: Any) -> tuple[str, Sequence[Any]] | None:
    """Return the one admitted working list and its captured-at watermark."""

    provider = _object(work_provider)
    if (
        provider is None
        or provider.get("provider") != "builderops_cockpit"
        or provider.get("status") != "available"
        or provider.get("authority") != "read_time_join"
    ):
        return None
    captured_at = _timestamp(provider.get("captured_at"))
    payload = _object(provider.get("payload"))
    if (
        captured_at is None
        or payload is None
        or payload.get("authority") != "read_time_join"
        or _timestamp(payload.get("generated_at")) != captured_at
    ):
        return None

    claim = _object(payload.get("claim"))
    if (
        claim is None
        or claim.get("kind") != "counted"
        or _nonblank(claim.get("text")) is None
        or claim.get("as_of") != captured_at
    ):
        return None

    sources = _items(payload.get("sources"))
    if sources is None:
        return None
    dispatcher_states: list[str] = []
    source_names: set[str] = set()
    for raw_source in sources:
        source = _object(raw_source)
        if source is None:
            return None
        name = _nonblank(source.get("name"))
        if name is None or name in source_names:
            return None
        source_names.add(name)
        if name == "dispatcher-store":
            if (
                source.get("configured") is not True
                or source.get("state") not in {"fresh", "empty"}
                or _timestamp(source.get("last_successful_read")) is None
            ):
                return None
            dispatcher_states.append(source["state"])
    if len(dispatcher_states) != 1:
        return None

    bands = _items(payload.get("bands"))
    if bands is None:
        return None
    working_bands: list[Mapping[str, Any]] = []
    for raw_band in bands:
        band = _object(raw_band)
        if band is not None and band.get("key") == "working":
            working_bands.append(band)
    if len(working_bands) != 1:
        return None
    working = working_bands[0]
    items = _items(working.get("items"))
    count = working.get("count")
    if (
        working.get("countable") is not True
        or type(count) is not int
        or count < 0
        or items is None
        or count != len(items)
    ):
        return None
    return captured_at, items


def _candidate(*, item: Any, captured_at: str) -> dict[str, Any] | None:
    source = _object(item)
    if source is None:
        return None
    repo = _nonblank(source.get("repo"))
    issue_number = source.get("issue_number")
    title = _nonblank(source.get("title"))
    why_now = _nonblank(source.get("why_now"))
    updated_at = _timestamp(source.get("updated_at"))
    if (
        repo is None
        or _GITHUB_REPOSITORY.fullmatch(repo) is None
        or type(issue_number) is not int
        or issue_number <= 0
        or title is None
        or why_now is None
        or updated_at is None
    ):
        return None

    subject_id = f"github:{repo}#{issue_number}"
    evidence_id = f"cockpit-working:{subject_id}:{updated_at}"
    return {
        "subject_ref": {
            "source_type": "github_issue",
            "source_id": subject_id,
            "locator": f"https://github.com/{repo}/issues/{issue_number}",
            "version": updated_at,
        },
        "display_label": title,
        "reason": why_now,
        "evidence": [
            {
                "evidence_id": evidence_id,
                "claim": "Cockpit working projection contains this source-owned item.",
                "source_ref": {
                    "source_type": "builderops_cockpit_working_projection",
                    "source_id": f"cockpit:working:{subject_id}",
                    "locator": "/api/cockpit/registry#working",
                    "version": updated_at,
                },
                "availability": "available",
                "freshness": "fresh",
                "completeness": "complete",
                "cardinality": "nonempty",
                "linkage": "linked",
                "captured_at": captured_at,
                "read_watermark": captured_at,
                "limitation": None,
            }
        ],
        "navigation_refs": [],
        "limitations": [],
    }


def derive_overview_inputs(*, work_provider: Any) -> dict[str, list[dict[str, Any]]]:
    """Derive only trusted source-ordered ``Now`` candidates from one contribution.

    A malformed or refused contribution remains visible in the Overview trust
    frame produced by ``compose_overview_view``.  This adapter adds no
    competing status, limitation, authority, delivery, or navigation claim.
    """

    trusted = _trusted_working_items(work_provider)
    if trusted is None:
        return {"now": []}
    captured_at, items = trusted
    candidates: list[dict[str, Any]] = []
    for item in items:
        candidate = _candidate(item=item, captured_at=captured_at)
        if candidate is None:
            return {"now": []}
        candidates.append(candidate)
    return copy.deepcopy({"now": candidates})


__all__ = ["derive_overview_inputs"]
