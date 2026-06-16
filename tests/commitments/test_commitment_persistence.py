"""Durable vault-backed commitment persistence — slice 1 of Commitment Surfacing.

Governing issue: #2073 (parent #1960).
Spec: docs/COMMITMENT_SURFACING/PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md
Contracts:
- docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Relation to artifacts
- docs/CONCEPTS/STATE_AXES_CONTRACT.md (commitment state must NOT collapse into review_state/maturity)

These tests pin the durable foundation the surfacing slices depend on:
1. CommitmentRecords persist as own-artefacts in the companion-note family and survive a
   simulated process restart with full shape + state intact.
2. The persistence write path asserts the WriteGuard at its production call site; a
   write-blocked runtime state raises WritesBlockedError and leaves no artefact on disk.
3. The query path returns persisted records and feeds query_next_and_waiting_commitments
   without collapsing commitment state into note review_state/maturity axes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.commitments import (
    CommitmentRecord,
    query_next_and_waiting_commitments,
)
from app.services import commitment_persistence as cp_module
from app.services.commitment_persistence import (
    commitment_artifact_path,
    load_commitments,
    persist_commitment,
)
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-default",
        active_vault_name="Vault Default",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _record(commitment_id: str = "c-001", state: str = "next") -> CommitmentRecord:
    return CommitmentRecord(
        commitment_id=commitment_id,
        commitment_kind="next_action",
        state=state,  # type: ignore[arg-type]
        target_ref="projects/hiring.md",
        summary="Reply to Alice about the offer",
        source_goal="close the hiring loop",
    )


def test_commitment_survives_restart(tmp_path: Path) -> None:
    """Full-shape persistence as a vault artefact, re-readable after a restart.

    Also asserts the pinned artefact shape: an own-artefact under the system-owned
    commitments/ folder (companion-note family), not a section in a host note.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    ctx = _vault(vault_root)
    record = _record()

    persist_commitment(record, vault_context=ctx, write_guard=_allowing_guard())

    # Pinned artefact shape: own-artefact at vault/<system_dir>/commitments/<id>.md.
    rel = commitment_artifact_path(record.commitment_id, vault_root)
    artefact = vault_root / rel
    assert artefact.exists()
    assert artefact.parent.name == "commitments"

    # The persisted artefact must NOT collapse commitment state into note axes.
    fm, _body = load_frontmatter(artefact.read_text(encoding="utf-8"))
    assert "review_state" not in fm
    assert "maturity" not in fm
    assert fm.get("commitment_state") == "next"

    # Simulate a process restart: fresh load from disk with no in-memory state.
    loaded = load_commitments(vault_context=ctx)
    by_id = {r.commitment_id: r for r in loaded}
    assert "c-001" in by_id
    restored = by_id["c-001"]

    # Full CommitmentRecord shape survives intact.
    assert restored.commitment_id == "c-001"
    assert restored.commitment_kind == "next_action"
    assert restored.state == "next"
    assert restored.target_ref == "projects/hiring.md"
    assert restored.summary == "Reply to Alice about the offer"
    assert restored.source_goal == "close the hiring loop"


def test_persist_blocked_by_writeguard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WriteGuard is asserted at the production call site; blocked => raise + no artefact.

    Patches the runtime health state behind the production DEFAULT_WRITE_GUARD (not a
    guard injected only by the test) so enforcement is proven at the real call site.
    persist_commitment must raise WritesBlockedError and leave nothing on disk
    (atomic-or-absent).
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    ctx = _vault(vault_root)
    record = _record()

    # Drive the production default guard into a write-blocked runtime state.
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "maintenance"},
    )

    with pytest.raises(WritesBlockedError):
        persist_commitment(record, vault_context=ctx)

    # Atomic-or-absent: no artefact (and no stray temp file) left behind.
    rel = commitment_artifact_path(record.commitment_id, vault_root)
    assert not (vault_root / rel).exists()
    commitments_dir = (vault_root / rel).parent
    leftovers = list(commitments_dir.glob("*")) if commitments_dir.exists() else []
    assert leftovers == []

    # Nothing is loadable after a blocked write.
    assert load_commitments(vault_context=ctx) == []


def test_load_feeds_next_and_waiting_query(tmp_path: Path) -> None:
    """Loaded records feed query_next_and_waiting_commitments with commitment-typed state.

    States stay in the CommitmentState vocabulary end-to-end; they are never read back
    out of note review_state/maturity axes.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    ctx = _vault(vault_root)
    guard = _allowing_guard()

    persist_commitment(_record("c-001", "next"), vault_context=ctx, write_guard=guard)
    persist_commitment(_record("c-002", "waiting"), vault_context=ctx, write_guard=guard)
    persist_commitment(_record("c-003", "done"), vault_context=ctx, write_guard=guard)

    records = load_commitments(vault_context=ctx)
    assert {r.commitment_id for r in records} == {"c-001", "c-002", "c-003"}

    # Loaded records are CommitmentRecords with commitment-family state values.
    assert all(isinstance(r, CommitmentRecord) for r in records)

    result = query_next_and_waiting_commitments(records)
    assert [r.commitment_id for r in result.next_items] == ["c-001"]
    assert [r.commitment_id for r in result.waiting_items] == ["c-002"]
    assert result.operator_summary["next_count"] == 1
    assert result.operator_summary["waiting_count"] == 1


def test_persist_writes_full_shape_via_default_guard(tmp_path: Path) -> None:
    """Production default-guard path persists a complete artefact when writes are allowed."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    ctx = _vault(vault_root)

    # No injected guard: exercise the production DEFAULT_WRITE_GUARD call site directly
    # (default runtime state is non-blocking under test).
    assert cp_module.DEFAULT_WRITE_GUARD is DEFAULT_WRITE_GUARD
    persist_commitment(_record("c-042", "open"), vault_context=ctx)

    loaded = {r.commitment_id: r for r in load_commitments(vault_context=ctx)}
    assert loaded["c-042"].state == "open"
    assert loaded["c-042"].commitment_kind == "next_action"
