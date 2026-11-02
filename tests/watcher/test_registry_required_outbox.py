"""Required DB-outbox policy coverage for watcher event producers (#4064)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from contextlib import nullcontext
from types import SimpleNamespace

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
        assert not (tmp_path / "outbox.jsonl").exists()
    else:
        assert call()
        assert state.enqueue_failures_total == 0
        assert len((tmp_path / "outbox.jsonl").read_text(encoding="utf-8").splitlines()) == 1

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


def _throttle_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, topic: str):
    """Exercise real scan/state transitions without a real outbox or vault writer."""
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    cfg, spec, note = _tick_config(tmp_path, topic=topic)
    monkeypatch.setattr(registry, "_panel_emit_allowed", lambda **_kwargs: True)
    monkeypatch.setattr(
        registry, "_maybe_heal_ingest_uuid",
        lambda _cfg, _state, _path, mtime, digest: (mtime, digest),
    )
    calls: list[tuple[str, str | None]] = []

    def emit(**kwargs: object) -> str:
        calls.append((str(kwargs["rel_path"]), kwargs["content_hash"]))  # type: ignore[arg-type]
        return f"trace-{len(calls)}"

    monkeypatch.setattr(registry, "_emit_watch_event", emit)
    return cfg, spec, note, calls


def _set_note(note: Path, contents: str, mtime: float) -> str:
    note.write_text(contents, encoding="utf-8")
    os.utime(note, (mtime, mtime))
    return hashlib.sha256(contents.encode()).hexdigest()


def _tick(cfg: registry.RegistryConfig, spec: registry.WatcherSpec, now: float):
    path = registry._state_path(cfg.state_dir, spec.name)
    state = registry._load_registry_state(path)
    return registry._run_spec_tick(cfg, spec, state, now=now)


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_throttled_debounce_observation_delivers_latest_after_window(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.debounce_ms = 1000
    base = time.time()
    first_hash = _set_note(note, "first", base - 2)
    assert _tick(cfg, spec, base)["emitted_in_tick"] == 1
    before = registry._load_registry_state(registry._state_path(cfg.state_dir, spec.name))
    assert before.file_entry("note.md")["last_seen"] == base
    latest_hash = _set_note(note, "latest", base - 1)
    assert _tick(cfg, spec, base + 0.2)["emitted_in_tick"] == 0
    saved = registry._load_registry_state(registry._state_path(cfg.state_dir, spec.name))
    assert saved.last_hash("note.md") == first_hash
    assert _tick(cfg, spec, base + 1.1)["emitted_in_tick"] == 1
    assert calls == [("note.md", first_hash), ("note.md", latest_hash)]
    assert _tick(cfg, spec, base + 2.2)["emitted_in_tick"] == 0


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_rate_limited_observation_delivers_after_window(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "one", base - 2)
    second = note.with_name("second.md")
    second_hash = _set_note(second, "two", base - 1)
    assert _tick(cfg, spec, base)["emitted_in_tick"] == 1
    assert _tick(cfg, spec, base + 61)["emitted_in_tick"] == 1
    assert calls == [("note.md", hashlib.sha256(b"one").hexdigest()), ("second.md", second_hash)]
    assert _tick(cfg, spec, base + 122)["emitted_in_tick"] == 0


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_throttled_observation_survives_restart_and_coalesces_latest(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.debounce_ms = 1000
    base = time.time()
    first = _set_note(note, "first", base - 3)
    _tick(cfg, spec, base)
    _set_note(note, "middle", base - 2)
    _tick(cfg, spec, base + 0.2)
    last = _set_note(note, "last", base - 1)
    _tick(cfg, spec, base + 0.4)
    assert _tick(cfg, spec, base + 1.2)["emitted_in_tick"] == 1
    assert calls == [("note.md", first), ("note.md", last)]
    assert _tick(cfg, spec, base + 2.3)["emitted_in_tick"] == 0


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_legacy_emission_timestamp_still_bounds_debounce(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.debounce_ms = 1000
    base = time.time()
    first = _set_note(note, "first", base - 2)
    _tick(cfg, spec, base)
    state_path = registry._state_path(cfg.state_dir, spec.name)
    legacy = registry._load_registry_state(state_path)
    entry = legacy.file_entry("note.md")
    assert entry is not None
    entry.pop("last_seen")
    legacy.restore_file_state("note.md", entry)
    legacy.save(state_path)
    last = _set_note(note, "later", base - 1)
    assert _tick(cfg, spec, base + 0.2)["emitted_in_tick"] == 0
    assert _tick(cfg, spec, base + 1.2)["emitted_in_tick"] == 1
    assert calls == [("note.md", first), ("note.md", last)]


def test_throttle_retry_preserves_policy_and_scan_boundaries(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.debounce_ms = 1000
    base = time.time()
    _set_note(note, "first", base - 3)
    _tick(cfg, spec, base)
    _set_note(note, "pending", base - 2)
    _tick(cfg, spec, base + 0.2)
    # While a prior accepted file is throttled, it remains present to the
    # sidecar's scan generation. Removing it later is a genuine absence.
    state_path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(state_path).file_entry("note.md") is not None
    note.unlink()
    _tick(cfg, spec, base + 1.2)
    assert registry._load_registry_state(state_path).file_entry("note.md") is None
    assert len(calls) == 1

    # Ineligible notes remain consumed as policy skips; they do not become
    # executable merely because a throttle window later expires.
    _set_note(note, "ineligible", base + 2)
    monkeypatch.setattr(registry, "_panel_emit_allowed", lambda **_kwargs: False)
    _tick(cfg, spec, base + 3)
    monkeypatch.setattr(registry, "_panel_emit_allowed", lambda **_kwargs: True)
    assert _tick(cfg, spec, base + 5)["emitted_in_tick"] == 0
    assert len(calls) == 1


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_deleted_never_delivered_throttled_file_leaves_no_observation(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "accepted", base - 2)
    deferred = note.with_name("second.md")
    _set_note(deferred, "never-delivered", base - 1)
    _tick(cfg, spec, base)
    state_path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(state_path).file_entry("second.md") is None
    deferred.unlink()
    _tick(cfg, spec, base + 61)
    assert registry._load_registry_state(state_path).file_entry("second.md") is None
    assert len(calls) == 1


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_unreadable_then_deleted_new_priority_never_becomes_observation(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "accepted", base - 2)
    deferred = note.with_name("second.md")
    _set_note(deferred, "never-delivered", base - 1)
    _tick(cfg, spec, base)
    state_path = registry._state_path(cfg.state_dir, spec.name)
    state = registry._load_registry_state(state_path)
    assert state.throttle_priority == "second.md"
    assert state.file_entry("second.md") is None

    original_hash = registry._hash_file
    monkeypatch.setattr(registry, "_hash_file", lambda p: None if p == deferred else original_hash(p))
    summary = _tick(cfg, spec, base + 61)
    assert summary["errors_in_tick"] > 0
    assert registry._load_registry_state(state_path).file_entry("second.md") is None

    deferred.unlink()
    _tick(cfg, spec, base + 122)
    assert registry._load_registry_state(state_path).file_entry("second.md") is None
    assert [path for path, _ in calls] == ["note.md"]


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_hash_error_preserves_existing_observation_without_accepting_change(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    base = time.time()
    _set_note(note, "accepted", base - 2)
    _tick(cfg, spec, base)
    state_path = registry._state_path(cfg.state_dir, spec.name)
    before = registry._load_registry_state(state_path).file_entry("note.md")
    _set_note(note, "unreadable change", base + 1)
    monkeypatch.setattr(registry, "_hash_file", lambda _path: None)
    assert _tick(cfg, spec, base + 2)["errors_in_tick"] > 0
    assert registry._load_registry_state(state_path).file_entry("note.md") == before
    assert len(calls) == 1


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
def test_rate_limited_burst_drains_fairly_with_bounded_scans(tmp_path, monkeypatch, topic):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    cfg.max_scanned_files_per_tick = 5
    spec.rate_limit_per_min = 30
    base = time.time()
    note.unlink()
    for index in range(35):
        _set_note(note.with_name(f"note-{index:02}.md"), f"content-{index}", base - 1)
    # Run enough limited ticks to traverse several full generations, first
    # inside one window and then beyond its expiry. Each tick reloads the
    # real checkpoint and its durable sidecar.
    for index in range(20):
        _tick(cfg, spec, base + index * 0.1)
    assert len(calls) == 30
    for index in range(20):
        _tick(cfg, spec, base + 61 + index * 0.1)
    assert len(calls) == 35
    assert len({path for path, _digest in calls}) == 35


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
@pytest.mark.parametrize("previously_delivered", [False, True])
@pytest.mark.parametrize("scan_limit", [5, 500])
def test_rate_limited_tail_not_starved_by_new_edits(tmp_path, monkeypatch, topic, previously_delivered, scan_limit):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, topic)
    cfg.max_scanned_files_per_tick = scan_limit
    spec.rate_limit_per_min = 30
    base = time.time()
    note.unlink()
    paths = [note.with_name(f"note-{index:02}.md") for index in range(35)]

    def generation(now: float) -> None:
        for index in range(30):
            summary = _tick(cfg, spec, now + index / 100)
            if not summary["scan_in_progress"] or summary["rate_limited_in_tick"]:
                return
        pytest.fail("bounded scanner did not finish a generation")

    for index, path in enumerate(paths):
        _set_note(path, f"initial-{index}", base - 5)
    if previously_delivered:
        generation(base)
        generation(base + 61)
        generation(base + 62)
        assert len(calls) == 35
        calls.clear()
        base += 122
        for index, path in enumerate(paths):
            _set_note(path, f"pending-{index}", base - 1)
    # Each generation ends before the next window, so an implementation
    # that always begins at the lexicographic head cannot rely on incidental
    # continuation state for fairness.
    generation(base)
    for window in range(1, 4):
        for index, path in enumerate(paths[:30]):
            _set_note(path, f"new-{window}-{index}", base + window * 61 - 1)
        generation(base + window * 61)
    assert {path for path, _digest in calls} >= {path.name for path in paths}


@pytest.mark.parametrize("scan_limit", [5, 500])
def test_unrelated_persistent_hash_error_does_not_starve_readable_tail(tmp_path, monkeypatch, scan_limit):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    cfg.max_scanned_files_per_tick = scan_limit
    # Keep the independent administrative bad-tick stop outside this fairness
    # test; the read error still has to remain visible in the checkpoint.
    cfg.max_bad_ticks = 10000
    spec.rate_limit_per_min = 30
    base = time.time()
    note.unlink()
    paths = [note.with_name(f"note-{index:02}.md") for index in range(35)]
    for index, path in enumerate(paths):
        _set_note(path, f"initial-{index}", base - 1)
    unreadable = note.with_name("zzz-unreadable.md")
    _set_note(unreadable, "unreadable", base - 1)
    original_hash = registry._hash_file
    monkeypatch.setattr(registry, "_hash_file", lambda p: None if p == unreadable else original_hash(p))

    for window in range(4):
        if window:
            for index, path in enumerate(paths[:30]):
                _set_note(path, f"edit-{window}-{index}", base + window * 61 - 1)
        for tick in range(25):
            _tick(cfg, spec, base + window * 61 + tick / 100)
    assert {path for path, _digest in calls} >= {path.name for path in paths}
    state = registry._load_registry_state(registry._state_path(cfg.state_dir, spec.name))
    assert state.errors > 0 and state.file_entry(unreadable.name) is None


def test_priority_does_not_block_settings_or_stop_and_does_not_repeat_reload(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 2)
    _set_note(note.with_name("second.md"), "deferred", base - 1)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    source = cfg.vault_path / "settings" / "custom.md"
    source.parent.mkdir()
    _set_note(source, "settings source", base + 0.1)
    reloads: list[bool] = []

    def reload_settings(**_kwargs):
        reloads.append(True)
        return SimpleNamespace(reloaded=True, errors=())

    monkeypatch.setattr(registry, "handle_settings_source_delta", reload_settings)
    _tick(cfg, spec, base + 0.2)
    _tick(cfg, spec, base + 0.4)
    assert reloads == [True]
    cfg.stop_file.write_text("stop", encoding="utf-8")
    assert _tick(cfg, spec, base + 61)["kill_switch"] is True
    assert len(calls) == 1
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    cfg.stop_file.unlink()
    assert _tick(cfg, spec, base + 62)["emitted_in_tick"] == 1
    assert reloads == [True]


def test_priority_removed_when_deferred_file_disappears_or_scope_changes(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    deferred = note.with_name("second.md")
    _set_note(deferred, "deferred", base - 2)
    _tick(cfg, spec, base)
    state_path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(state_path).throttle_priority == "second.md"
    deferred.unlink()
    _set_note(note, "new first", base + 60)
    _tick(cfg, spec, base + 61)
    assert registry._load_registry_state(state_path).throttle_priority is None
    assert _tick(cfg, spec, base + 62)["emitted_in_tick"] == 1
    assert [path for path, _ in calls] == ["note.md", "note.md"]

    # An old priority does not prevent a new configured scope from observing
    # its own eligible files after the rate window expires.
    _set_note(deferred, "deferred again", base + 63)
    _tick(cfg, spec, base + 63)
    assert registry._load_registry_state(state_path).throttle_priority == "second.md"
    spec.scope_glob = "*ote.md"
    _set_note(note, "scope revision", base + 122)
    assert _tick(cfg, spec, base + 123)["emitted_in_tick"] == 1
    assert registry._load_registry_state(state_path).throttle_priority is None


@pytest.mark.parametrize("authority_change", ["binding", "configuration"])
def test_priority_is_fenced_by_actual_rebind_authority(tmp_path, monkeypatch, authority_change):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    cfg.specs = [spec]
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    record = SimpleNamespace(desired_revision=1, prior_binding_id=None, candidate_binding_id="old")
    cycle = SimpleNamespace(mode="stable", record=record)
    reconciler = SimpleNamespace(
        begin_cycle=lambda _cfg: cycle,
        candidate_vault_path=lambda *_a, **_k: cfg.vault_path,
        finish_cycle=lambda *_a, **_k: None,
    )
    monkeypatch.setattr(registry, "_compatibility_watcher_window", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(registry, "_adopt_idle_selected_binding", lambda *_a, **_k: None)
    monkeypatch.setattr(registry, "_run_briefing_tick", lambda *_a, **_k: {})
    monkeypatch.setattr(registry, "_run_youtube_sync_tick", lambda *_a, **_k: {})
    monkeypatch.setattr(registry, "_run_journal_review_tick", lambda *_a, **_k: {})
    path = registry._state_path(cfg.state_dir, spec.name)

    def run(now):
        state = registry._load_registry_state(path)
        registry._run_registry_cycle(
            cfg, reconciler, states={spec.name: state}, now=now,
            briefing_cadence=registry.BriefingTickCadence(), process_panel_notes_inline=False,
        )

    run(base)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    if authority_change == "binding":
        record.candidate_binding_id = "new"
        record.desired_revision = 2
    else:
        spec.rate_limit_per_min = 2
    _set_note(note, "new binding content", base + 60)
    run(base + 61)
    assert [path for path, _ in calls][:2] == ["note.md", "note.md"]


def test_priority_rechecks_current_policy_before_any_effect(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    # Current policy revokes the previously deferred note; a third eligible
    # note may use the available slot, but the revoked one is never emitted.
    _set_note(note.with_name("third.md"), "eligible", base + 60)
    monkeypatch.setattr(registry, "_panel_emit_allowed", lambda **kw: kw["rel_path"].name != "second.md")
    _tick(cfg, spec, base + 61)
    assert [p for p, _ in calls] == ["note.md", "third.md"]
    assert registry._load_registry_state(path).throttle_priority is None


def test_priority_failure_retries_then_clears_after_success(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    original_emit = registry._emit_watch_event
    monkeypatch.setattr(registry, "_emit_watch_event", lambda **_kw: (_ for _ in ()).throw(OSError("synthetic")))
    assert _tick(cfg, spec, base + 61)["errors_in_tick"] > 0
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    monkeypatch.setattr(registry, "_emit_watch_event", original_emit)
    # The existing watcher backoff remains authoritative.
    assert _tick(cfg, spec, base + 72)["emitted_in_tick"] == 1
    assert [p for p, _ in calls] == ["note.md", "second.md"]
    assert registry._load_registry_state(path).throttle_priority is None


def test_priority_survives_cursor_failure_after_emission(tmp_path, monkeypatch):
    cfg, spec, note, _calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    original = WatcherState.update_file_state
    faulted = False

    def fail_once(state, rel_path, **kwargs):
        nonlocal faulted
        if rel_path == "second.md" and kwargs.get("emitted_at") is not None and not faulted:
            faulted = True
            raise OSError("synthetic cursor failure")
        return original(state, rel_path, **kwargs)

    monkeypatch.setattr(WatcherState, "update_file_state", fail_once)
    assert _tick(cfg, spec, base + 61)["errors_in_tick"] > 0
    assert faulted and registry._load_registry_state(path).throttle_priority == "second.md"
    assert _tick(cfg, spec, base + 122)["emitted_in_tick"] == 1
    assert registry._load_registry_state(path).throttle_priority is None


def test_unreadable_priority_does_not_starve_other_changes(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    deferred = note.with_name("second.md")
    _set_note(deferred, "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    other = note.with_name("third.md")
    _set_note(other, "independent", base + 60)
    original_hash = registry._hash_file
    monkeypatch.setattr(registry, "_hash_file", lambda p: None if p == deferred else original_hash(p))
    summary = _tick(cfg, spec, base + 61)
    assert summary["errors_in_tick"] > 0
    assert [p for p, _ in calls] == ["note.md", "third.md"]
    state = registry._load_registry_state(path)
    assert state.throttle_priority is None
    assert state.last_mtime("second.md") is None
    monkeypatch.setattr(registry, "_hash_file", original_hash)
    assert _tick(cfg, spec, base + 122)["emitted_in_tick"] == 1
    assert [p for p, _ in calls] == ["note.md", "third.md", "second.md"]


def test_unreachable_priority_on_scan_error_does_not_starve_other_changes(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    _set_note(note.with_name("third.md"), "independent", base + 60)
    original_next = registry._next_incremental_markdown

    def skip_unreachable(**kwargs):
        while True:
            entry, complete = original_next(**kwargs)
            if entry is not None and entry[0].name == "second.md":
                registry._record_scan_error(kwargs["state"])
                continue
            return entry, complete

    monkeypatch.setattr(registry, "_next_incremental_markdown", skip_unreachable)
    summary = _tick(cfg, spec, base + 61)
    assert summary["errors_in_tick"] > 0
    assert [p for p, _ in calls] == ["note.md", "third.md"]
    state = registry._load_registry_state(path)
    assert state.throttle_priority is None and state.last_mtime("second.md") is None
    monkeypatch.setattr(registry, "_next_incremental_markdown", original_next)
    assert _tick(cfg, spec, base + 122)["emitted_in_tick"] == 1
    assert [p for p, _ in calls] == ["note.md", "third.md", "second.md"]


def test_priority_does_not_cross_selected_vault_replacement(tmp_path, monkeypatch):
    cfg, spec, note, calls = _throttle_setup(tmp_path, monkeypatch, PANEL_SCAN_REQUESTED)
    spec.rate_limit_per_min = 1
    base = time.time()
    _set_note(note, "first", base - 3)
    _set_note(note.with_name("second.md"), "deferred", base - 2)
    _tick(cfg, spec, base)
    path = registry._state_path(cfg.state_dir, spec.name)
    assert registry._load_registry_state(path).throttle_priority == "second.md"
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    cfg.vault_path = replacement
    _set_note(replacement / "new.md", "new root", base + 60)
    assert _tick(cfg, spec, base + 61)["emitted_in_tick"] == 1
    assert [p for p, _ in calls] == ["note.md", "new.md"]
    assert registry._load_registry_state(path).throttle_priority is None
