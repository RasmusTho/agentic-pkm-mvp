"""One bounded host-side advancement of the OpenHands PR completion trial.

This command is a controller, not a model runtime. It never supplies host GitHub
credentials to a worker. Admission is an explicit controller-owned configuration;
missing or ambiguous evidence is a wait, not authority to perform an effect.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from app.builderops import closure, epic_run_state, epic_workspace as workspace
from app.builderops import openhands_pr_completion as completion
from app.builderops import openhands_pr_observation as observation
from app.builderops.publication import SubprocessExecutor
from app.dispatcher.sync_github import github_issue_task_id
from app.dispatcher.verification_contract import has_closing_issue_attempt
from scripts import agent_worktree
from scripts.pr_body_generator import resolve_native_issue_authority


class CycleError(RuntimeError):
    """An observation or operation could not be safely established."""


CONTAINER_TEST_VENV = "/opt/pr-cycle-venv"
CODEX_CLI = "/acp-node/lib/node_modules/@agentclientprotocol/codex-acp/node_modules/@openai/codex/bin/codex.js"
_worker_runner: workspace.Runner = subprocess.run
CLAUDE_STATUS = (
    "import glob,os; p=glob.glob('/acp-node/lib/node_modules/@agentclientprotocol/claude-agent-acp/"
    "node_modules/@anthropic-ai/claude-agent-sdk-*/claude'); "
    "assert len(p)==1; os.execv(p[0],[p[0],'auth','status','--json'])"
)


def _command(argv: Sequence[str], *, timeout: float = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CycleError(f"{argv[0]} unavailable or timed out") from exc


def github_fetch(path: str, timeout: float) -> tuple[int, bytes]:
    """Authenticated GET using host gh; only the collector's closed path set is allowed."""
    if not observation._PATH.fullmatch(path):
        raise CycleError("GitHub path outside the collector allowlist")
    result = _command(["gh", "api", "--method", "GET", path.lstrip("/")], timeout=timeout)
    if result.returncode:
        raise CycleError("authenticated GitHub read failed")
    return 200, result.stdout.encode()


@contextmanager
def _single_advancement(layout: workspace.Layout) -> Iterator[None]:
    """Serialize effects across invocations, without holding a lock between scans."""
    directory = layout.run_state_dir
    if not directory.is_dir():
        raise CycleError("existing epic run-state directory is unavailable")
    with (directory / ".pr-cycle.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CycleError("another advancement is running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _save(layout: workspace.Layout, record: dict[str, Any], *, expected_worker: str | None = None,
          expected_assignment: Mapping[str, Any] | None = None) -> None:
    def update(state: dict[str, Any]) -> dict[str, Any]:
        if expected_worker is not None and expected_assignment is not None:
            issue = workspace._issue_for_worker(state, expected_worker)
            current = state["issue_mappings"][str(issue)]
            if (not workspace._same_assignment(current, expected_assignment)
                    or current.get("stop_id") != expected_assignment.get("stop_id")
                    or current.get("work_at_stop") != expected_assignment.get("work_at_stop")):
                raise CycleError("worker assignment changed before recording the review stop")
        rows = state["compact_receipts"]
        rows[:] = [r for r in rows if not (isinstance(r, dict) and r.get("kind") == "pr_cycle"
                   and r.get("number") == record["number"] and r.get("identity") == record["identity"])]
        rows.append(record)
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir,
                                         expected_epic_issue_number=layout.epic, updater=update)


def _find(layout: workspace.Layout, number: int, identity: str) -> dict[str, Any]:
    state = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)
    if state["epic_issue_number"] != layout.epic:
        raise CycleError("epic owner mismatch")
    matches = [x for x in state["compact_receipts"] if isinstance(x, dict) and x.get("kind") == "pr_cycle"
               and x.get("number") == number and x.get("identity") == identity]
    if len(matches) > 1:
        raise CycleError("ambiguous cycle state")
    return dict(matches[0]) if matches else {"kind": "pr_cycle", "number": number, "identity": identity}


def _receipt(binding: str, ref: str, *, key: str = "identity") -> dict[str, Any]:
    return {"status": "pass", "trusted": True, key: binding, "ref": ref}


def _assert_stopped(layout: workspace.Layout, worker: str, mapping: Mapping[str, Any]) -> None:
    ident = mapping.get("container_id")
    if mapping.get("state") != "stopped_verified" or not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{12,64}", ident):
        raise CycleError("prior worker identity or verified stop is unavailable")
    workspace._assert_engine(subprocess.run)
    if workspace._container_state(layout, worker, subprocess.run) is not None:
        raise CycleError("worker container is still present")
    result = _command(["docker", "inspect", ident], timeout=15)
    if result.returncode == 0 or not re.search(r"no such (?:object|container)", result.stderr, re.I):
        raise CycleError("recorded worker container absence is not established")


def _test_venv_source(layout: workspace.Layout, value: str) -> Path:
    """Accept only an explicit, privately controlled venv without credential-shaped files.

    It must be outside the model workspace root, which a worker could write, and
    must not contain that root, so the read-only mount never exposes it wholesale.
    """
    source = Path(value)
    if not source.is_absolute() or source.resolve() != source or not workspace._MOUNT_PATH.fullmatch(str(source)):
        raise CycleError("test environment path must be absolute and contain no symlinks")
    if workspace._is_within(source, layout.root) or workspace._is_within(layout.root, source):
        raise CycleError("test environment must be controller-owned outside the model workspace root")
    for parent in source.parents:
        info = parent.stat()
        if info.st_uid not in (0, os.geteuid()) or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
            raise CycleError("test environment parent ownership or mode is unsafe")
    def unreadable(exc: OSError) -> None:
        raise CycleError("test environment cannot be fully inspected") from exc

    for root, dirs, files in os.walk(source, followlinks=False, onerror=unreadable):
        for name in [".", *dirs, *files]:
            path = Path(root) / name
            info = path.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise CycleError("test environment contains a special file")
            if info.st_uid not in (0, os.geteuid()) or (not stat.S_ISLNK(info.st_mode) and info.st_mode & 0o022):
                raise CycleError("test environment ownership or mode is unsafe")
            if name.lower() in (".env", ".credentials", "credentials.json", "auth.json", ".netrc") or name.lower().endswith(".key"):
                raise CycleError("test environment contains credential-shaped files")
            if stat.S_ISLNK(info.st_mode):
                target = path.resolve()
                if not workspace._is_within(target, source) and not (
                    path.parent == source / "bin" and re.fullmatch(r"python(?:3(?:\.13)?)?", name)
                    and str(target) in ("/usr/local/bin/python3.13", "/usr/bin/python3.13",
                                        "/usr/local/bin/python3", "/usr/bin/python3")
                ):
                    raise CycleError("test environment symlink escapes its boundary")
    python = source / "bin" / "python"
    if not source.is_dir() or not (python.is_symlink() or python.is_file()) or not (source / "pyvenv.cfg").is_file():
        raise CycleError("approved test environment is unavailable")
    return source


def sandbox_verify(layout: workspace.Layout, worker: str, head: str, targets: list[str], test_venv: str,
                   saved: dict[str, Any]) -> dict[str, Any]:
    """Run explicitly selected pytest targets in a credential-free disposable container.

    A stopped worker is mandatory so its model and descendants cannot change the
    mounted tree while tests run. The worker checkout is never interpreted by host Git.
    """
    with workspace._worker_lifecycle_lock(layout, worker):
        return _sandbox_verify_locked(layout, worker, head, targets, test_venv, saved)


def _clear_verification_marker(layout: workspace.Layout, worker: str, expected: Mapping[str, Any]) -> None:
    def clear(entry: dict[str, Any]) -> None:
        if entry.get("checkpoint_inspection_unknown") != expected:
            raise CycleError("verification lifecycle marker changed; the newer hold is kept")
        entry.pop("checkpoint_inspection_unknown", None)

    workspace._mutate_mapping(layout, worker, clear)


def _settle_verification(layout: workspace.Layout, worker: str, intent: Any) -> None:
    if (not isinstance(intent, dict) or intent.get("protocol") != workspace.LAUNCH_PROTOCOL
            or intent.get("worker") != worker or not isinstance(intent.get("container"), str)
            or not workspace._INSPECT_NAME.fullmatch(intent["container"])):
        raise CycleError("legacy or mismatched verification intent requires reconciliation")
    name, cid = intent["container"], intent.get("container_id")
    marker = _mapping(layout, worker).get("checkpoint_inspection_unknown")
    if marker is not None and (not isinstance(marker, dict) or marker.get("name") != name
                               or marker.get("container_id") != cid
                               or marker.get("protocol") != workspace.LAUNCH_PROTOCOL):
        raise CycleError("verification lifecycle marker differs from the recorded intent")
    if cid is not None and (not isinstance(cid, str) or not workspace._CONTAINER_ID.fullmatch(cid)):
        raise CycleError("verification container identity is invalid")
    # Without an ID only create was issued; a late create stays inert. With an
    # ID, remove that exact object so a delayed start cannot recreate it.
    labels = {"epic-workspace.inspect": "1", workspace.LABEL_EPIC: str(layout.epic),
              workspace.LABEL_WORKER: f"verify-{worker}"}
    workspace._remove_owned(name, labels, subprocess.run, cid=cid)
    if marker is not None:
        _clear_verification_marker(layout, worker, marker)


def _sandbox_verify_locked(layout: workspace.Layout, worker: str, head: str, targets: list[str], test_venv: str,
                           saved: dict[str, Any]) -> dict[str, Any]:
    mapping = _mapping(layout, worker)
    if any(key in saved for key in ("execution_proof", "stop_intent", "stop_verified")):
        _review_stop_checkpoint(mapping, saved, require_receipt=True)
    image = mapping.get("image")
    if mapping.get("state") != "stopped_verified" or not isinstance(image, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}", image
    ):
        raise CycleError("verification requires a stopped worker and its digest-pinned image")
    _assert_stopped(layout, worker, mapping)
    state = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)
    legacy_name = f"epicws-{layout.epic}-verify-{worker}"
    for other in state["compact_receipts"]:
        if (not isinstance(other, dict) or other.get("kind") != "pr_cycle" or other.get("verification") is not None
                or other.get("verification_settled") is True
                or (other.get("number"), other.get("identity")) == (saved.get("number"), saved.get("identity"))):
            continue
        prior = other.get("verification_intent")
        if isinstance(prior, dict) and (prior.get("worker") == worker or prior.get("container") == legacy_name):
            _settle_verification(layout, worker, prior)
            other["verification_settled"] = True
            _save(layout, other)
    pattern = r"tests/[A-Za-z0-9_./-]+\.py(?:::[A-Za-z_][A-Za-z0-9_]*(?:\[[A-Za-z0-9_.-]+\])?)*"
    if not targets or any(not re.fullmatch(pattern, t) or ".." in Path(t.split("::")[0]).parts for t in targets):
        raise CycleError("Verify targets must be explicit pytest files or selectors")
    checkout = layout.checkout(worker)
    if not workspace._MOUNT_PATH.fullmatch(str(checkout.resolve())):
        raise CycleError("checkout path is unsuitable for a container mount")
    before = workspace.inspect_checkout(layout, worker)
    if before.get("readable") is not True or before.get("head") != head or before.get("uncommitted_count") != 0:
        raise CycleError("verification checkout is not clean at the reviewed head")
    source = _test_venv_source(layout, test_venv)
    labels = {"epic-workspace.inspect": "1", workspace.LABEL_EPIC: str(layout.epic),
              workspace.LABEL_WORKER: f"verify-{worker}"}
    previous = saved.get("verification_intent")
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get("protocol") != workspace.LAUNCH_PROTOCOL
                or previous.get("worker") != worker or previous.get("head_sha") != head
                or previous.get("targets") != targets or previous.get("test_venv") != test_venv):
            raise CycleError("legacy or mismatched verification intent requires reconciliation")
        _settle_verification(layout, worker, previous)
        saved["verification_previous_intent"] = dict(previous)
    if _mapping(layout, worker).get("checkpoint_inspection_unknown"):
        raise CycleError("another lifecycle inspection remains unresolved")

    name = f"{workspace.CONTAINER_PREFIX}-git-{uuid.uuid4().hex[:12]}"
    intent: dict[str, Any] = {"protocol": workspace.LAUNCH_PROTOCOL, "worker": worker,
                              "head_sha": head, "targets": list(targets), "test_venv": test_venv, "container": name}
    saved.pop("verification_settled", None)
    saved["verification_intent"] = intent
    _save(layout, saved)
    base = [
        "docker", "create", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--name", name, "--label", "epic-workspace.inspect=1",
        "--label", f"{workspace.LABEL_EPIC}={layout.epic}",
        "--label", f"{workspace.LABEL_WORKER}=verify-{worker}",
        "--security-opt", "no-new-privileges", "--user", workspace.WORKER_UID_GID,
        "--memory", "1536m", "--cpus", "1", "--pids-limit", "512",
        "--tmpfs", "/tmp:rw,nosuid,size=768m", "--mount", f"type=bind,source={checkout},target=/workspace,readonly",
        "--mount", f"type=bind,source={source},target={CONTAINER_TEST_VENV},readonly",
        "--workdir", "/workspace", "--env", "PYTHONPATH=/workspace", "--env", "HOME=/tmp",
        "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", f"{CONTAINER_TEST_VENV}/bin/python", image,
    ]
    script = ("import sys; "
              "sys.version_info[:2] == (3, 13) or sys.exit('unsupported test interpreter'); "
              "import pytest; raise SystemExit(pytest.main(['-q', *sys.argv[1:]]))")
    created = _command([*base, "-c", script, *targets], timeout=60)
    cid = created.stdout.strip()
    if created.returncode != 0 or not workspace._CONTAINER_ID.fullmatch(cid):
        raise CycleError("verification container create outcome is unknown; no start was issued")
    intent["container_id"] = cid
    _save(layout, saved)

    marker = {"at": workspace._now(), "protocol": workspace.LAUNCH_PROTOCOL, "name": name, "container_id": cid}

    def mark(entry: dict[str, Any]) -> None:
        if entry.get("checkpoint_inspection_unknown"):
            raise CycleError("another lifecycle inspection remains unresolved")
        entry["checkpoint_inspection_unknown"] = marker

    # Existing lifecycle starts and takeovers already honor this exact-ID hold.
    workspace._mutate_mapping(layout, worker, mark)
    try:
        result = _command(["docker", "start", "--attach", cid], timeout=600)
    finally:
        workspace._remove_owned(name, labels, subprocess.run, cid=cid)
        _clear_verification_marker(layout, worker, marker)
    after = workspace.inspect_checkout(layout, worker)
    if after.get("readable") is not True or after.get("head") != head or after.get("uncommitted_count") != 0:
        raise CycleError("verification checkout changed while testing")
    digest = hashlib.sha256((result.stdout + "\n" + result.stderr).encode()).hexdigest()
    summary = result.stdout + "\n" + result.stderr
    passed = bool(re.search(r"\b[1-9][0-9]* passed\b", summary))
    incomplete = bool(re.search(r"\b[1-9][0-9]* (?:skipped|xfailed|xpassed|deselected)\b", summary))
    return {"head_sha": head, "targets": targets, "exit_code": result.returncode,
            "passed": result.returncode == 0 and passed and not incomplete, "output_sha256": digest}


def ci_once(number: int, source_root: Path) -> dict[str, Any]:
    """Run the existing merge-gating CI helper with a short bounded wait."""
    script = source_root / "scripts" / "await_pr_checks.sh"
    if not script.is_file():
        raise CycleError("pinned controller CI helper unavailable")
    result = _command([str(script), str(number), "--repo", completion.REPOSITORY,
                       "--initial-wait", "0", "--timeout", "1"], timeout=90)
    return {"exit_code": result.returncode,
            "output_sha256": hashlib.sha256((result.stdout + "\n" + result.stderr).encode()).hexdigest()}


def _assert_review_threads_clear(executor: SubprocessExecutor, cwd: Path, number: int) -> None:
    query = """query($number:Int!){repository(owner:"RasmusTho",name:"agentic-pkm-mvp"){
      pullRequest(number:$number){reviewThreads(first:100){nodes{isResolved isOutdated}
      pageInfo{hasNextPage}}}}}"""
    result = executor.run(["gh", "api", "--hostname", "github.com", "graphql", "-f", f"query={query}",
                           "-F", f"number={number}"], cwd=cwd)
    try:
        payload = json.loads(result.stdout)
        if payload.get("errors"):
            raise CycleError("review thread readback contains GraphQL errors")
        rows = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        if (result.returncode or rows["pageInfo"]["hasNextPage"] is not False or not isinstance(rows["nodes"], list)
                or any(not isinstance(x, dict) or x.get("isResolved") is not True for x in rows["nodes"])):
            raise CycleError("review threads are unresolved or incomplete")
    except (AttributeError, ValueError, KeyError, TypeError) as exc:
        raise CycleError("review thread readback unavailable") from exc


def _assert_unheld_issue(issue: Mapping[str, Any]) -> None:
    labels = issue.get("labels")
    if (not isinstance(labels, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in labels)
            or {x["name"].casefold() for x in labels} & {"agent:blocked", "agent:needs-human", "agent:needs-review",
                                                       "hold", "do-not-merge", "do not merge", "wip", "work in progress"}):
        raise CycleError("Issue labels are held or unreadable")


