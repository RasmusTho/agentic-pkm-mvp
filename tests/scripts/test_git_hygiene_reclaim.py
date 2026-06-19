"""Regression tests for git-hygiene worktree reclamation (issue #2192).

Two terminal-audit residuals from PR #2093, asserted on the production call
path (``build_janitor_plan`` / ``janitor_apply``):

1. A non-root worktree checked out on a protected branch (``stable``/``develop``)
   must NOT be reclaimable — reclaiming would ``git branch -d`` the protected ref
   and bypass branch protections.
2. A squash-merged (PR-proven, non-ancestor) branch must actually be deleted
   after its worktree is removed. ``git branch -d`` refuses non-ancestors, so the
   apply path must use ``git branch -D`` when the merge proof is a merged/closed
   PR; otherwise the branch is skipped forever.
"""

from pathlib import Path
import subprocess

from scripts import git_hygiene


def _reclaim_run_git(tmp_path: Path, worktrees_porcelain: str, local_refs: str):
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(tmp_path)
        if args == ["worktree", "list", "--porcelain"]:
            return worktrees_porcelain
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return local_refs
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    return fake_run_git


# --- Anchor 1: protected branches are never reclaimed (scripts/git_hygiene.py:372) ---


def test_protected_branch_worktree_is_not_reclaimable(tmp_path, monkeypatch) -> None:
    """A clean, non-root worktree on a protected branch is skipped with reason
    ``protected_branch`` and never enters ``reclaimable_worktrees`` — even when its
    branch is an ancestor of origin/main (which would otherwise make it a candidate).
    """
    stable_wt = tmp_path / "stable-wt"
    stable_wt.mkdir()
    develop_wt = tmp_path / "develop-wt"
    develop_wt.mkdir()
    feature_wt = tmp_path / "feature-wt"
    feature_wt.mkdir()

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {stable_wt}\nHEAD d1\nbranch refs/heads/stable\n\n"
        f"worktree {develop_wt}\nHEAD d2\nbranch refs/heads/develop\n\n"
        f"worktree {feature_wt}\nHEAD d3\nbranch refs/heads/deliver/foo\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(tmp_path, porcelain, "main\nstable\ndevelop\ndeliver/foo"),
    )
    # All branches are ancestors of origin/main, so only protection (not merge
    # state) can keep stable/develop out of reclamation.
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.build_janitor_plan(tmp_path, pr_states={})

    reasons = {
        item["path"]: item["reason"]
        for item in report["skipped"]
        if item.get("artifact") == "worktree"
    }
    assert reasons[str(stable_wt)] == "protected_branch"
    assert reasons[str(develop_wt)] == "protected_branch"

    reclaim_paths = {item["path"] for item in report["reclaimable_worktrees"]}
    # Protected worktrees never leak into reclamation.
    assert reclaim_paths.isdisjoint({str(stable_wt), str(develop_wt)})
    # The ordinary feature worktree is still reclaimable (regression guard: the
    # protection check must not over-block).
    assert str(feature_wt) in reclaim_paths


def test_protected_branch_worktree_branch_is_never_deleted(tmp_path, monkeypatch) -> None:
    """End-to-end on the apply path: a protected-branch worktree produces no
    ``worktree remove`` / ``branch -d``/``-D`` for that protected ref."""
    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    stable_wt = tmp_path / "stable-wt"
    stable_wt.mkdir()

    porcelain = (
        f"worktree {tmp_path}\nHEAD abc\nbranch refs/heads/main\n\n"
        f"worktree {stable_wt}\nHEAD d1\nbranch refs/heads/stable\n\n"
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        _reclaim_run_git(tmp_path, porcelain, "main\nstable"),
    )
    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)

    report = git_hygiene.janitor_apply(tmp_path, pr_states={"stable": {"state": "MERGED"}})

    assert report["ok"] is True
    assert ["worktree", "remove", str(stable_wt)] not in commands
    assert ["branch", "-d", "stable"] not in commands
    assert ["branch", "-D", "stable"] not in commands


# --- Anchor 2: PR-proven non-ancestor branches are deleted (scripts/git_hygiene.py:668) ---


