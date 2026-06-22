"""Rail ambient-until-active state contract (CUIDR-03, #2446).

The right companion rail has exactly two visual states:

- **Ambient** — a thin strip carried by ``data-rail-state="ambient"`` on the
  workspace layout grid. The note column reclaims the rail's width and is the
  widest column on screen. No permanently-reserved empty third.
- **Active** — full rail width (``data-rail-state="active"``), rendered only
  when the runtime payload carries at least one suggestion, proposal, or
  receipt. Safety-critical states (WriteGuard blocked, canvas recovery_needed,
  actionable reorient-with-items) also keep the rail active.

This is a presentation-only change: the underlying classification (which
proposals/receipts/suggestions exist) still arrives from the runtime payload;
the render never reclassifies or invents content.

These tests are the issue #2446 ``Verify:`` targets. The detailed
parametrised coverage lives in ``test_right_rail_compaction.py``.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(**overrides) -> dict:
    base = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody content here.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "in_memory",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "panel_last_response": {},
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _html(**overrides) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(**overrides),
    )


def _layout_open_tag(html: str) -> str:
    start = html.index('class="workspace-layout workspace-layout--three-col"')
    open_lt = html.rindex("<", 0, start)
    close_gt = html.index(">", start)
    return html[open_lt : close_gt + 1]


# ---------------------------------------------------------------------------
# AC B1 — idle rail is the thin ambient strip; the note column wins.
# ---------------------------------------------------------------------------


def test_idle_rail_is_ambient():
    # Default idle fields: zero proposals, zero suggestions, zero receipts.
    html = _html()
    layout = _layout_open_tag(html)
    assert 'data-rail-state="ambient"' in layout, (
        "idle shell must demote the rail to the ambient strip"
    )
    # The ambient/active width split is governed by CSS keyed on the
    # data-rail-state attribute; the ambient grid keeps the note (centre)
    # column as the widest column. Assert the styling hook exists.
    assert 'data-rail-state="ambient"' in html
    # A non-empty payload must flip the same attribute to active.
    active = _layout_open_tag(_html(panel_proposal_count=1))
    assert 'data-rail-state="active"' in active


# ---------------------------------------------------------------------------
# Rail-active-contract AC — active iff suggestion/proposal/receipt (+ the
# binding safety-critical predicates). No state has content while ambient.
# ---------------------------------------------------------------------------


def test_rail_active_contract():
    # Each content kind alone flips the rail to active.
    proposal = _layout_open_tag(
        _html(
            panel_proposal_count=1,
            panel_proposals=[
                {
                    "proposal_id": "p1",
                    "summary": "Add a link",
                    "action_mode": "confirm_required",
                    "status": "staged",
                }
            ],
        )
    )
    suggestion = _layout_open_tag(_html(suggestion_cards=[{"id": "s1", "text": "t"}]))
    receipt = _layout_open_tag(
        _html(
            panel_last_response={
                "status": "executed",
                "receipt": {
                    "receipt_id": "r1",
                    "outcome": "applied",
                    "message": "done",
                    "persistence": "durable",
                },
            }
        )
    )
    governance_receipt = _layout_open_tag(
        _html(governance_receipts=[{"receipt_id": "r2", "outcome": "applied"}])
    )
    absent = _layout_open_tag(_html())

    assert 'data-rail-state="active"' in proposal
    assert 'data-rail-state="active"' in suggestion
    assert 'data-rail-state="active"' in receipt
    assert 'data-rail-state="active"' in governance_receipt
    assert 'data-rail-state="ambient"' in absent
