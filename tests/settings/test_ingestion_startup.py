"""SETTINGS-01 / SET-1: vault-authored settings take effect at startup or fail loud.

Audit F1: the md→runtime settings pipeline was invoked only by the manual CLI and
CI, so running services silently served pydantic code defaults. These tests drive
the production ingestion entrypoint (``ingest_settings``) — the one the API
lifespan, watcher, and worker call — rather than ``compile_all`` in isolation.

Source: docs/SETTINGS_SPINE/WIRE_SETTINGS_INGESTION.md
"""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from app.settings import compiler, runtime
from app.settings.ingestion import (
    STATE_DEGRADED,
    STATE_OK,
    get_settings_ingestion_state,
    ingest_settings,
    reset_settings_ingestion_state,
)
from app.watcher.settings_delta import handle_settings_source_delta
from app.watcher.state import WatcherState
import app.watcher.registry as registry
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _source_md(log_level: str) -> str:
    return (
        "---\n"
        "uuid: 00000000-0000-0000-0000-0000000000aa\n"
        "title: Global Settings\n"
        "origin: user\n"
        "---\n"
        "## Runtime\n"
        "```yaml settings\n"
        f"log_level: {log_level}\n"
        "```\n"
    )


_INVALID_SOURCE_MD = (
    "---\n"
    "uuid: 00000000-0000-0000-0000-0000000000aa\n"
    "title: Global Settings\n"
    "origin: user\n"
    "---\n"
    "## Runtime\n"
    "```yaml settings\n"
    "log_level: [unterminated\n"
    "```\n"
)


def _select_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Bind a selected vault via VAULT_ROOT and return its @Settings source dir."""
    vault_root = tmp_path / "vault"
    source_dir = vault_root / "@Settings"
    source_dir.mkdir(parents=True)
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    return source_dir


@pytest.fixture
def sandbox_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Select a tmp vault, redirect the runtime projection at a tmp sandbox, and
    reset the in-memory bundle + ingestion state so each test starts clean. Ingestion
    resolves the source dir from the selected vault (VAULT_ROOT), not compiler.VAULT."""
    source_dir = _select_vault(tmp_path, monkeypatch)
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(tmp_path / "settings-reload.json"))
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    reset_settings_ingestion_state()
    try:
        yield source_dir
    finally:
        reset_settings_ingestion_state()


def test_service_startup_loads_vault_settings(sandbox_sources: Path) -> None:
    """Startup ingestion makes get_settings_bundle() see vault values, not code
    defaults, when a vault with settings sources is selected."""
    (sandbox_sources / "global.md").write_text(_source_md("DEBUG"), encoding="utf-8")

    state = ingest_settings(reason="test_startup")

    assert state.state == STATE_OK
    assert state.source == "vault"
    # The vault edit (DEBUG) wins over the pydantic default (INFO): the running
    # service now honors the vault, which is the whole point of F1.
    assert runtime.get_settings_bundle().global_.log_level == "DEBUG"


