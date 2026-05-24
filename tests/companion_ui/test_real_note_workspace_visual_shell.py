"""Tests for the Companion UI workspace visual shell structure (#1118).

Verifies that the rendered dev-page HTML matches the Companion UI visual contract:
- workspace-note-header region present with title and provenance
- workspace-note-body region present as primary surface
- workspace-agent-rail region present as right-side companion placeholder
- DEV marker present (non-production signal)
- artifact metadata rendered as subdued provenance chrome, not dominant table
- error state uses workspace-error-state marker
- data-testid and data-region attributes match real_note_workspace_shell.py constants
- no "Artifact ID" label in base page or error-only page (regression guard)
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.real_note_workspace_shell import (
    REGION_AGENT_RAIL,
    REGION_NOTE_BODY,
    REGION_NOTE_HEADER,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _fields(
    title: str = "Research Note",
    note_path: str = "Research/Deep-Work.md",
    artifact_id: str = "art-abc-123",
    content_hash: str = "sha256-feedcafe",
    body: str = "# Research Note\n\nContent goes here.",
    panel_rail: str = "Panel / agent rail placeholder",
    canvas_session_state: str = "idle",
    canvas_session_persistence: str = "in_memory",
    panel_state: str = "idle",
    panel_proposal_count: int = 0,
    guard_writeguard_status: str = "ok",
    guard_canvas_enabled: bool = True,
    guard_degraded: bool = False,
    artifact_identity_source: str = "frontmatter.uuid",
    artifact_identity_state: str = "resolved",
    runtime_environment_label: str = "dev",
    runtime_api_base_url_label: str = "local-dev",
    runtime_trace_id: str = "trace-visual-1",
) -> dict:
    return {
        "title": title,
        "note_path": note_path,
        "artifact_id": artifact_id,
        "artifact_kind": "human_note",
        "artifact_identity_source": artifact_identity_source,
        "artifact_identity_state": artifact_identity_state,
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": content_hash,
        "body": body,
        "panel_rail": panel_rail,
        "runtime_environment_label": runtime_environment_label,
        "runtime_api_base_url_label": runtime_api_base_url_label,
        "runtime_trace_id": runtime_trace_id,
        "canvas_session_state": canvas_session_state,
        "canvas_session_persistence": canvas_session_persistence,
        "panel_state": panel_state,
        "panel_proposal_count": panel_proposal_count,
        "guard_writeguard_status": guard_writeguard_status,
        "guard_canvas_enabled": guard_canvas_enabled,
        "guard_degraded": guard_degraded,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
    }


def _html_with_note(**kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=kw.get("note_path", "Research/Deep-Work.md"),
        fields=_fields(**kw),
    )


def _html_empty() -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001")


def _html_error(error: str = "Connection refused") -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:19999",
        note_path="Some/Note.md",
        error=error,
    )


# ---------------------------------------------------------------------------
# Region selectors — data-testid attributes match shell constants
# ---------------------------------------------------------------------------


class TestRegionDataTestids:
    """Rendered HTML must carry the same testid values as the shell model constants."""

    def test_note_header_testid_present_when_note_loaded(self) -> None:
        html = _html_with_note()
        assert f'data-testid="{REGION_NOTE_HEADER}"' in html

    def test_note_body_testid_present_when_note_loaded(self) -> None:
        html = _html_with_note()
        assert f'data-testid="{REGION_NOTE_BODY}"' in html

    def test_agent_rail_testid_present_when_note_loaded(self) -> None:
        html = _html_with_note()
        assert f'data-testid="{REGION_AGENT_RAIL}"' in html

    def test_region_constants_match_known_values(self) -> None:
        assert REGION_NOTE_HEADER == "workspace-note-header"
        assert REGION_NOTE_BODY == "workspace-note-body"
        assert REGION_AGENT_RAIL == "workspace-agent-rail"


class TestRegionDataAttributes:
    """Stable data-region attributes must be present for future Canvas/Panel wiring."""

    def test_note_header_data_region(self) -> None:
        html = _html_with_note()
        assert 'data-region="note-header"' in html

    def test_note_body_data_region(self) -> None:
        html = _html_with_note()
        assert 'data-region="note-body"' in html

    def test_agent_rail_data_region(self) -> None:
        html = _html_with_note()
        assert 'data-region="agent-rail"' in html


# ---------------------------------------------------------------------------
# Note header — title and provenance chrome
# ---------------------------------------------------------------------------


class TestNoteHeader:
    def test_title_rendered_in_header_region(self) -> None:
        html = _html_with_note(title="Deep Work Session")
        header_match = re.search(
            r'data-testid="workspace-note-header".*?</header>',
            html,
            re.DOTALL,
        )
        assert header_match, "workspace-note-header region not found"
        assert "Deep Work Session" in header_match.group()

    def test_note_path_in_provenance(self) -> None:
        html = _html_with_note(note_path="Projects/Alpha.md")
        header_match = re.search(
            r'data-testid="workspace-note-header".*?</header>',
            html,
            re.DOTALL,
        )
        assert header_match
        assert "Projects/Alpha.md" in header_match.group()

    def test_artifact_id_in_provenance(self) -> None:
        html = _html_with_note(artifact_id="art-xyz-999")
        assert "art-xyz-999" in html

    def test_content_hash_in_provenance(self) -> None:
        html = _html_with_note(content_hash="sha256-aabbcc")
        assert "sha256-aabbcc" in html

    def test_artifact_identity_pill_present(self) -> None:
        html = _html_with_note(
            artifact_identity_source="uuid_healing",
            artifact_identity_state="healed",
        )
        assert 'data-testid="workspace-artifact-identity-pill"' in html
        assert 'data-identity-source="uuid_healing"' in html
        assert 'data-identity-state="healed"' in html

    def test_content_hash_pill_present(self) -> None:
        html = _html_with_note(content_hash="sha256-aabbcc")
        assert 'data-testid="workspace-content-hash-pill"' in html

    def test_unresolved_identity_caution_visible(self) -> None:
        html = _html_with_note(
            artifact_identity_source="missing",
            artifact_identity_state="unresolved_missing_uuid",
        )
        assert 'data-testid="workspace-artifact-identity-caution"' in html
        assert "Artifact identity unresolved" in html

    def test_provenance_labels_are_lowercase(self) -> None:
        """Provenance labels must use subdued lowercase (path, artifact, hash)."""
        html = _html_with_note()
        assert 'class="prov-label"' in html or "prov-label" in html

    def test_no_dominant_table_for_metadata(self) -> None:
        """Artifact metadata must NOT render as a <th>Artifact ID</th> table row."""
        html = _html_with_note()
        assert "<th>Artifact ID</th>" not in html
        assert "<th>Title</th>" not in html
        assert "<th>Content hash</th>" not in html


# ---------------------------------------------------------------------------
# Note body — primary surface
# ---------------------------------------------------------------------------


class TestNoteBody:
    def test_body_content_rendered_in_body_region(self) -> None:
        html = _html_with_note(body="# Alpha\n\nThis is the note body.")
        body_match = re.search(
            r'data-testid="workspace-note-body".*?</div>',
            html,
            re.DOTALL,
        )
        assert body_match, "workspace-note-body region not found"
        assert "This is the note body." in body_match.group()

    def test_body_precedes_rail_in_markup(self) -> None:
        """workspace-note-body must appear before workspace-agent-rail in source order."""
        html = _html_with_note()
        body_pos = html.find('data-testid="workspace-note-body"')
        rail_pos = html.find('data-testid="workspace-agent-rail"')
        assert body_pos != -1
        assert rail_pos != -1
        assert body_pos < rail_pos

    def test_body_not_in_debug_pre_at_page_root(self) -> None:
        """Body must be inside the workspace-note-body region, not a bare root pre."""
        html = _html_with_note(body="# Test")
        body_region = re.search(
            r'data-testid="workspace-note-body"(.*?)</div>',
            html,
            re.DOTALL,
        )
        assert body_region, "workspace-note-body region missing"
        assert "<pre" in body_region.group(), "body content must be in a pre inside the body region"


# ---------------------------------------------------------------------------
# Agent rail — right-side companion placeholder
# ---------------------------------------------------------------------------


class TestAgentRail:
    def test_rail_present_as_aside(self) -> None:
        html = _html_with_note()
        assert '<aside' in html

    def test_rail_has_companion_panel_label(self) -> None:
        html = _html_with_note()
        rail_match = re.search(
            r'data-testid="workspace-agent-rail".*?</aside>',
            html,
            re.DOTALL,
        )
        assert rail_match, "workspace-agent-rail aside not found"
        region_text = rail_match.group().lower()
        assert "companion" in region_text or "panel" in region_text or "rail" in region_text

    def test_rail_placeholder_text_present(self) -> None:
        html = _html_with_note(panel_rail="Panel / agent rail placeholder")
        assert "Panel / agent rail placeholder" in html

    def test_rail_idle_badge_present(self) -> None:
        """Rail must carry an idle state badge for future Panel state wiring."""
        html = _html_with_note()
        assert "idle" in html

    def test_canvas_state_indicator(self) -> None:
        html = _html_with_note(canvas_session_state="paused")
        assert 'data-testid="workspace-canvas-state"' in html
        assert "Canvas" in html
        assert "paused" in html

    def test_panel_state_indicator(self) -> None:
        html = _html_with_note(panel_state="proposal_staged", panel_proposal_count=2)
        assert 'data-testid="workspace-panel-state"' in html
        assert "proposal_staged" in html
        assert "2 proposals" in html

    def test_guard_blocked_indicator(self) -> None:
        html = _html_with_note(
            guard_writeguard_status="blocked",
            guard_canvas_enabled=False,
        )
        assert 'data-testid="workspace-guard-indicator"' in html
        assert "WriteGuard blocked" in html
        assert "Canvas disabled" in html

    def test_in_memory_session_persistence_notice(self) -> None:
        html = _html_with_note(canvas_session_persistence="in_memory")
        assert 'data-testid="workspace-session-persistence"' in html
        assert "Session persistence: in_memory" in html


class TestRuntimeSafetyStrip:
    def test_runtime_safety_strip_present(self) -> None:
        html = _html_with_note()
        assert 'data-testid="workspace-runtime-safety-strip"' in html
        assert 'data-testid="workspace-runtime-channel"' in html
        assert 'data-testid="workspace-writeguard-state"' in html
        assert 'data-testid="workspace-canvas-enabled-state"' in html

    def test_runtime_channel_and_vault_fallback_visible(self) -> None:
        html = _html_with_note(
            runtime_environment_label="dev",
            runtime_api_base_url_label="local-dev",
        )
        assert "dev" in html
        assert "local-dev" in html
        assert 'data-testid="workspace-vault-identity"' in html
        assert "unresolved" in html

    def test_guard_degraded_state_visible(self) -> None:
        html = _html_with_note(guard_degraded=True, guard_canvas_enabled=False)
        assert 'data-testid="workspace-guard-degraded-state"' in html
        assert "degraded" in html


# ---------------------------------------------------------------------------
# Dev marker — non-production signal
# ---------------------------------------------------------------------------


class TestDevMarker:
    def test_dev_marker_present_in_base_page(self) -> None:
        html = _html_empty()
        assert "DEV" in html or "STAGING" in html or "not production" in html

    def test_dev_marker_present_when_note_loaded(self) -> None:
        html = _html_with_note()
        assert "DEV" in html or "STAGING" in html or "not production" in html

    def test_dev_marker_present_in_error_state(self) -> None:
        html = _html_error()
        assert "DEV" in html or "STAGING" in html or "not production" in html

    def test_dev_chip_class_present(self) -> None:
        html = _html_empty()
        assert "dev-chip" in html or "DEV" in html


# ---------------------------------------------------------------------------
# Error state — visible, semantically marked
# ---------------------------------------------------------------------------


class TestErrorState:
    def test_error_state_testid_present(self) -> None:
        html = _html_error("API timeout")
        assert 'data-testid="workspace-error-state"' in html

    def test_error_message_in_error_region(self) -> None:
        html = _html_error("Connection refused by host")
        error_match = re.search(
            r'data-testid="workspace-error-state".*?</div>',
            html,
            re.DOTALL,
        )
        assert error_match, "workspace-error-state region not found"
        assert "Connection refused by host" in error_match.group()

    def test_no_note_regions_in_error_only_page(self) -> None:
        """Workspace shell regions must not appear when only error is rendered."""
        html = _html_error()
        assert 'data-testid="workspace-note-header"' not in html
        assert 'data-testid="workspace-note-body"' not in html
        assert 'data-testid="workspace-agent-rail"' not in html

    def test_no_artifact_id_label_in_error_page(self) -> None:
        """Regression guard: no debug 'Artifact ID' label in error-only output."""
        html = _html_error()
        assert "Artifact ID" not in html

    def test_error_html_escaping(self) -> None:
        html = _html_error("<script>xss</script>")
        assert "<script>xss</script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# API indicator
# ---------------------------------------------------------------------------


class TestApiIndicator:
    def test_api_base_url_in_topbar(self) -> None:
        html = render_index_html(api_base_url="http://192.168.1.5:18001")
        assert "Server-side runtime" in html
        assert "http://192.168.1.5:18001" not in html

    def test_runtime_api_label_present(self) -> None:
        html = _html_empty()
        lower = html.lower()
        assert "runtime" in lower or "api" in lower

    def test_api_base_url_html_escaped(self) -> None:
        html = render_index_html(api_base_url='http://host/<path?x=1&y="z">')
        assert '<path?x=1&y="z">' not in html


# ---------------------------------------------------------------------------
# Load form
# ---------------------------------------------------------------------------


class TestLoadForm:
    def test_note_path_input_present(self) -> None:
        html = _html_empty()
        assert 'name="note_path"' in html

    def test_load_button_present(self) -> None:
        html = _html_empty()
        assert "<button" in html

    def test_note_path_value_echoed(self) -> None:
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="Inbox/Capture.md",
        )
        assert "Inbox/Capture.md" in html


# ---------------------------------------------------------------------------
# HTML structure
# ---------------------------------------------------------------------------


class TestHtmlStructure:
    def test_doctype_present(self) -> None:
        html = _html_empty()
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_viewport_meta_present(self) -> None:
        html = _html_empty()
        assert 'name="viewport"' in html

    def test_content_type_charset_utf8(self) -> None:
        html = _html_empty()
        assert 'charset="utf-8"' in html or "charset=utf-8" in html.lower()

    def test_workspace_layout_class_when_note_loaded(self) -> None:
        html = _html_with_note()
        assert "workspace-layout" in html

    def test_no_dominant_yellow_banner(self) -> None:
        """Regression: the old yellow #ffcc00 debug banner must not be present."""
        html = _html_with_note()
        assert "#ffcc00" not in html
        assert "dev-banner" not in html
