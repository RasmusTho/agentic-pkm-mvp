from __future__ import annotations

import importlib
import uuid
from pathlib import Path
from textwrap import dedent

import pytest

import app.observability.status_service as status_service
import app.watcher.registry as registry
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR, seed_vault_test_notes
from app.runtime.runtime_loop import RuntimeLoopConfig, run_once
from app.objects import ObjectStore
from app.stores import reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg

PROMOTE_UUID = "11111111-1111-4111-8111-111111111111"


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


def _seed_registry_vault(vault_root: Path) -> dict[str, Path]:
    inbox = vault_root / "capture"
    notes = vault_root / "notes"
    obsidian = vault_root / ".obsidian"
    inbox.mkdir(parents=True, exist_ok=True)
    notes.mkdir(parents=True, exist_ok=True)
    obsidian.mkdir(parents=True, exist_ok=True)

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

    return {
        "no_uuid": no_uuid_note,
        "candidate": panel_candidate,
        "never": panel_never,
        "proactive": proactive_note,
        "ineligible": ineligible_note,
    }


def _run_registry_variant(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    extra_env: dict[str, str],
) -> dict[str, object]:
    reset_store_backends()
    vault_root = tmp_path / name / "vault"
    initialize_test_vault(vault_root)
    paths = _seed_registry_vault(vault_root)
    config_path = tmp_path / name / "watchers.yaml"
    _write_registry_config(config_path)

    env = {
        "PKM_SETTINGS_PROFILE": "lab",
        "STORE_BACKEND": "memory",
        "WATCHER_ENABLE": "1",
        "WATCHER_VAULT_PATH": str(vault_root),
        "VAULT_INBOX_DIR_REL": "capture",
        "WATCHER_AUTO_EXEC": "1",
        "INDEX_OUTBOX_PATH": str(tmp_path / name / "index-outbox.jsonl"),
        "WATCHER_STATE_DIR": str(tmp_path / name / "state"),
        "WATCHER_HEARTBEAT_PATH": str(tmp_path / name / "heartbeat.json"),
        "WATCHER_TICK_LOG_PATH": str(tmp_path / name / "tick-log.jsonl"),
        "WATCHER_SUMMARY_INTERVAL": "0",
        "WATCHER_TICK_SLEEP_SECONDS": "0.05",
        "WATCHER_DEBOUNCE_MS": "0",
        "WATCHER_STOP_FILE": str(tmp_path / name / "watcher_stop"),
        "LLM_PROVIDER": "mock",
        "LLM_MOCK_RESPONSE": '{"type":"note","confidence":0.95}',
        "PANEL_AGENT_DECIDER": "rule",
    }
    env.update(extra_env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    registry.run_registry_forever(config_path, max_ticks=2)
    summaries = registry.run_registry_once(config_path)
    no_uuid_frontmatter, _ = load_frontmatter(paths["no_uuid"].read_text(encoding="utf-8"))

    return {
        "summaries": summaries,
        "uuid_healed": str((no_uuid_frontmatter or {}).get("uuid") or "").strip(),
        "candidate_keeps_panel": "%% AI:Start %%" in paths["candidate"].read_text(encoding="utf-8"),
        "never_unchanged": "<!--ai:assist:start-->" not in paths["never"].read_text(encoding="utf-8"),
        "ineligible_unchanged": "%% AI %%" not in paths["ineligible"].read_text(encoding="utf-8"),
    }


def test_registry_watcher_metamorphic_env_variants_keep_same_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _run_registry_variant(tmp_path=tmp_path, monkeypatch=monkeypatch, name="baseline", extra_env={})
    scoped = _run_registry_variant(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        name="scoped",
        extra_env={
            "WATCHER_SCOPE_GLOB": "capture/*.md,notes/*.md",
            "WATCHER_TICK_SLEEP_SECONDS": "0.2",
            "WATCHER_DEBOUNCE_MS": "10",
        },
    )

    for result in (baseline, scoped):
        assert result["uuid_healed"]
        uuid.UUID(str(result["uuid_healed"]))
        assert result["candidate_keeps_panel"] is True
        assert result["never_unchanged"] is True
        assert result["ineligible_unchanged"] is True

    assert baseline["summaries"].keys() == scoped["summaries"].keys()


@pytest.mark.e2e
def test_runtime_loop_cold_rebuild_restores_seeded_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_store_backends()
    outbox_path = tmp_path / "outbox.jsonl"

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_ACTIONS_PATH", str(Path(__file__).resolve().parents[2] / "docs/settings/panel-actions.md"))
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")

    importlib.reload(status_service)

    vault_root = tmp_path / "vault"
    seed_vault_test_notes(vault_root=vault_root)

    snapshot_path = tmp_path / "snapshot.json"
    cfg = RuntimeLoopConfig(
        snapshot_path=snapshot_path,
        max_notes=50,
        force=True,
        dry_run=False,
        run_panels=True,
        run_promotion_consumer=True,
        outbox_path=outbox_path,
    )

    first = run_once(vault_root / DEFAULT_TARGET_SUBDIR, cfg)
    assert first.promotion.get("applied", 0) >= 1

    promoted_path = vault_root / DEFAULT_TARGET_SUBDIR / DEFAULT_FOLDER_NAME / "evergreen-strategy.md"
    frontmatter, _ = load_frontmatter(promoted_path.read_text(encoding="utf-8"))
    assert frontmatter.get("review_state") == "reviewed"
    assert frontmatter.get("maturity") == "evergreen"

    reset_store_backends()
    importlib.reload(status_service)
    outbox_path.unlink(missing_ok=True)
    snapshot_path.unlink(missing_ok=True)
    Path(str(snapshot_path) + ".outbox_cursor.json").unlink(missing_ok=True)

    second = run_once(vault_root / DEFAULT_TARGET_SUBDIR, cfg)
    assert second.watcher.get("ingested", 0) >= 1
    assert second.watcher.get("errors", 0) == 0

    store = ObjectStore()
    promoted = store.get_object(PROMOTE_UUID)
    assert promoted is not None
    payload = promoted.payload or {}
    core6 = payload.get("core6") or {}
    assert core6.get("review_state") == "reviewed"
    assert str(payload.get("raw_text") or "").find("maturity: evergreen") >= 0