def test_apply_uses_force_delete_for_pr_proven_non_ancestor_branch(
    tmp_path, monkeypatch
) -> None:
    """A reclaimable worktree whose merge proof is a merged/closed PR (squash
    merge -> not an ancestor) must be deleted with ``git branch -D``. ``-d`` would
    be refused by git and leave the branch skipped forever."""
    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path):
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
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": [
                {
                    "path": str(tmp_path / "deliver-squashed"),
                    "branch": "deliver/squashed",
                    "merge_proof": "merged_pr",
                },
                {
                    "path": str(tmp_path / "docs-closed"),
                    "branch": "docs/closed",
                    "merge_proof": "closed_pr",
                },
                {
                    "path": str(tmp_path / "deliver-ancestor"),
                    "branch": "deliver/ancestor",
                    "merge_proof": "ancestor_of_origin_main",
                },
            ],
            "orphaned_worktrees": [],
            "skipped": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "active_leases_respected": [],
        },
    )

    report = git_hygiene.janitor_apply(
        tmp_path,
        pr_states={
            "deliver/squashed": {"state": "MERGED"},
            "docs/closed": {"state": "CLOSED"},
            "deliver/ancestor": {"state": "MERGED"},
        },
    )

    assert report["ok"] is True
    # Squash/closed-PR proofs get the force delete.
    assert ["branch", "-D", "deliver/squashed"] in commands
    assert ["branch", "-D", "docs/closed"] in commands
    # Ancestor proof keeps the conservative -d (must NOT be force-deleted).
    assert ["branch", "-d", "deliver/ancestor"] in commands
    assert ["branch", "-D", "deliver/ancestor"] not in commands
    # The ancestor branch is never force-deleted.
    assert not any(
        cmd == ["branch", "-D", "deliver/ancestor"] for cmd in commands
    )


def test_apply_real_git_reclaims_squash_merged_worktree_and_branch(tmp_path) -> None:
    """Real-git regression: a true squash-merge leaves the feature branch as a
    NON-ancestor of origin/main. With a merged PR proof, apply must remove the
    worktree AND delete the branch. This fails against pre-fix code because
    ``git branch -d`` refuses the non-ancestor branch (cleanup leaves ok:false
    and the branch is skipped forever)."""
    # A real bare remote (not the repo itself) isolates the worktree-reclaim path
    # from out-of-scope remote-branch cleanup: only `main` is published, so the
    # local squash-merged branch is never seen as a merged remote ref.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", remote], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)

    # Feature branch with its own commit.
    subprocess.run(["git", "checkout", "-b", "deliver/squashed"], cwd=repo, check=True)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature work"], cwd=repo, check=True)

    # Squash-merge into main: the content lands but the feature branch tip is NOT
    # an ancestor of main (history is rewritten), exactly like a GitHub squash merge.
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    subprocess.run(["git", "merge", "--squash", "deliver/squashed"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "squash: deliver feature (#1)"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "origin"], cwd=repo, check=True)

    # Sanity: the feature branch is genuinely NOT an ancestor of origin/main, so
    # the test would not exercise the -D path if this assumption broke.
    assert git_hygiene._is_ancestor(repo, "deliver/squashed", "origin/main") is False

    clean_wt = tmp_path / "deliver-squashed-wt"
    subprocess.run(["git", "worktree", "add", str(clean_wt), "deliver/squashed"], cwd=repo, check=True)

    report = git_hygiene.janitor_apply(
        repo,
        pr_states={"deliver/squashed": {"state": "MERGED"}},
    )

    assert report["ok"] is True, report["errors"]
    # The worktree is removed (no --force) and the squash-merged branch deleted.
    assert not clean_wt.exists()
    assert "deliver/squashed" not in git_hygiene._local_branches(repo)
    assert any(
        action.get("artifact") == "local_branch"
        and action.get("action") == "delete_after_worktree_remove"
        and action.get("branch") == "deliver/squashed"
        and action.get("command") == ["git", "branch", "-D", "deliver/squashed"]
        for action in report["destructive_actions"]
    )
