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
    # ...offering the server-declared configured vault as the pinned first row of
    # the "Choose a vault" overlay (#2564) — selection is a row click...
    assert 'data-testid="vault-picker"' in html
    assert 'data-testid="vault-picker-row-select"' in html
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in html
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


def test_picker_without_configured_root_omits_pinned_configured_row() -> None:
    payload = dict(_PICKER_PAYLOAD)
    payload["configured_vault_root"] = None
    client = _PickerClient(payload)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    assert 'data-testid="vault-selection-required"' in html
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')
    # No configured root → no pinned "configured" row...
    assert 'data-pinned="true"' not in picker_html
    assert ">configured<" not in picker_html
    # ...but the overlay is never an empty labelled region: the always-present
    # "Browse for a vault folder…" row remains the escape hatch (#2564 AC4).
    assert 'data-testid="vault-picker-browse-row"' in picker_html


def _balanced_section(text: str, open_marker: str, *, start: int = 0) -> str:
    """Return the balanced ``<section>…</section>`` beginning at ``open_marker``."""
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


def test_vault_picker_is_one_overlay_no_foreign_form_chrome() -> None:
    """The no-vault front door is one "Choose a vault" overlay (#2564).

    The picker is rebuilt in the note Browse-vault overlay idiom: a single
    titled overlay, no separate vault-settings panel folded in, and none of the
    foreign form chrome the design review flagged — no typed "Path to an existing
    vault" / "Path for a new vault" field, no machine-Role select, no inline
    settings panel, no raw "unknown" identity token on the front door.

    Assertions scan *visible text* (script/style contents stripped) so the test
    cannot stay green on the old double-render."""
    payload = {
        "state": "vault_selection_required",
        "reason": "no_vault_bound",
        "message": "No vault is selected. Choose a vault to continue.",
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

    picker_html = _balanced_section(html, '<section class="vault-selection-required"')
    picker_visible = _visible_text(picker_html)

    # One titled overlay in the browse idiom — exactly one "Choose a vault"
    # title element (the message copy may also reference choosing a vault).
    assert picker_html.count('data-testid="vault-picker-title"') == 1
    title_text = picker_html.split('data-testid="vault-picker-title"', 1)[1].split("</summary>", 1)[0]
    assert "Choose a vault" in title_text

    # The foreign form chrome is GONE from the front door: no typed path fields,
    # no Role select, no separate vault-settings panel folded in.
    assert "Path to an existing vault" not in html
    assert "Path for a new vault" not in html
    assert "/path/to/vault" not in picker_html
    assert 'data-testid="vault-open-form"' not in html
    assert 'data-testid="vault-init-form"' not in html
    assert 'data-testid="vault-init-role"' not in html
    assert 'name="machineRole"' not in html
    # The inline vault-settings panel no longer renders on the front door (it is
    # mounted only as the hidden drawer behind a loaded note).
    assert 'data-testid="vault-settings-panel"' not in html

    # No literal "unknown" identity/recent token leaks to the human.
    assert "unknown" not in picker_visible

    # The picker carries design-system styling — its own scoped CSS, no
    # default-browser serif leak.
    assert ".vault-picker" in html
    assert "font-family: serif" not in html
    assert "font-family:serif" not in html

    # A single Open-settings-folder affordance, only inside the operator drawer.
    assert picker_html.count('data-testid="vault-settings-folder-open"') == 1


def test_vault_picker_renders_browse_overlay_idiom() -> None:
    """AC: the picker renders in the browse-overlay idiom (#2564 AC1).

    Titled overlay + focused filter + clickable rows + footer count — the same
    graphical language as the note Browse-vault overlay."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # Titled overlay (a <details> with a summary title, like the note browser).
    assert "<details" in picker_html and 'class="vault-picker"' in picker_html
    assert 'data-testid="vault-picker-title"' in picker_html
    # Focused filter input.
    assert 'data-testid="vault-picker-filter"' in picker_html
    # Clickable rows.
    assert 'data-testid="vault-picker-row"' in picker_html
    assert 'data-testid="vault-picker-row-select"' in picker_html
    # Footer count.
    assert 'data-testid="vault-picker-footer"' in picker_html


def test_configured_vault_is_pinned_first_row_badged_configured() -> None:
    """AC: configured vault is the pinned first row badged "configured" (#2564 AC2)."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # First row in the list is the configured vault, pinned and badged.
    list_html = picker_html.split('data-testid="vault-picker-list"', 1)[1]
    first_row = list_html.split('data-testid="vault-picker-row"', 2)[1]
    assert 'data-pinned="true"' in first_row
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in first_row
    assert ">configured<" in first_row
    # Selection is the row click (a button carrying the existing vault.select
    # action), never a typed path.
    assert 'data-intent="vault.select"' in first_row
    assert 'data-api-path="/api/companion/vault/select"' in first_row


def test_recents_render_as_clickable_rows() -> None:
    """AC: recents render as clickable rows — name + mono path + last-opened (#2564 AC2)."""
    payload = dict(_PICKER_PAYLOAD)
    payload["recent_vaults"] = [
        {
            "ref": "path:/Users/me/Vaults/Bifrost",
            "path": "/Users/me/Vaults/Bifrost",
            "vault_name": "Bifrost",
            "last_opened_at": "2026-06-25T10:00:00Z",
        }
    ]
    client = _PickerClient(payload)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    assert 'data-vault-path="/Users/me/Vaults/Bifrost"' in picker_html
    assert ">Bifrost<" in picker_html
    # A read-only mono path shown for confidence (never typed to select by).
    assert 'data-testid="vault-picker-row-path"' in picker_html
    assert "/Users/me/Vaults/Bifrost" in picker_html
    # A quiet last-opened time.
    assert 'data-testid="vault-picker-row-last-opened"' in picker_html
    assert "2026-06-25" in picker_html


def test_filter_input_is_filter_not_path_to_select() -> None:
    """AC: the search input filters the visible list, never selects by path (#2564 AC3)."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    filter_tag = picker_html[
        picker_html.index("<input", picker_html.index('data-testid="vault-picker-filter"') - 200):
        picker_html.index(">", picker_html.index('data-testid="vault-picker-filter"')) + 1
    ]
    # It is a search/filter input — not a name="path" field that submits a path.
    assert 'type="search"' in filter_tag
    assert 'name="path"' not in filter_tag
    # The controller filters rows by name/path text; it never POSTs the filter
    # value as a selection.
    assert "vault-picker-controller" in html
    assert "filter.value" in html
    # Selection only ever happens via a row click handler on vault-picker-row-select.
    assert "vault-picker-row-select" in html


def test_first_run_no_recents_shows_configured_and_browse_rows() -> None:
    """AC: first-run/no-recents = configured row + Browse row, never empty (#2564 AC4)."""
    payload = dict(_PICKER_PAYLOAD)
    payload["recent_vaults"] = []
    client = _PickerClient(payload)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # The configured vault is still the pinned recommended row.
    assert 'data-pinned="true"' in picker_html
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in picker_html
    # And the always-present Browse row is the rest of the surface.
    assert 'data-testid="vault-picker-browse-row"' in picker_html
    # No empty labelled "Open recent vault" region (the old empty-state defect).
    assert "Open recent vault" not in picker_html


def test_browse_row_is_present_inert_entry_for_2565() -> None:
    """AC: a "Browse for a vault folder…" entry row is present (folder mode = #2565)."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    assert 'data-testid="vault-picker-browse-row"' in picker_html
    assert "Browse for a vault folder" in picker_html
    # Present-but-inert: it routes to a "coming next" affordance, not a folder
    # browser (the folder browser itself is #2565 / Ask 3b).
    assert 'data-coming-in="2565"' in picker_html
    assert 'aria-disabled="true"' in picker_html


def test_operator_affordances_relocated_off_front_door() -> None:
    """AC: Reload / Open settings folder / Role are not on the front door (#2564 AC5).

    Reload and Open settings folder move behind the overlay's ⓘ Operator drawer;
    the machine-Role select leaves the front door entirely."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # Role is gone from the front door entirely.
    assert 'data-testid="vault-init-role"' not in html
    assert 'name="machineRole"' not in html
    assert "Role" not in _visible_text(picker_html)

    # Reload + Open settings folder live behind the operator drawer, not in the
    # primary surface.
    assert 'data-testid="vault-picker-operator"' in picker_html
    operator_html = picker_html.split('data-testid="vault-picker-operator"', 1)[1]
    assert 'data-testid="vault-reload"' in operator_html
    assert 'data-testid="vault-settings-folder-open"' in operator_html
    # They are inside the <details> operator drawer, behind its summary toggle.
    before_operator = picker_html.split('data-testid="vault-picker-operator"', 1)[0]
    assert 'data-testid="vault-reload"' not in before_operator
    assert 'data-testid="vault-settings-folder-open"' not in before_operator


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
# #2564: the "Choose a vault" overlay carries the design system's chrome (dark
# palette, DS typography, tokenised controls). The only input is the visible-
# list filter; selection is a row click. No default-browser form chrome.
# ---------------------------------------------------------------------------


def test_vault_picker_uses_ds() -> None:
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    assert 'data-testid="vault-selection-required"' in html

    picker = _balanced_section(html, '<section class="vault-selection-required"')

    # The picker carries design-system styling — its own scoped CSS hooks the
    # dark palette tokens, and no default-browser serif font leaks in.
    assert ".vault-picker" in html, (
        "the vault picker must carry design-system CSS, not default-browser chrome"
    )
    assert "font-family: serif" not in html
    assert "font-family:serif" not in html

    # The picker's controls (filter input, row buttons, operator actions) are on
    # the dark palette via DS tokens.
    assert ".vault-picker-filter" in html
    assert "var(--bg-raised" in html
    # The only <input> on the front door is the visible-list filter (type=search)
    # — never a default text input to type a path into.
    assert '<input type="text"' not in picker
    assert 'type="search"' in picker

    # Rows use the clean clickable-row treatment, not raw "unknown / unknown"
    # default rows.
    assert 'data-testid="vault-picker-row"' in picker


def test_no_white_inputs() -> None:
    """No control on the no-vault page renders with default white chrome (#2564).

    The picker filter and the row/operator controls are all brought onto the
    dark palette via the design-system scoped rules; no inline
    ``background: white`` / ``#fff`` leaks onto the dark theme.
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    # The picker scoped rules style the filter and buttons onto the dark palette.
    assert ".vault-picker-filter" in html
    assert ".vault-picker-row-button" in html
    # No input is left with default white chrome via an inline style.
    for white in ("background: white", "background:#fff", "background: #fff", "background:white"):
        assert white not in html, f"no control may carry inline {white!r} on the dark theme"
