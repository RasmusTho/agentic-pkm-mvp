"""⌘K Panel command palette — a presentation of the Panel rail (#1786, SEP-04).

The palette is **a presentation of Panel, not new authority**
(`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Surface composition (NORMATIVE
table)`, `§Intent vocabulary`, `docs/SYSTEM_ENTRY_POINT/PANEL_COMMAND_PALETTE.md`):

- same server-declared proposal objects as the rail, keyed by
  `data-proposal-id` (never rendered position);
- confirm declares the existing `POST /api/panel/confirm` flow — no
  palette-local execution path, no receipt invention;
- a WriteGuard-denied proposal renders the calm guard-held state per
  `companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md` (gate, reason, intent
  preserved), never a generic error;
- the palette is visually and behaviorally distinct from chat: a callout
  states Panel ≠ Chat; no composer; the input only filters declared
  proposals (exact grammar deferred — package Q12);
- it mounts on the shared overlay host as the `cmd` occupant (#1785) and
  dismisses to the document anchor via the host (Esc / scrim).
"""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.overlay_host import SHIPPED_OVERLAY_OCCUPANTS
from companion_ui.workspace.panel_palette import (
    PALETTE_OVERLAY_ID,
    filter_palette_rows,
    palette_row_model,
)
from companion_ui.workspace.serve_dev_page import render_index_html

# ---------------------------------------------------------------------------
# Fixtures (mirror the proven workspace fixture in test_overlay_host)
# ---------------------------------------------------------------------------


