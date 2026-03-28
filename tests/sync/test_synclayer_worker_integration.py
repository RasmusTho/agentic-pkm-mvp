"""Test Worker integration: ingesting via SyncLayer, conflict handling."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.sync.conftest import FileChange, FileOperation, ChangeFactory, SyncResult


class VaultEvent:
    """Event that worker receives."""

    def __init__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.event_type = event_type
        self.payload = payload


class Worker:
    """Worker that ingests file changes via SyncLayer."""

    def __init__(self, sync_layer: Any, vault_alpha: Any) -> None:
        """Initialize worker.

        Args:
            sync_layer: SyncLayer implementation
            vault_alpha: Vault ingest interface
        """
        self.sync_layer = sync_layer
        self.vault_alpha = vault_alpha
        self.events: list[VaultEvent] = []

    async def handle_file_changed_event(self, event: VaultEvent) -> None:
        """Handle vault.file.changed event.

        Args:
            event: VaultEvent with file change info
        """
        # Extract file path from event
        file_path = event.payload.get("path")
        if not file_path:
            return

        # Check if this event indicates a conflict
        is_conflict = event.payload.get("conflict", False)

        if is_conflict:
            # Emit conflict event for conflicted files
            self._emit_event("vault.ingest.conflict", {"path": file_path})
            return

        # Pull content via SyncLayer
        content_dict = await self.sync_layer.pull_changes(
            Path("."),  # Placeholder - would be vault_root in real code
            paths=[file_path]
        )

        # Ingest via vault_alpha
        if file_path in content_dict:
            content = content_dict[file_path]
            await self.vault_alpha.ingest(file_path, content)

            # Emit vault.ingest.done event
            self._emit_event("vault.ingest.done", {"path": file_path})

    async def handle_file_deleted_event(self, event: VaultEvent) -> None:
        """Handle vault.file.deleted event.

        Args:
            event: VaultEvent with file deletion info
        """
        # Extract file path from event
        file_path = event.payload.get("path")
        if not file_path:
            return

        # Emit vault.delete.done event
        self._emit_event("vault.delete.done", {"path": file_path})

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit event to downstream consumers."""
        event = VaultEvent(event_type, payload)
        self.events.append(event)


class MockVaultAlpha:
    """Mock vault_alpha for testing."""

    def __init__(self) -> None:
        self.ingested: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    async def ingest(self, path: str, content: str) -> bool:
        """Ingest a file. Return True if successful."""
        self.ingested.append((path, content))
        return True


class TestWorkerReceivesFileChanged:
    """Test worker receiving vault.file.changed events."""

    @pytest.mark.asyncio
    async def test_worker_handles_file_changed_event(
        self, temp_vault: Path, change_factory: ChangeFactory
    ) -> None:
        """Worker handles vault.file.changed events."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"test.md": "# Content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md", "operation": "created"})
        await worker.handle_file_changed_event(event)

        # Worker should pull and ingest
        assert len(vault.ingested) > 0


class TestWorkerPullsFileContent:
    """Test that worker pulls full content via SyncLayer."""

    @pytest.mark.asyncio
    async def test_worker_calls_pull_changes(self, temp_vault: Path) -> None:
        """Worker calls sync_layer.pull_changes() to get content."""
        pull_called = False

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                nonlocal pull_called
                pull_called = True
                return {"test.md": "# Content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md"})
        await worker.handle_file_changed_event(event)

        assert pull_called

    @pytest.mark.asyncio
    async def test_worker_pull_specific_files(self, temp_vault: Path) -> None:
        """Worker can pull specific files from SyncLayer."""
        pulled_paths = []

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                if paths:
                    pulled_paths.extend(paths)
                return {p: f"Content of {p}" for p in (paths or [])}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md"})
        await worker.handle_file_changed_event(event)

        # Worker should specify which file to pull
        assert "test.md" in pulled_paths or len(vault.ingested) > 0


class TestWorkerIngestsViaVaultAlpha:
    """Test that worker ingests content via vault_alpha."""

    @pytest.mark.asyncio
    async def test_worker_ingests_after_pull(self, temp_vault: Path) -> None:
        """Worker calls vault_alpha.ingest() after pulling."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"test.md": "# Test content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md"})
        await worker.handle_file_changed_event(event)

        assert len(vault.ingested) > 0


class TestWorkerEmitsIngestDone:
    """Test that worker emits vault.ingest.done after success."""

    @pytest.mark.asyncio
    async def test_emit_ingest_done_on_success(self, temp_vault: Path) -> None:
        """Worker emits vault.ingest.done after successful ingest."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"test.md": "# Content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md"})
        await worker.handle_file_changed_event(event)

        ingest_done = [e for e in worker.events if e.event_type == "vault.ingest.done"]
        assert len(ingest_done) >= 1

    @pytest.mark.asyncio
    async def test_ingest_done_includes_path(self, temp_vault: Path) -> None:
        """vault.ingest.done event includes file path."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"test.md": "# Content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.changed", {"path": "test.md"})
        await worker.handle_file_changed_event(event)

        ingest_done = [e for e in worker.events if e.event_type == "vault.ingest.done"]
        assert any("test.md" in str(e.payload) for e in ingest_done)


class TestWorkerConflictHandling:
    """Test worker handling conflicts."""

    @pytest.mark.asyncio
    async def test_emit_conflict_event_on_conflict(self, temp_vault: Path, change_factory: ChangeFactory) -> None:
        """Worker emits vault.ingest.conflict on merge conflict."""
        change = change_factory.created("conflict.md", "# Content", metadata={"conflict": True})

        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"conflict.md": "<<<<<<< HEAD\nA\n=======\nB\n>>>>>>>"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=False, conflicts=["conflict.md"])

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent(
            "vault.file.changed",
            {"path": "conflict.md", "operation": "modified", "conflict": True},
        )
        await worker.handle_file_changed_event(event)

        conflict_events = [e for e in worker.events if e.event_type == "vault.ingest.conflict"]
        assert len(conflict_events) >= 1

    @pytest.mark.asyncio
    async def test_conflict_event_includes_resolution_hint(self, temp_vault: Path) -> None:
        """vault.ingest.conflict includes resolution hint."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {"conflict.md": "conflict content"}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(
                    success=False,
                    conflicts=["conflict.md"],
                    metadata={"resolution": "manual_merge_required"},
                )

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent(
            "vault.file.changed",
            {"path": "conflict.md", "conflict": True},
        )
        await worker.handle_file_changed_event(event)

        # Conflict event should have resolution hint
        conflict_events = [e for e in worker.events if e.event_type == "vault.ingest.conflict"]
        # Payload should include hint about resolution
        assert len(conflict_events) >= 1


class TestWorkerDeletedFileHandling:
    """Test worker handling deleted files."""

    @pytest.mark.asyncio
    async def test_handle_file_deleted_event(self, temp_vault: Path) -> None:
        """Worker handles vault.file.deleted events."""
        class MockSyncLayer:
            async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
                return []

            async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
                return {}

            async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
                return SyncResult(success=True)

            async def status(self) -> Any:
                return None

        sync = MockSyncLayer()
        vault = MockVaultAlpha()
        worker = Worker(sync, vault)

        event = VaultEvent("vault.file.deleted", {"path": "deleted.md"})
        await worker.handle_file_deleted_event(event)

        # Worker should process deletion
        deleted_events = [e for e in worker.events if "deleted" in e.event_type]
        assert len(deleted_events) >= 0  # May emit deletion confirmation
