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

from companion_ui.workspace.serve_dev_page import (
    _decorate_uninitialized_write_refusal,
    handle_get,
    render_index_html,
)
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


def test_unselected_vault_with_configured_root_renders_picker_not_cold_start() -> None:
    """#2653: VAULT_ROOT configured but nothing *selected* → picker, not cold_start.

    The #2653 repro is a selected-but-``uninitialized`` vault
    (``status != "selected"`` / ``active_vault_id is null``): orientation USED to
    resolve the configured ``VAULT_ROOT`` and the page rendered
    ``data-entry-state="cold_start"``. With the orientation selection gate in
    place the runtime returns the ``vault_selection_required`` picker (here with
    ``reason="uninitialized"``), and the entry surface must render the
    "Choose a vault" picker (``data-testid="vault-picker-title"``) — never the
    ``cold_start`` door for an unselected vault.
    """
    payload = dict(_PICKER_PAYLOAD)
    payload["reason"] = "uninitialized"
    payload["context"] = {"status": "uninitialized"}
    client = _PickerClient(payload)
    html = handle_get(
        query_string="",
        client=client,
        api_base_url="http://127.0.0.1:18001",
    )
    # The "Choose a vault" picker is rendered...
    assert 'data-testid="vault-picker-title"' in html
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-entry-state="no_vault"' in html
    # ...and the page is NOT a fabricated cold_start orientation.
    assert 'data-entry-state="cold_start"' not in html
    assert 'data-region="cold-start-threshold"' not in html
    assert 'data-region="reentry-card"' not in html
    # The orientation boundary was queried (the entry path, not a note load).
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
        # OBSSTAB-08 (#2615): entry-state path also fetches live health for the
        # ambient operator-health glyph.
        ("/api/health", {}),
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


def test_fresh_install_browse_is_the_working_bind_path_2565() -> None:
    """P1 regression (#2565): a fresh install can bind a vault — visually.

    #2564 made the picker clean but left Browse inert, so a fresh install
    (``no_vault_bound`` + ``configured_vault_root: null`` + empty recents) had NO
    way to bind a vault: no configured row, no recents, inert Browse. This slice
    makes Browse a working visual folder picker, so the fresh-install dead-end is
    gone — Browse is the clear, functional bind path and it is never a typed
    path.
    """
    payload = dict(_PICKER_PAYLOAD)
    payload["configured_vault_root"] = None
    payload["recent_vaults"] = []
    client = _PickerClient(payload)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # No configured row and no recents — the classic fresh-install state.
    assert 'data-pinned="true"' not in picker_html
    # The footer reports zero selectable vaults (configured + recents).
    assert 'data-count="0"' in picker_html

    # The Browse row is the working bind path, not an inert stub.
    assert 'data-testid="vault-picker-browse-row"' in picker_html
    assert 'data-coming-in="2565"' not in picker_html
    browse_btn = picker_html.split('data-testid="vault-picker-browse"', 1)[1][:200]
    assert 'data-affordance-status="available"' in browse_btn

    # Clicking it enters filesystem mode (the controller loads the browse
    # endpoint); the bind is fully visual — Open (vault.select) / Initialize
    # (vault.initialize), never a typed path.
    assert "function loadFolder" in html
    assert "setMode('filesystem')" in html
    assert 'data-intent="vault.select"' in html
    assert 'data-intent="vault.initialize"' in html
    # No typed-path-to-select field anywhere on this fresh-install surface.
    assert 'name="path"' not in picker_html


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


