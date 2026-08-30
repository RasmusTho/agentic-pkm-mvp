from __future__ import annotations

from pathlib import Path

import pytest

from app.watcher import registry
from app.watcher.settings_delta import SettingsDeltaResult, SettingsSourceDeltaResult
from app.watcher.state import RegistryObservationStore, WatcherState


def _write_note(root: Path, rel_path: str, body: str = "note\n") -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _make_cfg(
    tmp_path: Path,
    *,
    max_files: int = 3,
    max_bytes: int = 1_000_000,
    max_elapsed_ms: int = 10_000,
    max_bad_ticks: int = 3,
) -> tuple[registry.RegistryConfig, registry.WatcherSpec, Path]:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    spec = registry.WatcherSpec(
        name="incremental",
        scope_glob="*.md,**/*.md",
        debounce_ms=0,
        rate_limit_per_min=10_000,
        emit_event="test.vault.changed",
        backoff_seconds=0,
    )
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob=spec.scope_glob,
        debounce_ms=0,
        rate_limit_per_min=10_000,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "ticks.jsonl",
        max_scanned_files_per_tick=max_files,
        max_bytes_read_per_tick=max_bytes,
        max_elapsed_ms_per_tick=max_elapsed_ms,
        max_bad_ticks=max_bad_ticks,
        bad_tick_backoff_seconds=0.0,
        specs=[spec],
    )
    return cfg, spec, vault


def _load_state(cfg: registry.RegistryConfig, spec: registry.WatcherSpec) -> WatcherState:
    return registry._load_registry_state(registry._state_path(cfg.state_dir, spec.name))


def _run_until_drained(
    cfg: registry.RegistryConfig,
    spec: registry.WatcherSpec,
    state: WatcherState,
    *,
    start: float,
) -> tuple[WatcherState, list[dict[str, object]]]:
    summaries: list[dict[str, object]] = []
    for tick in range(100):
        summary = registry._run_spec_tick(
            cfg,
            spec,
            state,
            now=start + tick,
            states={spec.name: state},
            handled_settings_sources=set(),
        )
        summaries.append(summary)
        state = _load_state(cfg, spec)
        if summary["observation_status"] == "healthy-idle":
            return state, summaries
    raise AssertionError("incremental scan did not drain within 100 ticks")


def test_registry_scan_resumes_after_budget_without_restarting_from_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=2)
    expected = {
        f"notes/{directory}/note-{index}.md"
        for directory in ("a", "b", "c")
        for index in range(2)
    }
    for rel_path in sorted(expected):
        _write_note(vault, rel_path, body=rel_path)

    hashed: list[str] = []
    original_hash = registry._hash_file

    def record_hash(path: Path) -> tuple[str, int] | None:
        hashed.append(path.relative_to(vault).as_posix())
        return original_hash(path)

    emitted: list[str] = []

    def emit(**kwargs: object) -> str:
        emitted.append(Path(str(kwargs["rel_path"])).as_posix())
        return f"trace-{len(emitted)}"

    monkeypatch.setattr(registry, "_hash_file", record_hash)
    monkeypatch.setattr(registry, "_emit_watch_event", emit)

    state = _load_state(cfg, spec)
    first = registry._run_spec_tick(
        cfg,
        spec,
        state,
        now=1_700_000_000.0,
        states={spec.name: state},
        handled_settings_sources=set(),
    )
    assert first["scanned_files"] == 2
    assert first["observation_status"] == "catch-up"
    assert first["continuation_reason"] == "file_budget"
    assert not cfg.stop_file.exists()

    # A new process loads the durable checkpoint and continues after the
    # already-observed files. It does not traverse/hash the first batch again.
    restarted = _load_state(cfg, spec)
    restarted, summaries = _run_until_drained(
        cfg,
        spec,
        restarted,
        start=1_700_000_001.0,
    )

    assert all(int(summary["scanned_files"]) <= 2 for summary in summaries)
    assert set(emitted) == expected
    assert len(emitted) == len(expected)
    assert set(hashed) == expected
    assert len(hashed) == len(expected)
    assert restarted.scan_in_progress is False


