"""Panel visual shell stub — renderer-agnostic shell model (#1045).

Prototype/staging only.  Not production.  Stub/in-memory data.
No runtime endpoint calls.  No vault writes.  No Canvas Core imports.

This module assembles a PanelShellView from the existing Panel model layer
(render_model, proposal_row, interactions) and exposes the 8 required Panel
states with stub data so a renderer layer (HTML, CLI, or test) can consume
a single dict without knowing the underlying models.

Boundary:
- Panel in Companion UI only.
- NOT Canvas Core.  NOT Canvas bounded suggestion flow.
- No runtime calls.  No vault writes.  Stub data only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from companion_ui.panel.render_model import PanelRenderState, render_panel_state
from companion_ui.panel.proposal_row import (
    ProposalRow,
    ProposalReceipt,
    ProposalEvidence,
    make_stub_proposal_row,
    make_stub_receipt,
)
from companion_ui.panel.interactions import (
    PanelInteractionSession,
    ProposalInteractionState,
)


# ---------------------------------------------------------------------------
# Shell view dataclass
# ---------------------------------------------------------------------------


@dataclass
class PanelShellView:
    """Renderer-agnostic view snapshot for the Panel surface.

    Consumers (HTML renderer, test, CLI) read this dict-serialisable
    snapshot without calling model internals directly.

    All data is stub/in-memory.  No runtime calls are made.
    """

    render: dict
    proposals: list[dict] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    interaction_summary: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "render": self.render,
            "proposals": self.proposals,
            "receipts": self.receipts,
            "interaction_summary": self.interaction_summary,
        }


# ---------------------------------------------------------------------------
# Stub fixture builders (in-memory, no network/vault)
# ---------------------------------------------------------------------------


def _stub_proposals(artifact_id: str) -> list[ProposalRow]:
    return [
        make_stub_proposal_row(
            proposal_id="prop-001",
            artifact_id=artifact_id,
            description="Move note to Projects",
            cognition_route="rule",
        ),
        make_stub_proposal_row(
            proposal_id="prop-002",
            artifact_id=artifact_id,
            description="Add #active tag",
            cognition_route="llm",
        ),
    ]


def _stub_receipt(artifact_id: str, outcome: str = "success") -> ProposalReceipt:
    return make_stub_receipt(
        proposal_id="prop-001",
        artifact_id=artifact_id,
        action_taken="lifecycle.move",
        outcome=outcome,
        message="Note moved to Projects/Q2-arch.md" if outcome == "success" else None,
    )


# ---------------------------------------------------------------------------
# Per-state shell view builders
# ---------------------------------------------------------------------------


def build_idle_view(artifact_id: str) -> PanelShellView:
    rs = PanelRenderState(artifact_id=artifact_id, state="idle")
    return PanelShellView(render=render_panel_state(rs))


def build_running_view(artifact_id: str) -> PanelShellView:
    rs = PanelRenderState(artifact_id=artifact_id, state="running")
    return PanelShellView(render=render_panel_state(rs))


def build_proposals_staged_view(artifact_id: str) -> PanelShellView:
    proposals = _stub_proposals(artifact_id)
    rs = PanelRenderState(
        artifact_id=artifact_id,
        state="proposals-staged",
        proposal_count=len(proposals),
    )
    session = PanelInteractionSession(artifact_id=artifact_id)
    for p in proposals:
        session.register_proposal(p.proposal_id)
    return PanelShellView(
        render=render_panel_state(rs),
        proposals=[p.as_render_dict() for p in proposals],
        interaction_summary=session.summary(),
    )


def build_confirming_view(artifact_id: str) -> PanelShellView:
    proposals = _stub_proposals(artifact_id)
    rs = PanelRenderState(
        artifact_id=artifact_id,
        state="confirming",
        proposal_count=len(proposals),
    )
    session = PanelInteractionSession(artifact_id=artifact_id)
    for p in proposals:
        s = session.register_proposal(p.proposal_id)
    # Simulate user confirming prop-001
    session.get("prop-001").confirm()
    return PanelShellView(
        render=render_panel_state(rs),
        proposals=[p.as_render_dict() for p in proposals],
        interaction_summary=session.summary(),
    )


def build_executing_view(artifact_id: str) -> PanelShellView:
    rs = PanelRenderState(artifact_id=artifact_id, state="executing")
    return PanelShellView(render=render_panel_state(rs))


def build_receipt_displayed_view(artifact_id: str) -> PanelShellView:
    rs = PanelRenderState(artifact_id=artifact_id, state="receipt-displayed")
    receipt = _stub_receipt(artifact_id, outcome="success")
    return PanelShellView(
        render=render_panel_state(rs),
        receipts=[receipt.as_render_dict()],
    )


def build_no_match_view(artifact_id: str, reason: Optional[str] = None) -> PanelShellView:
    msg = reason or "Panel ran but found no actionable proposals for this note."
    rs = PanelRenderState(artifact_id=artifact_id, state="no-match", message=msg)
    return PanelShellView(render=render_panel_state(rs))


def build_blocked_view(artifact_id: str, reason: Optional[str] = None) -> PanelShellView:
    msg = reason or "Execution blocked: WriteGuard denied (tag allowlist)."
    rs = PanelRenderState(artifact_id=artifact_id, state="blocked", message=msg)
    receipt = _stub_receipt(artifact_id, outcome="blocked")
    return PanelShellView(
        render=render_panel_state(rs),
        receipts=[receipt.as_render_dict()],
    )


# ---------------------------------------------------------------------------
# All-states stub catalogue (for visual inspection and tests)
# ---------------------------------------------------------------------------


_PANEL_SHELL_BUILDERS: dict[str, object] = {
    "idle": build_idle_view,
    "running": build_running_view,
    "proposals-staged": build_proposals_staged_view,
    "confirming": build_confirming_view,
    "executing": build_executing_view,
    "receipt-displayed": build_receipt_displayed_view,
    "no-match": build_no_match_view,
    "blocked": build_blocked_view,
}

REQUIRED_PANEL_STATES: frozenset[str] = frozenset(_PANEL_SHELL_BUILDERS)


def build_all_states(artifact_id: str = "note-stub-a") -> dict[str, PanelShellView]:
    """Build stub shell views for all 8 required Panel states.

    Returns a mapping state_name → PanelShellView.
    Stub/in-memory only.  No runtime calls.
    """
    return {
        state: builder(artifact_id)  # type: ignore[operator]
        for state, builder in _PANEL_SHELL_BUILDERS.items()
    }
