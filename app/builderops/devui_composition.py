"""Read-only composition of Builder System evidence for devUI.

The composition is rebuilt for every read. It preserves provider envelopes and
their independent authority/snapshot semantics; it owns no durable state and
does not turn provider refusals into empty results.
"""

from __future__ import annotations

import logging
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from app.builderops.ckm.contracts import (
    ENVELOPE_SCHEMA_VERSION,
    RESOURCE_SCHEMA_VERSION,
    CkmContractError,
    CkmStateIdentity,
    CompletenessManifest,
    ErrorEnvelope,
    ObjectClassCompleteness,
    ProjectionMarker,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    TaggedValue,
    canonical_query_digest,
    validate_contract_request,
)
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION


CONTRACT_VERSION = "devui.composition.v1"
logger = logging.getLogger(__name__)
_CKM_REFUSAL_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CKM_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CKM_REFUSAL_MESSAGE = "CKM refused the read request"
_LIST_CAPABILITIES_QUERY_DIGEST = canonical_query_digest(
    {"operation": "list_capabilities", "public_id": None}
)


CockpitReader = Callable[[], Mapping[str, Any]]
CkmReader = Callable[[], ResultEnvelope | ErrorEnvelope]
Now = Callable[[], datetime]


def _cockpit_payload(reader: CockpitReader) -> Mapping[str, Any]:
    result = reader()
    if not isinstance(result, Mapping):
        raise TypeError("provider returned a non-object payload")
    return _json_object(result)


