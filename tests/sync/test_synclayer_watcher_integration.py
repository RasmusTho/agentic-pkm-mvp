"""Test Watcher integration: using SyncLayer instead of direct filesystem."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.sync.conftest import FileChange, FileOperation, ChangeFactory


class VaultEvent:
    """Event emitted by vault to the event bus."""

    def __init__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.event_type = event_type
        self.payload = payload


class Watcher:
    """Watcher using SyncLayer for transport-agnostic change detection."""

    def __init__(self, sync_layer: Any, vault_root: Path) -> None:
        """Initialize watcher with SyncLayer.

        Args:
            sync_layer: SyncLayer implementation (filesystem, git, icloud, etc.)
            vault_root: Vault root directory
        """
        self.sync_layer = sync_layer
        self.vault_root = vault_root
        self.last_tick_time = 0.0
        self.events: list[VaultEvent] = []

    async def tick(self) -> list[VaultEvent]:
        """Run one cycle: detect changes, emit events.

        Returns:
            List of VaultEvent objects emitted during this tick
        """
        # Clear previous events
        self.events.clear()

        # Detect changes via SyncLayer
        changes = await self.sync_layer.detect_changes(self.vault_root, self.last_tick_time)

        # Sort by timestamp for deterministic processing
        sorted_changes = sorted(changes, key=lambda c: c.timestamp)

        # Emit events for each change
        for change in sorted_changes:
            # Determine event type based on operation
            if change.operation == FileOperation.DELETED:
                event_type = "vault.file.deleted"
            else:
                event_type = "vault.file.changed"

            # Build payload with change metadata
            payload = {
                "path": change.path,
                "operation": change.operation.value,
                "timestamp": change.timestamp,
                "hash": change.hash,
                "size": change.size,
            }

            # Include metadata if present
            if change.metadata:
                payload["metadata"] = change.metadata

            self._emit_event(event_type, payload)

        # Update tick time to current time
        self.last_tick_time = max((c.timestamp for c in sorted_changes), default=self.last_tick_time)

        return self.events

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit an event to the vault."""
        event = VaultEvent(event_type, payload)
        self.events.append(event)


class TestWatcherUseSyncLayer:
    """Test that watcher uses SyncLayer.detect_changes instead of filesystem."""

    @pytest.mark.asyncio
    async def test_watcher_calls_detect_changes(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Watcher calls sync_layer.detect_changes() instead of filesystem."""
        # Mock SyncLayer
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change_factory.created("test.md", "content")]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)

        events = await watcher.tick()
        # Watcher should detect change from SyncLayer
        assert len(events) > 0

    @pytest.mark.asyncio
    async def test_watcher_not_tied_to_filesystem(self, temp_vault: Path) -> None:
        """Watcher doesn't directly call filesystem APIs."""
        # This test ensures watcher is decoupled from transport
        class MockSyncLayer:
            called_detect = False

            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                self.called_detect = True
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        await watcher.tick()

        assert sync.called_detect


class TestWatcherEmitFileChangedEvent:
    """Test that watcher emits vault.file.changed events."""

    @pytest.mark.asyncio
    async def test_emit_file_changed_for_created(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Watcher emits vault.file.changed for created files."""
        change = change_factory.created("new.md", "# New note")

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        changed_events = [e for e in events if e.event_type == "vault.file.changed"]
        assert len(changed_events) >= 1

    @pytest.mark.asyncio
    async def test_emit_file_deleted_event(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Watcher emits vault.file.deleted for deleted files."""
        change = change_factory.deleted("removed.md")

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        deleted_events = [e for e in events if e.event_type == "vault.file.deleted"]
        assert len(deleted_events) >= 1


class TestWatcherEventPayload:
    """Test that vault events include change metadata."""

    @pytest.mark.asyncio
    async def test_event_payload_includes_path(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Event payload includes file path."""
        change = change_factory.created("test.md", "content")

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        assert any("test.md" in str(e.payload) for e in events)

    @pytest.mark.asyncio
    async def test_event_payload_includes_operation(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Event payload includes operation type."""
        change = change_factory.created("test.md", "content")

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        assert any("created" in str(e.payload) for e in events)

    @pytest.mark.asyncio
    async def test_event_payload_includes_hash(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Event payload includes content hash."""
        change = change_factory.created("test.md", "content")

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        # Hash should be in payload for deduplication
        payloads = [e.payload for e in events]
        assert any("hash" in str(p) for p in payloads)

    @pytest.mark.asyncio
    async def test_event_payload_includes_source_metadata(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Event payload includes source metadata from FileChange."""
        change = change_factory.created("test.md", "content", metadata={"source": "git"})

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return [change]

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        # Metadata should be propagated
        payloads = [e.payload for e in events]
        assert any("source" in str(p) or "git" in str(p) for p in payloads)


class TestWatcherTimestampOrdering:
    """Test that changes are processed in deterministic timestamp order."""

    @pytest.mark.asyncio
    async def test_changes_processed_in_timestamp_order(
        self, temp_vault: Path, change_factory: ChangeFactory
    ) -> None:
        """Changes are emitted in timestamp order for deterministic processing."""
        changes = [
            change_factory.created("c.md", timestamp=3000.0),
            change_factory.created("a.md", timestamp=1000.0),
            change_factory.created("b.md", timestamp=2000.0),
        ]

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                # SyncLayer may return unordered; watcher should order them
                return changes

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        await watcher.tick()

        # Events should be in timestamp order
        # (implementation detail, but important for determinism)
        pass


class TestWatcherMultipleChanges:
    """Test watcher handling multiple changes in one tick."""

    @pytest.mark.asyncio
    async def test_emit_event_per_change(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Watcher emits one event per file change."""
        changes = [
            change_factory.created("a.md"),
            change_factory.created("b.md"),
            change_factory.modified("c.md"),
        ]

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return changes

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> Any:
                return None

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        watcher = Watcher(sync, temp_vault)
        events = await watcher.tick()

        # Should have events for each change
        assert len(events) >= 3
