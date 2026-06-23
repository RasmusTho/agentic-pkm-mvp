"""Receipts history surface — read-only receipts modal (#1794, SEP-10).

Implements ``docs/SYSTEM_ENTRY_POINT/RECEIPTS_HISTORY_SURFACE.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Surface composition — Receipts/history row: Receipt class, read-only,
runtime-produced, "Receipts are never invented by the UI"; §Intent vocabulary
``receipts.open``) and ``companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md``
(blocked renders as a calm held boundary, never a generic error):

- a top modal mounted on the shared overlay host (``receipts.open``), reached
  from the topbar surface icon, dismissing back to the document anchor;
- renders a bounded recent list of **existing runtime-produced receipt
  projections** (the vault-browser ``notes[].receipts`` projection over
  governed outbox records, ``app/receipts/artifact_receipts.py``) with
  outcome, id, target, and timestamp rendered verbatim;
- strictly read-only: reads only, no receipt creation, no mutation
  affordance, no receipt invented, edited, or re-derived;
- blocked receipts render with guard posture — a held boundary is a success
  of the governance model, not a failure of the app.

Like ``test_overlay_host.py`` and ``test_memory_review_drawer.py``, the pure
projections in ``receipts_history.py`` are the contract the in-page
controller mirrors; tests assert both.
"""

from __future__ import annotations

import io
import re
from typing import Any

from companion_ui.workspace.overlay_host import (
    DECLARED_OVERLAYS,
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    OverlayHostState,
    dismiss,
    mount,
)
from companion_ui.workspace.receipts_history import (
    GUARD_HELD_RECEIPT_STATES,
    RECEIPTS_HISTORY_FRAGMENT_ROUTE,
    RECEIPTS_HISTORY_MAX_ROWS,
    RECEIPTS_OVERLAY_ID,
    RECEIPTS_PROJECTION_ENDPOINT,
    governance_counts_row_html,
    governance_counts_view,
    receipts_history_fragment,
    receipts_history_modal_markup,
    receipts_history_unavailable_fragment,
    receipts_history_view,
)
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from companion_ui.workspace.workspace_http_client import WorkspaceClientError

# ---------------------------------------------------------------------------
# Fixtures (workspace fields mirror test_memory_review_drawer; receipt rows
# mirror the runtime projection in app/receipts/artifact_receipts.py as
# served by GET /api/companion/vault-browser notes[].receipts)
# ---------------------------------------------------------------------------


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
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
        "guard_update_flow_available": True,
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
    base.update(overrides)
    return base