def _lifecycle_owner(layout: workspace.Layout, entry: Mapping[str, Any], branch: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Use the host's existing registry, never Git against a model-owned checkout."""
    value = entry.get("lifecycle_repo")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise CycleError("host lifecycle repository is unavailable")
    source = Path(value)
    if str(source.resolve()) != value or not source.is_dir() or workspace._is_within(source, layout.root):
        raise CycleError("host lifecycle repository must be outside the worker workspace")
    try:
        # Hold the existing lifecycle fence while screening paths and binding
        # generations: the authority reader itself invokes git -C on them.
        with agent_worktree.locked_lifecycle_authority(source, candidate_branch=branch,
                                                       allow_released_history=True) as read_authority:
            records = agent_worktree.load_lifecycle_records(source)
            live = agent_worktree.git_hygiene._parse_worktrees(
                agent_worktree.git_hygiene.run_git(["worktree", "list", "--porcelain"], source))
            paths = [*records, *(row.get("worktree") for row in live)]
            if any(not isinstance(path, str) or workspace._is_within(Path(path).resolve(), layout.root) for path in paths):
                raise CycleError("lifecycle authority includes a model-controlled checkout")
            authority = read_authority()
            candidate_paths = {row.get("worktree") for row in live
                               if row.get("branch", "").removeprefix("refs/heads/") == branch}
            if len(candidate_paths) != 1:
                raise CycleError("candidate worktree registration is ambiguous")
    except (agent_worktree.WorktreeLifecycleError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise CycleError("host worktree lifecycle authority is unavailable") from exc
    active = [dict(row) for row in authority.values() if row.get("branch") == branch and row.get("status") == "active"]
    if len(active) != 1:
        raise CycleError("current registered worktree owner, generation or session is unavailable")
    expires = active[0].get("expires_at")
    if (active[0].get("owner") != entry.get("session")
            or active[0].get("path") != entry.get("owner_worktree")
            or not isinstance(expires, (int, float)) or expires <= time.time()
            or not isinstance(active[0].get("generation"), str)
            or not agent_worktree._valid_generation(active[0].get("registration_epoch"))):
        raise CycleError("current registered worktree owner, generation or session is unavailable")
    if any(row.get("branch") == branch and row.get("status") in ("removal_pending", "missing_preserved")
           for row in authority.values()):
        raise CycleError("prior worktree lifecycle state is unresolved")
    return active[0], records


def _authenticated_comment(comment: Any) -> bool:
    return (isinstance(comment, dict) and comment.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
            and isinstance(comment.get("user"), dict) and comment["user"].get("login") == "RasmusTho"
            and type(comment.get("id")) is int and comment["id"] > 0
            and isinstance(comment.get("created_at"), str))


def _fallback_comment(comments: list[Any], *, comment_id: int, issue: int, agent: str,
                      session: str, branch: str, path: str, reason: str) -> Any:
    matches = [row for row in comments if isinstance(row, dict) and row.get("id") == comment_id]
    if len(matches) != 1 or not _authenticated_comment(matches[0]):
        raise CycleError("fallback pickup comment is missing or unauthenticated")
    comment = matches[0]
    body = comment.get("body")
    match = closure.PICKUP_RECEIPT_RE.fullmatch(body) if isinstance(body, str) else None
    if (match is None or comment.get("issue_url") != f"https://api.github.com/repos/{completion.REPOSITORY}/issues/{issue}"
            or match.groupdict() != {"agent": agent, "session": session, "branch": branch, "worktree": path,
                                     "mode": closure.DEGRADED_MODE, "reason": reason, "issue": str(issue)}):
        raise CycleError("fallback pickup comment does not match its claimed owner")
    created = closure._parse_timestamp(comment.get("created_at"), "fallback pickup")
    if closure._parse_timestamp(comment.get("updated_at"), "fallback pickup update") != created:
        raise CycleError("edited fallback pickup comment is not authoritative")
    return created


def _pickup_origin(body: str, *, issue: int, closing: Sequence[int], branch: str,
                   comments: list[Any]) -> tuple[dict[str, str], Any]:
    """Bind the original PR pickup to its authenticated source when available."""
    receipts = re.findall(r"(?m)^Pickup-Receipt:[ \t]*(.+)$", body)
    if len(receipts) > 1:
        raise CycleError("original pickup provenance is ambiguous")
    if not receipts:
        return {}, None
    initial = re.fullmatch(r"pickup-claim-complete issue=([1-9][0-9]*) branch=(\S+) worktree=(.+?) "
                           r"coordination_mode=dispatcher-backed fallback_reason=none task_id=(\S+) "
                           r"lease_id=(\S+) holder=(\S+) evidence=verified-dispatcher-lease", receipts[0])
    fallback = re.fullmatch(r"pickup-claim-complete issue=([1-9][0-9]*) branch=(\S+) worktree=(.+?) "
                            r"coordination_mode=github-label-only-fallback fallback_reason=(\S+) "
                            r"agent=(\S+) session=(\S+) evidence=github-comment:([1-9][0-9]*)", receipts[0])
    if initial and int(initial[1]) == issue:
        if initial[2] != branch or initial[4] != github_issue_task_id(completion.REPOSITORY, issue):
            raise CycleError("original dispatcher pickup names the wrong branch or task")
        return {"mode": closure.DISPATCHER_MODE, "path": initial[3], "lease_id": initial[5], "agent": initial[6]}, None
    if fallback and int(fallback[1]) == issue:
        if fallback[2] != branch:
            raise CycleError("original fallback pickup names the wrong branch")
        origin = {"mode": closure.DEGRADED_MODE, "path": fallback[3], "reason": fallback[4],
                  "agent": fallback[5], "session": fallback[6], "comment_id": fallback[7]}
        at = _fallback_comment(comments, comment_id=int(fallback[7]), issue=issue, agent=fallback[5],
                               session=fallback[6], branch=branch, path=fallback[3], reason=fallback[4])
        return origin, at
    if not ((initial and int(initial[1]) in closing) or (fallback and int(fallback[1]) in closing)):
        raise CycleError("original pickup provenance cannot establish the governing owner")
    return {}, None


def _handoff_record(comments: list[Any], *, issue: int, pr_number: int, branch: str, head: str,
                    files: list[str], current: Mapping[str, Any], entry: Mapping[str, Any],
                    coordination: Mapping[str, Any], prior_agent: str | None, prior_session: str | None,
                    prior_path: str | None, prior_lease: str | None,
                    lineage: Mapping[str, Any] | None = None,
                    prior_registration: Mapping[str, Any] | None = None,
                    fallback_pickup_at: Any = None, fallback_origin_at: Any = None,
                    remote_prior: bool = False, historical: bool = False) -> None:
    """Read the existing lifecycle handoff and successor acknowledgment from GitHub.

    The latest record carries the acknowledgment. For a dispatcher-backed
    migration (``lineage``), the latest record without one is the receipt the
    predecessor posted before its release; its GitHub server times must fall in
    the released predecessor lease's live window, and the acknowledgment must
    follow the successor's own claim.
    """
    import yaml

    proof = current.get("transfer_registration")
    if not isinstance(proof, dict) or proof.get("state") != "pinned" or proof.get("issue") != issue:
        raise CycleError("historical transfer registration is unproved; reconcile through maintenance")

    class UniqueLoader(yaml.SafeLoader):
        pass

    def unique_mapping(loader: Any, node: Any) -> dict[Any, Any]:
        pairs = loader.construct_pairs(node)
        value: dict[Any, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate handoff field")
            value[key] = item
        return value

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
    records = []
    for comment in comments:
        if not _authenticated_comment(comment):
            continue
        body = comment.get("body")
        if not isinstance(body, str) or "lifecycle_handoff_receipt.v1" not in body:
            continue
        if len(body.encode()) > 65536:
            raise CycleError("lifecycle handoff receipt exceeds size bound")
        match = re.fullmatch(r"\s*```(?:yaml|yml|json)\s*\n(.*?)\n```\s*", body, re.S)
        try:
            payload = yaml.load(match.group(1) if match else body, Loader=UniqueLoader)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
            raise CycleError("lifecycle handoff receipt is malformed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("lifecycle_handoff_receipt.v1"), dict):
            raise CycleError("lifecycle handoff receipt is malformed")
        records.append((closure._parse_timestamp(comment["created_at"], "handoff receipt"), comment["id"],
                        payload["lifecycle_handoff_receipt.v1"], comment))
    if not records:
        raise CycleError("ownership migration lacks authenticated lifecycle handoff")
    records.sort(key=lambda item: (item[0], item[1]))
    if len(records) > 1 and records[-1][0] == records[-2][0]:
        raise CycleError("lifecycle handoff comment order is ambiguous")
    if not historical and records[-1][1] != proof.get("ack_comment_id"):
        raise CycleError("latest lifecycle handoff differs from the pinned transfer")
    acknowledged = [row for row in records if row[1] == proof.get("ack_comment_id")]
    if len(acknowledged) != 1:
        raise CycleError("pinned lifecycle acknowledgment is unavailable")
    acknowledged_at, _, receipt, ack_comment = acknowledged[0]
    predecessor, successor, ack = receipt.get("current_lifecycle_owner"), receipt.get("successor"), receipt.get("successor_acknowledgment")
    if not isinstance(predecessor, dict) or not isinstance(ack, dict):
        raise CycleError("lifecycle handoff does not bind the current candidate and owners")
    historical_pickup = ack.get("successor_pickup")
    successor_pickup_id = None
    if isinstance(historical_pickup, dict) and historical_pickup.get("mode") == closure.DEGRADED_MODE:
        evidence = historical_pickup.get("evidence")
        match = re.fullmatch(r"github-comment:([1-9][0-9]*)", evidence) if isinstance(evidence, str) else None
        pickup_agent = historical_pickup.get("agent")
        if match is None or not isinstance(pickup_agent, str):
            raise CycleError("historical fallback pickup is unavailable")
        successor_pickup_id = int(match[1])
        fallback_pickup_at = _fallback_comment(
            comments, comment_id=successor_pickup_id, issue=issue, agent=pickup_agent,
            session=current["owner"], branch=branch, path=proof["path"], reason="dispatcher_db_missing")
    if remote_prior:
        remote_registration = receipt.get("predecessor_registration")
        remote_dispatcher = receipt.get("predecessor_dispatcher")
        if not isinstance(remote_registration, dict) or not isinstance(remote_dispatcher, dict):
            raise CycleError("remote predecessor readbacks are unavailable; reconcile through maintenance")
        # Original PR pickup provenance can name an older same-session lease.
        # The authenticated controller's fresh remote readback names the lease
        # and registration actually being released for this transfer.
        prior_agent = remote_dispatcher.get("holder")
        prior_lease = remote_dispatcher.get("lease_id")
        prior_path = remote_registration.get("path")
        if not all(isinstance(value, str) and value for value in (prior_agent, prior_lease, prior_path)):
            raise CycleError("remote predecessor readbacks are unavailable; reconcile through maintenance")
    pending = [row for row in records if row[1] == proof.get("pending_comment_id")
               and row[2].get("successor_acknowledgment") is None]
    if len(pending) != 1:
        raise CycleError("migration lacks the pre-release lifecycle receipt")
    receipt_at, _, cutover, receipt_comment = pending[0]
    if cutover != {key: value for key, value in receipt.items() if key != "successor_acknowledgment"}:
        raise CycleError("pre-release lifecycle receipt does not bind every acknowledged field")
    if (closure._parse_timestamp(receipt_comment.get("updated_at"), "handoff receipt update") != receipt_at
            or closure._parse_timestamp(ack_comment.get("updated_at"), "handoff acknowledgment update") != acknowledged_at):
        raise CycleError("edited lifecycle handoff comments are not authoritative")
    try:
        _, _, pending_digest = agent_worktree._transfer_comment(receipt_comment, issue=issue, pr=pr_number)
        _, _, ack_digest = agent_worktree._transfer_comment(ack_comment, issue=issue, pr=pr_number)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise CycleError("pinned handoff comment is unavailable or unauthenticated") from exc
    if (pending_digest != proof.get("pending_digest") or ack_digest != proof.get("ack_digest")
            or acknowledged_at.timestamp() != proof.get("ack_at")):
        raise CycleError("pinned lifecycle handoff was changed")
    receipt_end = receipt_at + timedelta(seconds=1)
    if not receipt_end <= acknowledged_at:
        raise CycleError("lifecycle handoff comment order is ambiguous")
    if fallback_origin_at is not None and not fallback_origin_at + timedelta(seconds=1) <= receipt_at:
        raise CycleError("fallback origin does not precede the lifecycle receipt")
    registered = proof.get("authority_since")
    if (not agent_worktree._valid_authority_timestamp(registered)
            or acknowledged_at.timestamp() <= registered):
        raise CycleError("lifecycle acknowledgment does not follow successor registration and readbacks")
    if lineage is not None:
        if lineage["agent"] is not None and lineage["agent"] != predecessor.get("agent"):
            raise CycleError("predecessor dispatcher lease holder is not the handoff predecessor")
        if lineage.get("session") != predecessor.get("session"):
            raise CycleError("predecessor dispatcher session differs from the handoff")
        if lineage["lease_id"] is None:
            if not receipt_end <= lineage["successor_claimed_at"]:
                raise CycleError("pre-release lifecycle receipt does not precede the successor dispatcher claim")
        elif (not lineage["claimed_at"] < receipt_at
              or not receipt_end <= lineage["released_at"]
              or not receipt_end <= _predecessor_lease_expiry(lineage, receipt_at)):
            raise CycleError("pre-release lifecycle receipt was not written while the predecessor lease was live")
        if (lineage["lease_id"] is not None and lineage.get("release_reason") == "expired"
                and lineage["released_at"] < _predecessor_lease_expiry(lineage, lineage["released_at"])):
            raise CycleError("dispatcher expiry release predates the lease expiry")
        if not lineage["successor_claimed_at"] < acknowledged_at:
            raise CycleError("lifecycle acknowledgment does not follow the successor dispatcher claim")
        successor_window = {"claim": lineage["successor_claim"], "claimed_at": lineage["successor_claimed_at"],
                            "events": lineage["events"]}
        ack_end = acknowledged_at + timedelta(seconds=1)
        if (ack_end > _predecessor_lease_expiry(successor_window, acknowledged_at)
                or (lineage.get("successor_released_at") is not None and ack_end > lineage["successor_released_at"])):
            raise CycleError("successor dispatcher lease was not live through acknowledgment")
    if fallback_pickup_at is not None and not receipt_end <= fallback_pickup_at < acknowledged_at:
        raise CycleError("fallback pickup does not follow the receipt and precede the acknowledgment")
    if fallback_pickup_at is not None and (fallback_pickup_at + timedelta(seconds=1)).timestamp() > registered:
        raise CycleError("fallback pickup does not precede successor registration")
    if prior_registration is not None:
        since, until, released = (prior_registration.get(k) for k in ("authority_since", "authority_until", "released_at"))
        if (not agent_worktree._valid_authority_timestamp(since)
                or not agent_worktree._valid_authority_timestamp(until)
                or not agent_worktree._valid_authority_timestamp(released)
                or not since < receipt_at.timestamp() or receipt_end.timestamp() > until
                or until > released or released >= registered
                or (lineage is not None and lineage["successor_claimed_at"].timestamp() >= released)
                or (fallback_pickup_at is not None
                    and (fallback_pickup_at + timedelta(seconds=1)).timestamp() > released)):
            raise CycleError("predecessor registration was not continuously live at the receipt; reconcile through maintenance")
    elif not remote_prior:
        raise CycleError("predecessor registration is unavailable; re-establish authority through maintenance")
    if remote_prior:
        # A different host cannot inspect the predecessor's dispatcher or
        # registry. Bind the authenticated controller's pre-release
        # observations and later release readbacks explicitly instead.
        remote_registration = receipt.get("predecessor_registration")
        remote_dispatcher = receipt.get("predecessor_dispatcher")
        if (not isinstance(remote_registration, dict) or not isinstance(remote_dispatcher, dict)
                or remote_registration.get("path") != prior_path
                or remote_registration.get("owner") != predecessor.get("session")
                or remote_registration.get("branch") != branch
                or not agent_worktree._valid_generation(remote_registration.get("generation"))
                or remote_registration.get("status") != "active"
                or not agent_worktree._valid_authority_timestamp(remote_registration.get("observed_at"))
                or not agent_worktree._valid_authority_timestamp(remote_registration.get("expires_at"))
                or remote_registration["observed_at"] >= receipt_at.timestamp()
                or remote_registration["expires_at"] < receipt_end.timestamp()
                or remote_dispatcher.get("task_id") != github_issue_task_id(completion.REPOSITORY, issue)
                or remote_dispatcher.get("lease_id") != prior_lease
                or remote_dispatcher.get("holder") != prior_agent
                or remote_dispatcher.get("session") != predecessor.get("session")
                or remote_dispatcher.get("history_reconciled") is not True):
            raise CycleError("remote predecessor readbacks are unavailable; reconcile through maintenance")
        observed = closure._parse_timestamp(remote_dispatcher.get("observed_at"), "remote dispatcher observation")
        expiry = closure._parse_timestamp(remote_dispatcher.get("expires_at"), "remote dispatcher expiry")
        claimed = closure._parse_timestamp(remote_dispatcher.get("claimed_at"), "remote dispatcher claim")
        if not claimed <= observed < receipt_at or receipt_end > expiry:
            raise CycleError("remote predecessor lease was not observed live at the receipt")
    if (receipt.get("issue") != issue or receipt.get("branch") != branch
            or receipt.get("base") not in ("main", proof["candidate_readback"]["base_sha"])
            or receipt.get("writable_worktree") != proof.get("path")
            or receipt.get("unpublished_candidate_head") != proof["candidate_readback"]["head"]
            or receipt.get("changed_files") != proof["candidate_readback"]["changed_files"]
            or any(k not in receipt or receipt[k] in (None, "", [], {}) for k in
                   ("current_validation", "current_review_receipt_evidence", "blockers", "residual_risk", "next_authorized_action"))
            or not isinstance(receipt.get("next_authorized_action"), str) or not receipt["next_authorized_action"].strip()
            or not isinstance(predecessor, dict) or not isinstance(predecessor.get("agent"), str)
            or not isinstance(predecessor.get("session"), str) or not predecessor["session"]
            or (prior_agent is not None and predecessor["agent"] != prior_agent)
            or (prior_session is not None and predecessor["session"] != prior_session)
            or not isinstance(successor, dict) or successor.get("agent") != entry.get("claimant")
            or successor.get("session") != current["owner"] or not isinstance(ack, dict)
            or ack.get("agent") != successor["agent"] or ack.get("session") != successor["session"]):
        raise CycleError("lifecycle handoff does not bind the current candidate and owners")
    release, pickup = ack.get("prior_coordination_release"), ack.get("successor_pickup")
    worktree_release, registration, candidate = ack.get("prior_worktree_release"), ack.get("successor_registration"), ack.get("candidate_readback")
    release_readback = release.get("readback") if isinstance(release, dict) else None
    if remote_prior:
        remote_release = closure._parse_timestamp(release.get("released_at") if isinstance(release, dict) else None,
                                                  "remote dispatcher release")
        worktree_released_at = worktree_release.get("released_at") if isinstance(worktree_release, dict) else None
        if (fallback_pickup_at is None or not receipt_end <= remote_release < fallback_pickup_at
                or not isinstance(worktree_release, dict)
                or not agent_worktree._valid_authority_timestamp(worktree_released_at)
                or (fallback_pickup_at + timedelta(seconds=1)).timestamp() > worktree_released_at
                or worktree_released_at >= registered
                or any(worktree_release.get(key) != receipt["predecessor_registration"].get(key)
                       for key in ("path", "owner", "branch", "generation"))):
            raise CycleError("remote release readbacks do not bind the predecessor and transfer order")
    if (not isinstance(release, dict) or release.get("status") != "released"
            or (prior_lease is not None and release.get("lease_id") != prior_lease)
            or (prior_lease is not None and release.get("task_id") != github_issue_task_id(completion.REPOSITORY, issue))
            or (prior_lease is not None and release.get("holder") != predecessor["agent"])
            or (prior_lease is not None and (not isinstance(release_readback, dict)
                or release_readback.get("status") not in ("ready", "blocked")
                or "claimed_by" not in release_readback or release_readback["claimed_by"] is not None
                or "lease_id" not in release_readback or release_readback["lease_id"] is not None))
            or not isinstance(pickup, dict) or pickup.get("mode") != entry.get("coordination_mode", "dispatcher-backed")
            or pickup.get("agent") != successor["agent"] or pickup.get("session") != successor["session"]
            or (pickup.get("mode") == "dispatcher-backed" and (pickup.get("lease_id") != (lineage or {}).get("successor_lease", coordination.get("lease_id"))
                or pickup.get("lease_id") == release.get("lease_id")))
            or (pickup.get("mode") == "github-label-only-fallback" and fallback_pickup_at is None)
            or not isinstance(worktree_release, dict) or worktree_release.get("status") != "released"
            or (prior_path is not None and worktree_release.get("path") != prior_path)
            or worktree_release.get("owner") != predecessor["session"]
            or worktree_release.get("branch") != branch or not agent_worktree._valid_generation(worktree_release.get("generation"))
            or (prior_registration is not None and any(worktree_release.get(key) != prior_registration.get(key)
                for key in ("path", "owner", "branch", "generation")))
            or not isinstance(registration, dict) or registration.get("path") != proof["path"]
            or registration.get("branch") != branch or registration.get("generation") != proof["generation"]
            or registration.get("owner") != current["owner"]
            or registration.get("epoch") != proof["epoch"]
            or registration.get("observed_at") != proof["registration_read_at"]
            or not isinstance(candidate, dict) or candidate.get("branch") != branch
            or candidate != proof["candidate_readback"] or candidate.get("base") != receipt.get("base")):
        raise CycleError("lifecycle handoff lacks release, pickup, registration or candidate readback")
    # The checkout is outside the model workspace and was resolved through the
    # host lifecycle authority above. Re-read its candidate after registration.
    source, worktree = Path(str(entry["lifecycle_repo"])), str(current["path"])
    base = entry.get("base_sha")
    if not isinstance(base, str) or not closure.SHA_RE.fullmatch(base):
        raise CycleError("handoff base revision is unavailable")
    try:
        git = agent_worktree.git_hygiene.run_git
        live_head = git(["-C", worktree, "rev-parse", "--verify", "HEAD"], source)
        transfer_base = candidate["base_sha"]
        transfer_head = candidate["head"]
        git(["-C", worktree, "merge-base", "--is-ancestor", transfer_head, head], source)
        transfer_files = git(["-C", worktree, "diff", "--name-only", "--find-renames", "-z", f"{transfer_base}...{transfer_head}"], source)
        dirty = git(["-C", worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"], source)
        changed = git(["-C", worktree, "diff", "--name-only", "--find-renames", "-z", f"{base}...{head}"], source)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise CycleError("handoff candidate readback is unavailable") from exc
    if (live_head != head or dirty or sorted(p for p in changed.split("\0") if p) != files
            or sorted(p for p in transfer_files.split("\0") if p) != candidate["changed_files"]):
        raise CycleError("handoff candidate changed after successor registration")


def _claim_session(row: Mapping[str, Any]) -> str | None:
    payload = row.get("payload")
    value = payload.get("session") if isinstance(payload, Mapping) else None
    return value if isinstance(value, str) and value and not any(c.isspace() for c in value) else None


def _fallback_predecessor(comments: Sequence[Any], *, issue: int, branch: str,
                          prior: Mapping[str, Any], before: Any,
                          comment_id: int | None = None) -> tuple[str, Any, int]:
    """Return the agent, time and comment of the predecessor's uniquely latest pickup."""
    matches = []
    for comment in comments:
        body = comment.get("body") if isinstance(comment, dict) else None
        match = closure.PICKUP_RECEIPT_RE.fullmatch(body) if isinstance(body, str) else None
        if (match and match["issue"] == str(issue) and match["branch"] == branch
                and match["session"] == prior.get("owner") and match["worktree"] == prior.get("path")):
            at = _fallback_comment(list(comments), comment_id=comment["id"], issue=issue,
                                   agent=match["agent"], session=match["session"], branch=branch,
                                   path=match["worktree"], reason=match["reason"])
            if at + timedelta(seconds=1) <= before:
                matches.append((comment["id"], match["agent"], at))
    if comment_id is not None:
        matches.sort(key=lambda row: (row[2], row[0]))
        if not matches or matches[-1][0] != comment_id or (len(matches) > 1 and matches[-1][2] == matches[-2][2]):
            raise CycleError("fallback predecessor reference is missing, stale or ambiguous")
        return matches[-1][1], matches[-1][2], matches[-1][0]
    if len(matches) != 1:
        raise CycleError("fallback predecessor pickup is missing or ambiguous; reconcile through maintenance")
    return matches[0][1], matches[0][2], matches[0][0]


def _predecessor_pickup_reference(comments: Sequence[Any], proof: Any, *, issue: int, pr_number: int) -> int | None:
    if not isinstance(proof, Mapping):
        return None
    rows = [row for row in comments if isinstance(row, dict) and row.get("id") == proof.get("pending_comment_id")]
    if len(rows) != 1:
        raise CycleError("pinned pending handoff is unavailable")
    try:
        receipt, _, digest = agent_worktree._transfer_comment(rows[0], issue=issue, pr=pr_number)
    except agent_worktree.WorktreeLifecycleError as exc:
        raise CycleError("pinned pending handoff is missing, edited or unauthenticated") from exc
    if digest != proof.get("pending_digest"):
        raise CycleError("pinned lifecycle handoff was changed")
    value = receipt.get("predecessor_pickup_comment_id")
    if value is not None and (type(value) is not int or value < 1):
        raise CycleError("fallback predecessor reference is invalid")
    return value


def _dispatcher_migration_lineage(events: Sequence[Mapping[str, Any]], owner: Mapping[str, Any], *,
                                  origin: Mapping[str, str], registration: Mapping[str, Any],
                                  comments: Sequence[Any], issue: int, branch: str,
                                  predecessor_pickup_id: int | None = None) -> dict[str, Any] | None:
    """Bind the current claim and the most recent session change to recorded events."""
    task_id, current = owner["task_id"], owner["lease_id"]
    history = [row for row in events if row.get("task_id") == task_id
               and row.get("event_type") in {"task.claimed", "task.released", "task.completed"}]
    times = [closure._parse_timestamp(row.get("timestamp"), "dispatcher event") for row in history]
    if any(left >= right for left, right in zip(times, times[1:])):
        raise CycleError("dispatcher event ordering is ambiguous; reconcile the task through maintenance")
    claims = [(i, row) for i, row in enumerate(history) if row.get("event_type") == "task.claimed"]
    current_claims = [(i, row) for i, row in claims if row.get("lease_id") == current]
    if (len(current_claims) != 1 or current_claims[0][1].get("actor") != owner["lease_holder"]
            or _claim_session(current_claims[0][1]) != registration.get("owner")):
        raise CycleError("current dispatcher claim lacks the registered Builder session; perform a fresh normal pickup")
    if len({row.get("lease_id") for _, row in claims}) != len(claims):
        raise CycleError("dispatcher claim lineage is ambiguous")
    if origin.get("lease_id"):
        original = [row for _, row in claims if row.get("lease_id") == origin["lease_id"]]
        if ((not original and not isinstance(registration.get("prior_owner"), Mapping))
                or (original and original[0].get("actor") != origin.get("agent"))):
            raise CycleError("original pickup lease is not an earlier claim of this dispatcher task")
        if original:
            closure._parse_timestamp(original[0].get("timestamp"), "original pickup claim")
    position = next(i for i, (_, row) in enumerate(claims) if row is current_claims[0][1])
    session = registration["owner"]
    start = position
    while start and _claim_session(claims[start - 1][1]) == session:
        start -= 1
    predecessor = claims[start - 1][1] if start else None
    prior = registration.get("prior_owner")
    if predecessor is not None and _claim_session(predecessor) is None:
        legacy_end = claims[start - 1][0]
        new_start = claims[start][0]
        between = history[legacy_end + 1:new_start]
        release = between[0] if len(between) == 1 else None
        release_payload = release.get("payload") if isinstance(release, Mapping) else None
        release_at = (closure._parse_timestamp(release.get("timestamp"), "legacy predecessor release")
                      if isinstance(release, Mapping) else None)
        since = registration.get("authority_since")
        if (prior is not None or predecessor.get("actor") != owner["lease_holder"]
                or (origin.get("path") is not None and origin["path"] != registration.get("path"))
                or not isinstance(release, Mapping) or release.get("event_type") != "task.released"
                or release.get("lease_id") != predecessor.get("lease_id")
                or not isinstance(release_payload, Mapping)
                or not isinstance(release_payload.get("reason"), str)
                or (release_payload.get("reason") != "expired" and release.get("actor") != predecessor.get("actor"))
                or not agent_worktree._valid_authority_timestamp(since)
                or release_at is None or since >= release_at.timestamp()):
            raise CycleError("predecessor session history is unbound; re-establish authority through maintenance")
        predecessor = None  # A fresh bound pickup may establish a legacy unchanged owner.
    fallback_prior = None
    if (isinstance(prior, Mapping) and prior.get("owner") != session
            and (predecessor is None or _claim_session(predecessor) != prior.get("owner"))):
        fallback_prior = _fallback_predecessor(comments, issue=issue, branch=branch, prior=prior,
                                                before=times[claims[start][0]], comment_id=predecessor_pickup_id)
        if predecessor is not None:
            between = history[claims[start - 1][0] + 1:claims[start][0]]
            release_payload = between[0].get("payload") if len(between) == 1 else None
            reason = release_payload.get("reason") if isinstance(release_payload, Mapping) else None
            if (len(between) != 1 or between[0].get("event_type") != "task.released"
                    or between[0].get("lease_id") != predecessor.get("lease_id")
                    or not isinstance(reason, str)
                    or (reason != "expired" and between[0].get("actor") != predecessor.get("actor"))
                    or closure._parse_timestamp(between[0].get("timestamp"), "older dispatcher release") >= fallback_prior[1]):
                raise CycleError("older dispatcher history is unresolved before fallback predecessor")
            if reason == "expired":
                released_at = closure._parse_timestamp(between[0].get("timestamp"), "older dispatcher release")
                older = {"claim": predecessor, "claimed_at": times[claims[start - 1][0]], "events": events}
                if released_at < _predecessor_lease_expiry(older, released_at):
                    raise CycleError("older dispatcher expiry release predates lease expiry")
    migration = predecessor is not None and _claim_session(predecessor) != session and fallback_prior is None
    fallback_origin = fallback_prior is not None
    if (origin.get("mode") == closure.DEGRADED_MODE and origin.get("session") == session
            and origin.get("agent") != owner["lease_holder"] and predecessor is None):
        raise CycleError("fallback origin and dispatcher claim disagree on the Builder session owner")
    if isinstance(prior, Mapping) and prior.get("owner") != session and not (migration or fallback_origin):
        raise CycleError("predecessor session history is unavailable; re-establish authority through maintenance")

    # Validate each same-session replacement and the actual transfer boundary.
    first_pair = max(0, start - 1) if migration else start
    for offset in range(first_pair, position):
        left_index, left = claims[offset]
        right_index, right = claims[offset + 1]
        between = history[left_index + 1:right_index]
        released = [row for row in between if row.get("event_type") == "task.released"
                    and row.get("lease_id") == left.get("lease_id")]
        takeover = right.get("payload", {}).get("takeover") if isinstance(right.get("payload"), Mapping) else None
        same_session = _claim_session(left) == _claim_session(right) and _claim_session(left) is not None
        if same_session and left.get("actor") != right.get("actor"):
            raise CycleError("same Builder session has conflicting dispatcher actors")
        if len(between) == 1 and len(released) == 1:
            release = released[0]
            payload = release.get("payload")
            reason = payload.get("reason") if isinstance(payload, Mapping) else None
            if not isinstance(reason, str) or (reason != "expired" and release.get("actor") != left.get("actor")):
                raise CycleError("predecessor dispatcher release is not authenticated")
        elif (not between and same_session and isinstance(takeover, Mapping)
              and takeover.get("previous_lease_id") == left.get("lease_id")
              and takeover.get("previous_holder") == left.get("actor")
              and closure._parse_timestamp(takeover.get("previous_expires_at"), "stale takeover expiry")
                  <= closure._parse_timestamp(right.get("timestamp"), "stale takeover claim")):
            continue
        else:
            raise CycleError("dispatcher predecessor release or same-session takeover is unavailable")
    if not migration and not fallback_origin:
        return None
    successor_index, successor = claims[start]
    successor_released_at = None
    if start < position:
        next_index, next_claim = claims[start + 1]
        intervening = history[successor_index + 1:next_index]
        if intervening:
            successor_released_at = closure._parse_timestamp(intervening[0].get("timestamp"), "successor lease release")
        else:
            takeover = next_claim["payload"]["takeover"]
            successor_released_at = closure._parse_timestamp(takeover.get("previous_expires_at"), "successor lease expiry")
    if fallback_origin:
        assert fallback_prior is not None and isinstance(prior, Mapping)
        return {"agent": fallback_prior[0], "session": prior.get("owner"), "lease_id": None,
                "successor_lease": successor.get("lease_id"), "successor_claimed_at": times[successor_index],
                "successor_claim": successor, "successor_released_at": successor_released_at,
                "fallback_origin_at": fallback_prior[1], "fallback_origin_id": fallback_prior[2], "events": events}
    assert predecessor is not None
    previous_index = claims[start - 1][0]
    release = history[previous_index + 1]
    return {"agent": predecessor.get("actor"), "session": _claim_session(predecessor),
            "lease_id": predecessor.get("lease_id"), "claimed_at": times[previous_index],
            "released_at": closure._parse_timestamp(release.get("timestamp"), "dispatcher predecessor release"),
            "release_reason": release["payload"]["reason"],
            "successor_lease": successor.get("lease_id"), "successor_claimed_at": times[successor_index],
            "successor_claim": successor, "successor_released_at": successor_released_at,
            "claim": predecessor, "events": events}


def _predecessor_lease_expiry(lineage: Mapping[str, Any], receipt_at: Any) -> Any:
    claim = lineage["claim"]
    payload = claim.get("payload")
    ttl = payload.get("ttl_minutes") if isinstance(payload, Mapping) else None
    if type(ttl) is not int or ttl <= 0:
        raise CycleError("predecessor lease TTL is unavailable; reconcile through maintenance")
    expiry = lineage["claimed_at"].replace(microsecond=0) + timedelta(minutes=ttl)
    prior = lineage["claimed_at"]
    heartbeats = [row for row in lineage["events"] if row.get("task_id") == claim.get("task_id")
                  and row.get("event_type") == "task.heartbeat" and row.get("lease_id") == claim.get("lease_id")]
    for heartbeat in heartbeats:
        at = closure._parse_timestamp(heartbeat.get("timestamp"), "dispatcher heartbeat")
        if at >= receipt_at:
            continue
        if heartbeat.get("actor") != claim.get("actor") or not prior < at < expiry:
            raise CycleError("predecessor heartbeat lineage is ambiguous")
        expiry = at.replace(microsecond=0) + timedelta(minutes=ttl)
        prior = at
    return expiry


def _validate_original_moves(registration: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]],
                             origin_path: str) -> None:
    """Follow released same-owner moves back to the original pickup path."""
    row = registration
    seen: set[tuple[Any, Any, Any]] = set()
    while True:
        previous = row.get("previous_registration")
        if not isinstance(previous, Mapping) or previous.get("owner") != registration.get("owner"):
            break
        key = (previous.get("path"), previous.get("generation"), previous.get("registered_at"))
        if key in seen or len(seen) >= agent_worktree.MAX_TRANSFER_HISTORY:
            raise CycleError("worktree move history is ambiguous; reconcile through maintenance")
        seen.add(key)
        if (previous.get("branch") != registration.get("branch")
                or not isinstance(previous.get("path"), str)
                or not all(agent_worktree._valid_authority_timestamp(previous.get(k)) for k in
                           ("registered_at", "authority_since", "authority_until", "released_at"))
                or not agent_worktree._valid_authority_timestamp(row.get("registered_at"))
                or not previous["registered_at"] <= previous["authority_until"] <= previous["released_at"] <= row["registered_at"]):
            raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")
        prior_row = records.get(previous["path"])
        fields = ("path", "branch", "generation", "owner", "registered_at", "authority_since", "authority_until", "released_at")
        if (isinstance(prior_row, Mapping) and prior_row.get("status") == "released"
                and all(prior_row.get(k) == previous.get(k) for k in fields)):
            row = prior_row
        elif (isinstance(prior_row, Mapping) and agent_worktree._valid_authority_timestamp(prior_row.get("registered_at"))
              and prior_row["registered_at"] >= previous["released_at"]):
            row = previous
        else:
            raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")
    if row.get("path") != origin_path:
        raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")


def _validate_transfer_move(registration: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]]) -> None:
    proof = registration.get("transfer_registration")
    if not isinstance(proof, Mapping) or proof.get("state") != "pinned":
        raise CycleError("historical transfer registration is unproved; reconcile through maintenance")
    row = registration
    visited: set[tuple[str, str, Any]] = set()
    def at_proof(row: Mapping[str, Any]) -> bool:
        previous = row.get("previous_registration")
        returned = (isinstance(previous, Mapping) and previous.get("owner") == row.get("owner")
                    and previous.get("path") != row.get("path"))
        return (row.get("path"), row.get("generation")) == (proof.get("path"), proof.get("generation")) and not returned

    while not at_proof(row):
        previous = row.get("previous_registration")
        if (not isinstance(previous, Mapping) or previous.get("owner") != registration.get("owner")
                or previous.get("branch") != registration.get("branch")
                or not isinstance(previous.get("path"), str)
                or not isinstance(previous.get("generation"), str)
                or not agent_worktree._valid_authority_timestamp(previous.get("registered_at"))
                or (previous["path"], previous["generation"], previous["registered_at"]) in visited):
            raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")
        visited.add((previous["path"], previous["generation"], previous["registered_at"]))
        prior_row = records.get(previous["path"])
        if (not agent_worktree._valid_authority_timestamp(row.get("registered_at"))
                or not agent_worktree._valid_authority_timestamp(previous.get("released_at"))
                or not agent_worktree._valid_authority_timestamp(previous.get("authority_since"))
                or not agent_worktree._valid_authority_timestamp(previous.get("authority_until"))
                or previous["authority_since"] > previous["authority_until"]
                or previous["authority_until"] > previous["released_at"]
                or previous["released_at"] > row["registered_at"]):
            raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")
        fields = ("path", "branch", "generation", "owner", "registered_at", "authority_since", "authority_until", "released_at")
        prior_previous = prior_row.get("previous_registration") if isinstance(prior_row, Mapping) else None
        if isinstance(prior_previous, Mapping) and prior_previous.get("owner") != previous.get("owner"):
            prior_previous = None
        intact = (isinstance(prior_row, Mapping) and prior_row.get("status") == "released"
                  and all(prior_row.get(k) == previous.get(k) for k in fields)
                  and prior_row.get("transfer_registration") == proof
                  and prior_previous == previous.get("previous_registration"))
        if intact:
            assert prior_row is not None
            row = prior_row
            continue
        # A later registration may reuse the path-keyed row. The immutable
        # snapshot is usable only when the replacement is demonstrably later;
        # a changed or missing row is not evidence of reuse.
        if (not isinstance(prior_row, Mapping)
                or not agent_worktree._valid_authority_timestamp(prior_row.get("registered_at"))
                or prior_row["registered_at"] < previous["released_at"]):
            raise CycleError("worktree move lacks released registration mapping; reconcile through maintenance")
        if ((previous["path"], previous["generation"]) == (proof.get("path"), proof.get("generation"))
                and (previous["authority_since"] != proof.get("authority_since")
                     or not agent_worktree._valid_authority_timestamp(proof.get("verified_through"))
                     or proof["verified_through"] > previous["authority_until"])):
            raise CycleError("worktree move lacks pinned registration interval; reconcile through maintenance")
        row = previous


def _validate_predecessor_anchor(prior: Mapping[str, Any], comments: list[Any], *, issue: int,
                                 pr_number: int, records: Mapping[str, Mapping[str, Any]],
                                 current: bool = False) -> tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]] | None:
    proof = prior.get("transfer_registration")
    if proof is None:
        if "transfer_registration" in prior:
            raise CycleError("predecessor transfer history is unknown; reconcile through maintenance")
        return None
    if not isinstance(proof, Mapping) or proof.get("state") != "pinned" or proof.get("issue") != issue:
        raise CycleError("predecessor transfer history is unproved; reconcile through maintenance")
    _validate_transfer_move(prior, records)
    observed: list[tuple[dict[str, Any], float]] = []
    for name, digest_key in (("pending_comment_id", "pending_digest"), ("ack_comment_id", "ack_digest")):
        matches = [c for c in comments if isinstance(c, dict) and c.get("id") == proof.get(name)]
        if len(matches) != 1:
            raise CycleError("predecessor transfer comment is unavailable")
        try:
            receipt, at, digest = agent_worktree._transfer_comment(matches[0], issue=issue, pr=pr_number)
        except agent_worktree.WorktreeLifecycleError as exc:
            raise CycleError("predecessor transfer comment is unavailable") from exc
        if digest != proof.get(digest_key):
            raise CycleError("predecessor transfer comment changed")
        observed.append((receipt, at))
    end = prior.get("expires_at") if current else prior.get("released_at")
    if (not agent_worktree._valid_authority_timestamp(proof.get("verified_through"))
            or not agent_worktree._valid_authority_timestamp(end)
            or proof["verified_through"] > end):
        raise CycleError("predecessor transfer was not proved before release")
    pending, pending_at = observed[0]
    acknowledged, ack_at = observed[1]
    ack = acknowledged.get("successor_acknowledgment")
    successor = pending.get("successor")
    predecessor = pending.get("current_lifecycle_owner")
    expected_registration = {"path": proof.get("path"), "branch": proof.get("branch"),
                             "owner": proof.get("owner"), "generation": proof.get("generation"),
                             "epoch": proof.get("epoch"), "observed_at": proof.get("registration_read_at")}
    if (pending != {k: v for k, v in acknowledged.items() if k != "successor_acknowledgment"}
            or pending_at + 1 > ack_at or ack_at != proof.get("ack_at")
            or pending.get("issue") != issue or pending.get("branch") != prior.get("branch")
            or not isinstance(successor, dict) or successor.get("session") != prior.get("owner")
            or not isinstance(predecessor, dict) or not isinstance(ack, dict)
            or ack.get("agent") != successor.get("agent") or ack.get("session") != successor.get("session")
            or ack.get("successor_registration") != expected_registration
            or ack.get("candidate_readback") != proof.get("candidate_readback")):
        raise CycleError("predecessor transfer anchor is inconsistent")
    previous = proof.get("predecessor_registration")
    released = ack.get("prior_worktree_release")
    if isinstance(previous, Mapping):
        if (predecessor.get("session") != previous.get("owner") or not isinstance(released, dict)
                or released.get("status") != "released"
                or any(released.get(k) != previous.get(k) for k in ("path", "branch", "generation", "owner"))
                or not previous["authority_since"] < pending_at
                or pending_at + 1 > previous["authority_until"]
                or previous["authority_until"] > previous["released_at"]
                or previous["released_at"] >= proof["authority_since"]):
            raise CycleError("predecessor transfer registry interval is inconsistent")
    elif not (isinstance(pending.get("predecessor_registration"), dict)
              and isinstance(pending.get("predecessor_dispatcher"), dict)):
        raise CycleError("predecessor transfer history is unavailable; reconcile through maintenance")
    return proof, pending, ack


