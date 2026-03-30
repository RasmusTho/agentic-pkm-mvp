"""FilesystemTransport: filesystem-based change detection and synchronization."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from app.sync.base import FileChange, FileOperation, SyncLayer, SyncResult, SyncStatus

logger = logging.getLogger(__name__)


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
        self.last_sync: float | None = None
        self.last_error: str | None = None

    def _should_ignore(self, file_path: Path, vault_root: Path | None = None) -> bool:
        """Check if path matches ignore patterns."""
        from fnmatch import fnmatch

        # Get the relative path from vault root if provided
        if vault_root:
            try:
                path_str = str(file_path.relative_to(vault_root))
            except ValueError:
                path_str = str(file_path)
        else:
            path_str = str(file_path)

        for pattern in self.ignore_patterns:
            if fnmatch(path_str, pattern) or fnmatch(str(file_path.name), pattern):
                return True
        return False

    def _compute_hash(self, content: bytes) -> str:
        """Compute SHA256 hash of file content."""
        return hashlib.sha256(content).hexdigest()

    async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
        """Scan vault folder, return changes since timestamp.

        Returns:
            list[FileChange]: Created, modified, deleted files since timestamp
        """
        changes: list[FileChange] = []
        current_files: dict[str, tuple[float, str]] = {}

        try:
            # Scan all files in vault
            for file_path in path.rglob("*"):
                # Skip directories and ignored paths
                if file_path.is_dir() or self._should_ignore(file_path, path):
                    continue

                rel_path = str(file_path.relative_to(path))

                try:
                    # Get file stats
                    stat = file_path.stat()
                    mtime = stat.st_mtime

                    # Read file content and compute hash
                    content = file_path.read_bytes()
                    file_hash = self._compute_hash(content)
                    size = len(content)

                    # Store current state
                    current_files[rel_path] = (mtime, file_hash)

                    # Determine if this file is new or modified
                    if rel_path not in self.state:
                        # New file
                        if mtime > since_timestamp:
                            changes.append(
                                FileChange(
                                    path=rel_path,
                                    operation=FileOperation.CREATED,
                                    timestamp=mtime,
                                    hash=file_hash,
                                    size=size,
                                    metadata={"source": "filesystem"},
                                )
                            )
                    else:
                        # Existing file - check if modified
                        old_mtime, old_hash = self.state[rel_path]
                        if mtime > since_timestamp and (mtime > old_mtime or file_hash != old_hash):
                            changes.append(
                                FileChange(
                                    path=rel_path,
                                    operation=FileOperation.MODIFIED,
                                    timestamp=mtime,
                                    hash=file_hash,
                                    size=size,
                                    metadata={"source": "filesystem"},
                                )
                            )
                except (OSError, PermissionError) as e:
                    logger.warning(f"Failed to read {file_path}: {e}")
                    continue

            # Detect deleted files
            for old_path in self.state:
                if old_path not in current_files:
                    changes.append(
                        FileChange(
                            path=old_path,
                            operation=FileOperation.DELETED,
                            timestamp=time.time(),
                            hash=None,
                            size=None,
                            metadata={"source": "filesystem"},
                        )
                    )

            # Update state
            self.state = current_files
            self.last_sync = time.time()
            self.last_error = None

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error detecting changes: {e}")
            raise

        # Sort by timestamp
        return sorted(changes, key=lambda c: c.timestamp)

    async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
        """Read full content of specified or all recent files.

        Args:
            path: Vault root
            paths: Specific files to pull (None = all)

        Returns:
            Dict mapping file path -> content
        """
        result: dict[str, str] = {}

        try:
            if paths is None:
                # Pull all files
                paths = [p for p in self.state.keys()]

            for file_path in paths:
                full_path = path / file_path
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        result[file_path] = content
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning(f"Failed to read {file_path}: {e}")
                        continue

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error pulling changes: {e}")
            raise

        return result

    async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
        """Write files back to filesystem."""
        success = True
        errors: list[str] = []
        applied = 0

        try:
            for file_path, content in changes.items():
                full_path = path / file_path
                try:
                    # Create parent directories if needed
                    full_path.parent.mkdir(parents=True, exist_ok=True)

                    # Write file
                    full_path.write_text(content, encoding="utf-8")
                    applied += 1
                except (OSError, PermissionError) as e:
                    success = False
                    error_msg = f"Failed to write {file_path}: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            self.last_sync = time.time()
            self.last_error = None if success else "; ".join(errors)

        except Exception as e:
            success = False
            error_msg = f"Error pushing changes: {e}"
            errors.append(error_msg)
            self.last_error = error_msg
            logger.error(error_msg)

        return SyncResult(
            success=success,
            changes_applied=applied,
            errors=errors if errors else None,
            metadata={"layer": "filesystem", "timestamp": time.time()},
        )

    async def status(self) -> SyncStatus:
        """Return filesystem sync status."""
        return SyncStatus(
            is_healthy=self.last_error is None,
            last_sync=self.last_sync,
            pending_changes=len(self.state),
            last_error=self.last_error,
        )
