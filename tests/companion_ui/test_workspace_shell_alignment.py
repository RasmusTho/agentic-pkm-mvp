"""Tests for the workspace shell alignment with the Vault Browser orientation contract (#1260).

Eight acceptance criteria from the issue are covered:

AC1 — workspace body rendering does not display YAML frontmatter as normal body.
AC2 — frontmatter-derived identity/metadata remains visible.
AC3 — safety/status presentation consolidated into one primary posture surface.
AC4 — degraded/blocked/unavailable visibly distinct from ok/available.
AC5 — unavailable actions render as absence/reason states or clearly non-actionable controls.
AC6 — human-facing copy replaces internal runtime/test labels; internal state lives in data-*.
AC7 — empty/inactive rail cards collapse to a single no-active-session/unavailable state.

AC8 (existing MLP v0 tests still pass) is verified by the existing test files
``test_vault_browser.py`` and ``test_companion_vault_browser_api.py``.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


def _fields(
    *,
    body: str = "# Note\n\nBody content here.",
    title: str = "Note Title",
    note_path: str = "Notes/note.md",
    artifact_id: str = "art-123",
    content_hash: str = "sha256-aaa",
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
    }


def _html(**kw) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=kw.get("note_path", "Notes/note.md"),
        fields=_fields(**kw),
    )


def _body_region(html: str) -> str:
    m = re.search(r'data-testid="workspace-note-body".*?</div>', html, re.DOTALL)
    assert m, "workspace-note-body region not found"
    return m.group()


def _rail_region(html: str) -> str:
    m = re.search(r'data-testid="workspace-agent-rail".*?</aside>', html, re.DOTALL)
    assert m, "workspace-agent-rail region not found"
    return m.group()


# ---------------------------------------------------------------------------
# AC1 — frontmatter not rendered as note body
# ---------------------------------------------------------------------------


_FRONTMATTER_BODY = (
    "---\n"
    "uuid: 11111111-2222-3333-4444-555555555555\n"
    "kind: human_note\n"
    "zone: active\n"
    "tags:\n"
    "  - companion-ui\n"
    "---\n"
    "# Heading\n"
    "\n"
    "Body paragraph here.\n"
)


class TestFrontmatterStrippedFromBody:
    def test_frontmatter_block_not_in_body_region(self) -> None:
        html = _html(body=_FRONTMATTER_BODY)
        body = _body_region(html)
        assert "uuid: 11111111" not in body
        assert "- companion-ui" not in body

    def test_body_content_remains_in_body_region(self) -> None:
        html = _html(body=_FRONTMATTER_BODY)
        body = _body_region(html)
        assert "Body paragraph here." in body
        assert '<h1 id="heading">Heading</h1>' in body

    def test_body_without_frontmatter_unchanged(self) -> None:
        body_only = "# Plain note\n\nNo frontmatter."
        html = _html(body=body_only)
        body = _body_region(html)
        assert '<h1 id="plain-note">Plain note</h1>' in body
        assert "No frontmatter." in body

    def test_frontmatter_region_present_when_frontmatter_exists(self) -> None:
        html = _html(body=_FRONTMATTER_BODY)
        assert 'data-testid="workspace-note-frontmatter"' in html
        assert 'data-frontmatter-present="true"' in html

    def test_frontmatter_region_marked_absent_when_no_frontmatter(self) -> None:
        html = _html(body="# Plain\nbody only")
        assert 'data-frontmatter-present="false"' in html

    def test_frontmatter_keys_surfaced_in_frontmatter_region(self) -> None:
        html = _html(body=_FRONTMATTER_BODY)
        m = re.search(
            r'data-testid="workspace-note-frontmatter".*?</section>',
            html,
            re.DOTALL,
        )
        assert m, "workspace-note-frontmatter region not found"
        region = m.group()
        assert "uuid" in region
        assert "kind" in region


# ---------------------------------------------------------------------------
# AC2 — identity/metadata visible in bounded chrome
# ---------------------------------------------------------------------------


class TestIdentityChromePersists:
    def test_artifact_identity_pill_present_with_frontmatter_body(self) -> None:
        html = _html(body=_FRONTMATTER_BODY, artifact_id="art-xyz")
        assert 'data-testid="workspace-artifact-identity-pill"' in html
        assert "art-xyz" in html

    def test_content_hash_pill_present_with_frontmatter_body(self) -> None:
        html = _html(body=_FRONTMATTER_BODY, content_hash="sha256-zzz")
        assert 'data-testid="workspace-content-hash-pill"' in html
        assert "sha256-zzz" in html

    def test_path_visible(self) -> None:
        html = _html(body=_FRONTMATTER_BODY, note_path="Inbox/foo.md")
        assert "Inbox/foo.md" in html


# ---------------------------------------------------------------------------
# AC3 — primary posture surface
# ---------------------------------------------------------------------------


class TestPrimaryPostureSurface:
    def test_primary_posture_present(self) -> None:
        html = _html()
        assert 'data-testid="workspace-primary-posture"' in html

    def test_primary_posture_ok_when_no_problems(self) -> None:
        html = _html()
        assert re.search(r'data-testid="workspace-primary-posture"[^>]*data-posture="ok"', html)

    def test_primary_posture_blocked_when_writeguard_blocked(self) -> None:
        html = _html(guard_writeguard_status="blocked")
        assert re.search(
            r'data-testid="workspace-primary-posture"[^>]*data-posture="blocked"', html
        )

    def test_primary_posture_degraded_when_guard_degraded(self) -> None:
        html = _html(guard_degraded=True)
        assert re.search(
            r'data-testid="workspace-primary-posture"[^>]*data-posture="degraded"', html
        )

    def test_primary_posture_unavailable_when_vault_unresolved(self) -> None:
        html = _html(runtime_vault_provenance="unresolved")
        assert re.search(
            r'data-testid="workspace-primary-posture"[^>]*data-posture="unavailable"', html
        )

    def test_primary_posture_blocked_overrides_degraded(self) -> None:
        html = _html(guard_writeguard_status="blocked", guard_degraded=True)
        assert re.search(
            r'data-testid="workspace-primary-posture"[^>]*data-posture="blocked"', html
        )

    def test_primary_posture_has_human_label(self) -> None:
        html = _html()
        m = re.search(
            r'data-testid="workspace-primary-posture".*?</section>',
            html,
            re.DOTALL,
        )
        assert m
        region = m.group()
        assert "Online" in region or "Ok" in region or "Ready" in region


# ---------------------------------------------------------------------------
# AC4 — visibly distinct posture tones
# ---------------------------------------------------------------------------


class TestDistinctPostureTones:
    def test_ok_tone_class(self) -> None:
        html = _html()
        assert 'class="primary-posture posture-tone-ok"' in html or \
            'posture-tone-ok' in html

    def test_degraded_tone_class(self) -> None:
        html = _html(guard_degraded=True)
        assert "posture-tone-degraded" in html

    def test_blocked_tone_class(self) -> None:
        html = _html(guard_writeguard_status="blocked")
        assert "posture-tone-blocked" in html

    def test_unavailable_tone_class(self) -> None:
        html = _html(runtime_vault_provenance="unresolved")
        assert "posture-tone-unavailable" in html


# ---------------------------------------------------------------------------
# AC5 — absence states for unavailable actions
# ---------------------------------------------------------------------------


class TestAbsenceForUnavailableActions:
    def test_body_edit_absence_card_when_update_flow_disabled(self) -> None:
        html = _html(guard_update_flow_available=False)
        assert 'data-testid="workspace-action-absent"' in html
        assert 'data-action="body-edit"' in html

    def test_body_edit_absence_carries_reason(self) -> None:
        html = _html(guard_update_flow_available=False)
        m = re.search(
            r'data-testid="workspace-action-absent"[^>]*data-action="body-edit".*?</section>',
            html,
            re.DOTALL,
        )
        assert m
        # absence card must say why
        assert "unavailable" in m.group().lower() or "disabled" in m.group().lower()

    def test_no_actionable_submit_button_when_update_flow_disabled(self) -> None:
        html = _html(guard_update_flow_available=False)
        # No clickable Apply update button when the flow is unavailable.
        assert 'data-testid="workspace-body-edit-submit"' not in html

    def test_active_note_body_update_absence_when_disabled(self) -> None:
        html = _html(guard_workspace_update_available=False)
        # Existing testid already differentiates the disabled card; just confirm
        # the absence is still rendered (regression guard).
        assert 'data-testid="workspace-active-note-body-update-state-blocked"' in html


# ---------------------------------------------------------------------------
# AC6 — human-facing copy with data-* internal state
# ---------------------------------------------------------------------------


class TestHumanFacingCopy:
    def test_primary_posture_has_data_posture_attr(self) -> None:
        """Internal posture token lives in data-* so tests don't depend on copy."""
        html = _html()
        assert 'data-posture="ok"' in html

    def test_composer_state_data_attr_present(self) -> None:
        """Composer enabled/locked exposes its internal state as a data-* attribute."""
        html = _html(suggestion_composer_enabled=True)
        assert 'data-composer-state="enabled"' in html

    def test_composer_state_data_attr_when_locked(self) -> None:
        html = _html(suggestion_composer_enabled=False)
        assert 'data-composer-state="locked"' in html

    def test_workspace_update_label_has_human_text(self) -> None:
        """A human-friendly label is used somewhere in posture chrome."""
        html = _html()
        # "Online" is the human-facing posture phrase for ok.
        assert "Online" in html