def _verify_predecessor_transfer(anchor: tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]], *,
                                 comments: list[Any], events: Sequence[Mapping[str, Any]] | None,
                                 issue: int, pr_number: int, branch: str, head: str, files: list[str],
                                 registration: Mapping[str, Any], entry: Mapping[str, Any],
                                 remote_context: bool, current_transfer: bool = False) -> None:
    """Recheck the immediately preceding pinned transfer using retained local evidence."""
    proof, receipt, ack = anchor
    successor, predecessor = receipt["successor"], receipt["current_lifecycle_owner"]
    pickup, release = ack.get("successor_pickup"), ack.get("prior_coordination_release")
    previous = proof.get("predecessor_registration")
    if not isinstance(pickup, dict) or not isinstance(release, dict):
        raise CycleError("predecessor coordination history is unavailable")
    mode = pickup.get("mode")
    pickup_reference = receipt.get("predecessor_pickup_comment_id")
    if pickup_reference is not None and (type(pickup_reference) is not int or pickup_reference < 1):
        raise CycleError("fallback predecessor reference is invalid")
    lineage = None
    fallback_origin_at = None
    remote = isinstance(receipt.get("predecessor_dispatcher"), dict)
    if mode == closure.DISPATCHER_MODE:
        if events is None:
            # A receiving host cannot query a nonlocal dispatcher. The trusted
            # coordinator must reconcile this history before its remote handoff.
            if not remote_context:
                raise CycleError("predecessor dispatcher history is unavailable; reconcile through maintenance")
            return
        matches = [i for i, event in enumerate(events) if event.get("event_type") == "task.claimed"
                   and event.get("lease_id") == pickup.get("lease_id")
                   and event.get("task_id") == github_issue_task_id(completion.REPOSITORY, issue)]
        if len(matches) != 1:
            raise CycleError("predecessor dispatcher claim is unavailable")
        old_owner = {"task_id": github_issue_task_id(completion.REPOSITORY, issue),
                     "lease_id": pickup.get("lease_id"), "lease_holder": successor.get("agent")}
        old_registration = {"owner": successor.get("session"), "path": proof.get("path"),
                            "prior_owner": previous}
        lineage = _dispatcher_migration_lineage(events[:matches[0] + 1], old_owner, origin={},
                    registration=old_registration, comments=comments, issue=issue, branch=branch,
                    predecessor_pickup_id=pickup_reference)
        if lineage is None:
            raise CycleError("predecessor dispatcher transfer history is unavailable")
        fallback_origin_at = lineage.get("fallback_origin_at")
        # Include subsequent events so the ACK cannot outlive its original lease.
        later = [event for event in events[matches[0] + 1:] if event.get("event_type") == "task.released"
                 and event.get("lease_id") == pickup.get("lease_id")]
        if len(later) > 1:
            raise CycleError("predecessor dispatcher release is ambiguous")
        if later:
            lineage["successor_released_at"] = closure._parse_timestamp(later[0].get("timestamp"), "prior successor release")
        lineage["events"] = events
    elif mode == closure.DEGRADED_MODE:
        if isinstance(previous, Mapping) and release.get("lease_id") is None:
            pending_comment = next(c for c in comments if isinstance(c, dict) and c.get("id") == proof["pending_comment_id"])
            pending_at = closure._parse_timestamp(pending_comment.get("created_at"), "prior handoff receipt")
            _, fallback_origin_at, _ = _fallback_predecessor(
                comments, issue=issue, branch=branch, prior=previous, before=pending_at, comment_id=pickup_reference)
        elif not remote:
            raise CycleError("predecessor dispatcher evidence is unavailable; reconcile through maintenance")
    else:
        raise CycleError("predecessor coordination mode is invalid")
    old_current = {"owner": successor["session"], "path": registration["path"],
                   "generation": proof["generation"], "transfer_registration": proof}
    old_entry = {**entry, "claimant": successor["agent"], "session": successor["session"],
                 "coordination_mode": mode}
    _handoff_record(comments, issue=issue, pr_number=pr_number, branch=branch, head=head, files=files,
                    current=old_current, entry=old_entry, coordination=pickup,
                    prior_agent=predecessor.get("agent"), prior_session=predecessor.get("session"),
                    prior_path=previous.get("path") if isinstance(previous, Mapping) else None,
                    prior_lease=release.get("lease_id"), lineage=lineage,
                    prior_registration=previous if isinstance(previous, Mapping) else None,
                    fallback_origin_at=fallback_origin_at, remote_prior=remote, historical=not current_transfer)


