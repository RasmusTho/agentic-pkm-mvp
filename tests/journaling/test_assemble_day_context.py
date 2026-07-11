from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.domain.commitments import CommitmentRecord
from app.journaling.day_context import assemble_day_context
from app.receipts.decision_receipt_log import append_decision_receipt
from app.services.commitment_persistence import commitment_artifact_path, persist_commitment
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

DAY = date(2026, 7, 9)


@pytest.fixture
def vault(tmp_path: Path) -> tuple[Path, VaultContext]:
    root = tmp_path / "vault"
    root.mkdir()
    return root, VaultContext(status="selected", active_vault_path=str(root))


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _set_changed_today(root: Path, relative_path: str) -> None:
    when = datetime(2026, 7, 9, 12, tzinfo=timezone.utc).timestamp()
    os.utime(root / relative_path, (when, when))


def _seed_all(root: Path, context: VaultContext) -> None:
    record = CommitmentRecord("commitment-1", "next_action", "done", summary="Finished")
    persist_commitment(record, vault_context=context, write_guard=_allowing_guard())
    _set_changed_today(root, commitment_artifact_path(record.commitment_id, root))
    append_decision_receipt(
        object_id="object-1",
        key="review",
        value={},
        trace_id="trace-1",
        created_at=datetime(2026, 7, 9, 10, tzinfo=timezone.utc),
        vault_root=root,
        vault_uuid="uuid-1",
    )
    sources = root / "sources"
    sources.mkdir()
    (sources / "capture-one.md").write_text(
        """---
artifact_class: youtube_source_note
created: 2026-07-09T09:00:00Z
provenance:
  content_identity: sha256:capture-1
  source_kind: youtube
  url: https://example.test/capture-1
---
Capture one
""",
        encoding="utf-8",
    )


def test_assembles_full_context_with_provenance(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    _seed_all(root, context)

    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    assert bundle.degraded_sources == ()
    assert all(bundle.sections[name].items for name in bundle.sections)
    assert all(item.provenance_ref for section in bundle.sections.values() for item in section.items)
    assert bundle.authority.may_write is False


def test_partial_source_failure_names_missing_source(
    vault: tuple[Path, VaultContext], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.journaling import day_context

    root, context = vault
    _seed_all(root, context)
    monkeypatch.setattr(day_context, "iter_decision_receipts", lambda *_: (_ for _ in ()).throw(RuntimeError()))

    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    assert bundle.degraded_sources == ("decision_receipts",)
    assert bundle.sections["decision_receipts"].note == "decision_receipts could not be read"


def test_commitments_filtered_to_todays_changes(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    today = CommitmentRecord("today", "next_action", "done")
    old = CommitmentRecord("old", "next_action", "next")
    for record in (today, old):
        persist_commitment(record, vault_context=context, write_guard=_allowing_guard())
    _set_changed_today(root, commitment_artifact_path(today.commitment_id, root))
    old_path = root / commitment_artifact_path(old.commitment_id, root)
    yesterday = datetime(2026, 7, 8, 12, tzinfo=timezone.utc).timestamp()
    os.utime(old_path, (yesterday, yesterday))

    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    assert [item.content["commitment_id"] for item in bundle.sections["commitments"].items] == ["today"]


def test_bundle_carries_no_write_authority(vault: tuple[Path, VaultContext]) -> None:
    _root, context = vault

    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    assert bundle.may_write is False
    assert bundle.authority.may_write is False


def test_assembly_is_deterministic_for_same_inputs_same_day(vault: tuple[Path, VaultContext]) -> None:
    root, context = vault
    _seed_all(root, context)

    first = assemble_day_context(vault_context=context, for_date=DAY)
    second = assemble_day_context(vault_context=context, for_date=DAY)

    assert first.model_dump() == second.model_dump()
