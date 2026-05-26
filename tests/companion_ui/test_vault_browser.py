"""Vault Browser MLP v0 UI contract tests.

Pin the MLP v0 UI invariants from
``docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`` §6:

- opening the workspace renders a vault browser surface
- selecting a note loads it into the Companion workspace (read path only)
- the active vault identity is displayed
- explicit empty / error / identity-unavailable states render distinct test IDs

The browser is read-only; no UI test in this module exercises a mutation path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError, WorkspaceHttpClient


def _workspace_payload(note_path: str = "notes/current.md", title: str = "Current") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": title,
            "body": "# Body\n",
            "content_hash": "abc",
            "identity_source": "frontmatter.uuid",
            "identity_state": "resolved",
            "companion_of": None,
            "owns_identity": True,
        },
        "canvas": {"session_state": "idle", "session_persistence": "in_memory"},
        "panel": {"state": "idle", "proposal_count": 0},
        "guards": {
            "canvas_enabled": True,
            "writeguard_status": "ok",
            "workspace_update": {
                "available": True,
                "state": "available",
                "reason": "explicit_dev_config",
                "scope": "active_note_body",
                "governance_actions_enabled": False,
                "config_mode": "explicit",
            },
        },
        "runtime": {
            "environment_label": "dev",
            "api_base_url_label": "local-dev",
            "trace_id": "trace-vault-browser",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload(
    *,
    notes: list[dict[str, str]] | None = None,
    query: str = "",
    total_notes: int = 1,
    filtered_notes: int = 1,
    identity_available: bool = True,
) -> dict[str, Any]:
    return {
        "notes": notes
        or [
            {
                "note_path": "notes/Companion UI UAT.md",
                "title": "Companion UI UAT",
                "zone": "notes",
            }
        ],
        "query": query,
        "total_notes": total_notes,
        "filtered_notes": filtered_notes,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": identity_available,
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(
    *,
    workspace_payload: dict[str, Any] | None = None,
    browser_payload: dict[str, Any] | None = None,
    browser_error: Exception | None = None,
    note_path: str = "notes/current.md",
) -> RealNoteWorkspaceDevPage:
    workspace = _mock_get_response(workspace_payload or _workspace_payload(note_path=note_path))
    browser = _mock_get_response(browser_payload or _vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            if browser_error is not None:
                raise browser_error
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path=note_path))
    return page


def test_workspace_can_open_vault_browser() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-vault-browser"' in html
    assert 'data-testid="workspace-vault-browser-toggle"' in html
    assert 'data-testid="workspace-vault-browser-list"' in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html


def test_selecting_note_loads_workspace_note() -> None:
    page = _load_page(
        workspace_payload=_workspace_payload(note_path="notes/Companion UI UAT.md", title="Companion UI UAT"),
        note_path="notes/Companion UI UAT.md",
    )
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/Companion UI UAT.md",
        fields=fields,
    )
    assert fields["note_path"] == "notes/Companion UI UAT.md"
    assert "Companion UI UAT" in html
    assert "/?note_path=notes/Companion%20UI%20UAT.md" in html


def test_vault_browser_renders_active_vault_identity() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-vault-browser-active-identity"' in html
    assert "Niflheim/dev" in html


def test_vault_browser_distinguishes_empty_error_and_identity_states() -> None:
    empty_page = _load_page(
        browser_payload=_vault_browser_payload(notes=[], total_notes=2, filtered_notes=0),
    )
    empty_fields = empty_page.render_fields()
    assert empty_fields is not None
    empty_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=empty_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-empty"' in empty_html

    error_page = _load_page(browser_error=WorkspaceClientNetworkError("connection refused"))
    error_fields = error_page.render_fields()
    assert error_fields is not None
    error_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=error_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-error"' in error_html

    identity_page = _load_page(
        browser_payload=_vault_browser_payload(identity_available=False),
    )
    identity_fields = identity_page.render_fields()
    assert identity_fields is not None
    identity_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=identity_fields,
    )
    assert 'data-testid="workspace-vault-browser-state-identity-unavailable"' in identity_html


# ---- AC4: metadata badges rendered per row ----


def _note_with_metadata(
    *,
    note_path: str = "notes/rich.md",
    title: str = "Rich Note",
    kind: str | None = "human_note",
    zone: str = "active",
    review_state: str | None = "needs_review",
    trust: str | None = "assert",
    frontmatter_valid: bool = True,
    missing_required_fields: list[str] | None = None,
) -> dict:
    return {
        "note_path": note_path,
        "title": title,
        "kind": kind,
        "zone": zone,
        "review_state": review_state,
        "trust": trust,
        "origin": "vault",
        "source_ref": None,
        "created": None,
        "updated": None,
        "uuid": "abc-123",
        "frontmatter_valid": frontmatter_valid,
        "missing_required_fields": missing_required_fields or [],
    }


def test_vault_browser_renders_metadata_badges_when_present() -> None:
    """AC4: Client renders metadata badges for kind, zone, review_state, trust when present."""
    note = _note_with_metadata(
        kind="human_note",
        zone="active",
        review_state="needs_review",
        trust="assert",
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[note], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    assert 'data-testid="workspace-vault-browser-note-kind"' in html
    assert 'data-testid="workspace-vault-browser-note-review-state"' in html
    assert 'data-testid="workspace-vault-browser-note-trust"' in html


def test_vault_browser_omits_badge_when_metadata_absent() -> None:
    """AC4 corollary: absent optional metadata → badge not rendered (not empty string)."""
    note = _note_with_metadata(kind=None, review_state=None, trust=None)
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[note], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    assert 'data-testid="workspace-vault-browser-note-kind"' not in html
    assert 'data-testid="workspace-vault-browser-note-review-state"' not in html
    assert 'data-testid="workspace-vault-browser-note-trust"' not in html


# ---- AC5: missing/invalid metadata rendered as health state ----


def test_vault_browser_renders_health_badge_for_invalid_frontmatter() -> None:
    """AC5: Client renders missing/invalid metadata as visible health state."""
    note = _note_with_metadata(
        frontmatter_valid=False,
        missing_required_fields=["uuid"],
        kind=None,
        review_state=None,
        trust=None,
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[note], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    assert 'data-testid="workspace-vault-browser-note-health"' in html
    assert "invalid" in html or "missing" in html


def test_valid_frontmatter_renders_no_health_warning() -> None:
    """AC5 corollary: valid frontmatter → health warning absent."""
    note = _note_with_metadata(frontmatter_valid=True, missing_required_fields=[])
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[note], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    assert 'data-testid="workspace-vault-browser-note-health"' not in html


# ---- #1254: filter chip rendering ----


def _vault_browser_payload_with_filters(
    *,
    notes: list[dict] | None = None,
    active_filters: dict | None = None,
) -> dict:
    base = _vault_browser_payload(
        notes=notes
        or [
            _note_with_metadata(kind="human_note", zone="active", review_state="needs_review"),
            _note_with_metadata(
                note_path="notes/companion.md",
                kind="companion_note",
                zone="semi_active",
                review_state="reviewed",
                trust="suggest",
            ),
        ],
        total_notes=2,
        filtered_notes=2,
    )
    base["active_filters"] = active_filters or {}
    return base


def test_vault_browser_renders_filter_chips_for_metadata_dimensions() -> None:
    """#1254 AC5: filter chips are rendered for metadata dimensions in the vault browser."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    assert 'data-testid="vault-browser-filter-chip"' in html


