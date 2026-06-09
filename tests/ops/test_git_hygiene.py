from pathlib import Path
import subprocess

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


def test_preflight_allow_dirty_tolerates_dirty_tree_but_not_drift(
    tmp_path, monkeypatch
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return " M .codex/skills/publish-pr/SKILL.md"
        if args == ["branch", "--show-current"]:
            return "governance-work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)

    # At the publish boundary the tree is intentionally dirty; with --allow-dirty
    # that is not a failure as long as branch and worktree match.
    ok_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="governance-work",
        expected_worktree=str(tmp_path),
        allow_dirty=True,
    )
    assert ok_report["ok"] is True
    assert ok_report["checks"]["dirty_tree"] is True
    assert ok_report["checks"]["dirty_tree_enforced"] is False

    # Branch drift still fails even with --allow-dirty.
    drift_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="some-other-branch",
        expected_worktree=str(tmp_path),
        allow_dirty=True,
    )
    assert drift_report["ok"] is False
    assert drift_report["checks"]["branch_mismatch"] is True

    # Without --allow-dirty the dirty tree fails as before.
    strict_report = git_hygiene.preflight_report(
        tmp_path,
        expected_branch="governance-work",
        expected_worktree=str(tmp_path),
    )
    assert strict_report["ok"] is False
    assert strict_report["checks"]["dirty_tree_enforced"] is True


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


def test_preflight_reports_base_branch_behind_origin(tmp_path, monkeypatch) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["status", "--porcelain"]:
            return ""
        if args == ["branch", "--show-current"]:
            return "feature/work"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["rev-parse", "--git-dir"]:
            return str(git_dir)
        if args == ["rev-parse", "main"]:
            return "local-main-sha"
        if args == ["rev-parse", "origin/main"]:
            return "origin-main-sha"
        raise AssertionError(f"unexpected git command: {args}")

    def fake_run(args, **kwargs):
        assert args[:3] == ["git", "merge-base", "--is-ancestor"]
        ancestor, descendant = args[3], args[4]
        return_code = 0 if (ancestor, descendant) == ("main", "origin/main") else 1

        class Result:
            returncode = return_code

        return Result()

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene.subprocess, "run", fake_run)

    report = git_hygiene.preflight_report(tmp_path, base_branch="main")

    assert report["ok"] is False
    assert report["checks"]["base_branch"] == {
        "base_branch": "main",
        "remote_ref": "origin/main",
        "local_sha": "local-main-sha",
        "remote_sha": "origin-main-sha",
        "status": "behind",
        "mismatch": True,
    }


def test_janitor_report_respects_active_lease_and_reports_candidates(
    tmp_path, monkeypatch
) -> None:
    missing_worktree = tmp_path / "missing-worktree"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
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
                f"worktree {tmp_path}\n"
                "HEAD abc123\n"
                "branch refs/heads/main\n\n"
                f"worktree {missing_worktree}\n"
                "HEAD abc123\n"
                "branch refs/heads/orphaned-worktree\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "delivered-safe", "active-lane", "develop"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
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
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

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
    assert report["old_stashes"] == []
    assert report["prune_candidates"]["worktree"]
    assert report["prune_candidates"]["remote"] == [
        " * [would prune] origin/stale-remote"
    ]
    assert report["active_leases_respected"] == ["branch:active-lane"]


def test_janitor_plan_preserves_open_and_draft_pr_branches(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "feature-open", "feature-draft", "feature-merged"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={
            "feature-open": {"state": "OPEN", "isDraft": False},
            "feature-draft": {"state": "OPEN", "isDraft": True},
            "feature-merged": {"state": "MERGED", "isDraft": False},
        },
    )

    assert report["candidates"]["local_branches"] == [{"branch": "feature-merged"}]
    assert {
        (item["name"], item["reason"])
        for item in report["skipped"]
        if item["artifact"] == "local_branch"
    } >= {
        ("feature-open", "open_or_draft_pr"),
        ("feature-draft", "open_or_draft_pr"),
    }


def test_janitor_plan_deletes_only_merged_unchecked_local_branch(
    tmp_path, monkeypatch
) -> None:
    other_worktree = tmp_path / "other"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {other_worktree}\nHEAD def\nbranch refs/heads/checked-clean\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(["main", "stable", "checked-clean", "merged-safe", "not-merged"])
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    def fake_is_ancestor(_cwd: Path, ancestor: str, descendant: str) -> bool:
        return ancestor == "merged-safe" and descendant == "origin/main"

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", fake_is_ancestor)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={
            "checked-clean": {"state": "MERGED"},
            "merged-safe": {"state": "MERGED"},
            "not-merged": {"state": "MERGED"},
        },
    )

    assert report["candidates"]["local_branches"] == [{"branch": "merged-safe"}]
    reasons = {
        item["name"]: item["reason"]
        for item in report["skipped"]
        if item["artifact"] == "local_branch"
    }
    assert reasons["stable"] == "protected_branch"
    assert reasons["checked-clean"] == "checked_out_worktree"
    assert reasons["not-merged"] == "not_merged_to_origin_main"


def test_janitor_plan_skips_dirty_worktree(tmp_path, monkeypatch) -> None:
    dirty_worktree = tmp_path / "dirty"
    dirty_worktree.mkdir()

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return (
                f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
                f"worktree {dirty_worktree}\nHEAD def\nbranch refs/heads/codex/dirty\n\n"
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\ncodex/dirty"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"codex/dirty": {"state": "MERGED"}},
    )

    assert report["candidates"]["worktrees"] == []
    assert any(
        item["artifact"] == "worktree" and item["reason"] == "dirty_worktree"
        for item in report["skipped"]
    )


