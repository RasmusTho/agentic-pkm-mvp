"""Vault Browser density and 40+ artifact scale (#1400).

Applies ``ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md`` §6: the browse list must stay
scannable at 40+ artifacts across nested directories. Rows lead with the
title and a compact folder/path context, the list scrolls inside the left
panel without clamping the note pane, raw metadata stays out of primary row
text, companion notes are distinguishable without noisy badges, and long paths
are truncated / moved to a details affordance.

SSR markup/contract tests against the rendered dev-page HTML.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


def _dense_notes(count: int = 42) -> list[dict]:
    folders = [
        "projects/alpha",
        "projects/beta/sub",
        "research/papers",
        "research/notes/2026",
        "daily/2026/05",
        "reference",
    ]
    notes = []
    for i in range(count):
        folder = folders[i % len(folders)]
        path = f"{folder}/note-{i:02d}.md"
        notes.append(
            {
                "note_path": path,
                "title": f"Artifact {i:02d} title",
                "zone": folder.split("/")[0],
                "kind": "human_note",
            }
        )
    return notes


def _fields(*, notes: list[dict], note_path: str = "projects/alpha/note-00.md") -> dict:
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
        "body": "# Note\n\nBody content here.",
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
        # Vault browser payload
        "vault_browser_notes": notes,
        "vault_browser_query": "",
        "vault_browser_total_notes": len(notes),
        "vault_browser_filtered_notes": len(notes),
        "vault_browser_read_only": True,
        "vault_browser_identity_available": True,
        "vault_browser_vault_name": "vault/dev",
        "vault_browser_vault_channel": "dev",
    }


def _html(*, notes: list[dict] | None = None, note_path: str = "projects/alpha/note-00.md") -> str:
    notes = _dense_notes() if notes is None else notes
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=note_path,
        fields=_fields(notes=notes, note_path=note_path),
    )


def _rows(html: str) -> list[str]:
    return re.findall(
        r'<li class="vault-browser-row[^"]*"[^>]*>.*?</li>', html, re.S
    )


# ---------------------------------------------------------------------------
# AC: 40+ artifacts with nested folders
# ---------------------------------------------------------------------------


def test_vault_browser_handles_40_artifacts_with_nested_folders():
    html = _html()
    rows = _rows(html)
    assert len(rows) >= 40, f"expected >=40 rows, got {len(rows)}"
    # Folder grouping renders a header per distinct folder; nested paths appear
    # in the group folder markers.
    groups = re.findall(r'data-testid="workspace-vault-browser-group"[^>]*data-folder="([^"]*)"', html)
    assert groups, "expected folder group headers"
    assert any("/" in g for g in groups), "expected nested folder group headers"
    assert "projects/beta/sub" in groups


# ---------------------------------------------------------------------------
# AC: list scrolls inside the left panel, note pane stays visible
# ---------------------------------------------------------------------------


def test_browser_list_scrolls_inside_left_panel():
    html = _html()
    m = re.search(r"\n {4}\.vault-browser-list\s*\{(.*?)\n {4}\}", html, re.S)
    assert m, ".vault-browser-list rule not found"
    assert "overflow-y: auto;" in m.group(1)
    # The note pane is not clamped away by the dense list.
    assert 'data-testid="workspace-note-body"' in html
    assert 'data-region="note-body"' in html


# ---------------------------------------------------------------------------
# AC: rows prioritize title and folder
# ---------------------------------------------------------------------------


def test_browser_rows_prioritize_title_and_folder():
    html = _html()
    rows = _rows(html)
    assert rows
    row = rows[0]
    # Title (note-link) is the primary, first content of the row.
    link_idx = row.index('data-testid="workspace-vault-browser-note-link"')
    path_idx = row.index('data-testid="workspace-vault-browser-note-path"')
    assert link_idx < path_idx, "title must precede the path in the row"
    # Folder hierarchy is conveyed by group headers.
    assert 'data-testid="workspace-vault-browser-group"' in html


# ---------------------------------------------------------------------------
# AC: rows do not dump raw metadata as primary text
# ---------------------------------------------------------------------------


def test_browser_rows_do_not_dump_raw_metadata():
    note = {
        "note_path": "projects/alpha/secret.md",
        "title": "Secret Artifact",
        "zone": "projects",
        "kind": "human_note",
        "review_state": "needs_review",
        "trust": "asserted",
    }
    html = _html(notes=[note], note_path="projects/alpha/secret.md")
    row = _rows(html)[0]
    # review_state / trust are present only as nav-hidden metadata badges, never
    # as bare primary row text.
    for badge_testid, value in (
        ("workspace-vault-browser-note-review-state", "needs_review"),
        ("workspace-vault-browser-note-trust", "asserted"),
    ):
        badge = re.search(
            rf'<span[^>]*data-testid="{badge_testid}"[^>]*>([^<]*)</span>', row
        )
        assert badge, f"{badge_testid} badge missing"
        # the badge carrying the raw value is flagged nav-hidden
        full = re.search(
            rf'<span([^>]*)data-testid="{badge_testid}"', row
        ).group(1)
        assert "note-badge--nav-hidden" in full, f"{value} must be in a nav-hidden badge"


# ---------------------------------------------------------------------------
# AC: companion notes distinguishable without noisy badges
# ---------------------------------------------------------------------------


def test_companion_notes_are_distinguishable_without_noisy_badges():
    note = {
        "note_path": "projects/alpha/Note.companion.md",
        "title": "Companion sidecar",
        "zone": "projects",
        "kind": "companion_note",
    }
    html = _html(notes=[note], note_path="projects/alpha/Note.companion.md")
    rows = _rows(html)
    assert rows
    row = rows[0]
    # Distinguished structurally...
    assert "vault-browser-row--companion" in row
    assert 'data-companion="true"' in row
    # ...without a noisy visible kind badge (the kind marker stays nav-hidden).
    kind = re.search(r'<span([^>]*)data-testid="workspace-vault-browser-note-kind"', row)
    assert kind and "note-badge--nav-hidden" in kind.group(1)


# ---------------------------------------------------------------------------
# AC: long paths truncated or moved to details
# ---------------------------------------------------------------------------


def test_long_paths_are_truncated_or_moved_to_details():
    long_folder = "projects/very/deeply/nested/area/with/many/segments"
    note = {
        "note_path": f"{long_folder}/a-rather-long-note-filename.md",
        "title": "Deep note",
        "zone": "projects",
        "kind": "human_note",
    }
    html = _html(notes=[note], note_path=f"{long_folder}/a-rather-long-note-filename.md")
    row = _rows(html)[0]
    path_el = re.search(
        r'<code[^>]*data-testid="workspace-vault-browser-note-path"[^>]*>([^<]*)</code>',
        row,
    )
    assert path_el, "note-path element missing"
    # Full absolute path is preserved in a details affordance (title attribute),
    # while the visible text is compact (not the whole nested path).
    open_tag = re.search(
        r'<code[^>]*data-testid="workspace-vault-browser-note-path"[^>]*>', row
    ).group(0)
    assert f'title="{long_folder}/a-rather-long-note-filename.md"' in open_tag
    assert path_el.group(1).strip() != f"{long_folder}/a-rather-long-note-filename.md"
    # A truncation style exists for the path.
    assert ".vault-browser-row-path" in html


# ---------------------------------------------------------------------------
# #1417 — raw metadata must not leak into visible Browse row text
# ---------------------------------------------------------------------------


def _css_block(html: str, selector_re: str) -> str:
    m = re.search(r"\n {4}" + selector_re + r"\s*\{(.*?)\}", html, re.S)
    assert m, f"CSS rule {selector_re!r} not found"
    return m.group(1)


def test_row_metadata_badges_are_hidden_not_dimmed():
    # The kind/review/trust badges carry note-badge--nav-hidden; that class must
    # hide them (display:none), not merely dim them (opacity), so raw metadata
    # like "note"/"needs_review"/"asserted" never shows as visible row text.
    html = _html()
    block = _css_block(html, r"\.note-badge--nav-hidden")
    assert "display: none" in block, "nav-hidden badges must be display:none"
    assert "opacity:" not in block, "nav-hidden must not merely dim metadata"


def test_row_zone_label_not_rendered_as_visible_text():
    # The raw zone label (e.g. 'inbox', '⚙ System') must not show as primary row
    # text; folder grouping already supplies path context. Element may remain in
    # the DOM (for data-* compatibility) but must be hidden.
    html = _html()
    assert 'data-testid="workspace-vault-browser-note-zone"' in html  # preserved
    block = _css_block(html, r"\.vault-browser-zone-label")
    assert "display: none" in block, "zone label must be hidden from row text"


def test_filter_chips_are_collapsed_behind_a_filters_disclosure():
    # The Kind:/Zone:/Review:/Trust: filter facets must not dump into the default
    # Browse view; they live behind a collapsed Filters disclosure.
    html = _html()
    # The filters region is wrapped in a <details> that is not open by default.
    m = re.search(
        r'<details([^>]*)class="[^"]*vault-browser-filters-disclosure[^"]*"[^>]*>(.*?)</details>',
        html,
        re.S,
    )
    assert m, "filter chips must be inside a vault-browser-filters-disclosure <details>"
    assert "open" not in m.group(1), "Filters disclosure must be collapsed by default"
    # The chips (with their wiring) are preserved inside the disclosure.
    assert 'data-testid="vault-browser-filter-chip"' in m.group(2)
    assert 'onclick="vbToggleFilter(this)"' in m.group(2)
    # Human-facing summary label.
    assert re.search(r"<summary[^>]*>\s*Filters", m.group(2) + m.group(0))


def test_no_raw_kind_or_trust_label_in_default_visible_row_area():
    # Belt-and-braces: the literal "Kind:" / "Trust:" / "Review:" label text only
    # appears inside the collapsed Filters disclosure, never in a row.
    note = {
        "note_path": "📥 Inbox/Companion UI UAT.md",
        "title": "Companion UI UAT",
        "zone": "inbox",
        "kind": "note",
        "review_state": "needs_review",
        "trust": "internal",
    }
    html = _html(notes=[note], note_path="📥 Inbox/Companion UI UAT.md")
    row = _rows(html)[0]
    for leak in ("Kind:", "Zone:", "Review:", "Trust:"):
        assert leak not in row, f"row leaks raw metadata label {leak!r}"
    # The concatenated metadata fragment seen in UAT (e.g. 'noteinboxinternal')
    # must not appear as visible row text — those values live in hidden badges.
    assert ">note<" not in row or "note-badge--nav-hidden" in row
