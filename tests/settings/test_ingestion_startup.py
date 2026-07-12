"""SETTINGS-01 / SET-1: vault-authored settings take effect at startup or fail loud.

Audit F1: the md→runtime settings pipeline was invoked only by the manual CLI and
CI, so running services silently served pydantic code defaults. These tests drive
the production ingestion entrypoint (``ingest_settings``) — the one the API
lifespan, watcher, and worker call — rather than ``compile_all`` in isolation.

Source: docs/SETTINGS_SPINE/WIRE_SETTINGS_INGESTION.md
"""

from __future__ import annotations

from pathlib import Path

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
