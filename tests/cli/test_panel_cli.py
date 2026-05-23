from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from click.testing import CliRunner

from app.cli import cli
from app.store import object_store as object_store_module
from app.objects import DomainObject, ObjectStore


def _seed_panel_note(note_uuid: str, markdown: str) -> None:
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={"raw_text": markdown},
        source_ref="vault/Note.md",
        created_at=datetime.now(timezone.utc),
    )
    ObjectStore().save_object(obj, emit_outbox=False, trace_id="trace-cli")


def _settings_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        """---
mappings:
  - id: mapped
    label: "Do Thing"
    intent_type: task
    downstream_event: action.do
---
""",
        encoding="utf-8",
    )
    return path


def test_panel_cli_emits_outbox(tmp_path: Path, monkeypatch) -> None:
    # clear memory store between runs
    object_store_module._MEMORY_STORE.clear()

    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Please do the thing.
## AI-åtgärder
- [x] Do Thing
- [ ] Other Thing
%% AI:End %%
"""
    _seed_panel_note(note_uuid, markdown)

    settings_path = _settings_file(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run", "--uuid", note_uuid], env=env)

    assert result.exit_code == 0, result.output
    assert outbox_path.exists()
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, "expected an outbox entry"

    events = {record.get("event") for record in lines}
    assert "panel.intent.created" in events
    assert "panel.intent.executed" in events
    assert "panel.action.logged" in events

    created = next(rec for rec in lines if rec.get("event") == "panel.intent.created")
    payload = created.get("payload") or {}
    assert payload.get("note", {}).get("uuid") == note_uuid
    assert len(payload.get("actions", [])) == 2


def test_panel_cli_can_emit_only_without_runtime(tmp_path: Path, monkeypatch) -> None:
    object_store_module._MEMORY_STORE.clear()

    note_uuid = str(uuid4())
    markdown = """%% AI:Start %%
## AI-instruktion
Please do the thing.
## AI-åtgärder
- [x] Do Thing
%% AI:End %%
"""
    _seed_panel_note(note_uuid, markdown)

    settings_path = _settings_file(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    runner = CliRunner()
    env = {
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_ACTIONS_PATH": str(settings_path),
    }
    result = runner.invoke(cli, ["panel", "run", "--uuid", note_uuid, "--emit-only"], env=env)

    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = {record.get("event") for record in lines}
    assert events == {"panel.intent.created"}
