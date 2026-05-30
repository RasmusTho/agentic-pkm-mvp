from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceClientNetworkError,
    WorkspaceHttpClient,
)


def _workspace_payload(note_path: str = "notes/current.md", title: str = "Current") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-update-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": title,
            "body": "# Body\n\nInitial text.\n",
            "content_hash": "hash-current",
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
            "trace_id": "trace-active-note-update",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [
            {
                "note_path": "notes/current.md",
                "title": "Current",
                "zone": "notes",
            }
        ],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_page(*, workspace_payload: dict[str, Any] | None = None) -> RealNoteWorkspaceDevPage:
    workspace = _mock_get_response(workspace_payload or _workspace_payload())
    browser = _mock_get_response(_vault_browser_payload())

    def _side_effect(url: str, *, params: dict[str, Any], timeout: float):
        if url.endswith("/api/companion/workspace"):
            return workspace
        if url.endswith("/api/companion/vault-browser"):
            return browser
        raise AssertionError(f"Unexpected URL: {url}")

    with patch("httpx.get", side_effect=_side_effect):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        page = RealNoteWorkspaceDevPage(client)
        page.load(NoteLoadIntent(note_path="notes/current.md"))
    return page


def test_user_can_enter_active_note_body_update_flow() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-flow"' in html
    assert 'data-testid="workspace-active-note-body-update-input"' in html
    assert 'data-testid="workspace-active-note-body-update-submit"' in html


def test_body_update_renders_success_blocked_and_failure_states() -> None:
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None

    fields["active_note_body_update_state"] = "success"
    fields["active_note_body_update_message"] = "active_note_body_updated"
    success_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-success"' in success_html

    fields["active_note_body_update_state"] = "blocked"
    fields["active_note_body_update_message"] = "writeguard blocked"
    blocked_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-blocked"' in blocked_html

    fields["active_note_body_update_state"] = "failure"
    fields["active_note_body_update_message"] = "network timeout"
    failure_html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    assert 'data-testid="workspace-active-note-body-update-state-failure"' in failure_html


def test_blocked_body_update_preserves_loaded_state_and_renders_blocked_status() -> None:
    page = _load_page()
    page.state.guard_workspace_update_available = False
    state = page.update_active_note_body(new_body="# Body\n\nBlocked")
    assert state.is_loaded is True
    assert state.shell is not None
    assert state.active_note_body_update_state == "blocked"


def test_failed_body_update_preserves_loaded_state_and_renders_failure_status() -> None:
    page = _load_page()
    with patch.object(page._http, "post", side_effect=WorkspaceClientNetworkError("network timeout")):
        state = page.update_active_note_body(new_body="# Body\n\nFail")
    assert state.is_loaded is True
    assert state.shell is not None
    assert state.active_note_body_update_state == "failure"


# ---------------------------------------------------------------------------
# #1346 acceptance: body-edit wiring through active_note_body_update
# (Canvas commit, writeguard, staged-proposal preservation; #1332 AC4 blocker).
# The live enabled-Canvas human UAT runs against a dev runtime with Canvas
# enabled; the live Niflheim runtime keeps Canvas disabled, so that walk is
# handed to the owner. These pin the automated acceptance.
# ---------------------------------------------------------------------------


def _render(page: RealNoteWorkspaceDevPage) -> str:
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )


def test_no_writes_when_canvas_disabled() -> None:
    # AC1 — when the runtime update capability is unavailable (Canvas disabled),
    # the body update attempts no write and the flow reports the blocked state.
    page = _load_page()
    page.state.guard_workspace_update_available = False
    with patch.object(page._http, "post") as mock_post:
        state = page.update_active_note_body(new_body="# Body\n\nMust not write")
    mock_post.assert_not_called()
    assert state.active_note_body_update_state == "blocked"


