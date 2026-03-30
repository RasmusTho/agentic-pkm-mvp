from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.execution import run_panel_note_execution
from app.agents.panel_agent.runtime import PanelRuntimeResult, execute_panel_intent
from app.components.concurrency import IdempotencyGuard
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore


class _StubReasoningFacade:
    def __init__(self, response: dict) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None) -> dict:
        return self._response



def _seed_note(note_uuid: str, markdown: str, *, executed_action_ids: list[str] | None = None) -> None:
    payload = {"raw_text": markdown, "origin": "vault"}
    if executed_action_ids:
        payload["executed_action_ids"] = list(executed_action_ids)
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload=payload,
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


def _settings_file_with_flags(
    tmp_path: Path,
    *,
    action_id: str,
    label: str,
    intent_type: str,
    downstream_event: str,
    manual_only: bool = False,
    watcher_allowed: bool = True,
) -> Path:
    path = tmp_path / "panel-actions.md"
    manual_only_line = "    manual_only: true\n" if manual_only else ""
    watcher_allowed_line = "    watcher_allowed: false\n" if not watcher_allowed else ""
    path.write_text(
        f"""---
mappings:
  - id: "{action_id}"
    label: "{label}"
    intent_type: "{intent_type}"
    downstream_event: "{downstream_event}"
{manual_only_line}{watcher_allowed_line}    params:
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
    assert (payload.get("transition") or {}).get("target_maturity") == "evergreen"


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


def test_runtime_llm_filters_executed_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    _seed_note(note_uuid, markdown, executed_action_ids=["promote.evergreen"])

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-executed")
    assert len(events) == 1

    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "promote.intent.created" not in topics
    assert "panel.action.triggered" not in topics


def test_runtime_watcher_mode_blocks_manual_only_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file_with_flags(
        tmp_path,
        action_id="note.archive",
        label="Archive this note",
        intent_type="archival",
        downstream_event="note.archive",
        manual_only=True,
        watcher_allowed=False,
    )
    markdown = _panel_markdown("Archive this note", checked=True)
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-watcher", trigger="watcher")
    assert len(events) == 1
    assert events[0].source.trigger == "watcher"

    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)
    assert result.actions[0].status == "logged"
    assert result.actions[0].details.get("reason") == "watcher_not_allowed"

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "panel.action.logged" in topics
    assert "promote.intent.created" not in topics


def test_runtime_restart_does_not_reemit_executed_actions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    _seed_note(note_uuid, markdown, executed_action_ids=["promote.evergreen"])

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "llm")
    monkeypatch.setattr("app.agents.panel_agent.graph._IDEMPOTENCY_GUARD", IdempotencyGuard(ttl_seconds=86400.0))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-restart")
    assert len(events) == 1

    result = execute_panel_intent(events[0], outbox_path=outbox_path)
    assert isinstance(result, PanelRuntimeResult)
    assert [action.id for action in result.intent.payload.actions] == []

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "promote.intent.created" not in topics
    assert "panel.action.triggered" not in topics


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


def test_run_panel_note_execution_runs_full_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setenv("STORE_BACKEND", "memory")

    result = run_panel_note_execution(note_uuid, trace_id="trace-panel-pipeline", outbox_path=outbox_path)

    assert len(result.intent_events) == 1
    assert len(result.runtime_results) == 1
    assert result.emitted_count >= 3

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert {"panel.intent.created", "panel.intent.executed", "promote.intent.created"} <= topics
