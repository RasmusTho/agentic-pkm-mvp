"""VaultAction display model tests for the vault browser inspector (#1256).

Pins the MLP v0 invariants for the VaultAction model:

- browser renders at least read-only/UI-only actions for selected artifacts
- UI visibly distinguishes read-only/UI-only from governance/proposal/write actions
- blocked/disabled actions render an explicit reason
- no write path is surfaced without guard/receipt semantics
- active-note body update flow remains separate from browser action model

VaultAction modes:
    read_only        — navigation / read (open_note, find_related_readonly)
    ui_only          — client-side only, no vault mutation (copy_path)
    bounded_system_write — bounded write, requires receipt
    governance_write — governed mutation, requires confirmation + receipt
    agent_proposal   — agent-proposed action, requires human confirmation
    blocked          — action class present but disallowed for this artifact

This is an architectural safety slice. Governance and write-class actions may be
disabled/blocked with an explanation rather than fully implemented.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


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
            "trace_id": "trace-vault-action",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _browser_note(
    *,
    note_path: str = "notes/current.md",
    title: str = "Current",
    uuid: str | None = "test-uuid-abc",
    kind: str | None = "human_note",
    zone: str = "notes",
    frontmatter_valid: bool = True,
    related_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    note = {
        "note_path": note_path,
        "title": title,
        "uuid": uuid,
        "kind": kind,
        "zone": zone,
        "review_state": "needs_review",
        "trust": "assert",
        "origin": "vault",
        "source_ref": None,
        "created": None,
        "updated": None,
        "frontmatter_valid": frontmatter_valid,
        "missing_required_fields": [],
    }
    if related_results is not None:
        note["related_results"] = related_results
    return note


def _vault_browser_payload(notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if notes is None:
        notes = [_browser_note()]
    return {
        "notes": notes,
        "query": "",
        "total_notes": len(notes),
        "filtered_notes": len(notes),
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
        "active_filters": {},
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_html(
    *,
    note_path: str = "notes/current.md",
    browser_payload: dict[str, Any] | None = None,
) -> str:
    workspace = _mock_get_response(_workspace_payload(note_path=note_path))
    browser = _mock_get_response(browser_payload or _vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path=note_path))

    fields = page.render_fields()
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=note_path,
        fields=fields,
    )


def _inspector_html(html: str) -> str:
    """Extract just the inspector section from the full page HTML."""
    start = html.find('data-testid="workspace-vault-browser-inspector"')
    if start == -1:
        return ""
    end = html.find("</section>", start)
    return html[start:end + len("</section>")] if end != -1 else html[start:]


# ---- AC2: browser renders read-only/UI-only actions for selected artifact ----


def test_inspector_renders_actions_strip() -> None:
    """AC2: Inspector includes an actions strip when a note is selected."""
    html = _inspector_html(_load_html())
    assert 'data-testid="workspace-vault-browser-inspector-actions"' in html


def test_read_only_open_note_action_rendered() -> None:
    """AC2: open_note action (read_only mode) is rendered in the inspector."""
    html = _inspector_html(_load_html())
    assert 'data-testid="vault-action-open-note"' in html
    assert 'data-mode="read_only"' in html


def test_ui_only_copy_path_action_rendered() -> None:
    """AC2: copy_path action (ui_only mode) is rendered in the inspector."""
    html = _inspector_html(_load_html())
    assert 'data-testid="vault-action-copy-path"' in html
    assert 'data-mode="ui_only"' in html


# ---- AC3: UI distinguishes action classes visually ----


def test_actions_carry_distinct_mode_attributes() -> None:
    """AC3: Each action carries a data-mode attribute naming its class."""
    html = _inspector_html(_load_html())
    assert 'data-mode="read_only"' in html
    assert 'data-mode="ui_only"' in html


def test_governance_write_action_carries_governance_mode() -> None:
    """AC3: queue_review (or equivalent governance action) carries data-mode=governance_write."""
    html = _inspector_html(_load_html())
    assert 'data-mode="governance_write"' in html


# ---- AC4: blocked/disabled actions render a reason ----


def test_blocked_governance_action_renders_reason() -> None:
    """AC4: Blocked or disabled governance actions render data-blocked-reason or data-disabled-reason."""
    html = _inspector_html(_load_html())
    assert 'data-blocked="true"' in html or 'data-disabled="true"' in html
    assert "data-blocked-reason" in html or "data-disabled-reason" in html


def test_blocked_action_affordance_is_unavailable() -> None:
    """AC4: Blocked/disabled governance actions are not affordance-active."""
    html = _inspector_html(_load_html())
    # governance_write actions must not be affordance-status=active
    import re
    gov_write_blocks = re.findall(
        r'data-mode="governance_write"[^>]*data-affordance-status="([^"]*)"',
        html,
    )
    # Each governance_write action's affordance must not be "active"
    for status in gov_write_blocks:
        assert status != "active", f"governance_write action must not be active, got: {status}"


# ---- AC5: no hidden write path, all writes guarded ----


def test_read_only_action_has_no_mutation_semantics() -> None:
    """AC5: open_note and copy_path actions carry no write/mutation indicators."""
    html = _inspector_html(_load_html())
    # Extract just the open_note action element
    start = html.find('data-testid="vault-action-open-note"')
    end = html.find(">", start) + 1  # just the opening tag
    tag_html = html[start:end]
    assert 'data-requires-receipt="true"' not in tag_html
    assert 'data-affordance-status="active"' not in tag_html


def test_governance_action_requires_receipt_or_confirmation() -> None:
    """AC5: Any governance_write action must declare requires-receipt or be blocked."""
    html = _inspector_html(_load_html())
    import re
    # governance_write actions must either have requires-receipt=true or be blocked
    gov_blocks = re.findall(
        r'(data-mode="governance_write"[^<]*)',
        html,
    )
    for block in gov_blocks:
        has_receipt = 'data-requires-receipt="true"' in block
        is_blocked = 'data-blocked="true"' in block or 'data-disabled="true"' in block
        assert has_receipt or is_blocked, (
            f"governance_write action must require receipt or be blocked: {block!r}"
        )


# ---- AC for #1281: open_note + copy_path wired with affordance=available ----


def _action_tag(html: str, testid: str) -> str:
    """Return the opening <div> tag for the given vault-action testid."""
    import re
    m = re.search(rf'(<div\b[^>]*data-testid="{re.escape(testid)}"[^>]*>)', html)
    assert m, f"vault-action testid={testid!r} not found in inspector HTML"
    return m.group(1)


def test_open_note_affordance_available() -> None:
    """#1281 AC: open_note renders data-affordance-status=available when note_path is set."""
    html = _inspector_html(_load_html(note_path="notes/current.md"))
    tag = _action_tag(html, "vault-action-open-note")
    assert 'data-affordance-status="available"' in tag, (
        f"open_note must carry affordance=available; got: {tag!r}"
    )