def _claimant_history(*, registration: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]],
                      comments: list[Any], issue_comments: list[Any], events: Sequence[Mapping[str, Any]] | None,
                      origin: Mapping[str, str], origin_at: Any, issue: int, pr_number: int,
                      branch: str, entry: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]]:
    """Check every pickup against its proven owner interval, from origin to now.

    A pinned successor pickup is the only pickup admitted during a transfer for
    the incoming owner. All other pickups must match the current agent, session,
    branch and a registration live at that time. Neither a newer pickup nor a
    later pin can discard an earlier conflicting comment.
    """
    anchors: list[tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]]] = []
    row: Mapping[str, Any] = registration
    snapshots: list[Mapping[str, Any]] = [registration]
    seen: set[tuple[Any, Any]] = set()
    while isinstance(row.get("transfer_registration"), Mapping):
        if len(anchors) >= agent_worktree.MAX_TRANSFER_HISTORY:
            raise CycleError("transfer history exceeds its bound; reconcile through maintenance")
        anchor = _validate_predecessor_anchor(row, comments, issue=issue, pr_number=pr_number,
                                              records=records, current=not anchors)
        assert anchor is not None
        proof, _, _ = anchor
        key = (proof.get("pending_comment_id"), proof.get("ack_comment_id"))
        if key in seen:
            raise CycleError("transfer history is cyclic; reconcile through maintenance")
        seen.add(key)
        anchors.append(anchor)
        snapshots.append(row)
        previous = proof.get("predecessor_registration")
        if not isinstance(previous, Mapping):
            break
        # Pre-existing pins carry only the basic predecessor snapshot. The
        # still-retained immediate registry snapshot may also carry its pin.
        prior = registration.get("prior_owner") if len(anchors) == 1 else None
        fields = ("path", "branch", "generation", "owner", "registered_at", "authority_since", "authority_until", "released_at")
        if isinstance(prior, Mapping):
            if any(prior.get(k) != previous.get(k) for k in fields):
                raise CycleError("predecessor transfer snapshot changed; reconcile through maintenance")
            for key_name in ("transfer_registration", "previous_registration"):
                if key_name in previous and previous.get(key_name) != prior.get(key_name):
                    raise CycleError("predecessor transfer snapshot changed; reconcile through maintenance")
            previous = prior
        snapshots.append(previous)
        if "transfer_registration" in previous and previous.get("transfer_registration") is None:
            raise CycleError("predecessor transfer history is unknown; reconcile through maintenance")
        row = previous
    anchors.reverse()

    # Snapshots of same-owner moves are bounded inside the same proof, even if
    # a later registration replaced the path-keyed registry row.
    pending_rows = [*snapshots, registration.get("prior_owner")]
    visited_rows: set[tuple[Any, Any, Any]] = set()
    while pending_rows:
        candidate = pending_rows.pop()
        if not isinstance(candidate, Mapping):
            continue
        registration_identity = (candidate.get("path"), candidate.get("generation"), candidate.get("registered_at"))
        if registration_identity in visited_rows:
            continue
        visited_rows.add(registration_identity)
        snapshots.append(candidate)
        previous = candidate.get("previous_registration")
        if isinstance(previous, Mapping) and previous.get("owner") == candidate.get("owner"):
            snapshots.append(previous)
            pending_rows.append(previous)
            prior_row = records.get(str(previous.get("path")))
            fields = ("path", "branch", "generation", "owner", "registered_at", "authority_since", "authority_until", "released_at")
            if (isinstance(prior_row, Mapping) and prior_row.get("status") == "released"
                    and all(prior_row.get(k) == previous.get(k) for k in fields)):
                pending_rows.append(prior_row)

    task_id = github_issue_task_id(completion.REPOSITORY, issue)
    origin_id = int(origin["comment_id"]) if origin.get("comment_id") else None
    current_owner: tuple[Any, Any] | None = None
    legacy_origin_session: str | None = None
    start = origin_at
    if origin.get("mode") == closure.DEGRADED_MODE:
        if origin.get("reason") != "dispatcher_db_missing":
            raise CycleError("original fallback reason is invalid")
        current_owner = (origin.get("agent"), origin.get("session"))
    elif origin.get("mode") == closure.DISPATCHER_MODE:
        claims = [e for e in events or () if e.get("task_id") == task_id
                  and e.get("event_type") == "task.claimed" and e.get("lease_id") == origin.get("lease_id")]
        if len(claims) > 1:
            raise CycleError("original dispatcher claim is ambiguous")
        if claims:
            if claims[0].get("actor") != origin.get("agent"):
                raise CycleError("original dispatcher claim differs from pickup provenance")
            session = _claim_session(claims[0])
            if session is None:
                original_index = next(i for i, event in enumerate(events or ()) if event is claims[0])
                later = [(i, event) for i, event in enumerate(events or ()) if i > original_index
                         and event.get("task_id") == task_id and event.get("event_type") == "task.claimed"]
                prior = anchors[0][0].get("predecessor_registration") if anchors else registration
                if later and isinstance(prior, Mapping):
                    next_index, fresh = later[0]
                    fresh_session = _claim_session(fresh)
                    if (fresh.get("actor") == origin.get("agent") and fresh_session == prior.get("owner")
                            and isinstance(fresh.get("lease_id"), str)):
                        _dispatcher_migration_lineage((events or ())[:next_index + 1],
                            {"task_id": task_id, "lease_id": fresh["lease_id"], "lease_holder": fresh["actor"]},
                            origin=origin, registration=prior, comments=issue_comments, issue=issue, branch=branch)
                        session = legacy_origin_session = fresh_session
            if session:
                current_owner = (origin.get("agent"), session)
            start = closure._parse_timestamp(claims[0].get("timestamp"), "original dispatcher claim")
    elif not anchors and events is not None:
        claims = [e for e in events if e.get("task_id") == task_id and e.get("event_type") == "task.claimed"
                  and e.get("lease_id") == entry.get("lease_id") and e.get("actor") == entry.get("claimant")]
        if len(claims) == 1 and _claim_session(claims[0]) == registration.get("owner"):
            current_owner = (entry.get("claimant"), registration.get("owner"))
            start = closure._parse_timestamp(claims[0].get("timestamp"), "dispatcher claim")

    history_start = start
    segments: list[tuple[Any, Any, tuple[Any, Any]]] = []
    selected: set[int] = set()
    selected_leases: dict[str, tuple[tuple[Any, Any], Any, Any]] = {}
    acknowledgment_times: list[Any] = []
    for proof, receipt, ack in anchors:
        predecessor, successor = receipt.get("current_lifecycle_owner"), receipt.get("successor")
        if not isinstance(predecessor, dict) or not isinstance(successor, dict):
            raise CycleError("transfer claimant history is unavailable")
        before = (predecessor.get("agent"), predecessor.get("session"))
        after = (successor.get("agent"), successor.get("session"))
        if not all(isinstance(x, str) and x for x in (*before, *after)):
            raise CycleError("transfer claimant identity is unavailable")
        pending_comment = next(c for c in comments if isinstance(c, dict) and c.get("id") == proof["pending_comment_id"])
        receipt_at = closure._parse_timestamp(pending_comment.get("created_at"), "handoff receipt")
        ack_at = datetime.fromtimestamp(proof["ack_at"], timezone.utc)
        acknowledgment_times.append(ack_at)
        remote = receipt.get("predecessor_dispatcher")
        if (current_owner is None and origin.get("mode") == closure.DISPATCHER_MODE
                and isinstance(remote, dict) and remote.get("history_reconciled") is True
                and remote.get("lease_id") == origin.get("lease_id")
                and remote.get("holder") == origin.get("agent") == before[0]
                and remote.get("session") == before[1]):
            current_owner = before
            start = closure._parse_timestamp(remote.get("claimed_at"), "remote dispatcher claim")
            history_start = start
        if current_owner != before:
            if not isinstance(remote, dict) or remote.get("history_reconciled") is not True:
                raise CycleError("earlier claimant transfer is unavailable; reconcile through maintenance")
            remote_at = closure._parse_timestamp(remote.get("claimed_at"), "remote dispatcher claim")
            if start is not None and remote_at <= start:
                raise CycleError("remote claimant history overlaps the previous owner")
            if current_owner is not None:
                segments.append((start, remote_at, current_owner))
            start, current_owner = remote_at, before
        if start is not None and start >= receipt_at:
            raise CycleError("claimant transfer intervals are ambiguous")
        segments.append((start, ack_at, before))
        pickup = ack.get("successor_pickup")
        if isinstance(pickup, dict) and pickup.get("mode") == closure.DEGRADED_MODE:
            evidence = pickup.get("evidence")
            match = re.fullmatch(r"github-comment:([1-9][0-9]*)", evidence) if isinstance(evidence, str) else None
            if match is None or pickup.get("agent") != after[0] or pickup.get("session") != after[1]:
                raise CycleError("transfer successor pickup is unavailable")
            pickup_id = int(match[1])
            pickup_at = _fallback_comment(issue_comments, comment_id=pickup_id, issue=issue, agent=str(after[0]),
                                          session=str(after[1]), branch=branch, path=proof["path"],
                                          reason="dispatcher_db_missing")
            if not receipt_at + timedelta(seconds=1) <= pickup_at < ack_at:
                raise CycleError("transfer successor pickup order is ambiguous")
            selected.add(pickup_id)
        elif isinstance(pickup, dict) and pickup.get("mode") == closure.DISPATCHER_MODE:
            lease_id = pickup.get("lease_id")
            if (not isinstance(lease_id, str) or not lease_id or lease_id in selected_leases
                    or pickup.get("agent") != after[0] or pickup.get("session") != after[1]):
                raise CycleError("transfer successor dispatcher claim is unavailable")
            selected_leases[lease_id] = (after, receipt_at, ack_at)
        else:
            raise CycleError("transfer successor coordination mode is unavailable")
        start, current_owner = ack_at + timedelta(seconds=1), after
    if current_owner != (entry.get("claimant"), registration.get("owner")):
        raise CycleError("current claimant differs from the proven ownership history")
    segments.append((start, None, current_owner))

    if events is not None:
        for event in events:
            if event.get("task_id") != task_id or event.get("event_type") != "task.claimed":
                continue
            at = closure._parse_timestamp(event.get("timestamp"), "dispatcher claim")
            if history_start is not None and at < history_start:
                continue
            if any(ack <= at < ack + timedelta(seconds=1) for ack in acknowledgment_times):
                raise CycleError("dispatcher claimant ordering at acknowledgment is ambiguous")
            session = _claim_session(event)
            if (session is None and event.get("lease_id") == origin.get("lease_id")
                    and event.get("actor") == origin.get("agent")):
                session = legacy_origin_session
            identity = (event.get("actor"), session)
            transfer = selected_leases.get(str(event.get("lease_id")))
            if transfer is not None and transfer[0] == identity and transfer[1] < at < transfer[2]:
                continue
            if not any((begin is None or at >= begin) and (end is None or at <= end) and owner == identity
                       for begin, end, owner in segments):
                raise CycleError("conflicting dispatcher claimant requires maintenance")

    def registered_path(path: str, session: Any, at: Any) -> bool:
        for candidate in snapshots:
            if (candidate.get("path") != path or candidate.get("branch") != branch
                    or candidate.get("owner") != session
                    or not agent_worktree._valid_generation(candidate.get("generation"))):
                continue
            # A continuous re-registration updates registered_at while keeping
            # the same epoch. A new epoch starts authority_since again, so it
            # cannot fill an expiry, release, branch, or generation gap.
            since = candidate.get("authority_since", candidate.get("registered_at"))
            until = candidate.get("released_at", candidate.get("expires_at"))
            if "authority_until" in candidate:
                end = candidate.get("authority_until")
                if not agent_worktree._valid_authority_timestamp(end) or not agent_worktree._valid_authority_timestamp(until):
                    continue
                until = min(until, end)
            if (agent_worktree._valid_authority_timestamp(since) and agent_worktree._valid_authority_timestamp(until)
                    and since <= at.timestamp() and at.timestamp() + 1 <= until):
                return True
        return False

    comment_counts: dict[int, int] = {}
    for comment in issue_comments:
        if isinstance(comment, dict) and type(comment.get("id")) is int:
            comment_counts[comment["id"]] = comment_counts.get(comment["id"], 0) + 1
    for comment in issue_comments:
        body = comment.get("body") if isinstance(comment, dict) else None
        match = closure.PICKUP_RECEIPT_RE.fullmatch(body) if isinstance(body, str) else None
        if match is None or not _authenticated_comment(comment) or match["issue"] != str(issue):
            continue
        at = closure._parse_timestamp(comment["created_at"], "fallback pickup")
        # GitHub pickup times have only second precision. A comment in the
        # origin second could follow the claim, even when the claim includes
        # subsecond precision; only discard a wholly earlier second.
        if history_start is not None and at + timedelta(seconds=1) <= history_start:
            continue
        if comment_counts[comment["id"]] != 1:
            raise CycleError("fallback pickup comment is ambiguous")
        _fallback_comment([comment], comment_id=comment["id"], issue=issue, agent=match["agent"],
                          session=match["session"], branch=match["branch"], path=match["worktree"], reason=match["reason"])
        if comment["id"] == origin_id or comment["id"] in selected:
            continue
        if at in acknowledgment_times:
            raise CycleError("fallback pickup ordering at acknowledgment is ambiguous")
        if not any((begin is None or at >= begin) and (end is None or at <= end)
                   and owner == (match["agent"], match["session"])
                   and match["branch"] == branch and match["reason"] == "dispatcher_db_missing"
                   and registered_path(match["worktree"], match["session"], at)
                   for begin, end, owner in segments):
            raise CycleError("later conflicting fallback pickup requires maintenance")
    return anchors


