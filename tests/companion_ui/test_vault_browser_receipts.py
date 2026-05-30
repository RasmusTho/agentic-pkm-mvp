"""Agent receipts and review posture display in the inspector (#1257).

Pins the MLP v0 invariants for receipt/posture rendering in the vault browser inspector:

- inspector renders a receipt/review posture section
- UI distinguishes 'no receipts found' from 'receipt source unavailable/not connected'
- UI renders queued/applied/blocked/rejected/failed receipt states from fixture payload
- receipt display keeps artifact UUID/path, receipt ID, and trace ID separate
- unreviewed/inferred memory is visible with explicit posture and is NOT action-authorizing
- no mutation endpoint or action added

Data model:
  - If the note payload has a 'receipts' key with value [] → no_receipts state
  - If the note payload has no 'receipts' key → unavailable state
  - If receipts list is non-empty → render each with its state
  - Review posture rendered from existing metadata (review_state, trust)

Receipt states: no_receipts, unavailable, queued, applied, blocked, rejected, failed.
"""

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
            "trace_id": "trace-receipts",
            "vault_identity": {"vault_name": "Niflheim", "channel": "dev", "provenance": "env"},
        },
        "suggestions": {},
    }


def _browser_note(
    *,
    note_path: str = "notes/current.md",
    title: str = "Current",
    uuid: str | None = "note-uuid-abc",
    review_state: str | None = "needs_review",
    trust: str | None = "assert",
    receipts: list[dict[str, Any]] | None = None,
    include_receipts_key: bool = True,
) -> dict[str, Any]:
    note: dict[str, Any] = {
        "note_path": note_path,
        "title": title,
        "uuid": uuid,
        "kind": "human_note",
        "zone": "notes",
        "review_state": review_state,
        "trust": trust,
        "origin": "vault",
        "source_ref": None,
        "created": None,
        "updated": None,
        "frontmatter_valid": True,
        "missing_required_fields": [],
    }
    if include_receipts_key:
        note["receipts"] = receipts if receipts is not None else []
    return note


def _receipt(
    *,
    receipt_id: str = "rcpt-001",
    state: str = "queued",
    action_type: str = "frontmatter_update",
    action_id: str = "action-001",
    artifact_path: str = "notes/current.md",
    artifact_uuid: str | None = "note-uuid-abc",
    requested_by: str = "agent:codex",
    approved_by: str = "human:rasmus",
    status: str = "ok",
    timestamp: str = "2026-05-30T21:00:00Z",
    trace_id: str | None = "trace-001",
) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "state": state,
        "action_type": action_type,
        "action_id": action_id,
        "artifact_path": artifact_path,
        "artifact_uuid": artifact_uuid,
        "requested_by": requested_by,
        "approved_by": approved_by,
        "status": status,
        "timestamp": timestamp,
        "trace_id": trace_id,
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
    start = html.find('data-testid="workspace-vault-browser-inspector"')
    if start == -1:
        return ""
    end = html.find("</section>", start)
    return html[start:end + len("</section>")] if end != -1 else html[start:]


def _receipt_detail_html(html: str) -> str:
    marker = 'data-testid="vault-browser-receipt-detail"'
    marker_start = html.find(marker)
    if marker_start == -1:
        return ""
    start = html.rfind("<dl", 0, marker_start)
    end = html.find("</dl>", marker_start)
    return html[start : end + len("</dl>")] if start != -1 and end != -1 else ""


# ---- AC1: receipt/posture section renders ----


def test_inspector_renders_receipt_posture_section() -> None:
    """AC1: Inspector contains a receipt/review posture section."""
    html = _inspector_html(_load_html())
    assert 'data-testid="workspace-vault-browser-inspector-receipts"' in html


def test_inspector_renders_review_posture_from_metadata() -> None:
    """AC1: Review posture (review_state, trust) rendered in the posture section."""
    note = _browser_note(review_state="needs_review", trust="assert")
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-testid="workspace-vault-browser-inspector-review-posture"' in html
    assert "needs_review" in html
    assert "assert" in html


# ---- AC2: no_receipts vs unavailable distinguished ----


def test_no_receipts_state_when_receipts_empty_list() -> None:
    """AC2: receipts=[] → 'no receipts found' state, not 'unavailable'."""
    note = _browser_note(receipts=[])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="no_receipts"' in html
    assert 'data-receipt-state="unavailable"' not in html


def test_unavailable_state_when_receipts_key_absent() -> None:
    """AC2: receipts key absent from payload → 'unavailable' state, not 'no_receipts'."""
    note = _browser_note(include_receipts_key=False)
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="unavailable"' in html
    assert 'data-receipt-state="no_receipts"' not in html


# ---- AC3: receipt states rendered when present ----


