from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import execute_panel_intent
from app.events.types import PROMOTE_DONE, PROMOTE_INTENT_CREATED
from app.observability.status_service import get_system_status
from app.promotion.consumer import consume_promotion_intents
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore

pytestmark = pytest.mark.not_pg


def _seed_note(note_uuid: str, markdown: str, note_path: Path) -> None:
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(markdown, encoding="utf-8")
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref=str(note_path),
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-panel-promote")


def _panel_markdown(label: str) -> str:
    return f"""%% AI:Start %%
## AI-instruktion
Please promote this note.
## AI-åtgärder
- [x] {label}
%% AI:End %%
"""


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_panel_promotion_flow_consumes_and_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    object_store_module._MEMORY_STORE.clear()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")

    note_uuid = str(uuid4())
    markdown = _panel_markdown("Gör denna anteckning evergreen")
    note_path = tmp_path / "vault" / "Note.md"
    _seed_note(note_uuid, markdown, note_path)

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
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    # Force deterministic, non-LLM path regardless of user environment.
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr("app.observability.status_service.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    panel_events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-promote")
    assert panel_events, "expected a panel.intent.created event"

    runtime_result = execute_panel_intent(panel_events[0], outbox_path=outbox_path)
    records = _read_outbox(outbox_path)
    topics = {rec.get("event") for rec in records}
    assert PROMOTE_INTENT_CREATED in topics
    assert runtime_result.emitted_events

    summary = consume_promotion_intents(outbox_path=outbox_path)
    assert summary["applied"] == 1

    obj = ObjectStore().get_object(note_uuid)
    assert obj is not None
    assert obj.payload.get("review_state") == "reviewed"
    assert obj.payload.get("maturity") == "evergreen"
    assert obj.payload.get("promotion", {}).get("state") == "evergreen"
    assert note_path.read_text(encoding="utf-8").startswith("---")

    records = _read_outbox(outbox_path)
    topics = {rec.get("event") for rec in records}
    assert PROMOTE_DONE in topics

    status = get_system_status()
    assert status.events is not None
    assert status.events.promote_created_total == 1
    assert status.events.promotion_executed_total == 1
