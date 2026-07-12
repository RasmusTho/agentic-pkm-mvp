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
    validate_signboard,
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


def test_notes_containing_a_markdown_heading_survive_reexport(
    tmp_env, store, tmp_path: Path
) -> None:
    """A human note that itself contains a "## "-prefixed line (a pasted
    heading, a quoted snippet) must not be truncated at that line — only the
    generator's own "## Receipts" heading is a real section boundary."""
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    original = card.read_text(encoding="utf-8")
    hand_written = original.replace(
        "## Notes\n\n## Receipts",
        "## Notes\n\n"
        "Reminder: format headings like this:\n"
        "## Something\n"
        "Don't drop this line please.\n\n"
        "## Receipts",
    )
    card.write_text(hand_written, encoding="utf-8")

    export_signboard(store, board)

    content = next(board.glob(f"**/{ready.task_id}--*.md")).read_text(encoding="utf-8")
    assert "Reminder: format headings like this:" in content
    assert "## Something" in content
    assert "Don't drop this line please." in content


def test_notes_quoting_receipts_heading_survive_reexport(
    tmp_env, store, tmp_path: Path
) -> None:
    """A human quoting the literal text "## Receipts" earlier in their own
    notes must not be mistaken for the generator's real trailing boundary —
    only the *last* "## Receipts" line (always the generator's own) is the
    true boundary."""
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    original = card.read_text(encoding="utf-8")
    # The quoted line is a genuine standalone "## Receipts" heading line (not
    # embedded mid-sentence), so it round-trips through the same
    # `line.strip() == "## Receipts"` match the real boundary uses. Only
    # matching the *last* such line (the generator's own) instead of the
    # first (the human's quoted one) keeps the text below it intact.
    hand_written = original.replace(
        "## Notes\n\n## Receipts",
        "## Notes\n\n"
        "Reminder: cards end with a heading like this one:\n"
        "## Receipts\n"
        "Don't lose this last line either.\n\n"
        "## Receipts",
    )
    card.write_text(hand_written, encoding="utf-8")

    export_signboard(store, board)

    content = next(board.glob(f"**/{ready.task_id}--*.md")).read_text(encoding="utf-8")
    assert "Reminder: cards end with a heading like this one:" in content
    assert "Don't lose this last line either." in content


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


def test_reexport_never_deletes_a_non_generated_file_with_a_colliding_name(
    tmp_env, store, tmp_path: Path
) -> None:
    """A human file that happens to share a card's exact filename in another
    column must never be deleted just because the filename matches.

    Regression: export_signboard used to run a second cleanup pass keyed on
    filename alone (no ``generated_by: dispatcher.signboard`` check), which
    could delete an unrelated human-authored file purely by naming collision.
    """
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "board"

    export_signboard(store, board)
    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    filename = card.name

    done_dir = board / "Done"
    done_dir.mkdir(parents=True, exist_ok=True)
    human_file = done_dir / filename
    human_file.write_text("# My own notes, not generated by dispatcher\n", encoding="utf-8")

    export_signboard(store, board)

    assert human_file.exists()
    assert human_file.read_text(encoding="utf-8") == "# My own notes, not generated by dispatcher\n"


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


# ---------------------------------------------------------------------------
# Multi-repo coverage: a card's originating repo is visible in the projection
# ---------------------------------------------------------------------------


def test_exported_card_carries_its_source_repo(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    ready.repo = "RasmusTho/bifrost"
    store.upsert_task(ready)
    board = tmp_path / "board"

    export_signboard(store, board)

    card = next(board.glob(f"**/{ready.task_id}--*.md"))
    content = card.read_text(encoding="utf-8")
    assert 'repo: "RasmusTho/bifrost"' in content
    assert "- Repo: `RasmusTho/bifrost`" in content


# ---------------------------------------------------------------------------
# #3439: read-only Signboard validation
# ---------------------------------------------------------------------------


def test_validate_clean_board_passes(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    board = tmp_path / "board"

    export_signboard(store, board)

    result = validate_signboard(store, board)

    assert result["count"] == len(tasks)
    assert result["findings"] == []


def test_validate_detects_duplicate_cards(tmp_env, store, tmp_path: Path) -> None:
    ready = next(task for task in seed_tasks(store) if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    card = next((board / "Ready").glob(f"{ready.task_id}--*.md"))
    duplicate = board / "Done" / card.name
    duplicate.write_text(card.read_text(encoding="utf-8"), encoding="utf-8")

    result = validate_signboard(store, board)

    assert any(finding["kind"] == "duplicate_card" for finding in result["findings"])


def test_validate_detects_column_status_mismatch(tmp_env, store, tmp_path: Path) -> None:
    ready = next(task for task in seed_tasks(store) if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    card = next((board / "Ready").glob(f"{ready.task_id}--*.md"))
    wrong = board / "Done" / card.name
    wrong.write_text(card.read_text(encoding="utf-8"), encoding="utf-8")
    card.unlink()

    result = validate_signboard(store, board)

    assert any(finding["kind"] == "column_status_mismatch" for finding in result["findings"])


def test_validate_detects_stale_card_for_missing_task(tmp_env, store, tmp_path: Path) -> None:
    ready = next(task for task in seed_tasks(store) if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    card = next((board / "Ready").glob(f"{ready.task_id}--*.md"))
    content = card.read_text(encoding="utf-8").replace(f'id: "{ready.task_id}"', 'id: "gone"')
    card.write_text(content, encoding="utf-8")

    result = validate_signboard(store, board)

    assert any(finding["kind"] == "stale_card" for finding in result["findings"])


def test_validate_detects_malformed_generated_card(tmp_env, store, tmp_path: Path) -> None:
    seed_tasks(store)
    board = tmp_path / "board"
    malformed = board / "Ready" / "task-bad--broken.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("---\ngenerated_by: dispatcher.signboard\nid: [\n---\n", encoding="utf-8")

    result = validate_signboard(store, board)

    assert any(finding["kind"] == "malformed_generated_card" for finding in result["findings"])


def test_validate_reports_unreadable_card_without_mutation(
    tmp_env, store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_tasks(store)
    board = tmp_path / "board"
    candidate = board / "Ready" / "task-unreadable--candidate.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("not read", encoding="utf-8")
    original_read_text = Path.read_text

    def unreadable_read_text(path: Path, *args, **kwargs):
        if path == candidate:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable_read_text)

    result = validate_signboard(store, board)

    assert any(finding["kind"] == "unreadable_generated_card_candidate" for finding in result["findings"])
    assert candidate.exists()


def test_validate_ignores_human_authored_files(tmp_env, store, tmp_path: Path) -> None:
    seed_tasks(store)
    board = tmp_path / "board"
    human = board / "Ready" / "task-human--notes.md"
    human.parent.mkdir(parents=True)
    human.write_text("# Human notes\n", encoding="utf-8")

    result = validate_signboard(store, board)

    assert result["findings"] == []


def test_cli_signboard_validate_fails_loud_on_findings(
    tmp_env, store, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.dispatcher.cli import main

    seed_tasks(store)
    board = tmp_path / "board"
    broken = board / "Ready" / "task-bad--broken.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("---\ngenerated_by: dispatcher.signboard\nid: [\n---\n", encoding="utf-8")

    exit_code = main(["signboard-validate", str(board), "--json"])

    assert exit_code == 1
    assert '"ok": false' in capsys.readouterr().out