def test_vault_browser_active_filter_chip_has_data_active_true() -> None:
    """#1254: active filter chip has data-active=true."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(
            active_filters={"kind": ["human_note"]},
        ),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    # Active chip for human_note kind should have data-active="true"
    assert 'data-active="true"' in html
    assert 'data-key="kind"' in html
    assert 'data-value="human_note"' in html


def test_vault_browser_inactive_filter_chip_has_data_active_false() -> None:
    """#1254: non-active filter chips have data-active=false."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(
            active_filters={},
        ),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )

    # Without active filters, all chips should have data-active="false"
    assert 'data-active="false"' in html


# ---- #1280: wire filter chip clicks to server-side reload ----


def test_filter_chips_carry_onclick_wiring() -> None:
    """#1280 AC1+AC2: Every filter chip carries onclick=vbToggleFilter(this) for toggle interaction."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'onclick="vbToggleFilter(this)"' in html


def test_filter_chips_carry_cursor_pointer_style() -> None:
    """#1280 AC1: Filter chips are visually afforded as clickable."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'style="cursor:pointer"' in html


def test_multi_value_active_chips_show_deselect_affordance() -> None:
    """#1280 AC3: When 2+ values active for a dimension, active chips show a deselect affordance."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(
            active_filters={"kind": ["human_note", "companion_note"]},
        ),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="filter-chip-remove"' in html


def test_single_active_chip_no_deselect_affordance() -> None:
    """#1280 AC3 boundary: single active value → no deselect affordance (no ambiguity)."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(
            active_filters={"kind": ["human_note"]},
        ),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="filter-chip-remove"' not in html


