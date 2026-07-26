from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import logging
from pathlib import Path

from app.knowledge.multiwriter import conflict_artifact_path
from app.vault import manager
from app.vault.manager import iter_vault_markdown_files


def _write_markdown(path: Path, body: str = "Body.\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _iter_relative(vault_root: Path) -> set[str]:
    return {
        path.relative_to(vault_root).as_posix()
        for path in iter_vault_markdown_files(vault_root)
    }


def test_conflicted_copy_is_not_yielded_as_ordinary_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write_markdown(vault_root / "Notes" / "Plan (conflicted copy fixture-device).md")

    assert _iter_relative(vault_root) == set()


def test_staged_conflict_artifact_is_not_yielded_as_ordinary_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    staged_relative = conflict_artifact_path(
        "Notes/Plan.md",
        writer_identity="synthetic-writer",
        written_at=datetime(2026, 7, 26, 14, 2, tzinfo=UTC),
    )
    _write_markdown(vault_root / Path(staged_relative))

    assert _iter_relative(vault_root) == set()


def test_quarantine_preserves_normal_sibling_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write_markdown(vault_root / "Notes" / "Plan.md")
    _write_markdown(vault_root / "Notes" / "Plan (conflicted copy fixture-device).md")
    _write_markdown(vault_root / "Notes" / "Unrelated.md")

    assert _iter_relative(vault_root) == {
        "Notes/Plan.md",
        "Notes/Unrelated.md",
    }


def test_quarantine_does_not_delete_conflict_artifact(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    receipt_policy = manager._ConflictQuarantineReceiptPolicy()
    monkeypatch.setattr(manager, "_conflict_quarantine_receipts", receipt_policy)
    vault_root = tmp_path / "vault"
    conflict = _write_markdown(
        vault_root / "Notes" / "Plan (conflicted copy fixture-device).md",
        "Competing content must survive.\n",
    )

    with caplog.at_level(logging.WARNING, logger="app.vault.manager"):
        assert _iter_relative(vault_root) == set()
        assert _iter_relative(vault_root) == set()

    assert conflict.read_text(encoding="utf-8") == "Competing content must survive.\n"
    receipts = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "vault.markdown.quarantined"
    ]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.classification == "multiwriter_conflict_artifact"
    assert receipt.artifact_path == str(conflict)
    assert receipt.action == "excluded_from_iteration_preserved_on_disk"

    # Capacity + 1 remains bounded across repeated scans: tracked keys are
    # non-evicting and receipt output has an independent hard ceiling.
    caplog.clear()
    bounded_policy = manager._ConflictQuarantineReceiptPolicy(
        max_tracked_states=4,
        max_detail_receipts=2,
    )
    distinct_states = [
        (f"/vault/conflict-{index}.md", (1, index, 10, 20, 30))
        for index in range(5)
    ]
    with caplog.at_level(logging.WARNING, logger="app.vault.manager"):
        for _ in range(2):
            for artifact_path, state in distinct_states:
                bounded_policy.observe(artifact_path, state)
    assert [
        getattr(record, "receipt_kind", None) for record in caplog.records
    ] == ["detail", "detail", "suppression_summary"]

    # The policy lock gives one writer ownership of a concurrent first
    # observation, so identical events cannot race into duplicate receipts.
    caplog.clear()
    concurrent_policy = manager._ConflictQuarantineReceiptPolicy()
    same_state: manager.ConflictArtifactState = (1, 2, 3, 4, 5)
    with caplog.at_level(logging.WARNING, logger="app.vault.manager"):
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(
                executor.map(
                    lambda _: concurrent_policy.observe(
                        "/vault/concurrent-conflict.md",
                        same_state,
                    ),
                    range(32),
                )
            )
    assert len(caplog.records) == 1

    # Inode/ctime-bearing identity treats a recreated or changed artifact as a
    # new state. Restart intentionally resets process-local observation state
    # and permits one fresh, still-bounded detail receipt.
    caplog.clear()
    changed_policy = manager._ConflictQuarantineReceiptPolicy()
    initial_state: manager.ConflictArtifactState = (1, 2, 3, 4, 5)
    recreated_state: manager.ConflictArtifactState = (1, 9, 3, 4, 8)
    with caplog.at_level(logging.WARNING, logger="app.vault.manager"):
        changed_policy.observe("/vault/recreated-conflict.md", initial_state)
        changed_policy.observe("/vault/recreated-conflict.md", initial_state)
        changed_policy.observe("/vault/recreated-conflict.md", recreated_state)
        restarted_policy = manager._ConflictQuarantineReceiptPolicy()
        restarted_policy.observe("/vault/recreated-conflict.md", recreated_state)
    assert [
        getattr(record, "receipt_kind", None) for record in caplog.records
    ] == ["detail", "detail", "detail"]
