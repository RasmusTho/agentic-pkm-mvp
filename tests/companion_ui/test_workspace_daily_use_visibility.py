"""Tests for the daily-use visibility contract pass (#1361).

Covers five acceptance areas from the companion daily-use visibility contract:

A — Header chrome: dev controls behind disclosure, runtime identity always visible.
B — Panel visual states: disabled/degraded surfaces suppressed, not duplicated.
C — Vault browser: companion/UUID notes hidden, calm provenance, human titles.
D — Read-only body affordance: indicator visible, reason present, Why? link wired.
E — Breadcrumb/properties: closed summary humanizes review_state via _humanize_fm_pair.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html, _humanize_fm_pair


# ---------------------------------------------------------------------------
# Shared fixture (mirrors test_workspace_shell_alignment._fields / _html)
# ---------------------------------------------------------------------------


def _fields(
    *,
    body: str = "# Note\n\nBody content here.",
    title: str = "Note Title",
    note_path: str = "Notes/note.md",
    artifact_id: str = "art-daily",
    content_hash: str = "sha256-bbb",
    guard_writeguard_status: str = "ok",
    guard_canvas_enabled: bool = True,
    guard_degraded: bool = False,
    guard_workspace_update_available: bool = True,
    guard_update_flow_available: bool = True,
    runtime_vault_provenance: str = "resolved",
    runtime_vault_name: str = "vault/dev",
    runtime_vault_channel: str = "local-dev",
    panel_state: str = "idle",
    panel_proposal_count: int = 0,
    canvas_session_state: str = "idle",
    canvas_session_persistence: str = "durable",
    panel_proposals: list | None = None,
    panel_message: str = "",
    find_candidates: list | None = None,
    reorient_sections: dict | None = None,
    resurface_candidates: list | None = None,
    governance_receipts: list | None = None,
    suggestion_state: str = "idle",
    suggestion_composer_enabled: bool = True,
    vault_browser_notes: list | None = None,
    vault_browser_vault_provenance: str = "resolved",
    vault_browser_read_only: bool = True,
    vault_browser_identity_available: bool = False,
    vault_browser_vault_name: str = "vault/dev",
    vault_browser_vault_channel: str = "local-dev",
) -> dict:
    return {
        "title": title,
        "note_path": note_path,
        "artifact_id": artifact_id,
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": content_hash,
        "body": body,
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": runtime_vault_name,
        "runtime_vault_channel": runtime_vault_channel,
        "runtime_vault_provenance": runtime_vault_provenance,
        "canvas_session_state": canvas_session_state,
        "canvas_session_persistence": canvas_session_persistence,
        "panel_state": panel_state,
        "panel_proposal_count": panel_proposal_count,
        "panel_proposals": panel_proposals or [],
        "panel_message": panel_message,
        "guard_writeguard_status": guard_writeguard_status,
        "guard_canvas_enabled": guard_canvas_enabled,
        "guard_degraded": guard_degraded,
        "guard_workspace_update_available": guard_workspace_update_available,
        "guard_update_flow_available": guard_update_flow_available,
        "find_candidates": find_candidates or [],
        "find_payload_available": False,
        "reorient_sections": reorient_sections or {},
        "resurface_candidates": resurface_candidates or [],
        "governance_receipts": governance_receipts or [],
        "suggestion_state": suggestion_state,
        "suggestion_composer_enabled": suggestion_composer_enabled,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "vault_browser_notes": vault_browser_notes or [],
        "vault_browser_query": "",
        "vault_browser_total_notes": len(vault_browser_notes or []),
        "vault_browser_filtered_notes": len(vault_browser_notes or []),
        "vault_browser_error": None,
        "vault_browser_read_only": vault_browser_read_only,
        "vault_browser_identity_available": vault_browser_identity_available,
        "vault_browser_vault_name": vault_browser_vault_name,
        "vault_browser_vault_channel": vault_browser_vault_channel,
        "vault_browser_vault_provenance": vault_browser_vault_provenance,
        "vault_browser_active_filters": {},
    }


def _html(**kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=kw.get("note_path", "Notes/note.md"),
        fields=_fields(**kw),
    )


# ---------------------------------------------------------------------------
# Area A — Header chrome / dev disclosure
# ---------------------------------------------------------------------------


class TestDevControlsDisclosure:
    def test_dev_controls_behind_details_element(self) -> None:
        html = _html()
        assert 'data-testid="workspace-dev-controls"' in html
        # The controls must be inside a <details> element, not bare.
        m = re.search(
            r'<details[^>]*data-testid="workspace-dev-controls"',
            html,
        )
        assert m, "workspace-dev-controls must be a <details> element"

    def test_dev_controls_toggle_has_label(self) -> None:
        html = _html()
        assert 'data-testid="workspace-dev-controls-toggle"' in html

    def test_runtime_environment_always_visible(self) -> None:
        # The runtime safety strip (vault name, channel, trace id) must appear at
        # module level, outside the dev-controls disclosure.
        html = _html()
        dev_controls_pos = html.find('data-testid="workspace-dev-controls"')
        # Runtime channel indicator is always present in the safety strip
        channel_pos = html.find('data-testid="workspace-runtime-channel"')
        assert channel_pos != -1, "workspace-runtime-channel must be present"
        # The safety strip is rendered as a sibling to (not inside) the dev-controls disclosure.
        # It appears after the topbar in source order, so it will have a different position.
        assert dev_controls_pos != -1, "workspace-dev-controls must be present"
        # Both elements must be present — verifying they are not inside each other
        # by confirming dev-controls content does not contain runtime-channel testid.
        dev_controls_m = re.search(
            r'data-testid="workspace-dev-controls".*?</details>',
            html,
            re.DOTALL,
        )
        assert dev_controls_m, "workspace-dev-controls details element must be present"
        assert 'data-testid="workspace-runtime-channel"' not in dev_controls_m.group(), (
            "workspace-runtime-channel must not be inside the dev-controls disclosure"
        )


# ---------------------------------------------------------------------------
# Area B — Panel disabled/degraded surfaces suppressed
# ---------------------------------------------------------------------------


class TestPanelDisabledSuppression:
    def test_canvas_body_edit_unavailable_suppressed_when_canvas_disabled(self) -> None:
        html = _html(guard_canvas_enabled=False)
        # When canvas is disabled the unavailable element must be hidden.
        m = re.search(
            r'data-testid="workspace-canvas-body-edit-unavailable"[^>]*>',
            html,
        )
        assert m, "canvas-body-edit-unavailable element must be present in DOM"
        snippet = m.group()
        assert "hidden" in snippet or 'data-affordance-status="blocked"' in snippet, (
            "canvas-body-edit-unavailable must carry hidden or blocked status when suppressed"
        )

    def test_active_note_body_update_blocked_suppressed_when_disabled(self) -> None:
        # active_note_body_update_enabled defaults to guard_workspace_update_available
        html = _html(guard_workspace_update_available=False)
        m = re.search(
            r'data-testid="workspace-active-note-body-update-state-blocked"[^>]*>',
            html,
        )
        assert m, "active-note-body-update-state-blocked must be present in DOM"
        snippet = m.group()
        assert "hidden" in snippet, (
            "active-note-body-update-state-blocked must be hidden when update flow disabled"
        )

    def test_no_duplicate_canvas_unavailable_messages(self) -> None:
        html = _html(guard_canvas_enabled=False, guard_workspace_update_available=False)
        # canvas-body-edit-unavailable must be suppressed (hidden attr or --suppressed modifier)
        # when canvas is disabled — no duplicate "Body editing unavailable" banner.
        m = re.search(
            r'class="canvas-body-edit-unavailable canvas-body-edit-unavailable--suppressed"[^>]* hidden',
            html,
        )
        assert m, (
            "canvas-body-edit-unavailable must carry --suppressed and hidden when canvas is disabled"
        )


# ---------------------------------------------------------------------------
# Area C — Vault browser: filtering and calm provenance
# ---------------------------------------------------------------------------


_COMPANION_NOTE = {
    "note_path": "Notes/.meta/Companion.md",
    "title": "Companion note",
    "kind": "companion_note",
    "zone": "active",
}

_UUID_NOTE = {
    "note_path": "Notes/11111111-2222-3333-4444-555555555555.md",
    "title": "UUID note",
    "kind": "human_note",
    "zone": "active",
}

_HUMAN_NOTE = {
    "note_path": "Notes/My Note.md",
    "title": "My Note",
    "kind": "human_note",
    "zone": "active",
}


class TestVaultBrowserFiltering:
    def test_companion_note_not_in_nav_list(self) -> None:
        html = _html(vault_browser_notes=[_COMPANION_NOTE, _HUMAN_NOTE])
        # Companion note must be rendered hidden in the DOM (data-nav-visible="false")
        # not as an active nav link. It carries data-companion="true" on the <li>.
        companion_row_m = re.search(
            r'<li[^>]*data-companion="true"[^>]*data-nav-visible="false"[^>]*>',
            html,
        )
        assert companion_row_m, (
            "companion note row must be in DOM with data-companion=true and data-nav-visible=false"
        )
        # Human note must still appear as a visible nav link.
        assert "My Note" in html, "human note must still appear"

    def test_uuid_filename_note_not_in_nav_list(self) -> None:
        html = _html(vault_browser_notes=[_UUID_NOTE, _HUMAN_NOTE])
        # UUID-filename notes must be rendered hidden in the DOM (data-nav-visible="false").
        uuid_row_m = re.search(
            r'<li[^>]*data-nav-visible="false"[^>]*hidden[^>]*>.*?11111111-2222-3333-4444-555555555555',
            html,
            re.DOTALL,
        )
        assert uuid_row_m, "UUID-filename note row must be in DOM with data-nav-visible=false"
        assert "My Note" in html, "human note must still appear"

    def test_hidden_count_shown_when_notes_filtered(self) -> None:
        html = _html(vault_browser_notes=[_COMPANION_NOTE, _UUID_NOTE, _HUMAN_NOTE])
        assert 'data-testid="workspace-vault-browser-hidden-count"' in html
        m = re.search(
            r'data-hidden="(\d+)"',
            html,
        )
        assert m, "data-hidden attribute must be present on hidden-count span"
        assert int(m.group(1)) == 2, "two system notes should be hidden"

    def test_hidden_count_absent_when_nothing_filtered(self) -> None:
        html = _html(vault_browser_notes=[_HUMAN_NOTE])
        assert 'data-testid="workspace-vault-browser-hidden-count"' not in html

    def test_calm_provenance_label_shown(self) -> None:
        html = _html(vault_browser_read_only=True)
        m = re.search(
            r'data-testid="workspace-vault-browser-provenance"[^>]*>([^<]+)<',
            html,
        )
        assert m, "vault-browser-provenance must be present"
        label = m.group(1).strip()
        assert label == "read-only fallback · filesystem index", (
            f"calm provenance label must be 'read-only fallback · filesystem index', got {label!r}"
        )

    def test_raw_provenance_in_data_attribute(self) -> None:
        html = _html(vault_browser_vault_provenance="local-filesystem", vault_browser_read_only=True)
        assert 'data-raw-provenance="local-filesystem"' in html, (
            "raw provenance must be retained in data-raw-provenance for debugging"
        )

    def test_nav_badge_data_testids_present_but_visually_hidden(self) -> None:
        note_with_meta = {**_HUMAN_NOTE, "review_state": "needs_review", "trust": "trusted"}
        html = _html(vault_browser_notes=[note_with_meta])
        # testid present for test compatibility
        assert 'data-testid="workspace-vault-browser-note-review-state"' in html
        assert 'data-testid="workspace-vault-browser-note-trust"' in html
        # badges carry the nav-hidden class
        assert 'data-nav-visible="false"' in html


# ---------------------------------------------------------------------------
# Area D — Read-only body affordance
# ---------------------------------------------------------------------------


class TestReadOnlyBodyAffordance:
    def test_readonly_indicator_present(self) -> None:
        html = _html()
        assert 'data-testid="workspace-note-body-readonly-indicator"' in html

    def test_readonly_indicator_on_note_body(self) -> None:
        # Direct human editing is always available, so the note body is no longer
        # read-only just because Canvas is off (#1447). The attribute is present
        # for inspectability but now reflects the editable state.
        html = _html()
        note_body_m = re.search(
            r'data-testid="workspace-note-body"[^>]*data-read-only="([^"]*)"',
            html,
        )
        assert note_body_m, "workspace-note-body must carry data-read-only attribute"
        assert note_body_m.group(1) == "false"

    def test_readonly_reason_element_present(self) -> None:
        html = _html()
        assert 'data-testid="workspace-note-body-readonly-reason"' in html

    def test_readonly_reason_contains_why_link(self) -> None:
        html = _html()
        reason_m = re.search(
            r'data-testid="workspace-note-body-readonly-reason".*?</div>',
            html,
            re.DOTALL,
        )
        assert reason_m, "readonly-reason div must be present"
        assert 'data-testid="workspace-note-body-readonly-why"' in reason_m.group(), (
            "readonly-reason must contain a Why? link with the correct testid"
        )

    def test_readonly_why_link_points_to_runtime_telemetry(self) -> None:
        html = _html()
        m = re.search(
            r'data-testid="workspace-note-body-readonly-why"[^>]*href="([^"]*)"',
            html,
        )
        if not m:
            # href may be on the <a> before the data-testid
            m = re.search(
                r'href="([^"]*)"[^>]*data-testid="workspace-note-body-readonly-why"',
                html,
            )
        assert m, "readonly-why link must have an href"
        href = m.group(1)
        assert "workspace-runtime-telemetry" in href, (
            f"Why? link must target #workspace-runtime-telemetry, got {href!r}"
        )

    def test_runtime_telemetry_anchor_present(self) -> None:
        html = _html()
        assert 'data-testid="workspace-runtime-telemetry"' in html


# ---------------------------------------------------------------------------
# Area E — Frontmatter humanization
# ---------------------------------------------------------------------------


class TestFrontmatterHumanization:
    def test_humanize_review_state_needs_review(self) -> None:
        result = _humanize_fm_pair("review_state", "needs_review")
        assert result == "review · needs review"

    def test_humanize_review_state_reviewed(self) -> None:
        result = _humanize_fm_pair("review_state", "reviewed")
        assert result == "review · reviewed"

    def test_humanize_lifecycle_state_active(self) -> None:
        result = _humanize_fm_pair("lifecycle_state", "active")
        assert result == "lifecycle · active"

    def test_humanize_note_type_human_note(self) -> None:
        result = _humanize_fm_pair("note_type", "human_note")
        assert result == "type · note"

    def test_humanize_kind_companion_note(self) -> None:
        result = _humanize_fm_pair("kind", "companion_note")
        assert result == "type · companion"

    def test_humanize_zone(self) -> None:
        result = _humanize_fm_pair("zone", "active_zone")
        assert result == "zone · active zone"

    def test_humanize_unknown_key_returns_none(self) -> None:
        result = _humanize_fm_pair("uuid", "some-uuid-value")
        assert result is None

    def test_frontmatter_disclosure_present_when_frontmatter_in_body(self) -> None:
        body_with_fm = (
            "---\n"
            "review_state: needs_review\n"
            "lifecycle_state: active\n"
            "---\n"
            "# Heading\n\nBody text.\n"
        )
        html = _html(body=body_with_fm)
        assert 'data-testid="workspace-frontmatter-disclosure"' in html

    def test_frontmatter_summary_humanizes_review_state(self) -> None:
        body_with_fm = (
            "---\n"
            "review_state: needs_review\n"
            "lifecycle_state: active\n"
            "---\n"
            "# Heading\n\nBody text.\n"
        )
        html = _html(body=body_with_fm)
        summary_m = re.search(
            r'data-testid="workspace-frontmatter-summary"[^>]*>(.*?)</summary>',
            html,
            re.DOTALL,
        )
        assert summary_m, "frontmatter-summary must be present"
        summary_text = summary_m.group(1)
        assert "review" in summary_text.lower(), (
            "summary must contain humanized review label"
        )
        assert "needs_review" not in summary_text, (
            "raw snake_case key must not appear in summary"
        )
