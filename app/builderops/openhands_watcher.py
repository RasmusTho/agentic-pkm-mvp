"""One bounded host-side continuation for an authorized OpenHands run."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_factory as factory
from app.builderops import openhands_service as service
from app.builderops import publication
from app.dispatcher import leases
from app.dispatcher.cli import _make_store
from scripts import agent_worktree
from scripts.pr_body_generator import generate_pr_body_from_mapping

HANDOFF = ".codex-tmp/openhands-finish.json"
BODY_FIELDS = frozenset({"summary", "sbs_impact", "owner_doc_resolution", "builderops_records", "builderops_reason"})
POLL_SECONDS = 10
MAX_HEARTBEAT_INTERVAL = 30 * 60


def launch(install: Path, directory: Path, issue: int, repo: Path, worktree_root: Path) -> None:
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700, exist_ok=True)
    info = watch_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise delivery.DeliveryError("Watcher state directory is not private")
    log = os.open(watch_dir / "watcher.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR",
           "DISPATCHER_STATE_DIR", "DISPATCHER_DB_PATH", "DISPATCHER_EVENTS_PATH") if k in os.environ}
    env["PYTHONPATH"] = str(factory.FACTORY_ROOT)
    try:
        with os.fdopen(log, "ab") as stream:
            subprocess.Popen(
                [str(install / "venv/bin/python"), "-m", "app.builderops.openhands_watcher",
                 str(install), str(directory), str(issue), str(repo), str(worktree_root)],
                cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                start_new_session=True, close_fds=True,
            )
    except OSError as exc:
        raise delivery.DeliveryError("Watcher launch failed; use status and reconcile before retry") from exc


def status(directory: Path) -> dict[str, Any]:
    watch_dir = directory / "watcher"
    if not watch_dir.is_dir():
        return {"status": "not_started"}
    data = service._read(watch_dir)
    if data is None:
        return {"status": "pending", "reason": "Watcher has not recorded its start"}
    try:
        fd = os.open(watch_dir / "watch.lock", os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                running = True
            else:
                running = False
    except OSError:
        running = False
    if not running and data.get("status") == "running":
        return {**data, "status": "pending", "reason": "Watcher stopped; inspect and retry the recorded phase"}
    heartbeat = service._read(watch_dir / "heartbeat") if (watch_dir / "heartbeat").is_dir() else None
    if isinstance(heartbeat, dict):
        data = {**data, "heartbeat": heartbeat}
        if heartbeat.get("status") == "failed" and data.get("status") == "running":
            return {**data, "status": "pending", "reason": "Lease renewal failed; publication is fenced"}
        if heartbeat.get("status") == "healthy" and data.get("status") == "running":
            try:
                worktree_expiry = heartbeat["worktree_expires_at"]
                if isinstance(worktree_expiry, bool) or not isinstance(worktree_expiry, (int, float)):
                    raise ValueError("invalid worktree expiry")
                remaining = worktree_expiry - time.time()
                dispatcher_expiry = heartbeat.get("dispatcher_expires_at")
                if dispatcher_expiry is not None:
                    expires = datetime.fromisoformat(dispatcher_expiry.replace("Z", "+00:00"))
                    remaining = min(remaining, (expires - datetime.now(timezone.utc)).total_seconds())
                if remaining <= 0:
                    raise ValueError("expired heartbeat")
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                return {**data, "status": "pending", "reason": "Lease renewal is unconfirmed or expired"}
    return data


class _LeaseKeeper:
    """Renew only the recorded, still-live claim during worker and finish activity."""

    def __init__(self, state: dict[str, Any], watch_dir: Path) -> None:
        self.state = state
        self.watch_dir = watch_dir
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.error: str | None = None
        self.valid_until: float | None = None
        self.expires_at: float | None = None
        self.thread: threading.Thread | None = None
        self.runner = delivery.DraftOnlyExecutor()
        self.heartbeat_dir = watch_dir / "heartbeat"
        self.heartbeat_dir.mkdir(mode=0o700, exist_ok=True)

    def check(self) -> None:
        with self.lock:
            if self.error is None and (
                (self.valid_until is not None and time.monotonic() >= self.valid_until)
                or (self.expires_at is not None and time.time() >= self.expires_at)
            ):
                self.error = "Recorded lease expired before renewal was confirmed"
                service._write(self.heartbeat_dir, {"version": 1, "status": "failed", "reason": self.error})
            if self.error is not None:
                raise delivery.DeliveryError("Lease renewal failed; reconcile the recorded claim")

    def renew(self) -> float:
        state = self.state
        worktree = Path(state["worktree"]).resolve(strict=True)
        delivery._full_claim_readback(state, self.runner, worktree)
        issue = publication._read_issue(self.runner, worktree, delivery.REPOSITORY, state["issue"])
        publication._require_publishable_issue(issue, state["issue"])
        if issue["body_sha256"] != state["issue_body_sha256"]:
            raise delivery.DeliveryError("Issue contract changed during lease renewal")
        updated = agent_worktree.heartbeat_worktree(
            Path(state["root"]), worktree=worktree, owner=state["session_id"],
        )
        expiry_time = float(updated["expires_at"])
        receipt = state["pickup_receipt"]
        match = re.search(
            r" coordination_mode=dispatcher-backed fallback_reason=none task_id=(\S+) "
            r"lease_id=(\S+) holder=(.+?) evidence=verified-dispatcher-lease$", receipt,
        )
        dispatcher_expiry = None
        if match:
            task_id, lease_id, holder = match.groups()
            if holder != state["agent_id"]:
                raise delivery.DeliveryError("Dispatcher lease holder changed")
            renewed = leases.heartbeat(_make_store(), task_id, holder)
            if renewed.lease_id != lease_id or renewed.holder != holder or renewed.resource != f"issue:{state['issue']}":
                raise delivery.DeliveryError("Dispatcher renewal identity changed")
            dispatcher_expiry = renewed.expires_at
            expires = datetime.fromisoformat(dispatcher_expiry.replace("Z", "+00:00"))
            expiry_time = min(expiry_time, expires.timestamp())
        remaining = expiry_time - time.time()
        if remaining <= 0:
            raise delivery.DeliveryError("Renewed claim has expired")
        interval = min(MAX_HEARTBEAT_INTERVAL, remaining / 3)
        with self.lock:
            if self.error is not None:
                raise delivery.DeliveryError("Lease renewal was no longer confirmed in time")
            self.valid_until = time.monotonic() + remaining
            self.expires_at = expiry_time
            service._write(self.heartbeat_dir, {"version": 1, "status": "healthy",
                "worktree_expires_at": updated["expires_at"], "dispatcher_expires_at": dispatcher_expiry,
                "next_in_seconds": interval})
        return interval

    def start(self) -> None:
        with self.lock:
            interval = self.renew()

        def maintain() -> None:
            nonlocal interval
            while not self.stop_event.wait(interval):
                try:
                    interval = self.renew()
                except Exception as exc:
                    with self.lock:
                        self.error = str(exc) or type(exc).__name__
                        service._write(self.heartbeat_dir, {"version": 1, "status": "failed",
                                                            "reason": self.error})
                    return

        self.thread = threading.Thread(target=maintain, name="openhands-lease-heartbeat", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=130)
            if self.thread.is_alive():
                raise delivery.DeliveryError("Lease heartbeat did not stop; reconcile the run")
        with self.lock:
            self.check()


class _GuardedExecutor:
    def __init__(self, keeper: _LeaseKeeper) -> None:
        self.keeper = keeper
        self.delegate = publication.SubprocessExecutor()

    def run(self, argv: Any, *, cwd: Path, input_text: str | None = None) -> publication.CommandResult:
        with self.keeper.lock:
            self.keeper.check()
        result = self.delegate.run(argv, cwd=cwd, input_text=input_text)
        # A failure during an already-started effect leaves its outcome for the
        # existing publication reconciliation; do not continue to another effect.
        with self.keeper.lock:
            self.keeper.check()
        return result


def _handoff(state: dict[str, Any], worktree: Path, runner: delivery.DraftOnlyExecutor) -> dict[str, Any]:
    parent = worktree / ".codex-tmp"
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or parent.resolve(strict=True).parent != worktree:
        raise delivery.DeliveryError("Handoff directory is not a workspace directory")
    raw = factory._private_read(worktree / HANDOFF)
    if len(raw) > 65536:
        raise delivery.DeliveryError("Handoff exceeds the size limit")
    handoff = json.loads(raw)
    if (not isinstance(handoff, dict) or set(handoff) != {"version", "issue", "title", "paths", "risk_surfaces", "body"}
            or handoff.get("version") != 1 or handoff.get("issue") != state["issue"]
            or not isinstance(handoff.get("title"), str) or not handoff["title"].strip()
            or len(handoff["title"]) > 200):
        raise delivery.DeliveryError("Worker handoff is malformed or names another issue")
    paths, risks, body = handoff.get("paths"), handoff.get("risk_surfaces"), handoff.get("body")
    if (not isinstance(paths, list) or not paths or len(paths) > 256
            or any(not isinstance(p, str) or not p for p in paths)
            or not isinstance(risks, list) or any(not isinstance(r, str) for r in risks)
            or len(set(risks)) != len(risks) or set(risks) - publication.RISK_SURFACES
            or not isinstance(body, dict) or set(body) != BODY_FIELDS):
        raise delivery.DeliveryError("Worker handoff paths, risks or body are invalid")
    normalized = list(publication._normalize_paths(paths, worktree))
    if any(path == ".codex-tmp" or path.startswith(".codex-tmp/") for path in normalized):
        raise delivery.DeliveryError("The local handoff cannot be committed")
    ignored = runner.run(["git", "check-ignore", "-q", "--", HANDOFF], cwd=worktree)
    tracked = runner.run(["git", "ls-files", "--error-unmatch", "--", HANDOFF], cwd=worktree)
    if ignored.returncode != 0 or tracked.returncode != 1:
        raise delivery.DeliveryError("The handoff must be ignored and untracked")
    body = {**body, "lane": "implementation", "final_review_rounds": 1,
            "issue_number": state["issue"], "pickup_receipt": state["pickup_receipt"]}
    generate_pr_body_from_mapping(body)
    return {"title": handoff["title"], "body": body, "risks": risks, "paths": normalized}


def _commit(directory: Path, state: dict[str, Any], watcher: dict[str, Any], watch_dir: Path,
            runner: delivery.DraftOnlyExecutor | None = None) -> dict[str, Any]:
    worktree = Path(state["worktree"]).resolve(strict=True)
    runner = runner or delivery.DraftOnlyExecutor()
    top = publication._git_text(runner, worktree, "rev-parse", "--show-toplevel")
    branch = publication._git_text(runner, worktree, "branch", "--show-current")
    head = publication._git_text(runner, worktree, "rev-parse", "HEAD")
    if Path(top).resolve() != worktree or branch != state["branch"] or head != state["base_commit"]:
        raise delivery.DeliveryError("Worker branch or base changed before host commit")
    handoff = _handoff(state, worktree, runner)
    unstaged, staged, untracked = publication._changed_path_sets(runner, worktree)
    if staged or not (unstaged | untracked) or (unstaged | untracked) != set(handoff["paths"]):
        raise delivery.DeliveryError("Worker handoff does not match the unstaged change set")
    publication._checked(runner, [str(factory.FACTORY_ROOT / "scripts/agent_workspace_preflight.sh"),
                         "--cwd", str(worktree), "--expected-branch", state["branch"],
                         "--expected-worktree", str(worktree), "--base-branch", "main", "--allow-dirty"], worktree)
    delivery._full_claim_readback(state, runner, worktree)
    delivery._finished_run(directory)
    # Never run configured clean filters chosen by a worker-controlled attributes file.
    attrs = publication._checked(runner, ["git", "--literal-pathspecs", "check-attr", "-z", "filter", "--",
                                        *handoff["paths"]], worktree).stdout.split("\0")
    if len(attrs) != 3 * len(handoff["paths"]) + 1 or any(attrs[i] not in {"unspecified", "unset"}
                                                            for i in range(2, len(attrs) - 1, 3)):
        raise delivery.DeliveryError("Configured Git filters require manual inspection")
    watcher.update(status="running", phase="staging", handoff=handoff, base=head)
    service._write(watch_dir, watcher)
    publication._checked(runner, ["git", "--literal-pathspecs", "add", "-A", "--", *handoff["paths"]], worktree)
    unstaged, staged, untracked = publication._changed_path_sets(runner, worktree)
    if unstaged or untracked or staged != set(handoff["paths"]):
        raise delivery.DeliveryError("Staged changes changed during preparation; inspect the index")
    delivery._finished_run(directory)
    publication._checked(runner, [str(factory.FACTORY_ROOT / "scripts/agent_workspace_preflight.sh"),
                         "--cwd", str(worktree), "--expected-branch", state["branch"],
                         "--expected-worktree", str(worktree), "--base-branch", "main", "--allow-dirty"], worktree)
    delivery._full_claim_readback(state, runner, worktree)
    watcher["phase"] = "committing"
    service._write(watch_dir, watcher)
    publication._checked(runner, ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                                 "commit", "-m", f"Implement issue #{state['issue']}",
                                 "-m", f"Refs #{state['issue']}"], worktree)
    candidate = factory._candidate_head(worktree, state["branch"])
    watcher.update(phase="publishing", head=candidate)
    service._write(watch_dir, watcher)
    return handoff


def run(install: Path, directory: Path, issue: int, repo: Path, worktree_root: Path) -> None:
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(watch_dir / "watch.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        watcher = service._read(watch_dir) or {"version": 1, "status": "running", "phase": "watching"}
        if watcher.get("status") in {"finished", "failed"}:
            return
        if watcher.get("phase") in {"staging", "committing"}:
            watcher.update(status="pending", reason="Commit outcome is ambiguous; inspect the index and branch")
            service._write(watch_dir, watcher)
            return
        keeper = None
        try:
            with service._locked(directory):
                state = delivery._state(directory)
                if (state.get("auto_finish") is not True or state.get("issue") != issue
                        or state.get("root") != str(repo) or Path(state["worktree"]).parent != worktree_root
                        or state.get("phase") != "active"):
                    raise delivery.DeliveryError("Watcher does not match an active authorized delivery")
            keeper = _LeaseKeeper(state, watch_dir)
            try:
                keeper.start()
            except Exception as exc:
                keeper.error = str(exc) or type(exc).__name__
                service._write(keeper.heartbeat_dir, {"version": 1, "status": "failed", "reason": keeper.error})
                raise delivery.DeliveryError("Lease renewal failed; reconcile the recorded claim") from exc
            watcher["status"] = "running"
            service._write(watch_dir, watcher)
            guarded = _GuardedExecutor(keeper)
            read_failures = 0
            while True:
                keeper.check()
                with service._locked(directory):
                    state = delivery._state(directory)
                    if (state.get("auto_finish") is not True or state.get("issue") != issue
                            or state.get("root") != str(repo) or Path(state["worktree"]).parent != worktree_root):
                        raise delivery.DeliveryError("Watcher does not match an authorized delivery")
                    if any(state.get(key) != keeper.state.get(key) for key in (
                        "repository", "root", "worktree", "branch", "base_commit", "session_id", "agent_id",
                        "pickup_receipt", "conversation_id", "port", "issue_body_sha256",
                    )):
                        raise delivery.DeliveryError("Recorded delivery identity changed during watching")
                    if state.get("phase") != "active":
                        raise delivery.DeliveryError("Run is interrupted or its state requires inspection")
                    try:
                        observed = delivery._conversation(directory, state)
                    except delivery.DeliveryError:
                        read_failures += 1
                        if read_failures >= 3:
                            watcher.update(status="pending", reason="Conversation readback unavailable after three attempts")
                            service._write(watch_dir, watcher)
                            return
                        time.sleep(POLL_SECONDS)
                        continue
                    read_failures = 0
                    if observed.get("execution_status") == "finished":
                        delivery._finished_run(directory)
                        break
                    if observed.get("execution_status") not in {"idle", "running"}:
                        raise delivery.DeliveryError("Worker is not running or finished; inspect its state")
                    if watcher.get("phase") == "publishing":
                        raise delivery.DeliveryError("Recorded publication is not associated with a finished worker")
                watcher.update(status="running", phase="watching")
                service._write(watch_dir, watcher)
                time.sleep(POLL_SECONDS)
            keeper.check()
            if watcher.get("phase") == "publishing":
                handoff = watcher.get("handoff")
                if (not isinstance(handoff, dict) or factory._candidate_head(Path(state["worktree"]), state["branch"])
                        != watcher.get("head")):
                    raise delivery.DeliveryError("Recorded publication candidate changed")
            else:
                handoff = _commit(directory, state, watcher, watch_dir, delivery.DraftOnlyExecutor(guarded))
            result = factory._finish(install, directory, issue, repo, worktree_root,
                                     handoff["title"], handoff["body"], handoff["risks"], None,
                                     executor=guarded, guard=keeper.check)
            keeper.check()
            watcher.update(status="finished", phase="published", pr_number=result["pr_number"],
                           head=result["commit_sha"], checks=result["checks"])
        except factory.FinishEvidenceError as exc:
            watcher.update(status="failed", reason=str(exc))
        except (delivery.DeliveryError, service.ServiceError, publication.PublicationRefusal,
                publication.PublicationCommandError, OSError, ValueError, KeyError, TypeError) as exc:
            watcher.update(status="pending" if (keeper is not None and keeper.error is not None)
                           or watcher.get("phase") in {"staging", "committing", "publishing"}
                           else "failed", reason=str(exc))
        finally:
            if keeper is not None:
                try:
                    keeper.close()
                except delivery.DeliveryError as exc:
                    watcher.update(status="pending", reason=str(exc))
        service._write(watch_dir, watcher)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit("Watcher requires the recorded install, state, issue, repository and worktree roots")
    run(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5]))
