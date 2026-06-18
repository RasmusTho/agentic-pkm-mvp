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


# The HTTP 503 contract-error body the runtime returns when the orientation
# aggregate is unreachable (companion-ui WORKSPACE_ORIENTATION_CONTRACT.md
# §Runtime Unavailable). The workspace HTTP client wraps it as
# ``HTTP 503: <json>`` (workspace_http_client.WorkspaceClientHTTPError).
_RUNTIME_UNAVAILABLE_503 = (
    'HTTP 503: {"detail": {"error": "runtime_unavailable", '
    '"message": "The workspace orientation source could not be reached", '
    '"trace_id": "trace-abc", "contract_version": "1"}}'
)


def _render_error(error: str) -> str:
    """Render the error-page entry surface (no note anchor, no orientation)."""
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        fields=None,
        error=error,
    )


class TestVaultUnreachableEntryState:
    """#2123 — HTTP 503 runtime_unavailable renders the designed entry state."""

    def test_http_503_runtime_unavailable_renders_vault_unreachable_state(self) -> None:
        html = _render_error(_RUNTIME_UNAVAILABLE_503)

        # Designed "Vault unreachable" state, not the generic JSON-dumping card.
        assert 'data-testid="workspace-vault-unreachable-state"' in html
        assert "Vault unreachable" in html
        assert 'data-error-kind="runtime-unavailable"' in html

        # Provenance line per the design handoff, behind a Details disclosure
        # (open-questions Q23 — provenance is opt-in, never the headline).
        assert "runtime_unavailable · /api/companion/orientation · 503" in html
        assert 'data-testid="workspace-error-details"' in html

        # Reassurance: durable vault truth is unaffected; companion is a client.
        assert "durable" in html.lower()
        assert "client" in html.lower()

        # The two designed affordances: Retry connection + Open system map.
        assert 'data-testid="workspace-entry-retry"' in html
        assert 'data-testid="workspace-entry-map-affordance"' in html

        # Must not dump the raw JSON contract body or fall through to the
        # generic JSON-dumping "API Error" branch.
        assert "API Error" not in html
        assert "trace-abc" not in html  # the body's trace_id value
        assert '"contract_version"' not in html  # the raw JSON body key
        assert 'data-testid="workspace-error-state"' not in html  # generic card

        # Setup form is suppressed: no first-contact vault-config affordances.
        # (Asserted against the form's real testids — the runtime cannot process
        # an open/init while unreachable, so the whole panel is a false
        # affordance; #2123 AC1, open-questions Q24.)
        assert 'data-testid="vault-settings-actions"' not in html
        assert 'data-testid="vault-open-form"' not in html
        assert 'data-testid="vault-init-form"' not in html
        assert "No vault selected" not in html


def _render_error_with_origin(error: str, page_origin_hostname: str) -> str:
    """Render the error-page surface with an explicit page-origin hostname.

    ``page_origin_hostname`` is the host the browser used to load the page
    (the request ``Host`` header on the server). It is a client/page fact, not
    a runtime-state signal — the server still declares the runtime class.
    """
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        fields=None,
        error=error,
        page_origin_hostname=page_origin_hostname,
    )


class TestRemoteAccessDisambiguation:
    """#2124 — distinguish a wrong-device 503 from a genuinely-down runtime."""

    def test_remote_origin_renders_wrong_device_state(self) -> None:
        # Page served over LAN/Tailscale; the browser's API origin is the
        # API's localhost bind, unreachable from the remote device.
        html = _render_error_with_origin(_RUNTIME_UNAVAILABLE_503, "100.113.104.116")

        # Distinct "different device / API not exposed" state, not the plain
        # "Vault unreachable" card.
        assert 'data-testid="workspace-wrong-device-state"' in html
        assert 'data-testid="workspace-vault-unreachable-state"' not in html
        assert "different device" in html.lower()

        # Remote-access guidance + a local-only continuation affordance.
        assert 'data-testid="workspace-wrong-device-local-continuation"' in html

        # Like #2123: no raw JSON dump, no generic API Error, no setup form.
        assert "API Error" not in html
        assert "trace-abc" not in html
        assert 'data-testid="vault-open-form"' not in html
        assert "No vault selected" not in html

    def test_localhost_origin_renders_vault_unreachable_state(self) -> None:
        # Same 503 from a localhost page origin → unchanged #2123 state.
        for hostname in ("localhost", "127.0.0.1"):
            html = _render_error_with_origin(_RUNTIME_UNAVAILABLE_503, hostname)
            assert 'data-testid="workspace-vault-unreachable-state"' in html
            assert 'data-testid="workspace-wrong-device-state"' not in html
            assert "Vault unreachable" in html

    def test_default_origin_keeps_vault_unreachable_state(self) -> None:
        # No page-origin signal (default) must not regress #2123: the local
        # "Vault unreachable" state remains the safe default.
        html = _render_error(_RUNTIME_UNAVAILABLE_503)
        assert 'data-testid="workspace-vault-unreachable-state"' in html
        assert 'data-testid="workspace-wrong-device-state"' not in html


_FORM_MARKERS = (
    'data-testid="vault-settings-actions"',
    'data-testid="vault-open-form"',
    'data-testid="vault-init-form"',
    "No vault selected",
    "Open existing vault",
)


class TestVaultSetupFormSuppression:
    """The vault-setup form is suppressed whenever the runtime is unreachable.

    Regression guard for the gap behind #2123 AC1 / #2124: the error *banner*
    was restyled, but the vault-setup form is rendered by a separate layer
    (``vault_settings_panel_markup`` in ``render_index_html``) that was not
    gated on the unreachable state, so the form kept rendering on the live page.
    These assert the full page output, not the banner function in isolation.
    """

    def test_form_suppressed_on_http_503_local(self) -> None:
        html = _render_error(_RUNTIME_UNAVAILABLE_503)
        for marker in _FORM_MARKERS:
            assert marker not in html, marker
        # The panel's wiring script is suppressed too (no orphan handlers).
        assert "vault-settings-panel" not in html or 'data-testid="vault-open-form"' not in html

    def test_form_suppressed_on_remote_wrong_device(self) -> None:
        html = _render_error_with_origin(_RUNTIME_UNAVAILABLE_503, "100.113.104.116")
        for marker in _FORM_MARKERS:
            assert marker not in html, marker

    def test_form_suppressed_on_transport_connection_refused(self) -> None:
        # The transport-level failure shape from the screenshot (Errno 61) must
        # suppress the form just like the 503 contract error.
        html = _render_error("[Errno 61] Connection refused")
        for marker in _FORM_MARKERS:
            assert marker not in html, marker

    def test_form_present_for_structured_non_runtime_error_with_transport_word(self) -> None:
        # Regression (Codex P2 on #2135): a structured note_not_found error for a
        # path containing a transport word ("Network/…") must NOT be misread as
        # runtime-unreachable. The runtime is up, so the vault-setup form stays.
        note_not_found = (
            'HTTP 404: {"detail": {"error": "note_not_found", '
            '"note_path": "Network/Runbook.md", "message": "No note exists"}}'
        )
        html = _render_error(note_not_found)
        assert 'data-testid="vault-settings-actions"' in html
        assert 'data-testid="vault-open-form"' in html

    def test_form_present_when_runtime_healthy_no_vault(self) -> None:
        # The legitimate first-contact case: runtime up, no vault bound yet.
        # The setup form is the whole point here and MUST render.
        html = render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="",
            fields=None,
            error="",
        )
        assert 'data-testid="vault-settings-actions"' in html
        assert 'data-testid="vault-open-form"' in html
        assert "No vault selected" in html
