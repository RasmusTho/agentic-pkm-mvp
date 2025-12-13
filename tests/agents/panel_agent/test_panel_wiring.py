from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.agents.panel_agent.wiring import get_default_action_wiring, reset_action_wiring_cache
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
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-panel-wiring")


def _settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
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
    return path


def _read_outbox(outbox_path: Path) -> list[dict]:
    if not outbox_path.exists():
        return []
    return [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def clear_store_and_cache() -> None:
    object_store_module._MEMORY_STORE.clear()
    reset_action_wiring_cache()


def test_default_wiring_matches_current_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    markdown = """%% AI:Start %%
## AI-instruktion
Please promote this note.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-default-wiring")
    runtime_result = execute_panel_intent(events[0], outbox_path=outbox_path)
    topics = {getattr(ev, "event", "") for ev in runtime_result.emitted_events}

    assert "promote.intent.created" in topics
    assert "panel.intent.executed" in topics
    assert get_default_action_wiring().get("promote.evergreen") == "promote.intent.created"


def test_custom_wiring_overrides_target_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    markdown = """%% AI:Start %%
## AI-instruktion
Please promote this note.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    wiring_path = tmp_path / "panel-action-wiring.yaml"
    wiring_path.write_text(
        """actions:
  - id: promote.evergreen
    target_event: "custom.promote"
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("PANEL_ACTION_WIRING_PATH", str(wiring_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    reset_action_wiring_cache()

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-custom-wiring")
    runtime_result = execute_panel_intent(events[0], outbox_path=outbox_path)
    topics = {getattr(ev, "event", "") for ev in runtime_result.emitted_events}

    assert "custom.promote" in topics
    assert "promote.intent.created" not in topics
