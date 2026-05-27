"""Tests for vault-unreachable banner — shell error surface (§9 / #1341 AC3–4)."""
from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _render(**overrides) -> str:
    fields: dict = {
        "title": "Test Note",
        "note_path": "Notes/test.md",
        "artifact_id": "art-001",
        "content_hash": "sha256-abc",
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
        "body": "# Cached Note\n\nThis is the cached body content.",
    }
    fields.update(overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=fields["note_path"],
        fields=fields,
    )


class TestVaultUnreachableBanner:
    def test_banner_absent_when_vault_reachable(self) -> None:
        html = _render()
        assert 'data-testid="workspace-vault-unreachable-banner"' not in html

    def test_banner_appears_with_destructive_chip_via_field(self) -> None:
        html = _render(vault_unreachable=True)
        assert 'data-testid="workspace-vault-chip"' in html
        assert 'data-state="unreachable"' in html
        assert 'data-testid="workspace-vault-unreachable-banner"' in html
        assert "last sync" in html
        assert 'data-testid="workspace-vault-retry"' in html

    def test_banner_appears_when_provenance_is_unreachable(self) -> None:
        html = _render(runtime_vault_provenance="unreachable")
        assert 'data-state="unreachable"' in html
        assert 'data-testid="workspace-vault-unreachable-banner"' in html

    def test_cached_body_still_rendered(self) -> None:
        html = _render(vault_unreachable=True, body="# Cached Note\n\nCached content here.")
        assert 'data-testid="workspace-vault-unreachable-banner"' in html
        assert "vault-markdown-rendered" in html
        assert "Cached content here" in html

    def test_banner_contains_retry_link(self) -> None:
        html = _render(vault_unreachable=True)
        assert 'data-testid="workspace-vault-retry"' in html
        assert "retry" in html
