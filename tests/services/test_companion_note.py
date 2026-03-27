"""
TDD tests for app/services/companion_note.py — Parts 2 and 3.

Part 2: core API (path, read, write, find_by_content_hash, scan_attachments)
Part 3: healing scenarios (rebuild_from_db, repair_companion, resolve_uuid_conflict,
        path-change, missing-companion-variants)
"""
from __future__ import annotations

import pytest
from pathlib import Path

from app.services.companion_note import (
    AttachmentRef,
    CompanionNote,
    ConflictLog,
    companion_path,
    find_companion_by_content_hash,
    read_companion,
    rebuild_companion_from_db,
    repair_companion,
    resolve_uuid_conflict,
    scan_attachments,
    write_companion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_companion(
    uuid: str = "aaaaaaaa-1111-2222-3333-444444444444",
    source_ref: str = "Cards/Concepts/MyNote.md",
    title: str = "My Note",
    content_hash: str = "abcdef1234567890",
    ingest_state: str = "tracked",
    last_ingested: str = "2026-03-27T10:00:00Z",
    created_by_instance: str = "test-instance",
    attachments: list[AttachmentRef] | None = None,
) -> CompanionNote:
    return CompanionNote(
        uuid=uuid,
        source_ref=source_ref,
        title=title,
        content_hash=content_hash,
        ingest_state=ingest_state,
        last_ingested=last_ingested,
        created_by_instance=created_by_instance,
        attachments=attachments or [],
    )


# ---------------------------------------------------------------------------
# Part 2 — companion_path
# ---------------------------------------------------------------------------

class TestCompanionPath:
    def test_is_flat_uuid_path(self) -> None:
        p = companion_path("abc-123")
        assert p == Path("_system/companions/abc-123.md")

    def test_no_subdirectories(self) -> None:
        p = companion_path("some-uuid")
        assert len(p.parts) == 3  # _system / companions / <uuid>.md

    def test_always_md_extension(self) -> None:
        assert companion_path("x").suffix == ".md"


# ---------------------------------------------------------------------------
# Part 2 — write_companion / read_companion roundtrip
# ---------------------------------------------------------------------------

class TestReadWriteRoundtrip:
    def test_basic_roundtrip(self, tmp_path: Path) -> None:
        companion = _make_companion()
        write_companion(tmp_path, companion)
        result = read_companion(tmp_path, companion.uuid)
        assert result is not None
        assert result.uuid == companion.uuid
        assert result.source_ref == companion.source_ref
        assert result.title == companion.title
        assert result.content_hash == companion.content_hash
        assert result.ingest_state == companion.ingest_state
        assert result.last_ingested == companion.last_ingested
        assert result.created_by_instance == companion.created_by_instance

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        companion = _make_companion()
        write_companion(tmp_path, companion)
        expected = tmp_path / "_system" / "companions" / f"{companion.uuid}.md"
        assert expected.exists()

    def test_roundtrip_with_attachments(self, tmp_path: Path) -> None:
        attachments = [
            AttachmentRef(ref="Assets/photo.png", content_hash="sha256hash1"),
            AttachmentRef(ref="Assets/doc.pdf", content_hash=None),
        ]
        companion = _make_companion(attachments=attachments)
        write_companion(tmp_path, companion)
        result = read_companion(tmp_path, companion.uuid)
        assert result is not None
        assert len(result.attachments) == 2
        assert result.attachments[0].ref == "Assets/photo.png"
        assert result.attachments[0].content_hash == "sha256hash1"
        assert result.attachments[1].ref == "Assets/doc.pdf"
        assert result.attachments[1].content_hash is None

    def test_overwrite_updates_fields(self, tmp_path: Path) -> None:
        companion = _make_companion(content_hash="oldhash")
        write_companion(tmp_path, companion)
        updated = _make_companion(content_hash="newhash")
        write_companion(tmp_path, updated)
        result = read_companion(tmp_path, companion.uuid)
        assert result is not None
        assert result.content_hash == "newhash"

    def test_written_file_has_no_forbidden_fields(self, tmp_path: Path) -> None:
        """review_state and maturity must never appear in a companion file."""
        companion = _make_companion()
        write_companion(tmp_path, companion)
        file_path = tmp_path / companion_path(companion.uuid)
        text = file_path.read_text(encoding="utf-8")
        assert "review_state" not in text
        assert "maturity" not in text
        assert "ingest_fingerprint" not in text


# ---------------------------------------------------------------------------
# Part 2 — read_companion missing / malformed
# ---------------------------------------------------------------------------

class TestReadCompanionEdgeCases:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = read_companion(tmp_path, "nonexistent-uuid")
        assert result is None

    def test_empty_companions_dir_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "_system" / "companions").mkdir(parents=True)
        result = read_companion(tmp_path, "any-uuid")
        assert result is None

    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "_system" / "companions" / "bad-uuid.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\nnot: valid: yaml: [[[:\n---\n", encoding="utf-8")
        # read_companion must not raise; returns None for unparseable files
        result = read_companion(tmp_path, "bad-uuid")
        assert result is None

    def test_missing_uuid_field_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "_system" / "companions" / "no-uuid.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\nsource_ref: some/path.md\n---\n", encoding="utf-8")
        result = read_companion(tmp_path, "no-uuid")
        assert result is None


