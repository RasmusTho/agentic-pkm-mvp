from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.objects import DomainObject, ObjectStore


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-test")


def _settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        """---
mappings:
  - id: mapped-action
    label: "Mapped Action"
    intent_type: task
    downstream_event: action.mapped
    params:
      priority: high
---
""",
        encoding="utf-8",
    )
    return path


def test_panel_intent_event_contains_actions_and_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Do things.
## AI-åtgärder
- [x] Mapped Action
- [ ] Unknown Action
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    settings_path = _settings_file(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel")
    assert len(events) == 1
    event = events[0]

    assert event.event == "panel.intent.created"
    assert event.payload.note.uuid == note_uuid
    assert len(event.payload.actions) == 2

    mapped = next(a for a in event.payload.actions if a.label == "Mapped Action")
    assert mapped.checked is True
    assert mapped.mapping is not None
    assert mapped.mapping.downstream_event == "action.mapped"

    unknown = next(a for a in event.payload.actions if a.label == "Unknown Action")
    assert unknown.mapping is None
    assert unknown.checked is False

    # Outbox line should be written
    assert outbox_path.exists()
    lines = outbox_path.read_text(encoding="utf-8").splitlines()
    assert lines, "expected an outbox record"
    record = json.loads(lines[-1])
    assert record.get("event") == "panel.intent.created"
    assert record.get("payload", {}).get("panel", {}).get("panel_id") == "panel-1"
