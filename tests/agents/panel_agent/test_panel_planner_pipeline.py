from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.intent import PanelActionIntent
from app.agents.panel_agent.runtime import execute_panel_intent
from app.agents.panel_agent.settings import get_panel_agent_pipeline
from app.events.panel import NoteRef
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore
from app.stores.plan_store import get_plan_store, reset_plan_store


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-panel-planner")


def _settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        """---
mappings:
  - id: "promote.evergreen"
    label: "Gör denna anteckning evergreen"
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
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
def clear_stores() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_plan_store()


def test_panel_action_intent_round_trip() -> None:
    note = NoteRef(uuid="abc-123", path="vault/Test.md", origin="vault")
    intent = PanelActionIntent(note=note, instruction="Do things", actions=["promote.evergreen"], source="panel_agent")
    data = intent.model_dump()
    restored = PanelActionIntent(**data)
    assert restored.note.uuid == "abc-123"
    assert restored.instruction == "Do things"
    assert restored.actions == ["promote.evergreen"]
    assert restored.source == "panel_agent"


def test_pipeline_setting_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PANEL_AGENT_PIPELINE", raising=False)
    assert get_panel_agent_pipeline() == "direct"
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "planner")
    assert get_panel_agent_pipeline() == "planner"
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "invalid")
    assert get_panel_agent_pipeline() == "direct"


def test_execute_panel_intent_direct_does_not_create_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    markdown = _panel_markdown("Gör denna anteckning evergreen", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.delenv("PANEL_AGENT_PIPELINE", raising=False)
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-direct")
    assert len(events) == 1
    execute_panel_intent(events[0], outbox_path=outbox_path)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert {"panel.intent.created", "panel.intent.executed", "promote.intent.created"} <= topics
    store = get_plan_store()
    assert store.list_by_event(events[0].event_id) == []


def test_execute_panel_intent_planner_creates_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    markdown = _panel_markdown("Gör denna anteckning evergreen", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "planner")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-planner")
    assert len(events) == 1
    execute_panel_intent(events[0], outbox_path=outbox_path)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert {"panel.intent.created", "panel.intent.executed", "promote.intent.created"} <= topics

    store = get_plan_store()
    plans = store.list_by_event(events[0].event_id)
    assert len(plans) == 1
    plan = plans[0]
    assert plan.meta.source_object_uuid == note_uuid
    assert "panel" in plan.tags
    assert plan.trigger and plan.trigger.event_id == events[0].event_id