def native_authority(layout: workspace.Layout, pr: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    """Read native ownership, route and canonical scope from host authorities, not PR attestations."""
    cwd = Path(__file__).resolve().parents[2]
    executor = SubprocessExecutor(timeout_seconds=30)
    user = executor.run(["gh", "api", "--hostname", "github.com", "user", "--jq", ".login"], cwd=cwd)
    if user.returncode != 0 or user.stdout.strip() != "RasmusTho":
        raise CycleError("host GitHub identity is unavailable or differs from the authorized account")
    try:
        repo = closure._api(executor, cwd, completion.REPOSITORY, "GET", "")
        live = closure._pr(executor, cwd, completion.REPOSITORY, int(pr["number"]))
        body = live.get("body")
        authority = resolve_native_issue_authority(body)
        if (not isinstance(repo, dict) or repo.get("full_name") != completion.REPOSITORY
                or repo.get("default_branch") != "main" or authority is None
                or live.get("state") != "open" or live.get("draft") is not False
                or live.get("head", {}).get("sha") != pr["head_sha"]
                or live.get("head", {}).get("repo", {}).get("full_name") != completion.REPOSITORY
                or live.get("base", {}).get("ref") != "main" or body != pr["body"]
                or live.get("title", "") != pr.get("title", "")):
            raise CycleError("live PR or native contract drifted")
        refs = closure._closing_issue_references(executor, cwd, completion.REPOSITORY, int(pr["number"]))
        if refs != list(authority.closing_issues):
            raise CycleError("GitHub closing references differ from the canonical contract")
        issue = closure._issue(executor, cwd, completion.REPOSITORY, authority.governing_issue)
        if issue.get("state") != "open" or issue.get("body") != pr["governing_issue"]["body"]:
            raise CycleError("governing Issue contract or state drifted")
        _assert_unheld_issue(issue)
        _assert_review_threads_clear(executor, cwd, int(pr["number"]))
        branch = live.get("head", {}).get("ref")
        if not isinstance(branch, str) or not branch:
            raise CycleError("head branch identity unavailable")
        registration, lifecycle_records = _lifecycle_owner(layout, entry, branch)
        issue_comments = _api_pages(executor, cwd, f"/issues/{authority.governing_issue}/comments")
        pr_comments = _api_pages(executor, cwd, f"/issues/{pr['number']}/comments")
        origin, fallback_origin_at = _pickup_origin(body or "", issue=authority.governing_issue,
                                                    closing=refs, branch=branch, comments=issue_comments)
        original_at = fallback_origin_at
        task_id = github_issue_task_id(completion.REPOSITORY, authority.governing_issue)
        prior_registration = registration.get("prior_owner")
        if prior_registration is not None and not isinstance(prior_registration, Mapping):
            raise CycleError("predecessor registration evidence is malformed")
        pickup_reference = _predecessor_pickup_reference(
            [*issue_comments, *pr_comments], registration.get("transfer_registration"),
            issue=authority.governing_issue, pr_number=int(pr["number"]))
        lineage: dict[str, Any] | None = None
        dispatcher_events: Sequence[Mapping[str, Any]] | None = None
        changed_owner = False
        remote_prior = False
        fallback_pickup_at = None
        prior_agent: str | None = None
        prior_session: str | None = None
        prior_path: str | None = None
        prior_lease: str | None = None
        same_session_transfer: tuple[Mapping[str, Any], dict[str, Any], dict[str, Any]] | None = None
        if entry.get("coordination_mode", "dispatcher-backed") == "github-label-only-fallback":
            status = executor.run([sys.executable, "-m", "app.dispatcher", "status", "--json"], cwd=cwd)
            if status.returncode != 0:
                raise CycleError("dispatcher status failed; availability is ambiguous")
            try:
                dispatcher = json.loads(status.stdout)
            except ValueError as exc:
                raise CycleError("dispatcher status is malformed") from exc
            if (not isinstance(dispatcher, dict) or dispatcher.get("ok") is not True
                    or dispatcher.get("db_exists") is not False
                    or dispatcher.get("coordination_mode") != closure.DEGRADED_MODE
                    or dispatcher.get("fallback_reason") != "dispatcher_db_missing"
                    or entry.get("fallback_reason") != "dispatcher_db_missing"):
                raise CycleError("dispatcher is available or its status is ambiguous")
            owner_path = entry.get("owner_worktree")
            if not isinstance(owner_path, str) or not Path(owner_path).is_absolute() or str(Path(owner_path).resolve()) != owner_path:
                raise CycleError("fallback owner worktree is unavailable")
            owner = closure._degraded_coordination_snapshot(
                executor, Path(owner_path), completion.REPOSITORY, authority.governing_issue,
                entry.get("fallback_reason"), entry.get("coordination_evidence"), entry.get("claimant"),
                entry.get("session"), branch)
            if owner.get("comment_author") != "RasmusTho":
                raise CycleError("fallback pickup receipt was not authored by the authorized account")
            fallback_pickup_at = _fallback_comment(
                issue_comments, comment_id=owner["comment_id"], issue=authority.governing_issue,
                agent=entry["claimant"], session=entry["session"], branch=branch,
                path=owner_path, reason=entry["fallback_reason"])
            for comment in issue_comments:
                if not _authenticated_comment(comment) or not isinstance(comment.get("body"), str):
                    continue
                match = closure.PICKUP_RECEIPT_RE.fullmatch(comment["body"])
                if (match and int(match["issue"]) == authority.governing_issue and comment["id"] != owner["comment_id"]
                        and closure._parse_timestamp(comment["created_at"], "pickup receipt") == fallback_pickup_at):
                    raise CycleError("fallback pickup ordering is ambiguous")
            proof = registration.get("transfer_registration")
            pinned_ack = [c for c in [*issue_comments, *pr_comments] if isinstance(c, dict)
                          and isinstance(proof, Mapping) and c.get("id") == proof.get("ack_comment_id")]
            remote_evidence = False
            if len(pinned_ack) == 1:
                try:
                    parsed, _, _ = agent_worktree._transfer_comment(pinned_ack[0], issue=authority.governing_issue,
                                                                    pr=int(pr["number"]))
                    remote_evidence = isinstance(parsed.get("predecessor_dispatcher"), dict)
                except agent_worktree.WorktreeLifecycleError as exc:
                    raise CycleError("pinned handoff comment is unavailable or unauthenticated") from exc
            if remote_evidence:
                # The pinned receipt's reconciled remote readback names the
                # immediate predecessor. This host's own last owner can only be
                # released history before that remote claim, not the predecessor.
                try:
                    agent_worktree._assert_local_history_precedes_remote(prior_registration, parsed)
                except agent_worktree.WorktreeLifecycleError as exc:
                    raise CycleError(str(exc)) from exc
                prior_registration = None
                changed_owner, remote_prior = True, True
            elif isinstance(prior_registration, Mapping) and prior_registration.get("owner") != registration["owner"]:
                changed_owner = True
                prior_session, prior_path = prior_registration.get("owner"), prior_registration.get("path")
                prior_agent, fallback_origin_at, _ = _fallback_predecessor(
                    issue_comments, issue=authority.governing_issue, branch=branch,
                    prior=prior_registration, before=fallback_pickup_at, comment_id=pickup_reference)
            elif isinstance(proof, Mapping) or origin.get("mode") == closure.DISPATCHER_MODE or not origin:
                changed_owner, remote_prior = True, True
            elif origin.get("mode") == closure.DEGRADED_MODE and origin.get("session") != registration["owner"]:
                raise CycleError("fallback predecessor registration is unavailable; reconcile through maintenance")
        elif entry.get("coordination_mode", "dispatcher-backed") == "dispatcher-backed":
            task, events, lease = closure._dispatcher_inspect(executor, cwd, task_id)
            dispatcher_events = events
            owner = closure._dispatcher_snapshot_from_task(task, task_id, repository=completion.REPOSITORY,
                        issue_number=authority.governing_issue, pr_number=int(pr["number"]), lease=lease)
            closure._validate_claimant_history(events, owner)
            if (owner["lease_holder"] != entry.get("claimant") or owner["lease_id"] != entry.get("lease_id")
                    or not isinstance(entry.get("session"), str) or not entry["session"].strip()):
                raise CycleError("native owner or lease does not match the admitted session")
            proof = registration.get("transfer_registration")
            pinned = [c for c in [*issue_comments, *pr_comments] if isinstance(c, dict)
                      and isinstance(proof, Mapping) and c.get("id") == proof.get("ack_comment_id")]
            if isinstance(proof, Mapping) and proof.get("state") == "pinned" and len(pinned) == 1:
                try:
                    pinned_receipt, pinned_at, digest = agent_worktree._transfer_comment(
                        pinned[0], issue=authority.governing_issue, pr=int(pr["number"]))
                except agent_worktree.WorktreeLifecycleError as exc:
                    raise CycleError("pinned handoff comment is unavailable or unauthenticated") from exc
                handoff_ack = pinned_receipt.get("successor_acknowledgment")
                pinned_pickup = handoff_ack.get("successor_pickup") if isinstance(handoff_ack, dict) else None
                if isinstance(pinned_pickup, dict) and pinned_pickup.get("mode") == closure.DEGRADED_MODE:
                    if digest != proof.get("ack_digest") or pinned_at != proof.get("ack_at"):
                        raise CycleError("pinned lifecycle handoff was changed")
                    evidence = pinned_pickup.get("evidence")
                    match = re.fullmatch(r"github-comment:([1-9][0-9]*)", evidence) if isinstance(evidence, str) else None
                    if match is None or pinned_pickup.get("session") != registration["owner"]:
                        raise CycleError("historical fallback pickup is unavailable")
                    historical_pickup = _fallback_comment(issue_comments, comment_id=int(match[1]),
                        issue=authority.governing_issue, agent=entry["claimant"], session=registration["owner"],
                        branch=branch, path=proof["path"], reason="dispatcher_db_missing")
                    current_lineage = _dispatcher_migration_lineage(
                        events, owner, origin={}, registration={**registration, "prior_owner": None},
                        comments=issue_comments, issue=authority.governing_issue, branch=branch)
                    own_claims = [closure._parse_timestamp(event.get("timestamp"), "dispatcher claim")
                                  for event in events if event.get("task_id") == task_id
                                  and event.get("event_type") == "task.claimed"
                                  and _claim_session(event) == registration["owner"]]
                    claimed_at = (current_lineage["successor_claimed_at"] if current_lineage is not None
                                  else min(own_claims) if own_claims else None)
                    if (claimed_at is None or claimed_at.timestamp() < pinned_at + 1
                            or (current_lineage is not None and current_lineage.get("released_at") >= historical_pickup)):
                        raise CycleError("same-session dispatcher pickup does not follow the pinned fallback")
                    previous = pinned_receipt.get("current_lifecycle_owner")
                    if not isinstance(previous, dict):
                        raise CycleError("historical predecessor is unavailable")
                    prior_agent, prior_session = previous.get("agent"), previous.get("session")
                    remote_prior = isinstance(pinned_receipt.get("predecessor_dispatcher"), dict)
                    if remote_prior:
                        try:
                            agent_worktree._assert_local_history_precedes_remote(prior_registration, pinned_receipt)
                        except agent_worktree.WorktreeLifecycleError as exc:
                            raise CycleError(str(exc)) from exc
                        prior_registration = None
                    prior_path = prior_registration.get("path") if isinstance(prior_registration, Mapping) else None
                    assert isinstance(handoff_ack, dict)
                    same_session_transfer = (proof, pinned_receipt, handoff_ack)
            if same_session_transfer is None:
                lineage = _dispatcher_migration_lineage(events, owner, origin=origin, registration=registration,
                                                        comments=[*issue_comments, *pr_comments], issue=authority.governing_issue,
                                                        branch=branch, predecessor_pickup_id=pickup_reference)
            changed_owner = lineage is not None
            if same_session_transfer is not None:
                changed_owner = True
            if lineage:
                prior_agent, prior_session, prior_lease = lineage["agent"], lineage["session"], lineage["lease_id"]
                fallback_origin_at = lineage.get("fallback_origin_at", fallback_origin_at)
                if isinstance(prior_registration, Mapping):
                    prior_path = prior_registration.get("path")
                elif lineage["lease_id"] is None:
                    prior_path = origin.get("path")
            verification = executor.run([sys.executable, "-m", "app.dispatcher", "verification-status",
                                     "--repo", completion.REPOSITORY, "--limit", "10000", "--json"], cwd=cwd)
            payload = json.loads(verification.stdout) if verification.returncode == 0 else None
            runs = payload.get("runs") if isinstance(payload, dict) and payload.get("ok") is True else None
            if (not isinstance(runs, list) or len(runs) >= 10000 or not all(isinstance(x, dict)
                    and type(x.get("pr_number")) is int and x.get("repository") == completion.REPOSITORY for x in runs)
                    or any(x.get("pr_number") == pr["number"] for x in runs)):
                raise CycleError("verification-dispatch state is unavailable or owns this PR")
        else:
            raise CycleError("unsupported coordination mode")
        if not changed_owner and origin.get("path"):
            _validate_original_moves(registration, lifecycle_records, origin["path"])
        if changed_owner:
            _validate_transfer_move(registration, lifecycle_records)
            if (isinstance(prior_registration, Mapping)
                    and not agent_worktree._valid_authority_timestamp(prior_registration.get("released_at"))):
                # Expiry or completion is not a successor release; the later
                # owner's history stays authoritative until it is reconciled.
                raise CycleError("predecessor registration ended without release; reconcile through maintenance")
            predecessor_anchor = None
            if isinstance(prior_registration, Mapping):
                predecessor_anchor = _validate_predecessor_anchor(
                    prior_registration, [*issue_comments, *pr_comments],
                    issue=authority.governing_issue, pr_number=int(pr["number"]), records=lifecycle_records)
            if isinstance(prior_registration, Mapping) and prior_session != prior_registration.get("owner"):
                if not remote_prior:
                    raise CycleError("predecessor session differs from the released registry owner")
            files = _api_pages(executor, cwd, f"/pulls/{pr['number']}/files")
            if not files or any(not isinstance(x, dict) or not isinstance(x.get("filename"), str) for x in files):
                raise CycleError("candidate changed-file readback is unavailable")
            if predecessor_anchor is not None:
                _verify_predecessor_transfer(predecessor_anchor, comments=[*issue_comments, *pr_comments],
                    events=dispatcher_events, issue=authority.governing_issue, pr_number=int(pr["number"]),
                    branch=branch, head=pr["head_sha"], files=sorted(x["filename"] for x in files),
                    registration=registration, entry={**entry, "base_sha": live.get("base", {}).get("sha")},
                    remote_context=remote_prior)
            if same_session_transfer is not None:
                _verify_predecessor_transfer(same_session_transfer, comments=[*issue_comments, *pr_comments],
                    events=dispatcher_events, issue=authority.governing_issue, pr_number=int(pr["number"]),
                    branch=branch, head=pr["head_sha"], files=sorted(x["filename"] for x in files),
                    registration=registration, entry={**entry, "base_sha": live.get("base", {}).get("sha")},
                    remote_context=remote_prior, current_transfer=True)
            else:
                _handoff_record([*issue_comments, *pr_comments], issue=authority.governing_issue, pr_number=int(pr["number"]),
                            branch=branch, head=pr["head_sha"],
                            files=sorted(x["filename"] for x in files), current=registration,
                            entry={**entry, "base_sha": live.get("base", {}).get("sha")}, coordination=owner,
                            prior_agent=prior_agent, prior_session=prior_session, prior_path=prior_path,
                            prior_lease=prior_lease, lineage=lineage, prior_registration=prior_registration,
                            fallback_pickup_at=fallback_pickup_at, fallback_origin_at=fallback_origin_at,
                            remote_prior=remote_prior)
        anchors = _claimant_history(registration=registration, records=lifecycle_records,
            comments=[*issue_comments, *pr_comments], issue_comments=issue_comments, events=dispatcher_events,
            origin=origin, origin_at=original_at, issue=authority.governing_issue,
            pr_number=int(pr["number"]), branch=branch, entry=entry)
        if changed_owner and len(anchors) > 2:
            for anchor in anchors[:-2]:
                _verify_predecessor_transfer(anchor, comments=[*issue_comments, *pr_comments],
                    events=dispatcher_events, issue=authority.governing_issue, pr_number=int(pr["number"]),
                    branch=branch, head=pr["head_sha"], files=sorted(x["filename"] for x in files),
                    registration=registration, entry={**entry, "base_sha": live.get("base", {}).get("sha")},
                    remote_context=remote_prior)
        if any(isinstance(x, dict) and any(marker in str(x.get("body", "")) for marker in (
                    "verified_issue_set_merge_authority.v1", "verification_dispatch_request.v3",
                    "verified issue-set merge authority:", "verified issue-set merge phase:")) for x in pr_comments):
            raise CycleError("PR has a verification or fenced authority receipt")
        state = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)
        reviewer = _mapping(layout, entry["worker"])
        _assert_stopped(layout, entry["worker"], reviewer)
        for issue_key, other in state["issue_mappings"].items():
            if not isinstance(other, dict) or other.get("worker") == entry["worker"]:
                continue
            if issue_key == str(authority.governing_issue) and not other.get("branch"):
                raise CycleError("another worker may write the candidate")
            if other.get("branch") == branch:
                other_worker = other.get("worker")
                if not isinstance(other_worker, str):
                    raise CycleError("candidate writer identity is unavailable")
                _assert_stopped(layout, other_worker, other)
        return {"number": pr["number"], "head_sha": pr["head_sha"], "body": body,
                "title": live.get("title"), "branch": branch, "governing_issue": authority.governing_issue,
                "governing_issue_hashes": closure._issue_hashes(issue),
                "closing_issues": refs, "owner": owner, "base_ref": "main",
                "worktree_owner": {k: registration[k] for k in ("path", "branch", "owner", "generation", "expires_at")},
                "coordination_mode": entry.get("coordination_mode", "dispatcher-backed")}
    except closure.ClosureError as exc:
        raise CycleError(f"native authority unavailable: {exc.reason}") from exc


