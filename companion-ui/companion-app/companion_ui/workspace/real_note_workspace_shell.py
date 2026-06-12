"""Real-note workspace shell with a server-gated Canvas co-authoring region.

Renders an actual vault note/artifact payload as received from the
workspace aggregate artifact block. Note body is the primary surface;
a reserved secondary slot holds Panel/agent state without requiring Panel data.

The base note view stays read-only. A distinct Canvas co-authoring region
(#1717, CANVAS_CHAT_SURFACE/SURFACE_CANVAS_IN_COMPANION_UI) becomes reachable
only when the server-declared ``canvas_enabled`` guard is true; otherwise it
renders an inert disabled state with no mutation affordance. Server declares,
UI renders: this module composes no body locally and never writes the vault —
it only stores and renders bodies the server already applied.

This module does NOT:
- read or write vault files directly
- call runtime APIs (the HTTP client owns transport; this is the render model)
- compose a note body locally or stage a local edit
- render mutation affordances when ``canvas_enabled`` is false
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


# Layout region identifiers (data-testid anchors for rendering layers).
REGION_NOTE_BODY = "workspace-note-body"       # primary surface
REGION_NOTE_HEADER = "workspace-note-header"   # title / path / identity strip
REGION_AGENT_RAIL = "workspace-agent-rail"     # secondary slot: Panel / agent state
REGION_CANVAS_COAUTHOR = "workspace-canvas-coauthor"  # server-gated co-authoring


@dataclass
class ArtifactNotePayload:
    """Typed payload received from the runtime note-read endpoint.

    Mirrors the shape of ArtifactNoteResponse from app/api/routes/artifacts.py.
    The Companion UI consumes this payload; it must not fetch vault files itself.
    """

    artifact_id: str
    note_path: str
    title: str
    body: str
    content_hash: str


@dataclass
class CanvasCoAuthorRegion:
    """Render model for the server-gated Canvas co-authoring region.

    The region is reachable only when the server declares ``canvas_enabled``.
    When disabled it exposes no intent input, no undo affordance, and no
    mutation affordances at all. Server declares, UI renders: this model never
    composes a body locally — ``render_applied_edit`` stores verbatim what the
    server already applied, and a governance-bearing response (HTTP 409) is
    surfaced as routed-to-Panel rather than as an applied edit.

    On the governance-bearing path (CHAT-PANEL-HANDOFF-01/02) the server returns
    a structured handoff reference in the 409 body
    (``status="routed_to_panel"``, ``intent_id``, ``action_type``). The region
    stores that server-provided reference verbatim and exposes a "view in Panel"
    affordance keyed to ``intent_id`` so the user can correlate the canvas
    intent with the staged Panel proposal. It never synthesizes a proposal or
    infers governance locally — correlation is by server-declared fields only.

    Once the staged Panel proposal executes (CHAT-PANEL-HANDOFF-03) and a durable
    receipt exists, ``reflect_receipt`` mirrors that server-declared receipt
    posture (outcome, receipt id/visibility) back into the canvas region keyed by
    ``handoff_intent_id`` — read-only. The region invents no receipt and infers
    no success: if the server projection holds no matching receipt it surfaces a
    pending posture exactly as declared, and a server-declared blocked posture is
    reflected verbatim rather than read as success.
    """

    enabled: bool = False
    applied_body: Optional[str] = field(default=None)
    change_summary: Optional[str] = field(default=None)
    is_panel_routed: bool = field(default=False)
    # Server-provided handoff reference captured from the governance-bearing
    # 409 body. Both remain None until a structured handoff response arrives.
    handoff_intent_id: Optional[str] = field(default=None)
    handoff_action_type: Optional[str] = field(default=None)
    # Server-declared receipt posture reflected back into the canvas region,
    # correlated by ``handoff_intent_id``. None until ``reflect_receipt`` runs
    # against a canvas-originated proposal.
    reflected_receipt: Optional[dict[str, Optional[str]]] = field(default=None)

    @property
    def has_intent_input(self) -> bool:
        return self.enabled

    @property
    def has_undo_affordance(self) -> bool:
        return self.enabled

    @property
    def mutation_affordances(self) -> list[str]:
        """Affordance ids exposed by this region; empty unless enabled."""
        if not self.enabled:
            return []
        return ["canvas-intent-input", "canvas-undo"]

    @property
    def view_in_panel_affordance(self) -> Optional[dict[str, str]]:
        """A "view in Panel" affordance keyed to the server-provided intent_id.

        Present only when a handoff reference exists (i.e. after a structured
        governance-bearing 409). Returns ``None`` otherwise — the UI never
        fabricates a reference. The ``intent_id`` correlates with the staged
        Panel proposal's ``proposal_id``/``proposal_origin`` on the rail.
        """
        if not self.handoff_intent_id:
            return None
        affordance = {"intent_id": self.handoff_intent_id}
        if self.handoff_action_type:
            affordance["action_type"] = self.handoff_action_type
        return affordance

    @property
    def has_view_in_panel_affordance(self) -> bool:
        return self.view_in_panel_affordance is not None

    @property
    def has_reflected_receipt(self) -> bool:
        """True only when a durable, server-declared receipt is reflected.

        A pending or blocked posture is NOT a visible durable receipt; the UI
        must not read either as success.
        """
        return (
            self.reflected_receipt is not None
            and self.reflected_receipt.get("state") == "receipt_visible"
        )

    def reflect_receipt(
        self,
        *,
        receipt_projection: dict[str, dict[str, Any]],
        proposal_origin: Optional[str],
    ) -> None:
        """Reflect the server-declared receipt posture into the canvas region.

        Closes the hybrid loop (CHAT-PANEL-HANDOFF-03): once the canvas-originated
        Panel proposal executes and a durable receipt exists, mirror that receipt
        posture back into the originating context — read-only, server-declared.

        Correlation is strictly by the server-provided ``handoff_intent_id``
        captured from the governance-bearing 409. ``receipt_projection`` is the
        existing receipt-visibility projection (``panel.receipts`` /
        ``receipt_visibility`` from ``app/panel/confirmation.py``) keyed by
        ``intent_id``. Reflection only applies to a canvas-originated proposal
        (``proposal_origin == "canvas_coauthoring"``); other origins are left
        untouched. Nothing is invented:

        - no ``handoff_intent_id`` (no server reference) -> no reflection.
        - non-canvas ``proposal_origin`` -> no reflection.
        - intent_id present but no matching receipt in the projection -> a
          ``pending`` posture (correlated, but no durable receipt yet).
        - matching receipt with a non-blocked visibility -> ``receipt_visible``.
        - matching receipt the server declares blocked -> ``blocked`` posture
          (reflected verbatim, never read as success).
        """
        if not self.handoff_intent_id or proposal_origin != "canvas_coauthoring":
            self.reflected_receipt = None
            return

        record = receipt_projection.get(self.handoff_intent_id)
        if not isinstance(record, dict):
            # Correlated by intent_id but the server holds no durable receipt yet.
            self.reflected_receipt = _pending_receipt_posture(self.handoff_intent_id)
            return

        outcome = record.get("outcome")
        receipt_id = record.get("receipt_id") or None
        visibility = record.get("receipt_visibility") or None
        state = _receipt_state_for(visibility=visibility, outcome=outcome)
        self.reflected_receipt = {
            "intent_id": self.handoff_intent_id,
            "outcome": outcome if isinstance(outcome, str) and outcome else None,
            "receipt_id": receipt_id if isinstance(receipt_id, str) else None,
            "receipt_visibility": (
                visibility if isinstance(visibility, str) else None
            ),
            "state": state,
            "affordance_status": "read-only",
            "authority_role": "server_declared",
        }

    def render_applied_edit(self, *, applied_body: str, change_summary: str) -> None:
        """Store a server-applied edit for rendering (verbatim, no composition)."""
        self.applied_body = applied_body
        self.change_summary = change_summary
        self.is_panel_routed = False
        # An applied edit supersedes any prior panel-routed handoff reference
        # and its reflected receipt posture.
        self.handoff_intent_id = None
        self.handoff_action_type = None
        self.reflected_receipt = None

    def handle_coauthor_error(self, error: "object") -> None:
        """Surface a governance-bearing (HTTP 409) response as routed-to-Panel.

        A 409 means the runtime classified the intent as governance-bearing and
        routed it through the gated pipeline; it is not an applied edit, so any
        previously rendered edit state is cleared.

        When the 409 body carries the structured handoff reference returned by
        CHAT-PANEL-HANDOFF-01 (``intent_id``/``action_type``), the region stores
        those server-provided fields so it can expose a "view in Panel"
        affordance keyed to the staged Panel proposal. The reference is parsed
        from the server response only; nothing is inferred locally.
        """
        status_code = getattr(error, "status_code", None)
        if status_code != 409:
            return
        self.is_panel_routed = True
        self.applied_body = None
        self.change_summary = None
        intent_id, action_type = _parse_handoff_reference(
            getattr(error, "detail", None)
        )
        self.handoff_intent_id = intent_id
        self.handoff_action_type = action_type


def _parse_handoff_reference(detail: Any) -> tuple[Optional[str], Optional[str]]:
    """Extract ``(intent_id, action_type)`` from a structured 409 body.

    The runtime returns the handoff reference as a JSON object in the response
    body (carried verbatim on ``WorkspaceClientHTTPError.detail``):

        {"status": "routed_to_panel", "intent_id": "...",
         "action_type": "...", "detail": "..."}

    Only correlates when the server declares ``status == "routed_to_panel"``;
    legacy/opaque 409 strings degrade to ``(None, None)`` so the region still
    renders routed-to-Panel without fabricating a reference.
    """
    if not isinstance(detail, str) or not detail.strip():
        return (None, None)
    try:
        parsed = json.loads(detail)
    except (ValueError, TypeError):
        return (None, None)
    if not isinstance(parsed, dict):
        return (None, None)
    if parsed.get("status") != "routed_to_panel":
        return (None, None)
    intent_id = parsed.get("intent_id")
    action_type = parsed.get("action_type")
    return (
        intent_id if isinstance(intent_id, str) and intent_id else None,
        action_type if isinstance(action_type, str) and action_type else None,
    )


def _pending_receipt_posture(intent_id: str) -> dict[str, Optional[str]]:
    """A pending posture: correlated by intent_id, but no durable receipt yet.

    Invents nothing — outcome/receipt fields stay ``None`` until the server
    projection carries a durable receipt for this ``intent_id``.
    """
    return {
        "intent_id": intent_id,
        "outcome": None,
        "receipt_id": None,
        "receipt_visibility": None,
        "state": "pending",
        "affordance_status": "read-only",
        "authority_role": "server_declared",
    }


def _receipt_state_for(*, visibility: Optional[Any], outcome: Optional[Any]) -> str:
    """Derive the reflected-receipt state from server-declared fields only.

    Mirrors the receipt-visibility semantics of ``app/panel/confirmation.py``:
    a ``blocked_no_durable_receipt`` / ``none_*`` visibility (or a ``blocked``/
    ``rejected`` outcome) is reflected as a non-durable posture, never inferred
    as success. Anything the server marks durable surfaces as ``receipt_visible``.
    """
    vis = visibility if isinstance(visibility, str) else ""
    out = outcome if isinstance(outcome, str) else ""
    if vis.startswith("blocked") or out in ("blocked", "rejected"):
        return "blocked"
    if vis.startswith("none") or out in ("", "none"):
        return "pending"
    return "receipt_visible"


@dataclass
class RealNoteWorkspaceShell:
    """Model contract for the read-only real-note workspace shell.

    Layout:
    - note body is the primary working surface (REGION_NOTE_BODY = "primary")
    - note header strip carries identity metadata (REGION_NOTE_HEADER = "header")
    - agent rail is the reserved secondary slot for Panel/agent state
      (REGION_AGENT_RAIL = "secondary") — may be empty; presence is mandatory

    Mutation controls are not exposed (is_read_only = True, always).
    """

    payload: ArtifactNotePayload
    # Optional Panel/agent state to display in the secondary rail slot.
    agent_rail_state: Optional[str] = field(default=None)
    # Server-declared guard for the Canvas co-authoring region. The UI never
    # infers this locally; it mirrors guards.canvas_enabled from the runtime.
    canvas_enabled: bool = field(default=False)

    def __post_init__(self) -> None:
        if not self.payload.artifact_id:
            raise ValueError("artifact_id is required in workspace shell payload")
        self._canvas_region = CanvasCoAuthorRegion(enabled=self.canvas_enabled)

    # ------------------------------------------------------------------
    # Layout / region contract
    # ------------------------------------------------------------------

    @property
    def regions(self) -> dict[str, str]:
        layout = {
            REGION_NOTE_BODY:   "primary",
            REGION_NOTE_HEADER: "header",
            REGION_AGENT_RAIL:  "secondary",
        }
        # The co-authoring region only takes layout space when the server
        # declares it enabled; otherwise it renders as an inert disabled state
        # and is not part of the active layout.
        if self.canvas_enabled:
            layout[REGION_CANVAS_COAUTHOR] = "canvas"
        return layout

    def region_role(self, region: str) -> str:
        if region not in self.regions:
            raise KeyError(f"Unknown workspace layout region: {region!r}")
        return self.regions[region]

    # ------------------------------------------------------------------
    # Canvas co-authoring region (server-gated)
    # ------------------------------------------------------------------

    @property
    def canvas_region(self) -> CanvasCoAuthorRegion:
        """Server-gated Canvas co-authoring render model.

        Always present as a render model; ``enabled`` reflects the
        server-declared ``canvas_enabled`` guard. When disabled it exposes no
        mutation affordances.
        """
        return self._canvas_region

    # ------------------------------------------------------------------
    # Identity / content accessors
    # ------------------------------------------------------------------

    @property
    def artifact_id(self) -> str:
        return self.payload.artifact_id

    @property
    def note_path(self) -> str:
        return self.payload.note_path

    @property
    def title(self) -> str:
        return self.payload.title

    @property
    def body(self) -> str:
        return self.payload.body

    @property
    def content_hash(self) -> str:
        return self.payload.content_hash

    # ------------------------------------------------------------------
    # Read-only guard
    # ------------------------------------------------------------------

    @property
    def is_read_only(self) -> bool:
        """Workspace shell is always read-only; no mutation controls are rendered."""
        return True

    @property
    def mutation_controls(self) -> list:
        """No mutation controls exposed from this shell."""
        return []

    # ------------------------------------------------------------------
    # Agent rail slot
    # ------------------------------------------------------------------

    @property
    def has_agent_rail(self) -> bool:
        """Secondary rail slot is always present (may be empty)."""
        return True

    @property
    def agent_rail_is_empty(self) -> bool:
        return self.agent_rail_state is None
