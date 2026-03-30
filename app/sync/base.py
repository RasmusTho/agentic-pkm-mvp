"""Base classes and data structures for SyncLayer abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FileOperation(str, Enum):
    """File change operation types."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


@dataclass(frozen=True)
class FileChange:
    """Represents a single file change in the vault.

    Immutable dataclass enforcing invariants: CREATED/MODIFIED must have hash.
    """

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


class SyncLayer(ABC):
    """Abstract base class defining the SyncLayer contract.

    Implementations must support detecting, pulling, and pushing changes
    without knowing the underlying transport (filesystem, git, iCloud, S3).
    """

    @abstractmethod
    async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
        """Detect file changes since timestamp.

        Args:
            path: Vault root path to scan
            since_timestamp: Unix timestamp; only return changes after this time

        Returns:
            List of FileChange objects, ordered by timestamp (ascending)
        """
        pass

    @abstractmethod
    async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
        """Pull full content of changed files.

        Args:
            path: Vault root path
            paths: Specific file paths to pull; None means all recent changes

        Returns:
            Dict mapping file path -> file content
        """
        pass

    @abstractmethod
    async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
        """Push changes back to the transport.

        Args:
            path: Vault root path
            changes: Dict mapping file path -> new content

        Returns:
            SyncResult indicating success, conflicts, and errors
        """
        pass

    @abstractmethod
    async def status(self) -> SyncStatus:
        """Get current status of the sync layer.

        Returns:
            SyncStatus with health, last_sync time, pending changes, and errors
        """
        pass
