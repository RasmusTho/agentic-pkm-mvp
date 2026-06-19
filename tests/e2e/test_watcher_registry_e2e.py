
import json
import subprocess
import uuid
from pathlib import Path
from textwrap import dedent

import pytest

import app.watcher.registry as registry
from app.agents.panel_agent.policy import watcher_panel_candidate_for_path
from app.cli.uat import seed_vault_test_notes
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from scripts.yaml_roundtrip import load_frontmatter

pytestmark = pytest.mark.not_pg


def _initialize_design_handoff_vault(vault_root: Path, app_local_path: Path) -> None:
    result = VaultManager(
        app_local_store=AppLocalSettingsStore(app_local_path)
    ).initialize_vault(vault_root, machine_role="testNode", remember=False)
    assert result.context.status == "selected"


def _write_registry_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: panel
                scope_glob: ""
                debounce_ms: 150
                rate_limit_per_min: 120
                emit_event: "panel.scan.requested"
              - name: ingest
                scope_glob: ""
                debounce_ms: 150
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def _derive_startup_scope_glob(vault_root: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            "bash",
            "-lc",
            (
                "set -euo pipefail; "
                "source scripts/lib/start_full_system_env.sh; "
                "unset VAULT_SYSTEM_DIR_REL VAULT_INBOX_DIR_REL VAULT_DESK_DIR_REL WATCHER_SCOPE_GLOB; "
                "apply_start_full_system_vault_defaults \"$VAULT_ROOT\"; "
                "derive_start_full_system_scope_glob"
            ),
        ],
        cwd=repo_root,
        env={"VAULT_ROOT": str(vault_root)},
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_watcher_registry_uses_env_paths_heals_uuid_and_applies_panel_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    inbox_rel = "capture"
    inbox = vault_root / inbox_rel
    inbox.mkdir(parents=True, exist_ok=True)
    notes = vault_root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    obsidian = vault_root / ".obsidian"
    obsidian.mkdir(parents=True, exist_ok=True)
    _initialize_design_handoff_vault(vault_root, tmp_path / "app-local.md")

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

    panel_candidate = notes / "panel_candidate.md"
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

    panel_never = notes / "panel_never.md"
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

    proactive_note = notes / "proactive.md"
    proactive_note.write_text(
        dedent(
            """\
            ---
            title: Proactive candidate
            ---
            This note has no AI fence yet.
            """
        ),
        encoding="utf-8",
    )

    ineligible_note = obsidian / "settings.md"
    ineligible_note.write_text(
        dedent(
            """\
            ---
            title: Ineligible
            ---
            This lives under .obsidian and should not get an AI panel.
            """
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)

    env = {
        "PKM_SETTINGS_PROFILE": "lab",
        "STORE_BACKEND": "memory",
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": str(vault_root),
        "VAULT_INBOX_DIR_REL": inbox_rel,
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
    assert cfg.scope_glob == "*.md,**/*.md"
    assert all(spec.scope_glob == "*.md,**/*.md" for spec in cfg.specs)

    registry.run_registry_forever(config_path, max_ticks=2)

    updated_frontmatter, _ = load_frontmatter(no_uuid_note.read_text(encoding="utf-8"))
    note_uuid = str((updated_frontmatter or {}).get("uuid") or "").strip()
    assert note_uuid
    uuid.UUID(note_uuid)

    candidate_text = panel_candidate.read_text(encoding="utf-8")
    candidate_frontmatter, _ = load_frontmatter(candidate_text)
    assert watcher_panel_candidate_for_path(panel_candidate, candidate_frontmatter or {}, candidate_text)
    assert "<!--ai:assist:start-->" not in candidate_text

    never_text = panel_never.read_text(encoding="utf-8")
    never_frontmatter, _ = load_frontmatter(never_text)
    assert not watcher_panel_candidate_for_path(panel_never, never_frontmatter or {}, never_text)

    proactive_text = proactive_note.read_text(encoding="utf-8")
    assert "%% AI %%" not in proactive_text
    assert "<!--ai:assist:start-->" not in proactive_text

    ineligible_text = ineligible_note.read_text(encoding="utf-8")
    assert "%% AI %%" not in ineligible_text

    outbox_records = [
        json.loads(line)
        for line in Path(env["INDEX_OUTBOX_PATH"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    topics = [rec.get("event") for rec in outbox_records]
    assert "panel.scan.requested" in topics
    assert "ingest.vault.changed" in topics


def test_watcher_registry_uses_full_system_layout_scope_for_uat_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    inbox_rel = "capture"
    system_rel = "config"
    (vault_root / system_rel).mkdir(parents=True, exist_ok=True)
    (vault_root / "notes").mkdir(parents=True, exist_ok=True)
    (vault_root / system_rel / "vault.layout.md").write_text(
        dedent(
            f"""\
            ---
            system_folder: {system_rel}
            inbox_folder: {inbox_rel}
            desk_folder: workbench
            ---
            """
        ),
        encoding="utf-8",
    )
    _initialize_design_handoff_vault(vault_root, tmp_path / "app-local.md")

    seed_vault_test_notes(vault_root=vault_root, target_subdir=inbox_rel)

    scoped_no_uuid = vault_root / inbox_rel / "no_uuid.md"
    scoped_no_uuid.write_text(
        dedent(
            """\
            ---
            title: Scoped inbox note
            ---
            This note should be healed because it lives inside the startup-derived watcher scope.
            """
        ),
        encoding="utf-8",
    )

    outside_note = vault_root / "notes" / "outside_no_uuid.md"
    outside_note.write_text(
        dedent(
            """\
            ---
            title: Outside watcher scope
            ---
            This note should stay untouched because the full-system scope is inbox-bound.
            """
        ),
        encoding="utf-8",
    )

    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)
    scope_glob = _derive_startup_scope_glob(vault_root)

    env = {
        "PKM_SETTINGS_PROFILE": "lab",
        "STORE_BACKEND": "memory",
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": str(vault_root),
        "VAULT_INBOX_DIR_REL": inbox_rel,
        "WATCHER_SCOPE_GLOB": scope_glob,
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
    assert cfg.scope_glob == "capture/*.md,capture/**/*.md"
    assert all(spec.scope_glob == "capture/*.md,capture/**/*.md" for spec in cfg.specs)

    registry.run_registry_forever(config_path, max_ticks=2)

    scoped_frontmatter, _ = load_frontmatter(scoped_no_uuid.read_text(encoding="utf-8"))
    scoped_uuid = str((scoped_frontmatter or {}).get("uuid") or "").strip()
    assert scoped_uuid
    uuid.UUID(scoped_uuid)

    outside_frontmatter, _ = load_frontmatter(outside_note.read_text(encoding="utf-8"))
    assert not str((outside_frontmatter or {}).get("uuid") or "").strip()

    outbox_records = [
        json.loads(line)
        for line in Path(env["INDEX_OUTBOX_PATH"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    topics = [rec.get("event") for rec in outbox_records]
    assert "panel.scan.requested" in topics
    assert "ingest.vault.changed" in topics
    assert all("outside_no_uuid.md" not in json.dumps(rec, ensure_ascii=False) for rec in outbox_records)
