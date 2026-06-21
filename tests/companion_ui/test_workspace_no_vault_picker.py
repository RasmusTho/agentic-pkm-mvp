"""No-vault picker rendering on the primary Companion surfaces (#2309).

When the runtime reports no selected vault it returns the 200
``vault_selection_required`` picker payload on the orientation and workspace
boundaries (Option-2 decision, 2026-06-20). The page server must render the
vault picker — never a blank ``shell_active`` note (note-load path) and never a
fabricated ``cold_start`` orientation (home path). Server declares; UI renders.
"""
from __future__ import annotations

from typing import Any

from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError

_PICKER_PAYLOAD: dict[str, Any] = {
    "state": "vault_selection_required",
    "reason": "no_vault_bound",
    "message": "No vault is selected. Open the configured vault to continue.",
    "configured_vault_root": "/Users/me/Vaults/Niflheim",
    "requested_note_path": "Agenter och skills i yggdrasil.md",
    "context": {"status": "none"},
    "recent_vaults": [],
    "actions": [],
}


class _PickerClient:
    """Fake WorkspaceHttpClient whose every boundary returns the picker payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.get_calls: list[tuple[str, dict]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self._payload

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        return {}


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [],
        "query": "",
        "total_notes": 0,
        "filtered_notes": 0,
        "read_only": True,
        "identity_available": True,
        "vault_identity": {
            "vault_name": "Niflheim",
            "channel": "dev",
            "provenance": "selected",
        },
        "active_filters": {},
        "pagination": {},
    }


class _OrientationUnavailableClient:
    def __init__(self, vault_browser_payload: dict[str, Any]) -> None:
        self._vault_browser_payload = vault_browser_payload
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url == "/api/companion/orientation":
            raise WorkspaceClientNetworkError("orientation unavailable")
        if url == "/api/companion/vault-browser":
            return self._vault_browser_payload
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        return {}


def test_note_load_picker_payload_renders_picker_not_blank_note() -> None:
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="note_path=Agenter%20och%20skills%20i%20yggdrasil.md",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    # The vault picker surface is rendered, in the declared no_vault entry state...
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-entry-state="no_vault"' in html
    # ...offering the server-declared configured vault as a one-click open...
    assert 'data-testid="vault-selection-open-configured"' in html
    # ...and NOT a loaded/blank note shell.
    assert 'data-region="document-anchor"' not in html
    assert 'data-testid="workspace-note-frontmatter"' not in html
    # The workspace boundary was queried; the picker short-circuits the load.
    assert any(url == "/api/companion/workspace" for url, _ in client.get_calls)


def test_home_picker_payload_renders_picker_not_cold_start() -> None:
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-entry-state="no_vault"' in html
    # NOT a fabricated cold_start orientation with vault_id "unknown".
    assert 'data-region="cold-start-threshold"' not in html
    assert 'data-region="reentry-card"' not in html
    # The orientation boundary was queried.
    assert any(url == "/api/companion/orientation" for url, _ in client.get_calls)


def test_no_vault_orientation_unavailable_suppresses_degraded_banner() -> None:
    client = _OrientationUnavailableClient(_vault_browser_payload())

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.get_calls == [
        ("/api/companion/orientation", {}),
        ("/api/companion/vault-browser", {"q": "", "limit": 250}),
    ]
    assert 'data-entry-state="no_vault"' in html
    assert 'data-testid="workspace-vault-unreachable-threshold"' in html
    assert 'data-testid="workspace-orientation-degraded"' not in html
    assert "Partial orientation" not in html
    assert "orientation_unavailable" in html


def test_orientation_unavailable_preserves_vault_browser_identity() -> None:
    client = _OrientationUnavailableClient(_vault_browser_payload())

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    identity = html.split('data-testid="workspace-vault-browser-active-identity"', 1)[1].split("</span>", 1)[0]
    assert "Niflheim/dev" in identity
    assert "unknown/dev" not in identity
    assert "unknown/unknown" not in identity


def test_picker_without_configured_root_omits_one_click_open() -> None:
    payload = dict(_PICKER_PAYLOAD)
    payload["configured_vault_root"] = None
    client = _PickerClient(payload)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    assert 'data-testid="vault-selection-required"' in html
    # No configured root → no one-click "open configured" affordance.
    assert 'data-testid="vault-selection-open-configured"' not in html


def test_valid_note_does_not_render_visible_vault_settings_panel() -> None:
    fields: dict[str, Any] = {
        "title": "Companion UI UAT",
        "note_path": "Companion UI UAT.md",
        "artifact_id": "note-uat",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-uat",
        "body": "# Companion UI UAT\n\nReady.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-uat",
        "runtime_vault_name": "Niflheim",
        "runtime_vault_channel": "dev",
        "runtime_vault_provenance": "selected",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "in_memory",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
    }
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Companion UI UAT.md",
        fields=fields,
    )

    assert 'data-entry-state="shell_active"' in html
    assert "Companion UI UAT" in html
    assert 'data-testid="vault-selection-required"' not in html
    assert 'data-testid="vault-settings-panel"' in html
    assert 'data-testid="workspace-surface-icon-vault-settings"' in html
    assert 'data-intent="vault.settings.open"' in html
    assert 'aria-controls="workspace-vault-settings-panel"' in html
    assert "window.companionVaultSettings" in html

    panel_start = html.index('<section class="vault-settings-panel"')
    panel_tag_end = html.index(">", panel_start)
    panel_tag = html[panel_start:panel_tag_end]
    assert " hidden" in panel_tag
    assert 'aria-hidden="true"' in panel_tag
    assert " inert" in panel_tag
    assert 'data-display-mode="drawer"' in panel_tag
    assert 'data-open="false"' in panel_tag
    assert ".vault-settings-panel[hidden] { display: none !important; }" in html
    assert 'data-testid="vault-settings-panel-close"' in html
