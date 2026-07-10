"""Unit tests for the Signboard Markdown projection (#3312).

Covers:
- human-authored "## Notes" content survives re-export (no blind overwrite);
- default vault-path resolution reuses the shipped active-vault-selection
  mechanism instead of requiring a manually typed path;
- a governance regression guarding against reintroducing claim/lock writes
  into the external BuilderOps Vault projection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dispatcher import signboard as signboard_module
from app.dispatcher.signboard import (
    DEFAULT_SIGNBOARD_SUBPATH,
    NoActiveVaultError,
    default_signboard_root,
    export_signboard,
)
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.store import SqliteStore
from app.vault.manager import VaultContext
from tests.dispatcher.helpers import seed_tasks


@pytest.fixture()
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    state_dir = tmp_path / "dispatcher"
    env = {
        "DISPATCHER_STATE_DIR": str(state_dir),
        "DISPATCHER_DB_PATH": str(state_dir / "dispatcher.sqlite3"),
        "DISPATCHER_EVENTS_PATH": str(state_dir / "events.jsonl"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture()
def store(tmp_env: dict[str, str]) -> SqliteStore:
    paths = load_paths(tmp_env)
    writer = JsonlEventWriter(paths.events_path)
    s = SqliteStore(db_path=paths.db_path, event_writer=writer)
    s.initialize()
    return s


class _StubVaultManager:
    """Minimal stand-in for VaultManager exposing only what the resolver reads."""

    def __init__(self, context: VaultContext) -> None:
        self._context = context

    @property
    def context(self) -> VaultContext:
        return self._context

    def load_last_active(self) -> VaultContext:
        return self._context


# ---------------------------------------------------------------------------
# AC1: human-authored notes survive re-export
# ---------------------------------------------------------------------------


def test_reexport_preserves_human_authored_notes(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    card_paths = list(board.glob(f"**/{ready.task_id}--*.md"))
    assert len(card_paths) == 1
    card = card_paths[0]

    original = card.read_text(encoding="utf-8")
    assert "generated_by: dispatcher.signboard" in original
    hand_written = original.replace(
        "## Notes\n\n## Receipts",
        "## Notes\n\nDon't forget to ping the owner before merging.\n\n## Receipts",
    )
    card.write_text(hand_written, encoding="utf-8")

    # Refresh a generated field (status) so the re-export actually rewrites
    # frontmatter/body while notes must remain intact.
    ready.status = "review"
    store.upsert_task(ready)

    export_signboard(store, board)

    reexported = list(board.glob(f"**/{ready.task_id}--*.md"))
    assert len(reexported) == 1
    content = reexported[0].read_text(encoding="utf-8")
    assert 'status: "review"' in content
    assert "Don't forget to ping the owner before merging." in content


def test_reexport_with_empty_notes_stays_empty(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    export_signboard(store, board)

    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    content = card.read_text(encoding="utf-8")
    assert "## Notes\n\n## Receipts" in content


def test_notes_preserved_across_column_move(tmp_env, store, tmp_path: Path) -> None:
    """A status change moves the card to a new column/file; notes must follow."""
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    content = card.read_text(encoding="utf-8")
    content = content.replace(
        "## Notes\n\n## Receipts", "## Notes\n\nKeep an eye on flaky CI.\n\n## Receipts"
    )
    card.write_text(content, encoding="utf-8")

    ready.status = "blocked"
    ready.blocked_reason = "waiting on owner"
    store.upsert_task(ready)
    export_signboard(store, board)

    moved = next(board.glob(f"**/{ready.task_id}--*.md"))
    assert (board / "Blocked") in moved.parents
    moved_content = moved.read_text(encoding="utf-8")
    assert "Keep an eye on flaky CI." in moved_content


# ---------------------------------------------------------------------------
# AC2: default vault-path resolution (no manually typed path required)
# ---------------------------------------------------------------------------


def test_default_signboard_root_resolves_from_active_vault(tmp_path, monkeypatch) -> None:
    vault_dir = tmp_path / "MyVault"
    vault_dir.mkdir()
    context = VaultContext(status="selected", active_vault_path=str(vault_dir))
    monkeypatch.setattr(
        signboard_module, "get_vault_manager", lambda: _StubVaultManager(context)
    )

    resolved = default_signboard_root()

    assert resolved == (vault_dir.resolve() / DEFAULT_SIGNBOARD_SUBPATH)


def test_default_signboard_root_falls_back_to_load_last_active(tmp_path, monkeypatch) -> None:
    vault_dir = tmp_path / "LastActiveVault"
    vault_dir.mkdir()
    context = VaultContext(status="selected", active_vault_path=str(vault_dir))

    class _NoneThenLoaded(_StubVaultManager):
        def __init__(self) -> None:
            super().__init__(VaultContext(status="none"))
            self._loaded = context

        def load_last_active(self) -> VaultContext:
            return self._loaded

    monkeypatch.setattr(signboard_module, "get_vault_manager", _NoneThenLoaded)

    resolved = default_signboard_root()

    assert resolved == (vault_dir.resolve() / DEFAULT_SIGNBOARD_SUBPATH)


def test_default_signboard_root_raises_when_no_vault_selected(monkeypatch) -> None:
    context = VaultContext(status="none")
    monkeypatch.setattr(
        signboard_module, "get_vault_manager", lambda: _StubVaultManager(context)
    )

    with pytest.raises(NoActiveVaultError):
        default_signboard_root()


def test_cli_export_signboard_without_path_uses_default_vault(
    tmp_env, store, tmp_path, monkeypatch
) -> None:
    from app.dispatcher.cli import main

    seed_tasks(store)
    vault_dir = tmp_path / "ActiveVault"
    vault_dir.mkdir()
    context = VaultContext(status="selected", active_vault_path=str(vault_dir))
    monkeypatch.setattr(
        signboard_module, "get_vault_manager", lambda: _StubVaultManager(context)
    )

    exit_code = main(["export-signboard", "--json"])

    assert exit_code == 0
    expected_root = vault_dir.resolve() / DEFAULT_SIGNBOARD_SUBPATH
    assert expected_root.is_dir()
    assert any(expected_root.rglob("*.md"))


def test_cli_export_signboard_explicit_path_still_supported(
    tmp_env, store, tmp_path
) -> None:
    from app.dispatcher.cli import main

    seed_tasks(store)
    board = tmp_path / "explicit-board"

    exit_code = main(["export-signboard", str(board), "--json"])

    assert exit_code == 0
    assert board.is_dir()


# ---------------------------------------------------------------------------
# AC3: governance — no claim/lock writes into the external vault
# ---------------------------------------------------------------------------


def test_signboard_module_has_no_claims_or_locks_write_path() -> None:
    source = Path(signboard_module.__file__).read_text(encoding="utf-8")
    assert ".builderops/claims" not in source
    assert ".builderops/locks" not in source
    # Belt-and-suspenders: the module must not import sqlite3 or any lock
    # primitive for the vault-facing projection surface.
    assert "import sqlite3" not in source
    assert "fcntl" not in source
