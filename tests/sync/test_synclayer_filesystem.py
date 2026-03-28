"""Test FilesystemTransport: scanning, mtime tracking, ignore patterns, edge cases."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import AsyncIterator

import pytest

from tests.sync.conftest import FileChange, FileOperation, SyncLayer, SyncResult, SyncStatus


class FilesystemTransport(SyncLayer):
    """Transport layer for filesystem-based change detection.

    Scans vault folder, compares against last-seen state, returns created/modified/deleted.
    Uses file mtime as timestamp (or inode for reliability).
    """

    def __init__(
        self, *, ignore_patterns: list[str] | None = None, use_mtime: bool = True
    ) -> None:
        """Initialize FilesystemTransport.

        Args:
            ignore_patterns: List of glob patterns to ignore (default: _system, .git, .obsidian)
            use_mtime: Use mtime for timestamps (True) or inode (False)
        """
        self.ignore_patterns = ignore_patterns or ["_system/*", ".git/*", ".obsidian/*"]
        self.use_mtime = use_mtime
        self.state: dict[str, tuple[float, str]] = {}  # path -> (mtime, hash)

    async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
        """Scan vault folder, return changes since timestamp.

        Returns:
            list[FileChange]: Created, modified, deleted files since timestamp
        """
        pass  # Implementation required in TDD

    async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
        """Read full content of specified or all recent files.

        Args:
            path: Vault root
            paths: Specific files to pull (None = all)

        Returns:
            Dict mapping file path -> content
        """
        pass

    async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
        """Write files back to filesystem."""
        pass

    async def status(self) -> SyncStatus:
        """Return filesystem sync status."""
        pass

    def _should_ignore(self, file_path: Path) -> bool:
        """Check if path matches ignore patterns."""
        pass

    def _compute_hash(self, content: bytes) -> str:
        """Compute SHA256 hash of file content."""
        pass


class TestFilesystemTransportInitialization:
    """Test FilesystemTransport setup."""

    def test_initialize_with_defaults(self) -> None:
        """FilesystemTransport initializes with default ignore patterns."""
        transport = FilesystemTransport()
        assert transport.ignore_patterns == ["_system/*", ".git/*", ".obsidian/*"]

    def test_initialize_with_custom_ignore_patterns(self) -> None:
        """FilesystemTransport accepts custom ignore patterns."""
        patterns = ["*.tmp", ".cache/*"]
        transport = FilesystemTransport(ignore_patterns=patterns)
        assert transport.ignore_patterns == patterns

    def test_initialize_mtime_enabled_by_default(self) -> None:
        """FilesystemTransport uses mtime by default."""
        transport = FilesystemTransport()
        assert transport.use_mtime is True

    def test_initialize_can_disable_mtime(self) -> None:
        """FilesystemTransport can use inode instead of mtime."""
        transport = FilesystemTransport(use_mtime=False)
        assert transport.use_mtime is False

    def test_state_starts_empty(self) -> None:
        """Initial state is empty dict."""
        transport = FilesystemTransport()
        assert transport.state == {}


class TestFilesystemDetectCreated:
    """Test detecting newly created files."""

    @pytest.mark.asyncio
    async def test_detect_single_created_file(self, temp_vault: Path) -> None:
        """Detect a newly created file."""
        note = temp_vault / "note.md"
        note.write_text("# Test", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert len(changes) >= 1
        created_files = [c for c in changes if c.operation == FileOperation.CREATED]
        assert any(c.path == "note.md" for c in created_files)

    @pytest.mark.asyncio
    async def test_detect_multiple_created_files(self, temp_vault: Path) -> None:
        """Detect multiple newly created files."""
        (temp_vault / "a.md").write_text("A", encoding="utf-8")
        (temp_vault / "b.md").write_text("B", encoding="utf-8")
        (temp_vault / "c.md").write_text("C", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)
        created = [c for c in changes if c.operation == FileOperation.CREATED]

        assert len(created) == 3

    @pytest.mark.asyncio
    async def test_created_file_has_hash(self, temp_vault: Path) -> None:
        """Created files include content hash."""
        note = temp_vault / "note.md"
        content = "# Test content"
        note.write_text(content, encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)
        created = [c for c in changes if c.operation == FileOperation.CREATED and c.path == "note.md"]

        assert created
        assert created[0].hash is not None

    @pytest.mark.asyncio
    async def test_created_file_has_size(self, temp_vault: Path) -> None:
        """Created files include size in bytes."""
        note = temp_vault / "note.md"
        content = "# Test"
        note.write_text(content, encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)
        created = [c for c in changes if c.operation == FileOperation.CREATED]

        assert created
        assert created[0].size == len(content)


class TestFilesystemDetectModified:
    """Test detecting modified files."""

    @pytest.mark.asyncio
    async def test_detect_file_modification(self, temp_vault: Path) -> None:
        """Detect when existing file is modified."""
        note = temp_vault / "note.md"
        note.write_text("Original", encoding="utf-8")

        transport = FilesystemTransport()
        # First scan to establish baseline
        await transport.detect_changes(temp_vault, since_timestamp=0.0)

        # Modify file
        note.write_text("Modified", encoding="utf-8")

        # Detect modification
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)
        modified = [c for c in changes if c.operation == FileOperation.MODIFIED]

        assert any(c.path == "note.md" for c in modified)


class TestFilesystemDetectDeleted:
    """Test detecting deleted files."""

    @pytest.mark.asyncio
    async def test_detect_file_deletion(self, temp_vault: Path) -> None:
        """Detect when file is deleted."""
        note = temp_vault / "note.md"
        note.write_text("Content", encoding="utf-8")

        transport = FilesystemTransport()
        # Establish baseline
        await transport.detect_changes(temp_vault, since_timestamp=0.0)

        # Delete file
        note.unlink()

        # Detect deletion
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)
        deleted = [c for c in changes if c.operation == FileOperation.DELETED]

        assert any(c.path == "note.md" for c in deleted)


class TestFilesystemIgnorePatterns:
    """Test that ignore patterns work correctly."""

    @pytest.mark.asyncio
    async def test_ignore_system_folder(self, temp_vault: Path) -> None:
        """Files in _system/ are ignored by default."""
        (temp_vault / "_system" / "file.md").write_text("X", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert not any("_system" in c.path for c in changes)

    @pytest.mark.asyncio
    async def test_ignore_git_folder(self, temp_vault: Path) -> None:
        """Files in .git/ are ignored by default."""
        (temp_vault / ".git" / "config").write_text("X", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert not any(".git" in c.path for c in changes)

    @pytest.mark.asyncio
    async def test_ignore_obsidian_folder(self, temp_vault: Path) -> None:
        """Files in .obsidian/ are ignored by default."""
        (temp_vault / ".obsidian" / "plugins.json").write_text("X", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert not any(".obsidian" in c.path for c in changes)

    @pytest.mark.asyncio
    async def test_custom_ignore_patterns(self, temp_vault: Path) -> None:
        """Custom ignore patterns are respected."""
        (temp_vault / "temp.tmp").write_text("X", encoding="utf-8")
        (temp_vault / "keep.md").write_text("Y", encoding="utf-8")

        transport = FilesystemTransport(ignore_patterns=["*.tmp"])
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert not any(".tmp" in c.path for c in changes)
        assert any("keep.md" in c.path for c in changes)


class TestFilesystemTimestampFiltering:
    """Test that since_timestamp filtering works."""

    @pytest.mark.asyncio
    async def test_only_recent_changes_returned(self, temp_vault: Path) -> None:
        """Only changes after since_timestamp are returned."""
        # This is a contract test; implementation will use mtime
        pass  # To be implemented


class TestFilesystemEdgeCases:
    """Test edge cases: symlinks, permissions, atomic writes."""

    @pytest.mark.asyncio
    async def test_symlinks_handled_gracefully(self, temp_vault: Path) -> None:
        """Symlinks don't break the detector."""
        # Implementation should skip or follow symlinks consistently
        pass

    @pytest.mark.asyncio
    async def test_permission_denied_handled(self, temp_vault: Path) -> None:
        """Permission errors don't crash the detector."""
        pass

    @pytest.mark.asyncio
    async def test_nested_directory_traversal(self, temp_vault: Path) -> None:
        """Nested directories are traversed correctly."""
        (temp_vault / "dir" / "subdir").mkdir(parents=True)
        (temp_vault / "dir" / "subdir" / "note.md").write_text("X", encoding="utf-8")

        transport = FilesystemTransport()
        changes = await transport.detect_changes(temp_vault, since_timestamp=0.0)

        assert any("dir/subdir/note.md" in c.path for c in changes)
