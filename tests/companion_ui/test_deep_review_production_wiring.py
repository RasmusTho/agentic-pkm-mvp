"""Production-path regressions for the original #2443 Resume and Apply seams."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from html.parser import HTMLParser
import json
import os
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from tests.companion_ui.test_overlay_host import _fields


@contextmanager
def _served_html(html: str) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/" and not self.path.startswith("/?"):
                self.send_response(404)
                self.end_headers()
                return
            body = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_governed_proposal_projection_and_apply_use_existing_guarded_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, product_model_access_gateway: Any,
) -> None:
    from fastapi.testclient import TestClient
    from tests.api._vault_test_helpers import bind_initialized_vault
    import app.api.routes.companion as companion
    import app.panel.confirmation as confirmation
    from app.api.app import app
    from app.write_guard import WritesBlockedError
    from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
    from companion_ui.workspace.serve_dev_page import render_index_html
    from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError

    vault = tmp_path / "synthetic-vault"
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, channel="test")
    note = vault / "note.md"
    note.write_text("---\nuuid: 11111111-1111-4111-8111-111111111111\ntitle: Synthetic\n---\n# Synthetic\n\nBody.\n")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave.sqlite3"))
    store = confirmation.ProposalStore(tmp_path / "panel.sqlite3")
    idempotency = confirmation.ConfirmIdempotencyStore(tmp_path / "panel.sqlite3")
    monkeypatch.setattr(confirmation, "_proposal_store", store)
    monkeypatch.setattr(confirmation, "_idempotency_store", idempotency)
    monkeypatch.setattr(confirmation, "_service", confirmation.PanelConfirmationService(store, idempotency))
    api = TestClient(app)
    queued = api.post("/api/companion/vault-browser/actions/queue-review", json={"note_path": "note.md"})
    assert queued.status_code == 200
    proposal_id = queued.json()["proposal_id"]
    state = api.get("/api/companion/workspace", params={"note_path": "note.md"}).json()
    proposals = state["panel"]["proposals"]
    assert len(proposals) == 1 and proposals[0]["proposal_id"] == proposal_id
    assert proposals[0]["artifact_id"] == state["artifact"]["artifact_id"]

    body = {"proposal_id": proposal_id, "artifact_id": state["artifact"]["artifact_id"], "action": "confirm", "idempotency_key": "synthetic-confirm"}
    # The real same-turn boundary still refuses the first immediate Apply.
    early = api.post("/api/panel/confirm", json=body)
    assert early.status_code == 422 and store.get(proposal_id) is not None
    # Advance this isolated test clock; preserve the staged proposal timestamp
    # and exercise the same production guard instead of backdating the row.
    later = confirmation.time.time() + 6
    monkeypatch.setattr(confirmation.time, "time", lambda: later)
    original = companion.DEFAULT_WRITE_GUARD.assert_writes_allowed

    def blocked(action: str) -> None:
        raise WritesBlockedError(state="safe_mode", reason="synthetic lock", action=action)

    monkeypatch.setattr(companion.DEFAULT_WRITE_GUARD, "assert_writes_allowed", blocked)
    blocked_ack = api.post("/api/panel/confirm", json=body)
    assert blocked_ack.status_code == 200 and blocked_ack.json()["status"] == "blocked"
    assert blocked_ack.json()["receipt"] is None
    assert store.get(proposal_id) is not None
    monkeypatch.setattr(companion.DEFAULT_WRITE_GUARD, "assert_writes_allowed", original)
    reopened = api.get("/api/companion/workspace", params={"note_path": "note.md"}).json()
    assert reopened["panel"]["proposals"][0]["status"] == "staged"
    assert reopened["panel"]["last_response"]["status"] == "blocked"
    body["idempotency_key"] = "synthetic-confirm-after-guard"
    applied = api.post("/api/panel/confirm", json=body)
    assert applied.status_code == 200
    ack = applied.json()
    # This normal queue-review producer found no action. Its actual durable
    # decision is recorded; an event alone cannot establish execution.
    assert ack["status"] == "logged", ack
    assert ack["outcome"] == ack["receipt"]["outcome"] == "logged"
    assert ack["receipt"]["receipt_id"]
    assert api.post("/api/panel/confirm", json=body).json() == ack
    assert confirmation.ConfirmIdempotencyStore(tmp_path / "panel.sqlite3").get(body["idempotency_key"]).model_dump(mode="json") == ack
    assert store.get(proposal_id) is None

    class Client:
        def get(self, path: str, *, params: dict | None = None) -> dict:
            response = api.get(path, params=params)
            if response.status_code >= 400:
                raise WorkspaceClientHTTPError(response.status_code, response.text)
            return response.json()

    page = RealNoteWorkspaceDevPage(Client())
    page.load(NoteLoadIntent(note_path="note.md"))
    fields = page.render_fields()
    assert fields["panel_last_response"] == ack
    rendered = render_index_html(api_base_url="http://127.0.0.1:18002", note_path="note.md", fields=fields)
    assert 'data-testid="workspace-panel-receipt"' in rendered
    assert 'data-testid="workspace-panel-receipt-card"' not in rendered
    assert 'data-receipt-state="applied"' not in rendered
    assert f'data-receipt-id="{ack["receipt"]["receipt_id"]}"' in rendered
    class Elements(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.testids: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if value := dict(attrs).get("data-testid"):
                self.testids.append(value)

    elements = Elements()
    elements.feed(rendered)
    assert "workspace-panel-proposal-row" not in elements.testids
    assert 'window.panelActions.submit(button)' in rendered
    assert "response.getAttribute('data-proposal-id') !== id" in rendered
    assert "return window.panelActions.submit(btn)" in rendered
    outbox = [json.loads(line) for line in (tmp_path / "outbox.jsonl").read_text().splitlines()]
    assert any(row.get("event_id") == ack["receipt"]["receipt_id"] for row in outbox)


@pytest.mark.parametrize("case", ["empty", "intent_event_only", "logged", "unchecked_trigger", "triggered"])
def test_panel_confirmation_requires_actual_triggered_action_for_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str,
) -> None:
    """Typed-result classification proof; it is not a live execution claim."""
    from fastapi.testclient import TestClient
    from tests.api._vault_test_helpers import bind_initialized_vault
    import app.panel.confirmation as confirmation
    from app.agents.panel_agent.runtime import PanelRuntimeResult
    from app.api.app import app
    from app.events.panel import PanelRuntimeActionResult
    from companion_ui.workspace.serve_dev_page import _render_panel_confirm_response

    vault = tmp_path / "synthetic-vault"
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, channel="test")
    (vault / "note.md").write_text("---\nuuid: 11111111-1111-4111-8111-111111111111\n---\n# Synthetic\n")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave.sqlite3"))
    store = confirmation.ProposalStore(tmp_path / "panel.sqlite3")
    idem = confirmation.ConfirmIdempotencyStore(tmp_path / "panel.sqlite3")
    monkeypatch.setattr(confirmation, "_proposal_store", store)
    monkeypatch.setattr(confirmation, "_idempotency_store", idem)
    monkeypatch.setattr(confirmation, "_service", confirmation.PanelConfirmationService(store, idem))
    api = TestClient(app)
    queued = api.post("/api/companion/vault-browser/actions/queue-review", json={"note_path": "note.md"})
    assert queued.status_code == 200
    proposal_id = queued.json()["proposal_id"]
    artifact_id = store.get(proposal_id).artifact_id
    later = confirmation.time.time() + 6
    monkeypatch.setattr(confirmation.time, "time", lambda: later)
    calls = []

    def execute(intent: Any) -> PanelRuntimeResult:
        calls.append(intent)
        actions = []
        if case in {"logged", "unchecked_trigger", "triggered"}:
            actions = [PanelRuntimeActionResult(
                id="classification-fixture", label="Declared runtime result",
                checked=case != "unchecked_trigger",
                status="logged" if case == "logged" else "triggered",
            )]
        # An intent-executed event proves the graph ran, not an action triggered.
        events = [SimpleNamespace(event="panel.intent.executed")] if case == "intent_event_only" else []
        return PanelRuntimeResult(intent=intent, actions=actions, emitted_events=events)

    monkeypatch.setattr(confirmation, "execute_panel_intent", execute)
    request = {"proposal_id": proposal_id, "artifact_id": artifact_id, "action": "confirm", "idempotency_key": f"classification-{case}"}
    response = api.post("/api/panel/confirm", json=request)
    assert response.status_code == 200
    ack = response.json()
    expected_status, expected_outcome = ("executed", "success") if case == "triggered" else ("logged", "logged")
    assert (ack["status"], ack["outcome"], ack["receipt"]["outcome"]) == (expected_status, expected_outcome, expected_outcome)
    assert confirmation.ConfirmIdempotencyStore(tmp_path / "panel.sqlite3").get(request["idempotency_key"]).model_dump(mode="json") == ack
    assert api.post("/api/panel/confirm", json=request).json() == ack and len(calls) == 1
    records = [json.loads(line) for line in (tmp_path / "outbox.jsonl").read_text().splitlines()]
    assert any(event.get("event_id") == ack["receipt"]["receipt_id"] for event in records)
    html = _render_panel_confirm_response(ack)
    assert ('data-receipt-state="applied"' in html) is (case == "triggered")


@pytest.mark.parametrize("case", ["escape", "back", "replace", "disconnected", "stale"])
def test_overlay_frame_returns_to_original_focus_and_selection(case: str) -> None:
    if os.environ.get("COMPANION_UI_BROWSER_TESTS") != "1":
        pytest.skip("explicit offline browser QA only; this is not live acceptance")
    from playwright.sync_api import sync_playwright
    from companion_ui.workspace.serve_dev_page import render_index_html
    from tests.companion_ui.browser_runtime_harness import install_offline_esm_routes
    from tests.companion_ui.test_overlay_history_browser import _launch

    fields = _fields(body="# Synthetic note\n\n" + "\n".join(f"Synthetic line {i}." for i in range(100)))
    html = render_index_html(api_base_url="http://127.0.0.1:18002", note_path=fields["note_path"], fields=fields)
    with _served_html(html) as url, sync_playwright() as playwright:
        browser = _launch(playwright)
        try:
            page = browser.new_page()
            # Only this local fixture server and fulfilled offline ESM modules
            # are reachable. The rendered API origin is never contacted.
            page.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url) else route.abort("blockedbyclient"))
            install_offline_esm_routes(page.context)
            page.goto(url, wait_until="domcontentloaded")
            page.locator('[data-testid="workspace-note-utility-edit"]:visible').first.click()
            editor = page.locator('[data-testid="workspace-note-source-editor"]:visible').first
            editor.focus()
            editor.evaluate("e => {e.style.height='48px';e.style.minHeight='0';e.style.maxHeight='48px';e.setSelectionRange(3,8,'backward');e.scrollTop=120;}")
            before = editor.evaluate("e=>({selection:[e.selectionStart,e.selectionEnd,e.selectionDirection],scroll:e.scrollTop})")
            assert before["scroll"] > 0
            page.keyboard.press("Control+k")
            page.get_by_test_id("panel-palette").wait_for(state="visible")
            page.get_by_test_id("panel-palette").evaluate("root => {const controls=Array.from(root.querySelectorAll('button:not([disabled]),input:not([disabled]),a[href],[tabindex]')).filter(e=>e.offsetParent!==null);controls[controls.length-1].focus();}")
            for key in ("Tab", "Shift+Tab"):
                page.keyboard.press(key)
                assert page.get_by_test_id("panel-palette").evaluate("root=>root.contains(document.activeElement)")
            if case == "replace":
                page.evaluate("window.overlayHost.replace('map')")
                page.get_by_test_id("system-map-overlay").wait_for(state="visible")
            elif case == "disconnected":
                editor.evaluate("e => e.replaceWith(e.cloneNode(true))")
            elif case == "stale":
                editor.evaluate("e => e.setAttribute('data-content-hash','new-source-generation')")
            if case == "back":
                page.go_back()
            else:
                page.keyboard.press("Escape")
            page.get_by_test_id("panel-palette").wait_for(state="hidden")
            if case in {"disconnected", "stale"}:
                assert not editor.evaluate("e=>e===document.activeElement")
            else:
                assert editor.evaluate("e=>e===document.activeElement")
                assert editor.evaluate("e=>[e.selectionStart,e.selectionEnd,e.selectionDirection]") == before["selection"]
                assert editor.evaluate("e=>e.scrollTop") == before["scroll"]
        finally:
            browser.close()


def _view_fields(**changes: Any) -> dict[str, Any]:
    return _fields(
        artifact_id="11111111-1111-4111-8111-111111111111", runtime_vault_id="synthetic-vault-id", runtime_local_instance_id="synthetic-local-clone",
        runtime_vault_name="Synthetic", runtime_vault_channel="test", runtime_vault_provenance="selected",
        content_hash="current-source-hash", resume_view_requested=True, resume_view_admitted=True,
        **changes,
    )


def _orientation(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": {"vault_id": fields["runtime_vault_name"], "channel": fields["runtime_vault_channel"]},
        "leave_point": {"status": "present", "artifact_ref": {"artifact_uuid": fields["artifact_id"], "logical_ref": fields["note_path"]}},
    }


def _cached_view(fields: dict[str, Any]) -> dict[str, Any]:
    import time
    return {
        **{key: fields["runtime_vault_id" if key == "vault_id" else "runtime_local_instance_id" if key == "local_instance_id" else "runtime_vault_channel" if key == "channel" else key] for key in ("vault_id", "local_instance_id", "channel", "artifact_id", "note_path", "content_hash")},
        "version": 1, "captured_at": int(time.time() * 1000), "mode": "edit",
        "start": 2, "end": 7, "editor_scroll": 20, "reading_scroll": 40,
    }


def _view_outcome(fields: dict[str, Any], cache: dict[str, Any] | None) -> dict[str, Any]:
    import subprocess
    from companion_ui.workspace.serve_dev_page import _note_view_position_script
    script = _note_view_position_script(fields).split("<script>", 1)[1].split("</script>", 1)[0]
    setup = """