def test_browse_row_enters_working_filesystem_mode_2565() -> None:
    """AC (#2565): the Browse row is a WORKING entry into filesystem mode.

    The inert "coming next" stub is gone: clicking "Browse for a vault folder…"
    switches the same overlay to a folder browser (filesystem mode) backed by the
    read-only ``/api/companion/vault/browse`` endpoint. One graphical language,
    no typed path.
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    assert 'data-testid="vault-picker-browse-row"' in picker_html
    assert "Browse for a vault folder" in picker_html
    # The inert stub is removed — the row is now an available affordance.
    assert 'data-coming-in="2565"' not in picker_html
    assert 'data-testid="vault-picker-browse"' in picker_html
    browse_btn = picker_html.split('data-testid="vault-picker-browse"', 1)[1][:200]
    assert 'data-affordance-status="available"' in browse_btn
    assert "aria-disabled" not in browse_btn

    # The filesystem-mode region exists (hidden until Browse is clicked) with the
    # same browse idiom: a clickable breadcrumb + a folder list + a filter that
    # only narrows the current folder (never a path-to-select field).
    assert 'data-testid="vault-picker-fs-mode"' in picker_html
    assert 'data-testid="vault-picker-fs-breadcrumb"' in picker_html
    assert 'data-testid="vault-picker-fs-list"' in picker_html
    # The folder filter is a search filter (narrows the current folder), not a
    # path-to-select field.
    fs_filter_input = picker_html.split('vault-picker-fs-filter', 1)[0][-200:]
    assert 'type="search"' in fs_filter_input

    # The controller fetches the read-only browse endpoint and renders rows
    # client-side; vault detection / is_vault is server-declared.
    assert "/api/companion/vault/browse" in html
    assert "function loadFolder" in html
    # No typed-path field is introduced anywhere in the picker.
    assert 'name="path"' not in picker_html
    assert 'placeholder="Path to an existing vault"' not in picker_html


def test_filesystem_mode_renders_open_and_initialize_via_existing_authority() -> None:
    """AC (#2565): vault folders get Open (vault.select); plain folders Initialize.

    Both reuse the existing authority — no new endpoint, no new authority. The
    client renders an "Open" affordance bound to ``vault.select`` for vault rows
    and "Initialize a vault here" bound to ``vault.initialize`` (incl. the #2518
    409-confirm) for non-vault rows. Detection is server-declared (``is_vault``).
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")

    # The client-side row renderer wires the existing actions.
    assert 'data-intent="vault.select"' in html
    assert 'data-intent="vault.initialize"' in html
    assert 'data-testid="vault-picker-fs-open"' in html
    assert 'data-testid="vault-picker-fs-initialize"' in html
    assert "Initialize a vault here" in html
    # The 409-confirm round-trip is honored in the shared initialize dispatch.
    assert "vault_init_confirmation_required" in html
    # is_vault is read from the server payload, not classified client-side.
    assert "entry.is_vault" in html


def test_filesystem_mode_breadcrumb_navigation_is_click_only() -> None:
    """AC (#2565): breadcrumb segments + folder rows navigate by click, never type.

    The controller renders breadcrumb segments client-side from the server
    payload and navigates on a segment click (click to go up); folder rows
    navigate into a folder on click; a Back affordance returns to the recents
    view. No part of this requires typing a path.
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")

    # Breadcrumb is built from server segments and each segment is clickable.
    assert "function renderBreadcrumb" in html
    assert 'data-testid="vault-picker-fs-crumb"' in html
    # A breadcrumb-segment click navigates to that folder.
    assert "vault-picker-fs-crumb" in html and "loadFolder(crumb.getAttribute('data-fs-path')" in html
    # A folder-row click navigates into the folder.
    assert "loadFolder(enter.getAttribute('data-fs-path')" in html
    # Back returns to the recents view.
    assert 'data-testid="vault-picker-fs-back"' in html
    assert "setMode('recents')" in html


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


def _loaded_note_fields() -> dict[str, Any]:
    return {
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


def test_loaded_note_v_chip_opens_choose_a_vault_switch_overlay() -> None:
    """#2590: on a loaded note the "V" chip opens the reused Choose-a-vault
    overlay for vault *switching*, not the retired foreign-form drawer.

    The loaded-note vault surface is now in the same graphical idiom as the
    first-contact picker and note-browse: a hidden switch overlay revealed by
    the chip, with no typed path field and no machine-Role select on it. The
    retired ``vault-settings-panel`` drawer + its ``vault.settings.open`` toggle
    are gone from the loaded-note path.
    """
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Companion UI UAT.md",
        fields=_loaded_note_fields(),
    )

    assert 'data-entry-state="shell_active"' in html
    assert "Companion UI UAT" in html

    # The "V" chip retargets to the switch overlay (vault.switch.open), not the
    # retired settings-drawer toggle.
    assert 'data-testid="workspace-surface-icon-vault-settings"' in html
    assert 'data-intent="vault.switch.open"' in html
    assert 'data-intent="vault.settings.open"' not in html
    assert 'aria-controls="workspace-vault-switch-host"' in html

    # The retired foreign-form drawer mount + its toggle are gone.
    assert '<section class="vault-settings-panel"' not in html
    assert "window.companionVaultSettings" not in html
    assert 'data-testid="vault-settings-panel-close"' not in html

    # The switch overlay reuses the Choose-a-vault overlay, hosted hidden until
    # the chip reveals it (data-reason="switch", not a no_vault first-contact
    # picker).
    host_start = html.index('data-testid="vault-switch-host"')
    host_open = html.rindex("<div", 0, host_start)
    host_tag = html[host_open : html.index(">", host_start)]
    assert "hidden" in host_tag
    assert 'data-open="false"' in host_tag
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-reason="switch"' in html
    assert 'data-testid="vault-picker"' in html
    # The reused picker controller is emitted so the overlay is live.
    assert "vault-picker-controller" in html

    # No typed-path / Role chrome on the switch surface (one graphical language).
    assert 'data-testid="vault-open-path"' not in html
    assert 'data-testid="vault-init-path"' not in html
    assert 'data-testid="vault-init-role"' not in html


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


# ---------------------------------------------------------------------------
# #2564 Codex P2: a selected-but-uninitialized vault must get a working
# *initialize* affordance inside the "Choose a vault" overlay. When a write
# boundary refuses with reason="uninitialized"
# (_uninitialized_selection_required_response), re-clicking the pinned row only
# re-selects the same uninitialized vault — a dead end. The overlay must offer
# vault.initialize for the already-selected path. The general no_vault_bound
# first-contact picker must stay clean (no initialize / typed-path chrome).
# ---------------------------------------------------------------------------


def _uninitialized_payload() -> dict[str, Any]:
    return {
        "state": "vault_selection_required",
        "reason": "uninitialized",
        "message": (
            "The selected vault is not initialized yet. Initialize it to enable "
            "writes, or open a different vault to continue."
        ),
        "configured_vault_root": "/Users/me/Vaults/Niflheim",
        "requested_note_path": "",
        "context": {"status": "uninitialized", "active_vault_path": "/Users/me/Vaults/Niflheim"},
        "recent_vaults": [],
        "actions": [],
    }


def test_uninitialized_reason_renders_initialize_affordance() -> None:
    """reason="uninitialized" gets a working Initialize affordance (#2564 Codex P2).

    The already-selected uninitialized vault must present an explicit
    "Initialize this vault" action carrying the existing vault.initialize
    authority and the configured/selected path — not just a re-select that loops
    back to the same refusal.
    """
    client = _PickerClient(_uninitialized_payload())
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # The overlay declares the uninitialized state.
    assert 'data-reason="uninitialized"' in picker_html

    # An explicit Initialize affordance is rendered, carrying the existing
    # vault.initialize authority + the configured/selected path (no new authority).
    assert 'data-testid="vault-picker-initialize"' in picker_html
    init_block = picker_html.split('data-testid="vault-picker-initialize"', 1)[1]
    assert 'data-testid="vault-picker-initialize-submit"' in init_block
    assert 'data-intent="vault.initialize"' in init_block
    assert 'data-api-method="POST"' in init_block
    assert 'data-api-path="/api/companion/vault/initialize"' in init_block
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in init_block
    assert "Initialize this vault" in init_block

    # Honest copy that the vault isn't initialized yet.
    assert "isn’t initialized yet" in _visible_text(picker_html)

    # The picker controller handles the vault.initialize POST (not just select).
    assert "vault-picker-controller" in html
    assert 'vault-picker-initialize-submit' in html
    assert "vault/initialize" in html
    # It reuses the existing in-band confirm guard (#2518) for a populated folder.
    assert "vault_init_confirmation_required" in html
    assert "confirm: true" in html or "confirm = true" in html or "body.confirm" in html

    # No foreign form chrome leaks in even here: no typed path field, no Role select.
    assert 'data-testid="vault-init-role"' not in html
    assert 'name="machineRole"' not in html
    assert "Path for a new vault" not in html
    assert "Path to an existing vault" not in html


def test_uninitialized_write_refusal_renders_picker_with_initialize() -> None:
    """#2574: write refusals reach the existing Initialize-capable picker.

    Read endpoints can still render the normal workspace for a readable but
    uninitialized vault, so write handlers must not reload to re-resolve state.
    The page-server proxy decorates the server-declared refusal with a
    ``render_index_html`` picker page that the client can swap in directly.
    """
    payload = _uninitialized_payload()

    decorated = _decorate_uninitialized_write_refusal(
        payload,
        api_base_url="http://127.0.0.1:18001",
        note_path="Daily.md",
    )

    assert decorated["state"] == "vault_selection_required"
    assert decorated["reason"] == "uninitialized"
    picker_page = decorated["vault_selection_required_html"]
    assert 'data-testid="vault-selection-required"' in picker_page
    assert 'data-reason="uninitialized"' in picker_page
    assert 'data-testid="vault-picker-initialize-submit"' in picker_page
    assert 'data-intent="vault.initialize"' in picker_page
    assert 'data-api-path="/api/companion/vault/initialize"' in picker_page
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in picker_page
    assert 'data-region="document-anchor"' not in picker_page
    assert "window.renderVaultSelectionRequiredPicker" in picker_page
    assert "Object.prototype.hasOwnProperty.call(draft, 'text')" in picker_page
    assert "window.sessionStorage.setItem(refusedWriteDraftKey" in picker_page
    assert "window.restoreRefusedWriteDraft" in picker_page
    assert "vault-selection-required" in picker_page
    assert "window.sessionStorage.removeItem(refusedWriteDraftKey)" in picker_page
    assert "window['noteEditor']" in picker_page
    assert "kind: 'note_save'" in picker_page
    assert "text: ta.value" in picker_page
    assert "kind: 'body_edit'" in picker_page
    assert "text: newBody" in picker_page
    assert "kind: 'capture'" in picker_page
    assert "renderVaultSelectionRequired(ack, text)" in picker_page
    assert "data-refused-write-draft-restored" in picker_page


def test_vault_root_misconfigured_reason_renders_initialize_affordance() -> None:
    """reason="vault_root_misconfigured" (configured vault path missing) also earns
    a working create/initialize affordance (#2565 Codex P2). Re-selecting the
    missing configured row would otherwise loop back to the same refusal; the
    affordance reuses the existing vault.initialize authority on the configured
    path — still no typed-path / Role chrome."""
    payload = {
        "state": "vault_selection_required",
        "reason": "vault_root_misconfigured",
        "message": "The configured vault path is missing.",
        "configured_vault_root": "/Users/me/Vaults/Niflheim",
        "requested_note_path": "",
        "context": {"status": "missing", "active_vault_path": "/Users/me/Vaults/Niflheim"},
        "recent_vaults": [],
        "actions": [],
    }
    client = _PickerClient(payload)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    assert 'data-reason="vault_root_misconfigured"' in picker_html
    assert 'data-testid="vault-picker-initialize"' in picker_html
    init_block = picker_html.split('data-testid="vault-picker-initialize"', 1)[1]
    assert 'data-intent="vault.initialize"' in init_block
    assert 'data-api-path="/api/companion/vault/initialize"' in init_block
    assert 'data-vault-path="/Users/me/Vaults/Niflheim"' in init_block
    assert "Initialize this vault" in init_block
    # Missing-folder copy (distinct from the uninitialized case).
    assert "missing" in _visible_text(picker_html)
    # Still no foreign form chrome.
    assert 'name="machineRole"' not in html
    assert "Path to an existing vault" not in html


def test_no_vault_bound_picker_has_no_initialize_chrome() -> None:
    """The general first-contact picker stays clean (#2564) — guard against
    re-introducing the initialize / typed-path chrome on no_vault_bound.

    Only reason="uninitialized" earns the initialize affordance. The ordinary
    no_vault_bound picker (first contact) must not render it, nor any typed-path
    / Role chrome.
    """
    client = _PickerClient(_PICKER_PAYLOAD)
    assert _PICKER_PAYLOAD["reason"] == "no_vault_bound"
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    picker_html = _balanced_section(html, '<section class="vault-selection-required"')

    # No initialize affordance on the clean first-contact picker.
    assert 'data-testid="vault-picker-initialize"' not in picker_html
    assert 'data-testid="vault-picker-initialize-submit"' not in picker_html
    assert 'data-intent="vault.initialize"' not in picker_html
    assert "Initialize this vault" not in picker_html

    # And still none of the foreign form chrome.
    assert 'data-testid="vault-init-role"' not in html
    assert 'name="machineRole"' not in html
    assert "Path for a new vault" not in html
    assert "Path to an existing vault" not in html


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


def test_filesystem_mode_acts_on_current_folder() -> None:
    """#2565 Codex P2: filesystem mode must act on the CURRENT folder too — Open it
    when it is a vault, else Initialize a vault here — so a base narrowed to the
    exact vault/target dir (no parent row, maybe no matching child) is not a dead
    end. The DOM render is client-side; assert the picker controller carries the
    current-folder action logic + markup."""
    client = _PickerClient(_PICKER_PAYLOAD)
    html = handle_get(query_string="", client=client, api_base_url="http://127.0.0.1:18001")
    # The controller builds the current-folder row at runtime via setAttribute, so
    # assert on the JS value/literals rather than a rendered attribute.
    assert "vault-picker-fs-current" in html
    # Both branches are present: open the current vault, or initialize here.
    assert "Open this vault" in html
    assert "Initialize a vault here" in html
    # It reuses the existing select/initialize authority on the current path.
    assert "data.is_vault" in html and "data.path" in html
    # ...but never offers Initialize for the filesystem root '/' (the unconfigured
    # base default) — that would scaffold a vault into the container root (#2565
    # Codex P2). The current-folder row is suppressed at '/'.
    assert "data.path !== '/'" in html
