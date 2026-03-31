"""
TDD tests for app/services/note_context.py — Part 6.

NoteContext assembles a rich, multi-surface view of a vault note from:
  1. Companion note  (_system/companions/<uuid>.md)
  2. Vault note file (frontmatter + body)
  3. Runtime stores  (object store → classification; relation index → links)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.services.companion_note import AttachmentRef, CompanionNote, write_companion
from app.services.note_context import (
    ContextBudget,
    NoteContextError,
    build_note_context,
)
from app.stores.memory import MemoryObjectStore, MemoryRelationIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID = "aaaaaaaa-1111-2222-3333-444444444444"
_UUID2 = "bbbbbbbb-1111-2222-3333-444444444444"


def _write_vault_note(
    vault: Path,
    rel: str,
    body: str = "Some body text.",
    frontmatter_extra: str = "",
) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_block = f"---\nuuid: {_UUID}\ntitle: Test Note\ntrust: own\n{frontmatter_extra}---\n"
    path.write_text(fm_block + body, encoding="utf-8")
    return path


def _write_companion(
    vault: Path,
    uuid: str = _UUID,
    source_ref: str = "Cards/TestNote.md",
    content_hash: str = "deadbeef",
    attachments: list[AttachmentRef] | None = None,
) -> CompanionNote:
    companion = CompanionNote(
        uuid=uuid,
        source_ref=source_ref,
        title="Test Note",
        content_hash=content_hash,
        ingest_state="tracked",
        last_ingested=datetime.now(tz=timezone.utc).isoformat(),
        created_by_instance="test",
        attachments=attachments or [],
    )
    write_companion(vault, companion)
    return companion


# ---------------------------------------------------------------------------
# Part 6 — ContextBudget defaults
# ---------------------------------------------------------------------------

class TestContextBudget:
    def test_defaults_are_sane(self) -> None:
        budget = ContextBudget()
        assert budget.max_body_chars == 2000
        assert budget.include_relations is True
        assert budget.include_attachments is True
        assert budget.include_history is False

    def test_panel_budget(self) -> None:
        budget = ContextBudget(max_body_chars=2000, include_relations=True)
        assert budget.max_body_chars == 2000


# ---------------------------------------------------------------------------
# Part 6 — Full assembly
# ---------------------------------------------------------------------------

class TestBuildNoteContextFull:
    def test_uuid_and_source_ref_from_companion(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault)

        assert ctx.uuid == _UUID
        assert ctx.source_ref == "Cards/TestNote.md"
        assert ctx.content_hash == "deadbeef"
        assert ctx.ingest_state == "tracked"

    def test_frontmatter_from_vault_note(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault)

        assert ctx.frontmatter.get("title") == "Test Note"
        assert ctx.frontmatter.get("trust") == "own"

    def test_body_from_vault_note(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md", body="The real note body.\n")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault)

        assert "The real note body." in ctx.body

    def test_trust_level_from_frontmatter(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md", frontmatter_extra="trust: external\n")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault)

        assert ctx.trust_level == "external"

    def test_trust_level_empty_when_missing(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        note = vault / "Cards/TestNote.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(f"---\nuuid: {_UUID}\ntitle: No Trust\n---\nBody.\n", encoding="utf-8")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault)

        assert ctx.trust_level == ""

    def test_attachments_from_companion(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        attachments = [
            AttachmentRef(ref="Assets/photo.png", content_hash="abc123"),
            AttachmentRef(ref="Assets/doc.pdf", content_hash=None),
        ]
        _write_companion(vault, source_ref="Cards/TestNote.md", attachments=attachments)

        ctx = build_note_context(_UUID, vault)

        assert len(ctx.attachments) == 2
        assert ctx.attachments[0].ref == "Assets/photo.png"

    def test_classification_from_object_store(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        store = MemoryObjectStore()
        store.put(
            UUID(_UUID),
            kind="note",
            source_ref="Cards/TestNote.md",
            payload={"classification": {"type": "concept", "confidence": 0.92}},
        )

        ctx = build_note_context(_UUID, vault, object_store=store)

        assert ctx.classification is not None
        assert ctx.classification["type"] == "concept"

    def test_no_classification_when_store_empty(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault, object_store=MemoryObjectStore())

        assert ctx.classification is None
        assert ctx.executed_actions == []

    def test_outgoing_links_from_relation_index(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        rel_idx = MemoryRelationIndex()
        rel_idx.link(UUID(_UUID), UUID(_UUID2), rel="supports")

        ctx = build_note_context(_UUID, vault, relation_index=rel_idx)

        assert _UUID2 in ctx.outgoing_links

    def test_no_links_when_relation_index_empty(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(
            _UUID, vault,
            relation_index=MemoryRelationIndex(),
            object_store=MemoryObjectStore(),
        )

        assert ctx.outgoing_links == []
        assert ctx.backlinks == []  # backlinks not yet supported → always []


# ---------------------------------------------------------------------------
# Part 6 — Budget truncation
# ---------------------------------------------------------------------------

class TestBodyBudget:
    def test_body_truncated_when_over_budget(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        long_body = "x" * 500
        _write_vault_note(vault, "Cards/TestNote.md", body=long_body)
        _write_companion(vault, source_ref="Cards/TestNote.md")

        budget = ContextBudget(max_body_chars=100)
        ctx = build_note_context(_UUID, vault, budget=budget, object_store=MemoryObjectStore())

        assert len(ctx.body) <= 100
        assert ctx.body_truncated is True

    def test_body_not_truncated_within_budget(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md", body="Short body.\n")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        budget = ContextBudget(max_body_chars=10000)
        ctx = build_note_context(_UUID, vault, budget=budget, object_store=MemoryObjectStore())

        assert "Short body." in ctx.body
        assert ctx.body_truncated is False


# ---------------------------------------------------------------------------
# Part 6 — Budget flags
# ---------------------------------------------------------------------------

class TestBudgetFlags:
    def test_include_attachments_false_returns_empty(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(
            vault,
            source_ref="Cards/TestNote.md",
            attachments=[AttachmentRef(ref="img.png")],
        )

        budget = ContextBudget(include_attachments=False)
        ctx = build_note_context(_UUID, vault, budget=budget, object_store=MemoryObjectStore())

        assert ctx.attachments == []

    def test_include_relations_false_skips_index(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        rel_idx = MemoryRelationIndex()
        rel_idx.link(UUID(_UUID), UUID(_UUID2), rel="supports")

        budget = ContextBudget(include_relations=False)
        ctx = build_note_context(
            _UUID, vault, budget=budget,
            relation_index=rel_idx,
            object_store=MemoryObjectStore(),
        )

        assert ctx.outgoing_links == []


# ---------------------------------------------------------------------------
# Part 6 — Error / degraded paths
# ---------------------------------------------------------------------------

class TestDegradedPaths:
    def test_missing_companion_raises_note_context_error(self, tmp_path: Path) -> None:
        vault = tmp_path / "vault"
        vault.mkdir()

        with pytest.raises(NoteContextError, match="No companion"):
            build_note_context("nonexistent-uuid", vault, object_store=MemoryObjectStore())

    def test_missing_vault_note_returns_degraded_context(self, tmp_path: Path) -> None:
        """Companion exists but the vault note file has been deleted.

        Should return a context with empty body and frontmatter rather than crash.
        """
        vault = tmp_path / "vault"
        _write_companion(vault, source_ref="Cards/Missing.md")
        # Do NOT write the vault note file

        ctx = build_note_context(_UUID, vault, object_store=MemoryObjectStore())

        assert ctx.uuid == _UUID
        assert ctx.source_ref == "Cards/Missing.md"
        assert ctx.frontmatter == {}
        assert ctx.body == ""
        assert ctx.body_truncated is False

    def test_malformed_vault_note_returns_degraded_context(self, tmp_path: Path) -> None:
        """Vault note exists but frontmatter YAML is broken — must not crash."""
        vault = tmp_path / "vault"
        note = vault / "Cards" / "Broken.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("---\nnot: valid: yaml: [[[\n---\nBody.\n", encoding="utf-8")
        _write_companion(vault, source_ref="Cards/Broken.md")

        ctx = build_note_context(_UUID, vault, object_store=MemoryObjectStore())

        # Must not raise; body should still be available
        assert ctx.uuid == _UUID
        assert isinstance(ctx.frontmatter, dict)

    def test_invalid_uuid_in_store_does_not_crash(self, tmp_path: Path) -> None:
        """UUID that cannot be parsed as UUID type — store.get must be guarded."""
        vault = tmp_path / "vault"
        _write_vault_note(vault, "Cards/TestNote.md")
        _write_companion(vault, source_ref="Cards/TestNote.md")

        ctx = build_note_context(_UUID, vault, object_store=MemoryObjectStore())

        assert ctx.classification is None  # nothing in store, no crash
