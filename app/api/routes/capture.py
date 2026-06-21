"""Governed capture append to the vault inbox (SEP-08a, issue #1790).

``POST /api/companion/capture`` is the bounded capture action: friction-free
intake of "things I need to take care of" as a commitment to future-self
appended to the vault inbox note. A capture is plain vault intake — never an
app-owned task: the contract carries no due dates, no app-managed task
states, no reminders (``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
§Resolved Q17). Captured material resurfaces later only by relevance, like
any vault material.

The action rides the existing governed machinery — no parallel write path:

- **policy** — ``WriteGuard`` gates the bounded action
  (``companion.capture.append``); blocked states are explicit 409s, mirroring
  the vault-browser queue-review action.
- **validation** — an explicit schema (``extra="forbid"``) plus a non-empty
  text check; a capture is never silently dropped, and due-date/task-state
  fields are rejected at the schema boundary.
- **deterministic writer** — ``app.knowledge.write_ops.append_note_relative``
  performs the append and returns the runtime ``WriteReceipt``; the
  acknowledgement surfaces that receipt verbatim and is never fabricated by
  the endpoint.
- **event pipeline** — a ``capture.inbox.appended`` outbox event records the
  applied append (JSONL audit log plus DB outbox mirror, same pattern as the
  Panel confirmation service). The payload is metadata-only; the captured
  text itself is durable in the vault, not duplicated into event logs.

vault-inbox note convention (reused from existing repo conventions):

- the inbox directory resolves via ``app.vault.paths.get_vault_inbox_dir_rel``
  (env ``VAULT_INBOX_DIR_REL`` → ``system-settings.yaml paths.inbox_dir_rel``
  → ``vault.layout.md inbox_folder``);
- captures land in ``<inbox_dir_rel>/inbox.md``; ``VAULT_CAPTURE_NOTE_REL``
  overrides the note path (mirrors ``VAULT_CHANGE_LOG_NOTE_REL`` in
  ``app/services/inbox.py``);
- entries reuse the timestamped-bullet line convention from
  ``app/services/inbox.py`` — ``- [<utc-iso>] <text>`` with two-space
  continuation lines for multi-line captures. Deliberately *not* ``- [ ]``
  checkbox syntax: a capture is not a task.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config.paths import resolve_vault_root
from app.events.models import new_trace_id
from app.events.schema import make_outbox_event
from app.governance.governed_write import (
    AuthorityReceipt,
    GovernedWriteAdapter,
    GovernedWriteGrant,
)
from app.knowledge.write_ops import append_note_relative
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import (
    append_jsonl_outbox_event,
    coerce_outbox_event,
    write_outbox_event,
)
from app.vault.paths import get_vault_inbox_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companion", tags=["companion"])

CAPTURE_APPENDED_EVENT = "capture.inbox.appended"
_WRITE_GUARD_ACTION = "companion.capture.append"
_WRITE_CLASS = "vault_capture_append"
_DEFAULT_CAPTURE_NOTE_NAME = "inbox.md"
_EVENT_SOURCE = "companion.capture"
_STATE_OWNER = "knowledge"
_GOVERNED_WRITE_ADAPTER = GovernedWriteAdapter()


class CaptureRequest(BaseModel):
    """A capture is plain text intake.

    ``extra="forbid"`` keeps the contract honest: a due-date or task-state
    field is rejected explicitly (422) instead of being silently discarded.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)


class CaptureResponse(BaseModel):
    """Runtime acknowledgement of a written capture.

    ``operation`` and ``adapter`` are surfaced verbatim from the deterministic
    writer's ``WriteReceipt``; ``note_path`` is the vault-relative inbox
    reference where the capture landed. The endpoint never fabricates an
    acknowledgement — this model is only built from an actual write receipt.
    """

    outcome: Literal["written"] = "written"
    note_path: str
    operation: str
    adapter: str
    captured_at: str
    trace_id: str
    events_emitted: list[str] = Field(default_factory=list)
    governed_write: dict[str, Any] | None = None


def _capture_note_rel(vault_root: Path) -> str:
    override = (os.getenv("VAULT_CAPTURE_NOTE_REL") or "").strip()
    if override:
        return override
    inbox_rel = get_vault_inbox_dir_rel(vault_root)
    return (Path(inbox_rel) / _DEFAULT_CAPTURE_NOTE_NAME).as_posix()


def _compose_entry(text: str, captured_at: str) -> str:
    lines = text.splitlines() or [text]
    first = f"- [{captured_at}] {lines[0]}"
    continuation = [f"  {line}" for line in lines[1:]]
    return "\n".join([first, *continuation]) + "\n"


