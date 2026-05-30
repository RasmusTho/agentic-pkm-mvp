"""Single adaptive workspace layout contract (#1397).

Establishes the base workspace geometry and scroll-ownership contract from
``companion-ui/docs/ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md`` §§3, 7, 10, 12:

- one left context/navigation panel slot;
- one central note slot that stays primary;
- one optional/collapsible right companion rail slot;
- an app shell that owns no page scroll (``height:100dvh; overflow:hidden``);
- the central note surface owns the primary reading scroll, with
  ``min-height:0`` on scroll containers and no nested double-scroll that
  clips the note body at the bottom of the viewport.

These are structural/CSS contract tests against the rendered dev-page HTML.
They do not assert pixel rendering; real-browser behaviour is covered by the
UAT checklist (handoff §12).
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


# ---------------------------------------------------------------------------
# Fixture (mirrors the proven shell fixture in test_workspace_shell_alignment)
# ---------------------------------------------------------------------------


def _fields(
    *,
    body: str = "# Note\n\n" + "\n\n".join(f"Paragraph {i}." for i in range(40)),
    title: str = "Note Title",
    note_path: str = "Notes/note.md",
    panel_state: str = "idle",
    panel_proposal_count: int = 0,
    panel_proposals: list | None = None,
    panel_message: str = "",
) -> dict:
    return {
        "title": title,
        "note_path": note_path,
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": body,
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": panel_state,
        "panel_proposal_count": panel_proposal_count,
        "panel_proposals": panel_proposals or [],
        "panel_message": panel_message,
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


def _html(**kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=kw.get("note_path", "Notes/note.md"),
        fields=_fields(**kw),
    )


def _css_block(css: str, selector_re: str) -> str:
    """Return the declaration body of a top-level (4-space indented) CSS rule.

    ``selector_re`` is a regex fragment (escape dots yourself, e.g.
    ``r"\\.note-body"``).
    """
    pattern = r"\n {4}" + selector_re + r"\s*\{(.*?)\n {4}\}"
    m = re.search(pattern, css, re.S)
    assert m, f"CSS rule for {selector_re!r} not found"
    return m.group(1)


# ---------------------------------------------------------------------------
# AC: exactly one left context/navigation panel slot
# ---------------------------------------------------------------------------


def test_workspace_has_single_left_context_panel():
    html = _html()
    # Exactly one left context panel region at the grid level.
    assert html.count('data-region="vault-browser-pane"') == 1
    assert html.count('data-testid="workspace-vault-browser-left-pane"') == 1
    # The three-column shell declares one left / one centre / one right slot.
    assert "workspace-layout--three-col" in html


# ---------------------------------------------------------------------------
# AC: central note pane is the primary layout region
# ---------------------------------------------------------------------------


def test_central_note_pane_is_primary_layout_region():
    html = _html()
    left = html.index('data-region="vault-browser-pane"')
    main = html.index('class="workspace-main"')
    note = html.index('data-testid="workspace-note-body"')
    rail = html.index('data-region="agent-rail"')
    # Centre note slot sits between the left pane and the right rail, and the
    # note body lives inside the central main region (not nested in a side pane).
    assert left < main < note < rail
    assert 'data-region="note-body"' in html


# ---------------------------------------------------------------------------
# AC: note body is not bottom-clipped by workspace chrome
# ---------------------------------------------------------------------------


def test_note_body_not_bottom_clipped_by_workspace_chrome():
    html = _html()
    content = _css_block(html, r"\.note-body-content")
    # The reading column must not be height-clamped to a fraction of the
    # viewport — that is the bottom-clipping bug (handoff §3.3, §7).
    assert "max-height" not in content, (
        "note-body-content must not clamp height (caused bottom clipping)"
    )
    # The central scroll container keeps generous bottom breathing room (>=96px).
    note_body = _css_block(html, r"\.note-body")
    pad = re.search(r"padding:\s*([^;]+);", note_body)
    assert pad, "note-body must declare padding"
    bottom = pad.group(1).split()
    # padding shorthand: bottom is index 2 (t r b l) or index 0 if single value.
    bottom_px = bottom[2] if len(bottom) >= 3 else bottom[0]
    assert int(re.sub(r"[^0-9]", "", bottom_px)) >= 96, (
        f"note-body bottom padding must be >=96px, got {bottom_px!r}"
    )


# ---------------------------------------------------------------------------
# AC: right rail slot is optional/collapsible without breaking the note pane
# ---------------------------------------------------------------------------


def test_right_rail_slot_can_be_compact_without_breaking_note_pane():
    # Idle, no-proposal state: the rail has nothing actionable to show.
    html = _html(panel_state="idle", panel_proposal_count=0)
    # Right rail slot still present as the optional companion region...
    assert 'data-region="agent-rail"' in html
    # ...and the central note pane remains intact and primary.
    assert 'data-testid="workspace-note-body"' in html
    assert 'data-region="note-body"' in html
    # The note body is not nested inside the rail.
    note = html.index('data-testid="workspace-note-body"')
    rail = html.index('data-region="agent-rail"')
    assert note < rail


# ---------------------------------------------------------------------------
# AC: single scroll ownership markers
# ---------------------------------------------------------------------------


def test_layout_preserves_single_scroll_ownership_markers():
    html = _html()
    # App shell owns no page scroll: the body is exactly one viewport tall and
    # does not scroll (handoff §3.3).
    body = _css_block(html, r"body")
    assert "height: 100dvh;" in body
    assert "overflow: hidden;" in body
    # The central note surface owns the primary reading scroll.
    note_body = _css_block(html, r"\.note-body")
    assert "overflow-y: auto;" in note_body
    assert "min-height: 0;" in note_body
    # No nested double-scroll inside the reading column.
    content = _css_block(html, r"\.note-body-content")
    assert "overflow-y: auto;" not in content, (
        "note-body-content must not own a second nested scroll"
    )


# ---------------------------------------------------------------------------
# AC (#1416): the dev "Edit note body" composer must not squeeze the reading
# surface in the fixed-height shell. With guard_update_flow_available the
# composer renders as an opt-in disclosure (collapsed by default) and is
# shrink-locked + height-bounded, so the note reading layout stays primary.
# ---------------------------------------------------------------------------


def test_edit_composer_is_collapsed_by_default_so_reading_stays_primary():
    # _fields() sets guard_update_flow_available=True, so the enabled composer
    # renders. It must be present but collapsed, contributing only its summary
    # row, so the note body keeps its reading height (#1416, corrective #4).
    html = _html()
    assert 'data-testid="workspace-body-edit-panel"' in html
    assert 'data-update-flow="available"' in html
    panel = re.search(
        r'<details class="body-edit-panel"[^>]*'
        r'data-testid="workspace-body-edit-panel"[^>]*>',
        html,
    )
    assert panel, "enabled body-edit composer must render as a <details> disclosure"
    # Collapsed by default: no `open` attribute on the <details> tag.
    assert not re.search(r"\bopen\b", panel.group(0)), (
        "edit composer must be collapsed by default (opt-in), not expanded"
    )


def test_edit_composer_does_not_compete_with_reading_layout_for_shell_height():
    html = _html()
    # The reading layout remains the single growing primary region.
    reading = _css_block(html, r"\.note-reading-layout")
    assert "flex: 1;" in reading
    assert "min-height: 0;" in reading
    # The composer is shrink-locked and height-bounded with internal scroll, so
    # it cannot consume the reading layout's space even when expanded.
    panel = _css_block(html, r"\.body-edit-panel")
    assert "flex-shrink: 0;" in panel, "composer must not be squeezed by the shell"
    assert "max-height" in panel, "composer must be height-bounded"
    assert "overflow-y: auto;" in panel, "composer must scroll internally when tall"


def test_edit_composer_preserves_single_scroll_ownership():
    # With the composer enabled, the #1397 scroll-ownership contract still holds.
    html = _html()
    body = _css_block(html, r"body")
    assert "height: 100dvh;" in body
    assert "overflow: hidden;" in body
    note_body = _css_block(html, r"\.note-body")
    assert "overflow-y: auto;" in note_body
    # The composer's internal scroll is a bounded editor surface, not a second
    # ownership of the page/reading scroll.
    assert html.count("height: 100dvh;") == 1
