from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent import execute_panel_intent, run_panel_intent_for_note
from app.agents.panel_agent.wiring import DEFAULT_PANEL_ACTION_WIRING_PATH, get_action_wiring, load_action_wiring
from app.store import object_store as object_store_module
from app.objects import DomainObject, ObjectStore

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
    trust_verb: APPLY
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
def clear_store() -> None:
    object_store_module._MEMORY_STORE.clear()


def test_default_wiring_used_when_no_env_or_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    markdown = """%% AI:Start %%
## AI-instruktion
Promote this note.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    events = run_panel_intent_for_note(note_uuid, trace_id="trace-default")
    runtime_result = execute_panel_intent(events[0], outbox_path=outbox_path)
    topics = {getattr(ev, "event", "") for ev in runtime_result.emitted_events}

    assert "promote.intent.created" in topics
    assert get_action_wiring().get("promote.evergreen") == "promote.intent.created"


def test_env_wiring_overrides_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note_uuid = str(uuid4())
    outbox_path = tmp_path / "index-outbox.jsonl"
    settings_path = _settings_file(tmp_path)
    vault_root = tmp_path / "vault"
    vault_cfg = vault_root / "System" / "Config"
    vault_cfg.mkdir(parents=True, exist_ok=True)
    (vault_cfg / "panel-action-wiring.yaml").write_text(
        """actions:
  - id: promote.evergreen
    target_event: vault.event
""",
        encoding="utf-8",
    )
    env_wiring = tmp_path / "env-wiring.yaml"
    env_wiring.write_text(
        """actions:
  - id: promote.evergreen
    target_event: env.event
""",
        encoding="utf-8",
    )
    markdown = """%% AI:Start %%
## AI-instruktion
Promote this note.
## AI-åtgärder
- [x] Gör denna anteckning evergreen
%% AI:End %%
"""
    _seed_note(note_uuid, markdown)

    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(settings_path))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("PANEL_ACTION_WIRING_PATH", str(env_wiring))
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.setattr("app.agents.panel_agent.agent.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    wiring = get_action_wiring()
    assert wiring.get("promote.evergreen") == "env.event"


def test_vault_wiring_used_when_env_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    vault_cfg = vault_root / "System" / "Config"
    vault_cfg.mkdir(parents=True, exist_ok=True)
    wiring_path = vault_cfg / "panel-action-wiring.yaml"
    wiring_path.write_text(
        """actions:
  - id: promote.evergreen
    target_event: vault.event
""",
        encoding="utf-8",
    )

    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))

    wiring = get_action_wiring()
    assert wiring.get("promote.evergreen") == "vault.event"


def test_set_but_missing_vault_root_does_not_abort_wiring_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale HTTP VAULT_ROOT (set-but-missing) must not abort wiring discovery.

    Regression for #2476: optional wiring discovery routes through
    ``resolve_optional_vault_root()``, which raises ``VaultRootMisconfiguredError``
    on a set-but-missing ``VAULT_ROOT``. Wiring config has a DEFAULT fallback, so
    a stale UI binding must not stop watcher/worker-bound background panel
    execution (the worker threads its own resolved vault into
    ``execute_panel_intent`` separately). ``get_action_wiring()`` must fall back
    to the default rather than propagate the misconfiguration error.
    """
    missing_vault = tmp_path / "does-not-exist"
    assert not missing_vault.exists()

    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)
    monkeypatch.setenv("VAULT_ROOT", str(missing_vault))

    # Must not raise VaultRootMisconfiguredError; falls through to the default.
    wiring = get_action_wiring()
    assert wiring.get("promote.evergreen") == "promote.intent.created"


def test_invalid_yaml_warns_and_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text("not: [valid", encoding="utf-8")

    monkeypatch.setenv("PANEL_ACTION_WIRING_PATH", str(bad_path))
    monkeypatch.delenv("VAULT_ROOT", raising=False)

    wiring = get_action_wiring()
    assert wiring.get("promote.evergreen") == "promote.intent.created"
    captured = capsys.readouterr().err
    assert "Warning" in captured


def test_missing_required_keys_warns_and_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(
        """actions:
  - id: ""  # missing
    target_event: ""
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("PANEL_ACTION_WIRING_PATH", str(bad_path))
    monkeypatch.delenv("VAULT_ROOT", raising=False)

    wiring = get_action_wiring()
    assert wiring.get("promote.evergreen") == "promote.intent.created"
    captured = capsys.readouterr().err
    assert "Warning" in captured


def test_load_action_wiring_respects_path_argument(tmp_path: Path) -> None:
    path = tmp_path / "custom.yaml"
    path.write_text(
        """actions:
  - id: promote.evergreen
    target_event: custom.event
""",
        encoding="utf-8",
    )
    wiring = load_action_wiring(path)
    assert wiring.get("promote.evergreen") == "custom.event"


def test_default_file_is_accessible() -> None:
    wiring = load_action_wiring(DEFAULT_PANEL_ACTION_WIRING_PATH)
    assert wiring.get("promote.evergreen") == "promote.intent.created"