# ---------------------------------------------------------------------------
# AC7 — rail empty state
# ---------------------------------------------------------------------------


class TestRailEmptyState:
    def test_rail_empty_state_present_when_fully_idle(self) -> None:
        html = _html()
        rail = _rail_region(html)
        assert 'data-testid="workspace-rail-empty-state"' in rail

    def test_rail_empty_state_carries_human_copy(self) -> None:
        html = _html()
        m = re.search(
            r'data-testid="workspace-rail-empty-state".*?</div>',
            html,
            re.DOTALL,
        )
        assert m
        text = m.group().lower()
        assert "no active session" in text or "no active panel" in text or "nothing active" in text

    def test_rail_empty_state_absent_when_proposals_present(self) -> None:
        html = _html(
            panel_proposals=[
                {
                    "proposal_id": "p1",
                    "summary": "do thing",
                    "status": "pending",
                }
            ],
            panel_proposal_count=1,
            panel_state="proposal_staged",
        )
        rail = _rail_region(html)
        assert 'data-testid="workspace-rail-empty-state"' not in rail

    def test_rail_empty_state_absent_when_canvas_active(self) -> None:
        html = _html(canvas_session_state="composing")
        rail = _rail_region(html)
        assert 'data-testid="workspace-rail-empty-state"' not in rail

def test_malformed_frontmatter_is_omitted_from_body_with_diagnostic() -> None:
    body = "---\nThis is prose, not yaml: [\n---\n\nParagraph stays.\n"
    html = _html(body=body)
    note_body = _body_region(html)
    assert "This is prose, not yaml" not in note_body
    assert "frontmatter_parse_error" in note_body
    assert "Paragraph stays." in note_body


def test_rail_empty_state_uses_rendered_panel_proposals_not_stale_count() -> None:
    html = _html(
        panel_state="idle",
        panel_proposal_count=0,
        panel_proposals=[{"proposal_id": "p1", "status": "pending", "summary": "queued"}],
    )
    rail = _rail_region(html)
    assert 'data-testid="workspace-rail-empty-state"' not in rail
