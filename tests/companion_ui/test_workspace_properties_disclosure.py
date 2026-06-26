"""Tests for breadcrumb + properties detail.

§7.3 / #1337 introduced the breadcrumb + a single properties disclosure. #2563
re-houses the properties detail (artifact/hash/uuid) into a Tier-2 anchored
popover reached from the one quiet utility line — it is no longer an inline
``<details>`` stacked on the breadcrumb/above the body. These tests assert the
re-housed contract: the breadcrumb is the quiet path+meta line, and the
artifact/hash/uuid facts live only inside the properties popover.
"""
from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html
from tests.companion_ui._visible_text import visible_text as _visible_text


_FRONTMATTER_BODY = """\
---
kind: test_note
review: needs_review
uuid: 550e8400-e29b-41d4-a716-446655440000
trust: high
tags:
  - research
  - agentic
---

# Test note body
"""

_FIELDS_BASE: dict = {
    "title": "Test Note",
    "note_path": "Inbox/Test Note.md",
    "artifact_id": "art-12345-uuid",
    "content_hash": "sha256-deadbeef",
    "guard_writeguard_status": "ok",
    "guard_canvas_enabled": True,
    "guard_degraded": False,
    "guard_workspace_update_available": False,
    "guard_update_flow_available": True,
    "runtime_vault_provenance": "resolved",
    "runtime_vault_name": "TestVault",
    "runtime_vault_channel": "dev",
    "panel_state": "idle",
    "panel_proposal_count": 0,
    "canvas_session_state": "idle",
    "canvas_session_persistence": "durable",
    "panel_proposals": [],
    "panel_message": "",
    "find_candidates": [],
    "reorient_sections": None,
    "resurface_candidates": [],
    "governance_receipts": [],
    "suggestion_state": "idle",
    "suggestion_composer_enabled": True,
    "is_production_ui": False,
    "dev_page_label": "dev/staging",
}


def _render(**overrides) -> str:
    fields = {**_FIELDS_BASE, **overrides}
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


def _popover_html(html: str) -> str:
    """The Tier-2 properties popover subtree (artifact/hash/uuid live here)."""
    m = re.search(
        r'data-testid="workspace-properties-popover".*?</div>\s*</div>',
        html,
        re.DOTALL,
    )
    assert m, "workspace-properties-popover not found"
    return m.group()


class TestBreadcrumbReplacesChips:
    """AC1 — breadcrumb is the quiet path+meta line (chips moved off it)."""

    def test_breadcrumb_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-breadcrumb"' in html

    def test_breadcrumb_contains_path(self) -> None:
        html = _render(note_path="Inbox/Test Note.md")
        assert 'data-note-path="Inbox/Test Note.md"' in html

    def test_old_chip_row_absent(self) -> None:
        html = _render()
        # The standalone note-provenance chip strip no longer exists as a
        # top-level note-header sibling; chips live inside the popover.
        assert 'class="note-provenance"' not in html

    def test_breadcrumb_path_segments_rendered(self) -> None:
        html = _render(note_path="Projects/Alpha/Note.md")
        # Breadcrumb renders path parts separated by " / "
        assert "Projects" in html
        assert "Alpha" in html
        assert "Note.md" in html

    def test_breadcrumb_no_longer_hosts_inline_disclosure(self) -> None:
        # #2563 — the breadcrumb must not carry an inline properties <details>;
        # properties are reached from the utility line, hosted in a popover.
        html = _render()
        assert "workspace-properties-disclosure" not in html
        m = re.search(r'data-testid="workspace-breadcrumb".*?</div>', html, re.DOTALL)
        assert m, "breadcrumb not found"
        assert "<details" not in m.group(), "breadcrumb still hosts an inline <details>"


class TestPropertiesPopoverHiddenByDefault:
    """AC2 — the properties popover is closed (hidden) on open."""

    def test_popover_present_and_hidden(self) -> None:
        html = _render()
        m = re.search(
            r'<div class="note-properties-popover"[^>]*>',
            html,
        )
        assert m, "note-properties-popover not found"
        assert "hidden" in m.group(), "properties popover is not hidden by default"

    def test_properties_trigger_on_utility_line(self) -> None:
        # Properties is reachable from the one utility line, not the body.
        html = _render()
        assert 'data-testid="workspace-note-utility-properties"' in html
        assert 'aria-expanded="false"' in re.search(
            r'data-testid="workspace-note-utility-properties"[^>]*', html
        ).group()