def _compose_append_entry(
    note_rel: str, text: str, captured_at: str, *, vault_root: Path
) -> str:
    entry = _compose_entry(text, captured_at)
    note_path = (vault_root / note_rel).resolve()
    root = vault_root.resolve()
    try:
        note_path.relative_to(root)
    except ValueError:
        return entry
    if not note_path.exists():
        return entry
    existing = note_path.read_text(encoding="utf-8")
    if existing and not existing.endswith("\n"):
        return "\n" + entry
    return entry


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _governed_write_payload(
    grant: GovernedWriteGrant,
    authority_receipt: AuthorityReceipt,
) -> dict[str, Any]:
    return {
        "policy_decision": asdict(grant.policy_decision),
        "decision_token": asdict(grant.decision_token),
        "authority_receipt": asdict(authority_receipt),
    }


def _emit_capture_event(payload: dict[str, Any], trace_id: str) -> list[str]:
    """Record the applied append on the event pipeline.

    Same dual-sink pattern as the Panel confirmation service: JSONL audit log
    always, DB outbox mirror when a pg backend is configured. Returns the
    emitted event names; sink failures are logged, never silent.
    """
    evt = make_outbox_event(
        event=CAPTURE_APPENDED_EVENT,
        source=_EVENT_SOURCE,
        payload=payload,
        trace_id=trace_id,
    )
    emitted = False
    try:
        emitted = append_jsonl_outbox_event(
            _resolve_outbox_path(), evt, default_source=_EVENT_SOURCE
        )
    except Exception:
        logger.warning("capture event jsonl write failed trace_id=%s", trace_id)

    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = coerce_outbox_event(evt, default_source=_EVENT_SOURCE)
        if outbox_evt is not None:
            try:
                write_outbox_event(outbox_evt, idempotency_key=outbox_evt.event_id)
                emitted = True
            except Exception as exc:
                logger.warning(
                    "capture event db outbox write failed trace_id=%s err=%s",
                    trace_id,
                    exc,
                )

    return [CAPTURE_APPENDED_EVENT] if emitted else []


@router.post("/capture", response_model=CaptureResponse)
def capture_to_inbox(req: CaptureRequest, request: Request) -> CaptureResponse:
    """Append a capture to the vault inbox note through the governed pipeline."""
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()

    # Validation — never silently drop text: whitespace-only is an explicit,
    # named rejection (schema validation already rejected missing/empty text
    # and any due-date/task-state field).
    text = req.text.strip("\n").strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "empty_capture",
                "message": (
                    "Capture text must contain non-whitespace characters; "
                    "nothing was written."
                ),
            },
        )

    # vault-inbox note convention — resolution failures are explicit, the text is
    # never silently dropped.
    vault_root = resolve_vault_root()
    try:
        note_rel = _capture_note_rel(vault_root)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "inbox_convention_unresolved",
                "message": (
                    "The vault inbox note convention could not be resolved; "
                    f"nothing was written. {exc}"
                ),
            },
        ) from exc

    # Policy — the governed-write adapter maps WriteGuard approval to a
    # DecisionToken before the state-owning writer mutates the vault.
    try:
        grant = _GOVERNED_WRITE_ADAPTER.issue_decision_token(
            write_guard=DEFAULT_WRITE_GUARD,
            action=_WRITE_GUARD_ACTION,
            write_class=_WRITE_CLASS,
            actor=_EVENT_SOURCE,
            resource=note_rel,
        )
    except WritesBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "writeguard_blocked",
                "state": "blocked",
                "message": str(exc),
                "reason": exc.reason,
            },
        ) from exc

    # Deterministic writer — the governed append; its WriteReceipt is the
    # runtime acknowledgement.
    captured_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    receipt = append_note_relative(
        note_rel,
        _compose_append_entry(note_rel, text, captured_at, vault_root=vault_root),
        vault_root=vault_root,
    )
    authority_receipt = _GOVERNED_WRITE_ADAPTER.record_authority_receipt(
        decision_token=grant.decision_token,
        mutation_receipt=receipt,
        state_owner=_STATE_OWNER,
        trace_id=trace_id,
    )
    governed_write = _governed_write_payload(grant, authority_receipt)

    # Event pipeline — record the applied append (metadata only).
    events_emitted = _emit_capture_event(
        {
            "note_path": receipt.locator.path,
            "operation": receipt.operation,
            "adapter": receipt.adapter,
            "captured_at": captured_at,
            "decision_token_id": grant.decision_token.token_id,
            "authority_receipt_id": authority_receipt.receipt_id,
            "governed_write": governed_write,
        },
        trace_id=trace_id,
    )

    return CaptureResponse(
        note_path=receipt.locator.path,
        operation=receipt.operation,
        adapter=receipt.adapter,
        captured_at=captured_at,
        trace_id=trace_id,
        events_emitted=events_emitted,
        governed_write=governed_write,
    )


__all__ = ["router", "CaptureRequest", "CaptureResponse", "CAPTURE_APPENDED_EVENT"]