var stored = CACHED;
var column = {scrollTop: 0, addEventListener: function() {}};
var editor = {value: '0123456789', defaultValue: '0123456789', hidden: true,
  selectionStart: 0, selectionEnd: 0, scrollTop: 0,
  closest: function() {return column;}, addEventListener: function() {},
  setSelectionRange: function(start,end) {this.selectionStart=start;this.selectionEnd=end;}};
global.document = {getElementById: function() {return editor;}, body: {dataset: {}}, addEventListener: function() {}};
global.window = {sessionStorage: {getItem: function() {return stored;}, setItem: function(k,v) {stored=v;}, removeItem: function() {stored=null;}},
  noteEditor: {start: function() {editor.hidden=false;}}, addEventListener: function() {}};
""".replace("CACHED", json.dumps(json.dumps(cache) if cache is not None else None))
    result = subprocess.run(["node", "-e", setup + script + "\nconsole.log(JSON.stringify({state:document.body.dataset.resumePosition,selection:[editor.selectionStart,editor.selectionEnd],editor_scroll:editor.scrollTop,reading_scroll:column.scrollTop,snapshot:window.noteViewPosition.snapshot()}));"], capture_output=True, text=True, check=True, timeout=10)
    return json.loads(result.stdout)


def test_ephemeral_resume_preserves_runtime_cursor_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import asdict
    from app.orientation.leave_point_cursor import ALLOWED_CURSOR_FIELDS, capture_leave_point_cursor, latest_leave_point_projection
    from companion_ui.workspace.serve_dev_page import _resume_view_admitted

    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "cursor.sqlite3"))
    note = tmp_path / "Notes/note.md"
    note.parent.mkdir()
    note.write_text("---\nuuid: 11111111-1111-4111-8111-111111111111\n---\nBody.\n")
    fields = _view_fields()
    event = capture_leave_point_cursor(
        vault_id="Synthetic", channel="test", artifact_uuid=fields["artifact_id"],
        source_kind="artifact_activation", source_ref_id="Notes/note.md", capture_reason="artifact_focus",
    )
    assert set(event) <= ALLOWED_CURSOR_FIELDS
    assert not {"position", "selection", "scroll_position"} & set(event)
    projection = latest_leave_point_projection(vault_id="Synthetic", channel="test", vault_root=tmp_path)
    actual = {"scope": _orientation(fields)["scope"], "leave_point": asdict(projection)}
    assert _resume_view_admitted(actual, fields)
    outcome = _view_outcome(fields, _cached_view(fields))
    assert outcome["state"] == "restored"
    assert not {"body", "content", "receipt", "authority"} & outcome["snapshot"].keys()
    assert "position" not in actual["leave_point"]
    assert _view_outcome(fields, None)["state"] == "missing"


@pytest.mark.parametrize("fault", ["vault_id", "local_instance_id", "channel", "artifact_id", "note_path", "content_hash", "expired", "future", "range", "fractional_range", "body"])
def test_wrong_or_stale_resume_position_refused(fault: str) -> None:
    fields = _view_fields()
    cache = _cached_view(fields)
    if fault in {"vault_id", "local_instance_id", "channel", "artifact_id", "note_path", "content_hash"}:
        cache[fault] = "other-context"
    elif fault == "expired":
        cache["captured_at"] -= 4 * 24 * 60 * 60 * 1000
    elif fault == "future":
        cache["captured_at"] += 60000
    elif fault == "range":
        cache["end"] = 10000
    elif fault == "fractional_range":
        cache["start"] = 1.5
    else:
        cache["body"] = "no body belongs in a view snapshot"
    outcome = _view_outcome(fields, cache)
    assert outcome["state"] == "refused" and outcome["selection"] == [0, 0]
    assert outcome["reading_scroll"] == 0


@pytest.mark.parametrize("fault", [None, "wrong_artifact", "wrong_path", "wrong_scope", "wrong_channel", "wrong_provenance", "stale", "missing", "unavailable"])
def test_reentry_resume_uses_runtime_admitted_artifact(fault: str | None) -> None:
    from companion_ui.workspace.serve_dev_page import _reentry_resume_affordance, _resume_view_admitted
    fields = _view_fields()
    orientation = _orientation(fields)
    if fault == "wrong_artifact":
        orientation["leave_point"]["artifact_ref"]["artifact_uuid"] = "other-artifact"
    elif fault == "wrong_path":
        orientation["leave_point"]["artifact_ref"]["logical_ref"] = "Other/note.md"
    elif fault == "wrong_scope":
        orientation["scope"]["vault_id"] = "Other"
    elif fault == "wrong_channel":
        orientation["scope"]["channel"] = "prod"
    elif fault == "wrong_provenance":
        fields["runtime_vault_provenance"] = "resolved"
    elif fault in {"stale", "missing"}:
        orientation["leave_point"]["status"] = "stale" if fault == "stale" else "artifact_missing"
    elif fault == "unavailable":
        orientation = None
    fields["resume_view_admitted"] = _resume_view_admitted(orientation, fields)
    outcome = _view_outcome(fields, _cached_view(fields))
    assert outcome["state"] == ("restored" if fault is None else "refused")
    if fault is None:
        assert outcome["selection"] == [2, 7] and outcome["reading_scroll"] == 40
        assert "resume=1" in _reentry_resume_affordance(orientation["leave_point"], stale=False)
    if fault == "stale":
        assert "resume=1" not in _reentry_resume_affordance(orientation["leave_point"], stale=True)


@pytest.mark.parametrize("case", ["same_name", "same_logical_vault_clone", "absent_identity", "selected_root_changed", "selection_changes_after_admission"])
def test_optional_scope_identity_is_bound_to_actual_workspace_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, product_model_access_gateway: Any, case: str,
) -> None:
    from fastapi.testclient import TestClient
    from tests.api._vault_test_helpers import bind_initialized_vault
    from dataclasses import replace
    import shutil
    import app.api.routes.companion as companion
    from app.api.app import app
    from companion_ui.workspace.real_note_workspace_dev_page import NoteLoadIntent, RealNoteWorkspaceDevPage
    from companion_ui.workspace.serve_dev_page import _note_view_position_script, _resume_workspace_matches_rendered
    from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError

    first = tmp_path / "first"
    first.mkdir()
    manager = bind_initialized_vault(monkeypatch, first, name="Same Name", channel="test")
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "scope-cursor.sqlite3"))
    monkeypatch.setattr(companion, "_configured_vault_name", lambda: "Same Name")
    text = "---\nuuid: 11111111-1111-4111-8111-111111111111\n---\n# Identical synthetic note\n\nBody.\n"
    (first / "note.md").write_text(text)
    api = TestClient(app)

    class Client:
        def get(self, path: str, *, params: dict | None = None) -> dict:
            response = api.get(path, params=params)
            if response.status_code >= 400:
                raise WorkspaceClientHTTPError(response.status_code, response.text)
            return response.json()

    def fields() -> dict[str, Any]:
        page = RealNoteWorkspaceDevPage(Client())
        assert page.load(NoteLoadIntent(note_path="note.md")).is_loaded
        return page.render_fields()

    before = fields()
    assert before["runtime_vault_id"] == manager.context.active_vault_id
    assert before["runtime_local_instance_id"] == manager.context.local_instance_id
    assert before["runtime_vault_id"] and before["runtime_local_instance_id"]
    cache = _cached_view(before)
    if case == "absent_identity":
        manager._context = replace(manager.context, local_instance_id=None)
        actual = fields()
        assert actual["runtime_local_instance_id"] is None
        assert _note_view_position_script(actual) == ""
        return
    second = tmp_path / "second"
    second.mkdir()
    (second / "note.md").write_text(text)
    if case == "same_logical_vault_clone":
        (second / "settings").mkdir()
        shutil.copyfile(first / "settings/vault.md", second / "settings/vault.md")
    manager.initialize_vault(second, vault_name="Same Name", remember=False)
    if case == "selection_changes_after_admission":
        manager.select_vault(first, remember=False)
        original_admit = companion._active_companion_vault_root

        def admit_then_select(**kwargs: Any) -> Path:
            admitted = original_admit(**kwargs)
            manager.select_vault(second, remember=False)
            return admitted

        monkeypatch.setattr(companion, "_active_companion_vault_root", admit_then_select)
        actual = fields()
        assert actual["runtime_vault_id"] == before["runtime_vault_id"]
        assert actual["runtime_local_instance_id"] == before["runtime_local_instance_id"]
        current = api.get("/api/companion/workspace", params={"note_path": "note.md"}).json()
        assert not _resume_workspace_matches_rendered(current, actual)
        return
    if case == "selected_root_changed":
        identity = companion._vault_identity_state(first, context_snapshot=manager.context)
        assert identity.vault_id is None and identity.local_instance_id is None
        return
    actual = fields()
    assert actual["runtime_vault_name"] == before["runtime_vault_name"]
    assert actual["artifact_id"] == before["artifact_id"] and actual["content_hash"] == before["content_hash"]
    if case == "same_logical_vault_clone":
        assert actual["runtime_vault_id"] == before["runtime_vault_id"]
    else:
        assert actual["runtime_vault_id"] != before["runtime_vault_id"]
    assert actual["runtime_local_instance_id"] != before["runtime_local_instance_id"]
    actual.update(resume_view_requested=True, resume_view_admitted=True)
    assert _view_outcome(actual, cache)["state"] == "refused"


@pytest.mark.parametrize("change", [None, "vault_id", "local_instance_id", "content_hash", "unavailable"])
def test_resume_render_refuses_workspace_change_across_orientation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, product_model_access_gateway: Any, change: str | None,
) -> None:
    from fastapi.testclient import TestClient
    from tests.api._vault_test_helpers import bind_initialized_vault
    import app.api.routes.companion as companion
    from app.api.app import app
    from companion_ui.workspace.serve_dev_page import handle_get
    from companion_ui.workspace.workspace_http_client import WorkspaceClientHTTPError
    import re

    vault = tmp_path / "synthetic-vault"
    vault.mkdir()
    bind_initialized_vault(monkeypatch, vault, name="Synthetic", channel="test")
    (vault / "note.md").write_text("---\nuuid: 11111111-1111-4111-8111-111111111111\n---\n# Synthetic\n")
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "leave.sqlite3"))
    monkeypatch.setattr(companion, "_configured_vault_name", lambda: "Synthetic")
    api = TestClient(app)
    orientation_seen = False
    reads = []

    class Client:
        def get(self, path: str, *, params: dict | None = None) -> dict:
            nonlocal orientation_seen
            reads.append(path)
            if path == "/api/companion/orientation":
                orientation_seen = True
                return {"scope": {"vault_id": "Synthetic", "channel": "test"}, "leave_point": {"status": "present", "artifact_ref": {"artifact_uuid": "11111111-1111-4111-8111-111111111111", "logical_ref": "note.md"}}}
            if path == "/api/companion/workspace" and orientation_seen and change == "unavailable":
                raise WorkspaceClientHTTPError(503, "synthetic unavailable readback")
            response = api.get(path, params=params)
            if response.status_code >= 400:
                raise WorkspaceClientHTTPError(response.status_code, response.text)
            payload = response.json()
            if path == "/api/companion/workspace" and orientation_seen and change:
                if change == "content_hash":
                    payload["artifact"][change] = "different-content"
                else:
                    payload["runtime"]["vault_identity"][change] = "different-scope"
            return payload

    html = handle_get(query_string="note_path=note.md&resume=1", client=Client(), api_base_url="http://127.0.0.1:18002")
    config = json.loads(re.search(r"var config = (\{[^\n]+\});\n    var editor = document.getElementById\('note-source-editor'\)", html).group(1))
    assert config["requested"] and config["admitted"] is (change is None)
    assert reads.count("/api/companion/workspace") == 2
