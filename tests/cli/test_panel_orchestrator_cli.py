from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.intent import PanelActionIntent
from app.agents.panel_agent.planning import plan_panel_actions
from app.agents.panel_agent.runtime import execute_panel_intent
from app.events.panel import NoteRef, PanelActionMapping, PanelIntentAction, PanelInfo
from app.planner.schema import Plan, PlanMetadata, PlanStep
from app.cli import cli
from app.store import object_store as object_store_module
from app.objects import DomainObject, ObjectStore
from app.stores.plan_store import get_plan_store, reset_plan_store


pytestmark = pytest.mark.not_pg


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-panel-plan")


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_plan_store()


def test_promotion_tool_executes_and_emits_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    _seed_note(note_uuid, "note content")
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))

    plan = Plan(
        id="plan-panel-tool",
        meta=PlanMetadata(goal="Test promotion tool", source_object_uuid=note_uuid, created_by="test"),
        steps=[
            PlanStep(
                id="step-1",
                kind="tool_call",
                description="Emit promotion intent",
                tool="promotion.emit_intent",
                tool_args={"note_uuid": note_uuid, "action_id": "promote.evergreen", "maturity": "evergreen"},
            )
        ],
    )

    from app.orchestrator.runtime import Orchestrator

    orchestrator = Orchestrator()
    results = orchestrator.run_plan(plan)
    assert results and results[0]["status"] == "ok"

    events = _read_outbox(outbox_path)
    event_names = {rec.get("event") for rec in events}
    assert "promote.intent.created" in event_names
    promote = next(rec for rec in events if rec.get("event") == "promote.intent.created")
    assert promote.get("payload", {}).get("note", {}).get("uuid") == note_uuid


def test_panel_orchestrate_plan_cli_executes_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    _seed_note(note_uuid, "panel note")
    outbox_path = tmp_path / "index-outbox.jsonl"

    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    resolved_action = PanelIntentAction(id="promote.evergreen", label="Promote", checked=True, mapping=mapping)
    intent = PanelActionIntent(
        note=NoteRef(uuid=note_uuid, path="vault/Note.md", origin="vault"),
        instruction="Make this evergreen",
        actions=["promote.evergreen"],
        resolved_actions=[resolved_action],
        source="panel_agent",
    )
    plan = plan_panel_actions(intent, event_id="evt-panel", trace_id="trace-panel")

    runner = CliRunner()
    env = {"INDEX_OUTBOX_PATH": str(outbox_path)}
    result = runner.invoke(cli, ["panel-orchestrate-plan", "--plan-id", plan.id], env=env)

    assert result.exit_code == 0, result.output
    events = _read_outbox(outbox_path)
    event_names = {rec.get("event") for rec in events}
    assert "promote.intent.created" in event_names


def test_panel_planner_plan_can_be_executed_after_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Please promote this note.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: "Gör denna anteckning evergreen"
    intent_type: promotion
    downstream_event: review.promote.evergreen
    params:
      maturity: evergreen
---
""",
        encoding="utf-8",
    )
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "planner")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-orchestrate")
    runtime_result = execute_panel_intent(events[0], outbox_path=outbox_path)
    # Clear outbox to isolate orchestrator output
    outbox_path.write_text("", encoding="utf-8")

    store = get_plan_store()
    plans = store.list_by_object(note_uuid)
    assert plans, "expected a panel plan to be created"
    plan = plans[-1]

    runner = CliRunner()
    env = {"INDEX_OUTBOX_PATH": str(outbox_path)}
    result = runner.invoke(cli, ["panel-orchestrate-plan", "--plan-id", plan.id], env=env)

    assert result.exit_code == 0, result.output
    events_after = _read_outbox(outbox_path)
    topics = {rec.get("event") for rec in events_after}
    assert "promote.intent.created" in topics