def test_janitor_plan_remote_merged_branch_is_delete_candidate(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/merged-remote"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"merged-remote": {"state": "MERGED"}},
    )

    assert report["candidates"]["remote_branches"] == [{"branch": "merged-remote"}]


def test_janitor_plan_closed_unmerged_remote_requires_rescue(
    tmp_path, monkeypatch
) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/closed-unmerged"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: False)

    report = git_hygiene.build_janitor_plan(
        tmp_path,
        pr_states={"closed-unmerged": {"state": "CLOSED"}},
        now=2000000000,
    )

    assert report["candidates"]["remote_branches_requiring_rescue"] == [
        {
            "branch": "closed-unmerged",
            "rescue_ref": "refs/archive/git-hygiene/20330518T033320Z/closed-unmerged",
        }
    ]


def test_janitor_plan_unknown_github_state_skips_branch(tmp_path, monkeypatch) -> None:
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "main\nunknown"
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return "origin/unknown"
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)

    report = git_hygiene.build_janitor_plan(tmp_path, pr_states={})

    assert report["candidates"]["local_branches"] == []
    assert report["candidates"]["remote_branches"] == []
    assert {
        (item.get("artifact"), item.get("name"), item.get("reason"))
        for item in report["skipped"]
    } >= {
        ("local_branch", "unknown", "unknown_github_state"),
        ("remote_branch", "unknown", "unknown_github_state"),
    }


def test_janitor_apply_creates_rescue_before_remote_delete(tmp_path, monkeypatch) -> None:
    commands: list[list[str]] = []
    rescue_refspec = (
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged:"
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged"
    )

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {
                        "branch": "closed-unmerged",
                        "rescue_ref": "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged",
                    }
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(tmp_path, pr_states={"closed-unmerged": {"state": "CLOSED"}})

    assert report["ok"] is True
    assert commands.index(
        [
            "update-ref",
            "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged",
            "origin/closed-unmerged",
        ]
    ) < commands.index(["push", "origin", rescue_refspec])
    assert commands.index(["push", "origin", rescue_refspec]) < commands.index(
        ["push", "origin", "--delete", "closed-unmerged"]
    )


def test_janitor_apply_does_not_delete_remote_when_rescue_push_fails(
    tmp_path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    rescue_refspec = (
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged:"
        "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged"
    )

    def fake_run_git_result(args: list[str], _cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ["push", "origin", rescue_refspec]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "rejected")
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *args, **kwargs: {
            "mode": "report",
            "remote_policy": "merged-and-closed-with-rescue",
            "destructive_actions": [],
            "candidates": {
                "local_branches": [],
                "worktrees": [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [
                    {
                        "branch": "closed-unmerged",
                        "rescue_ref": "refs/archive/git-hygiene/20260607T000000Z/closed-unmerged",
                    }
                ],
                "old_stashes": [],
            },
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(tmp_path, pr_states={"closed-unmerged": {"state": "CLOSED"}})

    assert report["ok"] is False
    assert ["push", "origin", "--delete", "closed-unmerged"] not in commands


def test_janitor_dry_run_integration_with_temp_repo(tmp_path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "codex/merged-branch"], cwd=repo, check=True)
    (repo / "merged.txt").write_text("merged\n", encoding="utf-8")
    subprocess.run(["git", "add", "merged.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "merged"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "merge", "--no-ff", "codex/merged-branch", "-m", "merge"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "unmerged-branch"], cwd=repo, check=True)
    (repo / "unmerged.txt").write_text("unmerged\n", encoding="utf-8")
    subprocess.run(["git", "add", "unmerged.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "unmerged"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(repo)], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "main"], cwd=repo, check=True)
    subprocess.run(["git", "worktree", "add", str(tmp_path / "clean-wt"), "codex/merged-branch"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "codex/dirty"], cwd=repo, check=True)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    subprocess.run(["git", "add", "dirty.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "dirty base"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    dirty_wt = tmp_path / "dirty-wt"
    subprocess.run(["git", "worktree", "add", str(dirty_wt), "codex/dirty"], cwd=repo, check=True)
    (dirty_wt / "dirty.txt").write_text("local dirty\n", encoding="utf-8")
    missing_wt = tmp_path / "missing-wt"
    subprocess.run(["git", "worktree", "add", str(missing_wt), "-b", "codex/missing", "main"], cwd=repo, check=True)
    subprocess.run(["rm", "-rf", str(missing_wt)], check=True)

    report = git_hygiene.build_janitor_plan(
        repo,
        pr_states={
            "codex/merged-branch": {"state": "MERGED"},
            "unmerged-branch": {"state": "CLOSED"},
            "codex/dirty": {"state": "MERGED"},
            "codex/missing": {"state": "MERGED"},
        },
    )

    assert {
        "path": str(tmp_path / "clean-wt"),
        "branch": "codex/merged-branch",
    } in report["candidates"]["worktrees"]
    assert any(item["branch"] == "codex/missing" for item in report["candidates"]["orphaned_worktrees"])
    assert any(
        item["artifact"] == "worktree" and item["branch"] == "codex/dirty" and item["reason"] == "dirty_worktree"
        for item in report["skipped"]
    )


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
                "--base-branch",
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
        "--base-branch",
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
