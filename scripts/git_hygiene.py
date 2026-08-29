#!/usr/bin/env python3
"""
Git hygiene checks and cleanup for multi-agent repo workflows.
"""

from __future__ import annotations

import argparse
import hashlib
import datetime as dt
import json
import math
import os
import re
import subprocess
import time
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Mapping, TypeGuard


DEFAULT_PROTECTED_BRANCHES = {"main", "master", "develop", "dev", "stable"}
DEFAULT_REMOTE_POLICY = "merged-and-closed-with-rescue"
IN_PROGRESS_MARKERS = {
    "MERGE_HEAD": "merge",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
}


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run_git_result(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def run_git_check(args: list[str], cwd: Path) -> str:
    result = run_git_result(args, cwd)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["git", *args],
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout.strip()


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True)


def load_active_leases(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lease_is_active(lease: dict[str, Any], now: float | None = None) -> bool:
    expires_at = lease.get("expires_at")
    if expires_at is None:
        return True
    return float(expires_at) > (time.time() if now is None else now)


def lease_conflicts(
    leases: list[dict[str, Any]],
    resource_ids: set[str],
    execution_id: str | None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    conflicts = []
    for lease in leases:
        resource_id = str(lease.get("resource_id", ""))
        if resource_id not in resource_ids:
            continue
        if execution_id and lease.get("execution_id") == execution_id:
            continue
        if not lease_is_active(lease, now=now):
            continue
        conflicts.append(lease)
    return conflicts


def _git_dir(cwd: Path) -> Path:
    raw = run_git(["rev-parse", "--git-dir"], cwd)
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = cwd / git_dir
    return git_dir


def _in_progress_operations(cwd: Path) -> list[str]:
    git_dir = _git_dir(cwd)
    operations = [
        name for marker, name in IN_PROGRESS_MARKERS.items() if (git_dir / marker).exists()
    ]
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        operations.append("rebase")
    return sorted(operations)


def _base_branch_status(cwd: Path, base_branch: str | None) -> dict[str, Any]:
    if not base_branch:
        return {"base_branch": None, "remote_ref": None, "status": "not_checked", "mismatch": False}

    remote_ref = f"origin/{base_branch}"
    try:
        local_sha = run_git(["rev-parse", base_branch], cwd)
        remote_sha = run_git(["rev-parse", remote_ref], cwd)
    except subprocess.CalledProcessError as exc:
        return {
            "base_branch": base_branch,
            "remote_ref": remote_ref,
            "status": "unavailable",
            "mismatch": True,
            "error": str(exc),
        }

    head_contains_remote: bool | None = None
    if local_sha == remote_sha:
        status = "current"
    else:
        local_ancestor = _is_ancestor(cwd, base_branch, remote_ref)
        remote_ancestor = _is_ancestor(cwd, remote_ref, base_branch)
        if local_ancestor and not remote_ancestor:
            status = "behind"
            # A stale local base ref cannot be fast-forwarded from a dedicated
            # worktree while the base branch is checked out elsewhere. What the
            # publication boundary actually requires is that HEAD already
            # contains the remote head, so a stale local ref alone is advisory.
            head_contains_remote = _is_ancestor(cwd, remote_ref, "HEAD")
        elif remote_ancestor and not local_ancestor:
            status = "ahead"
        else:
            status = "diverged"
            # `main` is shared across worktrees. A concurrent root-worktree
            # task can legitimately leave that local ref diverged while this
            # dedicated publication branch already contains origin/main. The
            # remote base is the publish authority, so preserve the local
            # state as evidence but do not reject the isolated branch solely
            # because of that unrelated shared-ref drift.
            head_contains_remote = _is_ancestor(cwd, remote_ref, "HEAD")

    if status == "current":
        mismatch = False
    elif status == "behind":
        mismatch = not head_contains_remote
    else:
        mismatch = not head_contains_remote

    result: dict[str, Any] = {
        "base_branch": base_branch,
        "remote_ref": remote_ref,
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "status": status,
    }
    # Surface a distinct reason whenever a shared local base ref differs from
    # origin. The gate remains blocking unless this dedicated HEAD proves it
    # already contains the remote publication base.
    if status in {"behind", "diverged"}:
        if mismatch:
            result["reason"] = "rebase_required"
        elif status == "behind":
            result["reason"] = "advisory_stale_local_ref"
        else:
            result["reason"] = "advisory_diverged_local_base_ref"
    result["head_contains_remote"] = head_contains_remote
    result["mismatch"] = mismatch
    return result


def _is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    result = run_git_result(["merge-base", "--is-ancestor", ancestor, descendant], cwd)
    return result.returncode == 0


def in_shared_root(cwd: str | None = None) -> bool:
    """Return True when *cwd* is the PRIMARY (shared root) worktree.

    Detection: ``git rev-parse --git-dir`` and ``git rev-parse --git-common-dir``
    return the SAME path in the primary worktree and DIFFER in a linked worktree
    created by ``git worktree add``.  Both paths are normalised with
    ``Path.resolve()`` before comparison so relative outputs (e.g. ``.git``) and
    absolute outputs are treated identically.

    Returns False on any subprocess error rather than raising, so a missing or
    broken git repo is treated as "not the shared root" and never blocks the
    caller.
    """
    run_cwd = Path(cwd) if cwd is not None else Path.cwd()
    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=run_cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        common_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=run_cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return False
    if git_dir_result.returncode != 0 or common_dir_result.returncode != 0:
        return False
    raw_git = git_dir_result.stdout.strip()
    raw_common = common_dir_result.stdout.strip()
    if not raw_git or not raw_common:
        return False

    def _resolve(raw: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = run_cwd / p
        return p.resolve()

    return _resolve(raw_git) == _resolve(raw_common)


def preflight_report(
    cwd: Path,
    *,
    expected_branch: str | None = None,
    expected_worktree: str | None = None,
    base_branch: str | None = None,
    active_leases: list[dict[str, Any]] | None = None,
    resource_ids: set[str] | None = None,
    execution_id: str | None = None,
    allow_dirty: bool = False,
    now: float | None = None,
    require_dedicated_worktree: bool = False,
) -> dict[str, Any]:
    active_leases = active_leases or []
    resource_ids = resource_ids or set()
    status = run_git(["status", "--porcelain"], cwd)
    branch = run_git(["branch", "--show-current"], cwd)
    worktree = run_git(["rev-parse", "--show-toplevel"], cwd)
    operations = _in_progress_operations(cwd)
    conflicts = lease_conflicts(active_leases, resource_ids, execution_id, now=now)
    base_status = _base_branch_status(cwd, base_branch)

    shared_root = in_shared_root(str(cwd)) if require_dedicated_worktree else False

    checks = {
        "dirty_tree": bool(status),
        "dirty_tree_enforced": not allow_dirty,
        "in_progress_operations": operations,
        "branch": branch,
        "branch_mismatch": bool(expected_branch and branch != expected_branch),
        "worktree": worktree,
        "worktree_mismatch": bool(
            expected_worktree and Path(worktree).resolve() != Path(expected_worktree).resolve()
        ),
        "base_branch": base_status,
        "lease_conflicts": conflicts,
        "shared_root_worktree": shared_root,
    }
    ok = not (
        (checks["dirty_tree"] and not allow_dirty)
        or checks["in_progress_operations"]
        or checks["branch_mismatch"]
        or checks["worktree_mismatch"]
        or base_status["mismatch"]
        or checks["lease_conflicts"]
        or (require_dedicated_worktree and shared_root)
    )
    return {"ok": ok, "checks": checks}


def _parse_worktrees(output: str) -> list[dict[str, str]]:
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        worktrees.append(current)
    return worktrees


def _local_branches(cwd: Path) -> list[str]:
    output = run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _remote_branches(cwd: Path) -> list[str]:
    output = run_git(["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"], cwd)
    branches = []
    for line in output.splitlines():
        branch = line.strip()
        if not branch or branch in {"origin/HEAD", "origin"}:
            continue
        branch = branch.removeprefix("origin/")
        if branch == "HEAD":
            continue
        branches.append(branch)
    return branches


def load_pr_states_from_gh(cwd: Path) -> dict[str, dict[str, Any]]:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "500",
            "--json",
            "headRefName,state,isDraft,number,mergedAt,closedAt,updatedAt",
        ],
        cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh pr list failed")
    states: dict[str, dict[str, Any]] = {}
    for pr in json.loads(result.stdout or "[]"):
        branch = pr.get("headRefName")
        if branch:
            states[str(branch)] = pr
    return states


def _checked_out_branches(worktrees: list[dict[str, str]]) -> dict[str, str]:
    checked_out: dict[str, str] = {}
    for worktree in worktrees:
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        path = worktree.get("worktree")
        if branch and path:
            checked_out[branch] = path
    return checked_out


def _worktree_dirty(path: str) -> bool | None:
    try:
        result = run_git_result(["status", "--porcelain"], Path(path))
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _stash_epoch(line: str) -> int | None:
    match = re.search(r"(\d{10})", line)
    return int(match.group(1)) if match else None


def _stash_ref(line: str) -> str:
    return line.split(":", 1)[0]


def _current_stash_selector_for_sha(cwd: Path, sha: str) -> str | None:
    """Resolve which `stash@{N}` currently holds commit `sha`, or None.

    Uses a plain (no `--date`) listing so the returned selector is always a
    small positional index that `git stash drop` can act on directly. Called
    fresh immediately before every drop so a prior drop's renumbering of the
    stash reflog can never make this resolution stale.
    """
    listing = run_git(["stash", "list", "--format=%gd %H"], cwd)
    for entry in listing.splitlines():
        selector, _, entry_sha = entry.partition(" ")
        if entry_sha == sha:
            return selector
    return None


def _utc_stamp(now: float | None = None) -> str:
    value = dt.datetime.fromtimestamp(time.time() if now is None else now, tz=dt.UTC)
    return value.strftime("%Y%m%dT%H%M%SZ")


def _archive_ref(branch: str, now: float | None = None) -> str:
    safe_branch = branch.replace("/", "-")
    return f"refs/archive/git-hygiene/{_utc_stamp(now)}/{safe_branch}"


def _remote_ref_sha(cwd: Path, ref: str) -> str | None:
    """Return one exact remote ref value, or ``None`` only when it is absent."""
    result = run_git_result(["ls-remote", "--exit-code", "origin", ref], cwd)
    if result.returncode == 2:
        return None
    if result.returncode != 0:
        raise RuntimeError(f"remote_ref_read_failed:{ref}")
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) < 2 or rows[0][1] != ref:
        raise RuntimeError(f"remote_ref_read_ambiguous:{ref}")
    return rows[0][0]


def _targeted_remote_candidate(
    candidate: Mapping[str, Any], repository: str, cwd: Path
) -> dict[str, Any]:
    """Validate and canonicalise one deletion authority record.

    This deliberately does not infer identity from a janitor report: the caller
    supplies a bounded, reviewable disposition record and every field is part of
    the receipt digest used for retries.
    """
    required = {
        "repository", "source_ref", "source_sha", "archive_ref", "owner", "successor",
        "retention_class", "review_at", "discard", "authority",
    }
    if not required <= set(candidate) or candidate.get("repository") != repository:
        raise ValueError("candidate_identity_incomplete_or_wrong_repository")
    source_ref = candidate["source_ref"]
    archive_ref = candidate["archive_ref"]
    source_sha = candidate["source_sha"]
    if not all(isinstance(value, str) and value.strip() for value in (source_ref, archive_ref, source_sha, candidate["owner"], candidate["successor"], candidate["review_at"])) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", candidate["review_at"]):
        raise ValueError("candidate_identity_malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("candidate_source_sha_malformed")
    if (not source_ref.startswith("refs/heads/") or source_ref in {f"refs/heads/{name}" for name in DEFAULT_PROTECTED_BRANCHES} or not archive_ref.startswith("refs/archive/git-hygiene/")):
        raise ValueError("candidate_ref_protected_or_invalid")
    expected_archive = _targeted_archive_ref(repository, source_ref, source_sha)
    if archive_ref != expected_archive:
        raise ValueError("candidate_archive_ref_not_identity_derived")
    for ref in (source_ref, archive_ref):
        if run_git_result(["check-ref-format", ref], cwd).returncode != 0:
            raise ValueError("candidate_ref_malformed")
    issue = candidate.get("governing_issue")
    no_issue_lane = candidate.get("no_issue_lane")
    if (isinstance(issue, int)) == (isinstance(no_issue_lane, str) and bool(no_issue_lane.strip())):
        raise ValueError("candidate_issue_identity_ambiguous")
    if candidate["retention_class"] not in {"safety_archive", "quarantine"}:
        raise ValueError("candidate_retention_invalid")
    discard = candidate["discard"]
    if not isinstance(discard, Mapping) or discard.get("state") != "retain" or discard.get("receipt") is not None:
        raise ValueError("candidate_discard_state_not_explicit_retain")
    authority = candidate["authority"]
    if not isinstance(authority, Mapping) or authority.get("repository") != repository or authority.get("lease_conflicts") or authority.get("lifecycle_conflicts"):
        raise ValueError("candidate_destructive_authority_invalid")
    protected_heads = authority.get("protected_pr_heads")
    if not isinstance(protected_heads, Mapping) or not {"4728", "4813"} <= set(protected_heads):
        raise ValueError("candidate_protected_pr_authority_missing")
    if source_sha in set(protected_heads.values()):
        raise ValueError("candidate_source_is_live_protected_pr_head")
    return {key: candidate.get(key) for key in sorted(required | {"governing_issue", "no_issue_lane"})}


def _targeted_archive_ref(repository: str, source_ref: str, source_sha: str) -> str:
    seed = f"{repository}\0{source_ref}\0{source_sha}".encode()
    return f"refs/archive/git-hygiene/identity/{hashlib.sha256(seed).hexdigest()}"


def _canonical_origin(cwd: Path) -> str:
    result = run_git_result(["remote", "get-url", "origin"], cwd)
    if result.returncode != 0:
        raise RuntimeError("canonical_origin_unavailable")
    raw = result.stdout.strip().removesuffix(".git")
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+)", raw)
    if not match:
        raise RuntimeError("canonical_origin_invalid")
    return match.group(1)


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    """Durably replace one receipt; completed is monotonic at the caller."""
    payload = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def targeted_remote_cleanup(
    cwd: Path,
    *,
    repository: str,
    candidates: list[Mapping[str, Any]],
    receipt_dir: Path,
    receipt_writer: Callable[[Path, Mapping[str, Any]], None] = _write_receipt,
) -> dict[str, Any]:
    """Archive then CAS-delete no more than five explicitly bound remote refs.

    The function is intentionally not wired into broad ``janitor --apply``.
    It is the only production entrypoint for this targeted mechanism; callers
    must separately establish lifecycle/lease/GitHub authority before invoking it.
    """
    if not 1 <= len(candidates) <= 5:
        return {"ok": False, "completed": [], "error": "candidate_batch_size_invalid"}
    if _canonical_origin(cwd) != repository:
        return {"ok": False, "completed": [], "error": "canonical_origin_mismatch"}
    receipt_dir.mkdir(parents=True, exist_ok=True)
    completed: list[dict[str, Any]] = []
    validated: list[tuple[dict[str, Any], str]] = []
    try:
        for raw in candidates:
            candidate = _targeted_remote_candidate(raw, repository, cwd)
            identity = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
            validated.append((candidate, hashlib.sha256(identity.encode()).hexdigest()))
        archive_owners = {candidate["archive_ref"]: receipt_id for candidate, receipt_id in validated}
        if len(archive_owners) != len(validated):
            raise ValueError("candidate_archive_namespace_collision")
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "completed": [], "error": str(exc)}
    for candidate, receipt_id in validated:
        try:
            receipt_path = receipt_dir / f"{receipt_id}.json"
            lock_path = receipt_dir / f"{receipt_id}.lock"
            try:
                lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise RuntimeError("receipt_ownership_busy")
            receipt = {"version": 1, "identity": candidate, "receipt_id": receipt_id, "state": "prepared"}
            try:
                if receipt_path.exists():
                    existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if existing.get("identity") != candidate or existing.get("receipt_id") != receipt_id or existing.get("state") not in {"prepared", "completed"}:
                        raise RuntimeError("receipt_identity_or_state_conflict")
                    receipt = existing
                source_sha = _remote_ref_sha(cwd, candidate["source_ref"])
                archive_sha = _remote_ref_sha(cwd, candidate["archive_ref"])
                if receipt["state"] == "completed":
                    if source_sha is not None or archive_sha != candidate["source_sha"]:
                        raise RuntimeError("completed_receipt_live_state_conflict")
                    completed.append({"receipt": str(receipt_path), "state": "completed", **candidate})
                    continue
                if archive_sha is None:
                    if source_sha != candidate["source_sha"]:
                        raise RuntimeError("source_identity_drift_before_archive")
                    pushed = run_git_result(["push", "--no-verify", "origin", f"{source_sha}:{candidate['archive_ref']}"], cwd)
                    if pushed.returncode != 0:
                        raise RuntimeError("archive_push_failed")
                    archive_sha = _remote_ref_sha(cwd, candidate["archive_ref"])
                if archive_sha != candidate["source_sha"]:
                    raise RuntimeError("archive_sha_mismatch")
                receipt_writer(receipt_path, receipt)
                if source_sha is None:
                    # A durable matching prepared record plus exact archive and
                    # source absence is the only crash-recovery completion path.
                    receipt["state"] = "completed"
                    receipt_writer(receipt_path, receipt)
                    completed.append({"receipt": str(receipt_path), "state": "completed", **candidate})
                    continue
                if source_sha != candidate["source_sha"]:
                    raise RuntimeError("source_identity_drift_before_delete")
                deleted = run_git_result(["push", "--no-verify", f"--force-with-lease={candidate['source_ref']}:{source_sha}", "origin", f":{candidate['source_ref']}"], cwd)
                if deleted.returncode != 0:
                    raise RuntimeError("source_cas_delete_failed")
                if _remote_ref_sha(cwd, candidate["source_ref"]) is not None or _remote_ref_sha(cwd, candidate["archive_ref"]) != candidate["source_sha"]:
                    raise RuntimeError("post_delete_readback_failed")
                receipt["state"] = "completed"
                receipt_writer(receipt_path, receipt)
                completed.append({"receipt": str(receipt_path), "state": "completed", **candidate})
            finally:
                os.close(lock_fd)
                lock_path.unlink(missing_ok=True)
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            return {"ok": False, "completed": completed, "error": str(exc)}
    return {"ok": True, "completed": completed}


