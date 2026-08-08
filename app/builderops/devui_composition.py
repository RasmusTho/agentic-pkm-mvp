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
from typing import Any

from app.builderops.ckm.contracts import ErrorEnvelope, ResultEnvelope


CONTRACT_VERSION = "devui.composition.v1"
logger = logging.getLogger(__name__)
_CKM_REFUSAL_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CKM_REFUSAL_MESSAGE = "CKM refused the read request"


CockpitReader = Callable[[], Mapping[str, Any]]
CkmReader = Callable[[], ResultEnvelope | ErrorEnvelope]
Now = Callable[[], datetime]


def _cockpit_payload(reader: CockpitReader) -> Mapping[str, Any]:
    result = reader()
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
        payload = result.to_dict()
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
