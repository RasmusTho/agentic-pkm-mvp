from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.agents.panel_agent import graph as panel_graph
from app.cli.uat import seed_vault_test_notes
from app.components.concurrency import IdempotencyGuard
from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store
from app.store import object_store as object_store_module
from app.watcher import registry
from app.watcher.state import WatcherState
from app.workers import outbox_worker
from scripts.yaml_roundtrip import load_frontmatter
from tests.helpers.pkm_alpha_helper import reset_memory_stores

pytestmark = pytest.mark.not_pg

SEED_SCOPE_GLOB = "Test/AgenticPKM-UAT/*.md,Test/AgenticPKM-UAT/**/*.md"

_VOLATILE_KEYS = {
    "applied_at",
    "created_at",
    "elapsed_ms",
    "event_id",
    "last_processed",
    "modified_at",
    "mtime_ns",
    "tick_ms",
    "tick_start_ts",
    "timestamp",
    "trace_id",
}

_FRONTMATTER_VOLATILE_KEYS = {"maturity", "review_state", "last_ingested"}


@dataclass
class ChainRun:
    registry_records: list[dict[str, Any]]
    final_records: list[dict[str, Any]]
    object_snapshot: dict[str, dict[str, Any]]
    source_snapshot: dict[str, dict[str, Any]]
    companion_snapshot: dict[str, dict[str, Any]]
    ingest_summary: dict[str, object]
    panel_summary: dict[str, object]
    promotion_summary: dict[str, object]


def _reset_runtime_state() -> None:
    reset_memory_stores()
    reset_promotion_dedup_store()
    panel_graph._IDEMPOTENCY_GUARD = IdempotencyGuard(ttl_seconds=86400.0)


def _write_registry_config(path: Path) -> None:
    path.write_text(
        """\
version: 1
watchers:
  - name: ingest
    scope_glob: "${WATCHER_SCOPE_GLOB}"
    debounce_ms: 0
    rate_limit_per_min: 120
    emit_event: "ingest.vault.changed"
    backoff_seconds: 0
  - name: panel
    scope_glob: "${WATCHER_SCOPE_GLOB}"
    debounce_ms: 0
    rate_limit_per_min: 120
    emit_event: "panel.scan.requested"
    backoff_seconds: 0
""",
        encoding="utf-8",
    )