# ---------------------------------------------------------------------------
# Part 2 — find_companion_by_content_hash
# ---------------------------------------------------------------------------

class TestFindByContentHash:
    def test_found(self, tmp_path: Path) -> None:
        companion = _make_companion(content_hash="deadbeef42")
        write_companion(tmp_path, companion)
        result = find_companion_by_content_hash(tmp_path, "deadbeef42")
        assert result is not None
        assert result.uuid == companion.uuid

    def test_not_found_returns_none(self, tmp_path: Path) -> None:
        result = find_companion_by_content_hash(tmp_path, "nosuchhash")
        assert result is None

    def test_not_found_when_dir_missing(self, tmp_path: Path) -> None:
        result = find_companion_by_content_hash(tmp_path, "anyhash")
        assert result is None

    def test_multiple_companions_returns_correct_one(self, tmp_path: Path) -> None:
        c1 = _make_companion(uuid="uuid-one", content_hash="hash-one")
        c2 = _make_companion(uuid="uuid-two", content_hash="hash-two")
        write_companion(tmp_path, c1)
        write_companion(tmp_path, c2)
        result = find_companion_by_content_hash(tmp_path, "hash-two")
        assert result is not None
        assert result.uuid == "uuid-two"

    def test_wrong_hash_returns_none(self, tmp_path: Path) -> None:
        companion = _make_companion(content_hash="correct-hash")
        write_companion(tmp_path, companion)
        result = find_companion_by_content_hash(tmp_path, "wrong-hash")
        assert result is None


# ---------------------------------------------------------------------------
# Part 2 — scan_attachments
# ---------------------------------------------------------------------------

class TestScanAttachments:
    def test_basic_image(self) -> None:
        refs = scan_attachments("![[photo.png]]")
        assert len(refs) == 1
        assert refs[0].ref == "photo.png"

    def test_with_caption(self) -> None:
        refs = scan_attachments("![[diagram.png|My Diagram]]")
        assert len(refs) == 1
        assert refs[0].ref == "diagram.png"

    def test_with_anchor(self) -> None:
        refs = scan_attachments("![[document.pdf#section-1]]")
        assert len(refs) == 1
        assert refs[0].ref == "document.pdf"

    def test_with_anchor_and_caption(self) -> None:
        refs = scan_attachments("![[file.png#top|alt text]]")
        assert len(refs) == 1
        assert refs[0].ref == "file.png"

    def test_wiki_link_not_matched(self) -> None:
        refs = scan_attachments("See [[MyNote]] for details")
        assert refs == []

    def test_wiki_link_with_alias_not_matched(self) -> None:
        refs = scan_attachments("See [[MyNote|alias]] for details")
        assert refs == []

    def test_mixed_content(self) -> None:
        text = "![[image.jpg]]\n[[InternalNote]]\n![[doc.pdf|caption]]"
        refs = scan_attachments(text)
        assert len(refs) == 2
        file_refs = {r.ref for r in refs}
        assert file_refs == {"image.jpg", "doc.pdf"}

    def test_filename_with_spaces(self) -> None:
        refs = scan_attachments("![[my image file.png]]")
        assert len(refs) == 1
        assert refs[0].ref == "my image file.png"

    def test_deduplicates_same_file(self) -> None:
        text = "![[photo.png]]\nsome text\n![[photo.png]]"
        refs = scan_attachments(text)
        assert len(refs) == 1

    def test_empty_text(self) -> None:
        assert scan_attachments("") == []

    def test_no_attachments(self) -> None:
        assert scan_attachments("Just plain text with no embeds.") == []

    def test_attachment_content_hash_is_none_by_default(self) -> None:
        refs = scan_attachments("![[file.png]]")
        assert refs[0].content_hash is None


# ---------------------------------------------------------------------------
# Part 3 — rebuild_companion_from_db
# ---------------------------------------------------------------------------

