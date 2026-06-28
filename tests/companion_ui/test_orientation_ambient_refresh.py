from __future__ import annotations

from typing import Any

from companion_ui.workspace.serve_dev_page import handle_get, render_index_html


class _OrientationClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url != "/api/companion/orientation":
            raise AssertionError(f"unexpected GET from orientation surface: {url}")
        return self.payload

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        raise AssertionError(f"unexpected POST from orientation surface: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        raise AssertionError(f"unexpected DELETE from orientation surface: {url}")


def _source_ref(label: str = "orientation signals") -> dict[str, str]:
    return {
        "kind": "runtime_signal",
        "ref": "orientation.signals",
        "label": label,
    }


def _artifact_ref(note_path: str = "Notes/resume.md") -> dict[str, str]:
    return {
        "artifact_uuid": "art-resume",
        "logical_ref": note_path,
        "title": "Resume plan",
    }


def _orientation_payload(*, degraded: bool = False) -> dict[str, Any]:
    reasons = ["resurfacing_source_unavailable"] if degraded else []
    return {
        "scope": {
            "kind": "workspace",
            "vault_id": "dev-vault",
            "channel": "dev",
        },
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-05-31T12:00:00Z",
            "trace_id": "trace-orientation-ambient",
            "freshness": "partial" if degraded else "fresh",
            "stale_after": "2026-05-31T12:05:00Z",
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
            "status": "present",
            "artifact_ref": _artifact_ref(),
            "captured_at": "2026-05-31T11:45:00Z",
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        },
        "open_loops": [],
        "notable_changes": [],
        "resurface": {
            "candidates": [
                {
                    "id": "candidate-1",
                    "label": "Check runtime API PR",
                    "why_now": "Relevant because API contract just landed.",
                    "signal_labels": ["recent_change=orientation"],
                    "artifact_ref": _artifact_ref("Notes/resurface.md"),
                    "authority_role": "derived",
                    "source_ref": _source_ref("resurfacing signal"),
                }
            ]
        },
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": _source_ref("governance summary"),
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded" if degraded else "healthy",
            "degraded": degraded,
            "reasons": reasons,
            "authority_role": "derived",
            "source_ref": _source_ref("minimal status posture"),
        },
        "mutation_intents": [],
    }


def test_ambient_refresh_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_ORIENTATION_AMBIENT_REFRESH", raising=False)
    client = _OrientationClient(_orientation_payload())

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
    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-ambient-refresh="disabled"' in html
    assert 'data-refresh-mode="manual"' in html
    assert "fetch('/api/companion/orientation'" not in html


def test_ambient_refresh_uses_foreground_pull_after_staleness(monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_ORIENTATION_AMBIENT_REFRESH", "1")
    client = _OrientationClient(_orientation_payload())

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
    assert 'data-ambient-refresh="enabled"' in html
    assert 'data-stale-after="2026-05-31T12:05:00Z"' in html
    assert 'data-refresh-mode="foreground_pull"' in html
    assert "fetch('/api/companion/orientation', {method: 'GET'})" in html
    assert "window.setTimeout(refreshIfForeground, delay)" in html
    assert "document.addEventListener('visibilitychange'" in html
    assert "window.addEventListener('focus', refreshWhenStale)" in html
    assert "EventSource" not in html
    assert "WebSocket" not in html


def test_ambient_refresh_preserves_degraded_and_stale_states() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(degraded=True),
        ambient_refresh_enabled=True,
    )

    assert 'data-testid="workspace-orientation-degraded"' in html
    assert 'data-freshness="partial"' in html
    assert 'data-degraded="true"' in html
    assert 'data-refresh-state="degraded"' in html
    assert 'data-testid="workspace-orientation-manual-refresh"' in html
    assert "resurfacing_source_unavailable" in html


def test_ambient_refresh_renders_no_notification_ui() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
        ambient_refresh_enabled=True,
    )

    forbidden = [
        "Notification",
        "EventSource",
        "WebSocket",
        "setInterval",
        "data-testid=\"orientation-notification\"",
        "data-testid=\"orientation-badge\"",
        "data-testid=\"orientation-modal\"",
        "data-testid=\"orientation-banner\"",
        "urgency",
    ]
    for token in forbidden:
        assert token not in html


def test_ambient_refresh_has_no_write_or_action_execution_path() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
        ambient_refresh_enabled=True,
    )

    assert "method: 'POST'" not in html
    assert 'data-api-method="POST"' not in html
    assert "/api/panel/confirm" not in html
    assert "/api/companion/workspace/body" not in html
    assert "resurface.dismiss" not in html
    assert "resurface.snooze" not in html
    assert "resurface.pin" not in html


def test_orientation_vault_entry_includes_browser_control_handlers() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
        orientation_vault_browser={
            "notes": [
                {
                    "note_path": "Notes/resume.md",
                    "title": "Resume plan",
                    "kind": "source",
                    "zone": "work",
                    "review_state": "draft",
                    "trust": "human",
                }
            ],
            "query": "",
            "total_notes": 1,
            "filtered_notes": 1,
            "read_only": True,
            "identity_available": True,
            "vault_identity": {
                "vault_name": "vault-test",
                "channel": "test",
                "provenance": "test",
            },
        },
    )

    assert 'onclick="vbToggleFilter(this)"' in html
    assert "function vbToggleFilter(el)" in html
    # #2526: the dead ui_only selection checkbox/toggle was removed; only the
    # filter-toggle control handler remains in the orientation vault entry.
    assert "vaultBrowserToggleSelection" not in html
    assert "method: 'POST'" not in html