def test_registry_scan_lists_each_directory_once_per_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=5)
    notes = vault / "notes"
    for index in range(12):
        _write_note(vault, f"notes/{index:03d}.md")

    original_iterdir = Path.iterdir
    listings = 0

    def counted_iterdir(path: Path):
        nonlocal listings
        if path == notes:
            listings += 1
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)
    monkeypatch.setattr(registry, "_emit_watch_event", lambda **_: "trace-ok")

    summary = registry._run_spec_tick(
        cfg,
        spec,
        _load_state(cfg, spec),
        now=1_700_000_500.0,
        states=None,
        handled_settings_sources=set(),
    )

    assert summary["scanned_files"] == 5
    assert summary["observation_status"] == "catch-up"
    assert listings == 1


def test_budget_boundary_is_catch_up_and_real_failure_still_trips_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=1, max_bad_ticks=2)
    for index in range(5):
        _write_note(vault, f"notes/{index}.md", body="0123456789")

    monkeypatch.setattr(registry, "_emit_watch_event", lambda **_: "trace-ok")
    state = _load_state(cfg, spec)
    for tick in range(4):
        summary = registry._run_spec_tick(
            cfg,
            spec,
            state,
            now=1_700_001_000.0 + tick,
            states={spec.name: state},
            handled_settings_sources=set(),
        )
        assert summary["observation_status"] == "catch-up"
        assert summary["bad_tick"] is False
        assert state.bad_ticks == 0
        assert not cfg.stop_file.exists()
        state = _load_state(cfg, spec)

    # Byte and elapsed guardrails use the same continuation classification;
    # they are resource boundaries, not repeated failures.
    for reason in ("byte_budget", "elapsed_budget"):
        summary = {
            "scanned_files": 1,
            "bytes_read": cfg.max_bytes_read_per_tick,
            "tick_ms": cfg.max_elapsed_ms_per_tick,
            "errors_in_tick": 0,
            "scan_in_progress": True,
            "scan_progress_entries": 1,
            "continuation_reason": reason,
        }
        registry._apply_guardrails_registry(cfg, state, summary)
        assert summary["bad_tick"] is False
        assert summary["observation_status"] == "catch-up"

    state.scan_generation_had_error = True
    summary = {
        "scanned_files": 1,
        "bytes_read": 0,
        "tick_ms": 0,
        "errors_in_tick": 0,
        "scan_in_progress": True,
        "scan_progress_entries": 1,
        "scan_generation_had_error": True,
    }
    registry._apply_guardrails_registry(cfg, state, summary)
    assert summary["bad_tick"] is False
    assert summary["observation_status"] == "degraded"
    assert state.bad_ticks == 0
    assert not cfg.stop_file.exists()

    failing_cfg, failing_spec, failing_vault = _make_cfg(
        tmp_path / "failure", max_files=10, max_bad_ticks=2
    )
    _write_note(failing_vault, "notes/fails.md")

    def fail_emit(**_: object) -> str:
        raise OSError("durable outbox unavailable")

    monkeypatch.setattr(registry, "_emit_watch_event", fail_emit)
    failing_state = _load_state(failing_cfg, failing_spec)
    for tick in range(2):
        failure = registry._run_spec_tick(
            failing_cfg,
            failing_spec,
            failing_state,
            now=1_700_002_000.0 + tick,
            states={failing_spec.name: failing_state},
            handled_settings_sources=set(),
        )
        failing_state = _load_state(failing_cfg, failing_spec)

    assert failure["bad_tick_reason"] == "errors"
    assert failure["observation_status"] == "degraded"
    assert failing_cfg.stop_file.exists()


