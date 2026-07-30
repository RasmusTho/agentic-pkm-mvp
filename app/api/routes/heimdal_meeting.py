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

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.heimdal_capture import _assert_lan_posture, _trace_id
from app.events.schema import make_outbox_event
from app.events.types import HEIMDAL_MEETING_USER_NOTE_WRITTEN
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services import outbox as outbox_service
from app.heimdal import meeting_blocks, meeting_ledger, meeting_projection
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

    final_seq_count: int = Field(ge=0, le=meeting_ledger.MAX_SESSION_SEQ)


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


class UserNoteRequest(BaseModel):
    """One user-note write: client-minted identity, client-monotonic revision."""

    note_block_id: str = Field(min_length=1)
    revision: int = Field(ge=1, le=1_000_000)
    text: str = Field(max_length=1_000_000)
    editor_identity: str = Field(min_length=1)


class UserNoteResponse(BaseModel):
    """The durable acknowledgement for one user-note revision."""

    outcome: str = "written"
    session_id: str
    note_block_id: str
    revision: int
    content_sha256: str
    idempotent_replay: bool | None = None
    trace_id: str


@router.post(
    "/{session_id}/user-note",
    response_model=UserNoteResponse,
    response_model_exclude_none=True,
)
def write_user_note(
    request: Request, session_id: str, body: UserNoteRequest
) -> UserNoteResponse:
    """Write one user-note revision through the ownership guard (CDLM-07).

    Idempotent by ``(note_block_id, revision)``; the 2xx exists only after the
    block content is durably written AND the ``heimdal.meeting.user_note.written``
    event is committed — the CDLM-01 ack-ordering family — so the client can
    retain-until-ack and resend safely. The write passes the shared block
    guard as the user's editor identity; a refusal (e.g. the block id belongs
    to a derived block) is a named 409 with content untouched.
    """
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)
    try:
        session = meeting_ledger.get_meeting_session(session_id)
        if session is None:
            raise MeetingSessionNotFoundError(session_id)

        writer = meeting_blocks.WriterIdentity(
            kind=meeting_blocks.WRITER_USER_EDITOR,
            editor_identity=body.editor_identity,
        )

        # Idempotent replay: the stored revision is the acknowledgement — but
        # the replay is still fully authorized through the guard (a wrong
        # editor, a derived block id, or a foreign session must never collect
        # a success ack by replaying identical text), and a reused revision
        # number carrying different text is a named conflict, not a false ack.
        existing = meeting_blocks.get_note_revision(body.note_block_id, body.revision)
        if existing is not None:
            replay_auth = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=writer,
                action=meeting_blocks.ACTION_REVISE,
                block_id=body.note_block_id,
                content=meeting_blocks.get_block(body.note_block_id).content
                if meeting_blocks.get_block(body.note_block_id)
                else body.text,
            )
            if not replay_auth.allowed:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "block_write_refused",
                        "message": replay_auth.reason,
                        "state": "not_acknowledged",
                        "trace_id": trace_id,
                    },
                )
            if existing["text"] != body.text:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "note_revision_conflict",
                        "message": (
                            f"revision {body.revision} of this note was already "
                            "acknowledged with different text; revisions are "
                            "immutable — send the new text as the next revision."
                        ),
                        "trace_id": trace_id,
                    },
                )
            digest = hashlib.sha256(existing["text"].encode("utf-8")).hexdigest()
            return UserNoteResponse(
                session_id=session_id,
                note_block_id=body.note_block_id,
                revision=body.revision,
                content_sha256=digest,
                idempotent_replay=True,
                trace_id=trace_id,
            )

        # Client-monotonic revisions: a new write must advance past every
        # acknowledged revision of this note (gaps allowed); a lower or equal
        # number that is not an exact replay is stale.
        history = meeting_blocks.note_revisions(body.note_block_id)
        latest_acked = max((rev["revision"] for rev in history), default=0)
        if body.revision <= latest_acked:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "stale_note_revision",
                    "message": (
                        f"revision {body.revision} is not ahead of the latest "
                        f"acknowledged revision {latest_acked}; note revisions are "
                        "client-monotonic."
                    ),
                    "trace_id": trace_id,
                },
            )

        block = meeting_blocks.get_block(body.note_block_id)
        if block is None:
            outcome = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=writer,
                action=meeting_blocks.ACTION_CREATE,
                block_id=body.note_block_id,
                block_type=meeting_blocks.TYPE_USER_NOTE,
                content=body.text,
            )
        else:
            # The guard authorizes and treats same-content revises as replays
            # internally; the route never bypasses it.
            outcome = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=writer,
                action=meeting_blocks.ACTION_REVISE,
                block_id=body.note_block_id,
                content=body.text,
            )
        if not outcome.allowed:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "block_write_refused",
                    "message": outcome.reason,
                    "state": "not_acknowledged",
                    "trace_id": trace_id,
                },
            )

        digest = hashlib.sha256(body.text.encode("utf-8")).hexdigest()
        if not _emit_user_note_event(
            {
                "session_id": session_id,
                "note_block_id": body.note_block_id,
                "revision": body.revision,
                "editor_identity": body.editor_identity,
                "content_sha256": digest,
            },
            trace_id=trace_id,
        ):
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "note_event_commit_failed",
                    "state": "not_acknowledged",
                    "message": (
                        "The user-note event could not be committed, so the revision "
                        "was not acknowledged. Re-send the same note_block_id and "
                        "revision — the write is idempotent."
                    ),
                    "trace_id": trace_id,
                },
            )

        meeting_blocks.insert_note_revision(
            body.note_block_id, body.revision, body.text, body.editor_identity
        )
        return UserNoteResponse(
            session_id=session_id,
            note_block_id=body.note_block_id,
            revision=body.revision,
            content_sha256=digest,
            trace_id=trace_id,
        )
    except MeetingSessionNotFoundError as exc:
        raise _session_unknown(session_id, trace_id) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _ledger_failed(exc, trace_id) from exc


