"""Unit tests for the Signboard Markdown projection (#3312).

Covers:
- human-authored "## Notes" content survives re-export (no blind overwrite);
- default vault-path resolution reuses the shipped active-vault-selection
  mechanism instead of requiring a manually typed path;
- a governance regression guarding against reintroducing claim/lock writes
  into the external BuilderOps Vault projection.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.dispatcher import signboard as signboard_module
from app.dispatcher.signboard import (
    DEFAULT_SIGNBOARD_SUBPATH,
    STORE_STAMP_FILENAME,
    NoActiveVaultError,
    SignboardStoreOwnershipError,
    default_signboard_root,
    export_signboard,
    read_store_identity,
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


# ---------------------------------------------------------------------------
# #4324: same-column content drift (stale title/priority/claim/PR metadata)
# ---------------------------------------------------------------------------


def test_validate_signboard_detects_same_column_content_drift(
    tmp_env, store, tmp_path: Path
) -> None:
    """A card whose column is still correct but whose generated content has
    drifted from the live task (title, priority, claim, or linked PR) must
    still fail validation. `validate_signboard` previously only compared
    column placement, so a same-column stale card passed silently."""
    ready = next(task for task in seed_tasks(store) if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    card = next((board / "Ready").glob(f"{ready.task_id}--*.md"))

    # Task changes without a re-export: title, priority, claim, and linked PR
    # drift while status/column stay "ready"/"Ready".
    ready.title = "Test: implement feature A (renamed)"
    ready.priority = "high" if ready.priority != "high" else "med"
    ready.claimed_by = "agent-drift"
    ready.linked_pr = "9999"
    store.upsert_task(ready)

    result = validate_signboard(store, board)

    drift_findings = [f for f in result["findings"] if f["kind"] == "content_drift"]
    assert len(drift_findings) == 1
    assert drift_findings[0]["path"] == str(card.relative_to(board))
    assert not any(f["kind"] == "stale_card" for f in result["findings"])
    assert not any(f["kind"] == "column_status_mismatch" for f in result["findings"])


def test_validate_signboard_reports_repair_for_content_drift(
    tmp_env, store, tmp_path: Path
) -> None:
    """Content-drift findings must name the normal export repair path, the
    same as the existing stale-card repair guidance (#4198)."""
    ready = next(task for task in seed_tasks(store) if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)

    ready.claimed_by = "agent-drift"
    store.upsert_task(ready)

    result = validate_signboard(store, board)

    assert any(f["kind"] == "content_drift" for f in result["findings"])
    assert "export-signboard" in result["repair"]


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



# ---------------------------------------------------------------------------
# #4198: one Signboard root, and a repair path for cards absent from the store
# ---------------------------------------------------------------------------


def test_signboard_root_is_single_sourced() -> None:
    """The board-root default is spelled in exactly one place.

    Three independent resolutions of the Signboard root (the API route, the
    full-stack launcher, and the vault-relative dispatcher default) is the
    divergence #4198 removes. The launchers must derive from
    ``default_signboard_root`` instead of carrying a home-relative literal of
    their own. Since #4401 the API route resolves no root at all — it serves the
    board from the dispatcher store — so it carries neither the literal nor a
    resolution of its own.
    """
    repo_root = Path(signboard_module.__file__).resolve().parents[2]
    literal = "BuilderOpsVault"

    for relative in (
        "app/api/routes/signboard.py",
        "scripts/start_full_system.sh",
        "scripts/export_runtime_env.sh",
        "scripts/lib/signboard_root.sh",
    ):
        source = (repo_root / relative).read_text(encoding="utf-8")
        assert literal not in source, f"{relative} must not carry its own board-root literal"

    assert literal in Path(signboard_module.__file__).read_text(encoding="utf-8")


def test_export_remains_the_only_board_root_consumer(monkeypatch, tmp_path) -> None:
    """The legacy export still resolves the single-sourced root; the API does not.

    The board root exists for ``export-signboard`` only now. The API route must
    not reintroduce a root: reading back a filesystem copy of the store is the
    loop #4401 removed.
    """
    from app.api.routes import signboard as signboard_route

    vault_dir = tmp_path / "RouteVault"
    vault_dir.mkdir()
    context = VaultContext(status="selected", active_vault_path=str(vault_dir))
    monkeypatch.setattr(
        signboard_module, "get_vault_manager", lambda: _StubVaultManager(context)
    )

    monkeypatch.delenv("SIGNBOARD_ROOT", raising=False)
    assert default_signboard_root() == vault_dir.resolve() / DEFAULT_SIGNBOARD_SUBPATH

    for retired in ("signboard_root", "read_signboard", "parse_signboard_markdown"):
        assert not hasattr(signboard_route, retired)
    route_source = Path(signboard_route.__file__).read_text(encoding="utf-8")
    assert "SIGNBOARD_ROOT" not in route_source


def test_export_and_validate_commands_announce_themselves_as_legacy() -> None:
    """Both commands still work, and both say they are legacy (#4401).

    Deprecation here is a `--help` promise made to operators with a live board;
    ``docs/AGENT_ISSUE_DISPATCHER.md :: Signboard projection`` states it, so it
    has to stay true.
    """
    from app.dispatcher.cli import build_parser

    parser = build_parser()
    top_level_help = parser.format_help()
    subparsers = parser._subparsers._group_actions[0]  # type: ignore[union-attr]
    for command in ("export-signboard", "signboard-validate"):
        assert command in subparsers.choices
        # The command listing and the command's own --help both say it.
        assert "[LEGACY]" in top_level_help
        assert "[LEGACY]" in subparsers.choices[command].format_help()


def _write_stale_card(board: Path, template: Path, *, task_id: str, notes: str | None) -> Path:
    """Copy a generated card under a task id that is absent from the store.

    This is what the real board accumulates: cards whose dispatcher task no
    longer exists, which the exporter's own ``{task_id}--*.md`` cleanup can
    never reach because it only iterates task ids still in the store.
    """
    text = template.read_text(encoding="utf-8")
    original_id = next(
        line.split('"')[1] for line in text.splitlines() if line.startswith("id: ")
    )
    text = text.replace(original_id, task_id)
    if notes is not None:
        text = text.replace("## Notes\n\n## Receipts", f"## Notes\n\n{notes}\n\n## Receipts")
    card = template.parent / f"{task_id}--stale-card.md"
    card.write_text(text, encoding="utf-8")
    return card


def test_export_prunes_cards_absent_from_store_preserving_notes(
    tmp_env, store, tmp_path: Path
) -> None:
    """Cards whose task id vanished from dispatcher become removable.

    A note-free stale card is deleted; a stale card carrying human-authored
    "## Notes" content is kept and surfaced instead of being destroyed.
    """
    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)

    live_card = next(board.glob(f"**/{ready.task_id}--*.md"))
    plain = _write_stale_card(board, live_card, task_id="task-gone-plain", notes=None)
    note_text = "Keep this: the owner still owes a decision here."
    noted = _write_stale_card(board, live_card, task_id="task-gone-noted", notes=note_text)
    human_file = board / "Ready" / "human-authored.md"
    human_file.write_text("# Not a generated card\n", encoding="utf-8")

    stale = validate_signboard(store, board)
    assert {finding["kind"] for finding in stale["findings"]} == {"stale_card"}
    assert "--prune-absent" in stale["repair"]

    result = export_signboard(store, board, prune_absent=True)

    assert not plain.exists()
    assert result["pruned"] == [str(plain)]
    assert noted.exists()
    assert note_text in noted.read_text(encoding="utf-8")
    assert result["retained_with_notes"] == [str(noted)]
    assert live_card.exists()
    assert human_file.read_text(encoding="utf-8") == "# Not a generated card\n"

    remaining = validate_signboard(store, board)
    assert [
        finding["path"] for finding in remaining["findings"] if finding["kind"] == "stale_card"
    ] == [str(noted.relative_to(board))]


