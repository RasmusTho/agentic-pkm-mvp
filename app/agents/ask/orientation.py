"""Request-time orientation projection over retrieved candidates.

Orientation is derived from producer-owned metadata for one ASK turn.  The
projection is deliberately not written back to the candidate payload or any
durable store.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

OrientationState = Literal["active", "waiting", "supporting", "background", "unknown"]

_BACKGROUND_ZONES = frozenset({"archive", "background", "cold", "garden", "reference"})
_ACTIVE_REF_FIELDS = ("active_context_ref", "active_artifact_ref", "leave_point_artifact_uuid")


@dataclass(frozen=True)
class OrientationSignal:
    state: OrientationState
    provenance: dict[str, str]
    degradation: str | None = None


def _payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = item.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _identity_values(item: Mapping[str, Any]) -> set[str]:
    payload = _payload(item)
    values: set[str] = set()
    for value in (
        item.get("id"),
        item.get("doc_id"),
        item.get("object_id"),
        payload.get("uuid"),
        payload.get("artifact_id"),
        payload.get("stable_id"),
    ):
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
    for value in (item.get("source_ref"), item.get("path"), payload.get("source_ref"), payload.get("path")):
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
    return values


def _ref_values(value: Any) -> set[str]:
    if isinstance(value, str) and value.strip():
        return {value.strip()}
    if isinstance(value, Mapping):
        mapping_values: set[str] = set()
        for key in ("ref_id", "artifact_uuid", "object_id", "uuid", "path", "source_ref"):
            mapping_values.update(_ref_values(value.get(key)))
        return mapping_values
    if isinstance(value, (list, tuple, set)):
        sequence_values: set[str] = set()
        for item in value:
            sequence_values.update(_ref_values(item))
        return sequence_values
    return set()


def _candidate_key(item: Mapping[str, Any]) -> str:
    for value in (
        item.get("id"),
        item.get("doc_id"),
        item.get("object_id"),
        _payload(item).get("uuid"),
        _payload(item).get("artifact_id"),
        _payload(item).get("stable_id"),
        item.get("source_ref"),
        item.get("path"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _has_active_binding(item: Mapping[str, Any]) -> bool:
    payload = _payload(item)
    candidate_ids = _identity_values(item)
    for field in _ACTIVE_REF_FIELDS:
        refs = _ref_values(payload.get(field))
        if refs & candidate_ids:
            return True
    return False


def _is_background(item: Mapping[str, Any]) -> tuple[bool, dict[str, str]]:
    payload = _payload(item)
    zone = payload.get("zone") or payload.get("topology_zone")
    if isinstance(zone, str) and zone.strip().casefold() in _BACKGROUND_ZONES:
        return True, {"source": "frontmatter.zone", "value": zone.strip()}

    path = next(
        (
            value
            for value in (item.get("source_ref"), item.get("path"), payload.get("source_ref"), payload.get("path"))
            if isinstance(value, str) and value.strip()
        ),
        "",
    )
    segments = [segment.casefold() for segment in re.split(r"[/\\\\]", path) if segment]
    for segment in segments:
        if segment in _BACKGROUND_ZONES:
            return True, {"source": "vault_path_segment", "value": segment}
    return False, {}


def derive_orientation_signals(
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, OrientationSignal]:
    """Derive one signal per candidate using the contract's precedence."""

    candidate_ids = {value for item in candidates for value in _identity_values(item)}
    active_keys = {_candidate_key(item) for item in candidates if _has_active_binding(item)}
    waiting_keys = {
        _candidate_key(item)
        for item in candidates
        if _payload(item).get("commitment_state") == "waiting"
    }
    active_aliases = {
        alias
        for item in candidates
        if _candidate_key(item) in active_keys
        for alias in _identity_values(item)
    }
    waiting_aliases = {
        alias
        for item in candidates
        if _candidate_key(item) in waiting_keys
        for alias in _identity_values(item)
    }

    signals: dict[str, OrientationSignal] = {}
    for item in candidates:
        key = _candidate_key(item)
        payload = _payload(item)
        if key in active_keys:
            signals[key] = OrientationSignal(
                "active",
                {"source": "active_context_ref", "ref": key},
            )
            continue
        if key in waiting_keys:
            signals[key] = OrientationSignal(
                "waiting",
                {"source": "commitment_state", "value": "waiting"},
            )
            continue
        target_refs = _ref_values(payload.get("target_ref"))
        target_matches = target_refs & candidate_ids
        if target_matches & (active_aliases | waiting_aliases):
            signals[key] = OrientationSignal(
                "supporting",
                {"source": "target_ref", "ref": sorted(target_matches)[0]},
            )
            continue
        background, provenance = _is_background(item)
        if background:
            signals[key] = OrientationSignal("background", provenance)
            continue
        signals[key] = OrientationSignal(
            "unknown",
            {"source": "orientation_producer", "value": "unavailable"},
            degradation="orientation_producer_unavailable",
        )
    return signals


def is_return_orientation_question(question: str) -> bool:
    """Recognize explicit return-to-work context, not generic return/back wording."""

    normalized = " ".join((question or "").casefold().split())
    if not normalized:
        return False
    if re.search(r"\bafter\s+(?:an?\s+)?interruption\b|\bwas interrupted\b|\bwhere i left off\b", normalized):
        return True
    if re.search(r"\breturn(?:ing|ed)?\s+to\s+(?:work|the project|this project)\b", normalized):
        return True
    if re.search(
        r"\bresum(?:e|ed|ing|ption)\b.*\b(?:work|project|task|session|migration|where i left off)\b",
        normalized,
    ):
        return True
    if re.search(r"\bpick\s+up\s+where\s+i\s+left\s+off\b", normalized):
        return True
    return False


__all__ = ["OrientationSignal", "OrientationState", "derive_orientation_signals", "is_return_orientation_question"]