def test_large_vault_checkpoint_state_preserves_change_and_boundary_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=4)
    ordinary = {f"notes/{index:03d}.md" for index in range(30)}
    for rel_path in sorted(ordinary):
        _write_note(vault, rel_path, body=f"initial:{rel_path}")

    child = vault / "notes" / "private-child"
    _write_note(
        child,
        "settings/vault.md",
        body="---\nschema: design-handoff.vault.v1\nvaultId: private\n---\n",
    )
    _write_note(child, "secret.md", body="must stay private")
    settings_source = _write_note(vault, "settings/global.md", body="# settings v1\n")

    monkeypatch.setattr(
        registry,
        "handle_settings_detected_delta",
        lambda **_: SettingsDeltaResult(values=None),
    )
    settings_reloads: list[str] = []

    def reload_settings(*, rel_path: Path, vault_root: Path | None = None) -> SettingsSourceDeltaResult:
        assert vault_root == vault
        settings_reloads.append(rel_path.as_posix())
        return SettingsSourceDeltaResult(is_source=True, reloaded=True)

    monkeypatch.setattr(registry, "handle_settings_source_delta", reload_settings)

    emitted: list[str] = []

    def emit(**kwargs: object) -> str:
        rel = Path(str(kwargs["rel_path"])).as_posix()
        emitted.append(rel)
        return f"trace-{len(emitted)}"

    monkeypatch.setattr(registry, "_emit_watch_event", emit)

    state, first_cycle = _run_until_drained(
        cfg,
        spec,
        _load_state(cfg, spec),
        start=1_700_003_000.0,
    )
    assert set(emitted) == ordinary
    assert "notes/private-child/secret.md" not in emitted
    assert "settings/global.md" not in emitted
    assert settings_reloads == ["settings/global.md"]
    assert any(summary["observation_status"] == "catch-up" for summary in first_cycle)

    checkpoint_path = registry._state_path(cfg.state_dir, spec.name)
    observation_path = registry._observation_store_path(checkpoint_path)
    assert checkpoint_path.stat().st_size < 20_000
    assert observation_path.exists()
    assert state.file_paths() == ordinary | {"settings/global.md"}

    edited = "notes/005.md"
    deleted = "notes/010.md"
    added = "notes/999.md"
    _write_note(vault, edited, body="edited")
    (vault / deleted).unlink()
    _write_note(vault, added, body="added")
    settings_source.write_text("# settings v2\n", encoding="utf-8")

    emitted_before = len(emitted)
    state, _ = _run_until_drained(
        cfg,
        spec,
        state,
        start=1_700_004_000.0,
    )
    assert set(emitted[emitted_before:]) == {edited, added}
    assert deleted not in state.file_paths()
    assert added in state.file_paths()
    assert "notes/private-child/secret.md" not in state.file_paths()
    assert settings_reloads == ["settings/global.md", "settings/global.md"]
    assert checkpoint_path.stat().st_size < 20_000


def test_settings_source_reload_failure_keeps_observation_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=10)
    source = _write_note(vault, "settings/global.md", body="# settings\n")
    monkeypatch.setattr(
        registry,
        "handle_settings_detected_delta",
        lambda **_: SettingsDeltaResult(values=None),
    )
    attempts = 0

    def reload_settings(
        *, rel_path: Path, vault_root: Path | None = None
    ) -> SettingsSourceDeltaResult:
        nonlocal attempts
        assert rel_path == Path("settings/global.md")
        assert vault_root == vault
        attempts += 1
        if attempts == 1:
            return SettingsSourceDeltaResult(
                is_source=True,
                reloaded=False,
                errors=("invalid settings source",),
            )
        return SettingsSourceDeltaResult(is_source=True, reloaded=True)

    monkeypatch.setattr(registry, "handle_settings_source_delta", reload_settings)

    first_state = _load_state(cfg, spec)
    first = registry._run_spec_tick(
        cfg,
        spec,
        first_state,
        now=1_700_005_000.0,
        states={spec.name: first_state},
        handled_settings_sources=set(),
    )
    restarted = _load_state(cfg, spec)

    assert first["observation_status"] == "degraded"
    assert restarted.file_entry("settings/global.md") is None

    second = registry._run_spec_tick(
        cfg,
        spec,
        restarted,
        now=1_700_005_001.0,
        states={spec.name: restarted},
        handled_settings_sources=set(),
    )
    recovered = _load_state(cfg, spec)

    assert attempts == 2
    assert second["observation_status"] == "healthy-idle"
    assert recovered.file_entry("settings/global.md")["hash"] == registry._hash_file(source)[0]


