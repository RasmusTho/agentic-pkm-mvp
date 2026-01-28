from __future__ import annotations

import uuid
from pathlib import Path
from textwrap import dedent

import pytest

import app.watcher.registry as registry
from app.agents.panel_agent.policy import watcher_panel_candidate
from scripts.yaml_roundtrip import load_frontmatter

pytestmark = pytest.mark.not_pg


def _write_registry_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: "${VAULT_INBOX_DIR_REL}/**"
                debounce_ms: 150
                rate_limit_per_min: 120
                emit_event: "panel.scan.requested"
              - name: ingest
                scope_glob: "${VAULT_INBOX_DIR_REL}/**"
                debounce_ms: 150
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def test_watcher_registry_uses_env_paths_heals_uuid_and_applies_panel_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    inbox = vault_root / "📥 Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    no_uuid_note = inbox / "no_uuid.md"
    no_uuid_note.write_text(
        dedent(
            """\
            ---
            title: Missing UUID
            ---
            Content without a uuid yet.
            """
        ),
        encoding="utf-8",
    )

    panel_candidate = inbox / "panel_candidate.md"
    panel_candidate.write_text(
        dedent(
            """\
            ---
            title: Panel candidate
            ---
            %% AI:Start %%
            ## AI work
            - [ ] Surface watch notes
            %% AI:End %%
            """
        ),
        encoding="utf-8",
    )

    panel_never = inbox / "panel_never.md"
    panel_never.write_text(
        dedent(
            """\
            ---
            title: Panel opt-out
            ai_panel_auto_run: never
            ---
            %% AI:Start %%
            ## AI work
            - [ ] No autopanel
            %% AI:End %%
            """
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)

    env = {
        "STORE_BACKEND": "memory",
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": str(vault_root),
        "VAULT_INBOX_DIR_REL": "📥 Inbox",
        "WATCHER_AUTO_EXEC": "1",
        "INDEX_OUTBOX_PATH": str(tmp_path / "index-outbox.jsonl"),
        "WATCHER_STATE_DIR": str(tmp_path / "state"),
        "WATCHER_HEARTBEAT_PATH": str(tmp_path / "heartbeat.json"),
        "WATCHER_TICK_LOG_PATH": str(tmp_path / "tick-log.jsonl"),
        "WATCHER_SUMMARY_INTERVAL": "0",
        "WATCHER_TICK_SLEEP_SECONDS": "0.05",
        "WATCHER_DEBOUNCE_MS": "0",
        "WATCHER_STOP_FILE": str(tmp_path / "watcher_stop"),
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": '{"type":"note","confidence":0.95}',
        "PANEL_AGENT_DECIDER": "rule",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    cfg = registry.load_registry_config(config_path)
    assert cfg.vault_path == vault_root
    assert cfg.scope_glob == "📥 Inbox/**"
    assert all(spec.scope_glob == "📥 Inbox/**" for spec in cfg.specs)

    registry.run_registry_forever(config_path, max_ticks=2)

    updated_frontmatter, _ = load_frontmatter(no_uuid_note.read_text(encoding="utf-8"))
    note_uuid = str((updated_frontmatter or {}).get("uuid") or "").strip()
    assert note_uuid
    uuid.UUID(note_uuid)

    candidate_text = panel_candidate.read_text(encoding="utf-8")
    candidate_frontmatter, _ = load_frontmatter(candidate_text)
    assert watcher_panel_candidate(candidate_frontmatter or {}, candidate_text)

    never_text = panel_never.read_text(encoding="utf-8")
    never_frontmatter, _ = load_frontmatter(never_text)
    assert not watcher_panel_candidate(never_frontmatter or {}, never_text)
