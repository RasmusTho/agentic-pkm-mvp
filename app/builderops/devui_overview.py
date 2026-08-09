"""Pure server-side Overview projection for the devUI owner experience.

The module consumes an already-composed ``devui.composition.v1`` envelope and
explicit producer evidence.  It never opens sources, retains state, or
interprets missing evidence as an empty or affirmative claim.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any


CONTRACT_VERSION = "devui-overview-view.v1"
_COMPOSITION_VERSION = "devui.composition.v1"
_ZONE_ORDER = ("now", "needs_you", "ready_to_try")
_ZONES = frozenset(_ZONE_ORDER)
_AVAILABILITY = frozenset({"available", "unavailable", "refused", "unsupported"})
_FRESHNESS = frozenset({"fresh", "stale", "unknown"})
_COMPLETENESS = frozenset(
    {"complete", "partial", "unread", "missing", "not_applicable"}
)
_CARDINALITY = frozenset(
    {"nonempty", "measured_empty", "not_measured", "not_countable"}
)
_LINKAGE = frozenset({"linked", "unlinked", "not_assessed", "not_applicable"})
_ROOT_KINDS = frozenset(
    {"focus", "soi_evidence", "delivery_execution", "builder_system_control"}
)
_DELIVERY_FACTS = frozenset(
    {
        "merged",
        "delivery",
        "availability",
        "ready_to_try",
        "owner_trial",
        "owner_acceptance",
    }
)
_OWNER_AUTHORITY_CATEGORIES = frozenset(
    {
        "irreversible_external_effect",
        "security_privacy_cost_commitment",
        "production_release_operator_action",
        "contradictory_source_authority",
    }
)


class OverviewContractError(ValueError):
    """Raised when an Overview input could make an authority claim ambiguous."""


def _detached(value: Any, *, label: str) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise OverviewContractError(f"{label} must be copyable") from exc


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    copied = _detached(value, label=label)
    if not isinstance(copied, dict) or any(not isinstance(key, str) for key in copied):
        raise OverviewContractError(f"{label} must be an object with string keys")
    return copied


def _list(value: Any, *, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise OverviewContractError(f"{label} must be a list")
    copied = _detached(list(value), label=label)
    if not isinstance(copied, list):  # pragma: no cover - deepcopy guard
        raise OverviewContractError(f"{label} must be a list")
    return copied


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OverviewContractError(f"{label} must be a non-empty string")
    return value


def _keys(
    value: Mapping[str, Any], *, allowed: set[str], required: set[str], label: str
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise OverviewContractError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise OverviewContractError(f"{label} is missing fields: {sorted(missing)}")


def _source_ref(value: Any, *, label: str) -> dict[str, Any]:
    source = _mapping(value, label=label)
    _keys(
        source,
        allowed={"source_type", "source_id", "version", "snapshot", "content_hash", "locator"},
        required={"source_type", "source_id", "locator"},
        label=label,
    )
    for field in ("source_type", "source_id", "locator"):
        _string(source[field], label=f"{label}.{field}")
    if all(source.get(field) is None for field in ("version", "snapshot", "content_hash")):
        raise OverviewContractError(f"{label} requires a version, snapshot, or content hash")
    for field in ("version", "snapshot", "content_hash"):
        if source.get(field) is not None:
            _string(source[field], label=f"{label}.{field}")
    return source


def _evidence(value: Any, *, label: str) -> dict[str, Any]:
    evidence = _mapping(value, label=label)
    _keys(
        evidence,
        allowed={
            "evidence_id",
            "claim",
            "source_ref",
            "availability",
            "freshness",
            "completeness",
            "cardinality",
            "linkage",
            "captured_at",
            "read_watermark",
            "limitation",
        },
        required={
            "evidence_id",
            "claim",
            "source_ref",
            "availability",
            "freshness",
            "completeness",
            "cardinality",
            "linkage",
            "captured_at",
            "limitation",
        },
        label=label,
    )
    _string(evidence["evidence_id"], label=f"{label}.evidence_id")
    evidence["source_ref"] = _source_ref(evidence["source_ref"], label=f"{label}.source_ref")
    _string(evidence["captured_at"], label=f"{label}.captured_at")
    for field, allowed in (
        ("availability", _AVAILABILITY),
        ("freshness", _FRESHNESS),
        ("completeness", _COMPLETENESS),
        ("cardinality", _CARDINALITY),
        ("linkage", _LINKAGE),
    ):
        if evidence[field] not in allowed:
            raise OverviewContractError(f"{label}.{field} is unsupported")
    if evidence["claim"] is not None:
        _string(evidence["claim"], label=f"{label}.claim")
        if evidence["linkage"] != "linked":
            raise OverviewContractError(f"{label} unlinked evidence cannot support a claim")
        if evidence["availability"] != "available":
            raise OverviewContractError(f"{label} unavailable evidence cannot support a claim")
    else:
        _string(evidence["limitation"], label=f"{label}.limitation")
    if evidence["cardinality"] == "measured_empty":
        if (
            evidence["availability"] != "available"
            or evidence["completeness"] != "complete"
            or evidence["linkage"] != "linked"
            or not isinstance(evidence.get("read_watermark"), str)
            or not evidence["read_watermark"].strip()
        ):
            raise OverviewContractError(
                f"{label}.measured_empty requires an available, complete, linked watermark"
            )
    if evidence["availability"] != "available" and evidence["cardinality"] == "measured_empty":
        raise OverviewContractError(f"{label} cannot make an empty claim from an unavailable source")
    return evidence


def _is_actionable(evidence: Mapping[str, Any]) -> bool:
    return (
        evidence["claim"] is not None
        and evidence["availability"] == "available"
        and evidence["freshness"] == "fresh"
        and evidence["completeness"] == "complete"
        and evidence["cardinality"] == "nonempty"
        and evidence["linkage"] == "linked"
    )


def _root_ref(value: Any, *, label: str) -> dict[str, Any]:
    root = _mapping(value, label=label)
    _keys(
        root,
        allowed={"kind", "navigation_ref", "status", "limitation"},
        required={"kind", "navigation_ref", "status", "limitation"},
        label=label,
    )
    if root["kind"] not in _ROOT_KINDS:
        raise OverviewContractError(f"{label}.kind is unsupported")
    root["navigation_ref"] = _source_ref(
        root["navigation_ref"], label=f"{label}.navigation_ref"
    )
    if root["status"] not in {"available", "degraded", "unsupported", "unlinked"}:
        raise OverviewContractError(f"{label}.status is unsupported")
    if root["limitation"] is not None:
        _string(root["limitation"], label=f"{label}.limitation")
    return root


def _candidate(value: Any, *, zone: str) -> dict[str, Any]:
    candidate = _mapping(value, label=f"{zone} candidate")
    _keys(
        candidate,
        allowed={
            "subject_ref",
            "reason",
            "evidence",
            "owner_authority",
            "delivery_facts",
            "navigation_refs",
            "limitations",
        },
        required={"subject_ref", "reason", "evidence", "navigation_refs", "limitations"},
        label=f"{zone} candidate",
    )
    candidate["subject_ref"] = _source_ref(
        candidate["subject_ref"], label=f"{zone} candidate.subject_ref"
    )
    _string(candidate["reason"], label=f"{zone} candidate.reason")
    evidence = [_evidence(item, label=f"{zone} candidate.evidence") for item in _list(candidate["evidence"], label=f"{zone} candidate.evidence")]
    if not evidence:
        raise OverviewContractError(f"{zone} candidate requires source evidence")
    if len({item["evidence_id"] for item in evidence}) != len(evidence):
        raise OverviewContractError(f"{zone} candidate has duplicate evidence ids")
    candidate["evidence"] = evidence
    candidate["navigation_refs"] = [
        _root_ref(item, label=f"{zone} candidate.navigation_refs")
        for item in _list(candidate["navigation_refs"], label=f"{zone} candidate.navigation_refs")
    ]
    candidate["limitations"] = [
        _string(item, label=f"{zone} candidate.limitations")
        for item in _list(candidate["limitations"], label=f"{zone} candidate.limitations")
    ]

    authority = candidate.get("owner_authority")
    if authority is not None:
        authority = _mapping(authority, label=f"{zone} candidate.owner_authority")
        _keys(
            authority,
            allowed={"category", "governing_source", "evidence_id"},
            required={"category", "governing_source", "evidence_id"},
            label=f"{zone} candidate.owner_authority",
        )
        _string(authority["category"], label=f"{zone} candidate.owner_authority.category")
        authority["governing_source"] = _source_ref(
            authority["governing_source"], label=f"{zone} candidate.owner_authority.governing_source"
        )
        _string(authority["evidence_id"], label=f"{zone} candidate.owner_authority.evidence_id")
        candidate["owner_authority"] = authority

    facts = candidate.get("delivery_facts")
    if facts is not None:
        facts = _mapping(facts, label=f"{zone} candidate.delivery_facts")
        if set(facts) - _DELIVERY_FACTS:
            raise OverviewContractError(f"{zone} candidate.delivery_facts has unknown facts")
        for key, fact in facts.items():
            fact = _mapping(fact, label=f"{zone} candidate.delivery_facts.{key}")
            _keys(
                fact,
                allowed={"state", "source_ref", "receipt_ref", "evidence_id"},
                required={"state", "source_ref", "evidence_id"},
                label=f"{zone} candidate.delivery_facts.{key}",
            )
            if fact["state"] not in {"evidenced", "unknown", "not_applicable"}:
                raise OverviewContractError(f"{zone} candidate.delivery_facts.{key}.state is unsupported")
            fact["source_ref"] = _source_ref(
                fact["source_ref"], label=f"{zone} candidate.delivery_facts.{key}.source_ref"
            )
            _string(fact["evidence_id"], label=f"{zone} candidate.delivery_facts.{key}.evidence_id")
            if fact.get("receipt_ref") is not None:
                fact["receipt_ref"] = _source_ref(
                    fact["receipt_ref"], label=f"{zone} candidate.delivery_facts.{key}.receipt_ref"
                )
            facts[key] = fact
        candidate["delivery_facts"] = facts
    return candidate


def _withdrawal(candidate: Mapping[str, Any], *, zone: str, reason: str) -> dict[str, Any]:
    return {
        "kind": "classification_withdrawn",
        "zone": zone,
        "subject_ref": candidate["subject_ref"],
        "reason": reason,
        "evidence": candidate["evidence"],
    }


def _classify(candidate: dict[str, Any], *, zone: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    evidence_by_id = {item["evidence_id"]: item for item in candidate["evidence"]}
    if zone == "needs_you":
        authority = candidate.get("owner_authority")
        evidence = evidence_by_id.get(authority["evidence_id"]) if authority else None
        if (
            authority is None
            or authority["category"] not in _OWNER_AUTHORITY_CATEGORIES
            or evidence is None
            or not _is_actionable(evidence)
        ):
            return None, _withdrawal(
                candidate,
                zone=zone,
                reason="owner authority is missing, unknown, unlinked, or degraded",
            )
    if zone == "ready_to_try":
        facts = candidate.get("delivery_facts") or {}
        ready = facts.get("ready_to_try")
        evidence = evidence_by_id.get(ready["evidence_id"]) if ready else None
        if (
            ready is None
            or ready["state"] != "evidenced"
            or ready.get("receipt_ref") is None
            or evidence is None
            or not _is_actionable(evidence)
        ):
            return None, _withdrawal(
                candidate,
                zone=zone,
                reason="receipt-backed ready-to-try evidence is missing, unlinked, or degraded",
            )
    return candidate, None


def compose_overview_view(
    *,
    composition: Mapping[str, Any],
    candidates: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    root_references: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compose the rebuildable owner Overview without source access or mutation."""

    envelope = _mapping(composition, label="composition")
    _keys(
        envelope,
        allowed={"contract_version", "authority", "captured_at", "providers"},
        required={"contract_version", "authority", "captured_at", "providers"},
        label="composition",
    )
    if envelope["contract_version"] != _COMPOSITION_VERSION:
        raise OverviewContractError("composition contract version is unsupported")
    if envelope["authority"] != "projection_only":
        raise OverviewContractError("composition must remain projection_only")
    _string(envelope["captured_at"], label="composition.captured_at")
    providers = _mapping(envelope["providers"], label="composition.providers")
    trust_providers: list[dict[str, Any]] = []
    for name, provider in providers.items():
        provider = _mapping(provider, label=f"composition.providers.{name}")
        _string(name, label="composition provider name")
        if provider.get("status") not in {"available", "refused"}:
            raise OverviewContractError(f"composition.providers.{name}.status is unsupported")
        trust_providers.append(
            {
                "provider": name,
                "status": provider["status"],
                "captured_at": provider.get("captured_at"),
                "completeness": _detached(provider.get("completeness"), label="provider completeness"),
                "refusal": _detached(provider.get("refusal"), label="provider refusal"),
            }
        )

    raw_candidates = _mapping(candidates or {}, label="candidates")
    if set(raw_candidates) - _ZONES:
        raise OverviewContractError("candidates has unsupported zones")
    parsed_roots = [
        _root_ref(item, label="root_references")
        for item in _list(root_references, label="root_references")
    ]
    soi_roots = [root for root in parsed_roots if root["kind"] == "soi_evidence"]
    if len(soi_roots) > 1:
        raise OverviewContractError("root_references may contain at most one soi_evidence lens")

    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "composed_at": envelope["captured_at"],
        "trust_frame": {"provider_states": trust_providers, "limitations": []},
        "now": [],
        "needs_you": [],
        "ready_to_try": [],
        "root_references": parsed_roots,
        "soi_evidence_lens": soi_roots[0] if soi_roots else None,
        "limitations": [],
    }
    for zone in _ZONE_ORDER:
        zone_candidates = _list(raw_candidates.get(zone, []), label=f"candidates.{zone}")
        if zone in {"needs_you", "ready_to_try"} and not zone_candidates:
            result["limitations"].append(
                {
                    "kind": "classification_withdrawn",
                    "zone": zone,
                    "reason": "the producer supplied no actionable classification evidence",
                }
            )
        for raw in zone_candidates:
            candidate = _candidate(raw, zone=zone)
            classified, withdrawal = _classify(candidate, zone=zone)
            if classified is not None:
                result[zone].append(classified)
            if withdrawal is not None:
                result["limitations"].append(withdrawal)
    return result


__all__ = ["CONTRACT_VERSION", "OverviewContractError", "compose_overview_view"]
