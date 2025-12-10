from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore

pytestmark = pytest.mark.not_pg


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-panel-promo")


def test_panel_promote_intent_payload_is_queue_compatible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # fresh in-memory store
    object_store_module._MEMORY_STORE.clear()

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
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    panel_events = run_panel_intent_for_note(note_uuid, trace_id="trace-panel-promote")
    assert panel_events, "expected a panel.intent.created event"

    runtime_result = execute_panel_intent(panel_events[0], outbox_path=outbox_path)
    promote_event = next(
        ev for ev in runtime_result.emitted_events if getattr(ev, "event", "") == "promote.intent.created"
    )
    payload = promote_event.payload
    note_ref = payload["note"]
    assert note_ref["uuid"] == note_uuid
    assert note_ref["path"] == "vault/Note.md"
    assert payload.get("maturity") == "evergreen"

    # Promotion queue should accept the payload-derived fields without error
    import app.promotion.queue as q

    queue_path = tmp_path / "queue.jsonl"
    log_path = tmp_path / "log.jsonl"
    settings_yaml = tmp_path / "settings.yaml"
    monkeypatch.setattr(q, "QUEUE", queue_path, raising=False)
    monkeypatch.setattr(q, "LOG", log_path, raising=False)
    monkeypatch.setattr(q, "SETTINGS", settings_yaml, raising=False)

    q.enqueue(Path(note_ref["path"]), uuid=note_ref["uuid"], desired_state=payload.get("maturity", "promoted"))

    lines = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["uuid"] == note_uuid
    assert record["desired_state"] == "evergreen"
