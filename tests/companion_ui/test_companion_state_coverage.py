"""Fixture-safe state coverage for the major Companion UI modes (#1550).

A consolidated, repeatable coverage matrix over the currently shipped /
dev-staging Companion UI surfaces named in
`companion-ui/docs/COMPANION_UI_STATE_MAP.md`. Every assertion is driven by
in-memory fixtures or response fixtures — no private live vault, no committed
screenshots. Assertions pin stable `data-testid` / `data-*` regions that the
dev page already emits; this module does not invent runtime schema.

Scope guard: this module intentionally does NOT assert agent-memory review
authority. That posture is governed by #1474 / #1547 / #1551 and covered by the
dedicated Vault Browser posture coverage module; see #1550 acceptance criteria.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient

API_BASE = "http://127.0.0.1:18001"


# --------------------------------------------------------------------------
# Orientation (re-entry) fixtures — pure render, no network
# --------------------------------------------------------------------------
def _source_ref(label: str = "orientation signals") -> dict[str, str]:
    return {"kind": "runtime_signal", "ref": "orientation.signals", "label": label}


def _artifact_ref(
    note_path: str = "Notes/resume.md",
    title: str = "Resume plan",
    artifact_id: str = "art-resume",
) -> dict[str, str]:
    return {"artifact_id": artifact_id, "note_path": note_path, "title": title}


def _orientation_payload(*, degraded: bool = False) -> dict[str, Any]:
    reasons = ["resurfacing_source_unavailable"] if degraded else []
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-03T12:00:00Z",
            "trace_id": "trace-state-coverage",
            "freshness": "partial" if degraded else "fresh",
            "stale_after": "2026-06-03T12:05:00Z",
            "degraded_reasons": reasons,
            "caps": {
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "mutation_intents": 0,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": {
            "kind": "derived_only",
            "artifact_ref": _artifact_ref(),
            "label": "Resume the state-map work",
            "last_interaction_at": "2026-06-03T11:45:00Z",
            "last_session_id": None,
            "authority_role": "derived",
            "source_ref": _source_ref(),
        },
        "open_loops": [
            {
                "id": "loop-1",
                "label": "Finish state coverage tests",
                "status": "open",
                "handoff_hint": "panel",
                "artifact_ref": _artifact_ref(),
                "authority_role": "derived",
                "source_ref": _source_ref("orientation open items"),
            }
        ],
        "notable_changes": [
            {
                "id": "change-1",
                "label": "State map merged",
                "summary": "Companion UI state map landed.",
                "changed_at": "2026-06-03T10:00:00Z",
                "artifact_ref": _artifact_ref("Notes/recent.md", "Recent", "art-recent"),
                "authority_role": "derived",
                "source_ref": _source_ref("orientation notable change"),
            }
        ],
        "resurface": {
            "candidates": [
                {
                    "id": "candidate-1",
                    "label": "Review the state map",
                    "why_now": "Relevant because the state map just landed.",
                    "signal_labels": ["recent_change=state_map"],
                    "artifact_ref": _artifact_ref("Notes/resurface.md", "Resurface", "art-rs"),
                    "authority_role": "derived",
                    "source_ref": _source_ref("resurfacing signal"),
                }
            ]
        },
        "governance": {
            "pending_proposal_count": 2,
            "pending_receipt_count": 1,
            "latest_receipt_outcome": "logged",
            "authority_role": "derived",
            "source_ref": _source_ref("governance summary"),
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded" if degraded else "healthy",
            "degraded": degraded,
            "reasons": reasons,
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "api-status-derived", "label": "status"},
        },
        "mutation_intents": [],
    }


class _OrientationClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url != "/api/companion/orientation":
            raise AssertionError(f"unexpected GET: {url}")
        return self.payload


# --------------------------------------------------------------------------
# Active-note / Vault Browser inspector fixtures — page load via mocked httpx
# --------------------------------------------------------------------------
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
            "trace_id": "trace-coverage",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _browser_note(
    *,
    note_path: str = "notes/current.md",
    title: str = "Current",
    review_state: str | None = "needs_review",
    trust: str | None = "assert",
) -> dict[str, Any]:
    return {
        "note_path": note_path,
        "title": title,
        "uuid": "test-uuid-abc",
        "kind": "human_note",
        "zone": "notes",
        "review_state": review_state,
        "trust": trust,
        "origin": "vault",
        "source_ref": None,
        "created": "2026-01-01",
        "updated": "2026-05-01",
        "frontmatter_valid": True,
        "missing_required_fields": [],
    }


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


def _render_active_note(
    *,
    note_path: str = "notes/current.md",
    workspace_payload: dict[str, Any] | None = None,
    browser_payload: dict[str, Any] | None = None,
) -> str:
    workspace = _mock_get_response(workspace_payload or _workspace_payload(note_path=note_path))
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
    return render_index_html(api_base_url=API_BASE, note_path=note_path, fields=fields)


# --------------------------------------------------------------------------
# Coverage tests
# --------------------------------------------------------------------------
def test_reentry_orientation_fresh_state() -> None:
    """Re-entry orientation, nothing open, fresh freshness."""
    client = _OrientationClient(_orientation_payload())
    html = handle_get(query_string="", client=client, api_base_url=API_BASE)  # type: ignore[arg-type]

    assert client.get_calls == [("/api/companion/orientation", {})]
    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-read-only="true"' in html
    assert 'data-authority-role="derived"' in html
    assert 'data-freshness="fresh"' in html
    assert 'data-degraded="false"' in html
    # degraded section absent when healthy
    assert 'data-testid="workspace-orientation-degraded"' not in html
    assert "Resume the state-map work" in html


def test_reentry_orientation_degraded_state() -> None:
    """Degraded / stale / manual-refresh orientation state."""
    html = render_index_html(api_base_url=API_BASE, orientation=_orientation_payload(degraded=True))

    assert 'data-testid="workspace-orientation-degraded"' in html
    assert 'data-testid="workspace-orientation-manual-refresh"' in html
    assert 'data-freshness="partial"' in html
    assert 'data-degraded="true"' in html
    assert 'data-refresh-state="degraded"' in html


def test_active_note_workspace_desktop_state() -> None:
    """Active note workspace renders from fixtures, read-only and titled."""
    html = _render_active_note()

    assert "Current" in html
    assert 'data-read-only' in html
    # active-note shell renders without requiring a private vault
    assert "Unexpected URL" not in html


def test_artifact_inspector_review_and_receipt_posture() -> None:
    """Inspector distinguishes frontmatter/review posture from receipt posture."""
    html = _render_active_note()

    # frontmatter/review posture region
    assert 'data-testid="workspace-vault-browser-inspector"' in html
    assert 'data-testid="workspace-vault-browser-inspector-posture-review-state"' in html
    assert "needs_review" in html
    # receipt posture is a distinct region from review posture
    assert 'data-receipt-state="' in html or 'data-testid="vault-browser-receipt-state"' in html