def _emit_user_note_event(payload: Dict[str, Any], *, trace_id: str) -> bool:
    """Commit the user-note event; True once at least one sink persisted it.

    Same sink discipline as the admission seam (`media_ingress._emit_admission_event`).
    """
    evt = make_outbox_event(
        event=HEIMDAL_MEETING_USER_NOTE_WRITTEN,
        source="heimdal.meeting.blocks",
        payload=payload,
        trace_id=trace_id,
    )
    emitted = False
    try:
        emitted = outbox_service.append_jsonl_outbox_event(
            _resolve_note_outbox_path(), evt, default_source="heimdal.meeting.blocks"
        )
    except Exception as exc:
        logger.warning("user-note event jsonl write failed trace_id=%s err=%s", trace_id, exc)
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = outbox_service.coerce_outbox_event(
            evt, default_source="heimdal.meeting.blocks"
        )
        if outbox_evt is not None:
            try:
                outbox_service.write_outbox_event(
                    outbox_evt,
                    idempotency_key=outbox_service.derive_idempotency_key(
                        outbox_evt.event,
                        f"{payload['note_block_id']}\x1f{payload['revision']}",
                        str(payload["content_sha256"]),
                    ),
                )
                emitted = True
            except Exception as exc:
                logger.warning(
                    "user-note event db outbox write failed trace_id=%s err=%s",
                    trace_id,
                    exc,
                )
    return emitted


def _resolve_note_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


@router.get("/{session_id}/projection")
def projection(request: Request, session_id: str) -> Dict[str, Any]:
    """The iPad's poll target (CDLM-06): transcript + analysis projections.

    Side-effect-free: assembles from the ledger and durable projection state,
    derives nothing. Blocks are explicitly revisable projections, never
    canonical truth (INV-CDLM-5) — every block carries revision, derived_from,
    template, and engine provenance.
    """
    trace_id = _trace_id(request)
    _assert_lan_posture(request, trace_id)
    try:
        report = meeting_projection.build_projection(session_id)
    except MeetingSessionNotFoundError as exc:
        raise _session_unknown(session_id, trace_id) from exc
    except Exception as exc:
        raise _ledger_failed(exc, trace_id) from exc
    report["trace_id"] = trace_id
    return report


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