def _api_pages(executor: SubprocessExecutor, cwd: Path, endpoint: str) -> list[Any]:
    rows: list[Any] = []
    for page in range(1, 101):
        value = closure._api(executor, cwd, completion.REPOSITORY, "GET", f"{endpoint}?per_page=100&page={page}")
        if not isinstance(value, list):
            raise CycleError("GitHub paginated readback is invalid")
        rows.extend(value)
        if len(value) < 100:
            return rows
    raise CycleError("GitHub readback exceeded the page limit")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _review_context(pr: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the diff, exact closing contracts and relevant base check configuration."""
    cwd, executor = Path(__file__).resolve().parents[2], SubprocessExecutor(timeout_seconds=30)
    number = int(pr["number"])
    live = closure._pr(executor, cwd, completion.REPOSITORY, number)
    base = live.get("base", {}).get("sha")
    if live.get("head", {}).get("sha") != pr["head_sha"] or not isinstance(base, str):
        raise CycleError("review source head or base unavailable")
    files = _api_pages(executor, cwd, f"/pulls/{number}/files")
    if not files or any(not isinstance(row, dict) or not isinstance(row.get("filename"), str)
                        or not isinstance(row.get("patch"), str) for row in files):
        raise CycleError("complete review file patches unavailable")
    diff = executor.run(["gh", "api", "--hostname", "github.com", "-H", "Accept: application/vnd.github.v3.diff",
                         f"repos/{completion.REPOSITORY}/pulls/{number}"], cwd=cwd)
    if diff.returncode or not diff.stdout or "Binary files " in diff.stdout or "GIT binary patch" in diff.stdout:
        raise CycleError("complete textual review diff unavailable")
    authority = resolve_native_issue_authority(pr["body"])
    if authority is None:
        raise CycleError("review Issue authority unavailable")
    refs = closure._closing_issue_references(executor, cwd, completion.REPOSITORY, number)
    if refs != list(authority.closing_issues):
        raise CycleError("review closing references drifted")
    issues = {}
    for issue_number in refs:
        issue = closure._issue(executor, cwd, completion.REPOSITORY, issue_number)
        if issue.get("state") != "open" or not isinstance(issue.get("body"), str):
            raise CycleError("closing Issue contract unavailable")
        issues[str(issue_number)] = {"title": issue.get("title"), "body": issue["body"],
                                     "hashes": closure._issue_hashes(issue)}
    tree = closure._api(executor, cwd, completion.REPOSITORY, "GET", f"/git/trees/{base}?recursive=1")
    if not isinstance(tree, dict) or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise CycleError("base check configuration tree unavailable")
    paths = (".github/", "scripts/select_pr_tests.py", "pyproject.toml", "pytest.ini", "conftest.py")
    config = sorted((row.get("path"), row.get("sha"), row.get("mode")) for row in tree["tree"]
                    if isinstance(row, dict) and isinstance(row.get("path"), str)
                    and any(row["path"].startswith(p) for p in paths) and row.get("type") == "blob")
    protection = closure._api(executor, cwd, completion.REPOSITORY, "GET", "/branches/main/protection")
    rules = closure._api(executor, cwd, completion.REPOSITORY, "GET", "/rulesets?includes_parents=true&per_page=100")
    if not isinstance(protection, dict) or not isinstance(rules, list) or len(rules) >= 100:
        raise CycleError("branch check configuration unavailable")
    if any(not isinstance(row, dict) or type(row.get("id")) is not int for row in rules):
        raise CycleError("branch ruleset identities unavailable")
    rules = [closure._api(executor, cwd, completion.REPOSITORY, "GET", f"/rulesets/{row['id']}") for row in rules]
    if any(not isinstance(row, dict) or not isinstance(row.get("rules"), list) for row in rules):
        raise CycleError("branch ruleset details unavailable")
    final = closure._pr(executor, cwd, completion.REPOSITORY, number)
    if final.get("head", {}).get("sha") != pr["head_sha"] or final.get("base", {}).get("sha") != base:
        raise CycleError("review source changed during readback")
    context = {"files_digest": _digest(files), "diff_digest": hashlib.sha256(diff.stdout.encode()).hexdigest(),
               "closing_issue_hashes": {k: v["hashes"] for k, v in issues.items()},
               "check_config_digest": _digest({"tree": config, "protection": protection, "rules": rules})}
    return context, {"diff": diff.stdout, "issues": issues}


def _add_transfer_review_context(layout: workspace.Layout, entry: Mapping[str, Any],
                                 pr: dict[str, Any]) -> None:
    """Bind transfer-to-current changes to the ordinary review identity and material."""
    if not entry.get("lifecycle_repo"):
        return
    executor = SubprocessExecutor(timeout_seconds=30)
    cwd = Path(__file__).resolve().parents[2]
    live = closure._pr(executor, cwd, completion.REPOSITORY, int(pr["number"]))
    branch = live.get("head", {}).get("ref")
    if not isinstance(branch, str) or live.get("head", {}).get("sha") != pr["head_sha"]:
        raise CycleError("transfer review source is unavailable")
    registration, records = _lifecycle_owner(layout, entry, branch)
    proof = registration.get("transfer_registration")
    if proof is None and registration.get("prior_owner") is not None:
        raise CycleError("historical transfer registration is unproved; reconcile through maintenance")
    authority = resolve_native_issue_authority(pr.get("body"))
    if authority is None:
        raise CycleError("native issue authority is unavailable")
    issue_comments = _api_pages(executor, cwd, f"/issues/{authority.governing_issue}/comments")
    pr_comments = _api_pages(executor, cwd, f"/issues/{pr['number']}/comments")
    origin, origin_at = _pickup_origin(pr.get("body", ""), issue=authority.governing_issue,
        closing=authority.closing_issues, branch=branch, comments=issue_comments)
    if proof is None and origin.get("path"):
        _validate_original_moves(registration, records, origin["path"])
    events = None
    if entry.get("coordination_mode", closure.DISPATCHER_MODE) == closure.DISPATCHER_MODE:
        _, events, _ = closure._dispatcher_inspect(executor, cwd,
            github_issue_task_id(completion.REPOSITORY, authority.governing_issue))
    _claimant_history(registration=registration, records=records, comments=[*issue_comments, *pr_comments],
        issue_comments=issue_comments, events=events, origin=origin, origin_at=origin_at,
        issue=authority.governing_issue, pr_number=int(pr["number"]), branch=branch, entry=entry)
    if proof is None:
        return
    _validate_transfer_move(registration, records)
    if not isinstance(proof, dict) or proof.get("state") != "pinned":
        raise CycleError("historical transfer registration is unproved; reconcile through maintenance")
    worktree, source = str(registration["path"]), Path(str(entry["lifecycle_repo"]))
    old_head = proof["candidate_readback"]["head"]
    try:
        git = agent_worktree.git_hygiene.run_git
        live_head = git(["-C", worktree, "rev-parse", "--verify", "HEAD"], source)
        dirty = git(["-C", worktree, "status", "--porcelain=v1", "-z", "--untracked-files=all"], source)
        git(["-C", worktree, "merge-base", "--is-ancestor", old_head, pr["head_sha"]], source)
        delta = git(["-C", worktree, "diff", "--no-ext-diff", "--no-textconv", old_head, pr["head_sha"]], source)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise CycleError("transfer-to-current review delta is unavailable") from exc
    if (dirty or live_head != pr["head_sha"] or len(delta.encode()) > 2_000_000
            or "Binary files " in delta or "GIT binary patch" in delta):
        raise CycleError("transfer-to-current review delta is incomplete or candidate is dirty")
    material = {"transfer_head": old_head, "current_head": pr["head_sha"], "diff": delta}
    pr["review_context"]["transfer_delta_digest"] = _digest({**material, "ack_digest": proof["ack_digest"]})
    pr["review_material"]["transfer_to_current"] = material


def _premerge(layout: workspace.Layout, pr: dict[str, Any], entry: Mapping[str, Any],
              saved: Mapping[str, Any]) -> dict[str, Any]:
    """Refresh exact review, source, issue and CI evidence immediately before native merge."""
    proof, review, tests = saved.get("execution_proof"), saved.get("review"), saved.get("verification")
    if (not isinstance(proof, dict) or proof.get("operation_id") != saved.get("review_operation")
            or proof.get("engine") != entry["engine"] or proof.get("model") != entry["model"]
            or proof.get("auth") != {"codex": "chatgpt", "claude-code": "claude-subscription"}.get(entry["engine"])
            or proof.get("source") != "native-session-metadata" or not isinstance(proof.get("native_session_id"), str)
            or not isinstance(proof.get("timestamp"), str) or not proof["timestamp"]
            or not isinstance(saved.get("conversation_provenance"), dict)
            or saved["conversation_provenance"].get("reviewer") != proof.get("conversation_id")
            or (entry["engine"] == "codex" and proof.get("effort") not in ("high", "xhigh", "max", "ultra"))
            or not isinstance(review, dict)
            or review.get("verdict") != "pass" or review.get("findings") != []
            or not isinstance(tests, dict) or tests.get("passed") is not True
            or tests.get("head_sha") != pr["head_sha"] or tests.get("targets") != entry["verify_targets"]):
        raise CycleError("review execution or sandbox verification is incomplete")
    owner_doc = review.get("owner_doc")
    assessment = review.get("scope_assessment")
    if (not isinstance(assessment, dict) or not isinstance(assessment.get("acceptance"), str)
            or not assessment["acceptance"].strip() or not isinstance(assessment.get("verify_coverage"), str)
            or not assessment["verify_coverage"].strip() or assessment.get("limitations") != []):
        raise CycleError("independent scope and Verify coverage assessment is incomplete")
    if (not isinstance(owner_doc, dict) or owner_doc.get("outcome") not in ("no_change", "already_updated")
            or not isinstance(owner_doc.get("inspected_paths"), list) or not owner_doc["inspected_paths"]
            or not isinstance(owner_doc.get("rationale"), str) or not owner_doc["rationale"].strip()):
        raise CycleError("owner-doc assessment requires governed continuation")
    fresh = observation._observe(observation._Reader(github_fetch, time.monotonic), int(pr["number"]))
    if fresh is None:
        raise CycleError("PR is no longer open")
    fresh.update(route="native", check_config=pr["check_config"])
    fresh["review_context"], fresh["review_material"] = _review_context(fresh)
    _add_transfer_review_context(layout, entry, fresh)
    if completion.work_identity(fresh) != completion.work_identity(pr) or completion._blocking_reviews(fresh["reviews"]):
        raise CycleError("PR contract, head or actionable review drifted")
    authority = native_authority(layout, fresh, entry)
    cwd, executor = Path(__file__).resolve().parents[2], SubprocessExecutor(timeout_seconds=30)
    files = _api_pages(executor, cwd, f"/pulls/{pr['number']}/files")
    files_digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    paths = sorted(str(x["filename"]) for x in files if isinstance(x, dict) and isinstance(x.get("filename"), str))
    sources = [p for p in paths if p.startswith(("app/", "scripts/", "tests/"))]
    if not paths or len(paths) != len(files) or review.get("covered_sources") != sources:
        raise CycleError("independent review does not cover the exact changed source paths")
    doc_receipt = f"post-merge owner-doc check: PR #{pr['number']}; no owner-doc change implied."
    if owner_doc["outcome"] == "already_updated":
        updates = owner_doc.get("updates")
        if (not isinstance(updates, list) or not updates or any(not isinstance(x, dict)
                or x.get("path") not in paths or not isinstance(x.get("path"), str)
                or not re.fullmatch(r"[A-Za-z0-9_./-]{1,300}", x["path"])
                or not isinstance(x.get("claim"), str)
                or not re.fullmatch(r"[A-Za-z0-9 ,.;:/()_-]{1,300}", x["claim"]) for x in updates)):
            raise CycleError("owner-doc changes lack exact updated paths and claims")
        doc_receipt = (f"post-merge owner-doc check: PR #{pr['number']}; owner docs updated in this PR: "
                       + "; ".join(f"{x['path']} ({x['claim']})" for x in updates) + ".")
    commits = _api_pages(executor, cwd, f"/pulls/{pr['number']}/commits")
    if not commits or any(not isinstance(c, dict) or not isinstance(c.get("commit"), dict)
                          or not isinstance(c["commit"].get("message"), str)
                          or has_closing_issue_attempt(c["commit"]["message"]) for c in commits):
        raise CycleError("commit closing references are unavailable or unintended")
    closing_hashes: dict[str, dict[str, str]] = {}
    for number in authority["closing_issues"]:
        issue = closure._issue(executor, cwd, completion.REPOSITORY, number)
        if issue.get("state") != "open":
            raise CycleError("closing Issue is not open")
        _assert_unheld_issue(issue)
        closing_hashes[str(number)] = closure._issue_hashes(issue)
        criteria = closure._acceptance_criteria(issue.get("body"), repo_root=layout.checkout(entry["worker"]))
        _assert_child_assessment(review, number, criteria)
        targets = [t.strip("`") for criterion in criteria for t in criterion["verify_targets"]]
        if any(not any(t == actual or t.startswith(actual + "::") for actual in entry["verify_targets"])
               for t in targets):
            raise CycleError("closing Issue Verify targets are not covered by executed tests")
    if ci_once(int(pr["number"]), cwd)["exit_code"] != 0:
        raise CycleError("current-head CI is pending, failed or unavailable")
    # The API, contract, claim and review surfaces are refreshed after CI too.
    again = observation._observe(observation._Reader(github_fetch, time.monotonic), int(pr["number"]))
    if again is None:
        raise CycleError("PR disappeared before merge")
    again.update(route="native", check_config=pr["check_config"])
    again["review_context"], again["review_material"] = _review_context(again)
    _add_transfer_review_context(layout, entry, again)
    if completion.work_identity(again) != completion.work_identity(pr) or completion._blocking_reviews(again["reviews"]):
        raise CycleError("PR changed during premerge verification")
    final = native_authority(layout, again, entry)
    if final != authority:
        raise CycleError("native merge authority changed during premerge verification")
    for number in authority["closing_issues"]:
        issue = closure._issue(executor, cwd, completion.REPOSITORY, number)
        if issue.get("state") != "open" or closure._issue_hashes(issue) != closing_hashes[str(number)]:
            raise CycleError("closing Issue contract changed during premerge verification")
        _assert_unheld_issue(issue)
    final_files = _api_pages(executor, cwd, f"/pulls/{pr['number']}/files")
    if hashlib.sha256(json.dumps(final_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != files_digest:
        raise CycleError("reviewed file delta changed during premerge verification")
    authority["owner_doc_receipt"] = doc_receipt
    authority["files_digest"] = files_digest
    authority["closing_issue_hashes"] = closing_hashes
    return authority


def _assert_child_assessment(review: Mapping[str, Any], number: int, criteria: list[dict[str, Any]]) -> None:
    assessments = review.get("closing_assessments")
    child = assessments.get(str(number)) if isinstance(assessments, dict) else None
    rows = child.get("criteria") if isinstance(child, dict) else None
    hashes = {criterion["criterion_sha256"] for criterion in criteria}
    if (not isinstance(child, dict) or child.get("acceptance") != "covered"
            or child.get("verify_coverage") != "covered" or child.get("limitations") != []
            or not isinstance(rows, dict) or set(rows) != hashes or not hashes
            or any(not isinstance(row, dict) or row.get("assessment") != "covered"
                   or not isinstance(row.get("rationale"), str) or not row["rationale"].strip()
                   for row in rows.values())):
        raise CycleError("closing Issue acceptance and Verify assessment is incomplete")


def _dispatcher_after_merge(layout: workspace.Layout, saved: dict[str, Any], owner: Mapping[str, Any],
                            executor: SubprocessExecutor, cwd: Path, governor: int, number: int) -> None:
    """Reconcile each native dispatcher effect against ordered events and durable intent."""
    keys = ("task_id", "repository", "issue_number", "lease_holder", "lease_id", "lease_expires_at", "linked_pr")
    if (any(not isinstance(owner.get(k), str) or not owner[k] for k in keys)
            or owner["repository"] != completion.REPOSITORY or owner["issue_number"] != str(governor)
            or owner["linked_pr"] != str(number)):
        raise CycleError("recorded dispatcher lease lacks recovery lineage")
    original = {k: owner[k] for k in keys}
    task_id = original["task_id"]
    task, events, lease = closure._dispatcher_inspect(executor, cwd, task_id)
    if (task.get("task_id") != task_id or task.get("repo") != completion.REPOSITORY
            or task.get("issue_number") != governor or str(task.get("linked_pr")) != str(number)):
        raise CycleError("dispatcher task identity drifted")
    history = [(i, e) for i, e in enumerate(events) if e.get("task_id") == task_id
               and e.get("event_type") in {"task.claimed", "task.released", "task.completed"}]
    original_claims = [(i, e) for i, e in history if e.get("event_type") == "task.claimed"
                       and e.get("actor") == original["lease_holder"] and e.get("lease_id") == original["lease_id"]]
    if len(original_claims) != 1:
        raise CycleError("original dispatcher claimant history is unavailable")
    after = [(i, e) for i, e in history if i > original_claims[0][0]]
    replacement = saved.get("dispatcher_replacement")
    reclaim = saved.get("dispatcher_reclaim_intent")
    if after and after[0][1].get("event_type") == "task.released":
        release_index = closure._planned_release_index(events, original)
        if after[0][0] != release_index:
            raise CycleError("dispatcher release history is ambiguous")
        subsequent = [(i, e) for i, e in after if i > release_index]
        if subsequent:
            claim = subsequent[0][1]
            if (not isinstance(reclaim, dict) or reclaim.get("original") != original
                    or claim.get("event_type") != "task.claimed"
                    or claim.get("actor") != original["lease_holder"]
                    or not isinstance(claim.get("lease_id"), str) or claim["lease_id"] == original["lease_id"]):
                raise CycleError("dispatcher replacement is not attributable to this reclaim")
            if len(subsequent) > 2 or (len(subsequent) == 2 and
                    (subsequent[1][1].get("event_type") != "task.completed"
                     or subsequent[1][1].get("actor") != claim["actor"]
                     or subsequent[1][1].get("lease_id") != claim["lease_id"])):
                raise CycleError("dispatcher replacement claimant history conflicts")
            if replacement is None:
                if task.get("status") != "claimed":
                    raise CycleError("dispatcher replacement completed without persisted lineage")
                replacement = closure._dispatcher_snapshot_from_task(
                    task, task_id, repository=completion.REPOSITORY, issue_number=governor,
                    pr_number=number, allow_expired=True, lease=lease)
                if replacement["lease_holder"] != claim["actor"] or replacement["lease_id"] != claim["lease_id"]:
                    raise CycleError("dispatcher replacement snapshot conflicts with its event")
                closure._validate_claimant_history(events, replacement)
                saved["dispatcher_replacement"] = replacement
                _save(layout, saved)
            elif (not isinstance(replacement, dict) or replacement.get("lease_id") != claim["lease_id"]
                  or replacement.get("lease_holder") != claim["actor"]):
                raise CycleError("persisted dispatcher replacement conflicts with history")
        else:
            if (task.get("status") != "ready" or any(task.get(k) is not None for k in
                    ("claimed_by", "lease_id", "lease_expires_at")) or replacement is not None):
                raise CycleError("dispatcher release readback is ambiguous")
            if reclaim is not None or saved.get("dispatcher_completion_intent"):
                raise CycleError("dispatcher reclaim outcome remains unknown; do not repeat")
            saved["dispatcher_reclaim_intent"] = {"original": original}
            _save(layout, saved)
            recovered = closure._dispatcher_reclaim(executor, cwd, original, repository=completion.REPOSITORY,
                                                    issue_number=governor, pr_number=number)
            saved["dispatcher_replacement"] = recovered
            _save(layout, saved)
            return _dispatcher_after_merge(layout, saved, owner, executor, cwd, governor, number)
    elif replacement is not None or reclaim is not None:
        raise CycleError("dispatcher recovery lineage is inconsistent")
    active = replacement if isinstance(replacement, dict) else original
    state = closure._dispatcher_completion(executor, cwd, active, repository=completion.REPOSITORY,
                                           issue_number=governor, pr_number=number, allow_expired_claim=True)
    if state["status"] == "completed":
        expected = [(i, e) for i, e in history if e.get("event_type") == "task.completed"
                    and e.get("actor") == active["lease_holder"] and e.get("lease_id") == active["lease_id"]]
        claims = [(i, e) for i, e in history if e.get("event_type") == "task.claimed"
                  and e.get("actor") == active["lease_holder"] and e.get("lease_id") == active["lease_id"]]
        if len(expected) != 1 or len(claims) != 1 or expected[0][0] <= claims[0][0] or history[-1] != expected[0]:
            raise CycleError("dispatcher completion event lineage is ambiguous")
        saved["dispatcher_completion"] = state
        _save(layout, saved)
        return
    if state["status"] != "claimed":
        raise CycleError("dispatcher completion state is unavailable")
    if saved.get("dispatcher_completion_intent"):
        raise CycleError("dispatcher completion outcome remains unknown; do not repeat")
    saved["dispatcher_completion_intent"] = {"lease": active}
    _save(layout, saved)
    executor.run([sys.executable, "-m", "app.dispatcher", "complete", task_id,
                  "--agent", active["lease_holder"], "--lease-id", active["lease_id"], "--json"], cwd=cwd)
    return _dispatcher_after_merge(layout, saved, owner, executor, cwd, governor, number)


def reconcile_native(layout: workspace.Layout, saved: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a persisted merge intent and its exact owner-doc receipts, without repeating unknown effects."""
    intent = saved.get("merge_intent")
    if not isinstance(intent, dict):
        raise CycleError("merge intent unavailable")
    cwd, executor = Path(__file__).resolve().parents[2], SubprocessExecutor(timeout_seconds=30)
    number, head = intent["number"], intent["head_sha"]
    if (type(number) is not int or number <= 0 or number != saved.get("number")
            or not isinstance(head, str) or not closure.SHA_RE.fullmatch(head)):
        raise CycleError("recorded merge intent identity is invalid")
    try:
        governor = intent["governing_issue"]
        mode = intent.get("coordination_mode")
        owner = intent.get("owner")
        if governor in intent["closing_issues"]:
            # Old intents predate the explicit mode; their authenticated snapshots
            # retain either the fallback mode or the exact dispatcher lease fields.
            if mode is None and isinstance(owner, dict):
                mode = owner.get("mode")
                if mode is None and all(isinstance(owner.get(k), str) and owner[k] for k in
                                        ("task_id", "lease_holder", "lease_id")):
                    mode = "dispatcher-backed"
            if mode == "github-label-only-fallback":
                if not isinstance(owner, dict) or owner.get("mode") != mode:
                    raise CycleError("recorded fallback coordination is ambiguous")
            elif mode != "dispatcher-backed" or not isinstance(owner, dict) or not all(
                    isinstance(owner.get(k), str) and owner[k] for k in ("task_id", "lease_holder", "lease_id")):
                raise CycleError("recorded dispatcher coordination is ambiguous")
        merged = closure._pr(executor, cwd, completion.REPOSITORY, number)
        observed_head = merged.get("head", {}).get("sha")
        if (merged.get("state") == "open" and merged.get("merged_at") is None
                and isinstance(observed_head, str) and closure.SHA_RE.fullmatch(observed_head)):
            # Retain the original intent, including an unknown outcome. A
            # different observed head is protected by the expected-head guard;
            # the same head remains fenced against a repeat merge.
            return {"number": number, "action": "wait", "reason": "earlier merge intent remains unresolved",
                    "intent_head_sha": head, "observed_head_sha": observed_head}
        sha = merged.get("merge_commit_sha")
        if (merged.get("state") != "closed" or merged.get("merged_at") is None
                or merged.get("head", {}).get("sha") != head or not isinstance(sha, str)
                or not closure.SHA_RE.fullmatch(sha)):
            raise CycleError("merge outcome remains unknown; do not repeat")
        if (merged.get("body") != intent["body"] or merged.get("title") != intent["title"]
                or closure._closing_issue_references(executor, cwd, completion.REPOSITORY, number)
                != intent["closing_issues"]):
            raise CycleError("merged PR contract differs from the persisted intent")
        files = _api_pages(executor, cwd, f"/pulls/{number}/files")
        if hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != intent["files_digest"]:
            raise CycleError("merged file delta differs from the reviewed candidate")
        for issue_number in intent["closing_issues"]:
            issue = closure._issue(executor, cwd, completion.REPOSITORY, issue_number)
            if (issue.get("state") != "closed"
                    or closure._issue_hashes(issue) != intent["closing_issue_hashes"][str(issue_number)]):
                raise CycleError("exact closing Issue has not closed")
            events = closure._issue_events(executor, cwd, completion.REPOSITORY, issue_number)
            closure._validate_closure_attribution(events, closure._closure_evidence(
                executor, cwd, completion.REPOSITORY, issue_number, events), completion.REPOSITORY,
                issue_number, sha, number)
        if governor not in intent["closing_issues"]:
            issue = closure._issue(executor, cwd, completion.REPOSITORY, governor)
            if (issue.get("state") != "open"
                    or closure._issue_hashes(issue) != intent["governing_issue_hashes"]):
                raise CycleError("non-closing governing Issue did not remain open")
        saved["merged_sha"] = sha
        _save(layout, saved)
        targets = sorted(set([governor, *intent["closing_issues"]]))
        body = intent["owner_doc_receipt"]
        if not isinstance(body, str) or not body.startswith(f"post-merge owner-doc check: PR #{number}; "):
            raise CycleError("owner-doc receipt is not bound to this PR")
        sent = saved.setdefault("owner_doc", {})
        for target in targets:
            key = str(target)
            comments = _api_pages(executor, cwd, f"/issues/{target}/comments")
            exact = [c for c in comments if isinstance(c, dict) and c.get("body") == body
                     and isinstance(c.get("user"), dict) and c["user"].get("login") == "RasmusTho"]
            if len(exact) > 1:
                raise CycleError("owner-doc receipt readback is ambiguous")
            if exact:
                sent[key] = "observed"
                _save(layout, saved)
                continue
            if sent.get(key) == "pending":
                raise CycleError("owner-doc comment outcome remains unknown; do not repeat")
            sent[key] = "pending"
            _save(layout, saved)
            executor.run(["gh", "api", "--hostname", "github.com", "--method", "POST",
                          f"repos/{completion.REPOSITORY}/issues/{target}/comments", "-f", f"body={body}"], cwd=cwd)
            comments = _api_pages(executor, cwd, f"/issues/{target}/comments")
            exact = [c for c in comments if isinstance(c, dict) and c.get("body") == body
                     and isinstance(c.get("user"), dict) and c["user"].get("login") == "RasmusTho"]
            if len(exact) != 1:
                raise CycleError("owner-doc comment result is not established")
            sent[key] = "observed"
            _save(layout, saved)
        if governor in intent["closing_issues"] and mode == "dispatcher-backed":
            if not isinstance(owner, dict):
                raise CycleError("recorded dispatcher coordination is ambiguous")
            _dispatcher_after_merge(layout, saved, owner, executor, cwd, governor, number)
        cleanup = saved.setdefault("label_cleanup", {})
        for target in intent["closing_issues"]:
            issue = closure._issue(executor, cwd, completion.REPOSITORY, target)
            labels = issue.get("labels")
            if not isinstance(labels, list) or any(not isinstance(x, dict) or not isinstance(x.get("name"), str) for x in labels):
                raise CycleError("closed Issue labels are unreadable")
            for label in [x["name"] for x in labels if x["name"].startswith(("agent:", "action:"))]:
                key = f"{target}:{label}"
                if cleanup.get(key) == "pending":
                    raise CycleError("label removal outcome remains unknown; do not repeat")
                cleanup[key] = "pending"
                _save(layout, saved)
                executor.run(["gh", "issue", "edit", str(target), "--repo", completion.REPOSITORY,
                              "--remove-label", label], cwd=cwd)
                current = closure._issue(executor, cwd, completion.REPOSITORY, target)
                current_labels = current.get("labels")
                if (not isinstance(current_labels, list) or any(not isinstance(x, dict)
                        or not isinstance(x.get("name"), str) for x in current_labels)
                        or any(x["name"] == label for x in current_labels)):
                    raise CycleError("label removal result is not established")
                cleanup[key] = "observed"
                _save(layout, saved)
        saved["reconciled"] = True
        _save(layout, saved)
        return {"number": number, "action": "merged", "merge_sha": sha}
    except closure.ClosureError as exc:
        raise CycleError(f"native merge readback unavailable: {exc.reason}") from exc


def merge_once(layout: workspace.Layout, pr: dict[str, Any], entry: Mapping[str, Any],
               saved: dict[str, Any]) -> dict[str, Any]:
    if saved.get("merge_intent"):
        return reconcile_native(layout, saved)
    authority = _premerge(layout, pr, entry, saved)
    worker = entry["worker"]
    with workspace._worker_lifecycle_lock(layout, worker):
        _review_verification_lineage(_mapping(layout, worker), saved)
        saved["merge_intent"] = authority
        _save(layout, saved)
        try:
            result = _command(["gh", "pr", "merge", str(pr["number"]), "--repo", completion.REPOSITORY,
                               "--squash", "--match-head-commit", pr["head_sha"],
                               "--subject", f"Merge PR #{pr['number']}", "--body", f"Delivered PR #{pr['number']}."], timeout=60)
            saved["merge_exit_code"] = result.returncode
            _save(layout, saved)
        except CycleError:
            pass  # The merge might have happened; read back rather than retrying.
    return reconcile_native(layout, saved)


def _outcome(operation_id: str, ref: str) -> dict[str, Any]:
    return {"status": "completed", "trusted": True, "operation_id": operation_id, "ref": ref}


def _mapping(layout: workspace.Layout, worker: str) -> dict[str, Any]:
    state = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)
    if state["epic_issue_number"] != layout.epic:
        raise CycleError("epic owner mismatch")
    issue = workspace._issue_for_worker(state, worker)
    return dict(state["issue_mappings"][str(issue)])


