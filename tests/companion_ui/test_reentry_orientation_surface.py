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
            raise AssertionError(f"unexpected GET from re-entry surface: {url}")
        return self.payload

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        raise AssertionError(f"unexpected POST from re-entry surface: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.delete_calls.append((url, params))
        raise AssertionError(f"unexpected DELETE from re-entry surface: {url}")


def _source_ref(label: str = "orientation signals") -> dict[str, str]:
    return {
        "kind": "runtime_signal",
        "ref": "orientation.signals",
        "label": label,
    }


def _artifact_ref(
    note_path: str = "Notes/resume.md",
    title: str = "Resume plan",
    artifact_id: str = "art-resume",
) -> dict[str, str]:
    return {
        "artifact_id": artifact_id,
        "note_path": note_path,
        "title": title,
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
            "trace_id": "trace-orientation-1",
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
            "kind": "derived_only",
            "artifact_ref": _artifact_ref(),
            "label": "Resume the runtime API contract",
            "last_interaction_at": "2026-05-31T11:45:00Z",
            "last_session_id": None,
            "authority_role": "derived",
            "source_ref": _source_ref(),
        },
        "open_loops": [
            {
                "id": "loop-1",
                "label": "Finish UI re-entry acceptance tests",
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
                "label": "Recent orientation API merge",
                "summary": "Runtime endpoint landed with bounded candidates.",
                "changed_at": "2026-05-31T10:00:00Z",
                "artifact_ref": _artifact_ref("Notes/recent.md", "Recent change", "art-recent"),
                "authority_role": "derived",
                "source_ref": _source_ref("orientation notable change"),
            }
        ],
        "resurface": {
            "candidates": [
                {
                    "id": "candidate-1",
                    "label": "Check runtime API PR",
                    "why_now": "Relevant because API contract just landed.",
                    "signal_labels": ["recent_change=orientation"],
                    "artifact_ref": _artifact_ref("Notes/resurface.md", "Resurface target", "art-resurface"),
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
            "source_ref": {
                "kind": "status",
                "ref": "api-status-derived",
                "label": "minimal status posture",
            },
        },
        "mutation_intents": [],
    }


def test_renders_orientation_with_no_active_note() -> None:
    client = _OrientationClient(_orientation_payload())

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.get_calls == [("/api/companion/orientation", {})]
    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-read-only="true"' in html
    assert "Resume the runtime API contract" in html
    assert "Finish UI re-entry acceptance tests" in html
    assert "Recent orientation API merge" in html
    assert "Relevant because API contract just landed." in html
    assert "pending proposals" in html
    assert "logged" in html
    assert 'data-authority-role="derived"' in html


def test_deep_links_to_artifact_workspace() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
    )

    assert 'href="/workspace?note_path=Notes%2Fresume.md"' in html
    assert 'href="/workspace?note_path=Notes%2Frecent.md"' in html
    assert 'href="/workspace?note_path=Notes%2Fresurface.md"' in html


def test_leave_point_renders_structured_api_shape() -> None:
    payload = _orientation_payload()
    payload["leave_point"] = {
        "status": "present",
        "artifact_ref": {
            "artifact_uuid": "artifact-resume",
            "logical_ref": "Notes/resume.md",
            "title": "Resume plan",
        },
        "captured_at": "2026-05-31T11:45:00Z",
        "last_session_id": "session-123",
        "authority_role": "operational_trace_pointer",
        "source_ref": {
            "kind": "artifact_activation",
            "trace_id": "trace-leave",
        },
    }

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=payload,
    )

    assert 'data-leave-point-kind="present"' in html
    assert 'href="/workspace?note_path=Notes%2Fresume.md"' in html
    assert 'data-artifact-id="artifact-resume"' in html
    assert "Last signal: 2026-05-31T11:45:00Z" in html
    assert 'data-source-ref="trace-leave"' in html


def test_degraded_state_rendered() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(degraded=True),
    )

    assert 'data-testid="workspace-orientation-degraded"' in html
    assert 'data-freshness="partial"' in html
    assert 'data-runtime-posture="degraded"' in html
    assert "resurfacing_source_unavailable" in html


def test_no_mutation_calls() -> None:
    client = _OrientationClient(_orientation_payload())

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.post_calls == []
    assert client.delete_calls == []
    assert "method: 'POST'" not in html
    assert 'data-api-method="POST"' not in html
    assert "/api/companion/note/save" not in html
    assert "/api/companion/workspace/body" not in html
    assert "/api/panel/confirm" not in html
