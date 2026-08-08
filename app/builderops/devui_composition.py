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
    CkmStateIdentity,
    ErrorEnvelope,
    ResultEnvelope,
    SnapshotManifest,
    canonical_query_digest,
    validate_contract_request,
)
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION


CONTRACT_VERSION = "devui.composition.v1"
logger = logging.getLogger(__name__)
_CKM_REFUSAL_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
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

    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise TypeError("provider returned a non-object JSON payload")
    return decoded


def _validated_ckm_payload(result: ResultEnvelope) -> dict[str, Any]:
    """Re-run current CKM policy and snapshot invariants at the adapter boundary."""

    snapshot = result.snapshot
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
        if (
            payload.get("authority") != authority
            or not isinstance(generated_at, str)
            or not generated_at
            or not isinstance(claim, Mapping)
            or not isinstance(sources, list)
            or not isinstance(unread_planes, list)
            or not isinstance(withdrawn_counts, list)
        ):
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
                type(result.schema_version) is not int
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
