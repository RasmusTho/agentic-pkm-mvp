"""⌘N capture modal — the UI half of capture-to-vault-inbox (SEP-08b, #1791).

The capture surface is friction-free intake of "things I need to take care
of" as a commitment to future-self appended to the vault inbox — never an
app-owned task (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q17,
`docs/SYSTEM_ENTRY_POINT/CAPTURE_TO_VAULT_INBOX.md`, issue (b)):

- `⌘N` / `capture.open` mounts a top modal on the shared overlay host
  (#1785): a textarea (`data-region="capture-input"`), a "Capture to inbox"
  action (`capture.save`), and a session-capture list;
- a write is claimed only on the runtime acknowledgement from the shipped
  endpoint (`POST /api/companion/capture`, #1790) — the UI performs no
  direct vault I/O and never fabricates an acknowledgement;
- offline honesty: with the runtime unreachable the composer stays usable,
  each unwritten capture is plainly labeled not-yet-written, and text is
  never silently dropped;
- dismissal returns to the document anchor with unsent text preserved for
  the session;
- no due-date field and no app task states anywhere on the surface.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

import pytest

from companion_ui.workspace.capture_modal import (
    CAPTURE_ENDPOINT,
    CAPTURE_OVERLAY_ID,
    CAPTURE_STATES,
    NOT_YET_WRITTEN,
    WRITTEN,
    WRITTEN_UNACKNOWLEDGED,
    CaptureAck,
    CaptureSessionState,
    SessionCapture,
    dismiss_modal,
    edit_draft,
    submit_draft,
)
from companion_ui.workspace.overlay_host import (
    KEYBOARD_MAP,
    SHIPPED_OVERLAY_OCCUPANTS,
    OverlayHostState,
    apply_intent,
    dismiss as host_dismiss,
    keyboard_intent,
    mount,
)
from companion_ui.workspace.serve_dev_page import make_handler, render_index_html

# ---------------------------------------------------------------------------
# Fixtures (mirror the proven workspace fixture in test_overlay_host)
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


def _render(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _host_state(**overrides: Any) -> OverlayHostState:
    base: dict[str, Any] = {
        "anchor_note_path": "Notes/note.md",
        "route": "/?note_path=Notes%2Fnote.md",
        "scroll_owner": "note-body",
        "rail_state": "open",
        "staged_suggestion_ids": ("s-1", "s-2"),
        "open_loop_count": 3,
        "stack": (),
    }
    base.update(overrides)
    return OverlayHostState(**base)


def _modal(html: str) -> str:
    m = re.search(
        r'<div[^>]*data-region="capture-modal".*?</div>\s*<!-- /capture-modal -->',
        html,
        re.S,
    )
    assert m, "capture modal (data-region=capture-modal) must render"
    return m.group(0)


def _script(html: str) -> str:
    m = re.search(
        r"/\* capture-modal-controller \*/(.*?)/\* /capture-modal-controller \*/",
        html,
        re.S,
    )
    assert m, "capture-modal controller script must render"
    return m.group(1)


def _ack(**overrides: Any) -> CaptureAck:
    base: dict[str, Any] = {
        "note_path": "00-intake/inbox.md",
        "operation": "append",
        "adapter": "filesystem",
        "captured_at": "2026-06-10T08:00:00Z",
        "trace_id": "trace-cap-1",
    }
    base.update(overrides)
    return CaptureAck(**base)


class _ProxyClient:
    def __init__(self, *, post_result: dict[str, Any] | None = None) -> None:
        self.post_result = post_result if post_result is not None else {"ok": True}
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        self.post_calls.append((url, json))
        return self.post_result


class _CapturingPostHandler:
    """Drive make_handler().do_POST without binding a socket."""

    def __init__(self, handler_cls: type, path: str, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self._instance = handler_cls.__new__(handler_cls)
        self._instance.path = path
        self._instance.rfile = io.BytesIO(raw)
        self._instance.wfile = io.BytesIO()
        self._instance.headers = {"Content-Length": str(len(raw))}
        self.status_code: int | None = None
        self.payload: dict[str, Any] | None = None

        def _send_json(status_code: int, payload: dict[str, Any]) -> None:
            self.status_code = status_code
            self.payload = payload

        self._instance._send_json = _send_json  # type: ignore[method-assign]

    def run_post(self) -> None:
        self._instance.do_POST()


# ---------------------------------------------------------------------------
# AC1: ⌘N opens the modal; a successful capture appears in the session list
# as written, with the runtime acknowledgement reference
# ---------------------------------------------------------------------------


def test_capture_save_shows_written_state_from_runtime_ack() -> None:
    # ⌘N routes to capture.open, and the capture overlay is now a shipped
    # occupant of the host: the intent mounts the modal (no longer inert).
    assert KEYBOARD_MAP["meta+n"] == "capture.open"
    assert keyboard_intent("meta+n") == "capture.open"
    assert CAPTURE_OVERLAY_ID == "capture"
    assert CAPTURE_OVERLAY_ID in SHIPPED_OVERLAY_OCCUPANTS
    opened = apply_intent(_host_state(), "capture.open")
    assert opened.stack == ("capture",)

    # Pure session model: a save acknowledged by the runtime appears in the
    # session list as written, carrying the acknowledgement reference, and
    # the composer clears for the next thought.
    state = edit_draft(CaptureSessionState(), "call the dentist about invoice")
    ack = _ack()
    after = submit_draft(state, ack=ack)
    assert len(after.captures) == 1
    capture = after.captures[0]
    assert capture.state == WRITTEN
    assert capture.text == "call the dentist about invoice"
    assert capture.ack == ack
    assert capture.ack.note_path == "00-intake/inbox.md"
    assert capture.ack.trace_id == "trace-cap-1"
    assert after.draft == ""

    # A write can never be claimed without a runtime acknowledgement: the
    # written state is unconstructable ack-less, by construction.
    assert CAPTURE_STATES == (WRITTEN, WRITTEN_UNACKNOWLEDGED, NOT_YET_WRITTEN)
    with pytest.raises(ValueError):
        SessionCapture(text="ghost write", state=WRITTEN, ack=None)
    pending = SessionCapture(
        text="vault write happened but acknowledgement failed",
        state=WRITTEN_UNACKNOWLEDGED,
        ack=None,
    )
    assert pending.state == WRITTEN_UNACKNOWLEDGED

    # Rendered surface: the modal, its declared regions, and the save action.
    html = _render()
    modal = _modal(html)
    assert 'data-region="capture-input"' in modal
    assert re.search(r'<textarea[^>]*data-region="capture-input"', modal)
    assert "Capture to inbox" in modal
    assert 'data-intent="capture.save"' in modal
    assert 'data-region="capture-session-list"' in modal

    # The controller registers the capture occupant on the shared host and
    # posts to the shipped governed endpoint — no direct vault I/O.
    script = _script(html)
    assert "overlayHost.register('capture'" in script
    assert CAPTURE_ENDPOINT == "/api/companion/capture"
    assert "'/api/companion/capture'" in script
    # The written claim is made only from the runtime acknowledgement payload
    # (resp.ok branch); the entry carries the acknowledgement reference.
    assert "resp.ok" in script
    assert "data-capture-state" in script
    assert "data-ack-note-path" in script
    assert "data-ack-trace-id" in script

    # No task-manager posture anywhere on the surface: no due-date field, no
    # task states, no reminders (spec §Resolved Q17).
    lowered = modal.lower()
    for forbidden in (
        'type="date"',
        'type="datetime',
        'type="checkbox"',
        "due",
        "deadline",
        "remind",
        "recurring",
    ):
        assert forbidden not in lowered, (
            f"capture surface must not carry task affordance {forbidden!r}"
        )


def test_capture_modal_posts_through_companion_capture_proxy() -> None:
    client = _ProxyClient(
        post_result={
            "note_path": "00-intake/inbox.md",
            "operation": "append",
            "adapter": "filesystem",
            "captured_at": "2026-06-10T08:00:00Z",
            "trace_id": "trace-cap-1",
        }
    )
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    driver = _CapturingPostHandler(
        handler_cls,
        "/api/companion/capture",
        {"text": "book dentist appointment"},
    )

    driver.run_post()

    assert client.post_calls == [
        ("/api/companion/capture", {"text": "book dentist appointment"})
    ]
    assert driver.status_code == 200
    assert driver.payload == {
        "note_path": "00-intake/inbox.md",
        "operation": "append",
        "adapter": "filesystem",
        "captured_at": "2026-06-10T08:00:00Z",
        "trace_id": "trace-cap-1",
    }


def test_capture_modal_success_path_records_written_result() -> None:
    state = edit_draft(CaptureSessionState(), "book dentist appointment")

    after = submit_draft(state, ack=_ack(trace_id="trace-cap-written"))

    assert len(after.captures) == 1
    assert after.captures[0].state == WRITTEN
    assert after.captures[0].ack is not None
    assert after.captures[0].ack.trace_id == "trace-cap-written"
    assert after.draft == ""


def test_capture_modal_distinguishes_written_but_unacknowledged_response() -> None:
    pending = SessionCapture(
        text="already in vault, acknowledgement pending",
        state=WRITTEN_UNACKNOWLEDGED,
        ack=None,
    )
    assert pending.state == WRITTEN_UNACKNOWLEDGED
    with pytest.raises(ValueError):
        SessionCapture(
            text="ack reference would be fabricated",
            state=WRITTEN_UNACKNOWLEDGED,
            ack=_ack(),
        )

    script = _script(_render())
    assert "onWrittenUnacknowledged" in script
    assert "detail.state === 'not_acknowledged'" in script
    assert "addEntry(text, 'written_unacknowledged', null)" in script
    assert "written \\u00b7 acknowledgement pending" in script


def test_capture_proxy_allows_companion_capture_path() -> None:
    client = _ProxyClient()
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    driver = _CapturingPostHandler(
        handler_cls,
        "/api/companion/capture",
        {"text": "proxy reaches runtime"},
    )

    driver.run_post()

    assert driver.status_code == 200
    assert client.post_calls == [
        ("/api/companion/capture", {"text": "proxy reaches runtime"})
    ]


# ---------------------------------------------------------------------------
# AC2: with the runtime unreachable the composer stays usable and unwritten
# captures are labeled not-yet-written; no text dropped, no write claimed
# ---------------------------------------------------------------------------


def test_offline_capture_is_honest_and_preserves_text() -> None:
    # Pure session model: a save without runtime acknowledgement records the
    # capture as not-yet-written with its text preserved verbatim.
    state = edit_draft(CaptureSessionState(), "fragile thought, offline")
    after = submit_draft(state, ack=None)
    assert len(after.captures) == 1
    assert after.captures[0].state == NOT_YET_WRITTEN
    assert after.captures[0].text == "fragile thought, offline"
    assert after.captures[0].ack is None

    # The composer stays usable: further captures accumulate while offline,
    # and no earlier text is dropped.
    again = submit_draft(edit_draft(after, "second thought, still offline"), ack=None)
    assert [c.text for c in again.captures] == [
        "fragile thought, offline",
        "second thought, still offline",
    ]
    assert all(c.state == NOT_YET_WRITTEN for c in again.captures)

    # No write is claimed: a not-yet-written capture cannot carry a fabricated
    # acknowledgement reference.
    assert not any(c.state == WRITTEN for c in again.captures)
    with pytest.raises(ValueError):
        SessionCapture(text="x", state=NOT_YET_WRITTEN, ack=_ack())

    # Whitespace-only drafts are a no-op, mirroring the endpoint's explicit
    # empty-capture rejection — nothing fake enters the session list.
    blank = submit_draft(edit_draft(CaptureSessionState(), "   \n  "), ack=None)
    assert blank.captures == ()

    # Rendered controller: the unreachable path (fetch rejection) and every
    # non-acknowledged response route to the same honest not-yet-written
    # labeling; no acknowledgement object is fabricated offline.
    html = _render()
    script = _script(html)
    assert ".catch(" in script
    assert "not_yet_written" in script
    assert "not yet written" in script  # the plain user-facing label
    assert "ack.state === 'vault_selection_required'" in script
    assert "No vault is selected. Open a vault before capturing." in script
    # The not-yet-written entry is recorded with a null acknowledgement —
    # the offline path never builds one.
    assert "addEntry(text, 'not_yet_written', null)" in script
    # The composer is never disabled by a failed write: the controller never
    # toggles the textarea's disabled state.
    assert "disabled" not in script
    # The captured text always lands in the session list via textContent —
    # visible, intact, never silently dropped.
    assert "textContent = text" in script


# ---------------------------------------------------------------------------
# AC3: the modal dismisses to the anchor with unsent text preserved
# ---------------------------------------------------------------------------


def test_dismiss_preserves_unsent_text() -> None:
    # Pure session model: dismissal does not touch the session state — the
    # unsent draft and the session captures survive for the session.
    state = CaptureSessionState(
        draft="half-formed thought not yet saved",
        captures=(
            SessionCapture(text="already offline", state=NOT_YET_WRITTEN, ack=None),
        ),
    )
    assert dismiss_modal(state) == state
    assert dismiss_modal(state).draft == "half-formed thought not yet saved"

    # Host grammar: dismissing the capture overlay returns to the document
    # anchor with no route reset and no data loss (#1785 dismiss rule).
    before = _host_state()
    mounted = mount(before, CAPTURE_OVERLAY_ID)
    assert mounted.stack == ("capture",)
    dismissed = host_dismiss(mounted)
    assert dismissed == before
    assert dismissed.anchor_note_path == before.anchor_note_path
    assert dismissed.route == before.route

    # Rendered controller: the close path only hides the modal — it never
    # touches the textarea value or the session list, so unsent text and
    # session captures are preserved for the session.
    html = _render()
    script = _script(html)
    close_body = re.search(r"close: function\(\) \{(.*?)\n\s*\},", script, re.S)
    assert close_body, "controller must expose its close path"
    assert "hidden" in close_body.group(1)
    assert ".value" not in close_body.group(1)
    assert "innerHTML" not in close_body.group(1)
    assert "removeChild" not in close_body.group(1)
    # Dismissal routes through the shared host (Esc / scrim / close button),
    # keeping one dismiss owner; the modal close affordance uses the host.
    modal = _modal(html)
    assert "overlayHost.dismiss()" in modal
    # The controller performs no navigation on dismissal — no route reset.
    for forbidden in ("location.href", "location.assign", "location.reload",
                      "history.pushState", "window.open"):
        assert forbidden not in script


# ---------------------------------------------------------------------------
# AC (#2172): inline capture field renders on cold_start / suppressed no_vault
# ---------------------------------------------------------------------------


def _cold_start_orientation(*, leave_status: str = "absent") -> dict:
    """Minimal orientation payload for the given leave_point status."""
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-20T10:00:00Z",
            "trace_id": "trace-cold",
            "freshness": "fresh",
            "stale_after": "2026-06-20T10:05:00Z",
            "degraded_reasons": [],
        },
        "leave_point": {"status": leave_status} if leave_status else None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "healthy",
            "degraded": False,
            "reasons": [],
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "mutation_intents": [],
    }


def _render_cold_start() -> str:
    """Render the orientation page with a cold_start (absent leave_point)."""
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_cold_start_orientation(leave_status="absent"),
    )


def _render_no_vault() -> str:
    """Render the orientation page as no_vault via an error orientation."""
    from companion_ui.workspace.entry_state import EntryStateResolution
    from companion_ui.workspace.serve_dev_page import _render_orientation_index_html  # type: ignore[attr-defined]

    orientation = _cold_start_orientation(leave_status="absent")
    entry_resolution = EntryStateResolution(state="no_vault")
    return _render_orientation_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        orientation=orientation,
        entry_resolution=entry_resolution,
    )


def test_entry_capture_field_renders_on_cold_start_and_suppresses_on_no_vault() -> None:
    """Inline capture field renders on cold_start; suppressed on no_vault.

    Design item 4 (implementation-contracts.md): an unadorned input line
    "Leave a note for future-you…" that on focus / ⌘N mounts the shipped
    governed capture occupant verbatim.

    Suppressed on no_vault: capture has no honest landing for an offline write
    at boot (SYSTEM_ENTRY_POINT_SPEC.md §Resolved Q17: "never claim a write it
    cannot back").
    """
    # cold_start: the inline capture field and the modal occupant both render.
    cold = _render_cold_start()
    assert 'data-entry-state="cold_start"' in cold

    # The inline capture field renders inside the cold-start-threshold region.
    assert 'data-region="cold-start-threshold"' in cold
    assert 'data-region="cold-start-capture"' in cold
    assert 'data-testid="cold-start-capture-input"' in cold
    assert "Leave a note for future-you" in cold

    # On focus the field mounts the capture occupant (never opens inline editor).
    assert "overlayHost.mount('capture')" in cold

    # The capture modal occupant ships with the cold_start substrate.
    assert 'data-region="capture-modal"' in cold
    assert "overlayHost.register('capture'" in cold

    # no_vault: the inline capture field is suppressed.
    no_vault = _render_no_vault()
    assert 'data-entry-state="no_vault"' in no_vault
    assert 'data-region="cold-start-capture"' not in no_vault
    assert 'data-testid="cold-start-capture-input"' not in no_vault
    # The capture modal markup / script are also suppressed on no_vault
    # (no honest landing for an offline write at boot).
    assert 'data-region="capture-modal"' not in no_vault
    assert "overlayHost.register('capture'" not in no_vault


def test_entry_capture_preserves_unsent_text_without_claiming_write() -> None:
    """Offline/unsent capture text is preserved; no write is claimed.

    The inline capture field on cold_start opens the shipped capture occupant
    via overlayHost.mount('capture'): dismissal routes through the overlay host
    back to the anchor with unsent text preserved, no route reset.
    A write is claimed ONLY on the runtime WriteReceipt.
    """
    # Pure model: dismissal preserves draft and session captures (unchanged
    # contract from the workspace-shell modal, now also valid on entry surface).
    state = CaptureSessionState(
        draft="idea for future-me",
        captures=(
            SessionCapture(text="earlier offline", state=NOT_YET_WRITTEN, ack=None),
        ),
    )
    assert dismiss_modal(state) is state
    assert dismiss_modal(state).draft == "idea for future-me"
    # No write is claimed from the draft alone.
    assert not any(c.state == WRITTEN for c in state.captures)

    # The rendered cold_start substrate does not claim a write client-side:
    # the inline field routes to overlayHost.mount('capture') and the modal
    # controller's save path requires a runtime acknowledgement.
    cold = _render_cold_start()

    # Inline field routes through the host; no inline save button on the field.
    cold_start_capture = re.search(
        r'data-region="cold-start-capture"(.*?)(?=<div|<p\s|</div)', cold, re.S
    )
    assert cold_start_capture, "cold-start-capture region must render"
    capture_block = cold_start_capture.group(1)
    # The inline field triggers host mount on focus — no inline form post.
    assert "overlayHost.mount('capture')" in capture_block
    assert "capture.save" not in capture_block
    assert "/api/companion/capture" not in capture_block

    # The modal controller (running after mount) is what owns the governed
    # write path: save requires a runtime acknowledgement.
    script_m = re.search(
        r"/\* capture-modal-controller \*/(.*?)/\* /capture-modal-controller \*/",
        cold,
        re.S,
    )
    assert script_m, "capture-modal-controller must render on cold_start"
    script = script_m.group(1)
    # A write is claimed only from a real runtime acknowledgement path; 200
    # picker payloads are not acknowledged writes.
    assert "resp.ok" in script
    assert "ack.state === 'vault_selection_required'" in script
    # Unsent text is never silently dropped: the not-yet-written path preserves
    # the full text in the session list.
    assert "not_yet_written" in script
    assert "textContent = text" in script
    # Dismissal never navigates (no route reset).
    for forbidden in ("location.href", "location.assign", "location.reload",
                      "history.pushState"):
        assert forbidden not in script
