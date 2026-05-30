"""Obsidian-style collapsible folder tree in the Vault Browser (#1425).

Browse mode renders a nested, collapsible folder tree (like the Obsidian file
explorer) instead of flat folder groups: folders nest by real path depth and
collapse, notes render as clean name-only rows indented under their folder, the
active note's ancestor folders are expanded by default, and the active row is
highlighted. #1417 (no raw metadata in rows) guarantees still hold.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html

# Mirrors the live Niflheim vault layout (from /api/companion/vault/notes).
_NOTES = [
    {"note_path": "Companion UI UAT.md", "title": "Companion UI UAT", "kind": "note"},
    {"note_path": "Test.md", "title": "0. **Executive summary**", "kind": "note"},
    {"note_path": "📥 Inbox/Companion_UI_Markdown_Feature_UAT.md", "title": "Companion UI Markdown Feature UAT", "kind": "note", "review_state": "needs_review"},
    {"note_path": "📥 Inbox/Namnlös.md", "title": "Companion UI Markdown Feature UAT", "kind": "note"},
    {"note_path": "📥 Inbox/Test note 2.md", "title": "Test note 2", "kind": "note"},
    {"note_path": "⚙️ System/vault.layout.md", "title": "Vault Layout Contract", "kind": "note"},
    {"note_path": "⚙️ System/companions/11111111-1111-4111-8111-111111111111.md", "title": "Companion UI UAT", "kind": "companion_note"},
]


def _fields(*, notes, note_path):
    return {
        "title": "N", "note_path": note_path, "artifact_id": "a", "artifact_kind": "note",
        "artifact_identity_source": "frontmatter.uuid", "artifact_identity_state": "resolved",
        "artifact_companion_of": None, "artifact_owns_identity": True, "content_hash": "h",
        "body": "# N\n\nBody.", "panel_rail": "rail", "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev", "runtime_trace_id": "t",
        "runtime_vault_name": "vault/dev", "runtime_vault_channel": "dev", "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle", "canvas_session_persistence": "durable",
        "panel_state": "idle", "panel_proposal_count": 0, "panel_proposals": [], "panel_message": "",
        "guard_writeguard_status": "ok", "guard_canvas_enabled": True, "guard_degraded": False,
        "guard_workspace_update_available": True, "guard_update_flow_available": False,
        "find_candidates": [], "find_payload_available": False, "reorient_sections": {},
        "resurface_candidates": [], "governance_receipts": [], "suggestion_state": "idle",
        "suggestion_composer_enabled": True, "is_production_ui": False, "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
        "vault_browser_notes": notes, "vault_browser_query": "",
        "vault_browser_total_notes": len(notes), "vault_browser_filtered_notes": len(notes),
        "vault_browser_read_only": True, "vault_browser_identity_available": True,
        "vault_browser_vault_name": "vault/dev", "vault_browser_vault_channel": "dev",
    }


def _html(*, notes=None, note_path="📥 Inbox/Companion_UI_Markdown_Feature_UAT.md"):
    notes = _NOTES if notes is None else notes
    return render_index_html(api_base_url="http://127.0.0.1:18001", note_path=note_path,
                             fields=_fields(notes=notes, note_path=note_path))


def _folder(html, full):
    """Return the opening markup of the folder node with data-folder == full."""
    m = re.search(r'<li class="vault-tree-folder"[^>]*data-folder="' + re.escape(full) + r'"[^>]*>', html)
    return m.group(0) if m else None


def test_browse_renders_nested_folder_tree():
    html = _html()
    # Folders exist for both System and its nested companions subfolder.
    assert _folder(html, "⚙️ System")
    assert _folder(html, "⚙️ System/companions")
    # The companions folder node is nested *inside* the System folder node.
    sys_start = html.index('data-folder="⚙️ System"')
    sys_details = html.index("</details>", sys_start)  # close of the System folder
    comp_idx = html.index('data-folder="⚙️ System/companions"')
    assert sys_start < comp_idx < sys_details, "companions must nest inside System"


def test_active_note_ancestor_folders_expanded_others_collapsed():
    html = _html(note_path="📥 Inbox/Test note 2.md")
    inbox = _folder(html, "📥 Inbox")
    system = _folder(html, "⚙️ System")
    assert inbox and system
    # The active note's folder <details> is open; an unrelated folder is not.
    inbox_details = re.search(r'data-folder="📥 Inbox"[^>]*>\s*<details([^>]*)>', html)
    system_details = re.search(r'data-folder="⚙️ System"[^>]*>\s*<details([^>]*)>', html)
    assert inbox_details and "open" in inbox_details.group(1)
    assert system_details and "open" not in system_details.group(1)


def test_note_rows_show_name_only_no_metadata():
    html = _html()
    rows = re.findall(r'<li class="vault-browser-row[^"]*"[^>]*>.*?</li>', html, re.S)
    assert rows
    # The active Inbox note row shows the filename stem as its visible link text,
    # not the (duplicate) frontmatter title, and carries no raw metadata text.
    active = [r for r in rows if 'data-active="true"' in r][0]
    link = re.search(r'data-testid="workspace-vault-browser-note-link"[^>]*>([^<]*)</a>', active)
    assert link and link.group(1) == "Companion_UI_Markdown_Feature_UAT"
    # Filter-style label text never appears in a row.
    for leak in ("Kind:", "Zone:", "Review:", "Trust:"):
        assert leak not in active, f"row leaks {leak!r}"
    # review_state appears only inside a nav-hidden badge (hidden from row text).
    if "needs_review" in active:
        badge = re.search(r'<span([^>]*)>needs_review</span>', active)
        assert badge and "note-badge--nav-hidden" in badge.group(1)
    # The path/zone elements carry the path only in a hidden code/attr, never as
    # visible row label text (the visible label is the stem above).
    assert "hidden>" in active  # the note-path <code> is hidden
    assert 'class="vault-browser-zone-label"' in active  # zone span present but display:none


def test_active_note_row_is_highlighted():
    html = _html()
    rows = re.findall(r'<li class="vault-browser-row[^"]*"[^>]*>.*?</li>', html, re.S)
    active = [r for r in rows if 'data-active="true"' in r]
    assert len(active) == 1
    # A visible active style exists.
    assert re.search(r'\.vault-browser-row\[data-active="true"\][^{]*\{[^}]*\}', html)


def test_folders_are_collapsible_details():
    html = _html()
    folder = _folder(html, "📥 Inbox")
    assert folder
    # The folder body is a <details>/<summary> (collapsible) with the segment name.
    block = html[html.index(folder):]
    summary = re.search(r'<summary class="vault-tree-folder-summary"[^>]*>([^<]*)</summary>', block)
    assert summary and "Inbox" in summary.group(1)


def test_tree_preserves_note_testids_and_density():
    html = _html()
    assert 'data-testid="workspace-vault-browser-list"' in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html
    assert 'data-testid="workspace-vault-browser-note-row"' in html
    # Root-level notes (no folder) still render as rows.
    assert "Companion UI UAT.md" in html or "Companion UI UAT" in html


# ---------------------------------------------------------------------------
# #1427 — clean default browse view (no inspector dump, subtle hover/selection)
# ---------------------------------------------------------------------------


def test_inspector_is_collapsed_behind_a_disclosure_by_default():
    html = _html()
    m = re.search(
        r'<details class="vault-browser-inspector-disclosure"([^>]*)>(.*?)</details>',
        html, re.S,
    )
    assert m, "inspector must sit behind a vault-browser-inspector-disclosure <details>"
    assert "open" not in m.group(1), "inspector disclosure must be collapsed by default"
    # The inspector fields are still in the DOM (preserve #1255).
    assert 'data-testid="workspace-vault-browser-inspector"' in m.group(2)
    # Deterministic collapse CSS so the dump is hidden in every engine.
    assert re.search(
        r'\.vault-browser-inspector-disclosure:not\(\[open\]\)[^{]*\{[^}]*display:\s*none',
        html,
    )


def test_tree_hover_uses_background_not_outline_box():
    html = _html()
    # The tree row hover rule highlights with a background, not an outline box.
    hover = re.search(
        r'\.vault-tree \.vault-browser-row-title:hover[^{]*\{([^}]*)\}', html
    )
    assert hover, "tree row hover rule missing"
    assert "background" in hover.group(1)
    # No heavy outline box (outline:none to drop the focus ring is fine).
    assert "border-focus" not in hover.group(1)
    assert "outline: 1px" not in hover.group(1)
    # The folder summary focus ring is suppressed (no heavy blue box).
    assert re.search(
        r'\.vault-tree-folder-details > summary:focus[^{]*\{[^}]*outline:\s*none', html
    )


def test_active_note_has_subtle_background_highlight():
    html = _html()
    rule = re.search(
        r'\.vault-tree \.vault-browser-row\[data-active="true"\]\s*\{([^}]*)\}', html
    )
    assert rule and "background" in rule.group(1), "active row needs a background highlight"
