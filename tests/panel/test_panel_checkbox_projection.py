from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.panel.checkbox_projection as projection_module
from app.api.app import app
from app.api.routes.artifacts import _content_hash
from app.panel.checkbox_projection import extract_panel_selectable_options
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError


@pytest.fixture(autouse=True)
def _clear_projection_state(monkeypatch: pytest.MonkeyPatch) -> None:
    projection_module._idempotency_store.clear()
    projection_module._service._guard = DEFAULT_WRITE_GUARD
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    yield
    projection_module._idempotency_store.clear()
    projection_module._service._guard = DEFAULT_WRITE_GUARD


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _panel_note(*, checked: bool = False, option_id: str = "opt_abc") -> str:
    mark = "x" if checked else " "
    return (
        "---\n"
        "uuid: note-uuid-1\n"
        "---\n\n"
        "# Note\n\n"
        "- [ ] ordinary task\n\n"
        "```markdown\n"
        "- [ ] code task <!--ai:option_id=opt_code--> <!--ai:id=code--> <!--ai:proposed=979-->\n"
        "```\n\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Do the thing.\n"
        "## AI-åtgärder\n"
        f"- [{mark}] Send email <!--ai:option_id={option_id}--> <!--ai:id=send.email--> <!--ai:proposed=979-->\n"
        "- [ ] Missing identity <!--ai:id=legacy--> <!--ai:proposed=979-->\n"
        "## AI-logg\n"
        "- [ ] receipt checkbox <!--ai:option_id=opt_receipt--> <!--ai:id=receipt--> <!--ai:proposed=979-->\n"
        "%% AI:End %%\n"
    )


def _write_note(tmp_path: Path, content: str | None = None) -> Path:
    note = tmp_path / "notes" / "panel.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(content or _panel_note(), encoding="utf-8")
    return note


def _request_for(note: Path, *, option_id: str = "opt_abc") -> dict:
    content = note.read_text(encoding="utf-8")
    option = next(
        option
        for option in extract_panel_selectable_options(
            content,
            artifact_id="note-uuid-1",
            note_path="notes/panel.md",
            content_hash=_content_hash(content),
        )
        if option.option_id == option_id
    )
    return {
        "artifact_id": option.artifact_id,
        "note_path": option.note_path,
        "panel_id": option.panel_id,
        "option_id": option.option_id,
        "expected_content_hash": option.content_hash,
        "expected_source_hash": option.source_hash,
        "idempotency_key": "idem-1",
    }


def test_option_extraction_only_returns_panel_actions_with_option_id() -> None:
    content = _panel_note()

    options = extract_panel_selectable_options(
        content,
        artifact_id="note-uuid-1",
        note_path="notes/panel.md",
    )

    assert [option.option_id for option in options] == ["opt_abc"]
    option = options[0]
    assert option.panel_id == "panel-1"
    assert option.action_id == "send.email"
    assert option.label == "Send email"
    assert option.checked is False
    assert option.proposal_pending is True
    assert option.selectable is True
    source_line = content.splitlines()[option.source_range.start_line]
    assert option.source_hash == projection_module._source_line_hash(source_line)


def test_projection_endpoint_checks_markdown_source_and_projects_checkbox(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    runtime_result = MagicMock(runtime_results=[object()])
    monkeypatch.setattr(projection_module, "run_panel_note_execution", MagicMock(return_value=runtime_result))

    resp = client.post("/api/panel/checkbox-projection", json=_request_for(note))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "executed"
    assert data["content_hash_before"] != data["content_hash_after"]
    updated = note.read_text(encoding="utf-8")
    assert "- [x] Send email <!--ai:option_id=opt_abc-->" in updated
    assert "- [ ] ordinary task" in updated


def test_projection_endpoint_rejects_stale_content_hash(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    body = _request_for(note)
    body["expected_content_hash"] = "stale"

    resp = client.post("/api/panel/checkbox-projection", json=body)

    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "stale"
    assert "- [x] Send email" not in note.read_text(encoding="utf-8")


def test_projection_endpoint_rejects_stale_source_hash(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    body = _request_for(note)
    body["expected_source_hash"] = "stale"

    resp = client.post("/api/panel/checkbox-projection", json=body)

    assert resp.status_code == 409
    assert resp.json()["detail"]["block_reason"] == "source_hash_mismatch"


def test_projection_endpoint_unknown_option_returns_404(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    body = _request_for(note)
    body["option_id"] = "opt_missing"

    resp = client.post("/api/panel/checkbox-projection", json=body)

    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "not_found"


def test_projection_endpoint_already_checked_is_idempotent(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path, _panel_note(checked=True))
    content = note.read_text(encoding="utf-8")
    option = extract_panel_selectable_options(
        content,
        artifact_id="note-uuid-1",
        note_path="notes/panel.md",
        content_hash=_content_hash(content),
    )[0]
    body = {
        "artifact_id": option.artifact_id,
        "note_path": option.note_path,
        "panel_id": option.panel_id,
        "option_id": option.option_id,
        "expected_content_hash": option.content_hash,
        "expected_source_hash": option.source_hash,
        "idempotency_key": "idem-checked",
    }

    resp = client.post("/api/panel/checkbox-projection", json=body)

    assert resp.status_code == 200
    assert resp.json()["status"] == "already_projected"


def test_projection_endpoint_duplicate_idempotency_key_returns_cached_response(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    runtime = MagicMock(return_value=MagicMock(runtime_results=[object()]))
    monkeypatch.setattr(projection_module, "run_panel_note_execution", runtime)
    body = _request_for(note)

    first = client.post("/api/panel/checkbox-projection", json=body)
    second = client.post("/api/panel/checkbox-projection", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert runtime.call_count == 1


def test_projection_endpoint_writeguard_blocked_does_not_project(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = _write_note(tmp_path)
    guard = MagicMock(spec=WriteGuard)
    guard.assert_writes_allowed.side_effect = WritesBlockedError(
        "blocked",
        "guard active",
        "panel.checkbox_projection",
    )
    projection_module._service._guard = guard

    resp = client.post("/api/panel/checkbox-projection", json=_request_for(note))

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"
    assert "- [x] Send email" not in note.read_text(encoding="utf-8")
