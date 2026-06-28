from __future__ import annotations

from typing import Any

from companion_ui.workspace.serve_dev_page import handle_get


class _ReorientationEntryClient:
    def __init__(self) -> None:
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url == "/api/companion/orientation":
            return _orientation_payload()
        if url == "/api/companion/vault-browser":
            return _vault_browser_payload()
        raise AssertionError(f"unexpected GET from reorientation entry path: {url}")

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        raise AssertionError(f"unexpected POST from reorientation entry path: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        raise AssertionError(f"unexpected DELETE from reorientation entry path: {url}")


def _orientation_payload() -> dict[str, Any]:
    return {
        "scope": {
            "kind": "workspace",
            "vault_id": "dev-vault",
            "channel": "dev",
        },
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-08T12:00:00Z",
            "trace_id": "trace-reentry",
            "freshness": "fresh",
            "degraded_reasons": [],
        },
        "leave_point": None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "none",
            "authority_role": "derived",
            "source_ref": {
                "kind": "runtime_signal",
                "ref": "orientation.summary",
                "label": "orientation summary",
            },
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "healthy",
            "degraded": False,
            "reasons": [],
            "authority_role": "derived",
            "source_ref": {
                "kind": "status",
                "ref": "api-status-derived",
                "label": "minimal status posture",
            },
        },
        "mutation_intents": [],
    }


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [
            {
                "note_path": "Notes/resume.md",
                "title": "Resume plan",
                "zone": "Notes",
                "kind": "human_note",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            },
            {
                "note_path": "Projects/Deep work.md",
                "title": "Deep work",
                "zone": "Projects",
                "kind": "human_note",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            },
        ],
        "query": "",
        "total_notes": 2,
        "filtered_notes": 2,
        "read_only": True,
        "identity_available": True,
        "vault_identity": {
            "vault_name": "dev-vault",
            "channel": "dev",
            "provenance": "env",
        },
    }


def test_root_reorientation_screen_has_continuation_path() -> None:
    client = _ReorientationEntryClient()

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-testid="workspace-orientation-vault-entry"' in html
    assert "Browse notes" in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html


def test_reorientation_continuation_uses_workspace_navigation_target() -> None:
    client = _ReorientationEntryClient()

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
    assert 'href="/?note_path=Notes/resume.md"' in html
    assert 'href="/?note_path=Projects/Deep%20work.md"' in html


def test_reorientation_continuation_preserves_read_only_orientation() -> None:
    client = _ReorientationEntryClient()

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.post_calls == []
    assert client.delete_calls == []
    assert 'data-read-only="true"' in html
    # The orientation surface carries no implicit (background) POST calls at
    # render time. User-initiated governed writes (e.g. the capture modal on
    # cold_start, wired via capture.save → POST /api/companion/capture) are
    # acceptable; only ungoverned or implicit mutation paths are banned here.
    assert 'data-api-method="POST"' not in html
    assert "/api/companion/workspace/body" not in html
    assert "/api/panel/confirm" not in html