class TestArtifactAndHashInsidePopover:
    """AC3 — artifact id and content hash live inside the popover only."""

    def test_artifact_inside_popover(self) -> None:
        html = _render(artifact_id="art-99999")
        assert "art-99999" in _popover_html(html), "artifact_id not inside popover"

    def test_hash_inside_popover(self) -> None:
        html = _render(content_hash="sha256-cafecafe")
        assert "sha256-cafecafe" in _popover_html(html), "content_hash not inside popover"

    def test_artifact_only_in_popover(self) -> None:
        """artifact_id must not appear outside the popover (no restatement)."""
        html = _render(artifact_id="art-unique-7777")
        outside = html.replace(_popover_html(html), "")
        # A human restatement is visible copy, never a data-* attribute; scan the
        # rendered visible text only (parser-based, drops script/style + tags).
        assert "art-unique-7777" not in _visible_text(outside), (
            "artifact_id appears outside the properties popover (restatement)"
        )


class TestNoFactRestatement:
    """AC4 — each fact appears in at most one visible DOM region."""

    def test_no_fact_restatement_for_key_fields(self) -> None:
        html = _render(body=_FRONTMATTER_BODY, artifact_id="art-unique-xzy", content_hash="sha256-unique-abc")
        # Exclude the properties popover subtree (the one region that hosts the
        # identity facts), then scan the rendered visible text only.
        outside = html.replace(_popover_html(html), "")
        visible = _visible_text(outside)
        assert "art-unique-xzy" not in visible, "artifact_id leaked outside the popover"
        assert "sha256-unique-abc" not in visible, "content_hash leaked outside the popover"


class TestRendererContractPreserved:
    """AC5 — Markdown renderer contract unchanged."""

    def test_properties_renderer_html_inside_popover(self) -> None:
        html = _render(body=_FRONTMATTER_BODY)
        assert 'data-testid="workspace-note-properties"' in html

    def test_all_frontmatter_keys_still_surfaced(self) -> None:
        html = _render(body=_FRONTMATTER_BODY)
        popover = _popover_html(html)
        assert "kind" in popover
        assert "review" in popover
        assert "trust" in popover
        assert "tags" in popover


# ---------------------------------------------------------------------------
# #2563 — one rule, three tiers: the note-view chrome placement model.
# ---------------------------------------------------------------------------


def _between_title_and_first_body_line(html: str) -> str:
    """The markup between the note title and the rendered body's first line."""
    title_end = html.index("</h1>")
    body_start = html.index('data-testid="workspace-note-rendered"')
    return html[title_end:body_start]