class TestRebuildFromDb:
    def test_creates_companion_when_missing(self, tmp_path: Path) -> None:
        """Scenario B: uuid in frontmatter, no companion, DB record exists."""
        db_obj = {
            "uuid": "db-uuid-001",
            "source_ref": "Cards/Rebuilt.md",
            "title": "Rebuilt Note",
            "content_hash": "rebuilthash",
        }
        vault_note_fm = {"uuid": "db-uuid-001", "title": "Rebuilt Note"}
        result = rebuild_companion_from_db(
            tmp_path, "db-uuid-001", db_obj, vault_note_fm
        )
        assert result.uuid == "db-uuid-001"
        assert result.source_ref == "Cards/Rebuilt.md"
        assert result.ingest_state == "tracked"
        # Companion file must be written to disk
        assert read_companion(tmp_path, "db-uuid-001") is not None

    def test_uses_vault_note_fm_when_db_missing_fields(self, tmp_path: Path) -> None:
        """Scenario C: no DB record — create from vault note metadata."""
        db_obj: dict = {}
        vault_note_fm = {
            "uuid": "fm-uuid-002",
            "title": "From Frontmatter",
        }
        result = rebuild_companion_from_db(
            tmp_path, "fm-uuid-002", db_obj, vault_note_fm,
            source_ref="Notes/FromFM.md",
        )
        assert result.uuid == "fm-uuid-002"
        assert result.source_ref == "Notes/FromFM.md"


# ---------------------------------------------------------------------------
# Part 3 — repair_companion
# ---------------------------------------------------------------------------

class TestRepairCompanion:
    def test_repair_malformed_yaml(self, tmp_path: Path) -> None:
        """Scenario D: damaged companion — conservative repair."""
        p = tmp_path / "_system" / "companions" / "repair-uuid.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write malformed YAML — missing required uuid field
        p.write_text(
            "---\nsource_ref: Some/Note.md\ntitle: Broken\n---\n",
            encoding="utf-8",
        )
        result = repair_companion(tmp_path, "repair-uuid", source_ref="Some/Note.md")
        assert result is not None
        assert result.uuid == "repair-uuid"
        assert result.source_ref == "Some/Note.md"
        # Should now be readable
        assert read_companion(tmp_path, "repair-uuid") is not None

    def test_repair_missing_file_creates_minimal_companion(self, tmp_path: Path) -> None:
        """If file is entirely missing, repair creates a minimal tracked companion."""
        result = repair_companion(tmp_path, "ghost-uuid", source_ref="Notes/Ghost.md")
        assert result is not None
        assert result.uuid == "ghost-uuid"
        assert read_companion(tmp_path, "ghost-uuid") is not None

    def test_repair_preserves_valid_fields(self, tmp_path: Path) -> None:
        """Conservative repair: valid fields are kept, only missing ones filled."""
        companion = _make_companion(
            uuid="preserve-uuid",
            content_hash="original-hash",
            ingest_state="stale",
        )
        write_companion(tmp_path, companion)
        # Corrupt the file slightly but keep uuid
        p = tmp_path / companion_path("preserve-uuid")
        text = p.read_text(encoding="utf-8")
        # Simulate a field going missing by rewriting without last_ingested
        p.write_text(text.replace("last_ingested:", "# last_ingested:"), encoding="utf-8")
        result = repair_companion(tmp_path, "preserve-uuid")
        assert result.content_hash == "original-hash"  # preserved
        assert result.ingest_state == "stale"  # preserved


# ---------------------------------------------------------------------------
# Part 3 — resolve_uuid_conflict
# ---------------------------------------------------------------------------

class TestResolveUuidConflict:
    def test_frontmatter_wins_by_default(self) -> None:
        """Scenario E: frontmatter uuid wins unless companion has stronger provenance."""
        winner, log = resolve_uuid_conflict(
            frontmatter_uuid="fm-uuid",
            companion_uuid="comp-uuid",
        )
        assert winner == "fm-uuid"
        assert log.conflict is True
        assert log.winner == "fm-uuid"
        assert log.frontmatter_uuid == "fm-uuid"
        assert log.companion_uuid == "comp-uuid"

    def test_no_conflict_when_uuids_match(self) -> None:
        winner, log = resolve_uuid_conflict(
            frontmatter_uuid="same-uuid",
            companion_uuid="same-uuid",
        )
        assert winner == "same-uuid"
        assert log.conflict is False

    def test_conflict_log_has_reason(self) -> None:
        _, log = resolve_uuid_conflict(
            frontmatter_uuid="fm-uuid",
            companion_uuid="comp-uuid",
        )
        assert log.reason  # non-empty reason string


# ---------------------------------------------------------------------------
# Part 3 — path change scenario
# ---------------------------------------------------------------------------

class TestPathChange:
    def test_source_ref_updated_on_write(self, tmp_path: Path) -> None:
        """Scenario F: companion updated when note is renamed/moved."""
        companion = _make_companion(
            uuid="path-change-uuid",
            source_ref="old/path/Note.md",
        )
        write_companion(tmp_path, companion)

        # Simulate note being moved — update source_ref and re-write
        moved = _make_companion(
            uuid="path-change-uuid",
            source_ref="new/path/Note.md",
        )
        write_companion(tmp_path, moved)

        result = read_companion(tmp_path, "path-change-uuid")
        assert result is not None
        assert result.source_ref == "new/path/Note.md"
        assert result.uuid == "path-change-uuid"  # uuid stable across move