def _render_workspace(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _receipt_row(idx: int = 1, **overrides: Any) -> dict[str, Any]:
    """One runtime-produced receipt projection row, verbatim shape."""
    base: dict[str, Any] = {
        "receipt_id": f"receipt-{idx}",
        "trace_id": f"trace-{idx}",
        "action_id": f"action-{idx}",
        "action_type": "panel.action.logged",
        "artifact_uuid": f"uuid-{idx}",
        "artifact_path": f"Notes/note-{idx}.md",
        "path": f"Notes/note-{idx}.md",
        "requested_by": "panel",
        "approved_by": "user",
        "status": "success",
        "timestamp": f"2026-06-10T09:{idx:02d}:00Z",
        "state": "applied",
    }
    base.update(overrides)
    return base


def _browser_payload(
    notes_receipts: list[list[dict[str, Any]] | None],
) -> dict[str, Any]:
    """A GET /api/companion/vault-browser payload with per-note receipts."""
    notes = []
    for idx, receipts in enumerate(notes_receipts, start=1):
        note: dict[str, Any] = {
            "note_path": f"Notes/note-{idx}.md",
            "title": f"Note {idx}",
            "uuid": f"uuid-{idx}",
        }
        if receipts is not None:
            note["receipts"] = receipts
        notes.append(note)
    return {"notes": notes, "read_only": True}


def _modal(html: str) -> str:
    m = re.search(
        r'<div[^>]*data-testid="receipts-history-modal".*?</div>\s*'
        r"<!-- /receipts-history-modal -->",
        html,
        re.S,
    )
    assert m, "receipts history modal must render"
    return m.group(0)


def _modal_script(html: str) -> str:
    m = re.search(
        r"/\* receipts-history-controller \*/(.*?)"
        r"/\* /receipts-history-controller \*/",
        html,
        re.S,
    )
    assert m, "receipts history controller script must render"
    return m.group(1)


def _host_script(html: str) -> str:
    m = re.search(
        r"/\* overlay-host-controller \*/(.*?)/\* /overlay-host-controller \*/",
        html,
        re.S,
    )
    assert m, "overlay-host controller script must render"
    return m.group(1)


class _FakeClient:
    """Minimal WorkspaceHttpClient stand-in recording proxy calls."""

    def __init__(
        self,
        get_responses: dict[str, Any] | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self.get_responses = get_responses or {}
        self.get_error = get_error
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        if self.get_error:
            raise self.get_error
        return self.get_responses.get(url, {})


def _drive_get(handler_cls: type, path: str) -> bytes:
    instance = handler_cls.__new__(handler_cls)
    instance.path = path
    instance.headers = {}
    chunks: list[bytes] = []
    instance.wfile = io.BytesIO()
    instance.wfile.write = chunks.append  # type: ignore[method-assign]
    instance.send_response = lambda *_: None  # type: ignore[method-assign]
    instance.send_header = lambda *_: None  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.do_GET()
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# AC1: the modal renders receipts exclusively from existing runtime receipt
# projections, with outcome, id, target, and timestamp
# ---------------------------------------------------------------------------


def test_history_renders_runtime_receipt_projections() -> None:
    # Pure projection: rows come verbatim from the runtime payload — the
    # runtime's own outcome word, id, target path, and timestamp; nothing is
    # re-derived or re-classified.
    payload = _browser_payload(
        [
            [_receipt_row(1, status="logged", state="applied")],
            [
                _receipt_row(
                    2,
                    status="blocked",
                    state="blocked",
                    action_type="panel.action.blocked",
                )
            ],
        ]
    )
    view = receipts_history_view(payload)
    assert view["source_available"] is True
    assert len(view["rows"]) == 2
    # Most recent first, ordered by the runtime-declared timestamp.
    assert [row["receipt_id"] for row in view["rows"]] == [
        "receipt-2",
        "receipt-1",
    ]
    first = view["rows"][0]
    assert first["status"] == "blocked"  # the runtime's word, verbatim
    assert first["target"] == "Notes/note-2.md"
    assert first["timestamp"] == "2026-06-10T09:02:00Z"
    assert view["rows"][1]["status"] == "logged"

    # The same receipt attached to two notes by the runtime is shown once —
    # presentation bookkeeping by the runtime's own receipt_id, not a merge.
    shared = _receipt_row(7)
    deduped = receipts_history_view(_browser_payload([[shared], [dict(shared)]]))
    assert len(deduped["rows"]) == 1

    # Bounded recent list: the surface never grows past the declared bound.
    many = [
        _receipt_row(idx, timestamp=f"2026-06-09T{idx % 24:02d}:00:00Z")
        for idx in range(1, RECEIPTS_HISTORY_MAX_ROWS + 10)
    ]
    bounded = receipts_history_view(_browser_payload([many]))
    assert len(bounded["rows"]) == RECEIPTS_HISTORY_MAX_ROWS
    assert bounded["truncated"] is True

    # Server-rendered fragment: every row carries outcome, id, target, and
    # timestamp from the runtime projection.
    fragment = receipts_history_fragment(payload)
    rows = re.findall(
        r'<li[^>]*data-testid="receipts-history-row"[^>]*>.*?</li>', fragment, re.S
    )
    assert len(rows) == 2
    assert 'data-source="vault-browser.receipts"' in fragment
    for row_html, receipt in zip(
        rows,
        [
            _receipt_row(2, status="blocked", state="blocked"),
            _receipt_row(1, status="logged", state="applied"),
        ],
    ):
        assert f'data-receipt-id="{receipt["receipt_id"]}"' in row_html
        assert receipt["status"] in row_html
        assert receipt["artifact_path"] in row_html
        assert receipt["timestamp"] in row_html

    # An out-of-contract outcome word still renders verbatim — degraded
    # honesty over invented classification.
    odd = receipts_history_fragment(
        _browser_payload([[_receipt_row(3, status="half-applied", state="queued")]])
    )
    assert "half-applied" in odd

    # Rendered shell: the modal is a shipped occupant of the overlay host,
    # reached from the topbar via the declared receipts.open intent.
    assert RECEIPTS_OVERLAY_ID == "receipts"
    assert RECEIPTS_OVERLAY_ID in DECLARED_OVERLAYS
    assert RECEIPTS_OVERLAY_ID in SHIPPED_OVERLAY_OCCUPANTS
    # CUIDR-04 (#2447): the receipts launcher is displaced off the topbar
    # (IDENTITY + Capture only). It is reachable via the System Map overlay's
    # receipts node (receipts.open), a never-clipping surface.
    assert RECEIPTS_OVERLAY_ID not in SHIPPED_TOPBAR_SURFACES
    html = _render_workspace()
    modal = _modal(html)
    assert 'data-overlay-id="receipts"' in modal
    assert 'data-authority="receipt"' in modal
    assert 'data-testid="workspace-surface-icon-receipts"' not in html, (
        "the receipts launcher must not sit on the topbar"
    )
    map_node = re.search(
        r'<button[^>]*data-surface-id="receipts"[^>]*>', html
    )
    assert map_node, "receipts must be reachable via the System Map overlay node"
    assert 'data-intent="receipts.open"' in map_node.group(0)
    script = _modal_script(html)
    assert "register('receipts'" in script
    assert RECEIPTS_HISTORY_FRAGMENT_ROUTE in script

    # Proxy wiring: the page server composes the fragment from the existing
    # runtime projection endpoint — the modal introduces no new receipt
    # source, and the runtime is queried read-only.
    assert RECEIPTS_PROJECTION_ENDPOINT == "/api/companion/vault-browser"
    client = _FakeClient(get_responses={RECEIPTS_PROJECTION_ENDPOINT: payload})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")
    body = _drive_get(handler_cls, RECEIPTS_HISTORY_FRAGMENT_ROUTE).decode("utf-8")
    assert client.get_calls == [(RECEIPTS_PROJECTION_ENDPOINT, {})]
    assert 'data-testid="receipts-history-row"' in body
    assert "receipt-2" in body

    # An unreachable runtime renders the calm unavailable state — receipts
    # are never invented to fill the gap.
    down_client = _FakeClient(get_error=WorkspaceClientError("connection refused"))
    down_handler = make_handler(client=down_client, api_base_url="http://runtime")
    down_body = _drive_get(down_handler, RECEIPTS_HISTORY_FRAGMENT_ROUTE).decode(
        "utf-8"
    )
    assert 'data-testid="receipts-history-unavailable"' in down_body
    assert 'data-testid="receipts-history-row"' not in down_body


# ---------------------------------------------------------------------------
# AC2: the surface has no write path — reads only, no receipt creation, no
# mutation affordance
# ---------------------------------------------------------------------------


def test_surface_is_strictly_read_only() -> None:
    html = _render_workspace()
    modal = _modal(html)
    script = _modal_script(html)

    # The modal shell declares itself read-only and offers exactly two
    # affordances: dismiss, and the UI-local guidance ⓘ that every shipped
    # overlay head carries (#1788, SEP-06 — presentation visibility only,
    # never a receipt action). No save, confirm, retry, edit, annotate, or
    # any other action control exists anywhere on the surface.
    assert 'data-read-only="true"' in modal
    buttons = re.findall(r"<button[^>]*>", modal)
    assert len(buttons) == 2, (
        "the receipts modal offers only dismiss and the guidance toggle"
    )
    assert 'data-intent="guidance.toggle"' in buttons[0]
    assert 'data-testid="receipts-history-close"' in buttons[1]
    for forbidden_element in ("<form", "<input", "<textarea", "<select"):
        assert forbidden_element not in modal

    # The controller performs no mutation: no non-GET fetch, no mutation
    # transport, no navigation.
    for forbidden in (
        "POST",
        "PUT",
        "DELETE",
        "PATCH",
        "XMLHttpRequest",
        "location.href",
        "location.assign",
        "location.reload",
        "history.pushState",
        "window.open",
        "form.submit",
    ):
        assert forbidden not in script, (
            f"receipts history controller must not use {forbidden}"
        )
    assert "method: 'GET'" in script

    # The fragment renders no action affordances on any row — including
    # blocked rows (no Resolve/Retry from history; history only shows).
    fragment = receipts_history_fragment(
        _browser_payload(
            [
                [
                    _receipt_row(1),
                    _receipt_row(2, status="blocked", state="blocked"),
                ]
            ]
        )
    )
    assert "<button" not in fragment
    assert "<form" not in fragment
    assert "data-api-method" not in fragment

    # The pure view only ever projects runtime-supplied rows: an absent
    # receipts source yields no rows and no invented receipt.
    view = receipts_history_view(_browser_payload([None, None]))
    assert view["source_available"] is False
    assert view["rows"] == []

    # The page server queries the existing projection endpoint read-only and
    # the modal admits no POST path of its own.
    handler_cls = make_handler(
        client=_FakeClient(), api_base_url="http://runtime"
    )
    instance = handler_cls.__new__(handler_cls)
    assert not instance._post_path_allowed(RECEIPTS_HISTORY_FRAGMENT_ROUTE)
    assert not instance._post_path_allowed(RECEIPTS_PROJECTION_ENDPOINT)


# ---------------------------------------------------------------------------
# AC3: blocked receipts render with guard posture, visually distinct from
# generic errors
# ---------------------------------------------------------------------------


def test_blocked_receipts_render_guard_posture() -> None:
    # The guard-held presentation maps only the runtime's own declared
    # blocked state — never a UI re-classification.
    assert GUARD_HELD_RECEIPT_STATES == ("blocked",)

    payload = _browser_payload(
        [
            [
                _receipt_row(
                    1,
                    status="blocked",
                    state="blocked",
                    action_type="panel.action.blocked",
                ),
                _receipt_row(2, status="failed", state="failed"),
                _receipt_row(3, status="success", state="applied"),
            ]
        ]
    )
    view = receipts_history_view(payload)
    by_id = {row["receipt_id"]: row for row in view["rows"]}
    assert by_id["receipt-1"]["guard_held"] is True
    assert by_id["receipt-2"]["guard_held"] is False
    assert by_id["receipt-3"]["guard_held"] is False

    fragment = receipts_history_fragment(payload)
    blocked_row = re.search(
        r'<li[^>]*data-receipt-id="receipt-1"[^>]*>.*?</li>', fragment, re.S
    )
    assert blocked_row, "the blocked receipt row must render"
    blocked_html = blocked_row.group(0)
    # Guard posture: a held boundary, named as such (BLOCKED_AND_STALE_STATE
    # _SPEC.md) — calm copy, nothing mutated, never a generic error.
    assert 'data-guard-held="true"' in blocked_html
    assert 'data-testid="receipts-history-guard-note"' in blocked_html
    assert "boundary held" in blocked_html
    assert "nothing was mutated" in blocked_html
    for alarm in ("error", "Error", "failure!", "alert"):
        assert alarm not in blocked_html

    # Visually distinct from a non-guard failure: the failed row carries no
    # guard posture and no guard copy.
    failed_row = re.search(
        r'<li[^>]*data-receipt-id="receipt-2"[^>]*>.*?</li>', fragment, re.S
    )
    assert failed_row
    assert 'data-guard-held="false"' in failed_row.group(0)
    assert "boundary held" not in failed_row.group(0)

    # The blocked treatment styles via the guard-held attribute in the
    # amber/staged family (spec §Visual contract), not via a destructive
    # alarm treatment.
    markup = receipts_history_modal_markup()
    assert '[data-guard-held="true"]' in markup
    assert "--amber" in markup
    assert "--destructive" not in markup


# ---------------------------------------------------------------------------
# AC4: an empty history renders an honest empty state with no manufactured
# rows
# ---------------------------------------------------------------------------


def test_empty_history_is_honest() -> None:
    # Source connected, zero receipts: honest empty state, zero rows.
    empty_payload = _browser_payload([[], []])
    view = receipts_history_view(empty_payload)
    assert view["source_available"] is True
    assert view["rows"] == []

    fragment = receipts_history_fragment(empty_payload)
    assert 'data-testid="receipts-history-empty"' in fragment
    assert 'data-row-count="0"' in fragment
    assert 'data-testid="receipts-history-row"' not in fragment
    assert "No receipts" in fragment

    # Receipt source not connected: the distinct calm unavailable state —
    # never conflated with "no receipts found", never a manufactured row.
    unavailable_payload = _browser_payload([None])
    fragment_unavailable = receipts_history_fragment(unavailable_payload)
    assert 'data-testid="receipts-history-unavailable"' in fragment_unavailable
    assert 'data-testid="receipts-history-empty"' not in fragment_unavailable
    assert 'data-testid="receipts-history-row"' not in fragment_unavailable

    # Runtime unreachable: calm, explicit, row-free.
    unreachable = receipts_history_unavailable_fragment("connection refused")
    assert 'data-testid="receipts-history-unavailable"' in unreachable
    assert 'data-tone="calm"' in unreachable
    assert "connection refused" in unreachable
    assert 'data-testid="receipts-history-row"' not in unreachable


# ---------------------------------------------------------------------------
# Regression (#2155): the history fetch guards on response.ok before reading
# and injecting the fragment body — a non-2xx HTML body must fall into the
# calm unavailable .catch branch, never be written verbatim into innerHTML.
# ---------------------------------------------------------------------------


def test_history_fetch_guards_response_ok() -> None:
    script = _modal_script(_render_workspace())

    # The loader must check response.ok before reading the body, mirroring the
    # sibling guard in vault_settings_panel.py: a non-2xx response throws and
    # is handled by the existing .catch unavailable branch.
    ok_guard = re.search(r"if\s*\(\s*!\s*\w+\.ok\s*\)\s*\{[^}]*throw", script)
    assert ok_guard, (
        "the receipts-history loader must throw on a non-ok response before "
        "reading the fragment body"
    )

    # The guard must come before the body is read and injected — an error body
    # must never reach innerHTML.
    guard_pos = ok_guard.start()
    text_pos = script.index(".text()")
    inner_pos = script.index("body.innerHTML = html")
    assert guard_pos < text_pos < inner_pos, (
        "the response-ok guard must run before r.text() and the innerHTML "
        "injection"
    )


# ---------------------------------------------------------------------------
# AC5: the modal dismisses to the anchor with no route reset
# ---------------------------------------------------------------------------


def test_dismisses_to_anchor() -> None:
    # Pure host model: mount + dismiss restores the exact anchor context —
    # URL/route, scroll ownership, staged suggestions, open-loop counts.
    before = OverlayHostState(
        anchor_note_path="Notes/note.md",
        route="/?note_path=Notes%2Fnote.md",
        scroll_owner="note-body",
        rail_state="open",
        staged_suggestion_ids=("s-1",),
        open_loop_count=3,
    )
    mounted = mount(before, "receipts")
    assert mounted.stack == ("receipts",)
    assert dismiss(mounted) == before

    # The modal offers an explicit dismiss-to-anchor control routed through
    # the host, and Esc is host-owned (one Esc owner).
    html = _render_workspace()
    modal = _modal(html)
    close = re.search(
        r'<button[^>]*data-testid="receipts-history-close"[^>]*>', modal
    )
    assert close, "the modal must offer an explicit dismiss control"
    assert 'data-intent="overlay.dismiss"' in close.group(0)
    assert "overlayHost.dismiss()" in close.group(0)
    assert "Escape" in _host_script(html)

    # The controller never navigates — dismissal hides the modal and returns
    # to the document anchor with no route reset and no data loss.
    script = _modal_script(html)
    assert "Escape" not in script
    for forbidden in (
        "location.href",
        "location.assign",
        "location.reload",
        "history.pushState",
        "window.open",
    ):
        assert forbidden not in script, f"modal must not call {forbidden}"


# ---------------------------------------------------------------------------
# AC1–AC5 (#2246): governance counts row — read-only projection in receipts modal
# ---------------------------------------------------------------------------


def test_governance_counts_render_as_read_only_projection() -> None:
    """AC1–AC5 (#2246): governance counts row on receipts surface.

    Verify:
    - Counts row renders with data-region="governance-counts" and
      data-authority="read-only-projection" when payload supplies governance.*
    - Omitted when payload absent or all counts zero (no zero-state)
    - No mutation affordance (no confirm/reject/execute button)
    """
    # AC1: row renders with correct data attributes when governance data present.
    governance_with_counts = {
        "pending_proposal_count": 3,
        "pending_receipt_count": 1,
        "latest_receipt_outcome": "logged",
    }
    html = governance_counts_row_html(governance_with_counts)
    assert html != ""
    assert 'data-region="governance-counts"' in html
    assert 'data-authority="read-only-projection"' in html
    assert 'data-read-only="true"' in html
    assert 'data-testid="governance-counts-row"' in html
    # Counts are present verbatim.
    assert "3" in html  # pending proposals
    assert "1" in html  # pending receipts
    assert "logged" in html  # latest outcome

    # AC2: row omitted when all counts zero and outcome absent.
    assert governance_counts_view(None) is None
    assert governance_counts_row_html(None) == ""
    assert governance_counts_view({}) is None
    assert governance_counts_row_html({}) == ""

    all_zero = {
        "pending_proposal_count": 0,
        "pending_receipt_count": 0,
        "latest_receipt_outcome": "none",
    }
    assert governance_counts_view(all_zero) is None
    assert governance_counts_row_html(all_zero) == ""

    unknown_outcome = {
        "pending_proposal_count": 0,
        "pending_receipt_count": 0,
        "latest_receipt_outcome": "unknown",
    }
    assert governance_counts_view(unknown_outcome) is None
    assert governance_counts_row_html(unknown_outcome) == ""

    # Partial counts still render (non-zero field present).
    partial = {"pending_proposal_count": 2, "pending_receipt_count": 0}
    partial_html = governance_counts_row_html(partial)
    assert partial_html != ""
    assert "2" in partial_html
    assert 'data-authority="read-only-projection"' in partial_html

    # Meaningful outcome alone triggers render (zero counts + real outcome).
    outcome_only = {
        "pending_proposal_count": 0,
        "pending_receipt_count": 0,
        "latest_receipt_outcome": "logged",
    }
    outcome_html = governance_counts_row_html(outcome_only)
    assert outcome_html != ""
    assert "logged" in outcome_html

    # AC3: no mutation affordance — no confirm/reject/execute control.
    assert "<button" not in html
    assert "<form" not in html
    assert "<input" not in html
    assert "confirm" not in html.lower()
    assert "reject" not in html.lower()
    assert "execute" not in html.lower()

    # Pure view projection contract.
    view = governance_counts_view(governance_with_counts)
    assert view is not None
    assert view["proposals"] == 3
    assert view["receipts"] == 1
    assert view["outcome"] == "logged"

    # Coercion: string counts work.
    str_counts = {"pending_proposal_count": "5", "pending_receipt_count": "0"}
    str_view = governance_counts_view(str_counts)
    assert str_view is not None
    assert str_view["proposals"] == 5
