"""A vault delete tombstone may not be reported as purged unless it was queued (#4214 D3).

``_emit_watcher_delete_event`` had no ``required_db`` classification and returned
``True`` unconditionally, so the tick incremented ``deleted_purged`` for an event
the outbox policy had silently skipped. Because this path has no compensating
JSONL sink and ``refresh_snapshot()`` then drops the path, that false purge was
the only signal anyone would ever get.

Two properties are pinned here:

1. only a tombstone that actually landed is counted as a purge;
2. a runtime that NAMES a database keeps `main`'s delivery semantics — the
   enqueue is attempted and an unreachable database raises loudly — rather than
   being silently skipped by the optional-write policy under
   ``STORE_BACKEND=memory``. #4214's constraint says a properly configured
   runtime (``STORE_BACKEND=pg`` *or an explicit DSN*) must not change.

An unlanded deletion is re-observable across a bounded three-attempt policy.
The retry marker is stored separately from the snapshot and every snapshot
writer preserves it, so a bare ``refresh_snapshot()`` cannot erase it.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from app.config.database import RUNTIME_DATABASE_ENV_KEYS
from app.watcher import vault_watcher

pytestmark = pytest.mark.not_pg


def _tick(vault: Path, snapshot_path: Path) -> tuple[dict[str, Any], list[str]]:
    return vault_watcher.run_watcher_tick(
        vault_root=vault,
        snapshot_path=snapshot_path,
        skip_panel=True,
        emit_only=True,
        dry_run=False,
        max_notes=10,
        force=False,
    )


def _seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Concepts" / "D.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    return vault, note, vault / ".state.json"


@pytest.fixture()
def seeded_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """A vault with one ingested note, and `delete_note` stubbed to "can't identify".

    That stub is what routes the tick into the watcher's own tombstone emitter —
    the D3 path. `test_the_tick_terminates_when_no_database_is_named` deliberately
    does NOT use this fixture, because stubbing `delete_note` also stubs away its
    unguarded connection.
    """
    vault, note, snapshot_path = _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    _tick(vault, snapshot_path)
    return vault, note, snapshot_path


def _snapshot(snapshot_path: Path) -> dict[str, float]:
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def test_unqueued_tombstone_is_not_reported_as_purged(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime that names no database queues nothing, so it may not claim a purge."""
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    time.sleep(0.01)
    note.unlink()
    summary, _ = _tick(vault, snapshot_path)

    assert summary["deleted"] == 1
    assert summary["deleted_purged"] == 0, (
        "deleted_purged counted a tombstone the self-owned outbox write skipped"
    )


