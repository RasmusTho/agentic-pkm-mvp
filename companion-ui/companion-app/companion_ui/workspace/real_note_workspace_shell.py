"""Read-only real-note workspace shell (#1064).

Renders an actual vault note/artifact payload as received from the
GET /api/artifacts/note endpoint. Note body is the primary surface;
a reserved secondary slot holds Panel/agent state without requiring Panel data.

This module does NOT:
- read or write vault files directly
- call runtime APIs or Panel confirmation
- render Canvas body-edit controls or bounded suggestion flow
- implement mutation controls of any kind
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Layout region identifiers (data-testid anchors for rendering layers).
REGION_NOTE_BODY = "workspace-note-body"       # primary surface
REGION_NOTE_HEADER = "workspace-note-header"   # title / path / identity strip
REGION_AGENT_RAIL = "workspace-agent-rail"     # secondary slot: Panel / agent state


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

    def __post_init__(self) -> None:
        if not self.payload.artifact_id:
            raise ValueError("artifact_id is required in workspace shell payload")

    # ------------------------------------------------------------------
    # Layout / region contract
    # ------------------------------------------------------------------

    @property
    def regions(self) -> dict[str, str]:
        return {
            REGION_NOTE_BODY:   "primary",
            REGION_NOTE_HEADER: "header",
            REGION_AGENT_RAIL:  "secondary",
        }

    def region_role(self, region: str) -> str:
        if region not in self.regions:
            raise KeyError(f"Unknown workspace layout region: {region!r}")
        return self.regions[region]

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
