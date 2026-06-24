"""No-vault picker rendering on the primary Companion surfaces (#2309).

When the runtime reports no selected vault it returns the 200
``vault_selection_required`` picker payload on the orientation and workspace
boundaries (Option-2 decision, 2026-06-20). The page server must render the
vault picker — never a blank ``shell_active`` note (note-load path) and never a
fabricated ``cold_start`` orientation (home path). Server declares; UI renders.
"""
from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError

from tests.companion_ui._visible_text import visible_text as _visible_text

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


def test_vault_picker_is_design_system_only() -> None:
    """The no-vault front door renders one DS-styled picker surface (#2485 D1).

    After #2448 added the styled "No vault selected" hero, the original
    unstyled default-browser picker still rendered beneath it: a second
    "No vault selected" heading, ``/path/to/vault`` placeholder inputs, a system
    role ``<select>``, "unknown / unknown" identity rows, and an "Open settings
    folder" button. This pins the finished D1 state:

    - exactly one "No vault selected" heading is *visible*;
    - no raw ``/path/to/vault`` placeholder and no literal "unknown" leak to the
      human; and
    - the picker carries the DS panel chrome (its scoped tokenised stylesheet),
      not default-browser form chrome.

    Assertions scan *visible text* (script/style contents stripped) so the test
    cannot stay green on the broken double-render that ships today."""
    payload = {
        "state": "vault_selection_required",
        "reason": "no_vault_bound",
        "message": "No vault is selected. Open a vault to continue.",
        "configured_vault_root": "/Users/me/Vaults/Niflheim",
        "requested_note_path": "",
        "context": {"status": "none"},
        # A label-less recent that previously rendered "unknown / unknown".
        "recent_vaults": [{"vault_name": None, "path": None}],
        "actions": [],
    }
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        vault_selection_required=payload,
    )
    visible = _visible_text(html)

    # The literal front-door picker is the styled hero plus the inline
    # vault-settings panel folded beneath it. Scope the visible-text assertions
    # to that surface (not the whole page — the hidden settings/operator drawers
    # are separate overlays out of D1's scope).
    # The hero and the inline vault-settings panel are separate <body> siblings;
    # other overlays (hidden settings/operator drawers) sit between them in
    # source order. Extract each balanced <section> on its own and concatenate,
    # so the scan covers only the picker surface — not the unrelated drawers.
    def _balanced_section(text: str, open_marker: str, *, start: int = 0) -> str:
        open_idx = text.index(open_marker, start)
        depth = 0
        i = open_idx
        token = re.compile(r"<section\b|</section>", re.I)
        while True:
            m = token.search(text, i)
            assert m is not None, "unbalanced <section> in picker markup"
            if m.group(0).lower().startswith("<section"):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return text[open_idx : m.end()]
            i = m.end()

    hero_html = _balanced_section(html, '<section class="vault-selection-required"')
    panel_html = _balanced_section(html, '<section class="vault-settings-panel"')
    picker_html = hero_html + "\n" + panel_html
    picker_visible = _visible_text(picker_html)

    # Exactly one *visible* "No vault selected" heading — the styled hero owns
    # it; the picker form below must not repeat it.
    assert picker_visible.count("no vault selected") == 1, (
        "exactly one visible 'No vault selected' heading must render"
    )
    # And across the whole front door there is still only one (no third copy
    # elsewhere on the page).
    assert visible.count("no vault selected") == 1, (
        "exactly one visible 'No vault selected' heading on the whole page"
    )

    # No default-browser placeholder chrome and no raw enum placeholder leaks to
    # the human on the picker surface.
    assert "/path/to/vault" not in picker_html, (
        "no default-browser '/path/to/vault' placeholder may remain"
    )
    assert "unknown" not in picker_visible, (
        "no literal 'unknown' identity/recent token may show on the picker"
    )
    # The picker keeps a single settings-folder affordance, not a stray
    # duplicate.
    assert picker_visible.count("open settings folder") <= 1

    # The picker is a single DS-styled surface: the styled hero plus the
    # tokenised vault-settings panel chrome (DS fonts/colours/controls), not
    # default-browser form styling.
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-testid="vault-settings-panel"' in html
    # The DS panel stylesheet is present (scoped, tokenised controls), so the
    # picker inputs/buttons are not raw browser chrome.
    assert ".vault-settings-panel input" in html
    # The picker renders inline (not the hidden drawer) on the no-vault page.
    panel_start = html.index('<section class="vault-settings-panel"')
    panel_tag = html[panel_start : html.index(">", panel_start)]
    assert " hidden" not in panel_tag, "the no-vault picker panel renders visibly"
    assert 'data-display-mode="inline"' in panel_tag

    # Picker affordances are all preserved (presentation-only; behaviour is
    # #2312's domain): open-existing, create/init, recents, settings-folder.
    assert 'data-testid="vault-open-form"' in html
    assert 'data-testid="vault-init-form"' in html
    assert 'data-testid="vault-recent-vaults"' in html
    assert 'data-testid="vault-settings-folder-open"' in html


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


