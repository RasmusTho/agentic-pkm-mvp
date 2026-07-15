from __future__ import annotations

import inspect
from pathlib import Path
from uuid import UUID

import pytest

from app.agent_memory.candidate import MemoryType
from app.agent_memory.provisional_memory import (
    ProvisionalMarkdownArtifact,
    ProvisionalReconciliationState,
    ProvisionalSensitivity,
    rebuild_provisional_memory,
)
from app.agent_memory import provisional_write as provisional_write_module
from app.agent_memory.provisional_write import (
    load_provisional_markdown,
    render_provisional_markdown,
)


def test_write_endpoint_cannot_promote_or_authorize_apply() -> None:
    source = inspect.getsource(provisional_write_module)
    assert "materialize_promoted_memory" not in source
    assert "mark_terminal" not in source
    assert "promotion_state" not in source

    record_source = inspect.getsource(
        provisional_write_module.write_provisional_memory
    )
    assert "assert_provisional_trust_tier" in record_source
    assert "write_note_relative" in record_source


def test_sync_is_not_an_execution_bus(tmp_path: Path) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="A file appearing is not a transition.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{memory_id}.md"
    path.parent.mkdir(parents=True)
    path.write_text(render_provisional_markdown(artifact), encoding="utf-8")

    loaded = load_provisional_markdown(path, vault_root=tmp_path)
    reconciliation = rebuild_provisional_memory(
        memory_id=memory_id,
        artifact_ref=artifact.artifact_ref,
        artifact=loaded,
        receipts=(),
    )

    assert reconciliation.state is ProvisionalReconciliationState.RETRYABLE_PARTIAL
    assert reconciliation.record is None
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_loader_rejects_filename_frontmatter_uuid_mismatch(tmp_path: Path) -> None:
    memory_id = UUID("12345678-1234-4abc-8def-1234567890ab")
    other_id = UUID("22345678-1234-4abc-8def-1234567890ab")
    artifact = ProvisionalMarkdownArtifact(
        memory_id=memory_id,
        artifact_ref=f"vault://Memory/Provisional/{memory_id}.md",
        scope_id="scope-personal",
        principal_id="principal-1",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        sensitivity=ProvisionalSensitivity.PRIVATE,
        content="A copied file cannot acquire another identity.",
        created_by="human://owner",
        created_at="2026-07-15T00:00:00Z",
        provenance_event_ids=("event-1",),
    )
    path = tmp_path / "Memory" / "Provisional" / f"{other_id}.md"
    path.parent.mkdir(parents=True)
    path.write_text(render_provisional_markdown(artifact), encoding="utf-8")

    with pytest.raises(ValueError, match="physical provisional Markdown path"):
        load_provisional_markdown(path, vault_root=tmp_path)
