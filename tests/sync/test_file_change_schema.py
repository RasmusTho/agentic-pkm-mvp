"""Test FileChange contract: operation types, hashing, metadata, and ordering."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import pytest

from tests.sync.conftest import FileChange, FileOperation, ChangeFactory


class TestFileChangeOperationEnum:
    """Test FileOperation enum values."""

    def test_operation_created_value(self) -> None:
        """CREATED operation exists."""
        assert FileOperation.CREATED == "created"

    def test_operation_modified_value(self) -> None:
        """MODIFIED operation exists."""
        assert FileOperation.MODIFIED == "modified"

    def test_operation_deleted_value(self) -> None:
        """DELETED operation exists."""
        assert FileOperation.DELETED == "deleted"

    def test_operation_renamed_value(self) -> None:
        """RENAMED operation exists."""
        assert FileOperation.RENAMED == "renamed"

    def test_operation_enum_exhaustive(self) -> None:
        """FileOperation has exactly 4 values."""
        assert len(FileOperation) == 4


class TestFileChangeCreation:
    """Test FileChange instantiation and validation."""

    def test_create_change_with_required_fields(self) -> None:
        """FileChange can be created with required fields."""
        change = FileChange(
            path="notes/test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc123",
        )
        assert change.path == "notes/test.md"
        assert change.operation == FileOperation.CREATED
        assert change.timestamp == 1000.0
        assert change.hash == "abc123"

    def test_file_change_is_frozen(self) -> None:
        """FileChange is immutable (frozen dataclass)."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc",
        )
        with pytest.raises(AttributeError):
            change.path = "other.md"  # type: ignore

    def test_created_requires_hash(self) -> None:
        """CREATED operation requires hash for verification."""
        with pytest.raises(AssertionError, match=r"requires hash$"):
            FileChange(
                path="test.md",
                operation=FileOperation.CREATED,
                timestamp=1000.0,
                hash=None,
            )

    def test_modified_requires_hash(self) -> None:
        """MODIFIED operation requires hash for verification."""
        with pytest.raises(AssertionError, match=r"requires hash$"):
            FileChange(
                path="test.md",
                operation=FileOperation.MODIFIED,
                timestamp=1000.0,
                hash=None,
            )

    def test_deleted_does_not_require_hash(self) -> None:
        """DELETED operation can have hash=None."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.DELETED,
            timestamp=1000.0,
            hash=None,
        )
        assert change.hash is None


class TestFileChangeMetadata:
    """Test FileChange metadata field (user-defined tags)."""

    def test_metadata_can_be_empty(self) -> None:
        """Metadata defaults to None or empty dict."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc",
            metadata={},
        )
        assert change.metadata == {}

    def test_metadata_source_tag(self) -> None:
        """Metadata can include source tag (e.g., git, icloud)."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.MODIFIED,
            timestamp=1000.0,
            hash="abc",
            metadata={"source": "git"},
        )
        assert change.metadata["source"] == "git"

    def test_metadata_conflict_tag(self) -> None:
        """Metadata can include conflict flag."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.MODIFIED,
            timestamp=1000.0,
            hash="abc",
            metadata={"conflict": True},
        )
        assert change.metadata["conflict"] is True

    def test_metadata_custom_fields(self) -> None:
        """Metadata supports arbitrary custom fields."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc",
            metadata={"custom_field": "custom_value", "tag": 123},
        )
        assert change.metadata["custom_field"] == "custom_value"
        assert change.metadata["tag"] == 123


class TestFileChangeSize:
    """Test FileChange size field."""

    def test_size_field_set(self) -> None:
        """Size field can be set."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc",
            size=1024,
        )
        assert change.size == 1024

    def test_size_optional(self) -> None:
        """Size field is optional."""
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash="abc",
        )
        assert change.size is None


