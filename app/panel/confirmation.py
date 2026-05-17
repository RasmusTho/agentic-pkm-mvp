"""Panel confirmation service — runtime-mediated confirm/reject for Panel proposals.

The Companion UI must not write vault files directly. This module owns policy
evaluation, WriteGuard, idempotency, execution delegation, receipts, and the
typed response contract.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.agents.panel_agent.runtime import execute_panel_intent  # noqa: F401 — patchable by tests
from app.events.panel import PanelIntentEvent
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

SAME_TURN_TTL_SECONDS = 5.0


class SameTurnExecutionError(RuntimeError):
    pass


@dataclass
class StagedProposal:
    artifact_id: str
    intent_event: PanelIntentEvent
    proposed_at: float = field(default_factory=time.time)
    trace_id: str = ""


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
            return ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="error",
                outcome="error",
                error="unknown_proposal",
                idempotency_key=request.idempotency_key,
            )

        if proposal.artifact_id != request.artifact_id:
            raise ValueError("proposal does not belong to artifact_id")

        if (time.time() - proposal.proposed_at) < self._ttl:
            raise SameTurnExecutionError(
                "same-turn execution is not allowed — proposal was staged in the current interaction window"
            )

        if request.action == "reject":
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

        try:
            self._guard.assert_writes_allowed("panel.confirm")
        except WritesBlockedError as exc:
            resp = ConfirmResponse(
                proposal_id=request.proposal_id,
                artifact_id=request.artifact_id,
                status="blocked",
                outcome="blocked",
                block_reason=BlockReason(gate="writeguard", message=str(exc)),
                idempotency_key=request.idempotency_key,
            )
            self._idempotency.set(request.idempotency_key, resp)
            return resp

        import app.panel.confirmation as _self_mod

        result = _self_mod.execute_panel_intent(proposal.intent_event)
        events: list[str] = []
        for e in result.emitted_events:
            if isinstance(e, dict):
                events.append(e.get("event", ""))
            else:
                events.append(getattr(e, "event", str(e)))

        now_iso = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        receipt = Receipt(action_taken="confirm", outcome="success", timestamp=now_iso)
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
    "_idempotency_store",
    "_proposal_store",
    "_service",
]
