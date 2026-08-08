"""Read-only composition of Builder System evidence for devUI.

The composition is rebuilt for every read. It preserves provider envelopes and
their independent authority/snapshot semantics; it owns no durable state and
does not turn provider refusals into empty results.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from app.builderops.ckm.contracts import (
    ACCESS_POLICY_VERSION,
    EFFECTIVE_AUDIENCE,
    ENVELOPE_SCHEMA_VERSION,
    REDACTION_PROFILE,
    RESOURCE_SCHEMA_VERSION,
)
from app.builderops.ckm.schema import CKM_SCHEMA_VERSION


CONTRACT_VERSION = "devui.composition.v1"
logger = logging.getLogger(__name__)
_CKM_REFUSAL_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CKM_REFUSAL_MESSAGE = "CKM refused the read request"
_CKM_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class _Envelope(Protocol):
    def to_dict(self) -> dict[str, Any]: ...


ProviderReader = Callable[[], Mapping[str, Any] | _Envelope]
Now = Callable[[], datetime]


def _payload(reader: ProviderReader) -> Mapping[str, Any]:
    result = reader()
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    if not isinstance(result, Mapping):
        raise TypeError("provider returned a non-object payload")
    return result


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


def _cockpit_contribution(reader: ProviderReader) -> dict[str, Any]:
    provider = "builderops_cockpit"
    authority = "read_time_join"
    try:
        payload = _payload(reader)
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


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_ckm_snapshot(
    snapshot: Mapping[str, Any],
    resources: list[Any],
) -> bool:
    completeness = snapshot.get("completeness")
    object_classes = (
        completeness.get("object_classes")
        if isinstance(completeness, Mapping)
        else None
    )
    capability_accounting = None
    if isinstance(object_classes, list):
        capability_accounting = next(
            (
                item
                for item in object_classes
                if isinstance(item, Mapping)
                and item.get("object_class") == "capability"
            ),
            None,
        )
    digests = (
        snapshot.get("taxonomy_digest"),
        snapshot.get("read_set_digest"),
        snapshot.get("snapshot_digest"),
    )
    watermarks = snapshot.get("watermarks")
    provenance = snapshot.get("provenance")
    return bool(
        isinstance(snapshot.get("epoch"), str)
        and snapshot["epoch"]
        and _is_nonnegative_int(snapshot.get("state_revision"))
        and snapshot.get("ckm_schema_version") == CKM_SCHEMA_VERSION
        and snapshot.get("envelope_schema_version") == ENVELOPE_SCHEMA_VERSION
        and snapshot.get("resource_schema_version") == RESOURCE_SCHEMA_VERSION
        and all(
            isinstance(digest, str) and _CKM_DIGEST.fullmatch(digest)
            for digest in digests
        )
        and snapshot.get("effective_audience") == EFFECTIVE_AUDIENCE
        and snapshot.get("access_policy_version") == ACCESS_POLICY_VERSION
        and snapshot.get("redaction_profile") == REDACTION_PROFILE
        and isinstance(watermarks, Mapping)
        and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in watermarks.items()
        )
        and isinstance(provenance, list)
        and all(isinstance(item, Mapping) for item in provenance)
        and isinstance(completeness, Mapping)
        and completeness.get("complete") is True
        and isinstance(capability_accounting, Mapping)
        and capability_accounting.get("included") == len(resources)
        and all(
            _is_nonnegative_int(capability_accounting.get(field))
            for field in ("included", "filtered", "omitted", "truncated")
        )
        and capability_accounting.get("omitted") == 0
        and capability_accounting.get("truncated") == 0
    )


def _ckm_contribution(reader: ProviderReader) -> dict[str, Any]:
    provider = "ckm"
    authority = {"status": "derived_projection", "authoritative": False}
    try:
        payload = _payload(reader)
        error = payload.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            message = error.get("message")
            details = error.get("details")
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

        projection = payload.get("projection")
        snapshot = payload.get("snapshot")
        resources = payload.get("resources")
        if (
            payload.get("schema_version") != ENVELOPE_SCHEMA_VERSION
            or payload.get("resource_type") != "capability"
            or not isinstance(payload.get("query_digest"), str)
            or not payload["query_digest"]
            or not isinstance(projection, Mapping)
            or projection.get("status") != "derived_projection"
            or projection.get("authoritative") is not False
            or not isinstance(snapshot, Mapping)
            or not isinstance(resources, list)
            or not all(isinstance(resource, Mapping) for resource in resources)
            or not _valid_ckm_snapshot(snapshot, resources)
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
    cockpit_reader: ProviderReader,
    ckm_reader: ProviderReader,
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
