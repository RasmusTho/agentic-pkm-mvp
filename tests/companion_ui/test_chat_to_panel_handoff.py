"""Tests for the Chat→Panel governance handoff surface in the Companion UI (#1727).

Implements CANVAS_CHAT_SURFACE/SURFACE_CHAT_TO_PANEL_HANDOFF (CHAT-PANEL-HANDOFF-02).

After CHAT-PANEL-HANDOFF-01 (#1726, PR #1731) the runtime returns a structured
governance handoff reference on the governance-bearing co-authoring path:

  HTTP 409 body:
    {
      "status": "routed_to_panel",
      "intent_id": "<hex>",
      "action_type": "frontmatter_update",
      "detail": "..."
    }

and marks the staged Panel proposal with a proposal-scoped origin
``proposal_origin == "canvas_coauthoring"`` (distinct from the vault-note
``NoteRef.origin``).

These tests cover the UI side of the crossing:
- The canvas region stores the handoff ``intent_id``/``action_type`` from the
  structured 409 body and exposes a "view in Panel" affordance keyed to the
  ``intent_id`` only when a reference is present.
- The Panel rail surfaces the server-declared ``proposal_origin`` attribution on
  the matching proposal row.
- Confirmation continues to route through the existing
  ``POST /api/panel/confirm`` path; no new execution path is introduced.
- The UI synthesizes no proposal and infers no governance locally — correlation
  is by server-provided fields only.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
    _proposal_rows_from_panel,
)
from companion_ui.workspace.real_note_workspace_shell import (
    ArtifactNotePayload,
    CanvasCoAuthorRegion,
    RealNoteWorkspaceShell,
)
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
)


# ---------------------------------------------------------------------------
# Fixtures / doubles (mirrors test_canvas_coauthoring_surface.py patterns)
# ---------------------------------------------------------------------------


INTENT_ID = "a1b2c3d4e5f6"
ACTION_TYPE = "frontmatter_update"


def _handoff_409(
    *,
    intent_id: str = INTENT_ID,
    action_type: str = ACTION_TYPE,
) -> WorkspaceClientHTTPError:
    """Build the structured 409 error the runtime returns on the governance path.

    ``WorkspaceClientHTTPError.detail`` carries the raw JSON response body text
    (``resp.text``) per WorkspaceHttpClient.
    """
    body = json.dumps(
        {
            "status": "routed_to_panel",
            "intent_id": intent_id,
            "action_type": action_type,
            "detail": (
                "Governance-bearing — routed to the gated Panel pipeline; "
                "note body left unchanged."
            ),
        }
    )
    return WorkspaceClientHTTPError(409, body)


def _payload(
    artifact_id: str = "note-uuid-1",
    note_path: str = "notes/test.md",
    title: str = "My Test Note",
    body: str = "# My Test Note\n\nBody content here.",
    content_hash: str = "abc123",
) -> ArtifactNotePayload:
    return ArtifactNotePayload(
        artifact_id=artifact_id,
        note_path=note_path,
        title=title,
        body=body,
        content_hash=content_hash,
    )


class _ConfirmRecordingClient:
    """Records the confirm POST so we can assert the existing path is reused."""

    def __init__(self, workspace_payload: dict[str, Any]) -> None:
        self._workspace_payload = workspace_payload
        self.calls: list[dict[str, Any]] = []

    # Only the methods the dev page actually invokes are implemented.
    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"method": "GET", "url": url, "params": params})
        if url == "/api/companion/workspace":
            return self._workspace_payload
        return {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"method": "POST", "url": url, "json": json})
        return {
            "proposal_id": json.get("proposal_id"),
            "artifact_id": json.get("artifact_id"),
            "status": "success",
            "outcome": "success",
        }


def _workspace_payload_with_canvas_proposal() -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-1",
            "note_path": "notes/test.md",
            "title": "My Test Note",
            "body": "# My Test Note",
            "content_hash": "abc123",
        },
        "guards": {"canvas_enabled": True},
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": INTENT_ID,
                    "artifact_id": "note-uuid-1",
                    "description": "promote to evergreen",
                    "status": "staged",
                    "proposal_origin": "canvas_coauthoring",
                    "evidence": {
                        "trigger_summary": "user stated a governance-bearing intent",
                        "action_class": "maturity_transition",
                        "cognition_route": "rule",
                    },
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# AC 1: region stores handoff reference (intent_id + action_type)
# ---------------------------------------------------------------------------


def test_region_stores_handoff_reference() -> None:
    region = CanvasCoAuthorRegion(enabled=True)

    region.handle_coauthor_error(_handoff_409())

    assert region.is_panel_routed is True
    assert region.handoff_intent_id == INTENT_ID
    assert region.handoff_action_type == ACTION_TYPE
    # Governance-bearing — not an applied edit.
    assert region.applied_body is None
    assert region.change_summary is None


# ---------------------------------------------------------------------------
# AC 2: "view in Panel" affordance present only when a reference exists
# ---------------------------------------------------------------------------


def test_region_view_in_panel_affordance_present_with_reference() -> None:
    region = CanvasCoAuthorRegion(enabled=True)

    # No handoff reference yet -> no affordance.
    assert region.view_in_panel_affordance is None
    assert region.has_view_in_panel_affordance is False

    region.handle_coauthor_error(_handoff_409())

    affordance = region.view_in_panel_affordance
    assert region.has_view_in_panel_affordance is True
    assert affordance is not None
    # The affordance is keyed to the server-provided intent_id.
    assert affordance["intent_id"] == INTENT_ID
    assert affordance["action_type"] == ACTION_TYPE

    # A subsequent applied edit clears the handoff reference and its affordance.
    region.render_applied_edit(applied_body="# x", change_summary="y")
    assert region.has_view_in_panel_affordance is False
    assert region.view_in_panel_affordance is None
    assert region.handoff_intent_id is None
    assert region.handoff_action_type is None


# ---------------------------------------------------------------------------
# AC 3: Panel rail renders matching proposal with origin="canvas_coauthoring"
# ---------------------------------------------------------------------------


def test_panel_rail_shows_canvas_origin() -> None:
    panel = _workspace_payload_with_canvas_proposal()["panel"]
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")

    assert len(rows) == 1
    row = rows[0]
    assert row["proposal_id"] == INTENT_ID
    assert row["proposal_origin"] == "canvas_coauthoring"


def test_panel_rail_origin_absent_for_non_canvas_proposal() -> None:
    panel = {
        "proposals": [
            {
                "proposal_id": "prop-x",
                "artifact_id": "note-uuid-1",
                "description": "ordinary panel proposal",
                "status": "staged",
                "evidence": {
                    "trigger_summary": "t",
                    "action_class": "lifecycle.move",
                    "cognition_route": "rule",
                },
            }
        ]
    }
    rows = _proposal_rows_from_panel(panel=panel, artifact_id="note-uuid-1")

    assert len(rows) == 1
    # No server-declared proposal_origin -> attribution is absent (None).
    assert rows[0]["proposal_origin"] is None


# ---------------------------------------------------------------------------
# AC 4: confirmation routes through the existing POST /api/panel/confirm path
# ---------------------------------------------------------------------------


def test_confirm_uses_existing_panel_path() -> None:
    client = _ConfirmRecordingClient(_workspace_payload_with_canvas_proposal())
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    page.load(NoteLoadIntent(note_path="notes/test.md"))

    page.confirm_panel_proposal(
        proposal_id=INTENT_ID,
        artifact_id="note-uuid-1",
        note_path="notes/test.md",
    )

    post_calls = [c for c in client.calls if c["method"] == "POST"]
    assert len(post_calls) == 1
    confirm_call = post_calls[0]
    assert confirm_call["url"] == "/api/panel/confirm"
    assert confirm_call["json"]["proposal_id"] == INTENT_ID
    assert confirm_call["json"]["action"] == "confirm"


# ---------------------------------------------------------------------------
# AC 5: the UI synthesizes no proposal and infers no governance locally
# ---------------------------------------------------------------------------


def test_no_local_proposal_synthesis() -> None:
    """Architecture guard: correlation is by server-provided fields only.

    The region must not infer governance locally — without a server 409 there
    is no handoff reference and no "view in Panel" affordance — and the Panel
    rail must not fabricate a proposal_origin that the server did not declare.
    """
    # No server response -> no handoff state inferred locally.
    region = CanvasCoAuthorRegion(enabled=True)
    assert region.is_panel_routed is False
    assert region.handoff_intent_id is None
    assert region.has_view_in_panel_affordance is False

    # A non-409 error must not be treated as a governance handoff.
    region.handle_coauthor_error(WorkspaceClientHTTPError(500, "boom"))
    assert region.is_panel_routed is False
    assert region.handoff_intent_id is None

    # Panel rail surfaces only server-declared origin; with no proposals there
    # is nothing to synthesize.
    rows = _proposal_rows_from_panel(panel={"proposals": []}, artifact_id="a")
    assert rows == []

    # Static guard: the shell module must not perform direct vault I/O while
    # adding handoff correlation.
    shell_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "real_note_workspace_shell.py"
    )
    tree = ast.parse(shell_file.read_text(encoding="utf-8"))
    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    violations = [
        f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls
    ]
    assert not violations, "shell must not perform direct vault I/O: " + "; ".join(
        violations
    )


def test_shell_canvas_region_exposes_handoff_after_409() -> None:
    """End-to-end through the shell's canvas_region accessor."""
    shell = RealNoteWorkspaceShell(payload=_payload(), canvas_enabled=True)
    region = shell.canvas_region
    region.handle_coauthor_error(_handoff_409())
    assert shell.canvas_region.handoff_intent_id == INTENT_ID
    assert shell.canvas_region.has_view_in_panel_affordance is True