def _proposal(
    proposal_id: str,
    *,
    description: str,
    action_class: str = "lifecycle.move",
    status: str = "staged",
    affordances: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """One server-declared proposal in the normalized render-fields shape."""
    return {
        "proposal_id": proposal_id,
        "artifact_id": "art-1786",
        "description": description,
        "evidence": {
            "trigger_summary": f"Trigger for {proposal_id}",
            "action_class": action_class,
            "cognition_route": "rule",
        },
        "status": status,
        "proposal_origin": None,
        "reflected_receipt": None,
        "affordances": affordances
        or {"confirm": True, "correct": True, "reject": True},
    }


def _proposals() -> list[dict[str, Any]]:
    return [
        _proposal(
            "prop-move-1",
            description="Move note to Projects",
            action_class="lifecycle.move",
        ),
        _proposal(
            "prop-tag-2",
            description="Add status tag evergreen",
            action_class="metadata.tag",
            affordances={"confirm": True, "correct": False, "reject": True},
        ),
    ]


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-1786",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "proposals-staged",
        "panel_proposal_count": 2,
        "panel_proposals": _proposals(),
        "panel_message": "",
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


def _render(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _palette(html: str) -> str:
    m = re.search(
        r"<!-- panel-palette \(#1786, SEP-04\) -->(.*?)<!-- /panel-palette -->",
        html,
        re.S,
    )
    assert m, "panel palette markup must render"
    return m.group(1)


def _palette_script(html: str) -> str:
    m = re.search(
        r"/\* panel-palette-controller \*/(.*?)/\* /panel-palette-controller \*/",
        html,
        re.S,
    )
    assert m, "panel palette controller script must render"
    return m.group(1)


def _rail_action_buttons(html: str) -> list[str]:
    return re.findall(
        r'<button[^>]*data-testid="workspace-panel-action"[^>]*>', html
    )


def _palette_action_buttons(palette: str) -> list[str]:
    return re.findall(
        r'<button[^>]*data-testid="palette-proposal-action"[^>]*>', palette
    )


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', tag)
    assert m, f"{name} missing on {tag}"
    return m.group(1)


def _actions_by_proposal(buttons: list[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for tag in buttons:
        grouped.setdefault(_attr(tag, "data-proposal-id"), set()).add(
            _attr(tag, "data-panel-action")
        )
    return grouped


# ---------------------------------------------------------------------------
# AC1: the palette renders the same server-declared proposal set as the rail
# with identical data-proposal-ids, status, and actions
# ---------------------------------------------------------------------------


def test_palette_renders_same_proposals_as_rail() -> None:
    html = _render()
    palette = _palette(html)

    # The palette is the host's `cmd` occupant — registered, not invented.
    assert PALETTE_OVERLAY_ID == "cmd"
    assert PALETTE_OVERLAY_ID in SHIPPED_OVERLAY_OCCUPANTS

    rail_rows = re.findall(
        r'<div[^>]*data-testid="workspace-panel-proposal-row".*?'
        r'data-proposal-id="([^"]+)"',
        html,
        re.S,
    )
    palette_rows = re.findall(
        r'<li[^>]*data-testid="palette-proposal-row"[^>]*>', palette
    )
    palette_ids = [_attr(row, "data-proposal-id") for row in palette_rows]

    # Identical proposal set, keyed by id — the overlay-grammar continuity
    # rule: the same proposal object shows the same identity on both surfaces.
    assert set(palette_ids) == set(rail_rows) == {"prop-move-1", "prop-tag-2"}
    assert len(palette_ids) == len(set(palette_ids)), "ids must not repeat"

    # Identical status, and the server-declared class tag on every row.
    for row in palette_rows:
        assert _attr(row, "data-proposal-status") == "staged"
    by_id = {_attr(r, "data-proposal-id"): r for r in palette_rows}
    assert _attr(by_id["prop-move-1"], "data-action-class") == "lifecycle.move"
    assert _attr(by_id["prop-tag-2"], "data-action-class") == "metadata.tag"

    # Identical actions per proposal: what the rail enables, the palette
    # enables — nothing more (asserted, not assumed).
    rail_actions = _actions_by_proposal(_rail_action_buttons(html))
    palette_actions = _actions_by_proposal(_palette_action_buttons(palette))
    assert palette_actions == rail_actions
    assert palette_actions["prop-move-1"] == {"confirm", "reject", "correct"}
    assert palette_actions["prop-tag-2"] == {"confirm", "reject"}


# ---------------------------------------------------------------------------
# AC2: confirm routes through POST /api/panel/confirm and surfaces the runtime
# receipt — no palette-local execution or receipt invention
# ---------------------------------------------------------------------------


def test_palette_confirm_routes_through_panel_confirm() -> None:
    html = _render()
    palette = _palette(html)

    # Every palette action declares the rail's confirm transport — the same
    # endpoint, the same method, the same proposal/artifact identity.
    buttons = _palette_action_buttons(palette)
    assert buttons, "palette must render proposal actions"
    for tag in buttons:
        assert _attr(tag, "data-api-method") == "POST"
        assert _attr(tag, "data-api-path") == "/api/panel/confirm"
        assert _attr(tag, "data-proposal-id")
        assert _attr(tag, "data-artifact-id") == "art-1786"
    confirm_buttons = [t for t in buttons if 'data-panel-action="confirm"' in t]
    assert confirm_buttons, "palette must render the confirm affordance"
    for tag in confirm_buttons:
        # The declared entry/shell intent for governed confirm (spec §Intent
        # vocabulary: `panel.confirm` — surface "Panel (rail or palette)").
        assert _attr(tag, "data-intent") == "panel.confirm"

    # No palette-local execution: the palette controller performs no I/O and
    # declares no alternate endpoint — Panel transport stays with the rail's
    # declared flow.
    script = _palette_script(html)
    for forbidden in ("fetch(", "XMLHttpRequest", "/api/", "form.submit",
                      "location.href", "location.assign"):
        assert forbidden not in script, f"palette controller must not use {forbidden}"

    # The runtime receipt surfaces exactly as the rail surfaces it: same
    # server-declared receipt fields, rendered only when declared.
    executed = _render(
        panel_last_response={
            "proposal_id": "prop-move-1",
            "artifact_id": "art-1786",
            "status": "executed",
            "outcome": "success",
            "receipt": {
                "outcome": "success",
                "message": "note moved to Projects",
                "timestamp": "2026-06-10T12:00:00Z",
            },
        }
    )
    executed_palette = _palette(executed)
    assert 'data-testid="palette-receipt"' in executed_palette
    assert 'data-receipt-persistence="durable-runtime-projection"' in executed_palette
    assert "success" in executed_palette
    assert "note moved to Projects" in executed_palette
    assert "2026-06-10T12:00:00Z" in executed_palette
    # The rail surfaces the same receipt — one receipt, two presentations.
    assert 'data-testid="workspace-panel-receipt"' in executed
    assert "note moved to Projects" in executed

    # No receipt invention: without a server-declared receipt there is none.
    assert 'data-testid="palette-receipt"' not in _palette(_render())


# ---------------------------------------------------------------------------
# AC3: a guard-denied proposal renders the calm guard-held blocked state with
# gate and reason — distinct from a generic error
# ---------------------------------------------------------------------------


def test_blocked_proposal_renders_guard_held_state() -> None:
    blocked = _render(
        panel_last_response={
            "proposal_id": "prop-move-1",
            "artifact_id": "art-1786",
            "status": "blocked",
            "outcome": "blocked",
            "block_reason": {
                "gate": "writeguard",
                "message": "Cross-note writes outside the allowlist are held.",
            },
        }
    )
    palette = _palette(blocked)

    # Calm guard-held state: named gate, reason text, intent preserved
    # (BLOCKED_AND_STALE_STATE_SPEC.md §Blocked — WriteGuard / policy).
    held = re.search(
        r'<div[^>]*data-testid="palette-blocked"[^>]*>.*?</div>', palette, re.S
    )
    assert held, "palette must render the guard-held blocked state"
    block = held.group(0)
    assert 'data-guard-held="true"' in block
    assert 'data-guard-gate="writeguard"' in block
    assert "Cross-note writes outside the allowlist are held." in block
    assert "Intent preserved" in block
    assert "nothing was mutated" in block

    # Distinct from a generic error: no error-state classes, no alarm copy.
    assert "error-state" not in palette
    assert "Error:" not in block
    assert 'class="error' not in block

    # A WriteGuard-blocked workspace holds the rows themselves calmly: the
    # affordance is guard-held, never a dead button or an error.
    guard = _render(guard_writeguard_status="blocked")
    guard_palette = _palette(guard)
    assert 'data-testid="palette-proposal-held"' in guard_palette
    held_rows = re.findall(
        r'<span[^>]*data-testid="palette-proposal-held"[^>]*>[^<]*</span>',
        guard_palette,
    )
    for row in held_rows:
        assert 'data-guard-held="true"' in row
        assert 'data-guard-gate="writeguard"' in row
    assert "intent preserved" in guard_palette.lower()
    assert "error" not in guard_palette.lower()


# ---------------------------------------------------------------------------
# AC4: the palette contains no chat composer and renders the Panel ≠ Chat
# distinction
# ---------------------------------------------------------------------------


def test_palette_is_not_a_chat_surface() -> None:
    html = _render()
    palette = _palette(html)

    # The authority separation renders: Panel ≠ Chat, stated on the surface.
    callout = re.search(
        r'<p[^>]*data-testid="palette-not-chat-callout"[^>]*>(.*?)</p>',
        palette,
        re.S,
    )
    assert callout, "palette must render the Panel ≠ Chat callout"
    assert "Panel ≠ Chat" in callout.group(1)
    assert "no free-text generation" in callout.group(1)

    # The palette presents Panel authority — declared, not inferred.
    root = re.search(r'<div[^>]*data-testid="panel-palette"[^>]*>', palette)
    assert root, "palette root must render"
    assert _attr(root.group(0), "data-authority-surface") == "panel"
    assert _attr(root.group(0), "data-presentation-of") == "panel-rail"
    assert _attr(root.group(0), "data-overlay-id") == "cmd"

    # No conversational composer: no textarea, no form, no send affordance.
    assert "<textarea" not in palette
    assert "<form" not in palette
    assert "composer" not in palette.lower()
    assert "rail.send" not in palette

    # The single input is a filter over declared proposals (grammar deferred
    # to package Q12) — never a free-text generation surface.
    inputs = re.findall(r"<input[^>]*>", palette)
    assert len(inputs) == 1
    assert _attr(inputs[0], "data-testid") == "palette-filter-input"
    assert _attr(inputs[0], "data-input-role") == "filter"
    assert _attr(inputs[0], "type") == "search"

    # The controller never generates or sends free text anywhere.
    script = _palette_script(html)
    for forbidden in ("rail.send", "/api/canvas", "coauthor", "fetch("):
        assert forbidden not in script


# ---------------------------------------------------------------------------
# AC5: proposal identity comes from data-proposal-id, never rendered position
# ---------------------------------------------------------------------------


def test_proposal_identity_from_id_not_position() -> None:
    # Pure model: filtering selects by content but identity stays keyed by
    # proposal_id, regardless of input order.
    rows = [
        palette_row_model(p, writeguard_blocked=False) for p in _proposals()
    ]
    hit = filter_palette_rows(rows, "evergreen")
    assert [r["proposal_id"] for r in hit] == ["prop-tag-2"]
    reversed_hit = filter_palette_rows(list(reversed(rows)), "evergreen")
    assert [r["proposal_id"] for r in reversed_hit] == ["prop-tag-2"]
    # Empty/blank query: every declared proposal, identity unchanged.
    assert {r["proposal_id"] for r in filter_palette_rows(rows, "  ")} == {
        "prop-move-1",
        "prop-tag-2",
    }

    # Rendered identity is attached to the row, not its position: reversing
    # the server-declared order moves the rows, never re-keys them.
    proposals = _proposals()
    html_forward = _palette(_render(panel_proposals=proposals))
    html_reversed = _palette(
        _render(panel_proposals=list(reversed(_proposals())))
    )
    for palette in (html_forward, html_reversed):
        move_row = re.search(
            r'<li[^>]*data-proposal-id="prop-move-1"[^>]*>.*?</li>',
            palette,
            re.S,
        )
        assert move_row and "Move note to Projects" in move_row.group(0)
        tag_row = re.search(
            r'<li[^>]*data-proposal-id="prop-tag-2"[^>]*>.*?</li>',
            palette,
            re.S,
        )
        assert tag_row and "Add status tag evergreen" in tag_row.group(0)

    # No positional identity anywhere: no index-derived attributes, and every
    # actionable button carries its own explicit proposal identity.
    for palette in (html_forward, html_reversed):
        assert "data-option-index" not in palette
        assert "data-row-index" not in palette
        for tag in _palette_action_buttons(palette):
            assert _attr(tag, "data-proposal-id") in {
                "prop-move-1",
                "prop-tag-2",
            }

    # The controller filters by hiding rows; it never re-keys identity from
    # position (no children[]/index lookups on the list).
    script = _palette_script(_render())
    for forbidden in ("children[", "rowIndex", ".index", "nth-child"):
        assert forbidden not in script
