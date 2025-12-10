from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import PanelRuntimeResult, execute_panel_intent
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-runtime-test")


def _settings_file(tmp_path: Path, *, action_id: str, label: str, intent_type: str, downstream_event: str) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        f"""---
mappings:
  - id: "{action_id}"
    label: "{label}"
    intent_type: "{intent_type}"
    downstream_event: "{downstream_event}"
    params:
      maturity: "evergreen"
---
""",
        encoding="utf-8",
    )
    return path


def _panel_markdown(action_label: str, checked: bool = True) -> str:
    mark = "x" if checked else " "
    return f"""%% AI:Start %%
## AI-instruktion
Please process this panel.
## AI-åtgärder
- [{mark}] {action_label}
%% AI:End %%
"""


def _read_outbox(outbox_path: Path) -> list[dict]:
    if not outbox_path.exists():
        return []
    return [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def clear_memory_store() -> None:
    object_store_module._MEMORY_STORE.clear()


def test_runtime_emits_promotion_intent_and_execution_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Gör denna anteckning evergreen",
        intent_type="promotion",
        downstream_event="review.promote.evergreen",
    )
    markdown = _panel_markdown("Gör denna anteckning evergreen", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel")
    assert len(events) == 1

    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "panel.intent.created" in topics
    assert "panel.intent.executed" in topics
    assert "promote.intent.created" in topics

    promote = next(rec for rec in records if rec["event"] == "promote.intent.created")
    payload = promote.get("payload") or {}
    assert payload.get("note", {}).get("uuid") == note_uuid
    assert payload.get("maturity") == "evergreen"


def test_runtime_logs_unhandled_actions_without_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(
        tmp_path,
        action_id="note.archive",
        label="Arkivera den här anteckningen",
        intent_type="archival",
        downstream_event="note.archive",
    )
    markdown = _panel_markdown("Arkivera den här anteckningen", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-noop")
    assert len(events) == 1

    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "panel.intent.executed" in topics
    assert "panel.action.logged" in topics
    assert "promote.intent.created" not in topics


def test_runtime_appends_ai_log_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(
        tmp_path,
        action_id="promote.evergreen",
        label="Gör denna anteckning evergreen",
        intent_type="promotion",
        downstream_event="review.promote.evergreen",
    )
    markdown = _panel_markdown("Gör denna anteckning evergreen", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-log")
    result = execute_panel_intent(events[0], outbox_path=outbox_path)

    assert result.log_entry is not None
    assert "panel.intent.executed" in (result.log_entry.summary or "")

    stored = ObjectStore().get_object(note_uuid)
    assert stored is not None
    logs = stored.payload.get("panel_logs") or []
    assert logs, "expected panel_logs to contain the AI-log entry"

    records = _read_outbox(outbox_path)
    assert any(rec.get("event") == "panel.log.created" for rec in records)
