"""Vault Browser UI-only multi-note selection substrate tests (#1471)."""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html


def _render_html() -> str:
    fields: dict[str, Any] = {
        "note_path": "notes/current.md",
        "title": "Current",
        "body": "# Body\n",
        "artifact_kind": "human_note",
        "content_hash": "abc",
        "vault_browser_notes": [
            {
                "note_path": "notes/current.md",
                "title": "Current",
                "zone": "notes",
            },
            {
                "note_path": "notes/related.md",
                "title": "Related",
                "zone": "notes",
            },
        ],
        "vault_browser_total_notes": 2,
        "vault_browser_filtered_notes": 2,
        "vault_browser_read_only": True,
        "vault_browser_identity_available": True,
        "vault_browser_vault_name": "Niflheim",
        "vault_browser_vault_channel": "dev",
        "vault_browser_vault_provenance": "env",
    }
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )


def _selection_script(html: str) -> str:
    start = html.find("function vaultBrowserSelectionControls")
    end = html.find("function vbToggleFilter")
    assert start != -1, "selection toggle script must be embedded"
    assert end != -1, "filter toggle script should remain after selection script"
    return html[start:end]


def _selection_toggle_tags(html: str) -> list[str]:
    return re.findall(
        r"<input[^>]+data-testid=\"workspace-vault-browser-selection-toggle\"[^>]*>",
        html,
    )


def _row_tags(html: str) -> list[str]:
    return re.findall(
        r"<li[^>]+data-testid=\"workspace-vault-browser-note-row\"[^>]*>",
        html,
    )


def test_vault_browser_rows_toggle_ui_only_selection_state() -> None:
    html = _render_html()
    toggle_tags = _selection_toggle_tags(html)
    row_tags = _row_tags(html)

    assert toggle_tags
    assert len(row_tags) == 2
    assert all('data-selected="false"' in tag for tag in row_tags)
    assert all('data-mode="ui_only"' in tag for tag in toggle_tags)
    assert all('onclick="vaultBrowserToggleSelection(event, this)"' in tag for tag in toggle_tags)

    script = _selection_script(html)
    assert "row.dataset.selected = selected ? 'true' : 'false'" in script
    assert "control.dataset.selected = selected ? 'true' : 'false'" in script


def test_multi_selection_does_not_trigger_note_navigation() -> None:
    html = _render_html()
    toggle_tags = _selection_toggle_tags(html)
    script = _selection_script(html)

    assert toggle_tags
    assert all("href=" not in tag for tag in toggle_tags)
    assert all("window.location" not in tag for tag in toggle_tags)
    assert "event.stopPropagation()" in script
    assert "window.location" not in script


def test_multi_selection_summary_renders_selected_count() -> None:
    html = _render_html()

    assert 'data-testid="workspace-vault-browser-selection-summary"' in html
    assert 'data-mode="ui_only"' in html
    assert 'data-selected-count="0"' in html
    assert "0 selected" in html

    script = _selection_script(html)
    assert "vaultBrowserUpdateSelectionSummary" in script
    assert "summary.dataset.selectedCount = String(selected.length)" in script


def test_multi_selection_is_ui_only_no_write_controls() -> None:
    html = _render_html()
    toggle_tags = _selection_toggle_tags(html)
    script = _selection_script(html)

    assert toggle_tags
    assert all("<form" not in tag for tag in toggle_tags)
    assert all('data-mode="ui_only"' in tag for tag in toggle_tags)
    assert "fetch(" not in script
    assert "method: 'POST'" not in script
    assert 'data-api-method="POST"' not in script
    assert "governance_write" not in script
