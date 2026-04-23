from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.agent import run_panel_intent_for_note
from app.agents.panel_agent.runtime import execute_panel_intent
from app.store import object_store as object_store_module
from app.store.object_store import DomainObject, ObjectStore


@pytest.fixture(autouse=True)
def _clear_memory_store() -> None:
    object_store_module._MEMORY_STORE.clear()


def _seed_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown, "origin": "vault"},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-test")


def _panel_markdown(action_label: str) -> str:
    return f"""%% AI:Start %%
## AI-instruktion
Process this action.
## AI-åtgärder
- [x] {action_label}
%% AI:End %%
"""


def _settings_file(tmp_path: Path, *, trust_verb: str | None) -> Path:
    trust_line = f'    trust_verb: "{trust_verb}"\n' if trust_verb else ""
    path = tmp_path / "panel-actions.md"
    path.write_text(
        f"""---
mappings:
  - id: "promote.evergreen"
    label: "Make this note evergreen"
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
{trust_line}    params:
      maturity: "evergreen"
---
""",
        encoding="utf-8",
    )
    return path


def _read_outbox(outbox_path: Path) -> list[dict]:
    if not outbox_path.exists():
        return []
    return [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_panel_proposal_requires_trust_verb_classification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path, trust_verb=None)
    _seed_note(note_uuid, _panel_markdown("Make this note evergreen"))

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    created = run_panel_intent_for_note(note_uuid, trace_id="trace-missing-verb")
    execute_panel_intent(created[0], outbox_path=outbox_path)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "panel.action.logged" in topics
    assert "promote.intent.created" not in topics


def test_suggest_does_not_mutate_without_admission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path, trust_verb="SUGGEST")
    _seed_note(note_uuid, _panel_markdown("Make this note evergreen"))

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    created = run_panel_intent_for_note(note_uuid, trace_id="trace-suggest")
    execute_panel_intent(created[0], outbox_path=outbox_path)

    records = _read_outbox(outbox_path)
    topics = {rec["event"] for rec in records}
    assert "panel.action.logged" in topics
    assert "promote.intent.created" not in topics