class TestFileChangeOrdering:
    """Test that changes can be sorted by timestamp."""

    def test_changes_sortable_by_timestamp(self, change_factory: ChangeFactory) -> None:
        """Changes can be sorted by timestamp for deterministic processing."""
        changes = [
            change_factory.created("a.md", timestamp=3000.0),
            change_factory.created("b.md", timestamp=1000.0),
            change_factory.created("c.md", timestamp=2000.0),
        ]
        sorted_changes = sorted(changes, key=lambda c: c.timestamp)
        assert [c.timestamp for c in sorted_changes] == [1000.0, 2000.0, 3000.0]

    def test_same_timestamp_stable_sort(self, change_factory: ChangeFactory) -> None:
        """Changes with same timestamp maintain order (stable sort)."""
        ts = 1000.0
        changes = [
            change_factory.created("z.md", timestamp=ts),
            change_factory.created("a.md", timestamp=ts),
            change_factory.created("m.md", timestamp=ts),
        ]
        sorted_changes = sorted(changes, key=lambda c: (c.timestamp, c.path))
        assert [c.path for c in sorted_changes] == ["a.md", "m.md", "z.md"]

    def test_timestamp_ordering_preserved_in_list(self) -> None:
        """Timestamp ordering is deterministic for processing."""
        now = datetime.now(tz=timezone.utc).timestamp()
        changes = [
            FileChange("a.md", FileOperation.CREATED, now - 200, "abc"),
            FileChange("b.md", FileOperation.CREATED, now - 100, "def"),
            FileChange("c.md", FileOperation.CREATED, now, "ghi"),
        ]
        # Process in timestamp order
        sorted_changes = sorted(changes, key=lambda c: c.timestamp)
        assert len(sorted_changes) == 3
        assert sorted_changes[0].path == "a.md"
        assert sorted_changes[1].path == "b.md"
        assert sorted_changes[2].path == "c.md"


class TestFileChangeHash:
    """Test FileChange hash field for content verification."""

    def test_hash_is_stored(self) -> None:
        """Hash is stored in FileChange."""
        expected_hash = "sha256_value"
        change = FileChange(
            path="test.md",
            operation=FileOperation.CREATED,
            timestamp=1000.0,
            hash=expected_hash,
        )
        assert change.hash == expected_hash

    def test_hash_format_arbitrary(self) -> None:
        """Hash format is not enforced (transport-specific)."""
        # Could be SHA256, MD5, git-sha, S3-etag, etc.
        for hash_val in ["abc123", "deadbeef", "git:abc", "s3:xyz"]:
            change = FileChange(
                path="test.md",
                operation=FileOperation.CREATED,
                timestamp=1000.0,
                hash=hash_val,
            )
            assert change.hash == hash_val

    def test_hash_deduplication_possible(self, change_factory: ChangeFactory) -> None:
        """Same content hash indicates duplicate content."""
        same_content = "identical content"
        change1 = change_factory.created("a.md", same_content)
        change2 = change_factory.created("b.md", same_content)
        assert change1.hash == change2.hash


class TestFileChangeFactory:
    """Test the ChangeFactory helper."""

    def test_factory_creates_created_change(self, change_factory: ChangeFactory) -> None:
        """Factory creates CREATED changes."""
        change = change_factory.created("test.md", "content")
        assert change.operation == FileOperation.CREATED
        assert change.hash is not None
        assert change.size == len("content")

    def test_factory_creates_modified_change(self, change_factory: ChangeFactory) -> None:
        """Factory creates MODIFIED changes."""
        change = change_factory.modified("test.md", "new content")
        assert change.operation == FileOperation.MODIFIED
        assert change.hash is not None

    def test_factory_creates_deleted_change(self, change_factory: ChangeFactory) -> None:
        """Factory creates DELETED changes."""
        change = change_factory.deleted("test.md")
        assert change.operation == FileOperation.DELETED
        assert change.hash is None

    def test_factory_creates_renamed_change(self, change_factory: ChangeFactory) -> None:
        """Factory creates RENAMED changes."""
        change = change_factory.renamed("old.md", "new.md")
        assert change.operation == FileOperation.RENAMED
