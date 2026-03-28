"""GitTransport: git-based change detection and synchronization."""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from app.sync.base import FileChange, FileOperation, SyncLayer, SyncResult, SyncStatus

logger = logging.getLogger(__name__)


class GitTransport(SyncLayer):
    """Transport layer for git-based change detection.

    Detect changes via git diff (modified), git status (created), deletion via diff.
    Pull via git pull, push via stage/commit/push.
    Handles merge conflicts, branch isolation for multi-device.
    """

    def __init__(
        self,
        *,
        branch: str = "main",
        remote: str = "origin",
        auto_commit: bool = False,
    ) -> None:
        """Initialize GitTransport.

        Args:
            branch: Target branch (default: main)
            remote: Remote name (default: origin)
            auto_commit: Automatically commit changes (default: False)
        """
        self.branch = branch
        self.remote = remote
        self.auto_commit = auto_commit
        self.last_commit: str | None = None
        self.last_sync: float | None = None
        self.last_error: str | None = None
        self.repo_path: Path | None = None
        self._pending_change_timestamps: dict[tuple[Any, ...], float] = {}

    async def detect_changes(self, path: Path, since_timestamp: float) -> list[FileChange]:
        """Detect changes via git diff HEAD and git status.

        Returns:
            - Modified: git diff HEAD
            - Created: git status --untracked
            - Deleted: diff shows removed files
        """
        changes: list[FileChange] = []
        current_timestamps: dict[tuple[Any, ...], float] = {}

        try:
            self.repo_path = path
            # Get git diff to detect modifications and deletions
            result = subprocess.run(
                ["git", "diff", "HEAD", "--name-status"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0 and result.returncode != 1:
                raise RuntimeError(f"git diff failed: {result.stderr}")

            # Parse git diff output (M = modified, D = deleted, A = added)
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                op_code = parts[0]
                file_path = parts[-1]
                file_hash = None
                size = None
                metadata: dict[str, Any] = {"source": "git"}
                cache_key: tuple[Any, ...]

                # Get file content for hash
                full_path = path / file_path
                if op_code == "M":  # Modified
                    operation = FileOperation.MODIFIED
                    if full_path.exists():
                        content = full_path.read_bytes()
                        file_hash = hashlib.sha256(content).hexdigest()
                        size = len(content)
                    cache_key = ("modified", file_path, file_hash)
                elif op_code == "D":  # Deleted
                    operation = FileOperation.DELETED
                    cache_key = ("deleted", file_path)
                elif op_code == "A":  # Added
                    operation = FileOperation.CREATED
                    if full_path.exists():
                        content = full_path.read_bytes()
                        file_hash = hashlib.sha256(content).hexdigest()
                        size = len(content)
                    cache_key = ("created", file_path, file_hash)
                elif op_code.startswith("R") and len(parts) >= 3:  # Renamed, e.g. R100
                    operation = FileOperation.RENAMED
                    old_path = parts[1]
                    file_path = parts[2]
                    full_path = path / file_path
                    if full_path.exists():
                        content = full_path.read_bytes()
                        file_hash = hashlib.sha256(content).hexdigest()
                        size = len(content)
                    similarity = op_code[1:]
                    metadata["old_path"] = old_path
                    if similarity:
                        metadata["similarity"] = similarity
                    cache_key = ("renamed", old_path, file_path, file_hash)
                else:
                    continue

                timestamp = self._stable_timestamp(cache_key, current_timestamps, full_path)
                if timestamp > since_timestamp:
                    changes.append(
                        FileChange(
                            path=file_path,
                            operation=operation,
                            timestamp=timestamp,
                            hash=file_hash,
                            size=size,
                            metadata=metadata,
                        )
                    )

            # Get untracked files (created but not staged)
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue

                    # ?? = untracked
                    if line.startswith("??"):
                        file_path = line[3:].strip()
                        full_path = path / file_path
                        if full_path.exists():
                            content = full_path.read_bytes()
                            file_hash = hashlib.sha256(content).hexdigest()
                            size = len(content)
                            cache_key = ("created", file_path, file_hash)
                            timestamp = self._stable_timestamp(cache_key, current_timestamps, full_path)
                            if timestamp > since_timestamp:
                                changes.append(
                                    FileChange(
                                        path=file_path,
                                        operation=FileOperation.CREATED,
                                        timestamp=timestamp,
                                        hash=file_hash,
                                        size=size,
                                        metadata={"source": "git"},
                                    )
                                )

            self.last_sync = time.time()
            self.last_error = None
            self._pending_change_timestamps = current_timestamps

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error detecting git changes: {e}")
            raise

        return sorted(changes, key=lambda c: c.timestamp)

    async def pull_changes(self, path: Path, paths: list[str] | None = None) -> dict[str, str]:
        """Pull changes from remote: git pull origin <branch>."""
        result: dict[str, str] = {}

        try:
            self.repo_path = path
            # Perform git pull
            pull_result = subprocess.run(
                ["git", "pull", self.remote, self.branch, "--rebase"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if pull_result.returncode != 0:
                logger.warning(f"git pull failed: {pull_result.stderr}")

            # Read specified files or all files
            if paths is None:
                paths = []
                # Get list of all tracked files
                ls_result = subprocess.run(
                    ["git", "ls-files"],
                    cwd=path,
                    capture_output=True,
                    text=True,
                )
                if ls_result.returncode == 0:
                    paths = [p for p in ls_result.stdout.strip().split("\n") if p]

            for file_path in paths:
                full_path = path / file_path
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        result[file_path] = content
                    except (OSError, UnicodeDecodeError) as e:
                        logger.warning(f"Failed to read {file_path}: {e}")
                        continue

            self.last_sync = time.time()
            self.last_error = None

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error pulling git changes: {e}")
            raise

        return result

    async def push_changes(self, path: Path, changes: dict[str, str]) -> SyncResult:
        """Push changes: stage, commit, push."""
        success = True
        errors: list[str] = []
        conflicts: list[str] = []
        applied = 0

        try:
            self.repo_path = path
            # Write files to disk
            for file_path, content in changes.items():
                full_path = path / file_path
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding="utf-8")
                    applied += 1
                except (OSError, PermissionError) as e:
                    success = False
                    error_msg = f"Failed to write {file_path}: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            if applied == 0:
                return SyncResult(
                    success=False,
                    changes_applied=0,
                    errors=errors if errors else ["No files written"],
                    metadata={"layer": "git", "timestamp": time.time()},
                )

            # Stage changes
            stage_result = subprocess.run(
                ["git", "add"] + list(changes.keys()),
                cwd=path,
                capture_output=True,
                text=True,
            )

            if stage_result.returncode != 0:
                success = False
                error_msg = f"git add failed: {stage_result.stderr}"
                errors.append(error_msg)
                logger.error(error_msg)
                return SyncResult(
                    success=False,
                    changes_applied=applied,
                    errors=errors,
                    metadata={"layer": "git", "timestamp": time.time()},
                )

            # Commit changes
            commit_result = subprocess.run(
                ["git", "commit", "-m", f"Sync changes from {self.branch}"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if commit_result.returncode != 0:
                # Might be nothing to commit, which is OK
                if "nothing to commit" not in commit_result.stdout.lower():
                    logger.warning(f"git commit: {commit_result.stderr}")
            else:
                # Extract commit hash
                for line in commit_result.stdout.split("\n"):
                    if line.startswith("["):
                        self.last_commit = line
                        break

            # Pull with rebase to handle remote changes
            pull_result = subprocess.run(
                ["git", "pull", self.remote, self.branch, "--rebase"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if pull_result.returncode != 0:
                # Check for conflicts
                conflicts = await self._detect_conflicts(path)
                if conflicts:
                    success = False
                    error_msg = f"Merge conflicts detected in {len(conflicts)} files"
                    errors.append(error_msg)
                    logger.error(error_msg)

            # Push to remote
            if success or not conflicts:
                push_result = subprocess.run(
                    ["git", "push", self.remote, self.branch],
                    cwd=path,
                    capture_output=True,
                    text=True,
                )

                if push_result.returncode != 0:
                    success = False
                    error_msg = f"git push failed: {push_result.stderr}"
                    errors.append(error_msg)
                    logger.error(error_msg)

            self.last_sync = time.time()
            self.last_error = None if success else "; ".join(errors)

        except Exception as e:
            success = False
            error_msg = f"Error pushing git changes: {e}"
            errors.append(error_msg)
            self.last_error = error_msg
            logger.error(error_msg)

        return SyncResult(
            success=success,
            changes_applied=applied,
            conflicts=conflicts if conflicts else None,
            errors=errors if errors else None,
            metadata={"layer": "git", "branch": self.branch, "timestamp": time.time()},
        )

    async def status(self) -> SyncStatus:
        """Return git sync status (healthy, last commit, pending changes)."""
        pending = 0
        try:
            # Count pending changes
            if self.repo_path is not None:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                )
            else:
                result = None
            if result is not None and result.returncode == 0:
                pending = len([l for l in result.stdout.split("\n") if l])
        except Exception:
            pass

        return SyncStatus(
            is_healthy=self.last_error is None,
            last_sync=self.last_sync,
            pending_changes=pending,
            last_error=self.last_error,
        )

    async def _detect_conflicts(self, path: Path) -> list[str]:
        """Detect merge conflicts in working tree."""
        conflicts: list[str] = []

        try:
            # Check for unresolved merge conflicts
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=path,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                conflicts = [f for f in result.stdout.strip().split("\n") if f]
        except Exception as e:
            logger.error(f"Error detecting conflicts: {e}")

        return conflicts

    def _stable_timestamp(
        self,
        cache_key: tuple[Any, ...],
        current_timestamps: dict[tuple[Any, ...], float],
        full_path: Path | None = None,
    ) -> float:
        """Reuse timestamps for unchanged pending git entries across polling cycles."""
        cached = self._pending_change_timestamps.get(cache_key)
        if cached is not None:
            current_timestamps[cache_key] = cached
            return cached

        if full_path is not None and full_path.exists():
            timestamp = full_path.stat().st_mtime
        else:
            timestamp = time.time()

        current_timestamps[cache_key] = timestamp
        return timestamp
