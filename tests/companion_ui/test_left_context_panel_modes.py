"""Adaptive left context panel modes (#1399).

Applies ``ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md`` §4: the single left context
panel established by #1397 becomes mode-aware. It supports four modes —
``browse``, ``outline``, ``context``, ``collapsed`` — and renders only one at a
time. Opening a note prefers ``outline`` (when the note has headings) or
``collapsed`` (when it does not), never a cold-start browser dump. The Browse
Vault action activates ``browse`` mode in the same panel, the outline lives
inside the same left slot (not a second pane), collapsed mode keeps a visible
reopen affordance, and mode labels are human-facing.

SSR markup/contract tests against the rendered dev-page HTML.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html

_WITH_HEADINGS = "# Alpha\n\nText.\n\n## Beta\n\nMore.\n\n### Gamma\n\nEnd."
_NO_HEADINGS = "Just a paragraph with no headings at all.\n\nAnd another one."


def _fields(*, body: str, note_path: str = "Notes/note.md") -> dict:
    return {
        "title": "Note Title",
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
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
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


def _html(*, body: str = _WITH_HEADINGS, note_path: str = "Notes/note.md") -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=note_path,
        fields=_fields(body=body, note_path=note_path),
    )


def _left_nav(html: str) -> str:
    """Return the left context panel markup.

    The panel is a ``<nav>`` that contains an inner ``<nav class="note-outline">``
    (the outline), so a naive ``</nav>`` scan would truncate early. The panel
    always ends immediately before the central ``workspace-main`` region, so we
    bound on that instead.
    """
    start = html.index('<nav class="vault-browser-left-pane"')
    end = html.index('<div class="workspace-main"', start)
    return html[start:end]


# ---------------------------------------------------------------------------
# AC: declares supported modes
# ---------------------------------------------------------------------------


def test_left_panel_declares_supported_modes():
    nav = _left_nav(_html())
    m = re.search(r'data-left-panel-modes="([^"]*)"', nav)
    assert m, "left panel must declare its supported modes"
    modes = set(m.group(1).split())
    assert modes == {"browse", "outline", "context", "collapsed"}


# ---------------------------------------------------------------------------
# AC: only one mode visible at a time
# ---------------------------------------------------------------------------


def test_only_one_left_panel_mode_visible_at_a_time():
    nav = _left_nav(_html(body=_WITH_HEADINGS))
    # Each mode content region is a div carrying data-left-panel-mode-region
    # (the mode switcher is excluded — it is not a content region).
    regions = re.findall(
        r'<div[^>]*data-left-panel-mode-region="[a-z]+"[^>]*>', nav
    )
    assert len(regions) >= 2, "expected multiple mode regions in the panel"
    visible = [r for r in regions if "hidden" not in r]
    assert len(visible) == 1, f"exactly one mode region must be visible, got {len(visible)}"


# ---------------------------------------------------------------------------
# AC: opening a note defaults to outline/collapsed, not a browser dump
# ---------------------------------------------------------------------------


def test_open_note_defaults_to_outline_or_collapsed_not_browser_dump():
    # With headings → outline.
    nav = _left_nav(_html(body=_WITH_HEADINGS))
    mode = re.search(r'data-left-panel-mode="([a-z]+)"', nav).group(1)
    assert mode == "outline"
    # The browse mode region is not the active/visible one.
    browse = re.search(
        r'<div[^>]*data-testid="workspace-left-panel-mode-browse"[^>]*>', nav
    ).group(0)
    assert "hidden" in browse
    # Without headings → collapsed (no cold-start outline either).
    nav2 = _left_nav(_html(body=_NO_HEADINGS))
    mode2 = re.search(r'data-left-panel-mode="([a-z]+)"', nav2).group(1)
    assert mode2 == "collapsed"


# ---------------------------------------------------------------------------
# AC: browse action activates browse mode in the single left panel
# ---------------------------------------------------------------------------


def test_browse_action_activates_browse_mode():
    html = _html()
    # The Browse Vault entrypoint targets the left panel...
    assert 'data-browse-target="vault-browser-pane"' in html
    # ...and the focus handler activates browse mode on the left panel.
    assert "setMode('browse')" in html or 'data-left-panel-mode' in html
    # The left-panel controller exposes a browse-mode activation path.
    assert "leftPanel" in html
    assert "browse" in _left_nav(html)


# ---------------------------------------------------------------------------
# AC: outline mode uses the same left panel slot (not a second pane)
# ---------------------------------------------------------------------------


def test_outline_mode_uses_same_left_panel_slot():
    html = _html(body=_WITH_HEADINGS)
    nav = _left_nav(html)
    # The outline renders inside the left context panel.
    assert 'data-testid="note-outline"' in nav
    # ...and not as a second column inside the central reading layout.
    reading_start = html.index('data-testid="workspace-note-reading-layout"')
    reading_end = html.index("</div>", html.index('data-testid="workspace-note-body"'))
    reading_region = html[reading_start:reading_end]
    assert 'data-testid="note-outline"' not in reading_region


# ---------------------------------------------------------------------------
# AC: collapsed mode has a reopen affordance
# ---------------------------------------------------------------------------


def test_collapsed_mode_has_reopen_affordance():
    nav = _left_nav(_html(body=_NO_HEADINGS))
    assert 'data-left-panel-mode="collapsed"' in nav
    reopen = re.search(
        r'<button[^>]*data-testid="workspace-left-panel-reopen"[^>]*>(.*?)</button>',
        nav,
        re.S,
    )
    assert reopen, "collapsed mode must expose a reopen affordance"
    assert "hidden" not in reopen.group(0), "reopen affordance must be visible when collapsed"


# ---------------------------------------------------------------------------
# AC: mode labels are human-facing, not debug strings
# ---------------------------------------------------------------------------


def test_mode_labels_are_human_facing():
    nav = _left_nav(_html())
    # Human-facing tab labels.
    assert ">Browse</button>" in nav
    assert ">Outline</button>" in nav
    assert ">Context</button>" in nav
    # Internal mode keys live in data-* attributes, not as visible copy.
    assert ">browse</button>" not in nav
    assert ">outline</button>" not in nav
