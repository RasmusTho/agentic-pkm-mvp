"""Concrete PanelPipeline for canvas-origin governance proposals.

Replaces the inline _StubPipeline in app/api/routes/canvas.py.
Each governance action becomes a StagedProposal in the Panel ProposalStore
so the Companion UI can later confirm or reject it via POST /api/panel/confirm.
"""

from __future__ import annotations

import uuid
from typing import Any

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

# Stable namespace for deterministic note UUIDs derived from note paths.
_CANVAS_NS = uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")


def _note_uuid_from_path(note_path: str) -> str:
    return str(uuid.uuid5(_CANVAS_NS, note_path))


class CanvasPanelPipeline:
    """Route a canvas governance intent into the Panel ProposalStore.

    Instantiate once per request, capturing the note's artifact_id so the
    staged proposal carries the correct note identity for later confirmation.

    The staged proposal_id is returned as the governance intent_id; the
    Companion UI uses it as proposal_id when calling POST /api/panel/confirm,
    with artifact_id equal to the note_path relative to vault_root.
    """

    def __init__(self, proposal_store: ProposalStore, artifact_id: str) -> None:
        self._store = proposal_store
        self._artifact_id = artifact_id

    def submit_intent(
        self,
        action_type: str,
        payload: dict[str, Any],
        session_id: str,
    ) -> str:
        proposal_id = uuid.uuid4().hex
        intent_event = PanelIntentEvent(
            source=PanelEventSource(component="canvas", trigger="governance"),
            payload=PanelIntentPayload(
                note=NoteRef(
                    uuid=_note_uuid_from_path(self._artifact_id),
                    path=self._artifact_id,
                    origin=f"canvas/{session_id}",
                ),
                panel=PanelInfo(
                    panel_id=proposal_id,
                    instruction=f"canvas governance: {action_type}",
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
            ),
        )
        return proposal_id


__all__ = ["CanvasPanelPipeline"]
