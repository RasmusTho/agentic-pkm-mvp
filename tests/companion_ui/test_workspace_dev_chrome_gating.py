"""Dev/operator chrome gated out of the default workspace (#1418).

Applies `ADAPTIVE_WORKSPACE_LAYOUT_HANDOFF.md` §§5.3, 11 and Vault Browser UI
Requirements R5/R7: the default human workspace must not show dev/operator
harness chrome (`SERVER-SIDE RUNTIME same-origin bridge`, `dev controls`, raw
`NOTE_PATH`/`LOAD`, `DEV / not production` banner). Those controls remain
available behind an explicit diagnostics route (`?diagnostics=1`). Elements stay
in the DOM (data-* compatibility) but are hidden by default via CSS keyed on
`body[data-diagnostics="false"]`.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import handle_get, render_index_html


def _page(*, diagnostics: bool = False) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        fields=None,
        diagnostics=diagnostics,
    )


def test_default_workspace_marks_body_non_diagnostics():
    html = _page()
    m = re.search(r"<body[^>]*>", html)
    assert m and 'data-diagnostics="false"' in m.group(0)


def test_diagnostics_mode_marks_body_diagnostics():
    html = _page(diagnostics=True)
    m = re.search(r"<body[^>]*>", html)
    assert m and 'data-diagnostics="true"' in m.group(0)


def test_default_workspace_hides_dev_chrome_via_css():
    html = _page()
    # CSS hides each dev/operator chrome element when not in diagnostics mode.
    for selector in (
        r"\.topbar",
        r"\.dev-controls-disclosure",
        r"\.workspace-dev-ribbon",
        r"\.dev-chip",
    ):
        rule = re.search(
            r'body\[data-diagnostics="false"\][^{]*' + selector + r"[^{]*\{([^}]*)\}",
            html,
        )
        assert rule, f"missing default-hide rule for {selector}"
        assert "display: none" in rule.group(1)


def test_dev_chrome_elements_remain_in_dom_for_diagnostics():
    # The controls are not deleted — diagnostics mode can reveal them.
    html = _page()
    assert 'class="topbar"' in html
    assert 'data-testid="workspace-dev-controls"' in html
    assert 'id="note_path"' in html  # raw NOTE_PATH input present but hidden
    assert "same-origin bridge" in html


def test_human_header_strip_is_not_gated_by_diagnostics():
    # The human-facing header (vault/runtime posture) must always be available.
    fields = _min_fields()
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/n.md",
        fields=fields,
        diagnostics=False,
    )
    assert 'data-testid="workspace-vault-chip"' in html
    # The header strip is not inside the diagnostics-gated chrome.
    header_idx = html.index('data-testid="workspace-vault-chip"')
    # The gated topbar appears before the workspace content; ensure the vault
    # chip is not wrapped by a diagnostics-hidden container class.
    assert 'class="workspace-diagnostics-chrome"' not in html[header_idx - 400:header_idx]


def test_handle_get_threads_diagnostics_query_param():
    html = handle_get(
        query_string="diagnostics=1",
        client=None,  # no note_path → no network
        api_base_url="http://127.0.0.1:18001",
    )
    m = re.search(r"<body[^>]*>", html)
    assert m and 'data-diagnostics="true"' in m.group(0)

    html2 = handle_get(
        query_string="",
        client=None,
        api_base_url="http://127.0.0.1:18001",
    )
    m2 = re.search(r"<body[^>]*>", html2)
    assert m2 and 'data-diagnostics="false"' in m2.group(0)


def _min_fields() -> dict:
    return {
        "title": "N",
        "note_path": "Notes/n.md",
        "artifact_id": "a",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "h",
        "body": "# N\n\nBody.",
        "panel_rail": "rail",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "t",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": False,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