def test_a_named_database_is_still_delivered_to_under_a_memory_backend(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit DSN must keep `main`'s delivery semantics (#4214 constraint).

    Left optional, the policy would skip this write under ``STORE_BACKEND=memory``
    and drop the tombstone with no purge, no error and no message — a silent,
    permanent loss on a runtime that does have a durable queue and a durable
    projection. The delete path therefore resolves ``required_db`` as
    ``db_outbox_required() or runtime_database_is_named(...)``.
    """
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    attempts: list[bool] = []

    def _writer(*args: object, required_db: bool = False, **kwargs: object) -> str:
        attempts.append(required_db)
        return "queued"

    monkeypatch.setattr(vault_watcher, "insert_object_and_outbox", _writer)

    time.sleep(0.01)
    note.unlink()
    summary, _ = _tick(vault, snapshot_path)

    assert attempts == [True], "an explicit DSN must not be treated as an optional write"
    assert summary["deleted_purged"] == 1


def test_an_unreachable_named_database_fails_loud_instead_of_dropping_silently(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same widening makes an unreachable database observable, not silent."""
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _unavailable(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("required outbox unavailable")

    monkeypatch.setattr(vault_watcher, "insert_object_and_outbox", _unavailable)

    time.sleep(0.01)
    note.unlink()
    summary, messages = _tick(vault, snapshot_path)

    assert summary["deleted_purged"] == 0
    assert summary["errors"] == 1
    assert any("unable to reconcile deletion" in message for message in messages)


def test_required_tombstone_failure_is_recorded_and_retried_with_a_budget(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A required failure is retried, but never retained indefinitely."""
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")

    def _unavailable(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("required outbox unavailable")

    monkeypatch.setattr(vault_watcher, "insert_object_and_outbox", _unavailable)

    time.sleep(0.01)
    note.unlink()
    summary, messages = _tick(vault, snapshot_path)

    assert summary["deleted_purged"] == 0
    assert summary["errors"] == 1
    assert any("unable to reconcile deletion" in message for message in messages)

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 1
    assert second["errors"] == 1

    third, _ = _tick(vault, snapshot_path)
    assert third["unreconciled_deletions_terminated"] == 1
    assert third["errors"] == 0

    fourth, _ = _tick(vault, snapshot_path)
    assert fourth["deleted"] == 0


def test_queued_tombstone_is_counted_once_and_the_snapshot_advances(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    emitted: list[tuple[dict[str, Any], str]] = []
    monkeypatch.setattr(
        vault_watcher,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id=None, **kw: emitted.append((payload, topic)),
    )

    time.sleep(0.01)
    note.unlink()
    summary, _ = _tick(vault, snapshot_path)

    assert summary["deleted_purged"] == 1
    assert len(emitted) == 1
    assert "Concepts/D.md" not in _snapshot(snapshot_path)

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 0, "a reconciled deletion must not be re-reported"


def test_unreconciled_delete_retries_then_terminates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real seam retries twice, survives bare refresh, then terminates."""
    vault, note, snapshot_path = _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _tick(vault, snapshot_path)

    time.sleep(0.01)
    note.unlink()
    first, _ = _tick(vault, snapshot_path)
    assert first["deleted"] == 1
    assert first["deleted_purged"] == 0
    assert first["errors"] == 1

    # The runtime/CLI bare callers use this exact method; it must not erase
    # retryability while the note remains absent from disk.
    vault_watcher.VaultWatcher(vault, snapshot_path=snapshot_path).refresh_snapshot()

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 1
    assert second["errors"] == 1

    third, messages = _tick(vault, snapshot_path)
    assert third["deleted"] == 1
    assert third["errors"] == 0
    assert third["unreconciled_deletions_terminated"] == 1
    assert any("retry budget exhausted" in message for message in messages)

    fourth, _ = _tick(vault, snapshot_path)
    assert fourth["deleted"] == 0
    assert fourth["errors"] == 0


def test_recreated_path_clears_an_old_delete_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new live note may not inherit a prior deletion's retry budget."""
    vault, note, snapshot_path = _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    _tick(vault, snapshot_path)

    time.sleep(0.01)
    note.unlink()
    _tick(vault, snapshot_path)

    note.write_text("Recreated", encoding="utf-8")
    vault_watcher.VaultWatcher(vault, snapshot_path=snapshot_path).refresh_snapshot()

    note.unlink()
    first_new_delete, _ = _tick(vault, snapshot_path)
    assert first_new_delete["errors"] == 1
    assert first_new_delete["unreconciled_deletions_terminated"] == 0


def test_rename_supersedes_the_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rename owes no tombstone and must not be counted as a purge."""
    vault = tmp_path / "vault"
    vault.mkdir()
    old_note = vault / "Concepts" / "E.md"
    old_note.parent.mkdir(parents=True, exist_ok=True)
    old_note.write_text("Body", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    snapshot_path = vault / ".state.json"
    _tick(vault, snapshot_path)

    new_note = vault / "Concepts" / "E-renamed.md"
    emitted: list[object] = []
    monkeypatch.setattr(
        vault_watcher,
        "insert_object_and_outbox",
        lambda payload, topic, trace_id=None, **kw: emitted.append(payload),
    )
    monkeypatch.setattr(
        vault_watcher,
        "read_companion",
        lambda root, note_uuid: type("C", (), {"source_ref": "Concepts/E-renamed.md"})(),
    )

    time.sleep(0.01)
    old_note.rename(new_note)
    summary, _ = _tick(vault, snapshot_path)

    assert summary["deleted_purged"] == 0
    assert emitted == []
    assert "Concepts/E.md" not in _snapshot(snapshot_path)