def _pr_state(branch: str, pr_states: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    if pr_states is None:
        return {"state": "none"}
    return pr_states.get(branch, {"state": "unknown"})


def _branch_has_active_lease(branch: str, active_resources: set[str]) -> bool:
    return f"branch:{branch}" in active_resources


def _canonical_path_key(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _folded_path_key(path: str) -> str:
    """Case- and normalisation-insensitive identity for a filesystem path.

    Kept in its own ``casefold:`` namespace so it can only ever match another
    folded identity — an exact spelling never collides with a folded one.
    """
    return "casefold:" + unicodedata.normalize("NFC", path).casefold()


def _path_identities(path: str | None) -> set[str]:
    """Every spelling that can denote the same worktree directory.

    Lease matching must not be spelling-bound. Besides the raw and canonical
    (``resolve()``d) spellings, each is also emitted in a case-folded, NFC
    normalised form, because the filesystem this repo runs on by default (macOS
    APFS/HFS+) is case-insensitive *and* normalisation-insensitive:
    ``…/candidate-wt``, ``…/CANDIDATE-WT`` and the NFD spelling of a non-ASCII
    path are the identical directory there, and ``os.path.normcase`` is a no-op
    on POSIX so it cannot express this. The directory is already gone by the
    time the branch deletion is revalidated, so the filesystem cannot be probed
    for its actual case sensitivity at that point.

    On a genuinely case-sensitive filesystem those spellings are different
    directories and the folded identity can over-match. That is deliberate:
    every consumer uses these identities as a *preservation* predicate, so an
    over-match at worst preserves a branch that could have been reclaimed, while
    an under-match runs an irreversible ``git branch -D`` against a directory
    somebody holds a lease on. The asymmetry is not close, and the collision it
    costs requires two live agent worktree paths differing only by case or
    Unicode form.
    """
    if not path:
        return set()
    spellings = {path, _canonical_path_key(path)}
    return spellings | {_folded_path_key(spelling) for spelling in spellings}


def _leased_worktree_paths(active_resources: set[str]) -> set[str]:
    paths: set[str] = set()
    for resource in active_resources:
        if not resource.startswith("worktree:"):
            continue
        paths |= _path_identities(resource.removeprefix("worktree:"))
    return paths


def _worktree_path_has_active_lease(path: str, active_resources: set[str]) -> bool:
    return bool(_path_identities(path) & _leased_worktree_paths(active_resources))


def _lifecycle_worktree_paths_for_branch(
    branch: str | None,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
) -> set[str]:
    """Every worktree path a lifecycle record binds to ``branch``.

    Records survive the checkout they describe: removal only tombstones them
    (``status == "removed"``), it never drops the path/branch pair. That durable
    association is what lets a later cleanup run — after the checkout is gone and
    the branch looks like an ordinary local branch — still recognise a
    ``worktree:<path>`` lease as authority over the branch that path held.

    The registry is keyed by path, so reusing a path for a new branch replaces
    the record that held it. `agent_worktree.register_worktree` carries the
    displaced binding forward in ``prior_bindings``, and those are read here so
    the former branch keeps that path's lease authority across the reuse.

    That carry is bounded: ``agent_worktree.MAX_PRIOR_BINDINGS`` (8) most-recent
    bindings, deduplicated by branch. A branch displaced further back than that
    from the same canonical path is not returned here and is therefore not
    preserved by a ``worktree:<path>`` lease, so this is not an unconditional
    guarantee across unlimited reuse of one path.
    """
    if not branch or lifecycle_records is None:
        return set()
    paths: set[str] = set()
    for key, record in lifecycle_records.items():
        if not isinstance(record, Mapping):
            continue
        if record.get("branch") != branch and not _record_previously_bound(
            record, branch
        ):
            continue
        paths |= _path_identities(key)
        recorded_path = record.get("path")
        if isinstance(recorded_path, str):
            paths |= _path_identities(recorded_path)
    return paths


def _record_previously_bound(record: Mapping[str, Any], branch: str) -> bool:
    """True when ``record``'s path held ``branch`` before it was re-registered."""
    prior = record.get("prior_bindings")
    if not isinstance(prior, list):
        return False
    return any(
        isinstance(entry, Mapping) and entry.get("branch") == branch
        for entry in prior
    )


def _branch_has_worktree_path_lease(
    branch: str,
    active_resources: set[str],
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
) -> bool:
    """True when an active lease holds a worktree path bound to ``branch``."""
    return bool(
        _lifecycle_worktree_paths_for_branch(branch, lifecycle_records)
        & _leased_worktree_paths(active_resources)
    )


def _branch_has_lifecycle_preservation(
    branch: str,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
) -> bool:
    if lifecycle_records is None:
        return False
    return any(
        isinstance(record, Mapping)
        and record.get("branch") == branch
        and record.get("status") != "removed"
        for record in lifecycle_records.values()
    )


def _is_finite_timestamp(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _worktree_lifecycle_skip_reason(
    path: str,
    branch: str,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
    *,
    now: float | None,
) -> str | None:
    """Require a matching expired lifecycle registration when records are supplied."""

    if lifecycle_records is None:
        return None
    canonical_path = str(Path(path).resolve())
    record = lifecycle_records.get(canonical_path)
    if not isinstance(record, Mapping):
        return "unregistered_worktree"
    owner = record.get("owner")
    registered_at = record.get("registered_at")
    heartbeat_at = record.get("heartbeat_at")
    expires_at = record.get("expires_at")
    generation = record.get("generation")
    status = record.get("status")
    if (
        record.get("path") != canonical_path
        or record.get("branch") != branch
        or not isinstance(owner, str)
        or not owner.strip()
        or not (
            isinstance(generation, str)
            and re.fullmatch(r"[0-9a-f]{32}", generation)
        )
        or status not in {"active", "released", "complete"}
        or not _is_finite_timestamp(registered_at)
        or not _is_finite_timestamp(heartbeat_at)
        or not _is_finite_timestamp(expires_at)
        or registered_at > heartbeat_at
        or heartbeat_at > expires_at
    ):
        return "registration_mismatch"
    if status in {"released", "complete"}:
        terminal_at = record.get(f"{status}_at")
        if (
            not _is_finite_timestamp(terminal_at)
            or terminal_at != expires_at
        ):
            return "registration_mismatch"
    if expires_at > (time.time() if now is None else now):
        return "active_registration"
    return None


def _worktree_reclaim_reason(
    path: str,
    branch: str,
    *,
    current_worktree: str,
    active_resources: set[str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    cwd: Path,
    locked: bool = False,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None = None,
    now: float | None = None,
) -> tuple[str | None, str | None]:
    """Decide whether a present worktree is safe to reclaim.

    Returns ``(skip_reason, merge_proof)`` where exactly one element is set:

    - reclaimable -> ``(None, merge_proof)`` with ``merge_proof`` one of
      ``ancestor_of_origin_main``, ``merged_pr``, ``closed_pr``.
    - not reclaimable -> ``(reason, None)``.

    Candidacy gates on **merge state, not branch prefix**: any clean, non-root,
    non-lease, non-open-PR worktree whose branch is an ancestor of ``origin/main``
    OR has a merged/closed PR is reclaimable. Squash-merged branches are not
    ancestors, so PR state is required to catch them.

    Protected branches (``stable``/``develop``/etc.) are never reclaimed even
    when checked out in a non-root worktree: reclaiming would ``git branch -d``
    the protected ref and bypass the same protections the local/remote branch
    cleanup already honours.
    """
    if Path(path).resolve() == Path(current_worktree).resolve():
        return "root_worktree", None
    if branch in protected_branches:
        return "protected_branch", None
    # `git worktree list --porcelain` exposes a `locked` record for worktrees
    # guarded by another tool or session.  A lock is positive preservation
    # evidence, not stale metadata: never make it a removal candidate.
    if locked:
        return "locked_worktree", None
    if _worktree_path_has_active_lease(path, active_resources) or _branch_has_active_lease(
        branch, active_resources
    ):
        return "active_lease", None
    dirty = _worktree_dirty(path)
    if dirty is None:
        return "worktree_state_unavailable", None
    if dirty:
        return "dirty_worktree", None
    lifecycle_reason = _worktree_lifecycle_skip_reason(
        path,
        branch,
        lifecycle_records,
        now=now,
    )
    if lifecycle_reason is not None:
        return lifecycle_reason, None
    pr = _pr_state(branch, pr_states)
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr", None
    if _is_ancestor(cwd, branch, "origin/main"):
        return None, "ancestor_of_origin_main"
    if pr.get("state") == "MERGED":
        return None, "merged_pr"
    if pr.get("state") == "CLOSED":
        return None, "closed_pr"
    # Clean but not provably merged/closed: hold back for manual review rather
    # than reclaim. Covers unknown PR state (pr_states given but branch absent)
    # and the report-mode case where PR state was not resolved.
    return "unknown_merge_state", None


def _local_branch_skip_reason(
    branch: str,
    *,
    current_branch: str,
    active_resources: set[str],
    checked_out: dict[str, str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
    cwd: Path,
) -> str | None:
    if branch == current_branch:
        return "current_branch"
    if branch in protected_branches:
        return "protected_branch"
    if _branch_has_active_lease(branch, active_resources):
        return "active_lease"
    # A branch whose worktree the janitor already removed still belongs to the
    # holder of that path lease: the removal tombstone keeps the path->branch
    # association so the restart cannot reclassify it as an ordinary branch.
    if _branch_has_worktree_path_lease(branch, active_resources, lifecycle_records):
        return "active_worktree_path_lease"
    if _branch_has_lifecycle_preservation(branch, lifecycle_records):
        return "lifecycle_registration"
    pr = _pr_state(branch, pr_states)
    if pr["state"] == "unknown":
        return "unknown_github_state"
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr"
    if branch in checked_out:
        dirty = _worktree_dirty(checked_out[branch])
        if dirty is None:
            return "worktree_state_unavailable"
        if dirty:
            return "dirty_worktree"
        return "checked_out_worktree"
    if not _is_ancestor(cwd, branch, "origin/main"):
        return "not_merged_to_origin_main"
    return None


def _remote_branch_skip_reason(
    branch: str,
    *,
    current_branch: str,
    active_resources: set[str],
    checked_out: dict[str, str],
    protected_branches: set[str],
    pr_states: dict[str, dict[str, Any]] | None,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None,
    cwd: Path,
) -> tuple[str | None, bool]:
    if branch == current_branch:
        return "current_branch", False
    if branch in protected_branches:
        return "protected_branch", False
    if _branch_has_active_lease(branch, active_resources):
        return "active_lease", False
    if _branch_has_worktree_path_lease(branch, active_resources, lifecycle_records):
        return "active_worktree_path_lease", False
    if _branch_has_lifecycle_preservation(branch, lifecycle_records):
        return "lifecycle_registration", False
    if branch in checked_out:
        dirty = _worktree_dirty(checked_out[branch])
        if dirty is None:
            return "worktree_state_unavailable", False
        if dirty:
            return "dirty_worktree", False
    pr = _pr_state(branch, pr_states)
    if pr["state"] == "unknown":
        return "unknown_github_state", False
    if pr.get("state") == "OPEN" or pr.get("isDraft"):
        return "open_or_draft_pr", False
    merged = _is_ancestor(cwd, f"origin/{branch}", "origin/main")
    if merged:
        return None, False
    if pr.get("state") in {"CLOSED", "MERGED"}:
        return None, True
    if pr.get("state") == "none":
        return "remote_not_merged_without_pr", False
    return "remote_not_safe", False


def _lease_resources(active_leases: list[dict[str, Any]], now: float | None = None) -> set[str]:
    return {
        str(lease.get("resource_id"))
        for lease in active_leases
        if lease.get("resource_id") and lease_is_active(lease, now=now)
    }


PRESERVATION_REASONS = {
    "active_lease",
    "active_registration",
    "dirty_worktree",
    "locked_worktree",
    "registration_mismatch",
    "orphaned_worktree_report_only",
    "unregistered_worktree",
    "unknown_merge_state",
    "worktree_state_unavailable",
}


def _preservation_receipt(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return an operator-readable receipt for non-destructive holds."""
    reason = item.get("reason")
    if item.get("artifact") != "worktree" or reason not in PRESERVATION_REASONS:
        return None
    next_action = {
        "active_lease": "wait for the owning agent to release or supersede its lease",
        "active_registration": "wait for lifecycle expiry or an explicit release/complete receipt",
        "dirty_worktree": "preserve local drift; inspect or commit it before any cleanup",
        "locked_worktree": "preserve the lock; verify the owning session before any cleanup",
        "registration_mismatch": "repair the lifecycle record; do not infer cleanup authority",
        "orphaned_worktree_report_only": "inspect and prune missing worktree metadata manually",
        "unregistered_worktree": "register ownership explicitly before any cleanup decision",
        "unknown_merge_state": "verify merge and ownership state before any cleanup",
        "worktree_state_unavailable": "restore or inspect the worktree; do not infer abandonment",
    }[reason]
    return {
        "artifact": "worktree",
        "path": item["path"],
        "branch": item.get("branch", ""),
        "reason": reason,
        "action": "preserve",
        "next_action": next_action,
    }


def build_janitor_plan(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    remote_policy: str = DEFAULT_REMOTE_POLICY,
    pr_states: dict[str, dict[str, Any]] | None = None,
    protected_branches: set[str] | None = None,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    protected = protected_branches or DEFAULT_PROTECTED_BRANCHES
    active_resources = _lease_resources(active_leases, now=now)
    current_branch = run_git(["branch", "--show-current"], cwd)
    current_worktree = run_git(["rev-parse", "--show-toplevel"], cwd)
    worktrees = _parse_worktrees(run_git(["worktree", "list", "--porcelain"], cwd))
    checked_out = _checked_out_branches(worktrees)

    skipped: list[dict[str, Any]] = []
    preservation_receipts: list[dict[str, Any]] = []
    local_branches = []
    for branch in _local_branches(cwd):
        reason = _local_branch_skip_reason(
            branch,
            current_branch=current_branch,
            active_resources=active_resources,
            checked_out=checked_out,
            protected_branches=protected,
            pr_states=pr_states,
            lifecycle_records=lifecycle_records,
            cwd=cwd,
        )
        if reason:
            skipped.append({"artifact": "local_branch", "name": branch, "reason": reason})
            continue
        local_branches.append({"branch": branch})

    reclaimable_worktrees = []
    orphaned_worktrees = []
    for worktree in worktrees:
        path = worktree.get("worktree")
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        if not path:
            continue
        is_root = Path(path).resolve() == Path(current_worktree).resolve()
        leased = _worktree_path_has_active_lease(
            path, active_resources
        ) or _branch_has_active_lease(branch, active_resources)
        locked = "locked" in worktree
        # A missing worktree is an orphan (its metadata is pruned, not reclaimed)
        # — but the root is never missing, and active leases or locks still win
        # so we never touch protected work even if its checkout has gone.
        if not is_root and not Path(path).exists():
            if locked:
                reason = "locked_worktree"
            elif leased:
                reason = "active_lease"
            else:
                reason = _worktree_lifecycle_skip_reason(
                    path,
                    branch,
                    lifecycle_records,
                    now=now,
                )
            if reason is not None:
                item = {
                    "artifact": "worktree",
                    "path": path,
                    "branch": branch,
                    "reason": reason,
                }
                skipped.append(item)
                receipt = _preservation_receipt(item)
                if receipt:
                    preservation_receipts.append(receipt)
            else:
                orphaned_worktrees.append({"path": path, "branch": branch})
                item = {
                    "artifact": "worktree",
                    "path": path,
                    "branch": branch,
                    "reason": "orphaned_worktree_report_only",
                }
                skipped.append(item)
                receipt = _preservation_receipt(item)
                if receipt:
                    preservation_receipts.append(receipt)
            continue
        # Candidacy gates on merge state, not branch prefix.
        reason, merge_proof = _worktree_reclaim_reason(
            path,
            branch,
            current_worktree=current_worktree,
            active_resources=active_resources,
            protected_branches=protected,
            pr_states=pr_states,
            cwd=cwd,
            locked=locked,
            lifecycle_records=lifecycle_records,
            now=now,
        )
        if reason:
            item = {"artifact": "worktree", "path": path, "branch": branch, "reason": reason}
            skipped.append(item)
            receipt = _preservation_receipt(item)
            if receipt:
                preservation_receipts.append(receipt)
            continue
        reclaimable_worktrees.append(
            {
                "path": path,
                "branch": branch,
                "head": worktree.get("HEAD", ""),
                "merge_proof": merge_proof,
            }
        )

    remote_branches = []
    rescue_remote_branches = []
    for branch in _remote_branches(cwd):
        reason, needs_rescue = _remote_branch_skip_reason(
            branch,
            current_branch=current_branch,
            active_resources=active_resources,
            checked_out=checked_out,
            protected_branches=protected,
            pr_states=pr_states,
            lifecycle_records=lifecycle_records,
            cwd=cwd,
        )
        if reason:
            skipped.append({"artifact": "remote_branch", "name": branch, "reason": reason})
            continue
        if needs_rescue and remote_policy != DEFAULT_REMOTE_POLICY:
            skipped.append({"artifact": "remote_branch", "name": branch, "reason": "remote_policy_disallows_rescue"})
            continue
        candidate = {"branch": branch}
        if needs_rescue:
            candidate["rescue_ref"] = _archive_ref(branch, now=now)
            rescue_remote_branches.append(candidate)
        else:
            remote_branches.append(candidate)

    cutoff = (time.time() if now is None else now) - stale_after_days * 24 * 60 * 60
    old_stashes = []
    stash_output = run_git(["stash", "list", "--date=unix"], cwd)
    stash_lines = stash_output.splitlines()
    candidate_rows: list[tuple[int, str]] = []
    for index, line in enumerate(stash_lines):
        epoch = _stash_epoch(line)
        if epoch and epoch < cutoff and "preserve-local-drift" in line:
            candidate_rows.append((index, line))
        elif epoch and epoch < cutoff:
            skipped.append({"artifact": "stash", "name": _stash_ref(line), "reason": "missing_preserve_local_drift_marker"})
    if candidate_rows:
        # A companion plain listing (no --date), taken immediately after this
        # scan with no intervening mutation, recovers each candidate's stable
        # commit hash by position. `_stash_ref(line)` (the `--date=unix`
        # selector) must never be treated as that identity: it is a
        # positional index that a prior drop in the same apply run
        # renumbers, and with `--date` applied git can additionally fold
        # several entries pushed within the same second into one rendered
        # selector, so it cannot even be resolved back to a specific reflog
        # position on its own. `janitor_apply` re-resolves this hash to
        # whatever position currently holds it immediately before every
        # drop, instead of trusting any positional selector.
        stash_shas = run_git(["stash", "list", "--format=%H"], cwd).splitlines()
        for index, line in candidate_rows:
            sha = stash_shas[index] if index < len(stash_shas) else None
            old_stashes.append({"ref": _stash_ref(line), "line": line, "sha": sha})

    prune_candidates = {
        "worktree": run_git(["worktree", "prune", "--dry-run"], cwd).splitlines(),
        "remote": run_git(["remote", "prune", "origin", "--dry-run"], cwd).splitlines(),
    }
    return {
        "mode": "report",
        "remote_policy": remote_policy,
        "destructive_actions": [],
        "candidates": {
            "local_branches": local_branches,
            "worktrees": reclaimable_worktrees,
            "orphaned_worktrees": orphaned_worktrees,
            "remote_branches": remote_branches,
            "remote_branches_requiring_rescue": rescue_remote_branches,
            "old_stashes": old_stashes,
        },
        # Top-level reclaim view: present-but-merged worktrees that are safe to
        # reclaim (with the proof that qualified each), kept distinct from
        # orphaned_worktrees (missing checkouts handled by `worktree prune`).
        "reclaimable_worktrees": reclaimable_worktrees,
        "orphaned_worktrees": orphaned_worktrees,
        "skipped": skipped,
        "prune_candidates": prune_candidates,
        "active_leases_respected": sorted(active_resources),
        "preservation_receipts": preservation_receipts,
    }


def janitor_report(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    active_leases = active_leases or []
    plan = build_janitor_plan(
        cwd,
        active_leases=active_leases,
        stale_after_days=stale_after_days,
        pr_states=None,
        lifecycle_records=lifecycle_records,
        now=now,
    )
    plan["mode"] = "report-only"
    plan["stale_merged_branches"] = [item["branch"] for item in plan["candidates"]["local_branches"]]
    plan["reclaimable_worktrees"] = plan["candidates"]["worktrees"]
    plan["orphaned_worktrees"] = plan["candidates"]["orphaned_worktrees"]
    plan["old_stashes"] = [item["line"] for item in plan["candidates"]["old_stashes"]]
    return plan


def janitor_apply(
    cwd: Path,
    *,
    active_leases: list[dict[str, Any]] | None = None,
    stale_after_days: int = 14,
    remote_policy: str = DEFAULT_REMOTE_POLICY,
    pr_states: dict[str, dict[str, Any]] | None = None,
    lifecycle_records: Mapping[str, Mapping[str, Any]] | None = None,
    active_lease_loader: Callable[[], list[dict[str, Any]]] | None = None,
    lifecycle_authority_guard: Callable[
        [list[dict[str, Any]]], AbstractContextManager[Callable[[], None]]
    ]
    | None = None,
    target_worktree: str | None = None,
    target_branch: str | None = None,
    branch_lifecycle_authority_guard: Callable[
        [dict[str, Any]], AbstractContextManager[None]
    ]
    | None = None,
) -> dict[str, Any]:
    actions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if pr_states is None:
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "github_state",
                    "action": "load_pr_states",
                    "reason": "apply_requires_pr_state_file",
                }
            ],
        }
    if active_lease_loader is None:
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "lease_snapshot",
                    "action": "reload_active_leases",
                    "reason": "authoritative_lease_reload_required",
                }
            ],
        }
    if lifecycle_records is None:
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "worktree",
                    "action": "load_lifecycle_registry",
                    "reason": "registered_lifecycle_guard_required",
                }
            ],
        }
    if lifecycle_authority_guard is None:
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "worktree",
                    "action": "revalidate_lifecycle_registry",
                    "reason": "authoritative_lifecycle_revalidation_required",
                }
            ],
        }
    if target_branch is not None and (
        target_worktree is None or branch_lifecycle_authority_guard is None
    ):
        return {
            "mode": "apply",
            "ok": False,
            "destructive_actions": [],
            "errors": [
                {
                    "artifact": "worktree",
                    "action": "revalidate_lifecycle_registry",
                    "reason": "targeted_branch_lifecycle_guard_required",
                }
            ],
        }

    def apply_git(args: list[str], action: dict[str, Any]) -> bool:
        result = run_git_result(args, cwd)
        record = {**action, "command": ["git", *args], "returncode": result.returncode}
        if result.stdout.strip():
            record["stdout"] = result.stdout.strip()
        if result.stderr.strip():
            record["stderr"] = result.stderr.strip()
        if result.returncode == 0:
            actions.append(record)
            return True
        else:
            errors.append(record)
            return False

    apply_git(["fetch", "--prune", "origin"], {"artifact": "remote", "action": "fetch_prune"})
    if errors:
        return {
            "mode": "apply",
            "destructive_actions": actions,
            "errors": errors,
            "ok": False,
        }

    def reload_active_leases() -> tuple[list[dict[str, Any]], set[str]] | None:
        try:
            leases = active_lease_loader()
            if not isinstance(leases, list) or any(
                not isinstance(item, dict) for item in leases
            ):
                raise TypeError("active lease authority must be a list of objects")
            for lease in leases:
                resource_id = lease.get("resource_id")
                expires_at = lease.get("expires_at")
                if not isinstance(resource_id, str) or not resource_id.strip():
                    raise ValueError("active lease resource identity is invalid")
                if expires_at is not None and not _is_finite_timestamp(expires_at):
                    raise ValueError("active lease expiry is invalid")
            resources = _lease_resources(leases)
        except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
            errors.append(
                {
                    "artifact": "lease_snapshot",
                    "action": "reload_active_leases",
                    "reason": "active_lease_authority_invalid",
                }
            )
            return None
        return leases, resources

    initial_authority = reload_active_leases()
    if initial_authority is None:
        return {
            "mode": "apply",
            "destructive_actions": actions,
            "errors": errors,
            "ok": False,
        }
    active_leases, _ = initial_authority
    plan = build_janitor_plan(
        cwd,
        active_leases=active_leases,
        stale_after_days=stale_after_days,
        remote_policy=remote_policy,
        pr_states=pr_states,
        lifecycle_records=lifecycle_records,
    )

    if target_worktree is not None:
        target_path = str(Path(target_worktree).resolve(strict=False))
        reclaimable = plan.get("reclaimable_worktrees", plan["candidates"]["worktrees"])
        selected = [
            worktree
            for worktree in reclaimable
            if str(Path(str(worktree.get("path", ""))).resolve(strict=False))
            == target_path
        ]
        selected_branches = [
            {**branch, "merge_proof": "ancestor_of_origin_main"}
            for branch in plan["candidates"]["local_branches"]
            if branch.get("branch") == target_branch
        ]
        if target_branch is not None and not selected_branches:
            skipped_reason = next(
                (
                    item.get("reason")
                    for item in plan["skipped"]
                    if item.get("artifact") == "local_branch"
                    and item.get("name") == target_branch
                ),
                None,
            )
            pr = _pr_state(target_branch, pr_states)
            pr_state = pr.get("state")
            merged_head = pr.get("head_sha")
            current_head = run_git(["rev-parse", target_branch], cwd)
            if (
                skipped_reason == "not_merged_to_origin_main"
                and pr_state == "MERGED"
                and isinstance(merged_head, str)
                and merged_head == current_head
            ):
                selected_branches = [
                    {
                        "branch": target_branch,
                        "merge_proof": "merged_pr",
                        "merged_pr_head": merged_head,
                    }
                ]
        if target_branch is None and len(selected) != 1:
            return {
                **plan,
                "mode": "apply",
                "targeted_cleanup": {"worktree": target_path},
                "destructive_actions": actions,
                "errors": [
                    {
                        "artifact": "worktree",
                        "action": "select_target",
                        "reason": "target_not_exactly_one_reclaimable_worktree",
                        "path": target_path,
                    }
                ],
                "ok": False,
            }
        if target_branch is not None and len(selected_branches) != 1:
            return {
                **plan,
                "mode": "apply",
                "targeted_cleanup": {"worktree": target_path, "branch": target_branch},
                "destructive_actions": actions,
                "errors": [
                    {
                        "artifact": "local_branch",
                        "action": "select_target",
                        "reason": "target_not_exactly_one_reclaimable_tombstone_branch",
                        "path": target_path,
                        "branch": target_branch,
                    }
                ],
                "ok": False,
            }
        # A targeted operation is intentionally narrower than the global janitor:
        # preserve evidence and candidates belonging to other artifacts must not
        # block it, but neither may they become eligible for mutation.
        plan = {
            **plan,
            "candidates": {
                **plan["candidates"],
                "local_branches": selected_branches,
                "worktrees": selected if target_branch is None else [],
                "orphaned_worktrees": [],
                "remote_branches": [],
                "remote_branches_requiring_rescue": [],
                "old_stashes": [],
            },
            "reclaimable_worktrees": selected if target_branch is None else [],
            "orphaned_worktrees": [],
            "prune_candidates": {"worktree": [], "remote": []},
            "preservation_receipts": [],
            "targeted_cleanup": (
                {"worktree": target_path, "branch": target_branch}
                if target_branch is not None
                else {"worktree": target_path}
            ),
        }

    preservation_receipts = plan.get("preservation_receipts", [])
    if preservation_receipts:
        return {
            **plan,
            "mode": "apply",
            "destructive_actions": actions,
            "errors": [
                {
                    "artifact": "worktree",
                    "action": "preserve",
                    "reason": "preservation_evidence_present",
                    "preservation_receipts": preservation_receipts,
                }
            ],
            "ok": False,
        }

    def authority_changed_for(
        *,
        path: str | None = None,
        branch: str | None = None,
    ) -> bool:
        """Fail closed unless BOTH identities are still free of an active lease.

        The guarded paths are the explicit target path plus every worktree path a
        lifecycle record binds to ``branch`` — including the tombstone of a path
        this run has just removed. A `worktree:<path>` lease claimed after the
        checkout disappeared therefore still blocks the branch deletion.
        """
        refreshed = reload_active_leases()
        if refreshed is None:
            return True
        _, resources = refreshed
        guarded_paths = _path_identities(path) | _lifecycle_worktree_paths_for_branch(
            branch, lifecycle_records
        )
        conflicts = {
            resource
            for resource in resources
            if (
                resource.startswith("worktree:")
                and _path_identities(resource.removeprefix("worktree:")) & guarded_paths
            )
            or (branch and resource == f"branch:{branch}")
        }
        if conflicts:
            errors.append(
                {
                    "artifact": "worktree",
                    "action": "preserve",
                    "reason": "lease_authority_changed",
                    "path": path,
                    "branch": branch,
                    "active_leases": sorted(conflicts),
                }
            )
            return True
        return False

    def apply_with_lifecycle_authority(
        args: list[str],
        action: dict[str, Any],
        targets: list[dict[str, Any]],
    ) -> bool:
        """Run one worktree-destructive command under fresh lifecycle authority."""

        try:
            with lifecycle_authority_guard(targets) as mark_succeeded:
                if apply_git(args, action):
                    mark_succeeded()
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
            errors.append(
                {
                    "artifact": "worktree",
                    "action": "revalidate_lifecycle_registry",
                    "reason": "lifecycle_authority_changed",
                    "targets": targets,
                }
            )
            return False
        return True

    def apply_with_branch_lifecycle_authority(
        args: list[str],
        action: dict[str, Any],
    ) -> bool:
        if branch_lifecycle_authority_guard is None:
            return apply_git(args, action)
        try:
            with branch_lifecycle_authority_guard(action):
                if authority_changed_for(
                    path=action.get("path"), branch=action.get("branch")
                ):
                    return False
                merged_pr_head = action.get("merged_pr_head")
                if merged_pr_head is not None:
                    current_head = run_git(["rev-parse", str(action["branch"])], cwd)
                    if current_head != merged_pr_head:
                        errors.append(
                            {
                                "artifact": "local_branch",
                                "action": "revalidate_merged_pr_head",
                                "reason": "target_branch_head_changed",
                                "branch": action["branch"],
                                "expected_head": merged_pr_head,
                                "current_head": current_head,
                            }
                        )
                        return False
                return apply_git(args, action)
        except (OSError, RuntimeError, TypeError, ValueError, subprocess.SubprocessError):
            errors.append(
                {
                    "artifact": "worktree",
                    "action": "revalidate_lifecycle_registry",
                    "reason": "targeted_branch_lifecycle_authority_changed",
                    "path": action.get("path"),
                    "branch": action.get("branch"),
                }
            )
            return False

    def branch_delete_args(branch: Mapping[str, Any]) -> list[str] | None:
        """Return a ref-CAS delete for non-ancestor PR-proven branches.

        `git branch -D` cannot bind the delete to the planned ref.  A conditional
        `update-ref -d` does, so a branch advanced after planning is preserved.
        """

        branch_name = branch.get("branch")
        merge_proof = branch.get("merge_proof")
        if not isinstance(branch_name, str) or not branch_name:
            raise ValueError("branch cleanup candidate is invalid")
        if merge_proof not in {"merged_pr", "closed_pr"}:
            return ["branch", "-d", branch_name]
        expected_head = branch.get("merged_pr_head", branch.get("head"))
        if not isinstance(expected_head, str) or not expected_head:
            errors.append(
                {
                    "artifact": "local_branch",
                    "action": "select_delete_ref",
                    "reason": "conditional_branch_delete_head_required",
                    "branch": branch_name,
                }
            )
            return None
        return ["update-ref", "-d", f"refs/heads/{branch_name}", expected_head]

    reclaimable = plan.get("reclaimable_worktrees", plan["candidates"]["worktrees"])
    cleanup_worktrees = [
        *plan.get(
            "orphaned_worktrees",
            plan["candidates"].get("orphaned_worktrees", []),
        ),
        *reclaimable,
    ]
    for cleanup_worktree in cleanup_worktrees:
        if authority_changed_for(
            path=cleanup_worktree.get("path"),
            branch=cleanup_worktree.get("branch"),
        ):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }

    for worktree in reclaimable:
        if authority_changed_for(
            path=worktree.get("path"),
            branch=worktree.get("branch"),
        ):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        remove_errors_before = len(errors)
        # Never --force / --ignore-locked: a worktree that turned dirty or locked
        # since planning must fail the remove and keep its branch intact.
        if not apply_with_lifecycle_authority(
            ["worktree", "remove", worktree["path"]],
            {"artifact": "worktree", "action": "remove", **worktree},
            [worktree],
        ):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        if len(errors) == remove_errors_before:
            # Revalidate the worktree path as well as the branch: the checkout is
            # gone, but its path identity is exactly what a new owner leases, and
            # the deletion below is irreversible for merged_pr/closed_pr proofs.
            if authority_changed_for(
                path=worktree.get("path"),
                branch=worktree.get("branch"),
            ):
                return {
                    **plan,
                    "mode": "apply",
                    "destructive_actions": actions,
                    "errors": errors,
                    "ok": False,
                }
            delete_args = branch_delete_args(worktree)
            if delete_args is None or not apply_git(
                delete_args,
                {
                    "artifact": "local_branch",
                    "action": "delete_after_worktree_remove",
                    "branch": worktree["branch"],
                },
            ):
                return {
                    **plan,
                    "mode": "apply",
                    "destructive_actions": actions,
                    "errors": errors,
                    "ok": False,
                }
    for branch in plan["candidates"]["local_branches"]:
        if authority_changed_for(
            path=target_worktree if branch.get("branch") == target_branch else None,
            branch=branch.get("branch"),
        ):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        action = {"artifact": "local_branch", "action": "delete", **branch}
        if target_branch is not None and branch.get("branch") == target_branch:
            action["path"] = target_worktree
            delete_args = branch_delete_args(branch)
            if delete_args is None or not apply_with_branch_lifecycle_authority(
                delete_args, action
            ):
                return {
                    **plan,
                    "mode": "apply",
                    "destructive_actions": actions,
                    "errors": errors,
                    "ok": False,
                }
        else:
            apply_git(["branch", "-d", branch["branch"]], action)
    for remote in plan["candidates"]["remote_branches"]:
        if authority_changed_for(branch=remote.get("branch")):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        apply_git(["push", "origin", "--delete", remote["branch"]], {"artifact": "remote_branch", "action": "delete", **remote})
    for remote in plan["candidates"]["remote_branches_requiring_rescue"]:
        # Broad janitor plans are evidence only.  They never carry the complete
        # identity/disposition authority required by targeted_remote_cleanup.
        errors.append(
            {
                "artifact": "remote_branch",
                "action": "preserve",
                "reason": "targeted_remote_cleanup_required",
                **remote,
            }
        )
        return {
            **plan,
            "mode": "apply",
            "destructive_actions": actions,
            "errors": errors,
            "ok": False,
        }
        # Kept below temporarily as implementation history for the next
        # narrowly-authorized migration; unreachable by construction.
        branch = remote["branch"]
        if authority_changed_for(branch=branch):
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        rescue_ref = remote["rescue_ref"]
        source_ref = f"refs/heads/{branch}"
        protected_source_refs = {
            f"refs/heads/{protected}" for protected in DEFAULT_PROTECTED_BRANCHES
        }
        if (
            not branch
            or branch.startswith("-")
            or source_ref in protected_source_refs
            or not rescue_ref.startswith("refs/archive/git-hygiene/")
        ):
            errors.append(
                {
                    "artifact": "remote_branch",
                    "action": "validate_rescue_transport",
                    **remote,
                    "reason": "unsafe_rescue_transport_target",
                }
            )
            continue

        errors_before_validation = len(errors)
        apply_git(
            ["check-ref-format", rescue_ref],
            {"artifact": "remote_branch", "action": "validate_rescue_ref", **remote},
        )
        if len(errors) != errors_before_validation:
            continue
        apply_git(
            ["check-ref-format", source_ref],
            {"artifact": "remote_branch", "action": "validate_source_ref", **remote},
        )
        if len(errors) != errors_before_validation:
            continue

        errors_before_rescue = len(errors)
        apply_git(
            ["update-ref", rescue_ref, f"origin/{branch}"],
            {"artifact": "remote_branch", "action": "create_rescue_ref", **remote},
        )
        rescue_created = len(errors) == errors_before_rescue
        rescue_pushed = False
        if rescue_created:
            errors_before_push = len(errors)
            apply_git(
                ["push", "--no-verify", "origin", f"{rescue_ref}:{rescue_ref}"],
                {"artifact": "remote_branch", "action": "push_rescue_ref", **remote},
            )
            rescue_pushed = len(errors) == errors_before_push
        rescue_verified = False
        if rescue_pushed:
            errors_before_verify = len(errors)
            apply_git(
                ["ls-remote", "--exit-code", "origin", rescue_ref],
                {"artifact": "remote_branch", "action": "verify_rescue_ref", **remote},
            )
            rescue_verified = len(errors) == errors_before_verify
        if rescue_created and rescue_pushed and rescue_verified:
            if authority_changed_for(branch=branch):
                return {
                    **plan,
                    "mode": "apply",
                    "destructive_actions": actions,
                    "errors": errors,
                    "ok": False,
                }
            # The repository's direct-main pre-push guard is branch-based and
            # rejects every push made while main is checked out. This transport
            # bypass is deliberately confined to a validated archive ref and a
            # fully qualified non-protected source-branch deletion. Prefixing
            # the plan's short branch name with refs/heads/ prevents ref-like
            # names from being reinterpreted as refs/heads/main.
            apply_git(
                ["push", "--no-verify", "origin", f":{source_ref}"],
                {
                    "artifact": "remote_branch",
                    "action": "delete_after_rescue",
                    **remote,
                },
            )
    for stash in plan["candidates"]["old_stashes"]:
        expected_sha = stash.get("sha")
        if not expected_sha:
            errors.append(
                {
                    "artifact": "stash",
                    "action": "drop",
                    "reason": "missing_stash_identity",
                    **stash,
                }
            )
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        # Never trust `stash["ref"]`: it is the positional selector captured
        # when the plan was built, and a prior drop in this same loop
        # renumbers every stash above the one it removed. Re-resolve the
        # candidate's stable commit hash to whatever selector currently holds
        # it, verify that selector still names the intended commit, and only
        # then drop it. A candidate that can no longer be found or no longer
        # matches aborts the whole loop rather than risk touching an
        # unrelated stash.
        current_selector = _current_stash_selector_for_sha(cwd, expected_sha)
        if current_selector is None:
            errors.append(
                {
                    "artifact": "stash",
                    "action": "drop",
                    "reason": "stash_identity_not_found",
                    **stash,
                }
            )
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        verify = run_git_result(["rev-parse", "--verify", f"{current_selector}^{{commit}}"], cwd)
        if verify.returncode != 0 or verify.stdout.strip() != expected_sha:
            errors.append(
                {
                    "artifact": "stash",
                    "action": "drop",
                    "reason": "stash_identity_mismatch",
                    "resolved_selector": current_selector,
                    **stash,
                }
            )
            return {
                **plan,
                "mode": "apply",
                "destructive_actions": actions,
                "errors": errors,
                "ok": False,
            }
        apply_git(
            ["stash", "drop", current_selector],
            {"artifact": "stash", "action": "drop", **stash},
        )

    return {
        **plan,
        "mode": "apply",
        "destructive_actions": actions,
        "errors": errors,
        "ok": not errors,
    }


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--lease-file", help="Read-only JSON list of active lease claims")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--expected-branch")
    preflight.add_argument("--expected-worktree")
    preflight.add_argument("--base-branch")
    preflight.add_argument("--resource-id", action="append", default=[])
    preflight.add_argument("--execution-id")
    preflight.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not fail on a dirty working tree (use at the publish boundary, "
        "where uncommitted work is expected; branch/worktree drift still fails)",
    )
    preflight.add_argument(
        "--require-dedicated-worktree",
        action="store_true",
        help="Fail if run in the shared root worktree (use a dedicated git worktree for parallel work).",
    )

    janitor = subparsers.add_parser("janitor")
    janitor.add_argument("--stale-after-days", type=int, default=14)
    janitor.add_argument("--mode", choices=["report", "apply"], default="report")
    janitor.add_argument("--remote-policy", choices=[DEFAULT_REMOTE_POLICY, "merged-only"], default=DEFAULT_REMOTE_POLICY)
    janitor.add_argument("--pr-state-file", help="JSON map of branch name to GitHub PR state")
    janitor.add_argument("--resolve-github-state", action="store_true", help="Load PR state with gh before planning")

    args = parser.parse_args(argv)
    cwd = Path(args.cwd).resolve()
    leases = load_active_leases(args.lease_file)
    if args.command == "preflight":
        report = preflight_report(
            cwd,
            expected_branch=args.expected_branch,
            expected_worktree=args.expected_worktree,
            base_branch=args.base_branch,
            active_leases=leases,
            resource_ids=set(args.resource_id),
            execution_id=args.execution_id,
            allow_dirty=args.allow_dirty,
            require_dedicated_worktree=args.require_dedicated_worktree,
        )
        _print_json(report)
        return 0 if report["ok"] else 1

    pr_states = None
    if args.pr_state_file:
        pr_states = json.loads(Path(args.pr_state_file).read_text(encoding="utf-8"))
    if args.resolve_github_state:
        pr_states = load_pr_states_from_gh(cwd)
    if args.mode == "apply":
        _print_json(
            {
                "mode": "apply",
                "ok": False,
                "errors": [
                    {
                        "artifact": "worktree",
                        "action": "cleanup",
                        "reason": "registered_lifecycle_guard_required",
                        "next_action": "use scripts/agent_worktree.py janitor --mode apply",
                    }
                ],
            }
        )
        return 1
    else:
        report = janitor_report(
            cwd,
            active_leases=leases,
            stale_after_days=args.stale_after_days,
        )
        if pr_states is not None:
            report = build_janitor_plan(
                cwd,
                active_leases=leases,
                stale_after_days=args.stale_after_days,
                remote_policy=args.remote_policy,
                pr_states=pr_states,
            )
    _print_json(report)
    return 0 if not report.get("errors") else 1


def main_with_default_command(command: str, argv: list[str] | None = None) -> int:
    """Run a compatibility entrypoint while preserving global CLI options."""

    raw_args = list(argv or [])
    if command in raw_args:
        return main(raw_args)

    global_args: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if arg in {"--cwd", "--lease-file"} and index + 1 < len(raw_args):
            global_args.extend([arg, raw_args[index + 1]])
            index += 2
            continue
        remaining.append(arg)
        index += 1
    return main([*global_args, command, *remaining])


if __name__ == "__main__":
    raise SystemExit(main())
