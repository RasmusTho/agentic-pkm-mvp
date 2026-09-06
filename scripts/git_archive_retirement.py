"""Explicit owner retirement of exact dated remote archives; never automation authority."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence

from scripts import agent_worktree as aw
from scripts import git_hygiene as gh

SCHEMA = "remote_legacy_archive_retirement.v1"
RESCUE_SCHEMA = "remote_legacy_rescue_branch_retirement.v1"
CLOSED_PR_SCHEMA = "remote_closed_pr_batch_retirement.v1"


def _git(cwd: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, env=gh._sanitized_git_environment(),
                            capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError("archive_git_command_failed: " + result.stderr)
    return result.stdout.strip()


def _remote(cwd: Path, url: str, refs: Mapping[str, str]) -> dict[str, str]:
    result = {}
    for line in _git(cwd, ["ls-remote", "--refs", url, *refs]).splitlines():
        sha, ref = line.split()
        if ref not in refs or ref in result or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("archive_remote_inventory_invalid")
        result[ref] = sha
    return result


def _bundle(directory: Path, receipt: Mapping[str, Any]) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    bundle = directory / "repository.bundle"
    if manifest_path.is_symlink() or bundle.is_symlink():
        raise RuntimeError("archive_recovery_symlink")
    manifest = gh._json_without_duplicates(manifest_path.read_text())
    if (manifest.get("bundle") != str(bundle)
            or manifest.get("bundle_sha256") != receipt.get("bundle_sha256")
            or not set(receipt["targets"].values()) <= set(manifest.get("verified_objects", []))):
        raise RuntimeError("archive_recovery_manifest_mismatch")
    with bundle.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != manifest["bundle_sha256"]:
        raise RuntimeError("archive_recovery_checksum_mismatch")
    return manifest


def _compensate(cwd: Path, identity: gh.RepositoryIdentity, directory: Path,
                receipt: dict[str, Any]) -> None:
    path = directory / "archive-retirement.json"
    receipt["state"] = "recovery_required"
    aw._write_registry(path, receipt)
    manifest = _bundle(directory, receipt)
    pending = receipt["pending"]
    current = _remote(cwd, identity.push_url, pending)
    recreated = any(sha != pending[ref] for ref, sha in current.items())
    absent = {ref: sha for ref, sha in pending.items() if ref not in current}
    if absent:
        with tempfile.TemporaryDirectory(prefix="archive-recovery-") as temporary:
            recovery = Path(temporary)
            _git(recovery, ["init", "--bare", "."])
            _git(recovery, ["bundle", "unbundle", manifest["bundle"]])
            for sha in absent.values():
                _git(recovery, ["cat-file", "-e", sha])
            _git(recovery, ["push", "--atomic", "--no-verify",
                           *[f"--force-with-lease={ref}:" for ref in absent],
                           identity.push_url, *[f"{sha}:{ref}" for ref, sha in absent.items()]])
    if recreated:
        raise RuntimeError("archive_recovery_ref_recreated")
    if _remote(cwd, identity.push_url, pending) != pending:
        raise RuntimeError("archive_recovery_readback_failed")
    receipt["state"] = "compensated"
    aw._write_registry(path, receipt)


def _retire_remote_copies(
    cwd: Path, *, targets: Mapping[str, str], snapshot_directory: Path,
    owner_discard: str, batch_size: int = 25, kind: str,
    pr_targets: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Retire exact dated refs, or compensate a prior pending batch on retry."""
    if not targets or len(targets) > 1000 or not owner_discard.strip() or not 1 <= batch_size <= 25:
        raise ValueError("archive_exact_disposition_required")
    if kind not in {"archive", "rescue_branch", "closed_pr"}:
        raise ValueError("archive_retirement_kind_invalid")
    schema = {"archive": SCHEMA, "rescue_branch": RESCUE_SCHEMA, "closed_pr": CLOSED_PR_SCHEMA}[kind]
    pattern = {"archive": r"refs/archive/git-hygiene/[0-9]{8}T[0-9]{6}Z/.+",
               "rescue_branch": r"refs/heads/rescue/.+", "closed_pr": r"refs/heads/.+"}[kind]
    metadata = [dict(target) for target in pr_targets] if pr_targets is not None else None
    if kind == "closed_pr":
        if (not metadata or len(metadata) != len(targets)
                or {target.get("ref"): target.get("sha") for target in metadata} != dict(targets)
                or any(set(target) != {"ref", "sha", "pr"} or not gh._positive_int(target["pr"]) for target in metadata)):
            raise ValueError("closed_pr_exact_metadata_required")
    elif metadata is not None:
        raise ValueError("unexpected_pr_metadata")
    targets = dict(targets)
    for ref, sha in targets.items():
        if (not re.fullmatch(pattern, ref)
                or not re.fullmatch(r"[0-9a-f]{40}", sha)
                or (kind == "closed_pr" and (ref.startswith("refs/heads/rescue/")
                                             or ref.removeprefix("refs/heads/") in gh.DEFAULT_PROTECTED_BRANCHES))):
            raise ValueError("archive_namespace_or_sha_invalid")
        _git(cwd, ["check-ref-format", ref])
    identity = gh._resolve_repository_identity(cwd, "RasmusTho/agentic-pkm-mvp")
    directory = snapshot_directory.resolve()
    path = directory / "archive-retirement.json"
    if directory.exists():
        if path.is_symlink():
            raise RuntimeError("archive_receipt_invalid")
        receipt = gh._json_without_duplicates(path.read_text())
        if (not isinstance(receipt, dict) or receipt.get("schema") != schema
                or receipt.get("repository") != dataclasses.asdict(identity)
                or receipt.get("targets") != targets or receipt.get("owner_discard") != owner_discard
                or receipt.get("snapshot") != str(directory)
                or (kind == "closed_pr" and receipt.get("pr_targets") != metadata)):
            raise RuntimeError("archive_receipt_identity_mismatch")
        pending = receipt.get("pending")
        if pending is not None:
            if (not isinstance(pending, dict) or not pending or len(pending) > 25
                    or any(targets.get(ref) != sha for ref, sha in pending.items())):
                raise RuntimeError("archive_pending_invalid")
            registry_path = aw._default_registry_path(cwd)
            if registry_path.is_symlink() or not registry_path.is_file():
                raise RuntimeError("archive_lifecycle_registry_missing")
            with gh._dispatcher_authority_write_fence(cwd):
                with aw._registry_lock(registry_path):
                    _compensate(cwd, identity, directory, receipt)
        return receipt  # Never resume deletion using old authority or snapshot.
    special = gh._read_protected_targets(identity, cwd=cwd)
    heads = gh._open_cleanup_pr_heads(cwd, identity.full_name)
    registry_path = aw._default_registry_path(cwd)
    if registry_path.is_symlink() or not registry_path.is_file():
        raise RuntimeError("archive_lifecycle_registry_missing")
    initial_registry = aw._locked_lifecycle_snapshot(registry_path)
    if _remote(cwd, identity.push_url, targets) != targets:
        raise RuntimeError("archive_remote_source_drift")
    with tempfile.TemporaryDirectory(prefix="archive-snapshot-") as temporary:
        recovery = Path(temporary)
        _git(recovery, ["init", "--bare", "."])
        _git(recovery, ["fetch", "--no-tags", "--no-write-fetch-head", identity.push_url,
                        *[f"{ref}:{ref}" for ref in targets]])
        fetched = {line.split()[1]: line.split()[0] for line in
                   _git(recovery, ["for-each-ref", "--format=%(objectname) %(refname)"]).splitlines()}
        if fetched != targets:
            raise RuntimeError("archive_snapshot_source_drift")
        snapshot = gh.create_rescue_snapshot(recovery, directory)
    receipt = {"schema": schema, "state": "prepared", "targets": targets,
               "repository": dataclasses.asdict(identity), "owner_discard": owner_discard,
               "snapshot": str(directory), "bundle_sha256": snapshot["bundle_sha256"],
               "deleted": {}, "retained": {}, "batches": []}
    if kind == "closed_pr":
        receipt["pr_targets"] = metadata
    _bundle(directory, receipt)
    aw._write_registry(path, receipt)

    def external_check() -> None:
        if (gh._resolve_repository_identity(cwd, identity.full_name) != identity
                or gh._read_protected_targets(identity, cwd=cwd) != special
                or gh._open_cleanup_pr_heads(cwd, identity.full_name) != heads):
            raise RuntimeError("archive_external_authority_drift")

    items = list(targets.items())
    for offset in range(0, len(items), batch_size):
        with gh._dispatcher_authority_write_fence(cwd) as connection:
            with aw._registry_lock(registry_path):
                registry = aw._read_registry(registry_path)["worktrees"]
                if registry != initial_registry:
                    raise RuntimeError("archive_lifecycle_generation_drift")
                dispatcher = gh._dispatcher_snapshot_from_connection(connection)
                worktree_census = _git(cwd, ["worktree", "list", "--porcelain"])
                protected, resources = gh._retirement_local_activity(cwd, registry, dispatcher)
                live_lease = any(row["kind"] == "lease" and not row["record"].get("released_at")
                                 and gh._parse_dispatcher_time(row["record"].get("expires_at")).timestamp() > time.time()
                                 for row in dispatcher)
                batch = {}
                for ref, sha in items[offset:offset + batch_size]:
                    branch_activity = kind in {"rescue_branch", "closed_pr"} and _rescue_branch_active(
                        cwd, ref, registry, resources, heads, special,
                        include_original=kind == "rescue_branch")
                    if (branch_activity or live_lease or sha in protected or sha in heads.values() or sha == special.pull_sha
                            or re.search(r"(?:^|[-_/])" + str(special.issue_number) + r"(?:$|[-_/])", ref)
                            or any(ref in resource or sha in resource for resource in resources)):
                        receipt["retained"][ref] = "protected_or_resumable_activity"
                    else:
                        batch[ref] = sha
                if not batch:
                    aw._write_registry(path, receipt)
                    continue
                external_check()
                selected_prs = [target for target in metadata or [] if target["ref"] in batch]
                contracts = {target["ref"]: gh._closed_retirement_pr(cwd, identity, target)
                             for target in selected_prs}
                if _remote(cwd, identity.push_url, batch) != batch:
                    raise RuntimeError("archive_remote_source_drift")
                receipt["pending"] = batch
                if kind == "closed_pr":
                    receipt["pending_pr_contracts"] = contracts
                receipt["state"] = "delete_pending"
                aw._write_registry(path, receipt)
                try:
                    _git(cwd, ["push", "--atomic", "--no-verify",
                               *[f"--force-with-lease={ref}:{sha}" for ref, sha in batch.items()],
                               identity.push_url, *[f":{ref}" for ref in batch]])
                    if _remote(cwd, identity.push_url, batch):
                        raise RuntimeError("archive_delete_readback_failed")
                    external_check()
                    if any(gh._closed_retirement_pr(cwd, identity, target) != contracts[target["ref"]]
                           for target in selected_prs):
                        raise RuntimeError("closed_pr_post_delete_authority_drift")
                    if (aw._read_registry(registry_path)["worktrees"] != registry
                            or gh._dispatcher_snapshot_from_connection(connection) != dispatcher
                            or _git(cwd, ["worktree", "list", "--porcelain"]) != worktree_census):
                        raise RuntimeError("archive_post_delete_local_authority_drift")
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    _compensate(cwd, identity, directory, receipt)
                    raise
                receipt["deleted"].update(batch)
                receipt["batches"].append({"targets": batch, "readback": "verified",
                                          "checked_at": time.time(),
                                          "lifecycle_sha256": hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest(),
                                          "dispatcher_sha256": hashlib.sha256(json.dumps(dispatcher, sort_keys=True).encode()).hexdigest(),
                                          "open_heads": heads})
                receipt.pop("pending")
                receipt.pop("pending_pr_contracts", None)
                receipt["state"] = "batch_verified"
                aw._write_registry(path, receipt)
    receipt["state"] = "completed"
    aw._write_registry(path, receipt)
    return receipt


