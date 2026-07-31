"""Required DB-outbox policy coverage for watcher event producers (#4064)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.watcher import registry
from app.watcher.state import WatcherState

pytestmark = pytest.mark.not_pg


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
@pytest.mark.parametrize("fails", [False, True])
def test_required_db_intent_reaches_both_watcher_producers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
    fails: bool,
) -> None:
    """Both watcher topics must attempt and fail loud when DB delivery is required."""
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    observed: list[bool] = []

    def _writer(*args: object, required_db: bool = False, **kwargs: object) -> str:
        observed.append(required_db)
        if fails:
            raise RuntimeError("required watcher DB write failed")
        return "inserted-key"

    if topic == PANEL_SCAN_REQUESTED:
        monkeypatch.setattr(registry, "write_outbox_event", _writer)
    else:
        monkeypatch.setattr(registry, "insert_object_and_outbox", _writer)

    state = WatcherState()
    spec = registry.WatcherSpec(
        name="required-db",
        scope_glob="**/*.md",
        debounce_ms=0,
        rate_limit_per_min=60,
        emit_event=topic,
    )
    def call() -> str | None:
        return registry._emit_watch_event(
            spec=spec,
            cfg=None,  # type: ignore[arg-type]  # `_emit_watch_event` does not read cfg.
            outbox_path=tmp_path / "outbox.jsonl",
            vault_root=tmp_path,
            rel_path=Path("note.md"),
            mtime=1.0,
            content_hash="hash",
            state=state,
        )

    if fails:
        with pytest.raises(RuntimeError, match="required watcher DB write failed"):
            call()
        assert state.enqueue_failures_total == 1
    else:
        assert call()
        assert state.enqueue_failures_total == 0

    assert observed == [True]


def _tick_config(
    tmp_path: Path,
    *,
    topic: str,
) -> tuple[registry.RegistryConfig, registry.WatcherSpec, Path]:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_path = vault_root / "note.md"
    note_path.write_text(
        "%% AI %%\n- [ ] Review this note <!--ai:id=review.note-->\n%% AI %%\n",
        encoding="utf-8",
    )
    spec = registry.WatcherSpec(
        name=f"required-{topic}",
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=60,
        emit_event=topic,
        backoff_seconds=0,
    )
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault_root,
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=60,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.05,
        tick_log_path=tmp_path / "tick.jsonl",
        max_scanned_files_per_tick=500,
        max_bytes_read_per_tick=50_000_000,
        max_elapsed_ms_per_tick=2_000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=0,
        specs=[spec],
    )
    return cfg, spec, note_path


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_required_enqueue_failure_keeps_finalized_cursor_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
) -> None:
    """A failed required enqueue must retry unchanged input, then advance exactly once."""
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    monkeypatch.setattr(registry, "_panel_candidate_for_path", lambda _path: (True, True))
    monkeypatch.setattr(registry, "_auto_exec_enabled", lambda _vault: True)

    cfg, spec, note_path = _tick_config(tmp_path, topic=topic)
    rel_path = str(note_path.relative_to(cfg.vault_path))
    attempts: list[bool] = []

    def _writer(*args: object, required_db: bool = False, **kwargs: object) -> str:
        attempts.append(required_db)
        if len(attempts) == 1:
            raise RuntimeError("required watcher DB write failed")
        return "inserted-key"

    if topic == PANEL_SCAN_REQUESTED:
        monkeypatch.setattr(registry, "write_outbox_event", _writer)
    else:
        monkeypatch.setattr(registry, "insert_object_and_outbox", _writer)

    state_path = registry._state_path(cfg.state_dir, spec.name)
    first = registry._run_spec_tick(
        cfg,
        spec,
        WatcherState(),
        now=note_path.stat().st_mtime + 1,
    )

    assert first["emitted_in_tick"] == 0
    assert attempts == [True]
    after_failure = WatcherState.load(state_path)
    assert after_failure.last_mtime(rel_path) is None
    assert after_failure.last_hash(rel_path) is None

    second = registry._run_spec_tick(
        cfg,
        spec,
        after_failure,
        now=note_path.stat().st_mtime + 2,
    )

    assert second["emitted_in_tick"] == 1
    assert attempts == [True, True]
    after_success = WatcherState.load(state_path)
    assert after_success.last_mtime(rel_path) == note_path.stat().st_mtime
    assert after_success.last_hash(rel_path) is not None
    assert after_success.intents_emitted == 1

    third = registry._run_spec_tick(
        cfg,
        spec,
        after_success,
        now=note_path.stat().st_mtime + 3,
    )

    assert third["emitted_in_tick"] == 0
    assert attempts == [True, True]
    assert WatcherState.load(state_path).intents_emitted == 1


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_non_required_emission_failure_also_keeps_the_cursor_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
) -> None:
    """#4214 D6: the rollback may not be gated on required_db.

    ``append_jsonl_outbox_event`` is not wrapped, so an ``OSError`` on the
    compensating sink propagates out of ``_emit_watch_event`` on the NON-required
    path too — with neither sink written. While the cursor restore was gated on
    ``required_db`` the observation was consumed anyway: ``_finalize_spec_tick``
    saved the advanced ``state.files`` entry and the unchanged file was never
    re-detected.
    """
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setattr(registry, "_panel_candidate_for_path", lambda _path: (True, True))
    monkeypatch.setattr(registry, "_auto_exec_enabled", lambda _vault: True)

    cfg, spec, note_path = _tick_config(tmp_path, topic=topic)
    rel_path = str(note_path.relative_to(cfg.vault_path))
    appends: list[object] = []

    def _jsonl_sink(outbox_path: object, event: object, **kwargs: object) -> None:
        appends.append(event)
        if len(appends) == 1:
            raise OSError("compensating JSONL sink unavailable")

    monkeypatch.setattr(registry, "append_jsonl_outbox_event", _jsonl_sink)

    state_path = registry._state_path(cfg.state_dir, spec.name)
    first = registry._run_spec_tick(
        cfg,
        spec,
        WatcherState(),
        now=note_path.stat().st_mtime + 1,
    )

    assert first["emitted_in_tick"] == 0
    after_failure = WatcherState.load(state_path)
    assert after_failure.last_mtime(rel_path) is None, (
        "a non-required emission that wrote NEITHER sink still consumed the observation"
    )
    assert after_failure.last_hash(rel_path) is None

    second = registry._run_spec_tick(
        cfg,
        spec,
        after_failure,
        now=note_path.stat().st_mtime + 2,
    )

    assert second["emitted_in_tick"] == 1, "the unchanged file must be re-detected and retried"
    assert WatcherState.load(state_path).last_mtime(rel_path) == note_path.stat().st_mtime


def test_failed_emission_restores_a_previously_seen_file_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#4214 D6: cover the restore branch, not only the pop branch.

    ``previous_file_state is None`` (a first-ever observation) pops the entry;
    an ALREADY-SEEN file must have its prior mtime/hash put back, otherwise the
    partially-advanced entry suppresses the retry.
    """
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    monkeypatch.setattr(registry, "_panel_candidate_for_path", lambda _path: (True, True))
    monkeypatch.setattr(registry, "_auto_exec_enabled", lambda _vault: True)

    cfg, spec, note_path = _tick_config(tmp_path, topic=PANEL_SCAN_REQUESTED)
    rel_path = str(note_path.relative_to(cfg.vault_path))
    attempts: list[bool] = []

    def _writer(*args: object, required_db: bool = False, **kwargs: object) -> str:
        attempts.append(required_db)
        if len(attempts) == 2:
            raise RuntimeError("required watcher DB write failed")
        return "inserted-key"

    monkeypatch.setattr(registry, "write_outbox_event", _writer)
    state_path = registry._state_path(cfg.state_dir, spec.name)

    # Tick 1: the file becomes a SEEN observation with a durable cursor entry.
    registry._run_spec_tick(cfg, spec, WatcherState(), now=note_path.stat().st_mtime + 1)
    seen = WatcherState.load(state_path)
    first_mtime = seen.last_mtime(rel_path)
    first_hash = seen.last_hash(rel_path)
    assert first_mtime is not None and first_hash is not None

    # Tick 2: the file changes, and the required enqueue for the new content fails.
    note_path.write_text(
        "%% AI %%\n- [ ] Review the revised note <!--ai:id=review.note-->\n%% AI %%\n",
        encoding="utf-8",
    )
    changed_mtime = note_path.stat().st_mtime
    registry._run_spec_tick(cfg, spec, seen, now=changed_mtime + 1)

    restored = WatcherState.load(state_path)
    assert restored.last_mtime(rel_path) == first_mtime, (
        "the pre-observation cursor entry for an already-seen file was not restored"
    )
    assert restored.last_hash(rel_path) == first_hash

    # Tick 3: the unchanged-on-disk revision is re-detected and delivered.
    third = registry._run_spec_tick(cfg, spec, restored, now=changed_mtime + 2)

    assert third["emitted_in_tick"] == 1
    assert WatcherState.load(state_path).last_mtime(rel_path) == changed_mtime
