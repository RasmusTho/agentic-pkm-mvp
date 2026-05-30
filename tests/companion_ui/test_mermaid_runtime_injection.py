"""Mermaid client-runtime injection on the workspace dev page (#1344).

Static/structural coverage for the placeholder + lazy runtime contract. The
real-browser behaviour (valid source -> SVG; broken source -> failed-embed) is
covered by the opt-in Playwright suite in test_mermaid_browser.py; here we pin
the server-emitted shape and the lazy-load guard so they cannot silently
regress.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_index_html


def _fields(*, body: str) -> dict:
    return {
        "title": "Mermaid Page",
        "note_path": "Notes/mermaid-page.md",
        "artifact_id": "art-mmd-001",
        "content_hash": "sha256-mmd",
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


def _render(body: str) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/mermaid-page.md",
        fields=_fields(body=body),
    )


_VALID = "text\n\n```mermaid\ngraph TD\n    A --> B\n```\n"


def test_page_emits_placeholder_and_runtime_for_mermaid_note() -> None:
    html = _render(_VALID)

    # AC1 — stable placeholder selector emitted in the body.
    assert '<pre class="vault-mermaid"' in html
    assert '<code class="language-mermaid">' in html
    # Client runtime present, importing Mermaid from the pinned ESM source.
    assert "https://esm.sh/mermaid@10" in html
    assert "vault-mermaid-svg-" in html


def test_runtime_is_guarded_so_bundle_loads_only_when_needed() -> None:
    # AC4 — the import is gated on placeholder presence: no placeholder => the
    # async runtime returns before importing the Mermaid bundle.
    html = _render(_VALID)
    guard_idx = html.index("querySelectorAll('.note-body pre.vault-mermaid')")
    return_idx = html.index("if (!blocks.length) { return; }")
    import_idx = html.index("await import('https://esm.sh/mermaid@10")
    # The presence check and early return precede the dynamic import.
    assert guard_idx < return_idx < import_idx


def test_runtime_degrade_path_uses_failed_embed_kind_mermaid() -> None:
    # AC3 — the client failure path rewrites to the #1340 failed-embed shape,
    # matching the server partial (data-testid="failed-embed" data-kind="mermaid").
    html = _render(_VALID)
    assert "'data-testid', 'failed-embed'" in html
    assert "'data-kind', 'mermaid'" in html
    assert "securityLevel: 'strict'" in html


def test_no_mermaid_note_still_includes_inert_guarded_runtime() -> None:
    # A note without a fence emits no placeholder; the guarded runtime is inert
    # (it returns before importing the bundle).
    html = _render("Just text, no diagrams.\n")
    assert '<pre class="vault-mermaid"' not in html
    assert "if (!blocks.length) { return; }" in html
