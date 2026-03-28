"""Fixtures and factories for SyncLayer tests."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import pytest


class FileOperation(str, Enum):
    """File change operation types."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class FileChange:
    """Represents a single file change in the vault."""

    path: str
    operation: FileOperation
    timestamp: float  # Unix timestamp
    hash: str | None = None  # Content hash for verification
    size: int | None = None  # File size in bytes
    metadata: dict[str, Any] | None = None  # User-defined tags (source, conflict, etc.)

    def __post_init__(self) -> None:
        """Validate FileChange invariants."""
        if self.operation == FileOperation.DELETED:
            # Deleted files may not have hash/size
            pass
        elif self.operation in (FileOperation.CREATED, FileOperation.MODIFIED):
            # Created/modified should have hash for verification
            assert self.hash is not None, f"{self.operation} requires hash"


@dataclass(frozen=True)
class SyncStatus:
    """Status of the sync layer."""

    is_healthy: bool
    last_sync: float | None  # Unix timestamp
    pending_changes: int
    last_error: str | None = None


@dataclass(frozen=True)
class SyncResult:
    """Result of a sync operation."""

    success: bool
    changes_applied: int = 0
    conflicts: list[str] | None = None  # Paths with conflicts
    errors: list[str] | None = None  # Error messages
    metadata: dict[str, Any] | None = None  # Info about sync (layer used, timing, stats)


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    """Create a temporary vault directory structure."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create standard vault structure
    (vault / "_system").mkdir()
    (vault / ".obsidian").mkdir()
    (vault / ".git").mkdir()

    return vault


@pytest.fixture
def change_factory() -> ChangeFactory:
    """Factory for creating FileChange instances."""
    return ChangeFactory()


class ChangeFactory:
    """Factory for creating FileChange objects with defaults."""

    def __init__(self) -> None:
        self.counter = 0

    def created(
        self,
        path: str,
        content: str = "",
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FileChange:
        """Create a CREATED FileChange."""
        if timestamp is None:
            timestamp = datetime.now(tz=timezone.utc).timestamp()

        hash_val = hashlib.sha256(content.encode()).hexdigest()
        return FileChange(
            path=path,
            operation=FileOperation.CREATED,
            timestamp=timestamp,
            hash=hash_val,
            size=len(content.encode()),
            metadata=metadata or {},
        )

    def modified(
        self,
        path: str,
        content: str = "",
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FileChange:
        """Create a MODIFIED FileChange."""
        if timestamp is None:
            timestamp = datetime.now(tz=timezone.utc).timestamp()

        hash_val = hashlib.sha256(content.encode()).hexdigest()
        return FileChange(
            path=path,
            operation=FileOperation.MODIFIED,
            timestamp=timestamp,
            hash=hash_val,
            size=len(content.encode()),
            metadata=metadata or {},
        )

    def deleted(
        self, path: str, timestamp: float | None = None, metadata: dict[str, Any] | None = None
    ) -> FileChange:
        """Create a DELETED FileChange."""
        if timestamp is None:
            timestamp = datetime.now(tz=timezone.utc).timestamp()

        return FileChange(
            path=path,
            operation=FileOperation.DELETED,
            timestamp=timestamp,
            hash=None,
            size=None,
            metadata=metadata or {},
        )

    def renamed(
        self,
        old_path: str,
        new_path: str,
        timestamp: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FileChange:
        """Create a RENAMED FileChange."""
        if timestamp is None:
            timestamp = datetime.now(tz=timezone.utc).timestamp()

        return FileChange(
            path=f"{old_path} -> {new_path}",
            operation=FileOperation.RENAMED,
            timestamp=timestamp,
            hash=None,
            size=None,
            metadata=metadata or {},
        )


@pytest.fixture
def mock_git_repo(tmp_path: Path) -> Path:
    """Create a mock git repository structure."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return repo


@pytest.fixture
def mock_transports() -> MockTransports:
    """Fixture providing mock transport implementations."""
    return MockTransports()


class MockTransports:
    """Mock implementations of transport layers for testing."""

    def __init__(self) -> None:
        self.filesystem_changes: list[FileChange] = []
        self.git_changes: list[FileChange] = []
        self.icloud_changes: list[FileChange] = []
        self.s3_changes: list[FileChange] = []

    def add_filesystem_change(self, change: FileChange) -> None:
        """Add a change to filesystem transport."""
        self.filesystem_changes.append(change)

    def add_git_change(self, change: FileChange) -> None:
        """Add a change to git transport."""
        self.git_changes.append(change)

    def add_icloud_change(self, change: FileChange) -> None:
        """Add a change to iCloud transport."""
        self.icloud_changes.append(change)

    def add_s3_change(self, change: FileChange) -> None:
        """Add a change to S3 transport."""
        self.s3_changes.append(change)

    def reset(self) -> None:
        """Clear all tracked changes."""
        self.filesystem_changes.clear()
        self.git_changes.clear()
        self.icloud_changes.clear()
        self.s3_changes.clear()