def test_open_note_carries_workspace_href() -> None:
    """#1281 AC: open_note carries a data-href pointing to the note in the workspace."""
    html = _inspector_html(_load_html(note_path="notes/current.md"))
    tag = _action_tag(html, "vault-action-open-note")
    assert "data-href=" in tag, f"open_note must carry data-href; got: {tag!r}"
    assert "note_path" in tag, f"data-href must include note_path parameter; got: {tag!r}"
    assert "notes/current.md" in tag or "notes%2Fcurrent.md" in tag, (
        f"data-href must contain the note path; got: {tag!r}"
    )


def test_copy_path_affordance_available() -> None:
    """#1281 AC: copy_path renders data-affordance-status=available when note_path is set."""
    html = _inspector_html(_load_html(note_path="notes/current.md"))
    tag = _action_tag(html, "vault-action-copy-path")
    assert 'data-affordance-status="available"' in tag, (
        f"copy_path must carry affordance=available; got: {tag!r}"
    )


def test_copy_path_carries_note_path_in_data_path() -> None:
    """#1281 AC: copy_path carries data-path with the vault-relative note path."""
    html = _inspector_html(_load_html(note_path="notes/current.md"))
    tag = _action_tag(html, "vault-action-copy-path")
    assert 'data-path="notes/current.md"' in tag, (
        f"copy_path must carry data-path with the note path; got: {tag!r}"
    )


# ---- AC for #1282: find_related wired to read-only artifact-scoped Find ----


def test_find_related_affordance_available_with_artifact_scope() -> None:
    """#1282 AC: find_related is available when the selected artifact has scope."""
    note = _browser_note(note_path="notes/current.md", uuid="uuid-1282")
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    tag = _action_tag(html, "vault-action-find-related")

    assert 'data-mode="read_only"' in tag
    assert 'data-affordance-status="available"' in tag
    assert 'data-api-method="GET"' in tag
    assert 'data-api-path="/api/companion/vault-related"' in tag
    assert 'data-note-path="notes/current.md"' in tag
    assert 'data-artifact-uuid="uuid-1282"' in tag
    assert 'onclick="vaultBrowserFindRelated(this)"' in tag
    assert "Find not connected" not in tag
    assert "data-disabled" not in tag


def test_find_related_results_region_is_read_only() -> None:
    """#1282 AC: inspector exposes a read-only result region for related artifacts."""
    html = _inspector_html(_load_html())

    assert 'data-testid="vault-browser-find-related-results"' in html
    assert 'data-mode="read_only"' in html
    assert 'data-state="idle"' in html


def test_find_related_result_rows_expose_ranking_signals() -> None:
    """#1282 AC: rendered related rows surface ranking/provenance signals."""
    note = _browser_note(
        related_results=[
            {
                "note_path": "notes/related.md",
                "title": "Related",
                "data_mode": "read_only",
                "ranking_score": 130,
                "ranking_signals": [
                    {
                        "signal": "shared_tag",
                        "value": "alpha",
                        "weight": 30,
                        "provenance": "frontmatter.tags",
                    },
                    {
                        "signal": "wikilink_backlink",
                        "value": "notes/current.md",
                        "weight": 100,
                        "provenance": "notes/related.md wikilinks to scope artifact",
                    },
                ],
            }
        ]
    )
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))

    assert 'data-testid="vault-browser-find-related-result"' in html
    assert 'data-mode="read_only"' in html
    assert 'data-ranking-score="130"' in html
    assert 'data-testid="vault-browser-find-related-signal"' in html
    assert 'data-signal="shared_tag"' in html
    assert 'data-weight="30"' in html
    assert 'data-provenance="frontmatter.tags"' in html


def test_find_related_js_calls_read_only_endpoint() -> None:
    """#1282 AC: click handler calls the scoped endpoint with GET, not mutation."""
    html = _load_html()

    assert "function vaultBrowserFindRelated(action)" in html
    assert "params.set('note_path', action.dataset.notePath);" in html
    assert "params.set('artifact_uuid', action.dataset.artifactUuid);" in html
    assert "fetch(url, {method: 'GET'})" in html
    assert "renderVaultBrowserFindRelatedResults(data);" in html


# ---- AC6: body update flow remains separate ----


def test_body_update_flow_not_in_inspector_actions() -> None:
    """AC6: The active-note body update flow is NOT rendered as a browser action."""
    html = _inspector_html(_load_html())
    assert 'data-testid="workspace-active-note-body-update-flow"' not in html
    assert 'data-testid="workspace-active-note-body-update-submit"' not in html
