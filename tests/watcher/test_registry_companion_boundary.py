"""Real registry -> queued worker -> canonical index companion boundary (#5912)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.events.types import INGEST_VAULT_CHANGED
from app.services.companion_note import companion_path, read_companion, write_companion
from app.services import companion_note
from app.stores.memory import MemoryVectorIndex
from app.watcher import registry
from app.watcher.settings_delta import SettingsSourceDeltaResult
from app.watcher.state import WatcherState
from app.workers import outbox_worker
from tests.watcher.test_registry_incremental_scan import _load_state, _make_cfg
from tests.workers.test_companion_source_boundary import (
    SOURCE_UUID,
    SYSTEM_DIR,
    assert_source_publication,
    boundary_index as _boundary_index_fixture,
    write_source,
)
from tests.workers.test_outbox_worker_consumes_ingest import (
    FakeOutboxConn,
    fake_conn as _fake_conn_fixture,
)

pytestmark = pytest.mark.not_pg
boundary_index = _boundary_index_fixture
fake_conn = _fake_conn_fixture


def _tick(cfg: registry.RegistryConfig, spec: registry.WatcherSpec, now: float) -> WatcherState:
    state = _load_state(cfg, spec)
    summary = registry._run_spec_tick(cfg, spec, state, now=now)
    assert summary["errors_in_tick"] == 0
    assert summary["scan_complete"] is True
    return _load_state(cfg, spec)


def _consume(conn: FakeOutboxConn) -> None:
    for _ in range(100):
        if not conn.undelivered_count():
            return
        result = outbox_worker.run_once()
        assert result.state == "processed"
    raise AssertionError("registry events did not drain")


@pytest.mark.parametrize("location", ["canonical", "legacy"])
def test_registry_worker_preserves_source_body_after_companion_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    fake_conn: FakeOutboxConn, location: str,
) -> None:
    cfg, original_spec, vault = _make_cfg(tmp_path, max_files=100)
    spec = replace(original_spec, emit_event=INGEST_VAULT_CHANGED)
    source = write_source(vault)
    source_bytes = source.read_bytes()
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setattr(registry, "_has_db_outbox_env", lambda: True)
    _tick(cfg, spec, 1_700_000_000.0)
    _consume(fake_conn)
    assert_source_publication(boundary_index)

    canonical = vault / companion_path(SOURCE_UUID, vault)
    companion = read_companion(vault, SOURCE_UUID)
    assert companion is not None
    assert companion.uuid == SOURCE_UUID
    if location == "legacy":
        legacy = vault / f"_system/companions/{SOURCE_UUID}.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(canonical.read_bytes())

    for cycle in range(1, 4):
        write_companion(vault, replace(companion, last_ingested=f"2026-10-10T00:0{cycle}:00Z"))
        _tick(cfg, spec, 1_700_000_000.0 + cycle)
        _consume(fake_conn)
        assert_source_publication(boundary_index)
        assert source.read_bytes() == source_bytes
        assert read_companion(vault, SOURCE_UUID).source_ref == "Inbox/source.md"
    queued_sources = {
        json.loads(row["payload"])["payload"]["relative_path"]
        for row in fake_conn.rows.values()
        if row["topic"] == INGEST_VAULT_CHANGED
    }
    assert queued_sources == {"Inbox/source.md"}


def test_registry_scan_excludes_companions_and_keeps_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=100)
    write_source(vault)
    for rel in (f"{SYSTEM_DIR}/companions/{SOURCE_UUID}.md", f"_system/companions/{SOURCE_UUID}.md"):
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nuuid: ignored-companion\n---\n", encoding="utf-8")
    # Siblings in the system folder stay eligible; this is not a whole-folder
    # exclusion. Settings sources continue to use the actual reload call site.
    ordinary = vault / SYSTEM_DIR / "ordinary.md"
    ordinary.write_text("system-folder source\n", encoding="utf-8")
    settings = vault / "settings/watchers.md"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("watcher settings\n", encoding="utf-8")
    # Resolve the nested system folder through a real supported layout input,
    # rather than the cheap environment override, and count predicate I/O.
    layout = vault / SYSTEM_DIR / "vault.layout.md"
    layout.write_text(
        f"---\nsystem_folder: {SYSTEM_DIR}\ninbox_folder: Inbox\ndesk_folder: Workbench\n---\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL")
    monkeypatch.setenv("VAULT_LAYOUT_NOTE_REL", f"{SYSTEM_DIR}/vault.layout.md")
    predicate_resolutions: list[Path] = []
    original_resolver = companion_note.resolve_vault_system_dir_rel_or_default

    def resolve_system_dir(root: Path) -> str:
        predicate_resolutions.append(root)
        return original_resolver(root)

    monkeypatch.setattr(companion_note, "resolve_vault_system_dir_rel_or_default", resolve_system_dir)
    reloaded: list[Path] = []

    def reload_settings(*, rel_path: Path, vault_root: Path) -> SettingsSourceDeltaResult:
        reloaded.append(rel_path)
        return SettingsSourceDeltaResult(is_source=True, reloaded=True)

    monkeypatch.setattr(registry, "handle_settings_source_delta", reload_settings)
    state = _tick(cfg, spec, 1_700_000_000.0)
    expected = {"Inbox/source.md", f"{SYSTEM_DIR}/ordinary.md", "settings/watchers.md", f"{SYSTEM_DIR}/vault.layout.md"}
    assert state.file_paths() == expected
    assert reloaded == [Path("settings/watchers.md")]
    assert predicate_resolutions == []
    observed = {rel.as_posix() for rel, _mtime, _path in registry._scan_markdown_many(vault, [vault], spec.scope_glob)}
    assert observed == expected
    assert predicate_resolutions == []


@pytest.mark.parametrize("checkpoint", ["sqlite", "legacy", "resumed", "static-canonical", "static-legacy"])
def test_checkpoint_cleanup_preserves_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary_index: MemoryVectorIndex,
    fake_conn: FakeOutboxConn, checkpoint: str,
) -> None:
    cfg, original_spec, vault = _make_cfg(tmp_path, max_files=100)
    spec = replace(original_spec, emit_event=INGEST_VAULT_CHANGED)
    write_source(vault)
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setattr(registry, "_has_db_outbox_env", lambda: True)
    state = _tick(cfg, spec, 1_700_000_000.0)
    _consume(fake_conn)
    canonical = vault / companion_path(SOURCE_UUID, vault)
    legacy = vault / f"_system/companions/{SOURCE_UUID}.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(canonical.read_bytes())
    retained = {path: path.read_bytes() for path in (canonical, legacy)}
    historical_paths = [path.relative_to(vault).as_posix() for path in retained]
    historical_paths.append(f"{SYSTEM_DIR}/companions/already-missing.md")
    if checkpoint == "legacy":
        state = WatcherState(files={"Inbox/source.md": state.file_entry("Inbox/source.md")})
    for rel_path in historical_paths:
        state.update_file_state(rel_path, mtime=1.0, content_hash="historical-companion")
    if checkpoint.startswith("static-"):
        companion_root = canonical.parent if checkpoint == "static-canonical" else legacy.parent
        spec = replace(spec, scope_glob=f"{companion_root.relative_to(vault).as_posix()}/**/*.md")
        cfg.max_elapsed_ms_per_tick = 50
    if checkpoint == "resumed":
        state.scan_in_progress = True
        state.scan_root_index = 0
        state.scan_stack = [
            {"dir": ".", "after": "Runtime"},
            {"dir": canonical.parent.relative_to(vault).as_posix(), "after": ""},
        ]
    state.save(registry._state_path(cfg.state_dir, spec.name))

    # Existing clean-scan pruning removes only watcher observations. It must
    # never translate a companion's shared UUID into a source-delete effect.
    cleaned = _tick(cfg, spec, 1_700_000_001.0)
    _consume(fake_conn)
    if checkpoint == "resumed":
        # Finish one fresh generation after draining the retained cursor.
        cleaned = _tick(cfg, spec, 1_700_000_002.0)
        _consume(fake_conn)
    assert cleaned.file_paths() == (set() if checkpoint.startswith("static-") else {"Inbox/source.md"})
    assert_source_publication(boundary_index)
    assert all(path.read_bytes() == data for path, data in retained.items())
    assert read_companion(vault, SOURCE_UUID).source_ref == "Inbox/source.md"