# ---------------------------------------------------------------------------
# D1 (#2448): the vault picker (E11) is styled to the design system — dark
# palette, design-system typography, a ranked primary open button, and styled
# (not default-browser) form controls. The picker is the literal front door;
# default-browser chrome reads as a different application.
# ---------------------------------------------------------------------------


def test_vault_picker_uses_ds() -> None:
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    assert 'data-testid="vault-selection-required"' in html

    # Isolate the picker section so the DS assertions target the front-door
    # surface (the configured-vault open affordance lives here).
    start = html.index('<section class="vault-selection-required"')
    end = html.index("</section>", start) + len("</section>")
    picker = html[start:end]

    # The configured-vault open button uses the design-system primary button
    # class — a ranked affordance, not bare default-browser chrome.
    open_button_idx = picker.index('data-testid="vault-selection-open-configured"')
    open_tag = picker[picker.rindex("<button", 0, open_button_idx):picker.index(">", open_button_idx) + 1]
    assert "btn" in open_tag and "btn--primary" in open_tag, (
        f"configured-vault open button must use the DS primary button class: {open_tag}"
    )

    # The picker carries design-system styling — its own scoped CSS hooks the
    # dark palette tokens, and no default-browser serif font leaks in.
    assert ".vault-selection-required" in html, (
        "the vault picker must carry design-system CSS, not default-browser chrome"
    )
    assert "font-family: serif" not in html
    assert "font-family:serif" not in html

    # The full open / initialize / recent-vault forms (rendered in the vault-
    # settings panel below the picker on the no-vault page) carry no raw text
    # input or select without a design-system style: every input/select in the
    # panel is styled via the .vault-settings-panel scoped rule onto the dark
    # palette (background var(--bg-raised), color var(--fg-1)). Assert that
    # scoped rule is present so no field renders with default white chrome.
    assert ".vault-settings-panel input" in html
    assert ".vault-settings-panel select" in html
    assert "var(--bg-raised" in html
    # No bare unstyled text input escapes onto the front door outside the
    # design-system-scoped containers: the picker section itself carries only
    # the hidden path field (typeless) — never a visible default text input.
    assert '<input type="text"' not in picker

    # Recent-vault rows use the standard list-item / button treatment, not raw
    # "unknown / unknown" default rows.
    assert 'data-testid="vault-recent-vaults"' in html


def test_no_white_inputs() -> None:
    """No input on the no-vault page renders with default white chrome.

    The picker fields and the vault-settings-panel inputs/selects/textareas
    are all brought onto the dark palette via the design-system scoped rules;
    no inline ``background: white`` / ``#fff`` leaks onto the dark theme.
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    # The vault-settings-panel scoped rule styles every input/select/textarea
    # onto the dark palette.
    assert ".vault-settings-panel input, .vault-settings-panel select, .vault-settings-panel textarea" in html
    # No input is left with default white chrome via an inline style.
    for white in ("background: white", "background:#fff", "background: #fff", "background:white"):
        assert white not in html, f"no input may carry inline {white!r} on the dark theme"