def test_commit_round_trip() -> None:
    # AC2 — with the update capability available, an explicit commit posts to the
    # runtime update endpoint, reloads, and surfaces the success state.
    updated = _workspace_payload()
    updated["artifact"]["body"] = "# Body\n\n## Committed Heading\n\nDone."
    updated["artifact"]["content_hash"] = "hash-after"
    page = _load_page()

    def _get(url: str, *, params, timeout):
        if url.endswith("/api/companion/workspace"):
            return _mock_get_response(updated)
        if url.endswith("/api/companion/vault-browser"):
            return _mock_get_response(_vault_browser_payload())
        raise AssertionError(url)

    with patch("httpx.get", side_effect=_get), patch.object(
        page._http, "post", return_value={"reason": "active_note_body_updated"}
    ) as mock_post:
        state = page.update_active_note_body(new_body="# Body\n\n## Committed Heading\n\nDone.")

    assert mock_post.call_args[0][0] == "/api/companion/workspace/update"
    payload = mock_post.call_args.kwargs["json"]
    assert payload["active_note_path"] == "notes/current.md"
    assert payload["new_body"].endswith("Done.")
    assert state.active_note_body_update_state == "success"


def test_writeguard_rejection_surfaces_failure_state() -> None:
    # AC3 — a writeguard rejection surfaces as the blocked state in the flow DOM;
    # no silent loss, no infinite spinner.
    page = _load_page()
    with patch.object(
        page._http,
        "post",
        side_effect=WorkspaceClientHTTPError(403, "writeguard blocked: scope not allowed"),
    ):
        state = page.update_active_note_body(new_body="# Body\n\nBlocked")
    assert state.active_note_body_update_state == "blocked"
    assert "writeguard" in state.active_note_body_update_message.lower()
    html = _render(page)
    assert 'data-testid="workspace-active-note-body-update-state-blocked"' in html


def test_unsaved_edit_signal_visible() -> None:
    # AC5 — an uncommitted edit (staged state) renders a visible unsaved signal,
    # and the input carries the client reveal hook for real typing.
    page = _load_page()
    fields = page.render_fields()
    assert fields is not None
    fields["active_note_body_update_state"] = "staged"
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )
    match = re.search(
        r'<div class="active-note-body-update-staged"[^>]*'
        r'data-testid="workspace-active-note-body-update-state-staged"([^>]*)>',
        html,
    )
    assert match, "staged unsaved-edit signal must be present"
    assert "hidden" not in match.group(1), "staged signal must be visible when staged"
    # The input reveals the signal on uncommitted typing.
    assert "oninput=" in html
    assert "workspace-active-note-body-update-state-staged" in html


def test_body_rerenders_with_renderer_after_commit() -> None:
    # AC6 — after a successful commit the body re-renders through the Markdown
    # renderer (not raw text): a heading in the new body becomes an <h2>.
    updated = _workspace_payload()
    updated["artifact"]["body"] = "# Body\n\n## Committed Heading\n\nRendered."
    page = _load_page()

    def _get(url: str, *, params, timeout):
        if url.endswith("/api/companion/workspace"):
            return _mock_get_response(updated)
        if url.endswith("/api/companion/vault-browser"):
            return _mock_get_response(_vault_browser_payload())
        raise AssertionError(url)

    with patch("httpx.get", side_effect=_get), patch.object(
        page._http, "post", return_value={"reason": "active_note_body_updated"}
    ):
        page.update_active_note_body(new_body="# Body\n\n## Committed Heading\n\nRendered.")

    html = _render(page)
    assert 'class="vault-markdown-rendered"' in html
    assert '<h2 id="committed-heading">Committed Heading</h2>' in html


def test_proposal_does_not_auto_apply() -> None:
    # AC4 — a Panel proposal carrying suggested body text does not become document
    # state on its own: loading/rendering a staged proposal posts no Canvas edit.
    payload = _workspace_payload()
    payload["panel"] = {"state": "proposals-staged", "proposal_count": 1}
    page = _load_page(workspace_payload=payload)
    with patch.object(page._http, "post") as mock_post:
        html = _render(page)
    mock_post.assert_not_called()
    assert page.state.panel_proposal_count == 1
    # An explicit apply still requires the staged_body state machine, never an
    # automatic commit (guard in apply_body_suggestion).
    page.state.suggestion_state = "idle"
    result = page.apply_body_suggestion(
        suggestion_id="sugg-1", session_id="session-1", note_path="notes/current.md"
    )
    assert "staged_body" in (result.error or "")
    assert 'data-testid="workspace-active-note-body-update-flow"' in html