class TestNoteViewChromePlacement:
    """#2563 AC1·1–5 — the three-tier placement model (static slices)."""

    def test_nothing_visible_renders_between_title_and_first_body_line(self) -> None:
        # AC1 — on note open, no per-note control renders between the title and
        # the first body line. The only structural elements between them are the
        # quiet breadcrumb (path+meta), the title-row utility cluster, and the
        # edit-mode ribbon / Read-aloud occupant — and every chrome surface that
        # could outrank the body is hidden until invoked.
        html = _render()
        # The edit-mode ribbon is hidden on open.
        ribbon = re.search(r'<div class="note-edit-bar note-mode-ribbon"[^>]*>', html)
        assert ribbon and "hidden" in ribbon.group()
        # The Read-aloud occupant is hidden on open.
        occ = re.search(r'<div class="tts-readback-occupant"[^>]*>', html)
        assert occ and "hidden" in occ.group()
        # The properties popover is hidden on open.
        pop = re.search(r'<div class="note-properties-popover"[^>]*>', html)
        assert pop and "hidden" in pop.group()
        # No inline read-only chip stacked above the body, and no Read-aloud /
        # Edit <details> stacked above the body.
        between = _between_title_and_first_body_line(html)
        assert "workspace-read-only-pill" not in between
        assert "<details" not in between

    def test_one_utility_line_reaches_edit_read_aloud_properties(self) -> None:
        # AC2 — Edit, Read aloud, and Properties are reachable from one utility
        # line on the breadcrumb/title row; none is a stacked <details> above the
        # body.
        html = _render()
        line = re.search(
            r'data-testid="workspace-note-utility-line".*?</div>\s*</div>\s*</div>',
            html,
            re.DOTALL,
        )
        assert line, "note utility line not found"
        cluster = line.group()
        assert 'data-testid="workspace-note-utility-properties"' in cluster
        assert 'data-testid="workspace-note-utility-read-aloud"' in cluster
        assert 'data-testid="workspace-note-utility-edit"' in cluster
        # Read aloud mounts the overlay-hosted tts occupant; Edit enters the
        # Tier-3 frame mode; Properties opens the anchored popover.
        assert "overlayHost.mount('tts')" in cluster
        assert "noteEditor.start()" in cluster
        assert "noteUtility.toggleProperties(this)" in cluster
        # None of the three is a stacked <details> above the body.
        assert '<details class="tts-readback-controls"' not in html
        assert '<details class="note-edit-bar"' not in html
        assert "workspace-properties-disclosure" not in html

    def test_no_standing_read_only_chip_above_every_note(self) -> None:
        # AC4 — there is no standing read-only chip above every note. The
        # read-only indicator/reason are re-housed inside the edit-mode ribbon
        # (surfaced on the edit attempt) and stay hidden on open.
        html = _render()
        assert 'data-testid="workspace-read-only-pill"' not in html
        # The indicator still exists (server-declared posture renders verbatim),
        # but it is hidden on open AND lives inside the (hidden) edit-mode ribbon
        # — so there is no standing chip above the body. It surfaces in the ribbon
        # only on the edit attempt.
        ind = re.search(r'<div class="note-body-readonly-indicator"[^>]*>', html)
        assert ind and "hidden" in ind.group()
        ribbon = re.search(
            r'<div class="note-edit-bar note-mode-ribbon".*?</div>\s*</div>',
            html,
            re.DOTALL,
        )
        assert ribbon and "note-body-readonly-indicator" in ribbon.group(), (
            "read-only indicator must be re-housed inside the edit-mode ribbon"
        )
        ribbon_open = re.search(r'<div class="note-edit-bar note-mode-ribbon"[^>]*>', html)
        assert ribbon_open and "hidden" in ribbon_open.group()

    def test_edit_is_a_frame_mode_not_a_panel(self) -> None:
        # AC4 — entering Edit changes the document frame (mode ribbon + Save /
        # Cancel / Read draft); the reading state shows no edit toolbar. The
        # document frame carries the reading/editing state on note-body.
        html = _render()
        body = re.search(r'<div class="note-body"[^>]*>', html)
        assert body and 'data-edit-mode="off"' in body.group()
        ribbon = re.search(
            r'<div class="note-edit-bar note-mode-ribbon".*?</div>\s*</div>',
            html,
            re.DOTALL,
        )
        assert ribbon
        ribbon_html = ribbon.group()
        assert 'data-testid="workspace-note-edit-save"' in ribbon_html
        assert 'data-testid="workspace-note-edit-cancel"' in ribbon_html
        assert 'data-testid="workspace-note-edit-read-draft"' in ribbon_html
        # The frame mode is driven by the editor controller, not a <details>.
        assert "body.setAttribute('data-edit-mode', 'on')" in html

    def test_narrow_collapses_to_overflow_actions_affordance(self) -> None:
        # AC5 — at <=480px the utility line collapses to a single ⋯ actions
        # affordance opening an overlay sheet; the body still owns the column.
        html = _render()
        assert 'data-testid="workspace-note-utility-overflow"' in html
        # The CSS hides the inline cluster and shows the ⋯ overflow at <=480px.
        assert re.search(
            r"@media \(max-width: 480px\) \{\s*"
            r"\.note-utility-cluster \{ display: none; \}\s*"
            r"\.note-utility-overflow \{ display: inline-flex; \}",
            html,
        ), "the <=480px utility-line collapse rule is missing"
        # The overflow opens a sheet exposing the same three verbs.
        sheet = re.search(
            r'data-testid="workspace-note-utility-sheet".*?</div>',
            html,
            re.DOTALL,
        )
        assert sheet
        sheet_html = sheet.group()
        assert "noteUtility.fromSheet('properties')" in sheet_html
        assert "noteUtility.fromSheet('read-aloud')" in sheet_html
        assert "noteUtility.fromSheet('edit')" in sheet_html

    def test_read_aloud_routes_through_declared_tts_overlay_occupant(self) -> None:
        # AC3 support — the Read-aloud detail is overlay-hosted (the declared
        # `tts` overlay), preserving the dismiss grammar. The plan-before-audio
        # TTS contract (inspector + explicit Read) is exercised in live UAT.
        html = _render()
        occ = re.search(r'<div class="tts-readback-occupant"[^>]*>', html)
        assert occ and 'data-overlay-id="tts"' in occ.group()
        assert "window.overlayHost.register('tts'" in html
        # Codex PR #2569 regression: mounting `tts` activates the shared scrim at
        # z-index 900; the occupant must render ABOVE it (position:fixed, higher
        # z-index) or the first click lands on the scrim and dismisses the
        # overlay instead of pressing Read note/Selection/Proposal.
        shown = re.search(
            r"\.tts-readback-occupant:not\(\[hidden\]\)\s*\{([^}]*)\}", html
        )
        assert shown, "shown tts-occupant CSS rule (above the scrim) is missing"
        shown_body = shown.group(1)
        assert "position: fixed" in shown_body
        z = re.search(r"z-index:\s*(\d+)", shown_body)
        assert z and int(z.group(1)) > 900, "tts occupant must stack above the scrim (z-index 900)"
