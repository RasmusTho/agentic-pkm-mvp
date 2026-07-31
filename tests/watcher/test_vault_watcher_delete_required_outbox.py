"""A vault delete tombstone may not be reported as purged unless it was queued (#4214 D3).

``_emit_watcher_delete_event`` had no compensating sink, no ``required_db``
classification, and returned ``True`` unconditionally. Its caller then both
incremented ``deleted_purged`` and let ``refresh_snapshot()`` drop the path from
the snapshot — so a tombstone that never reached the outbox was permanently
unrecoverable: the note is gone from disk AND from the snapshot, later ticks
never re-see the deletion, and the deleted content stays indexed.
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


@pytest.fixture()
def seeded_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "Concepts" / "D.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("Body", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.setenv("WATCHER_RUN_LOG_PATH", str(tmp_path / "watcher_run.jsonl"))
    # delete_note cannot identify the note (no file_state row), so the tick
    # falls through to the watcher's own tombstone emitter — the D3 path.
    monkeypatch.setattr(vault_watcher, "delete_note", lambda path, **kw: False)
    snapshot_path = vault / ".state.json"
    _tick(vault, snapshot_path)
    return vault, note, snapshot_path


def _snapshot(snapshot_path: Path) -> dict[str, float]:
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def test_unqueued_tombstone_is_not_reported_as_purged(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit memory runtime queues nothing, so it may not claim a purge."""
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    time.sleep(0.01)
    note.unlink()
    summary, _ = _tick(vault, snapshot_path)

    assert summary["deleted"] == 1
    assert summary["deleted_purged"] == 0, (
        "deleted_purged counted a tombstone the self-owned outbox write skipped"
    )


def test_unqueued_tombstone_stays_reobservable_on_the_next_tick(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshot must retain a deletion no sink accepted, so it can retry.

    The runtime NAMES a database (so a durable queue and a durable projection
    exist and the tombstone is genuinely owed) while the explicit memory backend
    makes the optional self-owned write skip — the configuration in which D3's
    loss is real.
    """
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    time.sleep(0.01)
    note.unlink()
    _tick(vault, snapshot_path)

    assert "Concepts/D.md" in _snapshot(snapshot_path), (
        "refresh_snapshot() dropped a path whose tombstone was never queued; "
        "the deletion can never be re-observed"
    )

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 1, "the unreconciled deletion must be re-detected"


def test_required_tombstone_failure_keeps_the_deletion_retryable(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A required enqueue that raises must not consume the observation."""
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
    assert "Concepts/D.md" in _snapshot(snapshot_path)

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 1, "a failed required tombstone must be retried"


def test_queued_tombstone_still_advances_the_snapshot(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retention must be scoped to failures — a real purge still completes."""
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


def test_retention_survives_a_bare_refresh_snapshot_from_outside_the_tick(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retention must be durable, not a local variable of the tick.

    ``refresh_snapshot`` has callers outside ``run_watcher_tick`` —
    ``app/runtime/runtime_loop.py``, ``app/cli/uat.py``,
    ``app/cli/latency_harness.py`` — which construct their own ``VaultWatcher``
    and call it with no arguments. Holding the retained set in the tick's local
    scope let the very next bare call rescan disk (where the deleted note is
    gone) and silently undo the retention, restoring the exact D3 loss.
    """
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")

    def _unavailable(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("required outbox unavailable")

    monkeypatch.setattr(vault_watcher, "insert_object_and_outbox", _unavailable)

    time.sleep(0.01)
    note.unlink()
    _tick(vault, snapshot_path)
    assert "Concepts/D.md" in _snapshot(snapshot_path)

    # Exactly what runtime_loop.run_once does after the tick.
    vault_watcher.VaultWatcher(vault, snapshot_path=snapshot_path).refresh_snapshot()

    assert "Concepts/D.md" in _snapshot(snapshot_path), (
        "a bare refresh_snapshot() from outside the tick dropped the retained deletion"
    )
    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 1, "the deletion must still be retryable"


def test_a_reconciled_deletion_clears_the_durable_retention(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sidecar is authoritative per tick, so retention must not leak forever."""
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    failing = {"now": True}

    def _writer(*args: object, **kwargs: object) -> Any:
        if failing["now"]:
            raise RuntimeError("required outbox unavailable")
        return "queued"

    monkeypatch.setattr(vault_watcher, "insert_object_and_outbox", _writer)

    time.sleep(0.01)
    note.unlink()
    _tick(vault, snapshot_path)
    sidecar = vault_watcher.unreconciled_deletions_path(snapshot_path)
    assert sidecar.exists() and "Concepts/D.md" in json.loads(sidecar.read_text(encoding="utf-8"))

    failing["now"] = False
    second, _ = _tick(vault, snapshot_path)

    assert second["deleted_purged"] == 1
    assert not sidecar.exists(), "a reconciled deletion must stop being retained"
    assert "Concepts/D.md" not in _snapshot(snapshot_path)

    third, _ = _tick(vault, snapshot_path)
    assert third["deleted"] == 0, "the retention must terminate once reconciled"


def test_a_runtime_naming_no_database_does_not_retain_forever(
    seeded_vault: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No named database means no durable queue and no durable projection.

    Nothing is owed and nothing will ever accept the tombstone, so retaining it
    would re-report the same deletion on every tick forever.
    """
    vault, note, snapshot_path = seeded_vault
    monkeypatch.setenv("STORE_BACKEND", "memory")
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    time.sleep(0.01)
    note.unlink()
    summary, _ = _tick(vault, snapshot_path)

    assert summary["deleted_purged"] == 0, "no event was queued, so no purge may be counted"
    assert "Concepts/D.md" not in _snapshot(snapshot_path)
    assert not vault_watcher.unreconciled_deletions_path(snapshot_path).exists()

    second, _ = _tick(vault, snapshot_path)
    assert second["deleted"] == 0, "the deletion must not be re-reported forever"


def test_rename_supersedes_the_tombstone_without_retaining_the_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rename owes no tombstone, so the snapshot must still move on."""
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
    assert "Concepts/E.md" not in _snapshot(snapshot_path), (
        "a rename owes no tombstone; retaining the old path would re-report it forever"
    )