def _rescue_branch_active(cwd: Path, ref: str, registry: Mapping[str, Any],
                          resources: set[str], heads: Mapping[str, str],
                          special: gh.ProtectedAuthority, *, include_original: bool = True) -> bool:
    names = {ref.removeprefix("refs/heads/")}
    if include_original:
        names.add(ref.removeprefix("refs/heads/rescue/"))
    checked = {item.get("branch") for item in gh._parse_worktrees(
        gh.run_git(["worktree", "list", "--porcelain"], cwd))}
    for branch in names:
        if (branch in gh.DEFAULT_PROTECTED_BRANCHES
                or "refs/heads/" + branch in checked
                or branch in {key.split(":", 1)[1] for key in heads}
                or "refs/heads/" + branch == special.pull_ref
                or any(branch in resource for resource in resources)
                or gh._branch_has_worktree_path_lease(branch, resources, registry)):
            return True
        try:
            for path, record in registry.items():
                if record.get("branch") == branch or gh._record_previously_bound(record, branch):
                    aw._validate_authority_record(path, record)
                if record.get("branch") == branch and record["expires_at"] > time.time():
                    return True
        except (RuntimeError, TypeError, ValueError):
            return True
    return False


def retire_remote_legacy_archives(
    cwd: Path, *, targets: Mapping[str, str], snapshot_directory: Path,
    owner_discard: str, batch_size: int = 25,
) -> dict[str, Any]:
    """Explicit retirement of dated remote archives only."""
    return _retire_remote_copies(cwd, targets=targets, snapshot_directory=snapshot_directory,
                                owner_discard=owner_discard, batch_size=batch_size, kind="archive")


def retire_remote_legacy_rescue_branches(
    cwd: Path, *, targets: Mapping[str, str], snapshot_directory: Path,
    owner_discard: str, batch_size: int = 25,
) -> dict[str, Any]:
    """Explicit retirement of refs/heads/rescue/* copies only."""
    return _retire_remote_copies(cwd, targets=targets, snapshot_directory=snapshot_directory,
                                owner_discard=owner_discard, batch_size=batch_size, kind="rescue_branch")


def retire_closed_pr_remote_batches(
    cwd: Path, *, targets: Sequence[Mapping[str, Any]], snapshot_directory: Path,
    owner_discard: str, batch_size: int = 25,
) -> dict[str, Any]:
    """New exact closed-PR phases; old single-head receipts keep their recovery API."""
    metadata = [dict(target) for target in targets]
    return _retire_remote_copies(
        cwd, targets={target.get("ref"): target.get("sha") for target in metadata},
        snapshot_directory=snapshot_directory, owner_discard=owner_discard,
        batch_size=batch_size, kind="closed_pr", pr_targets=metadata)
