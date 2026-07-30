"""Meeting session lifecycle + gap report HTTP surface (CDLM-02, issue #4385).

Three routes over `app.heimdal.meeting_ledger`, which owns every semantic:

- ``POST /api/heimdal/meeting/session`` — open a session, idempotent by the
  client-minted ``session_id``; a re-post replays the recorded outcome.
- ``POST /api/heimdal/meeting/{session_id}/close`` — record the declared final
  segment count; idempotent, and sessions never re-open.
- ``GET /api/heimdal/meeting/{session_id}/segments`` — the gap report:
  received sequence set, missing holes, close state, completeness, per-segment
  receipt refs, and needs-attention conflicts (INV-CDLM-9).

Posture matches the governed media ingress routes (same vertical, same
clients): LAN / loopback / tailnet peers only, refused with 403
`public_ingress_refused` otherwise — enforced by the same
`_assert_lan_posture` the capture routes use, so the two surfaces cannot
drift apart.

Named error states:

| Status | `error` | Meaning |
| --- | --- | --- |
| 403 | `public_ingress_refused` | Peer outside the LAN/loopback/tailnet posture |
| 404 | `meeting_session_unknown` | No ledger record for the named session |
| 422 | (FastAPI validation) | Malformed body/params |
| 500 | `meeting_ledger_failed` | Ledger write/read failed; nothing recorded |
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.heimdal_capture import _assert_lan_posture, _trace_id
from app.heimdal import meeting_ledger
from app.heimdal.media_ingress import iso_timestamp
from app.heimdal.meeting_ledger import MeetingSession, MeetingSessionNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/heimdal/meeting", tags=["heimdal"])


class OpenSessionRequest(BaseModel):
    """Client-minted session identity plus opaque template selection."""

    session_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    template_selection: Dict[str, Any] = Field(default_factory=dict)


class CloseSessionRequest(BaseModel):
    """The client's declared final segment count for the session."""

    final_seq_count: int = Field(ge=0)


class SessionResponse(BaseModel):
    """One session's recorded lifecycle state."""

    session_id: str
    device_id: str
    template_selection: Dict[str, Any]
    opened_at: str
    closed: bool
    final_seq_count: Optional[int] = None
    closed_at: Optional[str] = None
    idempotent_replay: bool | None = None
    trace_id: str


def _session_response(
    session: MeetingSession, *, replay: bool, trace_id: str
) -> SessionResponse:
    return SessionResponse(
        session_id=session.session_id,
        device_id=session.device_id,
        template_selection=session.template_selection,
        opened_at=iso_timestamp(session.opened_at),
        closed=session.closed,
        final_seq_count=session.final_seq_count,
        closed_at=iso_timestamp(session.closed_at) if session.closed_at else None,
        idempotent_replay=True if replay else None,
        trace_id=trace_id,
    )


def _session_unknown(session_id: str, trace_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error": "meeting_session_unknown",
            "message": (
                f"session {session_id!r} has no ledger record; open it via "
                "POST /api/heimdal/meeting/session first."
            ),
            "trace_id": trace_id,
        },
    )


def _ledger_failed(exc: Exception, trace_id: str) -> HTTPException:
    logger.error("meeting ledger operation failed trace_id=%s err=%s", trace_id, exc)
    return HTTPException(
        status_code=500,
        detail={
            "error": "meeting_ledger_failed",
            "message": (
                f"The meeting ledger could not complete the operation "
                f"({type(exc).__name__}). Retry — every operation on this surface "
                "is idempotent."
            ),
            "trace_id": trace_id,
        },
    )


@router.post("/session", response_model=SessionResponse, response_model_exclude_none=True)
def open_session(request: Request, body: OpenSessionRequest) -> SessionResponse:
    """Open a meeting session, idempotent by the client-minted identity."""
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)
    try:
        session, created = meeting_ledger.open_meeting_session(
            session_id=body.session_id,
            device_id=body.device_id,
            template_selection=body.template_selection,
            trace_id=trace_id,
        )
    except Exception as exc:
        # Raw driver errors (sqlite3/psycopg) propagate from the stores too;
        # every failure on this surface must carry the named
        # `meeting_ledger_failed` shape rather than an unnamed 500.
        raise _ledger_failed(exc, trace_id) from exc
    return _session_response(session, replay=not created, trace_id=trace_id)


@router.post(
    "/{session_id}/close",
    response_model=SessionResponse,
    response_model_exclude_none=True,
)
def close_session(
    request: Request, session_id: str, body: CloseSessionRequest
) -> SessionResponse:
    """Close a session; a re-post replays the recorded close outcome."""
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)
    try:
        session, newly_closed = meeting_ledger.close_meeting_session(
            session_id=session_id, final_seq_count=body.final_seq_count
        )
    except MeetingSessionNotFoundError as exc:
        raise _session_unknown(session_id, trace_id) from exc
    except Exception as exc:
        # Raw driver errors (sqlite3/psycopg) propagate from the stores too;
        # every failure on this surface must carry the named
        # `meeting_ledger_failed` shape rather than an unnamed 500.
        raise _ledger_failed(exc, trace_id) from exc
    return _session_response(session, replay=not newly_closed, trace_id=trace_id)


@router.get("/{session_id}/segments")
def gap_report(request: Request, session_id: str) -> Dict[str, Any]:
    """The gap report: what the hub durably holds for this session (INV-CDLM-9)."""
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)
    try:
        report = meeting_ledger.build_gap_report(session_id)
    except MeetingSessionNotFoundError as exc:
        raise _session_unknown(session_id, trace_id) from exc
    except Exception as exc:
        # Raw driver errors (sqlite3/psycopg) propagate from the stores too;
        # every failure on this surface must carry the named
        # `meeting_ledger_failed` shape rather than an unnamed 500.
        raise _ledger_failed(exc, trace_id) from exc
    report["trace_id"] = trace_id
    return report


__all__ = ["router", "OpenSessionRequest", "CloseSessionRequest", "SessionResponse"]
