"""Non-authoritative receipt comparison for legacy Builder owner recovery.

This module does not claim a task, transfer a worktree, or authorize a merge.
The caller must collect fresh observations from the host, dispatcher and GitHub;
this comparison cannot establish their origin or freshness. A comment or a
caller-supplied session identifier is not an observation.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import argparse
import os
from pathlib import Path
import re
import json
import subprocess
import sys
import time
import uuid
from typing import Any

from scripts import agent_worktree
from app.dispatcher.config import load_paths as load_dispatcher_paths
from app.dispatcher.events import claim_event_digest, event_history_digest


class RecoveryEvidenceError(ValueError):
    """A recovery observation is missing, contradictory or unauthenticated."""


def read_expired_registration(*, cwd: Path, candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Read the exact ended registration without claiming its former authority."""
    path = candidate.get("path")
    branch = candidate.get("branch")
    generation = candidate.get("generation")
    if not isinstance(path, str) or not Path(path).is_absolute() or not isinstance(branch, str):
        raise RecoveryEvidenceError("candidate registration identity is incomplete")
    registry = agent_worktree._default_registry_path(cwd)
    if not registry.is_file():
        raise RecoveryEvidenceError("worktree registry is unavailable")
    try:
        before = agent_worktree._locked_lifecycle_snapshot(registry)
        actual_generation = agent_worktree._worktree_generation(cwd, Path(path), create=False)
        after = agent_worktree._locked_lifecycle_snapshot(registry)
    except (OSError, RuntimeError, agent_worktree.WorktreeLifecycleError) as exc:
        raise RecoveryEvidenceError("worktree registration readback is unavailable") from exc
    record = before.get(path)
    if before != after or not isinstance(record, dict):
        raise RecoveryEvidenceError("worktree registration changed during readback")
    now = time.time()
    registered = record.get("registered_at")
    expires = record.get("expires_at")
    if (record.get("path") != path or record.get("branch") != branch
            or record.get("generation") != generation or actual_generation != generation
            or not isinstance(record.get("owner"), str) or not record["owner"]
            or record.get("status") != "active"
            or any(key in record for key in ("prior_owner", "previous_registration", "transfer_registration"))
            or record.get("prior_bindings", []) != []
            or not agent_worktree._valid_authority_timestamp(registered)
            or not agent_worktree._valid_authority_timestamp(expires)
            or expires > now or registered > expires):
        raise RecoveryEvidenceError("predecessor worktree registration is not an exact expired record")
    try:
        agent_worktree._validate_authority_record(path, record)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("predecessor worktree registration is invalid") from exc
    for other_path, other in before.items():
        if other_path == path or other.get("branch") != branch:
            continue
        raise RecoveryEvidenceError("worktree successor history is ambiguous")
    try:
        branch_history_digest = agent_worktree._branch_history_digest(before, branch)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("worktree branch history is invalid") from exc
    return {"path": path, "branch": branch, "generation": generation, "owner": record["owner"],
            "registered_at": datetime.fromtimestamp(registered, timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(), "state": "expired",
            "authority_since": record.get("authority_since"), "registration_epoch": record.get("registration_epoch"),
            "history_digest": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
            "branch_history_digest": branch_history_digest}


def read_live_predecessor(*, cwd: Path, issue: int) -> dict[str, Any]:
    """Read one expired dispatcher predecessor and its claim in one snapshot.

    A verified expired lease is not itself a writer fence or a transfer. The
    atomic claimant must still recheck the exact predecessor under its lock.
    """
    if type(issue) is not int or issue <= 0:
        raise RecoveryEvidenceError("predecessor issue is invalid")
    task_id = f"github-RasmusTho--agentic-pkm-mvp-issue-{issue}"
    paths = load_dispatcher_paths({}, cwd=cwd)
    if not paths.db_path.is_file():
        raise RecoveryEvidenceError("dispatcher readback is unavailable")
    env = {"PATH": os.defpath, "HOME": "/dev/null", "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
           "DISPATCHER_STATE_DIR": str(paths.state_dir)}
    try:
        result = subprocess.run([sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=False)
        data = json.loads(result.stdout) if result.returncode == 0 and len(result.stdout) <= 1_000_000 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryEvidenceError("dispatcher readback is unavailable") from exc
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RecoveryEvidenceError("dispatcher readback is unavailable")
    task, lease, events = data.get("task"), data.get("lease"), data.get("events")
    if (not isinstance(task, dict) or not isinstance(lease, dict) or not isinstance(events, list)
            or any(not isinstance(event, dict) for event in events)):
        raise RecoveryEvidenceError("dispatcher predecessor is incomplete")
    if (task.get("task_id") != task_id or task.get("repo") != "RasmusTho/agentic-pkm-mvp"
            or task.get("issue_number") != issue or task.get("status") not in {"ready", "claimed"}
            or not isinstance(lease.get("lease_id"), str) or not lease["lease_id"]
            or not isinstance(lease.get("holder"), str) or not lease["holder"]
            or task.get("lease_id") != lease["lease_id"] or task.get("claimed_by") != lease.get("holder")
            or task.get("lease_expires_at") != lease.get("expires_at")
            or lease.get("resource") != f"issue:{issue}" or lease.get("released_at") is not None
            or _timestamp(lease.get("expires_at")) > datetime.now(timezone.utc).timestamp()):
        raise RecoveryEvidenceError("dispatcher predecessor changed or is not expired")
    history = [event for event in events if isinstance(event, dict)
               and event.get("event_type") in {"task.claimed", "task.released", "task.completed"}]
    times = [_timestamp(event.get("timestamp")) for event in history]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise RecoveryEvidenceError("dispatcher predecessor event order is ambiguous")
    claims = [event for event in history if event.get("event_type") == "task.claimed"]
    current = [event for event in claims if event.get("lease_id") == lease["lease_id"]]
    if (len(current) != 1 or not claims or claims[-1] != current[0] or history[-1] != current[0]
            or current[0].get("actor") != lease.get("holder")
            or not isinstance(current[0].get("event_id"), str)
            or not isinstance(current[0].get("payload"), dict)
            or (current[0]["payload"].get("session") is not None
                and (not isinstance(current[0]["payload"]["session"], str)
                     or not current[0]["payload"]["session"]))):
        raise RecoveryEvidenceError("dispatcher predecessor claim history is ambiguous")
    if _timestamp(current[0].get("timestamp")) >= _timestamp(lease.get("expires_at")):
        raise RecoveryEvidenceError("dispatcher predecessor claim timing is inconsistent")
    return {"task_id": task_id, "repo": task["repo"], "issue_number": issue,
            "holder": lease["holder"], "lease_id": lease["lease_id"],
            "session": current[0]["payload"].get("session"), "expires_at": lease["expires_at"],
            "claim_event_id": current[0]["event_id"], "claim_event_digest": claim_event_digest(current[0]),
            "history_digest": event_history_digest(events)}


def _git_read(worktree: Path, *args: str) -> bytes:
    # Do not run a repository-configured fsmonitor or external diff helper.
    env = {"PATH": os.defpath, "HOME": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
    try:
        result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(worktree), *args],
                                env=env, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryEvidenceError("candidate Git readback is unavailable") from exc
    if result.returncode or len(result.stdout) > 1_000_000:
        raise RecoveryEvidenceError("candidate Git readback is unavailable")
    return result.stdout


def read_clean_candidate(*, cwd: Path, worktree: Path) -> dict[str, Any]:
    """Read one tracked/nonignored clean candidate without modifying its index.

    Dirty or untracked work is refused rather than discarded. Preserving and
    transferring such a candidate requires its own content-bound path.
    """
    if not worktree.is_absolute() or worktree != worktree.resolve():
        raise RecoveryEvidenceError("candidate worktree path is invalid")

    def snapshot() -> tuple[str, str, str, str, bytes, bytes, str]:
        try:
            registered_path, registered_branch = agent_worktree._worktree_identity(cwd, worktree)
            root = _git_read(worktree, "rev-parse", "--show-toplevel").decode().strip()
            branch = _git_read(worktree, "branch", "--show-current").decode().strip()
            head = _git_read(worktree, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
            tree = _git_read(worktree, "rev-parse", "--verify", "HEAD^{tree}").decode().strip()
            flags = _git_read(worktree, "ls-files", "-v", "-z")
            status = _git_read(worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all")
            generation = agent_worktree._worktree_generation(cwd, worktree, create=False)
        except (UnicodeDecodeError, agent_worktree.WorktreeLifecycleError, OSError, RuntimeError) as exc:
            raise RecoveryEvidenceError("candidate identity is unavailable") from exc
        if registered_path != worktree or registered_branch != branch:
            raise RecoveryEvidenceError("candidate does not belong to the expected repository")
        return root, branch, head, tree, flags, status, generation

    first = snapshot()
    second = snapshot()
    root, branch, head, tree, flags, status, generation = first
    if first != second or root != str(worktree) or not branch or status:
        raise RecoveryEvidenceError("candidate is dirty, unavailable or changed during readback")
    if any(not item.startswith(b"H ") for item in flags.split(b"\0") if item):
        raise RecoveryEvidenceError("candidate has hidden or unsupported index flags")
    if (not re.fullmatch(r"[0-9a-f]{40,64}", head) or not re.fullmatch(r"[0-9a-f]{40,64}", tree)
            or not re.fullmatch(r"[0-9a-f]{32}", generation)):
        raise RecoveryEvidenceError("candidate identity is invalid")
    return {"path": str(worktree), "branch": branch, "head": head, "tree": tree, "generation": generation,
            "status_digest": hashlib.sha256(status).hexdigest()}


def _github_read(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["gh", "api", "--hostname", "github.com", *args], cwd=cwd,
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecoveryEvidenceError("authenticated GitHub readback is unavailable") from exc
    if result.returncode or len(result.stdout.encode()) > 1_000_000:
        raise RecoveryEvidenceError("authenticated GitHub readback is unavailable")
    return result.stdout


def read_live_publication(*, cwd: Path, pr: int, branch: str) -> dict[str, Any]:
    """Observe one open PR and refuse any other PR on the same branch.

    This is a point-in-time readback, not a reservation or publication permit;
    callers must repeat it before a later write and reconcile ambiguous effects.
    """
    if type(pr) is not int or pr <= 0 or not isinstance(branch, str) or not branch or branch.startswith("-"):
        raise RecoveryEvidenceError("publication target is invalid")
    if _github_read(["user", "--jq", ".login"], cwd=cwd).strip() != "RasmusTho":
        raise RecoveryEvidenceError("operator account is not the authenticated repository owner")
    try:
        current = json.loads(_github_read([f"repos/RasmusTho/agentic-pkm-mvp/pulls/{pr}"], cwd=cwd))
        repository = json.loads(_github_read(["repos/RasmusTho/agentic-pkm-mvp"], cwd=cwd))
        remote_ref = json.loads(_github_read([f"repos/RasmusTho/agentic-pkm-mvp/git/ref/heads/{branch}"], cwd=cwd))
        pages = json.loads(_github_read([
            "--method", "GET", "--paginate", "--slurp", "repos/RasmusTho/agentic-pkm-mvp/pulls",
            "-f", "state=all", "-f", f"head=RasmusTho:{branch}", "-f", "per_page=100",
        ], cwd=cwd))
    except (ValueError, TypeError) as exc:
        raise RecoveryEvidenceError("GitHub publication readback is invalid") from exc
    if (not isinstance(current, dict) or not isinstance(repository, dict) or not isinstance(remote_ref, dict)
            or not isinstance(pages, list)
            or any(not isinstance(p, list) for p in pages)):
        raise RecoveryEvidenceError("GitHub publication readback is invalid")
    head = current.get("head")
    base = current.get("base")
    body = current.get("body")
    sha = head.get("sha") if isinstance(head, dict) else None
    if (current.get("number") != pr or current.get("state") != "open"
            or not isinstance(head, dict) or head.get("ref") != branch
            or not isinstance(head.get("repo"), dict)
            or head["repo"].get("full_name") != "RasmusTho/agentic-pkm-mvp"
            or not isinstance(body, str) or not isinstance(base, dict) or not isinstance(base.get("repo"), dict)
            or base["repo"].get("full_name") != "RasmusTho/agentic-pkm-mvp"
            or repository.get("full_name") != "RasmusTho/agentic-pkm-mvp"
            or not isinstance(repository.get("default_branch"), str)
            or base.get("ref") != repository["default_branch"]
            or remote_ref.get("ref") != f"refs/heads/{branch}"
            or not isinstance(remote_ref.get("object"), dict) or remote_ref["object"].get("sha") != sha
            or not re.fullmatch(r"[0-9a-f]{40,64}", str(sha or ""))):
        raise RecoveryEvidenceError("GitHub PR identity or head is inconsistent")
    matches = [row for page in pages for row in page]
    listed = matches[0] if len(matches) == 1 and isinstance(matches[0], dict) else {}
    listed_head = listed.get("head") if isinstance(listed.get("head"), dict) else {}
    listed_base = listed.get("base") if isinstance(listed.get("base"), dict) else {}
    if (len(matches) != 1 or not isinstance(matches[0], dict) or matches[0].get("number") != pr
            or matches[0].get("state") != "open" or listed_head.get("sha") != sha
            or listed_head.get("ref") != branch or listed_base.get("ref") != base.get("ref")):
        raise RecoveryEvidenceError("open PR publication is missing, duplicated or ambiguous")
    return {"state": "open_pr_observed", "pr": pr, "head": sha, "repo": "RasmusTho/agentic-pkm-mvp",
            "branch": branch, "pr_state": "OPEN", "body_sha256": hashlib.sha256(body.encode()).hexdigest()}


def _verify_pr_origin(*, cwd: Path, issue: int, pr: int, worktree: Path, candidate: Mapping[str, Any],
                      predecessor: Mapping[str, Any], publication: Mapping[str, Any]) -> None:
    """Check the same original pickup and ancestry required by the PR consumer."""
    from app.builderops import openhands_pr_cycle
    from scripts.pr_body_generator import resolve_native_issue_authority
    try:
        current = json.loads(_github_read([f"repos/RasmusTho/agentic-pkm-mvp/pulls/{pr}"], cwd=cwd))
        body = current.get("body") if isinstance(current, dict) else None
        if not isinstance(body, str) or hashlib.sha256(body.encode()).hexdigest() != publication.get("body_sha256"):
            raise RecoveryEvidenceError("PR body changed during original pickup readback")
        authority = resolve_native_issue_authority(body)
        if authority is None or authority.governing_issue != issue or issue not in authority.closing_issues:
            raise RecoveryEvidenceError("PR governing or closing issue does not match the task")
        origin, _ = openhands_pr_cycle._pickup_origin(body, issue=issue, closing=authority.closing_issues,
                                                       branch=candidate["branch"], comments=[])
        if (origin.get("mode") != "dispatcher-backed" or origin.get("path") != str(worktree)
                or origin.get("lease_id") != predecessor.get("lease_id")
                or origin.get("agent") != predecessor.get("holder")):
            raise RecoveryEvidenceError("PR original pickup does not bind the predecessor")
        _git_read(worktree, "merge-base", "--is-ancestor", str(publication["head"]), str(candidate["head"]))
    except RecoveryEvidenceError:
        raise
    except (KeyError, ValueError, TypeError, openhands_pr_cycle.CycleError) as exc:
        raise RecoveryEvidenceError("PR origin or candidate ancestry is unavailable") from exc


def _timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise RecoveryEvidenceError("recovery timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryEvidenceError("recovery timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise RecoveryEvidenceError("recovery timestamp lacks a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


def _operator_sources(value: object, required: set[str]) -> bool:
    """Require the operator to name the sources of each reported observation."""
    return (isinstance(value, dict) and set(value) == required
            and all(isinstance(items, list) and bool(items)
                    and all(isinstance(item, str) and bool(item.strip()) for item in items)
                    for items in value.values()))


def read_operator_reconciliation(
    comment_id: int,
    *,
    cwd: Path,
    issue: int,
    pr: int,
    successor: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    registration: Mapping[str, Any],
    candidate: Mapping[str, Any],
    writer: Mapping[str, Any],
    publication: Mapping[str, Any],
) -> tuple[dict[str, Any], float, str]:
    """Read the owner-account comment through the existing host GitHub seam.

    Live collection of the five observations is still the caller's duty. This
    read authenticates the account and comment, not the human behind it.
    """
    try:
        comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator comment readback is unavailable") from exc
    return validate_operator_reconciliation(
        comment, issue=issue, pr=pr, github_login="RasmusTho", successor=successor,
        predecessor=predecessor, registration=registration, candidate=candidate, writer=writer, publication=publication,
    )


def _read_task_events(*, cwd: Path, task_id: str) -> list[dict[str, Any]]:
    paths = load_dispatcher_paths({}, cwd=cwd)
    try:
        result = subprocess.run([sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
                                 cwd=cwd, env={**os.environ, "DISPATCHER_STATE_DIR": str(paths.state_dir)},
                                 capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryEvidenceError("dispatcher event history is unavailable") from exc
    events = payload.get("events") if isinstance(payload, dict) and payload.get("ok") is True else None
    if not isinstance(events, list) or any(not isinstance(row, dict) for row in events):
        raise RecoveryEvidenceError("dispatcher event history is unavailable")
    return events


def preflight_operator_pickup(
    *, cwd: Path, issue: int, pr: int, worktree: Path, agent: str, session: str, comment_id: int,
    workspace_root: Path,
) -> dict[str, Any]:
    """Read the scoped operator decision and current sources before a claim.

    The named operator's source-backed historical writer/effect observations are
    attributed to that operator, not independently attested by this function.
    This read-only preflight alone cannot grant worktree or publication rights.
    """
    if (not session or session != os.environ.get("CODEX_SESSION_ID")
            or not isinstance(agent, str) or not agent or agent.strip() != agent
            or type(comment_id) is not int or comment_id <= 0):
        raise RecoveryEvidenceError("current Builder successor session is unavailable")
    try:
        agent_worktree._screen_transfer_workspace(cwd, worktree, workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator workspace boundary is invalid") from exc
    try:
        comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
        receipt, pending_at, _ = agent_worktree._transfer_comment(
            comment, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1"
        )
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator comment readback is unavailable") from exc
    if _github_read(["user", "--jq", ".login"], cwd=cwd).strip() != "RasmusTho":
        raise RecoveryEvidenceError("operator account is not the authenticated repository owner")
    successor = {"agent": agent, "session": session}
    predecessor = read_live_predecessor(cwd=cwd, issue=issue)
    events = _read_task_events(cwd=cwd, task_id=predecessor["task_id"])
    claims = [row for row in events if row.get("event_type") == "task.claimed"]
    if (predecessor.get("session") is not None or len(claims) != 1
            or claims[0].get("lease_id") != predecessor["lease_id"]
            or any(row.get("event_type") in {"task.released", "task.completed"} for row in events)
            or event_history_digest(events) != predecessor["history_digest"]):
        raise RecoveryEvidenceError("legacy claimant history is not eligible for operator pickup")
    # Match the actual downstream claimant rules before any claim is written.
    from app.builderops import closure, openhands_pr_cycle
    try:
        old_at = closure._parse_timestamp(claims[0].get("timestamp"), "legacy claim")
        expiry = openhands_pr_cycle._predecessor_lease_expiry(
            {"claim": claims[0], "claimed_at": old_at, "events": events},
            datetime.fromtimestamp(pending_at, timezone.utc))
        if expiry.timestamp() != _timestamp(predecessor["expires_at"]):
            raise RecoveryEvidenceError("legacy lease expiry differs from claimant history")
        pages = json.loads(_github_read(["--method", "GET", "--paginate", "--slurp",
                           f"repos/RasmusTho/agentic-pkm-mvp/issues/{issue}/comments", "-f", "per_page=100"], cwd=cwd))
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise RecoveryEvidenceError("fallback claimant history is unavailable")
        for item in (row for page in pages for row in page):
            if not openhands_pr_cycle._authenticated_comment(item):
                continue
            match = closure.PICKUP_RECEIPT_RE.fullmatch(str(item.get("body", "")))
            if (match and match["issue"] == str(issue)
                    and _timestamp(item.get("created_at")) + 1 > old_at.timestamp()):
                raise RecoveryEvidenceError("fallback claimant history conflicts with operator pickup")
    except RecoveryEvidenceError:
        raise
    except (ValueError, KeyError, TypeError, closure.ClosureError, openhands_pr_cycle.CycleError) as exc:
        raise RecoveryEvidenceError("legacy claimant history is unavailable or ambiguous") from exc
    candidate = read_clean_candidate(cwd=cwd, worktree=worktree)
    registration = read_expired_registration(cwd=cwd, candidate=candidate)
    publication_live = read_live_publication(cwd=cwd, pr=pr, branch=candidate["branch"])
    _verify_pr_origin(cwd=cwd, issue=issue, pr=pr, worktree=worktree, candidate=candidate,
                      predecessor=predecessor, publication=publication_live)
    publication_recorded = receipt.get("publication")
    if not isinstance(publication_recorded, dict):
        raise RecoveryEvidenceError("publication reconciliation is missing")
    if publication_recorded.get("state") != "reconciled":
        raise RecoveryEvidenceError("writer, restart or publication outcome is unknown")
    # Reconciliation is the operator's source-backed historical observation;
    # a current open-PR readback does not itself establish that observation.
    comparable_publication = {k: v for k, v in publication_recorded.items() if k not in {"state", "sources"}}
    if comparable_publication != {k: v for k, v in publication_live.items() if k != "state"}:
        raise RecoveryEvidenceError("publication changed since the operator observation")
    publication = publication_recorded
    writer = receipt.get("writer")
    if not isinstance(writer, dict):
        raise RecoveryEvidenceError("writer observation is missing")
    transfer_fields = {"branch", "writable_worktree", "predecessor_registration", "branch_history_digest",
                       "base", "unpublished_candidate_head", "changed_files"}
    if not transfer_fields <= receipt.keys() or "successor_acknowledgment" in receipt:
        raise RecoveryEvidenceError("pending operator transfer fields are missing")
    try:
        snapshot = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(cwd))
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("predecessor registration readback is unavailable") from exc
    if snapshot.get(str(worktree)) != receipt.get("predecessor_registration"):
        raise RecoveryEvidenceError("predecessor registration changed after the operator observation")
    if agent_worktree._branch_history_digest(snapshot, candidate["branch"]) != registration["branch_history_digest"]:
        raise RecoveryEvidenceError("branch history changed after the operator observation")
    checked, created_at, digest = validate_operator_reconciliation(
        comment, issue=issue, pr=pr, github_login="RasmusTho", successor=successor,
        predecessor=predecessor, registration=registration, candidate=candidate,
        writer=writer, publication=publication,
    )
    try:
        agent_worktree._operator_candidate(cwd, worktree=worktree, receipt=checked,
                                           base_sha=checked["base"], observed_at=time.time())
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator candidate or base is unavailable before claim") from exc
    return {"pending_comment": comment, "pending_digest": digest, "pending_created_at": created_at,
            "receipt": checked, "predecessor": predecessor, "registration": registration,
            "candidate": candidate, "publication": publication_live}


def _successor_claim_readback(*, cwd: Path, task_id: str, issue: int, agent: str, session: str,
                              claim_id: str, predecessor: Mapping[str, Any]) -> str:
    paths = load_dispatcher_paths({}, cwd=cwd)
    env = {**os.environ, "DISPATCHER_STATE_DIR": str(paths.state_dir)}
    try:
        result = subprocess.run([sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryEvidenceError("successor claim readback is unavailable; retain claim") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise RecoveryEvidenceError("successor claim readback is unavailable; retain claim")
    task, lease, events = payload.get("task"), payload.get("lease"), payload.get("events")
    if (not isinstance(task, dict) or not isinstance(lease, dict) or not isinstance(events, list)
            or any(not isinstance(event, dict) for event in events)):
        raise RecoveryEvidenceError("successor claim readback is incomplete; retain claim")
    lease_id = lease.get("lease_id")
    matches = [event for event in events if isinstance(event, dict) and event.get("event_type") == "task.claimed"
               and event.get("lease_id") == lease_id and event.get("actor") == agent]
    event = matches[0] if len(matches) == 1 else {}
    ep = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    takeover = ep.get("takeover") if isinstance(ep.get("takeover"), dict) else {}
    event_index = events.index(event) if event else -1
    before = events[:event_index] if event_index >= 0 else []
    after = events[event_index + 1:] if event_index >= 0 else []
    from app.builderops import closure, openhands_pr_cycle
    try:
        history_matches = event_history_digest(before) == predecessor.get("history_digest")
        expiry_future = _timestamp(lease.get("expires_at")) > datetime.now(timezone.utc).timestamp()
        claimed_at = closure._parse_timestamp(event.get("timestamp"), "successor claim")
        observed_expiry = openhands_pr_cycle._predecessor_lease_expiry(
            {"claim": event, "claimed_at": claimed_at, "events": events}, datetime.now(timezone.utc))
        expiry_matches = observed_expiry.timestamp() == _timestamp(lease.get("expires_at"))
    except (ValueError, RecoveryEvidenceError):
        history_matches, expiry_future, expiry_matches = False, False, False
    except (closure.ClosureError, openhands_pr_cycle.CycleError):
        history_matches, expiry_future, expiry_matches = False, False, False
    if (task.get("task_id") != task_id or task.get("repo") != "RasmusTho/agentic-pkm-mvp"
            or task.get("issue_number") != issue or task.get("status") not in {"claimed", "in_progress"}
            or task.get("claimed_by") != agent or task.get("lease_expires_at") != lease.get("expires_at")
            or task.get("lease_id") != lease_id or lease.get("holder") != agent
            or lease.get("resource") != f"issue:{issue}" or lease.get("released_at") is not None
            or not expiry_future or not isinstance(lease_id, str) or not lease_id
            or ep.get("session") != session or ep.get("claim_id") != claim_id
            or takeover.get("previous_lease_id") != predecessor.get("lease_id")
            or takeover.get("previous_holder") != predecessor.get("holder")
            or takeover.get("previous_expires_at") != predecessor.get("expires_at")
            or not history_matches or not expiry_matches
            or any(item.get("event_type") != "task.heartbeat" or item.get("actor") != agent
                   or item.get("lease_id") != lease_id for item in after)):
        raise RecoveryEvidenceError("successor claim is ambiguous; retain claim and reconcile")
    return lease_id


def _read_unique_operator_ack(*, cwd: Path, issue: int, pr: int, pending: Mapping[str, Any],
                              expected_ack: Mapping[str, Any]) -> dict[str, Any]:
    try:
        pages = json.loads(_github_read(["--method", "GET", "--paginate", "--slurp",
                   f"repos/RasmusTho/agentic-pkm-mvp/issues/{issue}/comments", "-f", "per_page=100"], cwd=cwd))
    except (ValueError, TypeError) as exc:
        raise RecoveryEvidenceError("ACK readback is unavailable; retain prepared registration") from exc
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise RecoveryEvidenceError("ACK readback is unavailable; retain prepared registration")
    matches = []
    for comment in (item for page in pages for item in page):
        try:
            ack, _, _ = agent_worktree._transfer_comment(comment, issue=issue, pr=pr,
                                                          receipt_key="operator_reconciliation.v1")
        except agent_worktree.WorktreeLifecycleError:
            continue
        if ({k: v for k, v in ack.items() if k != "successor_acknowledgment"} == pending
                and ack.get("successor_acknowledgment") == expected_ack):
            matches.append(comment)
    if len(matches) != 1 or type(matches[0].get("id")) is not int:
        raise RecoveryEvidenceError("ACK outcome is unknown or ambiguous; retain prepared registration")
    try:
        fresh = agent_worktree._read_github_transfer_comment(matches[0]["id"], cwd=cwd)
        _, _, digest = agent_worktree._transfer_comment(fresh, issue=issue, pr=pr,
                                                        receipt_key="operator_reconciliation.v1")
        _, _, listed_digest = agent_worktree._transfer_comment(matches[0], issue=issue, pr=pr,
                                                               receipt_key="operator_reconciliation.v1")
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("ACK changed during readback; retain prepared registration") from exc
    if (fresh.get("id") != matches[0]["id"] or fresh.get("created_at") != matches[0].get("created_at")
            or digest != listed_digest):
        raise RecoveryEvidenceError("ACK changed during readback; retain prepared registration")
    return fresh


def _post_and_pin_operator_ack(*, cwd: Path, issue: int, pr: int, worktree: Path, session: str,
                               workspace_root: Path, pending_comment: dict[str, Any],
                               receipt: dict[str, Any], prepared: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    try:
        pages = json.loads(_github_read(["--method", "GET", "--paginate", "--slurp",
                           f"repos/RasmusTho/agentic-pkm-mvp/issues/{issue}/comments", "-f", "per_page=100"], cwd=cwd))
    except (ValueError, TypeError) as exc:
        raise RecoveryEvidenceError("prior ACK readback is unavailable; retain prepared registration") from exc
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise RecoveryEvidenceError("prior ACK readback is unavailable; retain prepared registration")
    for comment in (item for page in pages for item in page):
        try:
            prior_ack, _, _ = agent_worktree._transfer_comment(comment, issue=issue, pr=pr,
                                                                receipt_key="operator_reconciliation.v1")
        except agent_worktree.WorktreeLifecycleError:
            continue
        if ("successor_acknowledgment" in prior_ack
                and {k: v for k, v in prior_ack.items() if k != "successor_acknowledgment"} == receipt):
            raise RecoveryEvidenceError("a prior ACK exists; reconcile it without reposting")
    try:
        intent = agent_worktree.begin_operator_ack(cwd, worktree=worktree, owner=session, issue=issue,
                    pr=pr, pending_comment=pending_comment, workspace_root=workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("ACK intent could not be established; retain prepared registration") from exc
    prepared = {**prepared, "ack_attempt_id": intent["attempt_id"]}
    target_time = max(prepared["successor_registration"]["observed_at"], prepared["candidate_readback"]["observed_at"],
                      intent["intent_at"])
    time.sleep(max(0.0, int(target_time) + 1.1 - time.time()))
    ack_body = json.dumps({"operator_reconciliation.v1": {**receipt, "successor_acknowledgment": prepared}}, sort_keys=True)
    try:
        posted = subprocess.run(["gh", "api", "--hostname", "github.com", "--method", "POST",
                                 f"repos/RasmusTho/agentic-pkm-mvp/issues/{issue}/comments", "--input", "-"],
                                cwd=cwd, input=json.dumps({"body": ack_body}), capture_output=True, text=True,
                                timeout=30, check=False)
        response = json.loads(posted.stdout) if posted.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        response = None
    ack_id = response.get("id") if isinstance(response, dict) else None
    if type(ack_id) is not int or ack_id <= 0:
        raise RecoveryEvidenceError("ACK publication outcome unknown; retain claim and prepared registration")
    try:
        ack_comment = _read_unique_operator_ack(cwd=cwd, issue=issue, pr=pr, pending=receipt, expected_ack=prepared)
        if ack_comment.get("id") != ack_id or ack_comment.get("body") != ack_body:
            raise RecoveryEvidenceError("ACK readback changed; retain prepared registration")
        time.sleep(max(0.0, _timestamp(ack_comment.get("created_at")) + 1.1 - time.time()))
        pinned = agent_worktree.pin_operator_registration(cwd, worktree=worktree, owner=session, issue=issue,
                    pr=pr, pending_comment=pending_comment, ack_comment=ack_comment, workspace_root=workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator ACK pin failed; retain claim and registration") from exc
    return ack_id, pinned


def _execute_operator_pickup(*, cwd: Path, issue: int, pr: int, worktree: Path, agent: str, session: str,
                            comment_id: int, workspace_root: Path) -> dict[str, Any]:
    """Execute the supported operator transition after wrapper issue checks.

    Failed or ambiguous writes are retained for reconciliation, never released
    or blindly retried. The caller must still apply all delivery consumers.
    """
    preflight = preflight_operator_pickup(cwd=cwd, issue=issue, pr=pr, worktree=worktree,
                                         agent=agent, session=session, comment_id=comment_id,
                                         workspace_root=workspace_root)
    prior, registration, candidate = preflight["predecessor"], preflight["registration"], preflight["candidate"]
    receipt, pending_comment = preflight["receipt"], preflight["pending_comment"]
    delay = max(0.0, preflight["pending_created_at"] + 1.05 - time.time())
    if delay:
        time.sleep(delay)
    task_id, claim_id = prior["task_id"], uuid.uuid4().hex
    args = [sys.executable, "-m", "app.dispatcher", "claim", task_id, "--agent", agent, "--session", session,
            "--claim-id", claim_id, "--takeover-stale", "--expected-lease-id", prior["lease_id"],
            "--expected-lease-holder", prior["holder"], "--expected-lease-expires-at", prior["expires_at"],
            "--expected-claim-event-id", prior["claim_event_id"], "--expected-claim-event-digest", prior["claim_event_digest"],
            "--expected-history-digest", prior["history_digest"], "--expected-repo", prior["repo"],
            "--expected-issue-number", str(issue), "--json"]
    paths = load_dispatcher_paths({}, cwd=cwd)
    try:
        claim = subprocess.run(args, cwd=cwd, env={**os.environ, "DISPATCHER_STATE_DIR": str(paths.state_dir)},
                               capture_output=True, text=True, timeout=30, check=False)
        claim_exit = claim.returncode
    except (OSError, subprocess.SubprocessError):
        claim_exit = None
    lease_id = _successor_claim_readback(cwd=cwd, task_id=task_id, issue=issue, agent=agent, session=session,
                                         claim_id=claim_id, predecessor=prior)
    # Re-read the operator decision and external state after claim, before the
    # registry write; a drift leaves the exact claim retained and unadmitted.
    if agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd) != pending_comment:
        raise RecoveryEvidenceError("operator decision changed after claim; retain claim")
    if read_live_publication(cwd=cwd, pr=pr, branch=candidate["branch"]) != preflight["publication"]:
        raise RecoveryEvidenceError("PR changed after claim; retain claim")
    try:
        prepared = agent_worktree.prepare_operator_registration(
            cwd, worktree=worktree, owner=session, issue=issue, pr=pr, pending_comment=pending_comment,
            base_sha=receipt["base"], workspace_root=workspace_root,
            expected_branch_history_digest=registration["branch_history_digest"])
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator registration failed; retain claim") from exc
    ack_id, pinned = _post_and_pin_operator_ack(cwd=cwd, issue=issue, pr=pr, worktree=worktree, session=session,
                      workspace_root=workspace_root, pending_comment=pending_comment, receipt=receipt, prepared=prepared)
    _successor_claim_readback(cwd=cwd, task_id=task_id, issue=issue, agent=agent, session=session,
                              claim_id=claim_id, predecessor=prior)
    pickup_receipt = (f"pickup-claim-complete issue={issue} branch={candidate['branch']} worktree={worktree} "
                      f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                      f"lease_id={lease_id} holder={agent} evidence=verified-dispatcher-lease")
    return {"task_id": task_id, "lease_id": lease_id, "holder": agent, "session": session,
            "claim_exit": claim_exit, "pending_comment_id": comment_id, "ack_comment_id": ack_id,
            "registration_epoch": pinned["epoch"], "state": "pinned", "pickup_receipt": pickup_receipt}


def _resume_operator_pickup(*, cwd: Path, issue: int, pr: int, worktree: Path, agent: str, session: str,
                           comment_id: int, workspace_root: Path) -> dict[str, Any]:
    """Reconcile an existing claim and exact ACK without repeating a write."""
    if not session or session != os.environ.get("CODEX_SESSION_ID"):
        raise RecoveryEvidenceError("current Builder successor session is unavailable")
    try:
        agent_worktree._screen_transfer_workspace(cwd, worktree, workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator workspace boundary is invalid") from exc
    try:
        pending_comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
        pending, pending_at, pending_digest = agent_worktree._transfer_comment(
            pending_comment, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1")
        values = {name: pending[name] for name in ("successor", "predecessor", "registration", "candidate", "writer", "publication")}
        validate_operator_reconciliation(pending_comment, issue=issue, pr=pr, github_login="RasmusTho", **values)
    except (KeyError, agent_worktree.WorktreeLifecycleError) as exc:
        raise RecoveryEvidenceError("operator decision is unavailable") from exc
    if (pending.get("successor") != {"agent": agent, "session": session}
            or pending.get("writable_worktree") != str(worktree)
            or "successor_acknowledgment" in pending):
        raise RecoveryEvidenceError("operator successor or worktree changed")
    if _github_read(["user", "--jq", ".login"], cwd=cwd).strip() != "RasmusTho":
        raise RecoveryEvidenceError("operator account is not the authenticated repository owner")
    candidate = read_clean_candidate(cwd=cwd, worktree=worktree)
    live_pr = read_live_publication(cwd=cwd, pr=pr, branch=candidate["branch"])
    _verify_pr_origin(cwd=cwd, issue=issue, pr=pr, worktree=worktree, candidate=candidate,
                      predecessor=pending["predecessor"], publication=live_pr)
    recorded_pr = pending["publication"]
    comparable_publication = {k: v for k, v in recorded_pr.items() if k not in {"state", "sources"}}
    if (candidate != pending.get("candidate")
            or {k: v for k, v in live_pr.items() if k != "state"} != comparable_publication):
        raise RecoveryEvidenceError("candidate or PR changed before operator continuation")
    task_id = pending["predecessor"]["task_id"]
    paths = load_dispatcher_paths({}, cwd=cwd)
    try:
        current = subprocess.run([sys.executable, "-m", "app.dispatcher", "show", task_id, "--events", "--json"],
                                 cwd=cwd, env={**os.environ, "DISPATCHER_STATE_DIR": str(paths.state_dir)},
                                 capture_output=True, text=True, timeout=30, check=False)
        payload = json.loads(current.stdout) if current.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RecoveryEvidenceError("successor claim readback is unavailable; retain state") from exc
    events = payload.get("events") if isinstance(payload, dict) else None
    claims = [row for row in events or [] if isinstance(row, dict) and row.get("event_type") == "task.claimed"
              and row.get("actor") == agent and isinstance(row.get("payload"), dict)
              and row["payload"].get("session") == session
              and isinstance(row["payload"].get("takeover"), dict)
              and row["payload"]["takeover"].get("previous_lease_id") == pending["predecessor"]["lease_id"]]
    if (len(claims) != 1 or not isinstance(claims[0]["payload"].get("claim_id"), str)
            or _timestamp(claims[0].get("timestamp")) < pending_at + 1):
        raise RecoveryEvidenceError("successor claim identity is ambiguous; retain state")
    lease_id = _successor_claim_readback(cwd=cwd, task_id=task_id, issue=issue, agent=agent, session=session,
                    claim_id=claims[0]["payload"]["claim_id"], predecessor=pending["predecessor"])
    registry = agent_worktree._default_registry_path(cwd)
    row = agent_worktree._locked_lifecycle_snapshot(registry).get(str(worktree))
    proof = row.get("operator_registration") if isinstance(row, dict) else None
    if row == pending.get("predecessor_registration") and proof is None:
        registration = read_expired_registration(cwd=cwd, candidate=candidate)
        if registration != pending.get("registration"):
            raise RecoveryEvidenceError("predecessor registration changed; retain claim")
        try:
            prepared = agent_worktree.prepare_operator_registration(
                cwd, worktree=worktree, owner=session, issue=issue, pr=pr, pending_comment=pending_comment,
                base_sha=pending["base"], workspace_root=workspace_root,
                expected_branch_history_digest=registration["branch_history_digest"])
        except agent_worktree.WorktreeLifecycleError as exc:
            raise RecoveryEvidenceError("operator registration could not be resumed; retain claim") from exc
        ack_id, pinned = _post_and_pin_operator_ack(cwd=cwd, issue=issue, pr=pr, worktree=worktree,
                            session=session, workspace_root=workspace_root, pending_comment=pending_comment,
                            receipt=pending, prepared=prepared)
        _successor_claim_readback(cwd=cwd, task_id=task_id, issue=issue, agent=agent, session=session,
                                  claim_id=claims[0]["payload"]["claim_id"], predecessor=pending["predecessor"])
        return {"task_id": task_id, "lease_id": lease_id, "holder": agent, "session": session,
                "pending_comment_id": comment_id, "ack_comment_id": ack_id, "registration_epoch": pinned["epoch"],
                "state": "pinned", "pickup_receipt": (f"pickup-claim-complete issue={issue} branch={candidate['branch']} "
                  f"worktree={worktree} coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                  f"lease_id={lease_id} holder={agent} evidence=verified-dispatcher-lease")}
    if (not isinstance(proof, dict) or proof.get("state") not in {"prepared", "pinned"}
            or proof.get("pending_comment_id") != comment_id or proof.get("pending_digest") != pending_digest
            or row.get("owner") != session or proof.get("epoch") != row.get("registration_epoch")):
        raise RecoveryEvidenceError("prepared operator registration is unavailable; retain claim")
    prepared = {"successor_registration": {"path": str(worktree), "branch": candidate["branch"],
                    "owner": session, "generation": candidate["generation"], "epoch": proof["epoch"],
                    "observed_at": proof["registration_read_at"]}, "candidate_readback": proof["candidate_readback"]}
    if proof.get("ack_intent") is None:
        ack_id, pinned = _post_and_pin_operator_ack(cwd=cwd, issue=issue, pr=pr, worktree=worktree, session=session,
                            workspace_root=workspace_root, pending_comment=pending_comment, receipt=pending,
                            prepared=prepared)
        return {"task_id": task_id, "lease_id": lease_id, "holder": agent, "session": session,
                "pending_comment_id": comment_id, "ack_comment_id": ack_id, "registration_epoch": pinned["epoch"],
                "state": "pinned", "pickup_receipt": (f"pickup-claim-complete issue={issue} branch={candidate['branch']} "
                  f"worktree={worktree} coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                  f"lease_id={lease_id} holder={agent} evidence=verified-dispatcher-lease")}
    intent = proof.get("ack_intent")
    if not isinstance(intent, dict) or not isinstance(intent.get("attempt_id"), str):
        raise RecoveryEvidenceError("ACK intent is ambiguous; retain prepared registration")
    expected_ack = {**prepared, "ack_attempt_id": intent["attempt_id"]}
    try:
        ack_comment = _read_unique_operator_ack(cwd=cwd, issue=issue, pr=pr,
                                                pending=pending, expected_ack=expected_ack)
        ack_id = ack_comment["id"]
        time.sleep(max(0.0, _timestamp(ack_comment.get("created_at")) + 1.1 - time.time()))
        pinned = agent_worktree.pin_operator_registration(cwd, worktree=worktree, owner=session, issue=issue,
                   pr=pr, pending_comment=pending_comment, ack_comment=ack_comment, workspace_root=workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator pin could not be reconciled; retain state") from exc
    return {"task_id": task_id, "lease_id": lease_id, "holder": agent, "session": session,
            "pending_comment_id": comment_id, "ack_comment_id": ack_id,
            "registration_epoch": pinned["epoch"], "state": "pinned",
            "pickup_receipt": (f"pickup-claim-complete issue={issue} branch={candidate['branch']} worktree={worktree} "
                               f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                               f"lease_id={lease_id} holder={agent} evidence=verified-dispatcher-lease")}


def _fenced_pickup(operation: Any, *, run_state_root: Path, cwd: Path, issue: int, pr: int,
                   worktree: Path, agent: str, session: str, comment_id: int,
                   workspace_root: Path) -> dict[str, Any]:
    from app.builderops import legacy_run_fence

    try:
        agent_worktree._screen_transfer_workspace(cwd, worktree, workspace_root)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator workspace boundary is invalid") from exc
    try:
        with legacy_run_fence.hold(state_root=run_state_root, issue=issue, worktree=worktree):
            result = operation(cwd=cwd, issue=issue, pr=pr, worktree=worktree, agent=agent,
                               session=session, comment_id=comment_id, workspace_root=workspace_root)
            row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(cwd)).get(str(worktree))
            proof = row.get("operator_registration") if isinstance(row, dict) else None
            if (not isinstance(proof, dict) or row.get("owner") != session
                    or proof.get("state") != "pinned" or proof.get("epoch") != result.get("registration_epoch")):
                raise RecoveryEvidenceError("successor registration changed; retain claim")
            comment = agent_worktree._read_github_transfer_comment(comment_id, cwd=cwd)
            pending, _, _ = agent_worktree._transfer_comment(
                comment, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1")
            predecessor = pending["predecessor"]
            events = _read_task_events(cwd=cwd, task_id=result["task_id"])
            claims = [event for event in events if event.get("event_type") == "task.claimed"
                      and event.get("actor") == agent and isinstance(event.get("payload"), dict)
                      and event["payload"].get("session") == session
                      and isinstance(event["payload"].get("takeover"), dict)
                      and event["payload"]["takeover"].get("previous_lease_id") == predecessor["lease_id"]]
            if len(claims) != 1 or not isinstance(claims[0]["payload"].get("claim_id"), str):
                raise RecoveryEvidenceError("successor claim identity changed; retain claim")
            current_lease = _successor_claim_readback(cwd=cwd, task_id=result["task_id"], issue=issue,
                agent=agent, session=session, claim_id=claims[0]["payload"]["claim_id"], predecessor=predecessor)
            if current_lease != result["lease_id"]:
                raise RecoveryEvidenceError("successor lease changed; retain claim")
            legacy_run_fence.check_locked(state_root=run_state_root, issue=issue, worktree=worktree)
            return result
    except legacy_run_fence.RunFenceError as exc:
        raise RecoveryEvidenceError(str(exc)) from exc


def execute_operator_pickup(*, run_state_root: Path, cwd: Path, issue: int, pr: int, worktree: Path,
                            agent: str, session: str, comment_id: int, workspace_root: Path) -> dict[str, Any]:
    return _fenced_pickup(_execute_operator_pickup, run_state_root=run_state_root, cwd=cwd, issue=issue,
                          pr=pr, worktree=worktree, agent=agent, session=session, comment_id=comment_id,
                          workspace_root=workspace_root)


def resume_operator_pickup(*, run_state_root: Path, cwd: Path, issue: int, pr: int, worktree: Path,
                           agent: str, session: str, comment_id: int, workspace_root: Path) -> dict[str, Any]:
    return _fenced_pickup(_resume_operator_pickup, run_state_root=run_state_root, cwd=cwd, issue=issue,
                          pr=pr, worktree=worktree, agent=agent, session=session, comment_id=comment_id,
                          workspace_root=workspace_root)


def validate_operator_reconciliation(
    comment: Mapping[str, Any],
    *,
    issue: int,
    pr: int,
    github_login: str,
    successor: Mapping[str, Any],
    predecessor: Mapping[str, Any],
    registration: Mapping[str, Any],
    candidate: Mapping[str, Any],
    writer: Mapping[str, Any],
    publication: Mapping[str, Any],
) -> tuple[dict[str, Any], float, str]:
    """Compare an account-authenticated comment to caller-provided values.

    No current transfer pin accepts this operator type. The digest does not
    authorize any effect, and the caller must re-read and verify each source
    immediately before mutation. Account authentication does not establish
    that a human personally wrote the comment or that a session is live. This
    first comparison supports the post-execution reboot case only; other
    legitimate stop evidence requires a separate verified path. An operator
    receipt must never masquerade as predecessor consent.
    """
    if github_login != "RasmusTho":
        raise RecoveryEvidenceError("operator account is not the authenticated repository owner")
    try:
        receipt, created_at, digest = agent_worktree._transfer_comment(
            comment, issue=issue, pr=pr, receipt_key="operator_reconciliation.v1"
        )
    except agent_worktree.WorktreeLifecycleError as exc:
        raise RecoveryEvidenceError("operator receipt is not authenticated") from exc

    operator = receipt
    if operator.get("mode") != "operator":
        raise RecoveryEvidenceError("receipt is not an operator reconciliation")
    basic_fields = {"issue", "mode", "account", "mandate", "successor", "predecessor", "registration",
                    "candidate", "writer", "publication"}
    transfer_fields = {"branch", "writable_worktree", "predecessor_registration", "branch_history_digest",
                       "base", "unpublished_candidate_head", "changed_files"}
    if set(operator) not in (basic_fields, basic_fields | transfer_fields,
                             basic_fields | transfer_fields | {"successor_acknowledgment"}):
        raise RecoveryEvidenceError("operator receipt has unexpected or missing fields")
    if operator.get("issue") != issue or operator.get("account") != github_login:
        raise RecoveryEvidenceError("operator receipt targets another issue or account")
    mandate = operator.get("mandate")
    if (not isinstance(mandate, dict) or set(mandate) != {"reference", "effects", "repo", "issue"}
            or not isinstance(mandate.get("reference"), str) or not mandate["reference"].strip()
            or mandate.get("repo") != "RasmusTho/agentic-pkm-mvp" or mandate.get("issue") != issue
            or mandate.get("effects") != ["reconcile", "claim", "register", "acknowledge"]):
        raise RecoveryEvidenceError("explicit, scoped operator mandate is missing")
    for name, observed in (
        ("successor", successor),
        ("predecessor", predecessor),
        ("registration", registration),
        ("candidate", candidate),
        ("writer", writer),
        ("publication", publication),
    ):
        if not isinstance(observed, Mapping) or not observed or operator.get(name) != dict(observed):
            raise RecoveryEvidenceError(f"{name} changed or could not be independently observed")

    if (writer.get("state") != "stopped" or writer.get("delegations") != "stopped"
            or writer.get("restart") != "reconciled"
            or not _operator_sources(writer.get("sources"), {"execution", "delegations", "restart"})
            or publication.get("state") != "reconciled"
            or not _operator_sources(publication.get("sources"), {"attempts", "github"})):
        raise RecoveryEvidenceError("writer, restart or publication outcome is unknown")
    if (not isinstance(successor.get("agent"), str) or not successor["agent"]
            or not isinstance(successor.get("session"), str) or not successor["session"]
            or not isinstance(predecessor.get("holder"), str) or not predecessor["holder"]
            or not isinstance(predecessor.get("lease_id"), str) or not predecessor["lease_id"]
            or not isinstance(predecessor.get("claim_event_id"), str) or not predecessor["claim_event_id"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(predecessor.get("claim_event_digest", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(predecessor.get("history_digest", "")))
            or predecessor.get("repo") != "RasmusTho/agentic-pkm-mvp" or predecessor.get("issue_number") != issue
            or predecessor.get("task_id") != f"github-RasmusTho--agentic-pkm-mvp-issue-{issue}"
            or not Path(str(candidate.get("path", ""))).is_absolute()
            or not isinstance(candidate.get("branch"), str) or not candidate["branch"]
            or not re.fullmatch(r"[0-9a-f]{32}", str(candidate.get("generation", "")))
            or not re.fullmatch(r"[0-9a-f]{40,64}", str(candidate.get("head", "")))
            or not re.fullmatch(r"[0-9a-f]{40,64}", str(candidate.get("tree", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("status_digest", "")))):
        raise RecoveryEvidenceError("reconciliation identity or candidate is incomplete")
    if (registration.get("state") != "expired" or not isinstance(registration.get("owner"), str)
            or not registration["owner"] or any(registration.get(k) != candidate.get(k)
                                                for k in ("path", "branch", "generation"))
            or not re.fullmatch(r"[0-9a-f]{64}", str(registration.get("history_digest", "")))
            or (predecessor.get("session") is not None and predecessor.get("session") != registration["owner"])):
        raise RecoveryEvidenceError("predecessor registration does not match the candidate")
    if successor.get("session") in (predecessor.get("session"), registration.get("owner")):
        raise RecoveryEvidenceError("successor must have its own session")
    if transfer_fields <= operator.keys():
        prior = operator["predecessor_registration"]
        if (not isinstance(prior, dict) or operator["branch"] != candidate.get("branch")
                or operator["writable_worktree"] != candidate.get("path")
                or operator["unpublished_candidate_head"] != candidate.get("head")
                or operator["branch_history_digest"] != registration.get("branch_history_digest")
                or not re.fullmatch(r"[0-9a-f]{64}", str(operator["branch_history_digest"]))
                or not re.fullmatch(r"[0-9a-f]{40,64}", str(operator["base"]))
                or not isinstance(operator["changed_files"], list)
                or not all(isinstance(path, str) and path for path in operator["changed_files"])
                or sorted(set(operator["changed_files"])) != operator["changed_files"]
                or hashlib.sha256(json.dumps(prior, sort_keys=True).encode()).hexdigest()
                    != registration.get("history_digest")):
            raise RecoveryEvidenceError("operator receipt candidate or predecessor binding changed")
    if (publication.get("pr") != pr or publication.get("repo") != "RasmusTho/agentic-pkm-mvp"
            or publication.get("branch") != candidate.get("branch") or publication.get("pr_state") != "OPEN"
            or not re.fullmatch(r"[0-9a-f]{64}", str(publication.get("body_sha256", "")))
            or not re.fullmatch(r"[0-9a-f]{40,64}", str(publication.get("head", "")))):
        raise RecoveryEvidenceError("publication is not bound to an observed PR head")
    if (not _timestamp(writer.get("last_activity")) < _timestamp(writer.get("boot")) <= created_at
            or _timestamp(predecessor.get("expires_at")) > created_at
            or _timestamp(registration.get("registered_at")) >= _timestamp(registration.get("expires_at"))
            or _timestamp(registration.get("expires_at")) > created_at):
        raise RecoveryEvidenceError("writer or predecessor timing is not reconciled")
    return receipt, created_at, digest


def _main() -> int:
    parser = argparse.ArgumentParser(description="Scoped operator pickup through the Builder host")
    parser.add_argument("action", choices=["pickup", "resume"])
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--comment-id", type=int, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--legacy-run-state-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        operation = execute_operator_pickup if args.action == "pickup" else resume_operator_pickup
        result = operation(run_state_root=args.legacy_run_state_root, cwd=Path.cwd(), issue=args.issue, pr=args.pr, worktree=args.worktree,
                           agent=args.agent, session=args.session, comment_id=args.comment_id,
                           workspace_root=args.workspace_root)
    except (RecoveryEvidenceError, agent_worktree.WorktreeLifecycleError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    print(result["pickup_receipt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