def _assert_live_container(layout: workspace.Layout, worker: str, mapping: Mapping[str, Any]) -> None:
    ident = mapping.get("container_id")
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{12,64}", ident):
        raise CycleError("recorded container identity unavailable")
    result = _command(["docker", "inspect", ident], timeout=15)
    try:
        rows = json.loads(result.stdout) if result.returncode == 0 else None
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
        labels = row.get("Config", {}).get("Labels", {}) if isinstance(row, dict) else {}
        if (not isinstance(row, dict) or not str(row.get("Id", "")).startswith(ident)
                or row.get("Name") != "/" + layout.container_name(worker)
                or row.get("State", {}).get("Running") is not True
                or labels.get(workspace.LABEL_EPIC) != str(layout.epic)
                or labels.get(workspace.LABEL_WORKER) != worker):
            raise CycleError("worker container identity is not verified")
    except (ValueError, TypeError, AttributeError) as exc:
        raise CycleError("worker container identity is unreadable") from exc


@workspace._serialized_worker
def native_execution_proof(layout: workspace.Layout, worker: str, operation_id: str,
                           admission: Mapping[str, Any], *,
                           http: Callable[..., tuple[int, Any]] = workspace._http) -> dict[str, Any]:
    """Observe the actual container, ACP conversation and subscription login without retaining secrets."""
    mapping = _mapping(layout, worker)
    _assert_live_container(layout, worker, mapping)
    record = mapping.get("conversation")
    image = mapping.get("image")
    credentials = mapping.get("credentials")
    engine, model = workspace.resolve_engine(admission["engine"], admission["model"])
    if (not isinstance(record, dict) or record.get("operation_id") != operation_id
            or record.get("engine") != engine or record.get("model") != model
            or not isinstance(credentials, dict)
            or (engine == "codex" and credentials.get("codex") != "chatgpt-login-dir")
            or (engine == "claude-code" and credentials.get("claude") != "oauth-token-env")
            or not isinstance(image, str) or not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image)):
        raise CycleError("native execution configuration is not admitted")
    ident = mapping["container_id"]
    container = _command(["docker", "inspect", ident], timeout=15)
    pinned = _command(["docker", "image", "inspect", image], timeout=15)
    try:
        row = json.loads(container.stdout)[0]
        pinned_row = json.loads(pinned.stdout)[0]
        env = row["Config"].get("Env", [])
        if (container.returncode or pinned.returncode or row["Image"] != pinned_row["Id"]
                or row["Config"]["Image"] != image or not isinstance(env, list)
                or any(isinstance(x, str) and x.split("=", 1)[0] in (
                    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                    "CHATGPT_BASE_URL", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY") for x in env)):
            raise CycleError("native container image or credential environment mismatch")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise CycleError("native image readback unavailable") from exc
    if engine == "claude-code" and not any(isinstance(x, str) and x.startswith("CLAUDE_CODE_OAUTH_TOKEN=") and len(x.split("=", 1)[1]) > 0 for x in env):
        raise CycleError("native subscription authentication not verified")
    if engine == "claude-code":
        login = _command(["docker", "exec", ident, "python", "-c", CLAUDE_STATUS], timeout=30)
        try:
            login_status = json.loads(login.stdout) if login.returncode == 0 else None
            if (not isinstance(login_status, dict) or login_status.get("loggedIn") is not True
                    or login_status.get("authMethod") not in ("claude.ai", "oauth_token")
                    or login_status.get("apiProvider") != "firstParty"):
                raise CycleError("native subscription authentication not verified")
        except ValueError as exc:
            raise CycleError("native subscription authentication not verified") from exc
    auth = _command(["docker", "exec", ident, "/acp-node/bin/node", CODEX_CLI, "login", "status"], timeout=30) if engine == "codex" else None
    if auth is not None and (auth.returncode != 0 or "logged in using chatgpt" not in (auth.stdout + auth.stderr).casefold()):
        raise CycleError("native subscription authentication not verified")
    config_check = (
        "import pathlib,tomllib; p=pathlib.Path('/run/codex-home/config.toml'); "
        "c=tomllib.loads(p.read_text()) if p.exists() else {}; "
        "assert c.get('model') in (None,'gpt-6.1-terra'); "
        "assert c.get('model_provider') in (None,'openai'); "
        "assert c.get('openai_base_url') is None; "
        "assert c.get('chatgpt_base_url') in (None,'https://chatgpt.com/backend-api/'); "
        "assert not c.get('model_providers') and not c.get('profiles'); print('route-ok')"
    )
    if engine == "codex":
        config = _command(["docker", "exec", ident, "python", "-c", config_check], timeout=15)
        if config.returncode != 0 or config.stdout.strip() != "route-ok":
            raise CycleError("native subscription provider configuration not verified")
    cid = record.get("id")
    if not isinstance(cid, str):
        raise CycleError("conversation identity unavailable")
    state = workspace._load_state(layout)
    issue = workspace._issue_for_worker(state, worker)
    try:
        with workspace._endpoint_session(layout, worker, issue, mapping, _worker_runner) as (port, key):
            code, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
            if code != 200 or not workspace._conversation_bound(info, layout, issue, worker, cid):
                raise CycleError("native conversation identity is not established")
            status = workspace.conversation_status(layout, worker, http=http, runner=_worker_runner, include_messages=False)
    except workspace.EpicWorkspaceError as exc:
        raise CycleError("native conversation endpoint is unavailable") from exc
    agent = info.get("agent") if isinstance(info, dict) else None
    kinds = status.get("event_kinds")
    if (code != 200 or not isinstance(info, dict) or str(info.get("id")) != cid
            or not isinstance(agent, dict) or agent.get("kind") != "ACPAgent"
            or agent.get("acp_server") != engine or agent.get("acp_model") != model
            or info.get("current_model_id") != model
            or not isinstance(info.get("current_effort"), str)
            or not isinstance(info.get("available_efforts"), list)
            or not any(isinstance(e, dict) and e.get("value") == info["current_effort"]
                       for e in info["available_efforts"])
            or status.get("reachable") is not True or status.get("execution_status") not in ("finished", "FINISHED")
            or status.get("errors") or not isinstance(kinds, list)
            or any(isinstance(k, str) and ("rerout" in k.casefold() or "fallback" in k.casefold()) for k in kinds)):
        raise CycleError("native conversation execution is not established")
    # Execute the controller-owned extractor in the existing worker; it emits only allowlisted metadata.
    extractor = Path(__file__).with_name("openhands_native_metadata.py").read_text(encoding="utf-8")
    observed = _command(["docker", "exec", ident, "python", "-c", extractor, workspace.CONTAINER_HOME,
                         workspace.CODEX_HOME_TARGET, engine, cid], timeout=30)
    try:
        evidence = json.loads(observed.stdout) if observed.returncode == 0 else None
        live_agent = info.get("agent_state")
        if (not isinstance(evidence, dict) or set(evidence) != {"engine", "conversation_id", "session_id", "model", "effort", "timestamp"}
                or evidence.get("engine") != engine or evidence.get("conversation_id") != cid
                or evidence.get("model") != model or not isinstance(evidence.get("session_id"), str)
                or not isinstance(live_agent, dict) or live_agent.get("acp_session_id") != evidence["session_id"]
                or live_agent.get("acp_session_cwd") != "/workspace"
                or not isinstance(evidence.get("timestamp"), str) or not evidence["timestamp"]
                or (engine == "codex" and (evidence.get("effort") != info["current_effort"]
                    or evidence.get("effort") not in ("high", "xhigh", "max", "ultra")))
                or (engine == "claude-code" and evidence.get("effort") is not None)):
            raise CycleError("native execution metadata does not match selected model or effort")
    except ValueError as exc:
        raise CycleError("native execution metadata is unreadable") from exc
    return {"conversation_id": cid, "native_session_id": evidence["session_id"],
            "operation_id": operation_id, "container_id": ident, "image": image,
            "engine": engine, "model": evidence["model"], "effort": evidence["effort"],
            "timestamp": evidence["timestamp"],
            "auth": "chatgpt" if engine == "codex" else "claude-subscription",
            "source": "native-session-metadata"}


def _review_prompt(pr: Mapping[str, Any], identity: str, targets: list[str]) -> str:
    return (f"Independently review PR #{pr['number']} at head {pr['head_sha']} and contract identity {identity}. "
            "Read the code, governing contract and applicable delivery rules. Inspect acceptance and Verify "
            "coverage and owner-doc impact. When transfer_to_current is supplied, assess that delta for dropped "
            "obligations or harmful reverts against the contract; judge intended fixes and refactors on their merits. "
            "Do not write or publish. In your final public response put one JSON "
            "object between <BEGIN_PR_CYCLE_REPORT> and <END_PR_CYCLE_REPORT>. Public closeout text may precede "
            "the delimiter, but do not put other JSON objects there. Include identity, head_sha, "
            "verdict (pass or findings), findings (array), "
            "verify_targets (array of exact targets reviewed), covered_sources (sorted array of every changed "
            "app/, scripts/ or tests/ path examined), scope_assessment (acceptance, verify_coverage, "
            "limitations), owner_doc (outcome, inspected_paths and rationale), "
            "closing_assessments keyed by exact Issue number, each with acceptance and verify_coverage "
            "(covered or incomplete), limitations array, and criteria keyed by SHA-256 of the exact criterion "
            "text, each with assessment and substantive rationale. Assess every criterion "
            "against the actual implementation, not merely the names of test targets. Obtain criterion hashes "
            "using app.builderops.closure._acceptance_criteria on each supplied Issue body. "
            f"Requested Verify targets: {json.dumps(targets)}. PR body: {pr['body']}\n"
            f"Governing Issue: {pr['governing_issue']['body']}\n"
            f"Exact closing contracts and reviewed file patches: {json.dumps(pr['review_material'])}")


def start_or_reconcile_review(layout: workspace.Layout, worker: str, operation_id: str,
                              pr: Mapping[str, Any], identity: str, admission: Mapping[str, Any],
                              *, http: Callable[..., tuple[int, Any]] = workspace._http) -> dict[str, Any]:
    mapping = _mapping(layout, worker)
    if mapping.get("state") != "running" or mapping.get("runtime") != "openhands":
        raise CycleError("review worker is not a running OpenHands worker")
    _assert_live_container(layout, worker, mapping)
    prior = mapping.get("conversation")
    if isinstance(prior, dict) and prior.get("operation_id") == operation_id:
        if prior.get("status") in ("creating", "unknown"):
            return workspace.reconcile_worker_conversation(layout, worker, http=http, runner=_worker_runner)
        return prior
    if isinstance(prior, dict) and prior.get("status") != workspace.CONVERSATION_ENDED:
        raise CycleError("previous conversation may still write")
    checkout = workspace.inspect_checkout(layout, worker)
    if (checkout.get("readable") is not True or checkout.get("head") != pr["head_sha"]
            or checkout.get("uncommitted_count") != 0):
        raise CycleError("review checkout is not clean at the admitted head")
    return workspace.start_conversation(
        layout, worker, engine=admission["engine"], model=admission["model"],
        prompt=_review_prompt(pr, identity, admission["verify_targets"]), operation_id=operation_id,
        http=http, runner=_worker_runner)


def _public_report(text: Any) -> dict[str, Any] | None:
    """Parse one bounded public finish response, never agent reasoning or events."""
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 65536:
        return None
    begin, end = "<BEGIN_PR_CYCLE_REPORT>", "<END_PR_CYCLE_REPORT>"
    if begin in text or end in text:
        if text.count(begin) != 1 or text.count(end) != 1 or text.index(end) < text.index(begin):
            return None
        prefix, remainder = text.split(begin)
        body, suffix = remainder.split(end)
        if suffix.strip() or any(c in prefix for c in "{}[]"):
            return None
    else:
        body = text

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate report field")
            value[key] = item
        return value

    def bounded(value: Any, depth: int = 0) -> bool:
        if depth > 20:
            return False
        if isinstance(value, dict):
            return all(bounded(v, depth + 1) for v in value.values())
        if isinstance(value, list):
            return all(bounded(v, depth + 1) for v in value)
        return True

    def invalid_constant(value: str) -> None:
        raise ValueError("non-JSON constant")

    try:
        result = json.loads(body, object_pairs_hook=unique, parse_constant=invalid_constant)
        return result if isinstance(result, dict) and bounded(result) else None
    except (ValueError, RecursionError):
        return None


@workspace._serialized_worker
def review_result(layout: workspace.Layout, worker: str, operation_id: str,
                  pr: Mapping[str, Any], identity: str, admission: Mapping[str, Any],
                  *, http: Callable[..., tuple[int, Any]] = workspace._http) -> dict[str, Any] | None:
    mapping = _mapping(layout, worker)
    _assert_live_container(layout, worker, mapping)
    try:
        state = workspace._load_state(layout)
        issue = workspace._issue_for_worker(state, worker)
        with workspace._endpoint_session(layout, worker, issue, mapping, _worker_runner) as (port, key):
            status = workspace.conversation_status(layout, worker, http=http, runner=_worker_runner, include_messages=False)
            conversation = status.get("conversation")
            if (not isinstance(conversation, dict) or conversation.get("operation_id") != operation_id
                    or status.get("reachable") is not True or status.get("execution_status") not in ("finished", "FINISHED")
                    or status.get("errors")):
                return None
            cid = conversation.get("id")
            if not isinstance(cid, str) or not cid:
                return None
            code, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
            if (code != 200 or not workspace._conversation_bound(info, layout, issue, worker, cid)
                    or info.get("execution_status") not in ("finished", "FINISHED")):
                return None
            code, final = http("GET", port, key, f"/conversations/{cid}/agent_final_response", None, 10.0)
            result = _public_report(final.get("response") if code == 200 and isinstance(final, dict) else None)
    except (OSError, ValueError, RecursionError, workspace.EpicWorkspaceError):
        return None
    allowed = {"identity", "head_sha", "verdict", "findings", "verify_targets", "owner_doc",
               "covered_sources", "scope_assessment", "closing_assessments"}
    if (not isinstance(result, dict) or not set(result) <= allowed
            or result.get("identity") != identity or result.get("head_sha") != pr["head_sha"]
            or result.get("verdict") not in ("pass", "findings") or not isinstance(result.get("findings"), list)
            or result.get("verify_targets") != admission["verify_targets"]
            or not isinstance(result.get("owner_doc"), dict)
            or (result["verdict"] == "pass" and result["findings"])
            or (result["verdict"] == "findings" and not result["findings"])):
        return None
    # A model's own account of its execution is not a runtime authentication receipt.
    # The controller must independently prove the executing engine before qualification.
    return result


def _validate_admission(value: Any) -> dict[int, dict[str, Any]]:
    if not isinstance(value, list):
        raise CycleError("admissions must be a list")
    admitted: dict[int, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise CycleError("invalid admission")
        number, head, worker = row.get("number"), row.get("head_sha"), row.get("worker")
        targets = row.get("verify_targets")
        if (type(number) is not int or number <= 0 or number in admitted or not isinstance(head, str)
                or not re.fullmatch(r"[0-9a-f]{40}", head) or not isinstance(worker, str)
                or row.get("native_session_owned") is not True
                or not isinstance(targets, list) or not targets or not all(isinstance(t, str) and t for t in targets)
                or not isinstance(row.get("test_venv"), str) or not row["test_venv"]):
            raise CycleError("invalid admission identity or Verify targets")
        workspace.validate_worker_id(worker)
        engine, model = workspace.resolve_engine(row.get("engine", ""), row.get("model"))
        admitted[number] = {**row, "engine": engine, "model": model}
    return admitted


def advance(layout: workspace.Layout, admissions: list[dict[str, Any]], *,
            fetch: observation.Fetch = github_fetch,
            http: Callable[..., tuple[int, Any]] = workspace._http) -> dict[str, Any]:
    admitted = _validate_admission(admissions)
    with _single_advancement(layout):
        state = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)
        if state["epic_issue_number"] != layout.epic:
            raise CycleError("epic owner mismatch")
        scan = observation.collect(fetch)
        results: list[dict[str, Any]] = []
        reconciling: dict[int, list[tuple[str, str, str] | None]] = {}
        for saved in state["compact_receipts"]:
            if (not isinstance(saved, dict) or saved.get("kind") != "pr_cycle"
                    or not isinstance(saved.get("merge_intent"), dict) or saved.get("reconciled") is True):
                continue
            number = saved.get("number")
            if type(number) is not int:
                continue
            try:
                result = reconcile_native(layout, dict(saved))
                results.append(result)
                old_head, observed_head = result.get("intent_head_sha"), result.get("observed_head_sha")
                identity = saved.get("identity")
                if isinstance(old_head, str) and isinstance(observed_head, str) and isinstance(identity, str) and identity:
                    reconciling.setdefault(number, []).append((identity, old_head, observed_head))
                else:
                    reconciling.setdefault(number, []).append(None)
            except (CycleError, closure.ClosureError, observation.ObservationError, OSError, ValueError,
                    KeyError, AttributeError, TypeError, RecursionError) as exc:
                reconciling.setdefault(number, []).append(None)
                results.append({"number": number, "action": "wait", "reason": str(exc)})
        for pr in scan["observations"]:
            number = pr["number"]
            obligations = reconciling.get(number, [])
            if any(item is None or item[2] != pr["head_sha"]
                   for item in obligations):
                continue
            entry = admitted.get(number)
            if entry is None or entry["head_sha"] != pr["head_sha"]:
                results.append({"number": number, "action": "wait", "reason": "not admitted at this head"})
                continue
            try:
                pending = [(item[0], item[1]) for item in obligations if item is not None]
                if pending:
                    results.append(_advance_one(layout, pr, entry, http=http, merge_obligations=pending))
                else:
                    results.append(_advance_one(layout, pr, entry, http=http))
            except (CycleError, closure.ClosureError, observation.ObservationError, workspace.EpicWorkspaceError,
                    OSError, ValueError, KeyError, AttributeError, TypeError, RecursionError) as exc:
                results.append({"number": number, "action": "wait", "reason": str(exc)})
        return {"repository": completion.REPOSITORY, "inventory_complete": scan["inventory_complete"],
                "failures": scan["failures"], "results": results}


def _review_stop_checkpoint(mapping: Mapping[str, Any], saved: Mapping[str, Any], *,
                            require_receipt: bool) -> Any:
    intent = saved.get("stop_intent")
    if (not isinstance(intent, dict) or not isinstance(intent.get("stop_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", intent["stop_id"])
            or "previous_stop_id" not in intent):
        raise CycleError("reviewer stop intent has no exact stop generation; reconcile the old record")
    assignment = intent.get("assignment")
    proof = saved.get("execution_proof")
    conversation = mapping.get("conversation")
    if (not isinstance(assignment, dict) or not isinstance(proof, dict)
            or intent.get("container_id") != mapping.get("container_id")
            or proof.get("container_id") != intent.get("container_id")
            or not isinstance(conversation, dict)
            or proof.get("conversation_id") != conversation.get("id")
            or proof.get("operation_id") != conversation.get("operation_id")):
        raise CycleError("review stop receipt does not bind the current worker assignment")
    before = workspace.assignment_of(assignment)
    current = workspace.assignment_of(mapping)
    if (any(before[field] != current[field] for field in workspace.ASSIGNMENT_FIELDS if field != "state")
            or not isinstance(before["conversation"], dict) or not isinstance(current["conversation"], dict)
            or before["conversation"].get("id") != current["conversation"].get("id")
            or current["conversation"].get("status") not in
            (before["conversation"].get("status"), workspace.CONVERSATION_ENDED)):
        raise CycleError("review stop receipt does not bind the current worker assignment")
    try:
        work = workspace._completed_stop(mapping, intent["stop_id"])
    except workspace.TakeoverRefused as exc:
        raise CycleError(str(exc)) from exc
    checkpoint = work["checkpoint"]
    if require_receipt and (saved.get("stop_verified") is not True or "checkpoint" not in intent
                            or intent["checkpoint"] != checkpoint):
        raise CycleError("review stop receipt does not match the current completed checkpoint; reconcile it")
    return checkpoint


def _review_verification_lineage(mapping: Mapping[str, Any], saved: Mapping[str, Any]) -> None:
    _review_stop_checkpoint(mapping, saved, require_receipt=True)
    if mapping.get("checkpoint_inspection_unknown"):
        raise CycleError("checkpoint or verification cleanup remains unresolved; reconcile the worker")
    verification = saved.get("verification")
    intent = saved["stop_intent"]
    if not isinstance(verification, dict) or verification.get("stop_id") != intent["stop_id"]:
        raise CycleError("verification receipt does not match the current stop; reconcile the review")


def _release_reviewer(layout: workspace.Layout, worker: str, saved: dict[str, Any],
                      observed: Mapping[str, Any]) -> None:
    """Stop the reviewed assignment and reconcile an uncertain stop through the lifecycle."""
    reason = "review completed; release model capacity"
    mapping = _mapping(layout, worker)
    if not workspace._same_assignment(mapping, observed):
        raise CycleError("reviewer assignment changed before release")
    proof = saved.get("execution_proof")
    conversation = mapping.get("conversation")
    if (not isinstance(proof, dict) or proof.get("container_id") != mapping.get("container_id")
            or not isinstance(conversation, dict) or proof.get("conversation_id") != conversation.get("id")
            or proof.get("operation_id") != conversation.get("operation_id")):
        raise CycleError("review proof does not bind the current worker assignment")
    intent = saved.get("stop_intent")
    if intent is None:
        if mapping.get("state") != "running":
            raise CycleError("reviewer is no longer running before release")
        ident = mapping.get("container_id")
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{12,64}", ident):
            raise CycleError("reviewer container identity is unavailable")
        _assert_live_container(layout, worker, mapping)
        intent = {"container_id": ident, "assignment": workspace.assignment_of(mapping),
                  "previous_stop_id": mapping.get("stop_id"), "stop_id": uuid.uuid4().hex}
        saved["stop_intent"] = intent
        _save(layout, saved, expected_worker=worker, expected_assignment=mapping)
    if (not isinstance(intent, dict) or not isinstance(intent.get("container_id"), str)
            or not workspace._CONTAINER_ID.fullmatch(intent["container_id"])
            or intent["container_id"] != mapping.get("container_id")):
        raise CycleError("reviewer stop intent has no exact container lineage")
    if (not isinstance(intent.get("stop_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", intent["stop_id"])
            or "previous_stop_id" not in intent):
        raise CycleError("reviewer stop intent has no exact stop generation; reconcile the old record")
    assignment = intent.get("assignment")
    def check_lineage(current_mapping: Mapping[str, Any]) -> None:
        if not isinstance(assignment, dict):
            raise CycleError("reviewer stop assignment is missing or malformed; reconcile the old record")
        before = workspace.assignment_of(assignment)
        current = workspace.assignment_of(current_mapping)
        if (any(before[field] != current[field] for field in workspace.ASSIGNMENT_FIELDS if field != "state")
                or not isinstance(before["conversation"], dict)
                or not isinstance(current["conversation"], dict)
                or before["conversation"].get("id") != current["conversation"].get("id")
                or (current_mapping.get("state") == "stopped_verified" and
                    current["conversation"].get("status") not in
                    (before["conversation"].get("status"), workspace.CONVERSATION_ENDED))
                or (current_mapping.get("state") != "stopped_verified" and before != current)):
            raise CycleError("reviewer assignment changed since stop intent")
    check_lineage(mapping)
    if not saved.get("stop_verified"):
        if (mapping.get("stop_id") != intent["stop_id"]
                and (mapping.get("state") != "running" or mapping.get("stop_id") != intent["previous_stop_id"])):
            raise CycleError("a newer reviewer stop requires reconciliation")
        # An interrupted ID-bound stop can be retried safely through the existing
        # stop/checkpoint path; absence alone must not manufacture its completion.
        try:
            workspace.stop_worker(layout, worker, reason=reason, expected_container_id=intent["container_id"],
                                  expected_assignment=mapping, stop_intent=intent)
        except workspace.EpicWorkspaceError:
            check_lineage(_mapping(layout, worker))
            raise
    with workspace._worker_lifecycle_lock(layout, worker):
        mapping = _mapping(layout, worker)
        check_lineage(mapping)
        if (mapping.get("container_id") != intent["container_id"]
                or not isinstance(mapping.get("conversation"), dict)
                or mapping["conversation"].get("id") != proof["conversation_id"]):
            raise CycleError("reviewer assignment changed after stop")
        _assert_stopped(layout, worker, mapping)
        checkpoint = _review_stop_checkpoint(mapping, saved, require_receipt=bool(saved.get("stop_verified")))
        verified = {**saved, "stop_intent": {**intent, "checkpoint": checkpoint}, "stop_verified": True}
        _save(layout, verified, expected_worker=worker, expected_assignment=mapping)
        saved.update(verified)


def _advance_one(layout: workspace.Layout, pr: dict[str, Any], entry: dict[str, Any], *,
                 http: Callable[..., tuple[int, Any]],
                 merge_obligations: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
    # Until independently observed, route/owner are unknown. Explicit trial admission
    # selects native session-owned review only; it does not assert merge eligibility.
    if re.search(r"\b(?:draft[ -]only|do[ -]not[ -]merge|do not merge|merge hold)\b", pr["body"], re.I):
        pr["restrictions"].append("possible PR-specific hold")
    pr.update(route="native", owner="unknown", effect_outcome="none", review_outcome="missing",
              check_config={"verify_targets": entry["verify_targets"], "test_venv": entry["test_venv"]})
    pr["review_context"], pr["review_material"] = _review_context(pr)
    _add_transfer_review_context(layout, entry, pr)
    identity = completion.work_identity(pr)
    if any(old_identity == identity for old_identity, _ in merge_obligations):
        return {"number": pr["number"], "action": "wait", "identity": identity,
                "reason": "merge outcome remains unknown; do not repeat"}
    saved = _find(layout, pr["number"], identity)
    operation_id = saved.get("review_operation")
    if operation_id:
        worker_record = _mapping(layout, entry["worker"])
        conversation = worker_record.get("conversation")
        cid = conversation.get("id") if isinstance(conversation, dict) else None
        review = saved.get("review") if saved.get("public_report_conversation") == cid and cid else None
        if review is None:
            review = review_result(layout, entry["worker"], operation_id, pr, identity, entry, http=http)
        if review is not None:
            saved["review"] = review
            saved["public_report_conversation"] = cid
            history = worker_record.get("conversation_history", [])
            saved["conversation_provenance"] = {"author": None,
                "reviewer": conversation.get("id") if isinstance(conversation, dict) else None,
                "prior_conversations": [row["id"] for row in history if isinstance(row, dict)
                                        and isinstance(row.get("id"), str)] if isinstance(history, list) else []}
            _save(layout, saved)
            if "execution_proof" not in saved:
                saved["execution_proof"] = native_execution_proof(layout, entry["worker"], operation_id, entry, http=http)
            if (not isinstance(saved["execution_proof"], dict)
                    or saved["execution_proof"].get("conversation_id") != cid
                    or saved["execution_proof"].get("operation_id") != operation_id):
                raise CycleError("public report and native execution proof do not bind the same conversation")
            _save(layout, saved)
            pr["effect_outcomes"][operation_id] = _outcome(operation_id, f"openhands:{operation_id}")
            pr["review_outcome"] = "pass" if review["verdict"] == "pass" and not review["findings"] else "changes_requested"
            pr["independent_review_identity"] = identity
            _release_reviewer(layout, entry["worker"], saved, worker_record)
            if pr["review_outcome"] == "pass":
                if "verification" not in saved:
                    verification = sandbox_verify(layout, entry["worker"], pr["head_sha"],
                                                  entry["verify_targets"], entry["test_venv"], saved)
                    with workspace._worker_lifecycle_lock(layout, entry["worker"]):
                        current = _mapping(layout, entry["worker"])
                        _review_stop_checkpoint(current, saved, require_receipt=True)
                        saved["verification"] = {**verification, "stop_id": saved["stop_intent"]["stop_id"]}
                        _save(layout, saved, expected_worker=entry["worker"], expected_assignment=current)
                with workspace._worker_lifecycle_lock(layout, entry["worker"]):
                    _review_verification_lineage(_mapping(layout, entry["worker"]), saved)
                if saved["verification"].get("passed") is True:
                    saved["ci"] = ci_once(pr["number"], Path(__file__).resolve().parents[2])
                    _save(layout, saved)
    decision = completion.intake([pr], run_id=layout.run_id, root=layout.run_state_dir,
                                 expected_run_id=layout.run_id, expected_root=layout.run_state_dir,
                                 expected_epic_issue_number=layout.epic)[0]
    if (pr["review_outcome"] == "pass" and isinstance(saved.get("verification"), dict)
            and saved["verification"].get("passed") is True and isinstance(saved.get("ci"), dict)
            and saved["ci"].get("exit_code") == 0 and decision["action"] == "wait"
            and decision["reason"] == "active or unknown writable owner"):
        if any(old_head == pr["head_sha"] for _, old_head in merge_obligations):
            return {"number": pr["number"], "action": "wait", "identity": identity,
                    "reason": "earlier merge at this head remains unknown; do not repeat"}
        return merge_once(layout, pr, entry, saved)
    if decision["action"] in ("independent-review", "reconcile"):
        op = decision["operation_id"]
        records = epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)["dispatch_decisions"]
        reserved_here = any(isinstance(r, dict) and r.get("operation_id") == op
                            and r.get("identity") == identity and r.get("request") == "independent-review"
                            and r.get("outcome") == "unknown"
                            for r in records)
        if op and reserved_here and (operation_id in (None, op)):
            saved["review_operation"] = op
            _save(layout, saved)
            started = start_or_reconcile_review(layout, entry["worker"], op, pr, identity, entry, http=http)
            decision["reason"] = f"conversation {started.get('id')} {started.get('status')}"
    return dict(decision)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--epic", required=True, type=int)
    parser.add_argument("--config", required=True, help="controller-owned JSON admission file")
    args = parser.parse_args(argv)
    try:
        path = Path(args.config)
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022
                or workspace._is_within(path, Path(args.root).resolve() / f"epic-{args.epic}" / "workers")):
            raise CycleError("admission configuration must be controller-owned and outside worker directories")
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise CycleError("invalid configuration")
        result = advance(workspace.Layout(Path(args.root).resolve(), args.epic), config.get("admissions", []))
    except (OSError, ValueError, CycleError, workspace.EpicWorkspaceError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["inventory_complete"] and not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