def test_deleted_settings_source_reload_failure_preserves_observation_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=10)
    source = _write_note(vault, "settings/global.md", body="# settings\n")
    monkeypatch.setattr(
        registry,
        "handle_settings_detected_delta",
        lambda **_: SettingsDeltaResult(values=None),
    )
    attempts = 0

    def reload_settings(
        *, rel_path: Path, vault_root: Path | None = None
    ) -> SettingsSourceDeltaResult:
        nonlocal attempts
        assert rel_path == Path("settings/global.md")
        assert vault_root == vault
        attempts += 1
        if attempts == 2:
            return SettingsSourceDeltaResult(
                is_source=True,
                reloaded=False,
                errors=("settings source temporarily unavailable",),
            )
        return SettingsSourceDeltaResult(is_source=True, reloaded=True)

    monkeypatch.setattr(registry, "handle_settings_source_delta", reload_settings)
    monkeypatch.setattr(registry, "_emit_watch_event", lambda **_: "trace-ok")

    state, _ = _run_until_drained(cfg, spec, _load_state(cfg, spec), start=1_700_006_000.0)
    assert state.file_entry("settings/global.md") is not None
    source.unlink()

    failed = registry._run_spec_tick(
        cfg,
        spec,
        state,
        now=1_700_006_100.0,
        states={spec.name: state},
        handled_settings_sources=set(),
    )
    failed_state = _load_state(cfg, spec)

    assert failed["observation_status"] == "degraded"
    assert failed_state.file_entry("settings/global.md") is not None

    recovered = registry._run_spec_tick(
        cfg,
        spec,
        failed_state,
        now=1_700_006_101.0,
        states={spec.name: failed_state},
        handled_settings_sources=set(),
    )
    recovered_state = _load_state(cfg, spec)

    assert attempts == 3
    assert recovered["observation_status"] == "healthy-idle"
    assert recovered_state.file_entry("settings/global.md") is None


def test_directory_listing_failure_blocks_generation_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path, max_files=10)
    note = _write_note(vault, "notes/retained.md", body="must be reconciled safely")
    monkeypatch.setattr(registry, "_emit_watch_event", lambda **_: "trace-ok")

    state, _ = _run_until_drained(
        cfg, spec, _load_state(cfg, spec), start=1_700_007_000.0
    )
    assert state.file_entry("notes/retained.md") is not None
    note.unlink()

    original_iterdir = Path.iterdir
    failed_once = False

    def fail_notes_listing(path: Path):
        nonlocal failed_once
        if path == vault / "notes" and not failed_once:
            failed_once = True
            raise OSError("directory temporarily unavailable")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_notes_listing)
    failed = registry._run_spec_tick(
        cfg,
        spec,
        state,
        now=1_700_007_100.0,
        states={spec.name: state},
        handled_settings_sources=set(),
    )
    failed_state = _load_state(cfg, spec)

    assert failed["observation_status"] == "degraded"
    assert failed_state.file_entry("notes/retained.md") is not None

    recovered = registry._run_spec_tick(
        cfg,
        spec,
        failed_state,
        now=1_700_007_101.0,
        states={spec.name: failed_state},
        handled_settings_sources=set(),
    )
    recovered_state = _load_state(cfg, spec)

    assert recovered["observation_status"] == "healthy-idle"
    assert recovered_state.file_entry("notes/retained.md") is None


