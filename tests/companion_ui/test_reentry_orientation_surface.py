from __future__ import annotations

from typing import Any

from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientNetworkError


class _OrientationClient:
    def __init__(
        self,
        payload: dict[str, Any],
        vault_browser_payload: dict[str, Any] | None = None,
        orientation_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.vault_browser_payload = vault_browser_payload or _vault_browser_payload()
        self.orientation_error = orientation_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if url == "/api/companion/orientation":
            if self.orientation_error is not None:
                raise self.orientation_error
            return self.payload
        if url == "/api/companion/vault-browser":
            return self.vault_browser_payload
        raise AssertionError(f"unexpected GET from re-entry surface: {url}")

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
            # CUIDR-06 (#2450): the orientation snapshot panels (leave point,
            # open loops, notable changes, resurface) are subtractive — they
            # render only from full_mist (>=2h gap) upward. as_of 12:00 minus a
            # 5h gap (07:00) resolves to full_mist so these panel-mechanics
            # tests exercise the rung where the panels actually live.
            "last_interaction_at": "2026-05-31T07:00:00Z",
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


def _with_resurface_candidates(payload: dict[str, Any], count: int) -> dict[str, Any]:
    payload["resurface"]["candidates"] = [
        {
            "id": f"candidate-{idx}",
            "label": f"Candidate {idx}",
            "why_now": f"Relevant now because signal {idx} changed.",
            "signal_labels": [f"signal={idx}"],
            "artifact_ref": _artifact_ref(f"Notes/resurface-{idx}.md", f"Candidate {idx}", f"art-{idx}"),
            "authority_role": "derived",
            "source_ref": _source_ref(f"resurfacing signal {idx}"),
        }
        for idx in range(count)
    ]
    return payload


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


def test_renders_orientation_with_no_active_note() -> None:
    client = _OrientationClient(_orientation_payload())

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.get_calls == [
        ("/api/companion/orientation", {}),
        ("/api/companion/vault-browser", {"q": "", "limit": 250}),
    ]
    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-read-only="true"' in html
    assert "Resume the runtime API contract" in html
    assert "Finish UI re-entry acceptance tests" in html
    assert "Recent orientation API merge" in html
    assert "Relevant because API contract just landed." in html
    # CUIDR-06 (#2450): the governance summary tile (pending proposals / latest
    # receipt outcome) is operator telemetry and no longer renders on the
    # orientation surface at any rung — it lives behind the System Map.
    assert 'data-testid="workspace-orientation-governance"' not in html
    assert "pending proposals" not in html
    assert 'data-authority-role="derived"' in html
    assert 'data-testid="workspace-orientation-vault-entry"' in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html
    assert 'href="/?note_path=Notes/resume.md"' in html


def test_deep_links_to_artifact_workspace() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
        orientation_vault_browser=_vault_browser_payload(),
    )

    assert 'href="/workspace?note_path=Notes%2Fresume.md"' in html
    assert 'href="/workspace?note_path=Notes%2Frecent.md"' in html
    assert 'href="/workspace?note_path=Notes%2Fresurface.md"' in html


def test_root_keeps_vault_entry_when_orientation_unavailable() -> None:
    client = _OrientationClient(
        _orientation_payload(),
        orientation_error=WorkspaceClientNetworkError("orientation connection refused"),
    )

    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert 'data-testid="workspace-reentry-orientation"' in html
    assert 'data-entry-state="no_vault"' in html
    assert 'data-testid="workspace-orientation-degraded"' not in html
    assert "orientation_unavailable" in html
    assert 'data-testid="workspace-orientation-vault-entry"' in html
    assert 'data-testid="workspace-vault-browser-note-link"' in html
    assert 'data-testid="workspace-error-state"' not in html


def test_leave_point_renders_structured_api_shape() -> None:
    payload = _orientation_payload()
    payload["leave_point"] = {
        "status": "present",
        "artifact_ref": {
            "artifact_uuid": "artifact-resume",
            "logical_ref": "Notes/resume.md",
            "title": "Resume plan",
        },
        # CUIDR-06 (#2450): full_mist gap (5h) so the subtractive leave-point
        # panel renders (panels appear from full_mist upward).
        "captured_at": "2026-05-31T07:00:00Z",
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
        orientation_vault_browser=_vault_browser_payload(),
    )

    assert 'data-leave-point-kind="present"' in html
    assert 'href="/workspace?note_path=Notes%2Fresume.md"' in html
    assert 'data-artifact-id="artifact-resume"' in html
    assert "Last signal: 2026-05-31T07:00:00Z" in html
    assert 'data-source-ref="trace-leave"' in html


def test_degraded_state_rendered() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(degraded=True),
        orientation_vault_browser=_vault_browser_payload(),
    )

    assert 'data-testid="workspace-orientation-degraded"' in html
    assert 'data-freshness="partial"' in html
    assert 'data-runtime-posture="degraded"' in html
    assert "resurfacing_source_unavailable" in html


def test_no_mutation_calls() -> None:
    # The orientation render itself must issue and embed no mutation. Pin a
    # short-rung (soft_mist) gap so the re-entry card — and its card-attached
    # governed memory-review drawer, which ships only from full_mist up and
    # carries its own pull-based review POST — is not present; this isolates the
    # orientation-surface no-mutation contract from the card occupant
    # (CUIDR-06 #2450 makes the ladder subtractive, so the card no longer
    # renders at the short rung this invariant tests).
    payload = _orientation_payload()
    # as_of 12:00 minus a 15-minute gap (11:45) → soft_mist: no card.
    payload["leave_point"]["last_interaction_at"] = "2026-05-31T11:45:00Z"
    client = _OrientationClient(payload)

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


def test_resurfacing_cards_are_budgeted_to_three_by_default() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_with_resurface_candidates(_orientation_payload(), 5),
    )

    assert html.count('data-testid="workspace-orientation-resurface-candidate"') == 3
    assert 'data-resurface-default-budget="3"' in html
    assert 'data-resurface-overflow-count="2"' in html


def test_resurfacing_cards_can_expand_to_server_cap() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_with_resurface_candidates(_orientation_payload(), 5),
    )

    assert 'data-testid="workspace-orientation-resurface-expand"' in html
    assert 'data-server-cap="5"' in html
    assert html.count('data-testid="workspace-orientation-resurface-overflow-candidate"') == 2
    assert "Candidate 4" in html


def test_resurfacing_cards_show_why_now_source_signals_and_authority() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_with_resurface_candidates(_orientation_payload(), 1),
    )

    assert 'data-testid="workspace-orientation-resurface-why-now"' in html
    assert 'data-testid="workspace-orientation-resurface-provenance"' in html
    assert 'data-authority-role="derived"' in html
    assert "signal=0" in html
    assert "resurfacing signal 0" in html


def test_resurfacing_cards_surface_degraded_posture() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_with_resurface_candidates(_orientation_payload(degraded=True), 2),
    )

    assert 'data-testid="workspace-orientation-resurface"' in html
    assert 'data-resurface-posture="degraded"' in html
    assert "resurfacing_source_unavailable" in html


def test_resurfacing_cards_do_not_create_notification_semantics() -> None:
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_with_resurface_candidates(_orientation_payload(), 5),
    )
    section = html.split('data-testid="workspace-orientation-resurface"', 1)[1].split("</section>", 1)[0]

    assert 'data-notification="false"' in section
    assert "urgency" not in section.lower()
    assert "badge" not in section.lower()
    assert "inbox" not in section.lower()
    assert "urgent" not in section.lower()
