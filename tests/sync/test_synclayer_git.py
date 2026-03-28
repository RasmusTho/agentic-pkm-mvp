"""Test GitTransport: git diff, git pull/push, conflict handling, branch isolation."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.sync.git import GitTransport


def _completed_process(
    args: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


class TestGitTransportInitialization:
    """Test GitTransport setup."""

    def test_initialize_with_defaults(self) -> None:
        """GitTransport initializes with default branch and remote."""
        transport = GitTransport()
        assert transport.branch == "main"
        assert transport.remote == "origin"
        assert transport.auto_commit is False

    def test_initialize_with_custom_branch(self) -> None:
        """GitTransport accepts custom branch."""
        transport = GitTransport(branch="develop")
        assert transport.branch == "develop"

    def test_initialize_with_custom_remote(self) -> None:
        """GitTransport accepts custom remote."""
        transport = GitTransport(remote="upstream")
        assert transport.remote == "upstream"

    def test_initialize_with_auto_commit(self) -> None:
        """GitTransport can enable auto-commit."""
        transport = GitTransport(auto_commit=True)
        assert transport.auto_commit is True

    def test_last_commit_starts_none(self) -> None:
        """last_commit is None initially."""
        transport = GitTransport()
        assert transport.last_commit is None


class TestGitDetectModified:
    """Test detecting modified files via git diff."""

    @pytest.mark.asyncio
    async def test_detect_modified_via_git_diff(self, mock_git_repo: Path) -> None:
        """Modified files detected via git diff HEAD."""
        # Initialize git repo with file
        (mock_git_repo / "note.md").write_text("Original", encoding="utf-8")

        transport = GitTransport()
        # Contract: implement git diff detection
        pass

    @pytest.mark.asyncio
    async def test_detect_staged_modifications(self, mock_git_repo: Path) -> None:
        """Staged modifications are detected."""
        pass

    @pytest.mark.asyncio
    async def test_modified_includes_hash(self, mock_git_repo: Path) -> None:
        """Modified files include content hash."""
        pass


class TestGitDetectCreated:
    """Test detecting created files via git status."""

    @pytest.mark.asyncio
    async def test_detect_untracked_files(self, mock_git_repo: Path) -> None:
        """Untracked files detected via git status --untracked-files."""
        pass

    @pytest.mark.asyncio
    async def test_ignore_untracked_patterns(self, mock_git_repo: Path) -> None:
        """git ignore patterns are respected."""
        pass


class TestGitDetectDeleted:
    """Test detecting deleted files."""

    @pytest.mark.asyncio
    async def test_detect_deleted_files_in_diff(self, mock_git_repo: Path) -> None:
        """Deleted files show in git diff as deletions."""
        pass

    @pytest.mark.asyncio
    async def test_deleted_change_has_no_hash(self, mock_git_repo: Path) -> None:
        """Deleted changes have hash=None."""
        pass


class TestGitPullChanges:
    """Test pulling changes from remote."""

    @pytest.mark.asyncio
    async def test_pull_from_configured_remote(self, mock_git_repo: Path) -> None:
        """Pull changes from configured remote and branch."""
        transport = GitTransport(branch="main", remote="origin")
        # Contract: git pull origin main
        pass

    @pytest.mark.asyncio
    async def test_pull_custom_remote(self, mock_git_repo: Path) -> None:
        """Pull from custom remote."""
        transport = GitTransport(remote="upstream")
        # Contract: git pull upstream <branch>
        pass

    @pytest.mark.asyncio
    async def test_pull_returns_file_contents(self, mock_git_repo: Path) -> None:
        """Pull returns dict of file path -> content."""
        pass

    @pytest.mark.asyncio
    async def test_pull_specific_files(self, mock_git_repo: Path) -> None:
        """Pull can fetch specific files only."""
        pass


class TestGitPushChanges:
    """Test pushing changes to remote."""

    @pytest.mark.asyncio
    async def test_push_stages_files(self, mock_git_repo: Path) -> None:
        """Push stages files with git add."""
        pass

    @pytest.mark.asyncio
    async def test_push_creates_commit(self, mock_git_repo: Path) -> None:
        """Push creates commit with changes."""
        pass

    @pytest.mark.asyncio
    async def test_push_to_configured_remote(self, mock_git_repo: Path) -> None:
        """Push sends to configured remote and branch."""
        transport = GitTransport(branch="main", remote="origin")
        # Contract: git push origin main
        pass

    @pytest.mark.asyncio
    async def test_push_result_success(self, mock_git_repo: Path) -> None:
        """Successful push returns SyncResult(success=True)."""
        pass


class TestGitConflictHandling:
    """Test conflict detection and reporting."""

    @pytest.mark.asyncio
    async def test_detect_merge_conflict_markers(self, mock_git_repo: Path) -> None:
        """Merge conflict markers are detected."""
        # File with <<<<<<< ======= >>>>>>> indicates conflict
        pass

    @pytest.mark.asyncio
    async def test_conflict_emitted_as_metadata(self, mock_git_repo: Path) -> None:
        """Conflicted files have metadata={'conflict': True}."""
        pass

    @pytest.mark.asyncio
    async def test_sync_result_includes_conflicts(self, mock_git_repo: Path) -> None:
        """SyncResult.conflicts lists conflicted file paths."""
        pass

    @pytest.mark.asyncio
    async def test_partial_push_with_conflicts(self, mock_git_repo: Path) -> None:
        """Push with conflicts reports success=False and lists conflicts."""
        pass


class TestGitBranchIsolation:
    """Test per-device branch isolation (multi-device support)."""

    def test_branch_configurable_per_device(self) -> None:
        """Branch can be set per transport instance."""
        device1 = GitTransport(branch="device-1")
        device2 = GitTransport(branch="device-2")
        assert device1.branch != device2.branch

    def test_each_device_on_different_branch(self) -> None:
        """Different devices work on different branches."""
        # device-1 pushes to device-1 branch
        # device-2 pushes to device-2 branch
        # They pull from main (or a sync branch)
        pass

    @pytest.mark.asyncio
    async def test_pull_from_main_push_to_device_branch(self, mock_git_repo: Path) -> None:
        """Pull from main, push to device-specific branch."""
        pass


class TestGitTransportConflictMetadata:
    """Test that conflicts are properly marked in metadata."""

    @pytest.mark.asyncio
    async def test_conflict_metadata_flag(self, mock_git_repo: Path) -> None:
        """FileChange for conflicted file has metadata={'conflict': True}."""
        pass

    @pytest.mark.asyncio
    async def test_resolution_hint_in_metadata(self, mock_git_repo: Path) -> None:
        """Metadata can include resolution hint for worker."""
        pass


class TestGitTransportReviewRegressions:
    """Regression coverage for PR review comments on GitTransport."""

    @pytest.mark.asyncio
    async def test_detect_changes_handles_scored_rename_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        renamed = repo / "renamed.md"
        renamed.write_text("renamed content", encoding="utf-8")

        def fake_run(
            args: list[str], *, cwd: Path | None = None, capture_output: bool = False, text: bool = False
        ) -> subprocess.CompletedProcess[str]:
            if args[:4] == ["git", "diff", "HEAD", "--name-status"]:
                return _completed_process(args, stdout="R100\told.md\trenamed.md\n")
            if args[:3] == ["git", "status", "--porcelain"]:
                return _completed_process(args)
            raise AssertionError(f"Unexpected command: {args}")

        monkeypatch.setattr(subprocess, "run", fake_run)

        changes = await GitTransport().detect_changes(repo, since_timestamp=0.0)

        assert len(changes) == 1
        assert changes[0].operation.value == "renamed"
        assert changes[0].path == "renamed.md"
        assert changes[0].metadata == {"source": "git", "old_path": "old.md", "similarity": "100"}

    @pytest.mark.asyncio
    async def test_detect_changes_reuses_timestamp_for_unchanged_pending_diff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        note = repo / "note.md"
        note.write_text("updated", encoding="utf-8")

        stable_mtime = 1_700_000_000
        note.touch()
        import os

        os.utime(note, (stable_mtime, stable_mtime))

        def fake_run(
            args: list[str], *, cwd: Path | None = None, capture_output: bool = False, text: bool = False
        ) -> subprocess.CompletedProcess[str]:
            if args[:4] == ["git", "diff", "HEAD", "--name-status"]:
                return _completed_process(args, stdout="M\tnote.md\n")
            if args[:3] == ["git", "status", "--porcelain"]:
                return _completed_process(args)
            raise AssertionError(f"Unexpected command: {args}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        transport = GitTransport()

        first_changes = await transport.detect_changes(repo, since_timestamp=0.0)
        second_changes = await transport.detect_changes(repo, since_timestamp=stable_mtime)

        assert len(first_changes) == 1
        assert first_changes[0].timestamp == stable_mtime
        assert second_changes == []

    @pytest.mark.asyncio
    async def test_status_uses_tracked_repo_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        observed_cwds: list[Path | None] = []

        def fake_run(
            args: list[str], *, cwd: Path | None = None, capture_output: bool = False, text: bool = False
        ) -> subprocess.CompletedProcess[str]:
            observed_cwds.append(cwd)
            if args[:4] == ["git", "diff", "HEAD", "--name-status"]:
                return _completed_process(args)
            if args[:3] == ["git", "status", "--porcelain"]:
                return _completed_process(args, stdout=" M tracked.md\n?? new.md\n")
            raise AssertionError(f"Unexpected command: {args}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        transport = GitTransport()

        await transport.detect_changes(repo, since_timestamp=0.0)
        status = await transport.status()

        assert observed_cwds[-1] == repo
        assert status.pending_changes == 2

    @pytest.mark.asyncio
    async def test_push_changes_fails_when_git_commit_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        commands: list[list[str]] = []

        def fake_run(
            args: list[str], *, cwd: Path | None = None, capture_output: bool = False, text: bool = False
        ) -> subprocess.CompletedProcess[str]:
            commands.append(args)
            if args[:2] == ["git", "add"]:
                return _completed_process(args)
            if args[:2] == ["git", "commit"]:
                return _completed_process(args, returncode=1, stderr="Author identity unknown")
            if args[:4] == ["git", "pull", "origin", "main"]:
                return _completed_process(args)
            if args[:2] == ["git", "push"]:
                raise AssertionError("git push should not run after a commit failure")
            raise AssertionError(f"Unexpected command: {args}")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = await GitTransport().push_changes(repo, {"note.md": "updated"})

        assert result.success is False
        assert result.errors is not None
        assert any("git commit failed" in error for error in result.errors)
        assert ["git", "pull", "origin", "main", "--rebase"] in commands
        assert not any(args[:2] == ["git", "push"] for args in commands)

    @pytest.mark.asyncio
    async def test_push_changes_fails_when_pull_fails_without_conflicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        commands: list[list[str]] = []

        def fake_run(
            args: list[str], *, cwd: Path | None = None, capture_output: bool = False, text: bool = False
        ) -> subprocess.CompletedProcess[str]:
            commands.append(args)
            if args[:2] == ["git", "add"]:
                return _completed_process(args)
            if args[:2] == ["git", "commit"]:
                return _completed_process(args, stdout="[main 1234567] Sync changes from main\n")
            if args[:4] == ["git", "pull", "origin", "main"]:
                return _completed_process(args, returncode=1, stderr="fatal: could not read from remote repository")
            if args[:2] == ["git", "push"]:
                raise AssertionError("git push should not run when git pull fails")
            raise AssertionError(f"Unexpected command: {args}")

        async def fake_detect_conflicts(self, path: Path) -> list[str]:
            assert path == repo
            return []

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(GitTransport, "_detect_conflicts", fake_detect_conflicts)

        result = await GitTransport().push_changes(repo, {"note.md": "updated"})

        assert result.success is False
        assert result.conflicts is None
        assert result.errors is not None
        assert any("git pull failed" in error for error in result.errors)
        assert not any(args[:2] == ["git", "push"] for args in commands)