def test_scan_root_resolution_failure_is_durable_and_identity_is_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, _spec, vault = _make_cfg(tmp_path)
    root = vault / "notes"
    root.mkdir()
    state = WatcherState()
    original_resolve = Path.resolve

    def fail_root_resolve(path: Path, *args: object, **kwargs: object) -> Path:
        if path == root:
            raise OSError("root temporarily unavailable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_root_resolve)
    roots = registry._normalized_scan_roots(vault, [root], state=state)

    assert roots == []
    assert state.scan_generation_had_error is True
    registry._begin_or_resume_scan(
        state,
        vault_root=vault,
        scan_roots=roots,
        scope_glob=cfg.scope_glob,
        preserve_generation_error=True,
    )
    assert state.scan_in_progress is True
    assert state.scan_generation_had_error is True


def test_resumed_scan_stack_revalidates_changed_boundary(
    tmp_path: Path,
) -> None:
    cfg, spec, vault = _make_cfg(tmp_path)
    notes = vault / "notes"
    notes.mkdir()
    outside = tmp_path / "outside"
    _write_note(outside, "secret.md", body="must not be traversed")
    state = WatcherState()
    roots = registry._normalized_scan_roots(vault, [vault], state=state)
    identity = registry._scan_identity(vault, roots, spec.scope_glob)
    state.scan_in_progress = True
    state.scan_generation = 1
    state.scan_identity = identity
    state.scan_stack = [{"dir": "notes", "after": ""}]
    notes.rmdir()
    notes.symlink_to(outside, target_is_directory=True)

    summary = registry._run_spec_tick(
        cfg,
        spec,
        state,
        now=1_700_009_100.0,
        states={spec.name: state},
        handled_settings_sources=set(),
    )

    assert summary["observation_status"] == "degraded"
    assert state.scan_generation_had_error is True
    assert state.file_entry("notes/secret.md") is None


def test_observation_sidecar_is_applied_before_checkpoint_payload(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "watcher_state.json"
    observations = RegistryObservationStore(tmp_path / "observations.sqlite3")
    state = WatcherState(_observation_store=observations)
    state.update_file_state(
        "notes/one.md",
        content_hash="digest",
        seen_at=1_700_008_000.0,
    )

    state.save(checkpoint)

    assert observations.get("notes/one.md") == {
        "hash": "digest",
        "last_seen": 1_700_008_000.0,
    }
    assert '"observation_store": "observations.sqlite3"' in checkpoint.read_text()


def test_disabled_registry_tick_reports_degraded_instead_of_healthy_idle(
    tmp_path: Path,
) -> None:
    cfg, spec, _vault = _make_cfg(tmp_path)
    cfg.enable = False

    summary = registry._run_spec_tick(
        cfg,
        spec,
        WatcherState(),
        now=1_700_009_000.0,
        states=None,
        handled_settings_sources=set(),
    )

    assert summary["disabled"] is True
    assert summary["observation_status"] == "degraded"


def test_registry_writer_lock_rejects_concurrent_entrypoint(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"

    with registry._registry_writer_lock(state_dir):
        with pytest.raises(RuntimeError, match="writer already active"):
            with registry._registry_writer_lock(state_dir):
                pass


def test_registry_writer_decorator_reuses_locked_config_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, _spec, _vault = _make_cfg(tmp_path)
    loads: list[Path] = []

    def load_config(path: Path) -> registry.RegistryConfig:
        loads.append(path)
        return cfg

    monkeypatch.setattr(registry, "load_registry_config", load_config)
    observed: list[registry.RegistryConfig | None] = []

    @registry._single_registry_writer
    def entrypoint(
        _config_path: Path,
        *,
        _loaded_config: registry.RegistryConfig | None = None,
    ) -> None:
        observed.append(_loaded_config)

    entrypoint(tmp_path / "watchers.yaml")

    assert len(loads) == 1
    assert observed == [cfg]
