"""Pure authority-aware discovery projection for the existing devUI envelope.

The caller supplies already-read, source-owned item declarations.  This module
does not discover sources, persist a registry, infer links, or execute routes;
it only validates and detaches a read-time projection.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


CONTRACT_VERSION = "devui.discovery-projection.v1"
_SOURCE_ROLES = frozenset({"owner", "evidence", "working", "projection", "receipt"})
_AUTHORITY_CLASSES = frozenset(
    {"normative", "non-normative", "operational", "projection", "receipt", "unknown"}
)
_ARTIFACT_CLASSES = frozenset(
    {"source", "derived", "proposal", "implementation", "mirror", "unknown"}
)
_STAGES = frozenset(
    {
        "capture",
        "explore",
        "synthesize",
        "propose",
        "promote",
        "implement",
        "verify",
        "supersede_retire",
        "unknown",
    }
)
_LIFECYCLE_STATES = frozenset(
    {"draft", "active", "accepted", "superseded", "retired", "unknown"}
)
_SOURCE_STATES = frozenset(
    {
        "fresh",
        "stale",
        "unknown",
        "unavailable",
        "unread",
        "refused",
        "unlinked",
        "missing",
        "ambiguous",
        "partial",
    }
)
_RFC3339 = re.compile(
    r"[0-9]{4}-(?:0[1-9]|1[0-2])-[0-9]{2}T"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])\Z",
    re.ASCII,
)


class DiscoveryContractError(ValueError):
    """Raised when a declaration would overstate source-owned discovery truth."""


def _detached(value: Any, *, label: str) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise DiscoveryContractError(f"{label} must be copyable") from exc


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    copied = _detached(value, label=label)
    if not isinstance(copied, dict) or any(not isinstance(key, str) for key in copied):
        raise DiscoveryContractError(f"{label} must be an object with string keys")
    return copied


def _string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryContractError(f"{label} must be a non-empty string")
    return value


def _timestamp(value: Any, *, label: str) -> str:
    text = _string(value, label=label)
    if _RFC3339.fullmatch(text) is None:
        raise DiscoveryContractError(f"{label} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscoveryContractError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DiscoveryContractError(f"{label} must be an RFC3339 timestamp")
    return text


def _keys(value: Mapping[str, Any], *, allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise DiscoveryContractError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise DiscoveryContractError(f"{label} is missing fields: {sorted(missing)}")


def _source_ref(value: Any, *, label: str) -> dict[str, Any]:
    ref = _mapping(value, label=label)
    _keys(
        ref,
        allowed={"source_type", "source_id", "version", "snapshot", "content_hash", "locator"},
        required={"source_type", "source_id", "locator"},
        label=label,
    )
    for field in ("source_type", "source_id", "locator"):
        _string(ref[field], label=f"{label}.{field}")
    if all(ref.get(field) is None for field in ("version", "snapshot", "content_hash")):
        raise DiscoveryContractError(f"{label} requires a version, snapshot, or content hash")
    for field in ("version", "snapshot", "content_hash"):
        if ref.get(field) is not None:
            _string(ref[field], label=f"{label}.{field}")
    return ref


def _refs(value: Any, *, label: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DiscoveryContractError(f"{label} must be a list")
    return [_source_ref(item, label=f"{label}[{index}]") for index, item in enumerate(value)]


def _limitations(value: Any, *, label: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise DiscoveryContractError(f"{label} must be a list")
    return [_string(item, label=f"{label}[{index}]") for index, item in enumerate(value)]


def _item(value: Any, *, index: int) -> dict[str, Any]:
    label = f"items[{index}]"
    item = _mapping(value, label=label)
    _keys(
        item,
        allowed={
            "source_ref", "source_role", "authority_class", "artifact_class", "lifecycle",
            "provenance", "freshness", "limitations", "navigation",
        },
        required={
            "source_ref", "source_role", "authority_class", "artifact_class", "lifecycle",
            "provenance", "freshness", "limitations", "navigation",
        },
        label=label,
    )
    item["source_ref"] = _source_ref(item["source_ref"], label=f"{label}.source_ref")
    if item["source_role"] not in _SOURCE_ROLES:
        raise DiscoveryContractError(f"{label}.source_role is unsupported")
    if item["authority_class"] not in _AUTHORITY_CLASSES:
        raise DiscoveryContractError(f"{label}.authority_class is unsupported")
    if item["artifact_class"] not in _ARTIFACT_CLASSES:
        raise DiscoveryContractError(f"{label}.artifact_class is unsupported")

    lifecycle = _mapping(item["lifecycle"], label=f"{label}.lifecycle")
    _keys(lifecycle, allowed={"stage", "state"}, required={"stage", "state"}, label=f"{label}.lifecycle")
    if lifecycle["stage"] not in _STAGES or lifecycle["state"] not in _LIFECYCLE_STATES:
        raise DiscoveryContractError(f"{label}.lifecycle is unsupported")
    item["lifecycle"] = lifecycle

    provenance = _mapping(item["provenance"], label=f"{label}.provenance")
    _keys(
        provenance,
        allowed={"source_refs", "derived_from", "review_or_promotion_ref", "receipt_refs"},
        required={"source_refs", "derived_from", "review_or_promotion_ref", "receipt_refs"},
        label=f"{label}.provenance",
    )
    provenance["source_refs"] = _refs(provenance["source_refs"], label=f"{label}.provenance.source_refs")
    provenance["derived_from"] = _refs(provenance["derived_from"], label=f"{label}.provenance.derived_from")
    promotion = provenance["review_or_promotion_ref"]
    provenance["review_or_promotion_ref"] = None if promotion is None else _source_ref(promotion, label=f"{label}.provenance.review_or_promotion_ref")
    provenance["receipt_refs"] = _refs(provenance["receipt_refs"], label=f"{label}.provenance.receipt_refs")
    item["provenance"] = provenance

    freshness = _mapping(item["freshness"], label=f"{label}.freshness")
    _keys(freshness, allowed={"observed_at", "watermark", "state"}, required={"observed_at", "watermark", "state"}, label=f"{label}.freshness")
    freshness["observed_at"] = _timestamp(freshness["observed_at"], label=f"{label}.freshness.observed_at")
    if freshness["watermark"] is not None:
        _string(freshness["watermark"], label=f"{label}.freshness.watermark")
    if freshness["state"] not in _SOURCE_STATES:
        raise DiscoveryContractError(f"{label}.freshness.state is unsupported")
    item["freshness"] = freshness
    item["limitations"] = _limitations(item["limitations"], label=f"{label}.limitations")
    if freshness["state"] != "fresh" and not item["limitations"]:
        raise DiscoveryContractError(f"{label} degraded source state requires a typed limitation")

    navigation = _mapping(item["navigation"], label=f"{label}.navigation")
    _keys(navigation, allowed={"inspect_ref", "governed_route_ref"}, required={"inspect_ref", "governed_route_ref"}, label=f"{label}.navigation")
    for field in ("inspect_ref", "governed_route_ref"):
        navigation[field] = None if navigation[field] is None else _source_ref(navigation[field], label=f"{label}.navigation.{field}")
    item["navigation"] = navigation

    if item["source_ref"]["source_type"] == "builder_vault" and item["authority_class"] != "non-normative":
        raise DiscoveryContractError("Builder Vault items must remain non-normative")
    return item


def compose_discovery_projection(*, composition: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a detached, source-bound discovery projection.

    ``composition`` is accepted only as the existing read-time envelope identity;
    no provider payload is copied or elevated into a discovery authority.
    """

    envelope = _mapping(composition, label="composition")
    if envelope.get("contract_version") != "devui.composition.v1" or envelope.get("authority") != "projection_only":
        raise DiscoveryContractError("composition must be the existing projection-only devUI envelope")
    captured_at = _timestamp(envelope.get("captured_at"), label="composition.captured_at")
    if not isinstance(envelope.get("providers"), Mapping):
        raise DiscoveryContractError("composition.providers must be an object")
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise DiscoveryContractError("items must be a list")

    rendered = []
    for index, declaration in enumerate(items):
        item = _item(declaration, index=index)
        state = item["freshness"]["state"]
        item["claim_status"] = "available" if state == "fresh" else "withdrawn"
        item["presentation"] = {
            "non_normative": item["authority_class"] == "non-normative",
            "ephemeral_or_rebuildable": item["source_ref"]["source_type"] == "builder_vault",
        }
        rendered.append(item)
    return {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "composition_ref": {"contract_version": "devui.composition.v1", "captured_at": captured_at},
        "navigation_mode": "source_bound_read_only",
        "items": rendered,
    }


__all__ = ["CONTRACT_VERSION", "DiscoveryContractError", "compose_discovery_projection"]
