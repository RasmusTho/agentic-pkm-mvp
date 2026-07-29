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
import unicodedata
from contextlib import nullcontext

import pytest

from scripts import agent_worktree, git_hygiene


GENERATION = "a" * 32


def _allow_lifecycle_authority(_targets):
    return nullcontext(lambda: None)


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

    report = git_hygiene.janitor_apply(
        tmp_path,
        pr_states={"stable": {"state": "MERGED"}},
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
    )

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
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records={},
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

    lifecycle_records = {
        str(clean_wt.resolve()): {
            "path": str(clean_wt.resolve()),
            "branch": "deliver/squashed",
            "generation": GENERATION,
            "owner": "completed-owner",
            "status": "complete",
            "registered_at": -20,
            "heartbeat_at": -10,
            "complete_at": 0,
            "expires_at": 0,
        }
    }
    report = git_hygiene.janitor_apply(
        repo,
        pr_states={"deliver/squashed": {"state": "MERGED"}},
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records=lifecycle_records,
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


# --- Anchor 3: post-removal branch deletion keeps path authority (issue #4201) ---


def _init_repo_with_merged_branch(
    tmp_path: Path,
    *,
    branch: str,
    squash: bool,
) -> Path:
    """Real repo + bare remote whose ``branch`` is merged into ``origin/main``.

    ``squash=True`` reproduces a GitHub squash merge (branch tip is NOT an
    ancestor of ``origin/main``, so the merge proof is ``merged_pr`` and the
    apply path uses the irreversible ``git branch -D``). ``squash=False`` keeps
    the branch an ancestor, which is what makes it an ordinary local-branch
    cleanup candidate on a later restart.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", remote], check=True
    )
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True)
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature work"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True)
    if squash:
        subprocess.run(["git", "merge", "--squash", branch], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "squash: feature (#1)"], cwd=repo, check=True)
    else:
        subprocess.run(
            ["git", "merge", "--no-ff", "-m", "merge: feature (#1)", branch],
            cwd=repo,
            check=True,
        )
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=repo, check=True)
    subprocess.run(["git", "fetch", "origin"], cwd=repo, check=True)
    return repo


def test_branch_deletion_fails_closed_on_post_removal_worktree_path_lease(
    tmp_path,
) -> None:
    """A `worktree:<path>` lease claimed between `git worktree remove` and the
    branch deletion must stop the deletion.

    Pre-fix, the post-removal recheck passed only ``branch=...`` to
    ``authority_changed_for``, so a fresh path lease was invisible and the
    squash-merged branch was destroyed with ``git branch -D`` — an irreversible
    action taken without the required lease authority.
    """
    repo = _init_repo_with_merged_branch(
        tmp_path, branch="codex/candidate", squash=True
    )
    # Sanity: squash merge -> non-ancestor -> merged_pr proof -> `git branch -D`.
    assert git_hygiene._is_ancestor(repo, "codex/candidate", "origin/main") is False

    worktree = tmp_path / "candidate-wt"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/candidate"],
        cwd=repo,
        check=True,
    )
    lifecycle_records = {
        str(worktree.resolve()): {
            "path": str(worktree.resolve()),
            "branch": "codex/candidate",
            "generation": GENERATION,
            "owner": "prior-agent",
            "status": "complete",
            "registered_at": -20,
            "heartbeat_at": -10,
            "complete_at": 0,
            "expires_at": 0,
        }
    }
    lease = {"resource_id": f"worktree:{worktree.resolve()}", "expires_at": None}

    def load_active_leases() -> list[dict[str, object]]:
        # The new owner claims the path lease the moment the checkout is gone,
        # i.e. after `git worktree remove` and before the branch deletion.
        return [] if worktree.exists() else [dict(lease)]

    report = git_hygiene.janitor_apply(
        repo,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        active_lease_loader=load_active_leases,
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records=lifecycle_records,
    )

    assert report["ok"] is False
    assert not worktree.exists()
    # The irreversible branch deletion never ran and the branch survives.
    assert "codex/candidate" in git_hygiene._local_branches(repo)
    assert not any(
        action.get("command", [])[:2] == ["git", "branch"]
        for action in report["destructive_actions"]
    )
    assert any(
        error.get("reason") == "lease_authority_changed"
        and error.get("branch") == "codex/candidate"
        and lease["resource_id"] in error.get("active_leases", [])
        for error in report["errors"]
    )


def test_restart_cleanup_preserves_branch_with_active_former_worktree_path_lease(
    tmp_path,
    monkeypatch,
) -> None:
    """A second cleanup invocation still binds the branch to its former worktree
    path while that path lease is active.

    Pre-fix, once the first apply removed the checkout the branch was reclassified
    as an ordinary local branch: nothing associated ``codex/candidate`` with the
    leased path, so the restart deleted it with ``git branch -d`` and reported
    ``ok=true``. This runs the real registry, planner, and apply paths twice.
    """
    repo = _init_repo_with_merged_branch(
        tmp_path, branch="codex/candidate", squash=False
    )
    # Ancestor of origin/main -> an ordinary local-branch cleanup candidate once
    # the worktree is gone, which is exactly the restart hazard.
    assert git_hygiene._is_ancestor(repo, "codex/candidate", "origin/main") is True

    worktree = tmp_path / "candidate-wt"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/candidate"],
        cwd=repo,
        check=True,
    )
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="prior-agent",
        ttl_seconds=1,
        registry_path=registry_path,
        now=0.0,
    )
    lease = {"resource_id": f"worktree:{worktree.resolve()}", "expires_at": None}
    monkeypatch.setattr(
        agent_worktree,
        "_load_active_lease_snapshot",
        lambda _path: [] if worktree.exists() else [dict(lease)],
    )

    first = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert first["ok"] is False
    assert not worktree.exists()
    assert "codex/candidate" in git_hygiene._local_branches(repo)
    # The path->branch association survives the removal in the lifecycle registry.
    tombstone = agent_worktree.load_lifecycle_records(
        repo, registry_path=registry_path
    )[str(worktree.resolve())]
    assert tombstone["status"] == "removed"
    assert tombstone["path"] == str(worktree.resolve())
    assert tombstone["branch"] == "codex/candidate"

    second = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert second["ok"] is True, second["errors"]
    assert "codex/candidate" in git_hygiene._local_branches(repo)
    assert not any(
        action.get("artifact") == "local_branch"
        for action in second["destructive_actions"]
    )
    assert {
        "artifact": "local_branch",
        "name": "codex/candidate",
        "reason": "active_worktree_path_lease",
    } in second["skipped"]


# --- Anchor 4: path identity is case- and normalisation-robust (round-1 F1) ---


def _assert_post_removal_lease_spelling_blocks_delete(
    tmp_path: Path,
    *,
    worktree_name: str,
    lease_spelling: str,
) -> None:
    """Run the #4201 post-removal scenario with an alternate lease *spelling*.

    ``lease_spelling`` denotes the same directory as ``worktree_name`` on the
    case-insensitive, normalisation-insensitive filesystem this repo runs on by
    default (macOS APFS/HFS+). The contract asserted here is that the guard is
    not spelling-bound: an active ``worktree:<path>`` lease must block the
    irreversible ``git branch -D`` regardless of how the path is spelled.
    """
    repo = _init_repo_with_merged_branch(
        tmp_path, branch="codex/candidate", squash=True
    )
    # Squash merge -> non-ancestor -> merged_pr proof -> irreversible `branch -D`.
    assert git_hygiene._is_ancestor(repo, "codex/candidate", "origin/main") is False

    worktree = tmp_path / worktree_name
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/candidate"],
        cwd=repo,
        check=True,
    )
    lifecycle_records = {
        str(worktree.resolve()): {
            "path": str(worktree.resolve()),
            "branch": "codex/candidate",
            "generation": GENERATION,
            "owner": "prior-agent",
            "status": "complete",
            "registered_at": -20,
            "heartbeat_at": -10,
            "complete_at": 0,
            "expires_at": 0,
        }
    }
    leased_path = str(tmp_path / lease_spelling)
    assert leased_path != str(worktree)
    lease = {"resource_id": f"worktree:{leased_path}", "expires_at": None}

    def load_active_leases() -> list[dict[str, object]]:
        return [] if worktree.exists() else [dict(lease)]

    report = git_hygiene.janitor_apply(
        repo,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        active_lease_loader=load_active_leases,
        lifecycle_authority_guard=_allow_lifecycle_authority,
        lifecycle_records=lifecycle_records,
    )

    assert report["ok"] is False
    # The irreversible branch deletion never ran and the branch survives.
    assert "codex/candidate" in git_hygiene._local_branches(repo)
    assert not any(
        action.get("command", [])[:2] == ["git", "branch"]
        for action in report["destructive_actions"]
    )
    assert any(
        error.get("reason") == "lease_authority_changed"
        and error.get("branch") == "codex/candidate"
        and lease["resource_id"] in error.get("active_leases", [])
        for error in report["errors"]
    )


def test_branch_deletion_fails_closed_on_case_variant_worktree_path_lease(
    tmp_path,
) -> None:
    """A lease on the same directory spelled with different case must block.

    On the default macOS filesystem ``…/candidate-wt`` and ``…/CANDIDATE-WT``
    are the *identical* directory, so an exact-string path identity lets the
    janitor run ``git branch -D`` while the checkout's path is leased.
    """
    _assert_post_removal_lease_spelling_blocks_delete(
        tmp_path,
        worktree_name="candidate-wt",
        lease_spelling="CANDIDATE-WT",
    )


def test_branch_deletion_fails_closed_on_unicode_variant_worktree_path_lease(
    tmp_path,
) -> None:
    """A lease on the same directory in the other Unicode normal form must block.

    macOS filesystems are normalisation-insensitive, so the NFC and NFD
    spellings of a non-ASCII worktree path name the same directory.
    """
    composed = unicodedata.normalize("NFC", "kandidát-wt")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    _assert_post_removal_lease_spelling_blocks_delete(
        tmp_path,
        worktree_name=composed,
        lease_spelling=decomposed,
    )


# --- Anchor 5: absent lifecycle registry fails closed (round-1 F2) ---


def test_apply_fails_closed_when_lifecycle_registry_is_absent(
    tmp_path,
    monkeypatch,
) -> None:
    """Losing the registry file must preserve the branch, like corruption does.

    After the first apply tombstones the removed checkout, deleting
    ``agent-worktrees.json`` (operator cleanup, fresh clone, ``.git`` surgery)
    destroys the durable path->branch association. Absence used to be
    indistinguishable from "never registered", so the restart reclassified the
    branch as an ordinary cleanup candidate and deleted it with ``git branch -d``
    while its former path was still leased. A corrupt registry already fails
    closed; an absent one must too.
    """
    repo = _init_repo_with_merged_branch(
        tmp_path, branch="codex/candidate", squash=False
    )
    assert git_hygiene._is_ancestor(repo, "codex/candidate", "origin/main") is True

    worktree = tmp_path / "candidate-wt"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/candidate"],
        cwd=repo,
        check=True,
    )
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="prior-agent",
        ttl_seconds=1,
        registry_path=registry_path,
        now=0.0,
    )
    lease = {"resource_id": f"worktree:{worktree.resolve()}", "expires_at": None}
    monkeypatch.setattr(
        agent_worktree,
        "_load_active_lease_snapshot",
        lambda _path: [] if worktree.exists() else [dict(lease)],
    )

    first = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        lease_path=lease_path,
    )
    assert first["ok"] is False
    assert not worktree.exists()
    assert "codex/candidate" in git_hygiene._local_branches(repo)

    # The durable lifecycle state is lost between runs.
    registry_path.unlink()

    with pytest.raises(agent_worktree.WorktreeLifecycleError):
        agent_worktree.janitor_apply(
            repo,
            registry_path=registry_path,
            pr_states={"codex/candidate": {"state": "MERGED"}},
            lease_path=lease_path,
        )

    assert "codex/candidate" in git_hygiene._local_branches(repo)


def _reregister_path_for_other_branch(
    repo: Path,
    *,
    worktree: Path,
    registry_path: Path,
    branch: str,
) -> None:
    """A successor agent reuses the same worktree path for a different branch.

    This is the ordinary lifecycle sequence that used to destroy the tombstone:
    the registry is keyed by path, so registering ``branch`` at ``worktree``
    overwrote the record that bound the *previous* branch to that path.
    """
    subprocess.run(
        ["git", "branch", branch, "main"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "worktree", "add", str(worktree), branch],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="next-agent",
        ttl_seconds=100_000,
        registry_path=registry_path,
    )
    subprocess.run(
        ["git", "worktree", "remove", str(worktree)],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_branch_deletion_fails_closed_when_worktree_path_is_reregistered(
    tmp_path,
    monkeypatch,
) -> None:
    """Re-registering a tombstoned path must not strip the old branch's protection.

    Pre-fix, ``register_worktree`` replaced the whole record for that path, so the
    ``codex/candidate`` -> path binding vanished and the second apply deleted the
    branch with ``git branch -d`` while a ``worktree:<path>`` lease was still
    active. Runs the real registry, planner, and apply paths.
    """
    repo = _init_repo_with_merged_branch(
        tmp_path, branch="codex/candidate", squash=False
    )
    worktree = tmp_path / "candidate-wt"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/candidate"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="prior-agent",
        ttl_seconds=1,
        registry_path=registry_path,
        now=0.0,
    )
    lease = {"resource_id": f"worktree:{worktree.resolve()}", "expires_at": None}
    monkeypatch.setattr(
        agent_worktree,
        "_load_active_lease_snapshot",
        lambda _path: [] if worktree.exists() else [dict(lease)],
    )

    first = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/candidate": {"state": "MERGED"}},
        lease_path=lease_path,
    )
    assert first["ok"] is False
    assert not worktree.exists()
    assert "codex/candidate" in git_hygiene._local_branches(repo)

    _reregister_path_for_other_branch(
        repo,
        worktree=worktree,
        registry_path=registry_path,
        branch="codex/other",
    )

    second = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={
            "codex/candidate": {"state": "MERGED"},
            "codex/other": {"state": "MERGED"},
        },
        lease_path=lease_path,
    )

    assert "codex/candidate" in git_hygiene._local_branches(repo)
    assert not [
        action
        for action in second.get("destructive_actions", [])
        if action.get("command", [])[:2] == ["git", "branch"]
    ]
    assert any(
        entry.get("name") == "codex/candidate"
        and entry.get("reason") == "active_worktree_path_lease"
        for entry in second.get("skipped", [])
    )


def test_remote_branch_deletion_fails_closed_when_worktree_path_is_reregistered(
    tmp_path,
) -> None:
    """The remote-deletion path keeps the same carried path->branch association.

    ``_remote_branch_skip_reason`` resolves the worktree-path lease through the
    same lifecycle lookup as the local path, so a re-registered path must not
    strip ``active_worktree_path_lease`` from the remote candidate either.
    """
    records = {
        "/tmp/candidate-wt": {
            "path": "/tmp/candidate-wt",
            "branch": "codex/other",
            "status": "active",
            "prior_bindings": [{"branch": "codex/candidate", "removed_at": 1.0}],
        }
    }
    active_resources = {"worktree:/tmp/candidate-wt"}

    reason, needs_rescue = git_hygiene._remote_branch_skip_reason(
        "codex/candidate",
        current_branch="main",
        active_resources=active_resources,
        checked_out={},
        protected_branches={"main"},
        pr_states={"codex/candidate": {"state": "MERGED"}},
        lifecycle_records=records,
        cwd=tmp_path,
    )

    assert reason == "active_worktree_path_lease"
    assert needs_rescue is False
