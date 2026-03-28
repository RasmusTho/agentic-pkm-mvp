"""Test SyncResult contract: success flag, conflicts, errors, metadata."""
from __future__ import annotations

from typing import Any

import pytest

from tests.sync.conftest import SyncResult


class TestSyncResultSuccessField:
    """Test success flag."""

    def test_success_true(self) -> None:
        """SyncResult with success=True."""
        result = SyncResult(success=True)
        assert result.success is True

    def test_success_false(self) -> None:
        """SyncResult with success=False."""
        result = SyncResult(success=False)
        assert result.success is False

    def test_success_required(self) -> None:
        """success field is required."""
        with pytest.raises(TypeError):
            SyncResult()  # type: ignore


class TestSyncResultChangesApplied:
    """Test changes_applied counter."""

    def test_changes_applied_default_zero(self) -> None:
        """changes_applied defaults to 0."""
        result = SyncResult(success=True)
        assert result.changes_applied == 0

    def test_changes_applied_set(self) -> None:
        """changes_applied can be set."""
        result = SyncResult(success=True, changes_applied=5)
        assert result.changes_applied == 5

    def test_changes_applied_tracks_count(self) -> None:
        """changes_applied reflects number of files synced."""
        result = SyncResult(success=True, changes_applied=3)
        assert result.changes_applied == 3


class TestSyncResultConflicts:
    """Test conflicts list."""

    def test_conflicts_default_none(self) -> None:
        """conflicts defaults to None (no conflicts)."""
        result = SyncResult(success=True)
        assert result.conflicts is None

    def test_conflicts_empty_list(self) -> None:
        """conflicts can be empty list."""
        result = SyncResult(success=True, conflicts=[])
        assert result.conflicts == []

    def test_conflicts_list_of_paths(self) -> None:
        """conflicts is list of file paths."""
        result = SyncResult(
            success=False,
            conflicts=["notes/file1.md", "notes/file2.md"],
        )
        assert result.conflicts == ["notes/file1.md", "notes/file2.md"]
        assert len(result.conflicts) == 2

    def test_success_false_with_conflicts(self) -> None:
        """Failed sync typically has conflicts."""
        result = SyncResult(
            success=False,
            conflicts=["notes/conflicted.md"],
        )
        assert result.success is False
        assert result.conflicts is not None


class TestSyncResultErrors:
    """Test errors list."""

    def test_errors_default_none(self) -> None:
        """errors defaults to None (no errors)."""
        result = SyncResult(success=True)
        assert result.errors is None

    def test_errors_empty_list(self) -> None:
        """errors can be empty list."""
        result = SyncResult(success=True, errors=[])
        assert result.errors == []

    def test_errors_list_of_messages(self) -> None:
        """errors is list of error messages."""
        result = SyncResult(
            success=False,
            errors=["Connection timeout", "File permission denied"],
        )
        assert len(result.errors) == 2
        assert "Connection timeout" in result.errors

    def test_partial_failure_with_errors(self) -> None:
        """Partial failure includes error messages."""
        result = SyncResult(
            success=False,
            changes_applied=2,
            errors=["Failed to sync file3.md: network error"],
        )
        assert result.success is False
        assert result.changes_applied == 2
        assert result.errors is not None


class TestSyncResultMetadata:
    """Test metadata dict."""

    def test_metadata_default_none(self) -> None:
        """metadata defaults to None."""
        result = SyncResult(success=True)
        assert result.metadata is None

    def test_metadata_dict(self) -> None:
        """metadata is a dict of info."""
        result = SyncResult(
            success=True,
            metadata={"layer": "filesystem", "duration_ms": 150},
        )
        assert result.metadata["layer"] == "filesystem"
        assert result.metadata["duration_ms"] == 150

    def test_metadata_includes_sync_layer(self) -> None:
        """metadata can track which layer was used."""
        for layer in ["filesystem", "git", "icloud", "s3"]:
            result = SyncResult(success=True, metadata={"layer": layer})
            assert result.metadata["layer"] == layer

    def test_metadata_includes_timing(self) -> None:
        """metadata can include sync duration."""
        result = SyncResult(
            success=True,
            metadata={"duration_ms": 250, "start": "2026-03-27T12:00:00Z"},
        )
        assert "duration_ms" in result.metadata
        assert result.metadata["duration_ms"] == 250

    def test_metadata_custom_fields(self) -> None:
        """metadata supports arbitrary fields."""
        result = SyncResult(
            success=True,
            metadata={
                "layer": "git",
                "branch": "main",
                "commit": "abc123",
                "files_pushed": 5,
            },
        )
        assert result.metadata["branch"] == "main"
        assert result.metadata["commit"] == "abc123"
        assert result.metadata["files_pushed"] == 5


class TestSyncResultSuccessWithNoChanges:
    """Test successful sync with no changes."""

    def test_success_zero_changes(self) -> None:
        """Success with zero changes applied."""
        result = SyncResult(success=True, changes_applied=0)
        assert result.success is True
        assert result.changes_applied == 0

    def test_success_no_conflicts_no_errors(self) -> None:
        """Successful sync has no conflicts or errors."""
        result = SyncResult(success=True)
        assert result.conflicts is None
        assert result.errors is None


class TestSyncResultPartialFailure:
    """Test partial failures (some changes applied, some failed)."""

    def test_partial_success(self) -> None:
        """Some files synced, some failed."""
        result = SyncResult(
            success=False,
            changes_applied=3,  # 3 files synced
            errors=["Failed to sync file4.md"],  # 1 file failed
        )
        assert result.success is False
        assert result.changes_applied == 3
        assert result.errors is not None

    def test_partial_with_conflicts(self) -> None:
        """Some files have conflicts."""
        result = SyncResult(
            success=False,
            changes_applied=2,
            conflicts=["file3.md"],
            errors=["Merge conflict in file3.md"],
        )
        assert result.success is False
        assert result.changes_applied == 2
        assert len(result.conflicts) == 1
        assert len(result.errors) == 1


class TestSyncResultIsFrozen:
    """Test that SyncResult is immutable."""

    def test_result_is_frozen_dataclass(self) -> None:
        """SyncResult cannot be modified after creation."""
        result = SyncResult(success=True)
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore

    def test_conflicts_list_immutable(self) -> None:
        """Conflicts list is part of immutable result."""
        result = SyncResult(success=False, conflicts=["file.md"])
        assert result.conflicts == ["file.md"]
        # Note: list itself is mutable, but result object is frozen


class TestSyncResultMetadataTimingStats:
    """Test metadata can include timing and stats."""

    def test_metadata_with_stats(self) -> None:
        """metadata can include sync statistics."""
        result = SyncResult(
            success=True,
            changes_applied=10,
            metadata={
                "files_created": 3,
                "files_modified": 5,
                "files_deleted": 2,
                "duration_ms": 500,
            },
        )
        assert result.metadata["files_created"] == 3
        assert result.metadata["files_modified"] == 5
        assert result.metadata["files_deleted"] == 2

    def test_metadata_with_retry_info(self) -> None:
        """metadata can track retry attempts."""
        result = SyncResult(
            success=True,
            metadata={"retries": 2, "final_attempt": 3},
        )
        assert result.metadata["retries"] == 2