def test_export_without_prune_leaves_absent_cards_alone(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    stale = _write_stale_card(
        board, next(board.glob(f"**/{ready.task_id}--*.md")), task_id="task-gone", notes=None
    )

    result = export_signboard(store, board)

    assert stale.exists()
    assert result["pruned"] == []
    assert result["retained_with_notes"] == []


def test_cli_export_signboard_prune_absent_flag(tmp_env, store, tmp_path: Path) -> None:
    from app.dispatcher.cli import main

    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    assert main(["export-signboard", str(board), "--json"]) == 0
    stale = _write_stale_card(
        board, next(board.glob(f"**/{ready.task_id}--*.md")), task_id="task-gone", notes=None
    )

    assert main(["export-signboard", str(board), "--prune-absent", "--json"]) == 0

    assert not stale.exists()


def test_prune_retains_a_stale_card_carrying_human_receipts(
    tmp_env, store, tmp_path: Path
) -> None:
    """The other hand-editable section is human material too.

    ``_render_task`` always leaves "## Receipts" empty, and re-export never
    reaches a stale card, so text below that heading is something a human put
    there and nothing else would have removed. The prune must not be what
    deletes it.
    """
    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    stale = _write_stale_card(
        board, next(board.glob(f"**/{ready.task_id}--*.md")), task_id="task-gone", notes=None
    )
    stale.write_text(
        stale.read_text(encoding="utf-8").rstrip("\n")
        + "\n- merged in PR #123 after the owner signed off\n",
        encoding="utf-8",
    )

    result = export_signboard(store, board, prune_absent=True)

    assert stale.exists()
    assert result["retained_with_notes"] == [str(stale)]
    assert result["pruned"] == []
    assert "merged in PR #123" in stale.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #4370: a board records the dispatcher store that owns it
#
# The store resolves from the current working directory
# (``app/dispatcher/config.py :: load_paths`` -> ``_default_state_dir`` ->
# ``discover_primary_worktree``), so two checkouts on one host have two
# independent stores. On 2026-07-29 ``--prune-absent`` was run from the checkout
# that did *not* own the board; every card looked absent and 404 live cards were
# deleted. These tests fix the missing fact: which store owns the board.
# ---------------------------------------------------------------------------


def _independent_store(state_dir: Path) -> SqliteStore:
    """A second dispatcher store — exactly like a second checkout on one host.

    It shares no tasks and no identity with the ``store`` fixture, so every card
    on the other store's board looks absent to it.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    other = SqliteStore(
        db_path=state_dir / "dispatcher.sqlite3",
        event_writer=JsonlEventWriter(state_dir / "events.jsonl"),
    )
    other.initialize()
    return other


def test_export_writes_store_identity_stamp(tmp_env, store, tmp_path: Path) -> None:
    seed_tasks(store)
    board = tmp_path / "board"

    result = export_signboard(store, board)

    stamp = board / STORE_STAMP_FILENAME
    assert stamp.is_file()
    data = json.loads(stamp.read_text(encoding="utf-8"))
    assert data["store_id"] == read_store_identity(store)
    assert data["store_id"]
    assert result["store_id"] == data["store_id"]
    # The stamp lives outside the card namespace: not a ".md" file, and at the
    # board root rather than inside a column, so no board consumer renders it.
    assert stamp.suffix != ".md"
    assert stamp.parent == board


def test_prune_refuses_when_store_stamp_mismatches(tmp_env, store, tmp_path: Path) -> None:
    seed_tasks(store)
    board = tmp_path / "board"
    export_signboard(store, board)
    foreign = _independent_store(tmp_path / "other-checkout")

    with pytest.raises(SignboardStoreOwnershipError) as excinfo:
        export_signboard(foreign, board, prune_absent=True)

    assert "stamped by dispatcher store" in str(excinfo.value)


def test_prune_mismatch_leaves_every_card_intact(tmp_env, store, tmp_path: Path) -> None:
    """The 2026-07-29 incident in miniature: the refusal must be total.

    The foreign store knows none of this board's tasks, so without the guard
    every card is a prune candidate — and the export loop that runs *before*
    the prune already unlinks generated cards of its own accord. Nothing on the
    board may change.
    """
    seed_tasks(store)
    board = tmp_path / "board"
    export_signboard(store, board)
    before = {path: path.read_bytes() for path in sorted(board.rglob("*.md"))}
    assert before

    foreign = _independent_store(tmp_path / "other-checkout")
    with pytest.raises(SignboardStoreOwnershipError):
        export_signboard(foreign, board, prune_absent=True)

    after = {path: path.read_bytes() for path in sorted(board.rglob("*.md"))}
    assert after == before


def test_validate_reports_foreign_store_distinctly(tmp_env, store, tmp_path: Path) -> None:
    seed_tasks(store)
    board = tmp_path / "board"
    export_signboard(store, board)
    foreign = _independent_store(tmp_path / "other-checkout")

    result = validate_signboard(foreign, board)

    kinds = [finding["kind"] for finding in result["findings"]]
    assert "store_stamp_mismatch" in kinds
    # Distinct from stale_card, and named before the cards it explains.
    assert kinds[0] == "store_stamp_mismatch"
    assert kinds.count("store_stamp_mismatch") == 1
    assert "stale_card" in kinds
    # The read-only surface must not point the operator at the loaded gun.
    assert "--prune-absent" not in result["repair"]


def test_prune_unchanged_when_stamp_matches(tmp_env, store, tmp_path: Path) -> None:
    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    live_card = next(board.glob(f"**/{ready.task_id}--*.md"))
    plain = _write_stale_card(board, live_card, task_id="task-gone-plain", notes=None)
    noted = _write_stale_card(board, live_card, task_id="task-gone-noted", notes="Owner decision pending.")

    result = export_signboard(store, board, prune_absent=True)

    assert not plain.exists()
    assert result["pruned"] == [str(plain)]
    assert noted.exists()
    assert result["retained_with_notes"] == [str(noted)]
    assert live_card.exists()


def test_stamp_is_identity_not_path(tmp_env, store, tmp_path: Path) -> None:
    """A legitimate relocation of the store must not read as a foreign store."""
    tasks = seed_tasks(store)
    ready = next(task for task in tasks if task.status == "ready")
    board = tmp_path / "board"
    export_signboard(store, board)
    stale = _write_stale_card(
        board, next(board.glob(f"**/{ready.task_id}--*.md")), task_id="task-gone", notes=None
    )
    stamped_id = json.loads((board / STORE_STAMP_FILENAME).read_text(encoding="utf-8"))["store_id"]

    relocated_dir = tmp_path / "relocated-dispatcher"
    shutil.move(str(Path(tmp_env["DISPATCHER_STATE_DIR"])), str(relocated_dir))
    relocated = SqliteStore(
        db_path=relocated_dir / "dispatcher.sqlite3",
        event_writer=JsonlEventWriter(relocated_dir / "events.jsonl"),
    )

    result = export_signboard(relocated, board, prune_absent=True)

    assert read_store_identity(relocated) == stamped_id
    assert not stale.exists()
    assert result["pruned"] == [str(stale)]


def test_prune_refuses_on_unstamped_board_that_holds_cards(
    tmp_env, store, tmp_path: Path
) -> None:
    """Every board that exists today is unstamped; none may be silently adopted."""
    seed_tasks(store)
    board = tmp_path / "board"
    export_signboard(store, board)
    (board / STORE_STAMP_FILENAME).unlink()
    before = {path: path.read_bytes() for path in sorted(board.rglob("*.md"))}

    with pytest.raises(SignboardStoreOwnershipError) as excinfo:
        export_signboard(store, board, prune_absent=True)

    assert "no store-identity stamp" in str(excinfo.value)
    assert {path: path.read_bytes() for path in sorted(board.rglob("*.md"))} == before


def test_prune_on_a_board_with_nothing_to_lose_still_works(
    tmp_env, store, tmp_path: Path
) -> None:
    """A fresh board holds no cards, so a first export may prune in one command."""
    seed_tasks(store)
    board = tmp_path / "board"

    result = export_signboard(store, board, prune_absent=True)

    assert result["pruned"] == []
    assert (board / STORE_STAMP_FILENAME).is_file()
    assert any(board.rglob("*.md"))


def test_export_does_not_restamp_a_board_owned_by_another_store(
    tmp_env, store, tmp_path: Path
) -> None:
    """A plain export must not be the way the guard gets defeated."""
    seed_tasks(store)
    board = tmp_path / "board"
    export_signboard(store, board)
    owner_id = json.loads((board / STORE_STAMP_FILENAME).read_text(encoding="utf-8"))["store_id"]
    foreign = _independent_store(tmp_path / "other-checkout")

    export_signboard(foreign, board)

    still = json.loads((board / STORE_STAMP_FILENAME).read_text(encoding="utf-8"))["store_id"]
    assert still == owner_id
    with pytest.raises(SignboardStoreOwnershipError):
        export_signboard(foreign, board, prune_absent=True)


def test_cli_export_signboard_prune_exits_nonzero_on_foreign_board(
    tmp_env, store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.dispatcher.cli import main

    seed_tasks(store)
    board = tmp_path / "board"
    assert main(["export-signboard", str(board), "--json"]) == 0
    before = {path: path.read_bytes() for path in sorted(board.rglob("*.md"))}

    other_dir = tmp_path / "other-checkout"
    _independent_store(other_dir)
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(other_dir))
    monkeypatch.setenv("DISPATCHER_DB_PATH", str(other_dir / "dispatcher.sqlite3"))
    monkeypatch.setenv("DISPATCHER_EVENTS_PATH", str(other_dir / "events.jsonl"))

    assert main(["export-signboard", str(board), "--prune-absent", "--json"]) == 1
    assert {path: path.read_bytes() for path in sorted(board.rglob("*.md"))} == before


def test_render_task_shows_labels_and_url_from_synced_record() -> None:
    """A record produced by the sync path renders label chips and the GitHub
    link without hand-seeded sync_state (#4441)."""
    from app.dispatcher.signboard import _render_task
    from app.dispatcher.sync_github import normalize_github_issue

    payload = {
        "number": 4441,
        "title": "Synced card",
        "labels": [{"name": "type:task"}, {"name": "prio:med"}],
        "url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/4441",
        "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4441",
        "created_at": "2026-07-31T10:00:00Z",
        "updated_at": "2026-07-31T10:00:00Z",
    }
    task = normalize_github_issue(payload, "RasmusTho/agentic-pkm-mvp")

    card = _render_task(task)

    assert 'labels: ["type:task", "prio:med"]' in card
    assert 'github_url: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4441"' in card
    assert "- GitHub: https://github.com/RasmusTho/agentic-pkm-mvp/issues/4441" in card


def test_render_task_tolerates_sync_state_without_labels_or_url() -> None:
    """Pre-#4441 rows without the new keys keep rendering unchanged."""
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.signboard import _render_task

    task = TaskRecord(
        task_id="github-RasmusTho--agentic-pkm-mvp-issue-99",
        issue_number=99,
        title="Legacy row",
        status="ready",
        priority="med",
        source_anchor_refs=["github:issue:99"],
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        sync_state={"last_pull_at": "2026-07-01T00:00:00+00:00"},
    )

    card = _render_task(task)

    assert 'github_url: ""' in card
    assert "labels: []" in card
    assert "- GitHub:" not in card
