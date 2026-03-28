"""Fixtures and factories for SyncLayer tests."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.sync.base import FileChange, FileOperation, SyncLayer, SyncResult, SyncStatus


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
