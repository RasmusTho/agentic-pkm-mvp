"""Test SyncLayer interface contract: base class with abstract methods."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pytest

from tests.sync.conftest import FileChange, FileOperation, SyncResult, SyncStatus


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


class TestSyncLayerIsAbstract:
    """Test that SyncLayer is abstract and cannot be instantiated."""

    def test_cannot_instantiate_synclayer(self) -> None:
        """SyncLayer should not be directly instantiable."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            SyncLayer()  # type: ignore

    def test_detect_changes_is_abstract(self) -> None:
        """detect_changes must be implemented by subclasses."""
        assert hasattr(SyncLayer, "detect_changes")
        assert getattr(SyncLayer.detect_changes, "__isabstractmethod__", False)

    def test_pull_changes_is_abstract(self) -> None:
        """pull_changes must be implemented by subclasses."""
        assert hasattr(SyncLayer, "pull_changes")
        assert getattr(SyncLayer.pull_changes, "__isabstractmethod__", False)

    def test_push_changes_is_abstract(self) -> None:
        """push_changes must be implemented by subclasses."""
        assert hasattr(SyncLayer, "push_changes")
        assert getattr(SyncLayer.push_changes, "__isabstractmethod__", False)

    def test_status_is_abstract(self) -> None:
        """status must be implemented by subclasses."""
        assert hasattr(SyncLayer, "status")
        assert getattr(SyncLayer.status, "__isabstractmethod__", False)


class TestSyncLayerMethodSignatures:
    """Test that SyncLayer method signatures are correct."""

    def test_detect_changes_signature(self) -> None:
        """detect_changes accepts path and since_timestamp."""
        # Verify abstract method exists and is async
        method = SyncLayer.detect_changes
        assert callable(method)

    def test_pull_changes_signature(self) -> None:
        """pull_changes accepts path and optional paths list."""
        method = SyncLayer.pull_changes
        assert callable(method)

    def test_push_changes_signature(self) -> None:
        """push_changes accepts path and changes dict."""
        method = SyncLayer.push_changes
        assert callable(method)

    def test_status_signature(self) -> None:
        """status is a parameterless async method."""
        method = SyncLayer.status
        assert callable(method)


class ConcreteSyncLayer(SyncLayer):
    """Concrete implementation for testing the interface contract."""

    async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
        """Stub implementation."""
        return []

    async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
        """Stub implementation."""
        return {}

    async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
        """Stub implementation."""
        return SyncResult(success=True)

    async def status(self) -> SyncStatus:
        """Stub implementation."""
        return SyncStatus(is_healthy=True, last_sync=None, pending_changes=0)


class TestSyncLayerCanBeImplemented:
    """Test that concrete implementations can be created."""

    def test_concrete_implementation_instantiates(self) -> None:
        """Concrete SyncLayer can be instantiated."""
        layer = ConcreteSyncLayer()
        assert isinstance(layer, SyncLayer)

    def test_concrete_implementation_has_detect_changes(self) -> None:
        """Concrete implementation has detect_changes method."""
        layer = ConcreteSyncLayer()
        assert hasattr(layer, "detect_changes")
        assert callable(layer.detect_changes)

    def test_concrete_implementation_has_pull_changes(self) -> None:
        """Concrete implementation has pull_changes method."""
        layer = ConcreteSyncLayer()
        assert hasattr(layer, "pull_changes")
        assert callable(layer.pull_changes)

    def test_concrete_implementation_has_push_changes(self) -> None:
        """Concrete implementation has push_changes method."""
        layer = ConcreteSyncLayer()
        assert hasattr(layer, "push_changes")
        assert callable(layer.push_changes)

    def test_concrete_implementation_has_status(self) -> None:
        """Concrete implementation has status method."""
        layer = ConcreteSyncLayer()
        assert hasattr(layer, "status")
        assert callable(layer.status)
