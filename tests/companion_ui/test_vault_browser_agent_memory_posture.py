"""Vault Browser agent-memory posture rendering stays non-authoritative."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient


def _workspace_payload(note_path: str = "notes/current.md") -> dict[str, Any]:
    return {
        "artifact": {
            "artifact_id": "note-uuid-1",
            "artifact_kind": "human_note",
            "note_path": note_path,
            "title": "Current",
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
            "trace_id": "trace-agent-memory-posture",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _agent_memory_posture() -> dict[str, Any]:
    return {
        "source": "agent_memory.review_queue",
        "authority": "non_authoritative",
        "state": "pending",
        "counts": {"pending": 1, "promoted": 0, "rejected": 0, "revised": 0},
        "items": [
            {
                "candidate_id": "candidate-1474",
                "title": "Observed posture candidate",
                "status": "pending",
                "review_state": "unreviewed",
                "memory_type": "preference_memory",
                "inferred": True,
                "source_refs": ["note_path:notes/current.md"],
                "derived_from": None,
                "generated_by": "agent_memory.test",
                "revision_of": None,
            }
        ],
    }


def _browser_note(
    *,
    note_path: str = "notes/current.md",
    agent_memory_posture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "note_path": note_path,
        "title": "Current",
        "uuid": "note-uuid-abc",
        "kind": "human_note",
        "zone": "notes",
        "review_state": "reviewed",
        "trust": "assert",
        "origin": "vault",
        "source_ref": None,
        "created": None,
        "updated": None,
        "frontmatter_valid": True,
        "missing_required_fields": [],
        "receipts": [],
        "agent_memory_posture": agent_memory_posture or _agent_memory_posture(),
    }


def _vault_browser_payload(notes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    notes = notes or [_browser_note()]
    return {
        "notes": notes,
        "query": "",
        "total_notes": len(notes),
        "filtered_notes": len(notes),
        "read_only": True,
        "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        "identity_available": True,
        "active_filters": {},
        "pagination": {
            "mode": "cursor",
            "cursor": None,
            "next_cursor": None,
            "previous_cursor": None,
            "page_size": len(notes),
            "returned_notes": len(notes),
            "total_filtered_notes": len(notes),
            "has_next": False,
            "has_previous": False,
        },
    }


def _mock_get_response(payload: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    return mock


def _load_html(*, browser_payload: dict[str, Any] | None = None) -> str:
    workspace = _mock_get_response(_workspace_payload())
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
        page.load(NoteLoadIntent(note_path="notes/current.md"))

    fields = page.render_fields()
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="notes/current.md",
        fields=fields,
    )


def _agent_memory_section(html: str) -> str:
    marker = 'data-testid="workspace-vault-browser-inspector-agent-memory-posture"'
    marker_start = html.find(marker)
    if marker_start == -1:
        return ""
    start = html.rfind("<div", 0, marker_start)
    end = html.find("</div>", marker_start)
    return html[start : end + len("</div>")] if start != -1 and end != -1 else ""


def test_inspector_renders_agent_memory_posture_non_authoritative() -> None:
    html = _load_html()
    section = _agent_memory_section(html)

    assert 'data-testid="workspace-vault-browser-inspector-agent-memory-posture"' in section
    assert 'data-agent-memory-authority="non_authoritative"' in section
    assert 'data-agent-memory-state="pending"' in section
    assert 'data-testid="vault-browser-agent-memory-posture-row"' in section
    assert "candidate-1474" in section
    assert "unreviewed" in section


def test_agent_memory_posture_section_contains_no_mutation_controls() -> None:
    html = _load_html()
    section = _agent_memory_section(html)

    assert 'data-api-method="POST"' not in section
    assert 'data-api-method="DELETE"' not in section
    assert 'data-api-method="PUT"' not in section
    assert 'data-api-method="PATCH"' not in section
    assert "<button" not in section
    assert "<form" not in section