def test_no_vault_boot_loads_defaults_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no vault selected, ingestion reports no_vault on defaults — no error,
    no ./vault fallback, bundle builds from typed defaults (no-vault boot preserved)."""
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    monkeypatch.chdir(tmp_path)
    reset_settings_ingestion_state()

    state = ingest_settings(reason="test_no_vault")

    assert state.state == "no_vault"
    assert state.source == "defaults"
    assert state.error is None
    assert runtime.get_settings_bundle().global_.log_level == "INFO"  # typed default
    assert not (tmp_path / "vault").exists()
    reset_settings_ingestion_state()


def test_settings_edit_reloads_bundle(sandbox_sources: Path) -> None:
    """Editing a settings source while running updates the effective bundle within
    one watcher-tick reload, via the existing settings.changed bus."""
    source = sandbox_sources / "global.md"
    source.write_text(_source_md("DEBUG"), encoding="utf-8")
    ingest_settings(reason="test_startup")
    assert runtime.get_settings_bundle().global_.log_level == "DEBUG"

    # Operator edits the source file; the watcher tick routes it through the
    # production source-delta path.
    source.write_text(_source_md("WARNING"), encoding="utf-8")
    result = handle_settings_source_delta(rel_path=Path("@Settings/global.md"))

    assert result.is_source is True
    assert result.reloaded is True
    assert runtime.get_settings_bundle().global_.log_level == "WARNING"


def test_invalid_settings_degrade_loud(sandbox_sources: Path) -> None:
    """An invalid edit degrades to the last-valid bundle and surfaces
    settings.state=degraded_last_valid; code defaults are never substituted while a
    last-valid bundle exists."""
    source = sandbox_sources / "global.md"
    source.write_text(_source_md("DEBUG"), encoding="utf-8")
    ingest_settings(reason="test_startup")
    assert get_settings_ingestion_state().state == STATE_OK

    # Break the source: invalid YAML.
    source.write_text(_INVALID_SOURCE_MD, encoding="utf-8")
    result = handle_settings_source_delta(rel_path=Path("@Settings/global.md"))

    assert result.is_source is True
    assert result.reloaded is False
    state = get_settings_ingestion_state()
    assert state.state == STATE_DEGRADED
    assert state.error
    # Last-valid bundle is preserved — NOT reset to the code default.
    assert runtime.get_settings_bundle().global_.log_level == "DEBUG"


def test_non_source_delta_is_ignored(sandbox_sources: Path) -> None:
    """A non-settings file change is not treated as a settings source reload."""
    result = handle_settings_source_delta(rel_path=Path("notes/some-note.md"))
    assert result.is_source is False
    assert result.reloaded is False


def test_selected_dev_channel_vault_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A channel-specific binding is a selected vault, not a no-vault boot."""
    vault_root = tmp_path / "dev-vault"
    source_dir = vault_root / "@Settings"
    source_dir.mkdir(parents=True)
    (source_dir / "global.md").write_text(_source_md("DEBUG"), encoding="utf-8")
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("VAULT_ROOT_DEV", str(vault_root))
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.setenv("SETTINGS_RELOAD_SIGNAL_PATH", str(tmp_path / "settings-reload.json"))
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    reset_settings_ingestion_state()

    state = ingest_settings(reason="test_dev_channel")

    assert state.state == STATE_OK
    assert runtime.get_settings_bundle().global_.log_level == "DEBUG"


def test_agents_subtree_is_a_settings_source(sandbox_sources: Path) -> None:
    """An agent override alone must trigger ingestion (compiler supports it)."""
    agents_dir = sandbox_sources / "agents"
    agents_dir.mkdir()
    (agents_dir / "custom.md").write_text(
        "## Runtime\n```yaml settings\nenabled: true\n```\n", encoding="utf-8"
    )

    state = ingest_settings(reason="test_agents_only")

    assert state.state == STATE_OK
    assert runtime.get_settings_bundle().agents["custom"] == {"enabled": True}


def test_watcher_signal_reloads_another_process_projection(
    sandbox_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A watcher signal makes a separately cached service rebuild from vault md."""
    source = sandbox_sources / "global.md"
    source.write_text(_source_md("DEBUG"), encoding="utf-8")
    ingest_settings(reason="api_startup")
    source.write_text(_source_md("WARNING"), encoding="utf-8")
    handle_settings_source_delta(rel_path=Path("@Settings/global.md"))

    # Simulate API/worker's independent process-local runtime projection/cache.
    other_runtime = tmp_path / "other-runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", other_runtime)
    monkeypatch.setattr(runtime, "RUNTIME", other_runtime)
    monkeypatch.setattr(runtime, "_CURRENT", None)
    monkeypatch.setattr(runtime, "_LAST_EXTERNAL_SIGNAL_GENERATION", None)

    assert runtime.get_settings_bundle().global_.log_level == "WARNING"


def test_registry_watcher_routes_settings_sources_outside_note_scope(
    sandbox_sources: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production registry scan reloads @Settings even under a narrowed scope."""
    initialize_test_vault(sandbox_sources.parent)
    source = sandbox_sources / "global.md"
    source.write_text(_source_md("DEBUG"), encoding="utf-8")
    notes_dir = sandbox_sources.parent / "Notes"
    notes_dir.mkdir()
    (notes_dir / "note.md").write_text("# note\n", encoding="utf-8")
    config_path = tmp_path / "watchers.yaml"
    config_path.write_text(
        "watchers:\n  - name: panel\n    scope_glob: 'Notes/**'\n    emit_event: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(sandbox_sources.parent))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "Notes/**")
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "watcher-state"))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    cfg = registry.load_registry_config(config_path)
    state = WatcherState()

    summary = registry._run_spec_tick(cfg, cfg.specs[0], state, now=time.time())
    assert summary.get("settings_source_reloads_in_tick") == 1
    assert runtime.get_settings_bundle().global_.log_level == "DEBUG"

    source.write_text(_source_md("WARNING"), encoding="utf-8")
    time.sleep(0.02)
    registry._run_spec_tick(cfg, cfg.specs[0], state, now=time.time())

    assert runtime.get_settings_bundle().global_.log_level == "WARNING"
