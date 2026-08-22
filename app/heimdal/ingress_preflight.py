"""Startup preflight for the governed ingress lanes' runtime preconditions (#4422, #4492).

The media (`POST /api/heimdal/capture/media`) and screen
(`POST /api/heimdal/screen/capture`) ingress lanes encrypt through the raw
store, so they need ``HEIMDAL_RAW_STORE_KEY`` in the api process. Before this
preflight, a missing key was invisible until the first upload returned the
named 500 — a dead lane that looked calm (#4369's failure class).

The media lane has a second precondition (#4492): its standing consent grant
(`consent_ledger.MEDIA_CAPTURE_SCOPE`, seeded by migration `a9f3c2d7b6e1`).
Without it every admission refuses with the named 409 `consent_refused`, which
is the *same* invisible-dead-lane shape — a database that never ran the
migration, or a lane whose grant was revoked, looks calm until the first
upload. Checking it here is the `AGENTS.md :: Required rules`
invariant→producers preflight for that seeded grant.

The check is a read against the ledger and liveness authority and never
grants, revokes, or repairs consent or raw state **in production**. One caveat worth naming: under
``STORE_SCHEMA_AUTOCREATE=1`` (a test-fixture opt-in, `tests/conftest.py`) the
Postgres ledger backend bootstraps its own schema and standing-grant seeds on
construction — and `consent_ledger._backend()` constructs a fresh
`_PgConsentLedger` per call — so in that environment resolving the grant can
create the table and seed it, meaning the preflight cannot report
`media_consent_grant_missing` for a missing table there. Production never sets
that flag and takes `consent_ledger._assert_pg_schema` instead, so the read-only
property holds on the path that matters.

Posture is **degrade-visibly, never fail-exit**: the api process also serves
search, ask, note-read, and text capture, so a missing precondition must not
take the runtime down. The preflight runs once from the api lifespan, records a
named result, logs loudly when a lane is unavailable, and surfaces the lane
state on ``/api/status`` — the request-time ``raw_store_key_unavailable`` /
``consent_refused`` contracts in the routes are unchanged and remain the
per-request truth.

Never logs, stores, or echoes key material — only availability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.heimdal import raw_liveness
from app.heimdal.consent_ledger import MEDIA_CAPTURE_SCOPE, resolve_active_grant
from app.heimdal.raw_store import RawStoreKeyMissingError, resolve_raw_store_key

logger = logging.getLogger(__name__)

LANE_MEDIA = "media_ingress"
LANE_SCREEN = "screen_capture"

STATE_AVAILABLE = "available"
STATE_UNAVAILABLE = "unavailable"

# Named detail classes. Never an exception message: a future error embedding
# env material must not flow to the status surface.
DETAIL_RAW_STORE_KEY_MISSING = "raw_store_key_missing"
DETAIL_RAW_STORE_KEY_INVALID = "raw_store_key_invalid"
DETAIL_MEDIA_CONSENT_GRANT_MISSING = "media_consent_grant_missing"
DETAIL_MEDIA_CONSENT_LEDGER_UNREADABLE = "media_consent_ledger_unreadable"
DETAIL_RAW_LIVENESS_SCHEMA_UNAVAILABLE = "raw_liveness_schema_unavailable"


@dataclass(frozen=True)
class IngressPreflightResult:
    """One recorded preflight outcome (no key material, ever).

    ``detail`` is a comma-joined list of named detail classes, empty when every
    checked precondition holds. Two preconditions can fail at once, so it is
    never a single cause.
    """

    raw_store_key_available: bool
    raw_liveness_schema_available: bool
    # Required, not defaulted: an omitted precondition must not read as
    # "available". Every precondition is load-bearing for the affected lanes.
    media_consent_grant_available: bool
    lanes: Dict[str, str] = field(default_factory=dict)
    detail: str = ""
    checked_at: Optional[datetime] = None


_LAST_RESULT: Optional[IngressPreflightResult] = None


def _check_raw_store_key(details: List[str]) -> bool:
    try:
        resolve_raw_store_key()
        return True
    except RawStoreKeyMissingError:
        details.append(DETAIL_RAW_STORE_KEY_MISSING)
    except Exception as exc:  # malformed key material etc. — same degradation
        details.append(f"{DETAIL_RAW_STORE_KEY_INVALID}:{type(exc).__name__}")
    return False


def _check_media_consent_grant(details: List[str]) -> bool:
    """Whether the media lane's standing consent grant resolves right now.

    A read-only ledger query. An unreadable ledger (no migration, DSN down) is
    reported as its own named class rather than conflated with "revoked": the
    operator remedies differ.
    """
    try:
        grant = resolve_active_grant(scope=MEDIA_CAPTURE_SCOPE)
    except Exception as exc:
        details.append(f"{DETAIL_MEDIA_CONSENT_LEDGER_UNREADABLE}:{type(exc).__name__}")
        return False
    if grant is None:
        details.append(DETAIL_MEDIA_CONSENT_GRANT_MISSING)
        return False
    return True


def _check_raw_liveness_schema(details: List[str]) -> bool:
    """Whether the durable liveness authority is ready for raw ingress."""
    try:
        raw_liveness.assert_runtime_schema()
        return True
    except Exception as exc:
        details.append(f"{DETAIL_RAW_LIVENESS_SCHEMA_UNAVAILABLE}:{type(exc).__name__}")
        return False


def run_ingress_preflight() -> IngressPreflightResult:
    """Check every ingress-lane precondition once and record lane availability.

    Called from the api lifespan startup. Never raises and never exits the
    process: an unavailable precondition is a named, logged, surfaced
    degradation of exactly the affected ingress lane, not a runtime failure.
    """
    global _LAST_RESULT
    details: List[str] = []
    key_available = _check_raw_store_key(details)
    liveness_schema_available = _check_raw_liveness_schema(details)
    # The screen lane's `screen_always_on` scope carries no seeded grant, so
    # this check is the media lane's alone.
    media_grant_available = _check_media_consent_grant(details)

    raw_available = key_available and liveness_schema_available
    media_available = raw_available and media_grant_available
    result = IngressPreflightResult(
        raw_store_key_available=key_available,
        raw_liveness_schema_available=liveness_schema_available,
        lanes={
            LANE_MEDIA: STATE_AVAILABLE if media_available else STATE_UNAVAILABLE,
            LANE_SCREEN: STATE_AVAILABLE if raw_available else STATE_UNAVAILABLE,
        },
        detail=",".join(details),
        checked_at=datetime.now(timezone.utc),
        media_consent_grant_available=media_grant_available,
    )
    _LAST_RESULT = result
    if not key_available:
        logger.error(
            "Heimdal ingress preflight: HEIMDAL_RAW_STORE_KEY is not available to "
            "this process — the media and screen ingress lanes will refuse every "
            "admission with the named raw_store_key_unavailable 500 until it is "
            "provisioned (host secret contract consumer 'heimdal-api-ingress'). All other API "
            "functions keep serving. Detail: %s",
            result.detail,
        )
    if not media_grant_available:
        # Two causes, two remedies — do not give the operator the wrong one.
        if DETAIL_MEDIA_CONSENT_LEDGER_UNREADABLE in result.detail:
            remedy = (
                "the consent ledger could not be read at all: the "
                "heimdal_consent_grant table is absent (migration c4f7a1b2d9e3 "
                "never ran) or the database is unreachable. Check the DSN, then "
                "run 'alembic upgrade head'"
            )
        else:
            remedy = (
                "no active grant covers the scope: most often this database has "
                "not yet run migration a9f3c2d7b6e1 (run 'alembic upgrade head'); "
                "otherwise the grant was revoked and must be re-granted"
            )
        logger.error(
            "Heimdal ingress preflight: media ingress lane unavailable for scope "
            "%r — every admission will refuse with the named 409 consent_refused "
            "until this is resolved. %s. All other API functions keep serving. "
            "Detail: %s",
            MEDIA_CAPTURE_SCOPE,
            remedy,
            result.detail,
        )
    if not liveness_schema_available:
        logger.error(
            "Heimdal ingress preflight: raw-liveness authority is unavailable; "
            "media and screen ingress lanes will refuse admissions until the current "
            "raw/liveness migrations are applied with 'alembic upgrade head'. All other "
            "API functions keep serving. Detail: %s",
            result.detail,
        )
    if key_available and liveness_schema_available and media_grant_available:
        logger.info(
            "Heimdal ingress preflight: raw-store key and media consent grant "
            "available; ingress lanes ready."
        )
    return result


def current_ingress_status() -> Optional[IngressPreflightResult]:
    """The last recorded preflight result, or None before startup ran it."""
    return _LAST_RESULT


def reset_ingress_preflight() -> None:
    """Test-only reset."""
    global _LAST_RESULT
    _LAST_RESULT = None


__all__ = [
    "DETAIL_MEDIA_CONSENT_GRANT_MISSING",
    "DETAIL_MEDIA_CONSENT_LEDGER_UNREADABLE",
    "DETAIL_RAW_STORE_KEY_INVALID",
    "DETAIL_RAW_STORE_KEY_MISSING",
    "DETAIL_RAW_LIVENESS_SCHEMA_UNAVAILABLE",
    "LANE_MEDIA",
    "LANE_SCREEN",
    "STATE_AVAILABLE",
    "STATE_UNAVAILABLE",
    "IngressPreflightResult",
    "current_ingress_status",
    "reset_ingress_preflight",
    "run_ingress_preflight",
]
