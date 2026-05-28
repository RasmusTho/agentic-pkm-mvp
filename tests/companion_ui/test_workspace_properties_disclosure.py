"""Tests for breadcrumb + properties disclosure (§7.3 / #1337 AC1–5)."""
from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


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


class TestBreadcrumbReplacesChips:
    """AC1 — breadcrumb replaces the chip strip."""

    def test_breadcrumb_present(self) -> None:
        html = _render()
        assert 'data-testid="workspace-breadcrumb"' in html

    def test_breadcrumb_contains_path(self) -> None:
        html = _render(note_path="Inbox/Test Note.md")
        assert 'data-note-path="Inbox/Test Note.md"' in html

    def test_old_chip_row_absent(self) -> None:
        html = _render()
        # The standalone note-provenance chip strip no longer exists as a
        # top-level note-header sibling; chips live inside the disclosure.
        assert 'class="note-provenance"' not in html

    def test_breadcrumb_path_segments_rendered(self) -> None:
        html = _render(note_path="Projects/Alpha/Note.md")
        # Breadcrumb renders path parts separated by " / "
        assert "Projects" in html
        assert "Alpha" in html
        assert "Note.md" in html


class TestPropertiesDefaultCollapsed:
    """AC2 — disclosure default state is collapsed."""

    def test_default_collapsed(self) -> None:
        html = _render()
        m = re.search(r'data-testid="workspace-properties-disclosure"[^>]*', html)
        assert m, "workspace-properties-disclosure not found"
        assert 'aria-expanded="false"' in m.group(), (
            f"disclosure is not aria-expanded=false: {m.group()!r}"
        )

    def test_details_has_no_open_attribute(self) -> None:
        html = _render()
        m = re.search(
            r'<details[^>]*data-testid="workspace-properties-disclosure"[^>]*>',
            html,
        )
        assert m, "properties disclosure <details> not found"
        assert " open" not in m.group(), "disclosure is open by default"


class TestArtifactAndHashInsideDisclosure:
    """AC3 — artifact id and content hash live inside the disclosure only."""

    def test_artifact_inside_disclosure(self) -> None:
        html = _render(artifact_id="art-99999")
        disc_m = re.search(
            r'data-testid="workspace-properties-disclosure".*?</details>',
            html,
            re.DOTALL,
        )
        assert disc_m, "workspace-properties-disclosure not found"
        assert "art-99999" in disc_m.group(), "artifact_id not inside disclosure"

    def test_hash_inside_disclosure(self) -> None:
        html = _render(content_hash="sha256-cafecafe")
        disc_m = re.search(
            r'data-testid="workspace-properties-disclosure".*?</details>',
            html,
            re.DOTALL,
        )
        assert disc_m, "workspace-properties-disclosure not found"
        assert "sha256-cafecafe" in disc_m.group(), "content_hash not inside disclosure"

    def test_artifact_only_in_disclosure(self) -> None:
        """artifact_id must not appear outside the disclosure (no restatement)."""
        html = _render(artifact_id="art-unique-7777")
        disc_m = re.search(
            r'data-testid="workspace-properties-disclosure".*?</details>',
            html,
            re.DOTALL,
        )
        assert disc_m
        outside = html.replace(disc_m.group(), "")
        # Strip style/script blocks before checking
        import re as _re
        outside = _re.sub(r"<style[^>]*>.*?</style[^>]*>", "", outside, flags=_re.DOTALL | _re.IGNORECASE)
        outside = _re.sub(r"<script[^>]*>.*?</script[^>]*>", "", outside, flags=_re.DOTALL | _re.IGNORECASE)
        assert "art-unique-7777" not in outside, (
            "artifact_id appears outside the disclosure (restatement violation)"
        )


class TestNoFactRestatement:
    """AC4 — each fact appears in at most one visible DOM region."""

    def test_no_fact_restatement_for_key_fields(self) -> None:
        html = _render(body=_FRONTMATTER_BODY, artifact_id="art-unique-xzy", content_hash="sha256-unique-abc")
        import re as _re
        # Exclude the closed details subtree (not visible on default render)
        html_outside_details = _re.sub(
            r'<details[^>]*data-testid="workspace-properties-disclosure".*?</details>',
            "",
            html,
            flags=_re.DOTALL,
        )
        # Strip style/script
        stripped = _re.sub(r"<style[^>]*>.*?</style[^>]*>", "", html_outside_details, flags=_re.DOTALL | _re.IGNORECASE)
        stripped = _re.sub(r"<script[^>]*>.*?</script[^>]*>", "", stripped, flags=_re.DOTALL | _re.IGNORECASE)
        # These unique values should NOT appear outside the disclosure
        assert "art-unique-xzy" not in stripped, "artifact_id leaked outside disclosure"
        assert "sha256-unique-abc" not in stripped, "content_hash leaked outside disclosure"


class TestRendererContractPreserved:
    """AC5 — Markdown renderer contract unchanged."""

    def test_properties_renderer_html_inside_disclosure(self) -> None:
        html = _render(body=_FRONTMATTER_BODY)
        assert 'data-testid="workspace-note-properties"' in html

    def test_all_frontmatter_keys_still_surfaced(self) -> None:
        html = _render(body=_FRONTMATTER_BODY)
        disc_m = re.search(
            r'data-testid="workspace-properties-disclosure".*?</details>',
            html,
            re.DOTALL,
        )
        assert disc_m
        disc_html = disc_m.group()
        assert "kind" in disc_html
        assert "review" in disc_html
        assert "trust" in disc_html
        assert "tags" in disc_html
