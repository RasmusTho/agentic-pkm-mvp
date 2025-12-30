from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from click.testing import CliRunner

from app.cli import cli

pytestmark = pytest.mark.not_pg


class _StubChatClient:
    def __init__(self, response: str) -> None:
        self._response = response

    def chat(self, *args, **kwargs) -> str:
        return self._response


def _panel_actions_file(tmp_path: Path) -> Path:
    path = tmp_path / "panel-actions.md"
    path.write_text(
        """---
mappings:
  - id: "promote.evergreen"
    kind: "promotion"
    labels:
      - "Gör denna anteckning evergreen"
      - "Make this note evergreen"
      - "Promote to evergreen"
    description: "Promote the note to evergreen maturity."
    intent_type: "promotion"
    downstream_event: "review.promote.evergreen"
    params:
      maturity: "evergreen"
  - id: "panel.reply"
    kind: "chat"
    labels:
      - "Reply in panel"
    description: "Reply inline in the panel log."
    intent_type: "chat"
    downstream_event: "panel.reply.created"
    params: {}
---
""",
        encoding="utf-8",
    )
    return path


def _write_note(path: Path, *, uuid: str, instruction: str, action_label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
uuid: {uuid}
ai_panel_auto_run: watcher
---

%% AI:Start %%
## AI-instruktion
{instruction}
## AI-åtgärder
- [x] {action_label}
%% AI:End %%
""",
        encoding="utf-8",
    )


def _read_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_watcher_rule_mode_promotes_with_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    note_uuid = str(uuid4())
    note_path = vault_root / "Test" / "Note.md"
    _write_note(
        note_path,
        uuid=note_uuid,
        instruction="Please make this evergreen",
        action_label="Gör denna anteckning evergreen",
    )

    actions_path = _panel_actions_file(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    snapshot_path = tmp_path / "snapshot.json"

    env = {
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "PANEL_ACTIONS_PATH": str(actions_path),
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_AGENT_DECIDER": "rule",
        "WATCHER_AUTO_EXEC": "1",
    }
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "vault-watcher-run",
            "--vault-root",
            str(vault_root),
            "--snapshot-path",
            str(snapshot_path),
            "--max-notes",
            "5",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "panel_promotions=1" in result.output
    assert "errors=0" in result.output

    events = _read_outbox(outbox_path)
    topics = {entry.get("event") for entry in events}
    assert "promote.intent.created" in topics
    promote = next(e for e in events if e.get("event") == "promote.intent.created")
    assert promote.get("payload", {}).get("note", {}).get("uuid") == note_uuid


def test_watcher_llm_mode_promotes_without_exact_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    note_uuid = str(uuid4())
    note_path = vault_root / "Notes" / "Evergreen.md"
    _write_note(
        note_path,
        uuid=note_uuid,
        instruction="Make this note evergreen please",
        action_label="Promote this card to evergreen status",
    )

    actions_path = _panel_actions_file(tmp_path)
    outbox_path = tmp_path / "index-outbox.jsonl"
    snapshot_path = tmp_path / "snapshot.json"

    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_chat_client",
        lambda intent: _StubChatClient(json.dumps({"actions": [{"id": "promote.evergreen", "reason": "panel intent"}]})),
    )

    env = {
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "PANEL_ACTIONS_PATH": str(actions_path),
        "INDEX_OUTBOX_PATH": str(outbox_path),
        "PANEL_AGENT_DECIDER": "llm",
        "WATCHER_AUTO_EXEC": "1",
    }
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "vault-watcher-run",
            "--vault-root",
            str(vault_root),
            "--snapshot-path",
            str(snapshot_path),
            "--max-notes",
            "5",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert "panel_promotions=1" in result.output
    assert "errors=0" in result.output

    events = _read_outbox(outbox_path)
    topics = {entry.get("event") for entry in events}
    assert "promote.intent.created" in topics
    promote = next(e for e in events if e.get("event") == "promote.intent.created")
    assert promote.get("payload", {}).get("note", {}).get("uuid") == note_uuid