def test_handle_get_passes_filter_params_to_vault_browser_api() -> None:
    """#1280 AC4: URL filter params are forwarded to the vault browser API call."""
    from unittest.mock import MagicMock, patch

    from companion_ui.workspace.serve_dev_page import handle_get
    from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient

    captured: dict = {}

    workspace_mock = MagicMock()
    workspace_mock.status_code = 200
    workspace_mock.json.return_value = _workspace_payload()

    browser_mock = MagicMock()
    browser_mock.status_code = 200
    browser_mock.json.return_value = _vault_browser_payload_with_filters(
        active_filters={"kind": ["human_note"]},
    )

    def _side_effect(url: str, *, params: dict, timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace_mock
        if url.endswith("/api/companion/vault-browser"):
            captured["params"] = dict(params)
            return browser_mock
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        handle_get(
            query_string="note_path=notes/current.md&kind=human_note",
            client=client,
            api_base_url="http://127.0.0.1:18001",
        )

    assert "kind" in captured.get("params", {}), (
        "Filter param 'kind' must be forwarded to vault-browser API"
    )
    assert captured["params"]["kind"] == ["human_note"], (
        f"Filter value must be ['human_note']; got: {captured['params']['kind']!r}"
    )


def test_vbtoggle_script_block_present_in_page() -> None:
    """#1280: vbToggleFilter JS function is embedded in page output."""
    page = _load_page(
        browser_payload=_vault_browser_payload_with_filters(),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert "vbToggleFilter" in html
    assert "url.searchParams" in html


# ---- #1283: visually distinguish companion vs human notes ----


def test_companion_note_row_has_data_companion_true() -> None:
    """#1283 AC1: Companion note row carries data-companion="true"."""
    companion = _note_with_metadata(
        note_path="notes/companion.md",
        title="Companion",
        kind="companion_note",
        zone="semi_active",
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[companion], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-companion="true"' in html, (
        "companion_note row must carry data-companion=\"true\""
    )


def test_companion_note_row_has_data_kind_companion_note() -> None:
    """#1283 AC1: Companion note row carries data-kind="companion_note"."""
    companion = _note_with_metadata(
        note_path="notes/companion.md",
        kind="companion_note",
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[companion], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-kind="companion_note"' in html, (
        "companion_note row must carry data-kind=\"companion_note\""
    )


def test_companion_note_row_carries_companion_css_class() -> None:
    """#1283 AC1: Companion note row carries vault-browser-row--companion CSS class."""
    companion = _note_with_metadata(
        note_path="notes/companion.md",
        kind="companion_note",
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[companion], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert "vault-browser-row--companion" in html, (
        "companion_note row must carry vault-browser-row--companion CSS class"
    )


def test_human_note_row_has_no_companion_treatment() -> None:
    """#1283 AC1 boundary: human_note row does NOT carry companion treatment."""
    human = _note_with_metadata(
        note_path="notes/human.md",
        kind="human_note",
    )
    page = _load_page(
        browser_payload=_vault_browser_payload(notes=[human], total_notes=1, filtered_notes=1),
    )
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-companion="true"' not in html
    assert "vault-browser-row--companion" not in html


def test_vault_provenance_attribute_is_escaped() -> None:
    payload = _workspace_payload()
    payload["runtime"]["vault_identity"]["provenance"] = 'env" onmouseover="alert(1)'
    page = _load_page(workspace_payload=payload)
    fields = page.render_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-vault-provenance="env&quot; onmouseover=&quot;alert(1)"' in html
    assert 'data-vault-provenance="env" onmouseover=' not in html