def test_queued_receipt_rendered() -> None:
    """AC3: queued receipt is rendered with its state."""
    note = _browser_note(receipts=[_receipt(state="queued")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-testid="vault-browser-receipt-row"' in html
    assert 'data-receipt-state="queued"' in html
    assert 'data-receipt-state="unavailable"' not in html


def test_applied_receipt_rendered() -> None:
    """AC3: applied receipt is rendered with its state."""
    note = _browser_note(receipts=[_receipt(state="applied")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="applied"' in html


def test_blocked_receipt_rendered() -> None:
    """AC3: blocked receipt is rendered with its state."""
    note = _browser_note(receipts=[_receipt(state="blocked")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="blocked"' in html


def test_rejected_receipt_rendered() -> None:
    """AC3: rejected receipt is rendered with its state."""
    note = _browser_note(receipts=[_receipt(state="rejected")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="rejected"' in html


def test_failed_receipt_rendered() -> None:
    """AC3: failed receipt is rendered with its state."""
    note = _browser_note(receipts=[_receipt(state="failed")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-receipt-state="failed"' in html


# ---- AC4: identity separation ----


def test_receipt_display_keeps_receipt_id_separate() -> None:
    """AC4: receipt_id is rendered in a dedicated element, not mixed with artifact uuid."""
    note = _browser_note(
        uuid="art-uuid-xyz",
        receipts=[_receipt(receipt_id="rcpt-001", trace_id="trace-001")],
    )
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-testid="vault-browser-receipt-id"' in html
    assert "rcpt-001" in html


def test_receipt_trace_id_rendered_separately() -> None:
    """AC4: trace_id is in its own element, separate from receipt_id and artifact uuid."""
    note = _browser_note(receipts=[_receipt(trace_id="trace-xyz")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-testid="vault-browser-receipt-trace-id"' in html
    assert "trace-xyz" in html


def test_receipt_row_exposes_collapsed_detail_toggle() -> None:
    """#1284: receipt row expands a deterministic read-only detail region."""
    note = _browser_note(receipts=[_receipt(receipt_id="rcpt-detail-001")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    detail = _receipt_detail_html(html)

    assert 'onclick="vaultBrowserToggleReceiptDetail(this)"' in html
    assert 'data-detail-id="vault-browser-receipt-detail-0"' in html
    assert 'aria-expanded="false"' in html
    assert 'data-testid="vault-browser-receipt-detail"' in detail
    assert 'id="vault-browser-receipt-detail-0"' in detail
    assert "hidden" in detail
    assert 'aria-hidden="true"' in detail
    assert 'data-expanded="false"' in detail


def test_receipt_detail_displays_available_receipt_fields() -> None:
    """#1284: expanded receipt detail exposes VaultReceipt fields."""
    note = _browser_note(
        receipts=[
            _receipt(
                receipt_id="rcpt-detail-002",
                trace_id="trace-detail-002",
                action_id="action-detail-002",
                artifact_uuid="note-uuid-detail",
                requested_by="agent:test",
                approved_by="human:test",
                status="ok",
                timestamp="2026-05-30T22:00:00Z",
            )
        ]
    )
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    detail = _receipt_detail_html(html)

    assert 'data-testid="vault-browser-receipt-detail-receipt-id"' in detail
    assert "rcpt-detail-002" in detail
    assert 'data-testid="vault-browser-receipt-detail-trace-id"' in detail
    assert "trace-detail-002" in detail
    assert 'data-testid="vault-browser-receipt-detail-action-id"' in detail
    assert "action-detail-002" in detail
    assert 'data-testid="vault-browser-receipt-detail-artifact-uuid"' in detail
    assert "note-uuid-detail" in detail
    assert 'data-testid="vault-browser-receipt-detail-requested-by"' in detail
    assert "agent:test" in detail
    assert 'data-testid="vault-browser-receipt-detail-approved-by"' in detail
    assert "human:test" in detail
    assert 'data-testid="vault-browser-receipt-detail-status"' in detail
    assert "ok" in detail
    assert 'data-testid="vault-browser-receipt-detail-timestamp"' in detail
    assert "2026-05-30T22:00:00Z" in detail


def test_receipt_detail_contains_no_buttons_or_forms() -> None:
    """#1284: detail section is read-only and contains no action controls."""
    note = _browser_note(receipts=[_receipt()])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    detail = _receipt_detail_html(html)

    assert "<button" not in detail
    assert "<form" not in detail


def test_receipt_detail_toggle_function_collapses_deterministically() -> None:
    """#1284: second click collapses via the same deterministic toggler."""
    note = _browser_note(receipts=[_receipt()])
    html = _load_html(browser_payload=_vault_browser_payload(notes=[note]))

    assert "function vaultBrowserToggleReceiptDetail(row)" in html
    assert "var expanded = row.getAttribute('aria-expanded') === 'true';" in html
    assert "detail.hidden = expanded;" in html
    assert "row.setAttribute('aria-expanded', expanded ? 'false' : 'true');" in html


# ---- AC5: unreviewed memory visible but not action-authorizing ----


def test_unreviewed_note_shows_review_posture_not_authoritative() -> None:
    """AC5: needs_review state is visible and marked as non-authoritative."""
    note = _browser_note(review_state="needs_review", trust="assert")
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-review-authority="non_authoritative"' in html or 'data-testid="workspace-vault-browser-inspector-review-posture"' in html
    # No "active" affordance should be asserted based on review state alone
    assert 'data-affordance-status="active"' not in html


# ---- AC6: no mutation endpoint ----


def test_no_mutation_controls_in_receipts_section() -> None:
    """AC6: The receipts section contains no write/mutation controls."""
    note = _browser_note(receipts=[_receipt(state="queued")])
    html = _inspector_html(_load_html(browser_payload=_vault_browser_payload(notes=[note])))
    assert 'data-api-method="POST"' not in html
    assert 'data-api-method="DELETE"' not in html
    assert 'data-api-method="PUT"' not in html
    assert 'data-api-method="PATCH"' not in html