def _configure_runtime_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vault_root: Path,
    outbox_path: Path,
    state_dir: Path,
) -> None:
    resolved_vault_root = vault_root.expanduser().resolve()
    resolved_outbox_path = outbox_path.expanduser().resolve()
    resolved_state_dir = state_dir.expanduser().resolve()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(resolved_vault_root))
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", SEED_SCOPE_GLOB)
    monkeypatch.setenv("WATCHER_STATE_DIR", str(resolved_state_dir))
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str((resolved_state_dir / "heartbeat.json").resolve()))
    monkeypatch.setenv("WATCHER_TICK_LOG_PATH", str((resolved_state_dir / "tick.jsonl").resolve()))
    monkeypatch.setenv("WATCHER_STOP_FILE", str((resolved_state_dir / "WATCHER_STOP").resolve()))
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "0")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0")
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "0")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "120")
    monkeypatch.setenv("WATCHER_AUTO_EXEC", "1")
    monkeypatch.setenv("PANEL_AGENT_DECIDER", "rule")
    monkeypatch.setenv("PANEL_AGENT_PIPELINE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(resolved_outbox_path))


def _load_registry_config(config_path: Path, monkeypatch: pytest.MonkeyPatch, *, outbox_path: Path, state_dir: Path, vault_root: Path) -> registry.RegistryConfig:
    _configure_runtime_env(monkeypatch, vault_root=vault_root, outbox_path=outbox_path, state_dir=state_dir)
    return registry.load_registry_config(config_path)


def _run_tick(
    monkeypatch: pytest.MonkeyPatch,
    cfg: registry.RegistryConfig,
    spec: registry.WatcherSpec,
    state: WatcherState,
    *,
    now: float,
) -> dict[str, object]:
    monkeypatch.setattr(registry.time, "time", lambda: now)
    return registry._run_spec_tick(cfg, spec, state, now=now, process_panel_notes_inline=False)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in _VOLATILE_KEYS:
                continue
            if key == "ingest_fingerprint" and isinstance(item, dict):
                cleaned[key] = {k: _strip_volatile(v) for k, v in item.items() if k not in {"mtime_ns"}}
                continue
            cleaned[key] = _strip_volatile(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    return value


def _snapshot_objects() -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for object_id, domain_object in sorted(object_store_module._MEMORY_STORE.items()):
        source_ref = domain_object.source_ref
        if isinstance(source_ref, str) and Path(source_ref).name == "golden.md":
            continue
        snapshot[object_id] = {
            "kind": domain_object.kind,
            "source_ref": source_ref,
            "payload": _stable_object_payload(domain_object.payload),
        }
    return snapshot


def _stable_object_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "content",
        "executed_action_ids",
        "ingest_fingerprint",
        "panel_logs",
        "promotion",
        "raw_text",
        "text",
    }
    if not isinstance(payload, dict):
        return _strip_volatile(payload)
    stable_payload: dict[str, Any] = {}
    for key, value in payload.items():
        if key in ignored:
            continue
        if key == "frontmatter" and isinstance(value, dict):
            stable_payload[key] = {
                fm_key: _strip_volatile(fm_value)
                for fm_key, fm_value in value.items()
                if fm_key not in _FRONTMATTER_VOLATILE_KEYS
            }
            continue
        stable_payload[key] = _strip_volatile(value)
    return stable_payload


def _snapshot_markdown_files(root: Path, files: list[Path]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(files):
        frontmatter, body = load_frontmatter(path.read_text(encoding="utf-8"))
        snapshot[str(path.relative_to(root))] = {
            "frontmatter": {
                key: _strip_volatile(value)
                for key, value in (frontmatter if isinstance(frontmatter, dict) else {}).items()
                if key not in _FRONTMATTER_VOLATILE_KEYS
            },
            "body": body,
        }
    return snapshot


def _seeded_note_paths(seed_folder: Path) -> list[Path]:
    return sorted(seed_folder.glob("*.md"))


def _companion_paths(vault_root: Path) -> list[Path]:
    companions_dir = vault_root / "_system" / "companions"
    if not companions_dir.exists():
        return []
    return sorted(companions_dir.rglob("*.md"))


def _project_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") or {}
    event = record.get("event")
    if event in {INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED}:
        projected = {
            "event": event,
            "relative_path": payload.get("relative_path"),
            "watcher": payload.get("watcher"),
            "hash": payload.get("hash"),
        }
        return _strip_volatile(projected)
    if event in {"panel.intent.created", "panel.intent.executed"}:
        note = payload.get("note") or {}
        panel = payload.get("panel") or {}
        projected = {
            "event": event,
            "note_uuid": note.get("uuid"),
            "note_path": note.get("path"),
            "panel_id": panel.get("panel_id"),
            "actions": [action.get("id") for action in payload.get("actions", []) if isinstance(action, dict)],
        }
        return _strip_volatile(projected)
    if event == "promote.intent.created":
        note = payload.get("note") or {}
        action = payload.get("action") or {}
        projected = {
            "event": event,
            "note_uuid": note.get("uuid"),
            "note_path": note.get("path"),
            "action_id": action.get("id"),
            "maturity": payload.get("maturity"),
            "review_state": payload.get("review_state"),
        }
        return _strip_volatile(projected)
    if event == "promote.done":
        projected = {
            "event": event,
            "note_uuid": payload.get("note_uuid"),
            "note_path": payload.get("note_path"),
            "state": payload.get("state"),
            "maturity": payload.get("maturity"),
            "review_state": payload.get("review_state"),
        }
        return _strip_volatile(projected)
    return _strip_volatile({"event": event, "payload": payload})


def _dispatch_worker_records(records: list[dict[str, Any]], *, vault_root: Path) -> None:
    for record in records:
        event = record.get("event")
        payload = record.get("payload") or {}
        if event == INGEST_VAULT_CHANGED:
            outbox_worker.handle_ingest_vault_changed(payload, vault_root=vault_root)
        elif event == PANEL_SCAN_REQUESTED:
            outbox_worker.handle_panel_scan_requested(payload, vault_root=vault_root)


def _run_chain(
    *,
    monkeypatch: pytest.MonkeyPatch,
    vault_root: Path,
    seed_folder: Path,
    config_path: Path,
    outbox_path: Path,
    state_dir: Path,
    ingest_state: WatcherState,
    panel_state: WatcherState,
) -> ChainRun:
    monkeypatch.setattr(
        registry,
        "_maybe_heal_ingest_uuid",
        lambda cfg, state, rel_path, mtime, digest: (mtime, digest),
    )
    monkeypatch.setattr(outbox_worker, "_maybe_heal_uuid", lambda note_path, vault_root: "")
    cfg = _load_registry_config(config_path, monkeypatch, outbox_path=outbox_path, state_dir=state_dir, vault_root=vault_root)
    ingest_spec, panel_spec = cfg.specs

    ingest_summary = _run_tick(monkeypatch, cfg, ingest_spec, ingest_state, now=1_700_000_000.0)
    panel_summary = _run_tick(monkeypatch, cfg, panel_spec, panel_state, now=1_700_000_001.0)

    registry_records = _read_records(outbox_path)
    _dispatch_worker_records(registry_records, vault_root=vault_root)
    promotion_summary = consume_promotion_intents(outbox_path=outbox_path)
    final_records = _read_records(outbox_path)

    return ChainRun(
        registry_records=registry_records,
        final_records=final_records,
        object_snapshot=_snapshot_objects(),
        source_snapshot=_snapshot_markdown_files(seed_folder, _seeded_note_paths(seed_folder)),
        companion_snapshot=_snapshot_markdown_files(vault_root, _companion_paths(vault_root)),
        ingest_summary=ingest_summary,
        panel_summary=panel_summary,
        promotion_summary=promotion_summary,
    )


def _assert_duplicate_gates(run: ChainRun) -> None:
    event_ids = [str(record.get("event_id") or "") for record in run.final_records if record.get("event")]
    assert len(event_ids) == len(set(event_ids))

    promote_intents = [record for record in run.final_records if record.get("event") == "promote.intent.created"]
    note_uuids = [record.get("payload", {}).get("note", {}).get("uuid") for record in promote_intents]
    assert len(note_uuids) == len(set(note_uuids))


def _assert_chain_contract(run: ChainRun, *, expected_note_count: int) -> None:
    assert int(run.ingest_summary.get("changed_in_tick", 0)) == expected_note_count
    assert int(run.ingest_summary.get("emitted_in_tick", 0)) == expected_note_count
    assert int(run.panel_summary.get("changed_in_tick", 0)) == expected_note_count
    assert int(run.panel_summary.get("panel_candidates", 0)) >= 1

    events = {record.get("event") for record in run.final_records}
    required = {
        INGEST_VAULT_CHANGED,
        PANEL_SCAN_REQUESTED,
        "panel.intent.created",
        "panel.intent.executed",
        "promote.intent.created",
        "promote.done",
    }
    assert required <= events
    _assert_duplicate_gates(run)


def test_registry_chain_contract_and_rerun_idempotence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_runtime_state()

    vault_root = tmp_path / "vault"
    seed = seed_vault_test_notes(vault_root=vault_root, target_subdir="Test")
    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)
    state_dir = tmp_path / "state"
    first_outbox = tmp_path / "outbox-first.jsonl"
    ingest_state = WatcherState()
    panel_state = WatcherState()

    first = _run_chain(
        monkeypatch=monkeypatch,
        vault_root=vault_root,
        seed_folder=seed.destination,
        config_path=config_path,
        outbox_path=first_outbox,
        state_dir=state_dir,
        ingest_state=ingest_state,
        panel_state=panel_state,
    )

    _assert_chain_contract(first, expected_note_count=len(_seeded_note_paths(seed.destination)))
    assert first.promotion_summary["applied"] >= 1
    assert first.object_snapshot
    assert first.source_snapshot
    assert first.companion_snapshot

    rerun_outbox = tmp_path / "outbox-rerun.jsonl"
    rerun = _run_chain(
        monkeypatch=monkeypatch,
        vault_root=vault_root,
        seed_folder=seed.destination,
        config_path=config_path,
        outbox_path=rerun_outbox,
        state_dir=state_dir,
        ingest_state=ingest_state,
        panel_state=panel_state,
    )

    assert rerun.promotion_summary["applied"] == 0
    assert rerun.promotion_summary["intents_seen"] == 0
    assert rerun.object_snapshot == first.object_snapshot
    assert rerun.source_snapshot == first.source_snapshot
    assert rerun.companion_snapshot == first.companion_snapshot
    assert rerun.registry_records
    assert rerun.final_records
    assert all(record.get("event") != "promote.intent.created" for record in rerun.final_records)
    assert all(record.get("event") != "promote.done" for record in rerun.final_records)
    _assert_duplicate_gates(rerun)


def test_registry_cold_rebuild_recreates_final_state_from_seed_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reset_runtime_state()

    vault_root = tmp_path / "vault"
    seed = seed_vault_test_notes(vault_root=vault_root, target_subdir="Test")
    config_path = tmp_path / "watchers.yaml"
    _write_registry_config(config_path)
    state_dir = tmp_path / "state"
    first_outbox = tmp_path / "outbox-first.jsonl"

    first = _run_chain(
        monkeypatch=monkeypatch,
        vault_root=vault_root,
        seed_folder=seed.destination,
        config_path=config_path,
        outbox_path=first_outbox,
        state_dir=state_dir,
        ingest_state=WatcherState(),
        panel_state=WatcherState(),
    )

    _reset_runtime_state()

    rebuild = _run_chain(
        monkeypatch=monkeypatch,
        vault_root=vault_root,
        seed_folder=seed.destination,
        config_path=config_path,
        outbox_path=tmp_path / "outbox-rebuild.jsonl",
        state_dir=tmp_path / "state-rebuild",
        ingest_state=WatcherState(),
        panel_state=WatcherState(),
    )

    assert rebuild.object_snapshot == first.object_snapshot
    assert rebuild.source_snapshot == first.source_snapshot
    assert rebuild.companion_snapshot == first.companion_snapshot
    _assert_duplicate_gates(rebuild)
