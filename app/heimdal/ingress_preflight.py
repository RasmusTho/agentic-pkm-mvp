"""Startup preflight for the governed ingress lanes' raw-store key (#4422).

The media (`POST /api/heimdal/capture/media`) and screen
(`POST /api/heimdal/screen/capture`) ingress lanes encrypt through the raw
store, so they need ``HEIMDAL_RAW_STORE_KEY`` in the api process. Before this
preflight, a missing key was invisible until the first upload returned the
named 500 — a dead lane that looked calm (#4369's failure class).

Posture is **degrade-visibly, never fail-exit**: the api process also serves
search, ask, note-read, and text capture, so a missing key must not take the
runtime down. The preflight runs once from the api lifespan, records a named
result, logs loudly when the lanes are unavailable, and surfaces the lane
state on ``/api/status`` — the request-time ``raw_store_key_unavailable``
contract in the routes is unchanged and remains the per-request truth.

Never logs, stores, or echoes key material — only availability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from app.heimdal.raw_store import RawStoreKeyMissingError, resolve_raw_store_key

logger = logging.getLogger(__name__)

LANE_MEDIA = "media_ingress"
LANE_SCREEN = "screen_capture"
_KEY_LANES = (LANE_MEDIA, LANE_SCREEN)

STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class IngressPreflightResult:
    """One recorded preflight outcome (no key material, ever)."""

    raw_store_key_available: bool
    lanes: Dict[str, str] = field(default_factory=dict)
    detail: str = ""
    checked_at: Optional[datetime] = None


_LAST_RESULT: Optional[IngressPreflightResult] = None


def run_ingress_preflight() -> IngressPreflightResult:
    """Check the raw-store key once and record the lane availability.

    Called from the api lifespan startup. Never raises and never exits the
    process: an unavailable key is a named, logged, surfaced degradation of
    exactly the ingress lanes, not a runtime failure.
    """
    global _LAST_RESULT
    try:
        resolve_raw_store_key()
        available = True
        detail = ""
    except RawStoreKeyMissingError as exc:
        available = False
        detail = str(exc)
    except Exception as exc:  # malformed key material etc. — same degradation
        available = False
        detail = f"{type(exc).__name__}: {exc}"

    state = STATE_AVAILABLE if available else STATE_UNAVAILABLE
    result = IngressPreflightResult(
        raw_store_key_available=available,
        lanes={lane: state for lane in _KEY_LANES},
        detail=detail,
        checked_at=datetime.now(timezone.utc),
    )
    _LAST_RESULT = result
    if not available:
        logger.error(
            "Heimdal ingress preflight: HEIMDAL_RAW_STORE_KEY is not available to "
            "this process — the media and screen ingress lanes will refuse every "
            "admission with the named raw_store_key_unavailable 500 until it is "
            "provisioned (host secret contract consumer 'api'). All other API "
            "functions keep serving. Detail: %s",
            detail,
        )
    else:
        logger.info("Heimdal ingress preflight: raw-store key available; ingress lanes ready.")
    return result


def current_ingress_status() -> Optional[IngressPreflightResult]:
    """The last recorded preflight result, or None before startup ran it."""
    return _LAST_RESULT


def reset_ingress_preflight() -> None:
    """Test-only reset."""
    global _LAST_RESULT
    _LAST_RESULT = None


__all__ = [
    "LANE_MEDIA",
    "LANE_SCREEN",
    "STATE_AVAILABLE",
    "STATE_UNAVAILABLE",
    "IngressPreflightResult",
    "current_ingress_status",
    "reset_ingress_preflight",
    "run_ingress_preflight",
]
