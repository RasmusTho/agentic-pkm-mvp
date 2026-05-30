"""Workspace wikilink resolver seeding (#1345).

The renderer resolves vault-internal wikilinks correctly when given a seeded
``VaultLinkResolver``. These tests pin the workspace render seam: when the
fields carry an active-vault link index, ``[[Note]]`` renders as a resolved,
navigable ``vault-wikilink``; when the index is absent (current runtime,
pending the read-only link-index API), links stay diagnostic — identical to the
prior default. This is a structural seam test against the rendered HTML.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(*, body: str, vault_link_index: object | None = None) -> dict:
    base: dict = {
        "title": "Seed Check",
        "note_path": "Notes/seed-check.md",
        "artifact_id": "art-seed-001",
        "content_hash": "sha256-seed",
        "body": body,
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": False,
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
        "workspace_loaded_at": None,
    }
    if vault_link_index is not None:
        base["vault_link_index"] = vault_link_index
    return base


def _render(**kwargs) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/seed-check.md",
        fields=_fields(**kwargs),
    )


def test_seeded_link_index_resolves_internal_wikilink() -> None:
    html = _render(
        body="See [[Existing Note]] for details.",
        vault_link_index={"Existing Note": "Notes/Existing Note.md"},
    )

    assert 'class="vault-wikilink"' in html
    assert 'data-link-state="resolved"' in html
    assert "href=\"?note_path=Notes%2FExisting%20Note.md\"" in html


def test_missing_link_index_keeps_diagnostic() -> None:
    # No vault_link_index -> empty resolver -> diagnostic, unchanged behavior.
    html = _render(body="See [[Existing Note]] for details.")

    assert 'vault-wikilink-diagnostic' in html
    assert 'data-link-state="missing"' in html
    assert 'data-link-state="resolved"' not in html


def test_link_index_accepts_list_candidates() -> None:
    # Single-candidate list resolves; the coercion helper accepts list shape.
    html = _render(
        body="[[Existing Note]]",
        vault_link_index={"Existing Note": ["Notes/Existing Note.md"]},
    )

    assert 'data-link-state="resolved"' in html


def test_link_index_note_path_list_resolves_end_to_end() -> None:
    # #1431 AC3 — the read-only link-index API returns a note-path list; the
    # resolver expands each path into its lookup keys so a bare wikilink to an
    # existing note resolves and navigates end-to-end.
    html = _render(
        body="See [[Existing Note]] and [[Missing One]].",
        vault_link_index=["Notes/Existing Note.md", "Archive/Other.md"],
    )

    assert 'data-link-state="resolved"' in html
    assert "href=\"?note_path=Notes%2FExisting%20Note.md\"" in html
    # The unknown target still degrades to the diagnostic.
    assert 'data-link-state="missing"' in html
