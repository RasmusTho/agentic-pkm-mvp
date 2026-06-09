"""Panel confirmation service — runtime-mediated confirm/reject for Panel proposals.

The Companion UI must not write vault files directly. This module owns policy
evaluation, WriteGuard, idempotency, execution delegation, receipts, and the
typed response contract.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agents.panel_agent.runtime import execute_panel_intent  # noqa: F401 — patchable by tests
from app.agents.panel.writeback import (
    annotate_action_ids,
    remove_actions_from_markdown,
    stable_action_id,
    write_receipts,
)
from app.events.panel import PanelIntentEvent
from app.events.schema import make_outbox_event
from app.outbox.events import INDEX_OUTBOX_PATH
from app.services.outbox import append_jsonl_outbox_event, coerce_outbox_event, write_outbox_event
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

logger = logging.getLogger(__name__)

SAME_TURN_TTL_SECONDS = 5.0


class SameTurnExecutionError(RuntimeError):
    pass


class UnknownProposalError(LookupError):
    pass


@dataclass
class StagedProposal:
    artifact_id: str
    intent_event: PanelIntentEvent
    proposed_at: float = field(default_factory=time.time)
    trace_id: str = ""
    # Proposal-scoped provenance — which surface staged this Panel proposal
    # (e.g. "canvas_coauthoring"). Distinct from the vault-note/frontmatter
    # ``origin`` field; Panel attribution must never overwrite artifact origin.
    proposal_origin: str | None = None


class CorrectionFields(BaseModel):
    enabled: bool = False
    corrected_action_id: str | None = None
    corrected_parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _require_correction_payload(self) -> "CorrectionFields":
        if self.enabled and self.corrected_action_id is None and self.corrected_parameters is None:
            raise ValueError(
                "correction.enabled=true requires corrected_action_id or corrected_parameters"
            )
        return self


class ConfirmRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    action: str
    idempotency_key: str = Field(min_length=1)
    correction: CorrectionFields | None = None

    @model_validator(mode="after")
    def _validate_action(self) -> "ConfirmRequest":
        if self.action not in ("confirm", "reject"):
            raise ValueError(f"action must be 'confirm' or 'reject', got '{self.action}'")
        return self


class Receipt(BaseModel):
    action_taken: str
    outcome: str
    timestamp: str
    message: str | None = None
    inverse_action: str | None = None


class BlockReason(BaseModel):
    gate: str
    message: str
    code: str | None = None


def _receipt_visibility_for(status: str) -> str:
    """Map a confirm outcome to its receipt-visibility posture.

    This is the receipt step of the inspect -> queue -> confirm -> receipt
    operational loop. The posture is a projection of where the durable receipt
    lives; it is not the durable authority store. Durable receipts are written
    to the vault AI-status callout by the runtime.
    """
    if status in ("executed", "logged"):
        return "durable_vault_visible"
    if status == "blocked":
        return "blocked_no_durable_receipt"
    if status == "rejected":
        return "none_rejected"
    return "none"


class ConfirmResponse(BaseModel):
    proposal_id: str
    artifact_id: str
    status: str
    outcome: str
    receipt: Receipt | None = None
    block_reason: BlockReason | None = None
    error: str | None = None
    idempotency_key: str
    events_emitted: list[str] = Field(default_factory=list)
    # Receipt-visibility posture for the operational loop. Derived from status
    # when not explicitly provided; the UI surfaces this as visibility, not as
    # durable approval/execution authority.
    receipt_visibility: str = ""

    @model_validator(mode="after")
    def _derive_receipt_visibility(self) -> "ConfirmResponse":
        if not self.receipt_visibility:
            self.receipt_visibility = _receipt_visibility_for(self.status)
        return self


class ProposalStore:
    def __init__(self) -> None:
        self._proposals: dict[str, StagedProposal] = {}

    def stage(self, proposal_id: str, proposal: StagedProposal) -> None:
        self._proposals[proposal_id] = proposal

    def get(self, proposal_id: str) -> StagedProposal | None:
        return self._proposals.get(proposal_id)

    def clear(self) -> None:
        self._proposals.clear()


class ConfirmIdempotencyStore:
    def __init__(self) -> None:
        self._cache: dict[str, ConfirmResponse] = {}

    def get(self, key: str) -> ConfirmResponse | None:
        return self._cache.get(key)

    def set(self, key: str, response: ConfirmResponse) -> None:
        self._cache[key] = response

    def clear(self) -> None:
        self._cache.clear()


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path(INDEX_OUTBOX_PATH)


def _emit_projection_event(
    event_name: str,
    payload: dict[str, Any],
    trace_id: str,
    outbox_path: Path | None = None,
) -> None:
    evt = make_outbox_event(
        event=event_name,
        source="panel_agent.confirmation",
        payload=payload,
        trace_id=trace_id,
    )
    # Write to JSONL audit log
    resolved = outbox_path or _resolve_outbox_path()
    try:
        append_jsonl_outbox_event(resolved, evt, default_source="panel_agent.confirmation")
    except Exception:
        logger.debug("projection event jsonl write skipped event=%s", event_name)
    # Mirror to DB outbox when backend is pg (same pattern as panel_agent/runtime.py)
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    db_url = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if backend == "pg" or db_url:
        outbox_evt = coerce_outbox_event(evt, default_source="panel_agent.confirmation")
        if outbox_evt is not None:
            try:
                write_outbox_event(outbox_evt, idempotency_key=outbox_evt.event_id)
            except Exception as exc:
                logger.debug("projection event db outbox write skipped event=%s err=%s", event_name, exc)


def _resolve_note_file(note_path: str | None) -> Path | None:
    if not note_path:
        return None
    vault_root_env = os.getenv("VAULT_ROOT") or os.getenv("WATCHER_VAULT_PATH")
    candidate = Path(note_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if vault_root_env:
        candidate = Path(vault_root_env).expanduser() / note_path
        if candidate.exists():
            return candidate
    return None


def _write_rejected_projection(proposal: StagedProposal) -> None:
    """Remove the proposed checkbox from the vault on rejection (no execution receipt)."""
    note_path = proposal.intent_event.payload.note.path
    note_file = _resolve_note_file(note_path)
    if note_file is None:
        return
    try:
        current = note_file.read_text(encoding="utf-8")
    except OSError:
        return

    action_ids = {
        stable_action_id(a.label)
        for a in proposal.intent_event.payload.actions
    }
    annotated = annotate_action_ids(current)
    updated = remove_actions_from_markdown(annotated, action_ids)

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    receipt_lines = [
        f"❌ {a.label} — dismissed — {now_iso}"
        for a in proposal.intent_event.payload.actions
    ]
    if receipt_lines:
        updated = write_receipts(updated, receipt_lines)

    try:
        note_file.write_text(updated, encoding="utf-8")
    except OSError:
        logger.debug("rejected projection vault write failed note_path=%s", note_path)


def _apply_correction(
    intent_event: "PanelIntentEvent",
    correction: CorrectionFields,
) -> "PanelIntentEvent":
    """Return a deep copy of intent_event with the correction applied.

    If correction.corrected_action_id is set, that action becomes the selected
    action for confirmation. If corrected_parameters is also set, parameters are
    merged into the selected action only. The original proposal is never mutated.
    """
    corrected = intent_event.model_copy(deep=True)
    for action in corrected.payload.actions:
        target = correction.corrected_action_id is None or action.id == correction.corrected_action_id
        if correction.corrected_action_id is not None:
            action.checked = target
        if target and correction.corrected_parameters is not None and action.mapping is not None:
            action.mapping.params = {**action.mapping.params, **correction.corrected_parameters}
    return corrected


def _write_blocked_projection(
    proposal: StagedProposal,
    gate: str,
    reason: str,
) -> None:
    """Write blocked receipt to AI status callout; preserve the proposed checkbox."""
    note_path = proposal.intent_event.payload.note.path
    note_file = _resolve_note_file(note_path)
    if note_file is None:
        return
    try:
        current = note_file.read_text(encoding="utf-8")
    except OSError:
        return

    now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    receipt_lines = [
        f"🚫 {a.label} — blocked — gate: {gate} — {now_iso}"
        for a in proposal.intent_event.payload.actions
    ]
    if reason:
        receipt_lines.append(f"Reason: {reason}")

    updated = write_receipts(current, receipt_lines)
    try:
        note_file.write_text(updated, encoding="utf-8")
    except OSError:
        logger.debug("blocked projection vault write failed note_path=%s", note_path)


class PanelConfirmationService:
    def __init__(
        self,
        proposal_store: ProposalStore,
        idempotency_store: ConfirmIdempotencyStore,
        write_guard: WriteGuard | None = None,
        same_turn_ttl: float = SAME_TURN_TTL_SECONDS,
    ) -> None:
        self._proposals = proposal_store
        self._idempotency = idempotency_store
        self._guard = write_guard or DEFAULT_WRITE_GUARD
        self._ttl = same_turn_ttl

    def confirm(self, request: ConfirmRequest) -> ConfirmResponse:
        cached = self._idempotency.get(request.idempotency_key)
        if cached is not None:
            return cached

        proposal = self._proposals.get(request.proposal_id)
        if proposal is None:
            raise UnknownProposalError(request.proposal_id)

        if proposal.artifact_id != request.artifact_id:
            raise ValueError("proposal does not belong to artifact_id")

        if (time.time() - proposal.proposed_at) < self._ttl:
            raise SameTurnExecutionError(
                "same-turn execution is not allowed — proposal was staged in the current interaction window"
            )

        try:
            self._guard.assert_writes_allowed("panel.confirm")
        except WritesBlockedError as exc:
            if request.action == "reject":
                # Rejection is a user decision, not an execution; vault write is safe even when
                # execution is blocked, but we still honour WriteGuard to keep the single-writer
                # rule uniform. Skip vault write; record rejected outcome without receipt.
                resp = ConfirmResponse(
                    proposal_id=request.proposal_id,
                    artifact_id=request.artifact_id,
                    status="rejected",
                    outcome="rejected",
                    idempotency_key=request.idempotency_key,
                    events_emitted=[],
                )
                self._idempotency.set(request.idempotency_key, resp)
                return resp
            _write_blocked_projection(
                proposal,
                gate="writeguard",
                reason=str(exc),
            )
            _emit_projection_event(
                "panel.action.blocked",
                {
                    "note_uuid": proposal.intent_event.payload.note.uuid,
                    "note_path": proposal.intent_event.payload.note.path,
                    "gate": "writeguard",
                    "reason": str(exc),
                    "proposal_id": request.proposal_id,
                },
                trace_id=proposal.trace_id or request.idempotency_key,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="blocked",
                outcome="blocked",
                block_reason=BlockReason(gate="writeguard", message=str(exc)),
                idempotency_key=request.idempotency_key,
                events_emitted=["panel.action.blocked"],
            )
            self._idempotency.set(request.idempotency_key, resp)
            return resp

        if request.action == "reject":
            _write_rejected_projection(proposal)
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="rejected",
                outcome="rejected",
                idempotency_key=request.idempotency_key,
                events_emitted=[],
            )
            self._idempotency.set(request.idempotency_key, resp)
            return resp

        import app.panel.confirmation as _self_mod

        if request.correction and request.correction.enabled:
            corrected_event = _apply_correction(proposal.intent_event, request.correction)
            result = _self_mod.execute_panel_intent(corrected_event)
        else:
            result = _self_mod.execute_panel_intent(proposal.intent_event)
        events: list[str] = []
        for e in result.emitted_events:
            if isinstance(e, dict):
                events.append(e.get("event", ""))
            else:
                events.append(getattr(e, "event", str(e)))

        # Classify outcome: if all checked actions were logged (not triggered), surface as logged.
        checked_actions = [a for a in result.actions if a.checked]
        all_logged = bool(checked_actions) and all(a.status == "logged" for a in checked_actions)
        any_triggered = any(a.status == "triggered" for a in checked_actions)

        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

        is_corrected = bool(request.correction and request.correction.enabled)
        correction_note = "corrected" if is_corrected else None

        if all_logged and not any_triggered:
            # Logged outcome: emit panel.action.logged if not already present
            if "panel.action.logged" not in events:
                _emit_projection_event(
                    "panel.action.logged",
                    {
                        "note_uuid": proposal.intent_event.payload.note.uuid,
                        "note_path": proposal.intent_event.payload.note.path,
                        "proposal_id": request.proposal_id,
                    },
                    trace_id=proposal.trace_id or request.idempotency_key,
                )
                events.append("panel.action.logged")
            receipt = Receipt(
                action_taken="confirm",
                outcome="logged",
                timestamp=now_iso,
                message=correction_note,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="logged",
                outcome="logged",
                receipt=receipt,
                idempotency_key=request.idempotency_key,
                events_emitted=events,
            )
        else:
            # Executed outcome: extract inverse_action from result if declared.
            inverse_action: str | None = None
            for action_result in result.actions:
                inv = (action_result.details or {}).get("inverse_action_id")
                if inv:
                    inverse_action = str(inv)
                    break

            receipt = Receipt(
                action_taken="confirm",
                outcome="success",
                timestamp=now_iso,
                inverse_action=inverse_action,
                message=correction_note,
            )
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="executed",
                outcome="success",
                receipt=receipt,
                idempotency_key=request.idempotency_key,
                events_emitted=events,
            )

        self._idempotency.set(request.idempotency_key, resp)
        return resp


_proposal_store = ProposalStore()
_idempotency_store = ConfirmIdempotencyStore()
_service = PanelConfirmationService(_proposal_store, _idempotency_store)

__all__ = [
    "BlockReason",
    "ConfirmIdempotencyStore",
    "ConfirmRequest",
    "ConfirmResponse",
    "PanelConfirmationService",
    "ProposalStore",
    "Receipt",
    "SameTurnExecutionError",
    "StagedProposal",
    "UnknownProposalError",
    "_idempotency_store",
    "_proposal_store",
    "_service",
]