def _json_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached JSON-safe object or refuse before API serialization."""

    _require_string_mapping_keys(payload)
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    encoded.encode("utf-8", errors="strict")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise TypeError("provider returned a non-object JSON payload")
    return decoded


def _require_string_mapping_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("provider JSON objects require string keys")
            _require_string_mapping_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_string_mapping_keys(item)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _aware_iso_timestamp(value: Any) -> bool:
    if not _nonempty_string(value):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_cockpit_contract(payload: Mapping[str, Any]) -> bool:
    claim = payload.get("claim")
    sources = payload.get("sources")
    unread_planes = payload.get("unread_planes")
    withdrawn_counts = payload.get("withdrawn_counts")
    if (
        payload.get("authority") != "read_time_join"
        or not _aware_iso_timestamp(payload.get("generated_at"))
        or not isinstance(claim, Mapping)
        or claim.get("kind") not in {"counted", "refused"}
        or not _nonempty_string(claim.get("text"))
        or not isinstance(sources, list)
        or not isinstance(unread_planes, list)
        or any(not _nonempty_string(item) for item in unread_planes)
        or not isinstance(withdrawn_counts, list)
    ):
        return False
    generated_at = payload["generated_at"]
    if claim.get("as_of") != generated_at:
        return False
    source_states: dict[str, str] = {}
    for source in sources:
        if (
            not isinstance(source, Mapping)
            or not _nonempty_string(source.get("name"))
            or source.get("state") not in {"fresh", "stale", "empty", "unavailable"}
            or not _nonempty_string(source.get("detail"))
            or type(source.get("configured")) is not bool
            or type(source.get("stale_after_days")) is not int
            or source["stale_after_days"] < 0
        ):
            return False
        name = source["name"]
        if name in source_states:
            return False
        source_states[name] = source["state"]
        read_at = source.get("last_successful_read")
        if source["state"] == "unavailable":
            if read_at is not None:
                return False
        elif not _aware_iso_timestamp(read_at):
            return False
        if source["configured"] is False and source["state"] != "unavailable":
            return False
    dispatcher_state = source_states.get("dispatcher-store")
    if (
        dispatcher_state is None
        or next(
            source["configured"]
            for source in sources
            if source["name"] == "dispatcher-store"
        )
        is not True
        or (claim["kind"] == "refused" and dispatcher_state != "unavailable")
        or (claim["kind"] == "counted" and dispatcher_state not in {"fresh", "empty"})
    ):
        return False
    withdrawn_sources: set[str] = set()
    for withdrawal in withdrawn_counts:
        withdrawal_source = (
            withdrawal.get("source") if isinstance(withdrawal, Mapping) else None
        )
        if (
            not isinstance(withdrawal, Mapping)
            or not isinstance(withdrawal_source, str)
            or not withdrawal_source
            or withdrawal_source in withdrawn_sources
            or source_states.get(withdrawal_source) != "stale"
            or not isinstance(withdrawal.get("counts"), list)
            or not withdrawal["counts"]
            or len(withdrawal["counts"]) != len(set(withdrawal["counts"]))
            or any(not _nonempty_string(item) for item in withdrawal["counts"])
        ):
            return False
        withdrawn_sources.add(withdrawal_source)
    return True


def _validated_ckm_payload(result: ResultEnvelope) -> dict[str, Any]:
    """Re-run current CKM policy and snapshot invariants at the adapter boundary."""

    if type(result) is not ResultEnvelope:
        raise TypeError("CKM result must use the exact public envelope type")
    snapshot = result.snapshot
    if type(snapshot) is not SnapshotManifest:
        raise TypeError("CKM snapshot must use the exact public manifest type")
    if type(snapshot.completeness) is not CompletenessManifest:
        raise TypeError("CKM completeness must use the exact public manifest type")
    if type(result.projection) is not ProjectionMarker:
        raise TypeError("CKM projection must use the exact public marker type")
    versions = (
        (result.schema_version, ENVELOPE_SCHEMA_VERSION),
        (snapshot.ckm_schema_version, CKM_SCHEMA_VERSION),
        (snapshot.envelope_schema_version, ENVELOPE_SCHEMA_VERSION),
        (snapshot.resource_schema_version, RESOURCE_SCHEMA_VERSION),
        *(
            (resource.schema_version, RESOURCE_SCHEMA_VERSION)
            for resource in result.resources
        ),
    )
    if any(type(value) is not int or value != expected for value, expected in versions):
        raise ValueError("unsupported CKM schema version")
    if result.query_digest != _LIST_CAPABILITIES_QUERY_DIGEST:
        raise ValueError("CKM query identity does not match list_capabilities")
    if not _nonempty_string(snapshot.epoch):
        raise ValueError("CKM snapshot epoch must be a non-empty string")
    if type(snapshot.state_revision) is not int or snapshot.state_revision < 0:
        raise ValueError("CKM state revision must be a non-negative integer")
    if not isinstance(snapshot.taxonomy_digest, str) or not _CKM_DIGEST.fullmatch(
        snapshot.taxonomy_digest
    ):
        raise ValueError("CKM taxonomy identity must be a canonical digest")
    if type(snapshot.completeness.complete) is not bool:
        raise ValueError("CKM completeness marker must be boolean")
    for accounting in snapshot.completeness.object_classes:
        if type(accounting) is not ObjectClassCompleteness:
            raise TypeError("CKM accounting must use the exact public contract type")
        counts = (
            accounting.included,
            accounting.filtered,
            accounting.omitted,
            accounting.truncated,
        )
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError("CKM completeness counts must be non-negative integers")
    if not isinstance(snapshot.watermarks, Mapping) or any(
        not _nonempty_string(key) or not _nonempty_string(value)
        for key, value in snapshot.watermarks.items()
    ):
        raise ValueError("CKM watermarks must use non-empty string keys and values")
    if not isinstance(snapshot.read_set, Mapping):
        raise TypeError("CKM read set must be a mapping")
    for object_class, public_ids in snapshot.read_set.items():
        if not _nonempty_string(object_class) or isinstance(public_ids, (str, bytes)):
            raise ValueError("CKM read set identity is malformed")
        if not isinstance(public_ids, (list, tuple)) or any(
            not _nonempty_string(public_id) for public_id in public_ids
        ):
            raise ValueError("CKM read set public IDs must be non-empty strings")
    if not isinstance(snapshot.provenance, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in snapshot.provenance
    ):
        raise ValueError("CKM snapshot provenance must contain mappings")

    for resource in result.resources:
        if type(resource) is not ResourceDto:
            raise TypeError("CKM resources must use the exact public DTO type")
        if not all(
            _nonempty_string(value)
            for value in (resource.public_id, resource.display_name, resource.lifecycle)
        ):
            raise ValueError("CKM resource identity fields must be non-empty strings")
        if type(resource.candidate) is not bool:
            raise ValueError("CKM resource candidate marker must be boolean")
        if not isinstance(resource.provenance, (list, tuple)) or any(
            not isinstance(item, Mapping) for item in resource.provenance
        ):
            raise ValueError("CKM resource provenance must contain mappings")
        if not isinstance(resource.values, Mapping) or any(
            not _nonempty_string(key) or type(value) is not TaggedValue
            for key, value in resource.values.items()
        ):
            raise ValueError("CKM resource values must be typed and string-keyed")
    validate_contract_request(
        ckm_schema_version=snapshot.ckm_schema_version,
        envelope_schema_version=result.schema_version,
        resource_schema_version=snapshot.resource_schema_version,
        resource_type=result.resource_type,
        effective_audience=snapshot.effective_audience,
        access_policy_version=snapshot.access_policy_version,
        redaction_profile=snapshot.redaction_profile,
    )
    rebuilt_snapshot = SnapshotManifest.build(
        state=CkmStateIdentity(
            epoch=snapshot.epoch,
            state_revision=snapshot.state_revision,
            schema_version=snapshot.ckm_schema_version,
        ),
        taxonomy_digest=snapshot.taxonomy_digest,
        watermarks=snapshot.watermarks,
        provenance=snapshot.provenance,
        completeness=snapshot.completeness,
        read_set=snapshot.read_set,
    )
    if rebuilt_snapshot.to_dict() != snapshot.to_dict():
        raise ValueError("CKM snapshot identity does not match its declared read set")

    # Re-instantiation re-runs ResultEnvelope's resource ordering, completeness,
    # and exact read-set checks even if a frozen dataclass was copied/replaced.
    ResultEnvelope(
        resource_type=result.resource_type,
        query_digest=result.query_digest,
        snapshot=result.snapshot,
        resources=result.resources,
        projection=result.projection,
        schema_version=result.schema_version,
    )
    return _json_object(result.to_dict())


def _refusal(
    *,
    provider: str,
    authority: str | Mapping[str, Any],
    message: str,
    code: str,
    details: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "refused",
        "authority": authority,
        "captured_at": None,
        "snapshot": None,
        "completeness": None,
        "refusal": {
            "code": code,
            "message": message,
            "details": dict(details),
        },
    }


def _cockpit_contribution(reader: CockpitReader) -> dict[str, Any]:
    provider = "builderops_cockpit"
    authority = "read_time_join"
    try:
        payload = _cockpit_payload(reader)
        generated_at = payload.get("generated_at")
        claim = payload.get("claim")
        sources = payload.get("sources")
        unread_planes = payload.get("unread_planes")
        withdrawn_counts = payload.get("withdrawn_counts")
        if not _valid_cockpit_contract(payload):
            raise ValueError("malformed BuilderOps Cockpit registry envelope")
        return {
            "provider": provider,
            "status": "available",
            "authority": payload["authority"],
            "captured_at": generated_at,
            "snapshot": {
                "generated_at": generated_at,
                "sources": sources,
            },
            "completeness": {
                "claim": claim,
                "unread_planes": unread_planes,
                "withdrawn_counts": withdrawn_counts,
            },
            "payload": payload,
        }
    except Exception:
        logger.exception("BuilderOps Cockpit devUI provider read failed")
        return _refusal(
            provider=provider,
            authority=authority,
            code="provider_unavailable",
            message="BuilderOps Cockpit could not provide its read snapshot",
            details={"reason": "provider read failed"},
        )


def _ckm_contribution(reader: CkmReader) -> dict[str, Any]:
    provider = "ckm"
    authority = {"status": "derived_projection", "authoritative": False}
    try:
        result = reader()
        if isinstance(result, ErrorEnvelope):
            if (
                type(result) is not ErrorEnvelope
                or type(result.error) is not CkmContractError
                or type(result.schema_version) is not int
                or result.schema_version != ENVELOPE_SCHEMA_VERSION
            ):
                raise ValueError("unsupported CKM refusal envelope version")
            code = result.error.code
            message = result.error.message
            details = result.error.details
            if (
                isinstance(code, str)
                and _CKM_REFUSAL_CODE.fullmatch(code)
                and isinstance(message, str)
                and message
                and isinstance(details, Mapping)
            ):
                return _refusal(
                    provider=provider,
                    authority=authority,
                    code=code,
                    # CKM's local read contract may include filesystem paths
                    # and raw SQLite/OSError text in message/details. The
                    # unified owner projection preserves the typed code, but
                    # never republishes that diagnostic material.
                    message=_CKM_REFUSAL_MESSAGE,
                    details={},
                )
            raise ValueError("malformed CKM refusal envelope")

        if not isinstance(result, ResultEnvelope):
            raise ValueError("CKM reader returned an unvalidated envelope")
        payload = _validated_ckm_payload(result)
        projection = payload["projection"]
        snapshot = payload["snapshot"]
        if (
            result.resource_type != "capability"
            or projection.get("status") != "derived_projection"
            or projection.get("authoritative") is not False
        ):
            raise ValueError("malformed CKM result envelope")
        return {
            "provider": provider,
            "status": "available",
            "authority": projection,
            # CKM identifies the source snapshot by epoch, revision, digest,
            # and watermarks. Inventing a global timestamp here would weaken
            # that contract, so captured_at remains explicitly absent.
            "captured_at": None,
            "snapshot": snapshot,
            "completeness": snapshot["completeness"],
            "payload": payload,
        }
    except Exception:
        logger.exception("CKM devUI provider read failed")
        return _refusal(
            provider=provider,
            authority=authority,
            code="provider_unavailable",
            message="CKM could not provide its read snapshot",
            details={"reason": "provider read failed"},
        )


def compose_owner_snapshot(
    *,
    cockpit_reader: CockpitReader,
    ckm_reader: CkmReader,
    now: Now | None = None,
) -> dict[str, Any]:
    """Capture independent provider reads beneath one projection envelope."""

    captured_at = (now or (lambda: datetime.now(timezone.utc)))()
    if captured_at.tzinfo is None:
        raise ValueError("composition capture time must be timezone-aware")
    return {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "captured_at": captured_at.isoformat(),
        "providers": {
            "work": _cockpit_contribution(cockpit_reader),
            "capabilities": _ckm_contribution(ckm_reader),
        },
    }


__all__ = ["CONTRACT_VERSION", "compose_owner_snapshot"]
