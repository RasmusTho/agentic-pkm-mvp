"""Concrete PanelPipeline for canvas-origin governance proposals.

Replaces the inline _StubPipeline in app/api/routes/canvas.py.
Each governance action becomes a StagedProposal in the Panel ProposalStore
so the Companion UI can later confirm or reject it via POST /api/panel/confirm.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelEventSource,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.panel.confirmation import ProposalStore, StagedProposal

class CanvasPanelPipeline:
    """Route a canvas governance intent into the Panel ProposalStore.

    Instantiate once per request, capturing the note's artifact_id so the
    staged proposal carries the correct note identity for later confirmation.

    The staged proposal_id is returned as the governance intent_id; the
    Companion UI uses it as proposal_id when calling POST /api/panel/confirm,
    with artifact_id equal to the note_path relative to vault_root.
    """

    #: Proposal-scoped origin recorded on every canvas-originated Panel proposal.
    #: This is distinct from the vault-note/frontmatter ``origin`` field; it marks
    #: the *proposal* as canvas co-authoring provenance for Panel attribution.
    PROPOSAL_ORIGIN = "canvas_coauthoring"

    def __init__(self, proposal_store: ProposalStore, artifact_id: str, note_path: str) -> None:
        self._store = proposal_store
        self._artifact_id = artifact_id
        self._note_path = note_path

    @staticmethod
    def _instruction(action_type: str, payload: dict[str, Any]) -> str:
        """Human-facing proposal instruction for Panel review.

        When the payload carries the original natural-language request (#1772),
        surface it alongside the coarse action type so reviewing the proposal
        shows what the human actually asked for. Falls back to the generic form
        when no request text was carried (e.g. explicit ``/governance`` calls
        with caller-supplied payloads).
        """
        original_request = payload.get("original_request")
        if isinstance(original_request, str) and original_request.strip():
            return f'canvas governance: {action_type} — "{original_request.strip()}"'
        return f"canvas governance: {action_type}"

    def submit_intent(
        self,
        action_type: str,
        payload: dict[str, Any],
        session_id: str,
    ) -> str:
        proposal_id = uuid4().hex
        intent_event = PanelIntentEvent(
            source=PanelEventSource(component="canvas", trigger="governance"),
            payload=PanelIntentPayload(
                note=NoteRef(
                    uuid=self._artifact_id,
                    path=self._note_path,
                    origin=f"canvas/{session_id}",
                ),
                panel=PanelInfo(
                    panel_id=proposal_id,
                    instruction=self._instruction(action_type, payload),
                ),
                actions=[
                    PanelIntentAction(
                        id=proposal_id,
                        label=action_type,
                        checked=True,
                        mapping=PanelActionMapping(
                            id=action_type,
                            intent_type=action_type,
                            downstream_event="panel.governance.requested",
                            trust_verb="APPLY",
                            params=payload,
                        ),
                    )
                ],
            ),
        )
        self._store.stage(
            proposal_id,
            StagedProposal(
                artifact_id=self._artifact_id,
                intent_event=intent_event,
                trace_id=proposal_id,
                proposal_origin=self.PROPOSAL_ORIGIN,
            ),
        )
        return proposal_id


__all__ = ["CanvasPanelPipeline"]
