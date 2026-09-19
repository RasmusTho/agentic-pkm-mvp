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
from urllib.parse import quote

from app.builderops.devui_focus import CONTRACT_VERSION as FOCUS_CONTRACT_VERSION
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
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_CONTEXT_FIELDS = frozenset(
    {
        "claimed_by",
        "status",
        "capability_lane",
        "sources",
        "next_action",
        "next_action_evidence",
        "mirror_watermark",
        "chain_position",
        "position_evidence",
        "position_unresolved_reason",
        "flaws",
    }
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


def _trusted_working_items(
    work_provider: Any,
) -> tuple[str, Sequence[Any], dict[str, Mapping[str, Any]]] | None:
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
    source_map: dict[str, Mapping[str, Any]] = {}
    for raw_source in sources:
        source = _object(raw_source)
        if source is None:
            return None
        name = _nonblank(source.get("name"))
        if name is None or name in source_names:
            return None
        source_names.add(name)
        source_map[name] = source
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
    return captured_at, items, source_map


def _source_axes(source: Mapping[str, Any] | None) -> tuple[str, str, str, str]:
    """Map one source's declared read state to existing evidence axes."""

    state = source.get("state") if source is not None else "unavailable"
    if state == "fresh":
        return "available", "fresh", "complete", "linked"
    if state == "empty":
        return "available", "fresh", "complete", "unlinked"
    if state == "stale":
        return "available", "stale", "partial", "unlinked"
    return "unavailable", "unknown", "unread", "unlinked"


def _source_watermark(
    source: Mapping[str, Any] | None, *, fallback: str
) -> tuple[str, str | None]:
    """Return a source read time and its optional read watermark."""

    watermark = _timestamp(source.get("last_successful_read")) if source else None
    return watermark or fallback, watermark


def _source_transport(source: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if source is None:
        return None
    return _object(source.get("transport"))


def _source_ref(
    *,
    source_type: str,
    source_id: str,
    locator: str,
    version: str,
) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "locator": locator,
        "version": version,
    }


def _evidence(
    *,
    evidence_id: str,
    claim: str | None,
    source_ref: Mapping[str, str],
    availability: str,
    freshness: str,
    completeness: str,
    cardinality: str,
    linkage: str,
    captured_at: str,
    read_watermark: str | None = None,
    limitation: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence_id": evidence_id,
        "claim": claim,
        "source_ref": dict(source_ref),
        "availability": availability,
        "freshness": freshness,
        "completeness": completeness,
        "cardinality": cardinality,
        "linkage": linkage,
        "captured_at": captured_at,
        "limitation": limitation,
    }
    if read_watermark is not None:
        result["read_watermark"] = read_watermark
    return result


def _context_enabled(item: Mapping[str, Any], sources: Mapping[str, Mapping[str, Any]]) -> bool:
    return bool(_CONTEXT_FIELDS.intersection(item) or "docs-frontmatter" in sources)


def _capability_evidence(
    *,
    source: Mapping[str, Any] | None,
    item: Mapping[str, Any],
    subject_id: str,
    captured_at: str,
) -> tuple[dict[str, Any], str | None]:
    lane = _object(item.get("capability_lane"))
    docs = _source_transport(source)
    docs_state = source.get("state") if source is not None else "unavailable"
    docs_read_at, docs_watermark = _source_watermark(source, fallback=captured_at)
    repo = _nonblank(item.get("repo")) or "unknown"
    lane_key = _nonblank(lane.get("key")) if lane else None
    lane_name = _nonblank(lane.get("name")) if lane else None
    candidate_sha = _nonblank(docs.get("candidate_sha")) if docs else None
    refs = _items(docs.get("source_refs")) if docs else None
    locator = (
        next((ref for ref in refs or [] if _nonblank(ref)), None)
        if refs is not None
        else None
    )
    linked = (
        lane is not None
        and lane.get("rung") == "proven"
        and lane_key is not None
        and lane_name is not None
        and docs_state == "fresh"
        and docs is not None
        and docs.get("repository") == repo
        and docs.get("outcome") == "available"
        and candidate_sha is not None
        and _SOURCE_SHA.fullmatch(candidate_sha) is not None
        and isinstance(locator, str)
        and bool(locator.strip())
    )
    if linked:
        assert lane_key is not None
        assert isinstance(locator, str)
        assert candidate_sha is not None
        source_ref = _source_ref(
            source_type="docs-frontmatter",
            source_id=lane_key,
            locator=locator,
            version=candidate_sha,
        )
        return (
            _evidence(
                evidence_id=f"capability:{subject_id}:{candidate_sha}",
                claim=f"Explicit docs-linked capability: {lane_name}.",
                source_ref=source_ref,
                availability="available",
                freshness="fresh",
                completeness="complete",
                cardinality="nonempty",
                linkage="linked",
                captured_at=docs_read_at,
                read_watermark=docs_watermark,
            ),
            None,
        )

    source_id = lane_key or subject_id
    source_version = candidate_sha or docs_watermark or f"state:{docs_state}"
    source_ref = _source_ref(
        source_type="docs-frontmatter",
        source_id=source_id,
        locator=locator or "/api/cockpit/registry#docs-frontmatter",
        version=source_version,
    )
    limitation = (
        "Capability is unknown: the explicit docs edge is unavailable, stale, "
        "unlinked, or not proven for this source item."
    )
    return (
        _evidence(
            evidence_id=f"capability-unknown:{subject_id}:{source_version}",
            claim=None,
            source_ref=source_ref,
            availability=_source_axes(source)[0],
            freshness=_source_axes(source)[1],
            completeness=_source_axes(source)[2],
            cardinality="not_countable",
            linkage="unlinked",
            captured_at=docs_read_at,
            read_watermark=docs_watermark,
            limitation=limitation,
        ),
        limitation,
    )


def _work_context_evidence(
    *,
    source: Mapping[str, Any] | None,
    item: Mapping[str, Any],
    subject_id: str,
    captured_at: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    source_captured, source_watermark = _source_watermark(source, fallback=captured_at)
    source_state = source.get("state") if source is not None else "unavailable"
    availability, freshness, completeness, linkage = _source_axes(source)
    version = _timestamp(item.get("updated_at")) or source_watermark or captured_at
    source_ref = _source_ref(
        source_type="dispatcher-store",
        source_id=f"dispatcher:{subject_id}",
        locator="/api/cockpit/registry#working",
        version=version,
    )
    parts: list[str] = []
    holder = _nonblank(item.get("claimed_by"))
    status = _nonblank(item.get("status"))
    position = _nonblank(item.get("chain_position"))
    observed_at = _timestamp(item.get("updated_at"))
    if holder:
        parts.append(f"Registered holder (source-declared): {holder}.")
    if status:
        parts.append(f"Observed work status (source-declared): {status}.")
    if position:
        parts.append(f"Observed chain position: {position}.")
    if observed_at:
        parts.append(f"Observed update time: {observed_at}.")
    unresolved = _nonblank(item.get("position_unresolved_reason"))
    limitations: list[str] = []
    if unresolved:
        limitations.append(f"Observed chain position is unknown: {unresolved}")
    if not parts:
        limitations.append("Observed holder and work status are unavailable from the admitted source.")
    claim = " ".join(parts) if parts and source_state == "fresh" else None
    if claim is None and not limitations:
        limitations.append("Observed holder and work status remain unknown because this source is not fresh.")
    return (
        [
            _evidence(
                evidence_id=f"work-context:{subject_id}:{version}",
                claim=claim,
                source_ref=source_ref,
                availability=availability,
                freshness=freshness,
                completeness=completeness,
                cardinality="nonempty" if parts else "not_countable",
                linkage=linkage,
                captured_at=source_captured,
                read_watermark=source_watermark,
                limitation=None if claim else limitations[0],
            )
        ],
        limitations,
    )


def _next_action_evidence(
    *,
    item: Mapping[str, Any],
    subject_id: str,
    captured_at: str,
) -> tuple[dict[str, Any], str]:
    watermark = _timestamp(item.get("mirror_watermark"))
    next_action = _nonblank(item.get("next_action"))
    version = watermark or captured_at
    source_ref = _source_ref(
        source_type="builderops_mirror",
        source_id=f"mirror:{subject_id}",
        locator="/api/cockpit/registry#mirror",
        version=version,
    )
    if next_action and watermark:
        claim = f"Proposed next step (source proposal): {next_action}."
        evidence = _evidence(
            evidence_id=f"next-action:{subject_id}:{watermark}",
            claim=claim,
            source_ref=source_ref,
            availability="available",
            freshness="fresh",
            completeness="complete",
            cardinality="nonempty",
            linkage="linked",
            captured_at=watermark,
            read_watermark=watermark,
        )
        return evidence, ""
    limitation = (
        "Proposed next step is unavailable; blocker absence is unknown and "
        "does not grant execution permission."
    )
    evidence = _evidence(
        evidence_id=f"next-action-unknown:{subject_id}:{version}",
        claim=None,
        source_ref=source_ref,
        availability="available" if watermark else "unavailable",
        freshness="fresh" if watermark else "unknown",
        completeness="partial" if watermark else "unread",
        cardinality="not_countable",
        linkage="linked" if watermark else "unlinked",
        captured_at=watermark or captured_at,
        read_watermark=watermark,
        limitation=limitation,
    )
    return evidence, limitation


def _flaw_evidence(
    *,
    item: Mapping[str, Any],
    subject_id: str,
    captured_at: str,
) -> list[dict[str, Any]]:
    flaws = item.get("flaws")
    if not isinstance(flaws, Sequence) or isinstance(flaws, (str, bytes)):
        return []
    version = _timestamp(item.get("updated_at")) or captured_at
    result: list[dict[str, Any]] = []
    for index, raw_flaw in enumerate(flaws):
        flaw = _object(raw_flaw)
        text = _nonblank(flaw.get("text")) if flaw else None
        predicate = _nonblank(flaw.get("predicate")) if flaw else None
        if text is None:
            continue
        result.append(
            _evidence(
                evidence_id=f"flaw:{subject_id}:{predicate or index}:{version}",
                claim=f"Source-reported flaw: {text}",
                source_ref=_source_ref(
                    source_type="builderops_cockpit_flaws",
                    source_id=f"{subject_id}:{predicate or index}",
                    locator="/api/cockpit/registry#flawed",
                    version=version,
                ),
                availability="available",
                freshness="fresh",
                completeness="complete",
                cardinality="nonempty",
                linkage="linked",
                captured_at=captured_at,
                read_watermark=captured_at,
            )
        )
    return result


def _append_work_context(
    *,
    candidate: dict[str, Any],
    item: Mapping[str, Any],
    sources: Mapping[str, Mapping[str, Any]],
    captured_at: str,
) -> None:
    subject_id = candidate["subject_ref"]["source_id"]
    docs_evidence, docs_limitation = _capability_evidence(
        source=sources.get("docs-frontmatter"),
        item=item,
        subject_id=subject_id,
        captured_at=captured_at,
    )
    candidate["evidence"].append(docs_evidence)
    if docs_limitation:
        candidate["limitations"].append(docs_limitation)
    work_evidence, work_limitations = _work_context_evidence(
        source=sources.get("dispatcher-store"),
        item=item,
        subject_id=subject_id,
        captured_at=captured_at,
    )
    candidate["evidence"].extend(work_evidence)
    candidate["limitations"].extend(work_limitations)
    next_evidence, next_limitation = _next_action_evidence(
        item=item, subject_id=subject_id, captured_at=captured_at
    )
    candidate["evidence"].append(next_evidence)
    if next_limitation:
        candidate["limitations"].append(next_limitation)
    candidate["evidence"].extend(
        _flaw_evidence(item=item, subject_id=subject_id, captured_at=captured_at)
    )
    candidate["limitations"].append(
        "Flaw coverage is source-scoped; absence of a rendered flaw is not a blocker-free claim."
    )


def _candidate(
    *, item: Any, captured_at: str, sources: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
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
    candidate = {
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
    if _context_enabled(source, sources):
        _append_work_context(
            candidate=candidate,
            item=source,
            sources=sources,
            captured_at=captured_at,
        )
    return candidate


def _receipt_candidate(receipt_provider: Any) -> dict[str, Any] | None:
    """Map only an admitted receipt chain to the existing ready-to-try shape."""

    provider = _object(receipt_provider)
    if (
        provider is None
        or provider.get("provider") != "builderops_vm102_receipts"
        or provider.get("status") != "available"
        or provider.get("authority") != "builderops_vm102_receipt_source"
    ):
        return None
    captured_at = _timestamp(provider.get("captured_at"))
    snapshot = _object(provider.get("snapshot"))
    payload = _object(provider.get("payload"))
    if snapshot is None or payload is None:
        return None
    component_id = _nonblank(snapshot.get("component_id"))
    candidate_sha = _nonblank(snapshot.get("candidate_source_sha"))
    receipt_refs = _items(snapshot.get("receipt_refs"))
    if (
        component_id is None
        or candidate_sha is None
        or receipt_refs is None
        or len(receipt_refs) != 3
        or any(_nonblank(item) is None for item in receipt_refs)
        or _nonblank(payload.get("observed_at")) is None
    ):
        return None
    source_ref = {
        "source_type": "builderops_vm102_receipt",
        "source_id": str(receipt_refs[-1]),
        "locator": str(receipt_refs[-1]),
        "version": candidate_sha,
    }
    evidence_id = f"builderops-vm102-chain:{component_id}:{candidate_sha}"
    return {
        "subject_ref": {
            "source_type": "builderops_vm102_component",
            "source_id": f"vm102:{component_id}",
            "locator": str(receipt_refs[-1]),
            "version": candidate_sha,
        },
        "display_label": "DevUI on VM 102",
        "reason": "BuilderOps qualification, deployment, and health receipts bind this candidate to VM 102.",
        "evidence": [
            {
                "evidence_id": evidence_id,
                "claim": "The source-owned VM-102 receipt chain is current and linked to this component.",
                "source_ref": source_ref,
                "availability": "available",
                "freshness": "fresh",
                "completeness": "complete",
                "cardinality": "nonempty",
                "linkage": "linked",
                "captured_at": captured_at,
                "read_watermark": payload["observed_at"],
                "limitation": None,
            }
        ],
        "delivery_facts": {
            "ready_to_try": {
                "state": "evidenced",
                "source_ref": source_ref,
                "receipt_ref": source_ref,
                "evidence_id": evidence_id,
            }
        },
        "navigation_refs": [],
        "limitations": [],
    }


def derive_overview_inputs(
    *,
    work_provider: Any,
    receipt_provider: Any = None,
    owner_fact_provider: Any = None,
    issue_delivery_provider: Any = None,
) -> dict[str, list[dict[str, Any]]]:
    """Derive only trusted source-ordered ``Now`` candidates from one contribution.

    A malformed or refused contribution remains visible in the Overview trust
    frame produced by ``compose_overview_view``.  This adapter adds no
    competing status, limitation, authority, delivery, or navigation claim.
    """

    trusted = _trusted_working_items(work_provider)
    candidates: list[dict[str, Any]] = []
    if trusted is not None:
        captured_at, items, sources = trusted
        for item in items:
            candidate = _candidate(item=item, captured_at=captured_at, sources=sources)
            if candidate is None:
                candidates = []
                break
            subject = candidate["subject_ref"]["source_id"]
            projection = (
                issue_delivery_provider.get(subject)
                if isinstance(issue_delivery_provider, Mapping)
                else item.get("issue_delivery_readback")
                if isinstance(item, Mapping)
                else None
            )
            if isinstance(projection, Mapping):
                if (
                    projection.get("contract") != "fca-issue-delivery-readback.v1"
                    or projection.get("state") != "delivered"
                    or projection.get("subject_ref") != subject
                    or not isinstance(projection.get("evidence"), list)
                    or not isinstance(projection.get("delivery_facts"), Mapping)
                ):
                    candidates = []
                    break
                candidate["evidence"].extend(copy.deepcopy(projection["evidence"]))
                candidate["delivery_facts"] = copy.deepcopy(projection["delivery_facts"])
                candidate["limitations"].extend(copy.deepcopy(projection.get("limitations", [])))
            candidates.append(candidate)
    result: dict[str, list[dict[str, Any]]] = {"now": candidates}
    receipt_candidate = _receipt_candidate(receipt_provider)
    if receipt_candidate is not None:
        result["ready_to_try"] = [receipt_candidate]
    if owner_fact_provider is not None:
        from app.builderops.devui_owner_facts import owner_fact_candidates

        for zone, items in owner_fact_candidates(owner_fact_provider).items():
            result.setdefault(zone, []).extend(items)
    return copy.deepcopy(result)


__all__ = ["derive_overview_inputs"]


def bind_visual_focus_targets(
    candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Attach the one shipped visual Focus root to real Now subjects.

    The source adapter still owns subject identity and placement.  This route
    owns only the presentation locator, and supplies it as a typed root rather
    than asking the browser to construct or probe candidate URLs.
    """

    for item in candidates.get("now", []):
        subject = item.get("subject_ref", {}).get("source_id")
        if not isinstance(subject, str) or not subject:
            continue
        item["navigation_refs"] = [
            {
                "kind": "focus",
                "navigation_ref": {
                    "source_type": "devui_focus_route",
                    "source_id": subject,
                    "locator": f"/devui/focus?subject={quote(subject, safe='')}",
                    "version": FOCUS_CONTRACT_VERSION,
                },
                "status": "available",
                "limitation": None,
            }
        ]
    return candidates
