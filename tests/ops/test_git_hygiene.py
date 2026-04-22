from pathlib import Path

from scripts import git_hygiene


def test_preflight_reports_dirty_tree_and_in_progress_operation(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "MERGE_HEAD").write_text("abc123\n", encoding="utf-8")

    def fake_run_git(args: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        if args == ["status", "--porcelain"]:
            return " M docs/development/GITHUB_GOVERNANCE_SETUP.md"
        if args == ["branch", "--show-current"]:
            return "feature/work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="main",
        expected_worktree=str(tmp_path / "other"),
    )

    assert report["ok"] is False
    assert report["checks"]["dirty_tree"] is True
    assert report["checks"]["in_progress_operations"] == ["merge"]
    assert report["checks"]["branch_mismatch"] is True
    assert report["checks"]["worktree_mismatch"] is True


def test_preflight_reports_active_lease_conflict(tmp_path, monkeypatch) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.preflight_report(
        tmp_path,
        active_leases=[
            {
                "resource_id": "issue:561",
                "execution_id": "other-agent",
                "expires_at": 2000,
            },
            {
                "resource_id": "lane:governance",
                "execution_id": "expired-agent",
                "expires_at": 1000,
            },
        ],
        resource_ids={"issue:561", "lane:governance"},
        execution_id="this-agent",
        now=1500,
    )

    assert report["ok"] is False
    assert report["checks"]["lease_conflicts"] == [
        {
            "resource_id": "issue:561",
            "execution_id": "other-agent",
            "expires_at": 2000,
        }
    ]


def test_janitor_report_respects_active_lease_and_reports_candidates(
    tmp_path, monkeypatch
) -> None:
    missing_worktree = tmp_path / "missing-worktree"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["branch", "--merged"]:
            return "\n".join(
                [
                    "* main",
                    "  delivered-safe",
                    "  active-lane",
                    "  develop",
                ]
            )
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {missing_worktree}\n"
                "HEAD abc123\n"
                "branch refs/heads/orphaned-worktree\n\n"
            )
        if args == ["stash", "list", "--date=unix"]:
            return "\n".join(
                [
                    "stash@{0}: WIP on main 1000000000: old work",
                    "stash@{1}: WIP on main 1999999999: current work",
                ]
            )
        if args == ["worktree", "prune", "--dry-run"]:
            return f"Removing worktrees/{missing_worktree.name}: gitdir file points to non-existent location"
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return " * [would prune] origin/stale-remote"
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    report = git_hygiene.janitor_report(
        tmp_path,
        active_leases=[
            {
                "resource_id": "branch:active-lane",
                "execution_id": "agent-1",
                "expires_at": 3000000000,
            }
        ],
        stale_after_days=1,
        now=2000000000,
    )

    assert report["mode"] == "report-only"
    assert report["destructive_actions"] == []
    assert report["stale_merged_branches"] == ["delivered-safe"]
    assert report["orphaned_worktrees"] == [
        {"path": str(missing_worktree), "branch": "orphaned-worktree"}
    ]
    assert report["old_stashes"] == [
        "stash@{0}: WIP on main 1000000000: old work"
    ]
    assert report["prune_candidates"]["worktree"]
    assert report["prune_candidates"]["remote"] == [
        " * [would prune] origin/stale-remote"
    ]
    assert report["active_leases_respected"] == ["branch:active-lane"]


def test_default_command_entrypoint_preserves_global_and_subcommand_args(
    monkeypatch,
) -> None:
    captured = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(git_hygiene, "main", fake_main)

    assert (
        git_hygiene.main_with_default_command(
            "preflight",
            [
                "--cwd",
                "/repo",
                "--lease-file",
                "/leases.json",
                "--expected-branch",
                "main",
            ],
        )
        == 0
    )

    assert captured["argv"] == [
        "--cwd",
        "/repo",
        "--lease-file",
        "/leases.json",
        "preflight",
        "--expected-branch",
        "main",
    ]


def test_default_command_entrypoint_keeps_explicit_command(monkeypatch) -> None:
    captured = {}

    def fake_main(argv: list[str]) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(git_hygiene, "main", fake_main)

    assert git_hygiene.main_with_default_command("janitor", ["janitor"]) == 0
    assert captured["argv"] == ["janitor"]
