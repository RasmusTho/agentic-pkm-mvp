"""Trusted lifecycle controller for a persistent epic workspace (#6615 / #6616).

The controller runs on the worker VM from a pinned release directory that is not
mounted into any worker. It owns one persistent directory per epic:

    <root>/epic-<N>/
        source.git/                 controller-owned bare mirror (never mounted)
        workers/<worker>/checkout   one separate writable clone per worker
        workers/<worker>/home       the worker's native-CLI home (session history)
        integration/checkout        combined-candidate checkout
        run-state/epic-<N>.json     existing ``epic_run_state`` record (delivery ledger)

Containers are replaceable; checkouts and run-state are unique work and survive
container removal. Worker containers receive exactly their own checkout and home,
explicit CPU/memory/process budgets, no capabilities, no Docker socket and no
publication credentials. A missing or failing engine is refused; there is no
host-execution fallback anywhere in this module.

Stdlib only so the pinned controller runs on the VM's system Python.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Concatenate, Iterator, Mapping, ParamSpec, Sequence, TypeVar

from app.builderops import epic_run_state

SCHEMA = "epic_workspace.v1"
CONTAINER_PREFIX = "epicws"
LABEL_EPIC = "epic-workspace.epic"
LABEL_WORKER = "epic-workspace.worker"
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_HOME = "/home/worker"
WORKER_UID_GID = "1000:1000"
DEFAULT_IMAGE = "epic-worker:baseline"
DEFAULT_NETWORK = "epicws"  # owned user-defined bridge; host/container modes are refused
# Upstream OpenHands agent-server (same release as the #6600 pin). It bundles the ACP providers
# claude-agent-acp 0.63.0 (``claude-code``) and codex-acp 2.2.2 (``codex``).
OPENHANDS_IMAGE = (
    "ghcr.io/openhands/agent-server:1.60.1-python"
    "@sha256:b43ee580c2177280c81cb807c9a559d7a14aa13b48dba5040132a6a637bb6d55"
)
OPENHANDS_CONTAINER_PORT = 8000
OPENHANDS_PORT_RANGE = range(18700, 18800)
CODEX_HOME_TARGET = "/run/codex-home"
# Engine/model policy for epic workers (#6615 owner revisions 2026-11-12/12b).
ENGINE_DEFAULT_MODELS = {"claude-code": "claude-sonnet-5-5", "codex": "gpt-6.1-terra"}
_ENGINE_MODEL = {"claude-code": re.compile(r"^claude-[a-z0-9.-]{1,60}$"), "codex": re.compile(r"^gpt-6\.1-terra$")}

_WORKER_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_MEMORY = re.compile(r"^[1-9][0-9]*[mg]$")
_CPUS = re.compile(r"^(0\.[1-9][0-9]?|[1-9][0-9]?(\.[0-9]{1,2})?)$")
# Docker image reference: never starts with "-", no whitespace or option syntax.
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,199}(:[A-Za-z0-9._-]{1,128})?(@sha256:[0-9a-f]{64})?$")
_NETWORK = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
# Paths embedded in --mount CSV: no comma, quote, equals, whitespace or control characters.
_MOUNT_PATH = re.compile(r"^/[A-Za-z0-9._/@+-]*$")
EXTRA_MOUNT_PREFIX = "/mnt/"
INSPECT_TARGET = "/inspect"
SCRATCH_TARGET = "/scratch"
CHECKPOINT_REF_PREFIX = "refs/checkpoints/"
STAGED_REF_PREFIX = "refs/checkpoint-staged/"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GIT_TIMEOUT = 120.0
GIT_WRITE_TIMEOUT = 900.0
ENGINE_TIMEOUT = 30.0
MAX_PUBLISHED_TIPS = 5000
MAX_DETAIL_QUERIES = 64
MAX_RETAINED_REFS = 5000
MAX_GIT_METADATA_ENTRIES = 200_000
MAX_REFLOG_BYTES = 32 * 1024 * 1024
PUBLICATION_KINDS = ("branch_push", "pr_create")
# Older candidates treated an empty readback as proof of absence. Such records
# do not prove a request has stopped and must be reconciled again.
_OP_UNRESOLVED = ("intended", "quarantined", "absent_confirmed")
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_OID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_CKPT_REF = re.compile(r"^refs/checkpoints/ckpt-([0-9]{4,})$")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
_INSPECT_NAME = re.compile(r"^epicws-git-[0-9a-f]{12}$")
_REFLOG_LINE = re.compile(
    rb"^([0-9a-f]{40}|[0-9a-f]{64}) ([0-9a-f]{40}|[0-9a-f]{64}) "
    # Git's generated ident is a nonempty name, <email> (which may be empty),
    # nonzero timestamp, and numeric timezone. Git silently skips a malformed
    # identity or zero timestamp during reflog traversal.
    rb"[^ <>\x00\r\n\t](?:[^<>\x00\r\n\t]*[^ <>\x00\r\n\t])? "
    rb"<[^<>\x00\r\n\t]*> 0*[1-9][0-9]* [+-][0-9]{4}(?:\t[^\x00\r\n]*)?$"
)
LAUNCH_PROTOCOL = "create-start-v1"

Runner = Callable[..., subprocess.CompletedProcess]
_P = ParamSpec("_P")
_R = TypeVar("_R")


class EpicWorkspaceError(RuntimeError):
    """Base error; the operation it names did not take effect."""


class EngineUnavailable(EpicWorkspaceError):
    """The container engine cannot be used. Never fall back to the host."""


class LaunchRefused(EpicWorkspaceError):
    """A launch request violates the workspace or resource boundary."""


class UniqueWorkPresent(EpicWorkspaceError):
    """Retirement refused: the checkout may hold work that exists nowhere else."""


class TakeoverRefused(EpicWorkspaceError):
    """A successor may not write yet; the previous execution or its work is not reconciled."""


@dataclass(frozen=True)
class Budget:
    """Per-worker resource budget enforced by the engine (cgroup v2)."""

    cpus: str = "1.0"
    memory: str = "1g"
    pids: int = 256

    def validated(self) -> "Budget":
        if not _CPUS.match(self.cpus):
            raise LaunchRefused(f"invalid cpu budget {self.cpus!r}")
        if not _MEMORY.match(self.memory):
            raise LaunchRefused(f"invalid memory budget {self.memory!r}")
        if not (16 <= int(self.pids) <= 4096):
            raise LaunchRefused(f"invalid pids budget {self.pids!r}")
        return self


@dataclass(frozen=True)
class Layout:
    root: Path
    epic: int

    @property
    def epic_dir(self) -> Path:
        return self.root / f"epic-{self.epic}"

    @property
    def source(self) -> Path:
        return self.epic_dir / "source.git"

    @property
    def workers(self) -> Path:
        return self.epic_dir / "workers"

    @property
    def integration(self) -> Path:
        return self.epic_dir / "integration" / "checkout"

    @property
    def run_state_dir(self) -> Path:
        return self.epic_dir / "run-state"

    @property
    def run_id(self) -> str:
        return f"epic-{self.epic}"

    def worker_dir(self, worker: str) -> Path:
        return self.workers / validate_worker_id(worker)

    def checkout(self, worker: str) -> Path:
        return self.worker_dir(worker) / "checkout"

    def home(self, worker: str) -> Path:
        return self.worker_dir(worker) / "home"

    def container_name(self, worker: str) -> str:
        return f"{CONTAINER_PREFIX}-{self.epic}-{validate_worker_id(worker)}"


def validate_worker_id(worker: str) -> str:
    if not isinstance(worker, str) or not _WORKER_ID.match(worker):
        raise LaunchRefused(f"invalid worker id {worker!r}")
    return worker


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(
    runner: Runner, argv: Sequence[str], *, check: bool = True, cwd: Path | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}
    try:
        result = runner(list(argv), capture_output=True, text=True, cwd=str(cwd) if cwd else None, check=False, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise EpicWorkspaceError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} timed out; outcome unknown") from exc
    if check and result.returncode != 0:
        raise EpicWorkspaceError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed: {(result.stderr or '').strip()[:400]}")
    return result


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(base.resolve(strict=False))
        return True
    except ValueError:
        return False


@contextmanager
def _worker_lifecycle_lock(layout: Layout, worker: str) -> Iterator[None]:
    """Fence overlapping controller effects for this worker, including across processes."""

    directory = _controller_dir(layout, "lifecycle-locks")
    path = directory / f"{validate_worker_id(worker)}.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise EpicWorkspaceError("cannot safely open worker lifecycle lock") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise EpicWorkspaceError("worker lifecycle lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LaunchRefused("another lifecycle operation is in progress for this worker") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _serialized_worker(
    func: Callable[Concatenate[Layout, str, _P], _R],
) -> Callable[Concatenate[Layout, str, _P], _R]:
    @wraps(func)
    def wrapped(layout: Layout, worker: str, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _worker_lifecycle_lock(layout, worker):
            return func(layout, worker, *args, **kwargs)

    return wrapped


def _serialized_openhands_start(
    func: Callable[Concatenate[Layout, str, _P], _R],
) -> Callable[Concatenate[Layout, str, _P], _R]:
    """Fence port selection and credential-home admission across workers of this root."""
    @wraps(func)
    def wrapped(layout: Layout, worker: str, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            fd = os.open(layout.root / ".openhands-start.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except OSError as exc:
            raise LaunchRefused("cannot open OpenHands start lock") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise LaunchRefused("OpenHands start lock is not a regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LaunchRefused("another OpenHands start is selecting a port; retry") from exc
            try:
                return func(layout, worker, *args, **kwargs)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    return wrapped


# --------------------------------------------------------------------------- state


def _load_state(layout: Layout) -> dict[str, Any]:
    return epic_run_state.load_epic_run_state(layout.run_id, root=layout.run_state_dir)


def _record_worker(layout: Layout, issue: int, **fields: Any) -> dict[str, Any]:
    key = str(int(issue))

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        mapping = dict(state.get("issue_mappings", {}).get(key, {}))
        mapping.update(fields)
        mapping["updated_at"] = _now()
        state.setdefault("issue_mappings", {})[key] = mapping
        return state

    return epic_run_state.update_epic_run_state(
        layout.run_id,
        root=layout.run_state_dir,
        updater=updater,
        expected_epic_issue_number=layout.epic,
    )


def _reserve_worker(layout: Layout, issue: int, worker: str, **fields: Any) -> dict[str, Any]:
    """Bind issue<->worker under the run-state lock; refuse any reassignment."""

    key = str(int(issue))

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        mappings = state.setdefault("issue_mappings", {})
        for other_key, other in mappings.items():
            if not isinstance(other, Mapping):
                continue
            if other_key == key and other.get("worker") not in (None, worker):
                raise LaunchRefused(f"issue #{key} already belongs to worker {other.get('worker')!r}")
            if other_key != key and other.get("worker") == worker:
                raise LaunchRefused(f"worker {worker!r} already owns issue #{other_key}")
        mapping = dict(mappings.get(key, {}))
        mapping.update(fields, worker=worker, updated_at=_now())
        mappings[key] = mapping
        return state

    return epic_run_state.update_epic_run_state(
        layout.run_id,
        root=layout.run_state_dir,
        updater=updater,
        expected_epic_issue_number=layout.epic,
    )


def _takeover_of(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    value = mapping.get("takeover")
    return value if isinstance(value, Mapping) else {}


def _assert_no_pending_takeover(mapping: Mapping[str, Any]) -> None:
    if mapping.get("checkpoint_inspection_unknown"):
        raise TakeoverRefused("checkpoint inspection cleanup is unknown; trusted reconciliation is required")
    if _takeover_of(mapping).get("status") == "required":
        raise TakeoverRefused("takeover required: reconcile the predecessor's work and publication before any successor writes")


def _begin_start(
    layout: Layout, issue: int, worker: str, *, preflight: Mapping[str, Any] | None,
    runner: Runner, inspection_image: str, **fields: Any,
) -> None:
    """Gate and record a successor start in one locked update.

    The takeover gate, the "no earlier execution left unreconciled" check and the ``starting``
    record are decided under the run-state lock, so a concurrent stop or takeover cannot slip in
    between the check and the launch. An authorized continuation is consumed here, exactly once,
    by whichever start path launches the successor.
    """

    key = str(int(issue))

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        mapping = dict(state.get("issue_mappings", {}).get(key, {}))
        if mapping.get("worker") != worker:
            raise LaunchRefused(f"issue #{key} does not belong to worker {worker!r}")
        _assert_no_pending_takeover(mapping)
        recorded = mapping.get("state")
        if recorded == "retired":
            raise LaunchRefused(f"worker {worker!r} is retired")
        if recorded in ("starting", "running"):
            raise LaunchRefused(
                f"worker {worker!r} is recorded as {recorded!r} without a verified stop; "
                "run takeover (or worker-stop) so the earlier execution is proven gone and reconciled first"
            )
        pending = _takeover_of(mapping)
        if recorded == "stopped_verified" and mapping.get("started_at") and pending.get("status") != "authorized":
            raise TakeoverRefused("takeover required before starting a successor")
        if pending.get("status") != "authorized" and any(
            op.get("status") in _OP_UNRESOLVED
            for op in mapping.get("publication_ops", []) if isinstance(op, Mapping)
        ):
            raise TakeoverRefused("takeover required: publication has an unresolved outcome")
        if preflight is None or mapping.get("branch") != preflight.get("branch"):
            raise TakeoverRefused("checkout start preflight is missing or stale; run takeover")
        if pending.get("status") == "authorized":
            if (pending.get("generation") != preflight.get("generation")
                    or mapping.get("execution_identity") != preflight.get("identity")):
                raise TakeoverRefused("checkout authorization changed after preflight; run takeover")
            _identity, checkpoint = _authorization_record(mapping)
            if checkpoint is not None and not _checkpoint_present(layout.checkout(worker), _checkpoint_repo(layout, worker), checkpoint, runner, inspection_image):
                raise TakeoverRefused("authorized checkpoint changed after preflight; run takeover")
        elif (preflight.get("identity") is not None
              or mapping.get("execution_branch", mapping.get("branch")) != preflight.get("execution_branch")):
            raise TakeoverRefused("checkout execution branch changed after preflight; run takeover")
        _assert_engine(runner)
        if _container_state(layout, worker, runner) is not None:
            raise TakeoverRefused("worker container appeared after preflight; run takeover")
        latest, _ = _inspect(layout, worker, runner=runner, image=inspection_image)
        if _checkout_identity(latest) != preflight.get("checked_identity"):
            raise TakeoverRefused("checkout changed after start preflight; run takeover")
        if pending.get("status") == "authorized":
            mapping["takeover"] = {**pending, "status": "consumed", "consumed_at": _now(), "consumed_by": fields.get("runtime")}
        mapping.update(fields, state="starting", container_id=None, launch_protocol=LAUNCH_PROTOCOL, updated_at=_now())
        state["issue_mappings"][key] = mapping
        return state

    try:
        epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic)
    except TakeoverRefused:
        if preflight is not None and preflight.get("identity") is not None:
            _fence_authorization(layout, worker, preflight.get("generation"))
        raise


def _launch(layout: Layout, issue: int, worker: str, argv: Sequence[str], runner: Runner) -> str:
    """Create without running; persist the immutable ID before issuing an ID-bound start."""

    try:
        created = runner(list(argv), capture_output=True, text=True, check=False, timeout=300.0)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EpicWorkspaceError("worker create outcome unknown; run worker-stop or takeover to settle") from exc
    cid = (created.stdout or "").strip()
    if created.returncode != 0 or not _CONTAINER_ID.fullmatch(cid):
        # A create never starts a process. A late created container may occupy the name,
        # but cannot write; worker-stop can remove it after verifying its scope.
        raise EpicWorkspaceError("worker create failed or returned no ID; run worker-stop or takeover to settle")
    _record_worker(layout, issue, container_id=cid)
    try:
        started = runner(["docker", "start", cid], capture_output=True, text=True, check=False, timeout=300.0)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EpicWorkspaceError("worker start outcome unknown; run worker-stop or takeover to settle") from exc
    if started.returncode != 0:
        raise EpicWorkspaceError("worker start failed; run worker-stop or takeover to settle")
    return cid


def _issue_for_worker(state: Mapping[str, Any], worker: str) -> int:
    for key, mapping in state.get("issue_mappings", {}).items():
        if isinstance(mapping, Mapping) and mapping.get("worker") == worker:
            return int(key)
    raise EpicWorkspaceError(f"worker {worker!r} is not recorded in run-state")


# --------------------------------------------------------------------------- lifecycle


def init_workspace(root: Path, epic: int, repo_url: str, *, runner: Runner = subprocess.run) -> Layout:
    """Create (idempotently) the persistent epic directory, mirror and run-state."""

    layout = Layout(Path(root).expanduser().resolve(), int(epic))
    layout.workers.mkdir(parents=True, exist_ok=True)
    layout.run_state_dir.mkdir(parents=True, exist_ok=True)
    if not layout.source.exists():
        _run(runner, ["git", "clone", "--bare", "--quiet", repo_url, str(layout.source)])
    else:
        _run(runner, ["git", "-C", str(layout.source), "fetch", "--quiet", "--prune", "origin", "+refs/heads/*:refs/heads/*"])
    epic_run_state.create_epic_run_state(
        layout.epic,
        layout.run_id,
        root=layout.run_state_dir,
        compact_receipts=[{"schema": SCHEMA, "event": "workspace_initialized", "source": repo_url, "at": _now()}],
    )
    return layout


@_serialized_worker
def create_worker(
    layout: Layout,
    worker: str,
    *,
    issue: int,
    branch: str,
    base: str = "main",
    next_action: str,
    runner: Runner = subprocess.run,
) -> Path:
    """Give one worker its own clone; nothing is shared writable with other workers."""

    if not _BRANCH.match(branch) or ".." in branch:
        raise LaunchRefused(f"invalid branch {branch!r}")
    checkout = layout.checkout(worker)
    recorded = _load_state(layout).get("issue_mappings", {}).get(str(int(issue)), {})
    if recorded.get("worker") not in (None, worker):
        raise LaunchRefused(f"issue #{int(issue)} already belongs to worker {recorded.get('worker')!r}")
    if recorded.get("state") == "retired":
        raise LaunchRefused(f"worker for issue #{int(issue)} is retired")
    if not checkout.exists() and recorded.get("state") not in (None, "creating"):
        raise LaunchRefused("recorded worker checkout is missing; refusing to replace its state")
    if checkout.exists():
        # A re-run must not record a branch the checkout is not on (KD-FE5EDF575D1E).
        actual = checkout_branch(checkout, runner=runner)
        pending = _takeover_of(recorded)
        if pending.get("status") == "authorized":
            try:
                _check_authorized_checkout(layout, worker, recorded, runner=runner, image=DEFAULT_IMAGE)
            except EpicWorkspaceError:
                _fence_authorization(layout, worker, pending.get("generation"))
                raise
        detached = actual is None and pending.get("status") == "authorized" and recorded.get("execution_branch", recorded.get("branch")) is None
        if actual != branch and not (detached and branch == recorded.get("branch")):
            raise LaunchRefused(f"checkout of worker {worker!r} is on {actual!r}, not the requested {branch!r}; refusing to record it")
        execution_branch = recorded.get("execution_branch", recorded.get("branch"))
        unfinished_create = ("execution_branch" not in recorded and recorded.get("branch") is None
                             and recorded.get("state") in (None, "creating"))
        if not detached and execution_branch != branch and not unfinished_create:
            raise LaunchRefused(f"issue #{int(issue)} is recorded on branch {execution_branch!r}, not {branch!r}")
        # A reconciled execution branch never rewrites the parent's publication branch.
        _reserve_worker(layout, issue, worker, branch=recorded.get("branch") or actual, checkout=str(checkout), next_action=next_action,
                        **({"state": "created"} if recorded.get("state") in (None, "creating") else {}))
        layout.home(worker).mkdir(parents=True, exist_ok=True)
        return checkout
    _reserve_worker(layout, issue, worker, state="creating")
    checkout.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, ["git", "clone", "--quiet", "--no-hardlinks", str(layout.source), str(checkout)])
    exists = _run(runner, ["git", "-C", str(checkout), "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], check=False)
    start = f"origin/{branch}" if exists.returncode == 0 else f"origin/{base}"
    _run(runner, ["git", "-C", str(checkout), "checkout", "--quiet", "-B", branch, start])
    actual = checkout_branch(checkout, runner=runner)
    if actual != branch:
        raise EpicWorkspaceError(f"new checkout is on {actual!r}, not {branch!r}")
    layout.home(worker).mkdir(parents=True, exist_ok=True)
    _reserve_worker(layout, issue, worker, branch=actual, checkout=str(checkout), state="created", next_action=next_action)
    return checkout


def _assert_engine(runner: Runner) -> str:
    try:
        result = runner(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
    except OSError as exc:
        raise EngineUnavailable("docker CLI unavailable; refusing (no host fallback)") from exc
    except subprocess.TimeoutExpired as exc:
        raise EngineUnavailable("container engine did not answer; refusing (no host fallback)") from exc
    if result.returncode != 0 or not (result.stdout or "").strip():
        raise EngineUnavailable("container engine unavailable; refusing (no host fallback)")
    return result.stdout.strip()


def _validate_env_file(env_file: Path | None, layout: Layout) -> Path | None:
    if env_file is None:
        return None
    path = Path(env_file).expanduser()
    if not path.is_file() or path.is_symlink():
        raise LaunchRefused("credential env file missing or not a regular file")
    if _is_within(path, layout.root):
        raise LaunchRefused("credential env file must live outside the workspace root")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise LaunchRefused("credential env file must not be group/world accessible")
    return path


_FORBIDDEN_SOURCES = ("/var/run/docker.sock", "/run/docker.sock", "/run/containerd", "/var/lib/docker", "/proc", "/sys", "/etc", "/root")


def validate_mounts(layout: Layout, worker: str, mounts: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Allow only this worker's own directories; refuse everything else."""

    own = layout.worker_dir(worker).resolve(strict=False)
    resolved: list[tuple[str, str]] = []
    for source, target in mounts:
        raw = Path(source).expanduser()
        if raw.is_symlink():
            raise LaunchRefused(f"symlink mount source refused: {raw}")
        text = str(raw.resolve(strict=False))
        if not _MOUNT_PATH.match(text) or not _MOUNT_PATH.match(target):
            raise LaunchRefused("mount source/target contains characters outside the safe path set")
        if any(text == f or text.startswith(f + "/") for f in _FORBIDDEN_SOURCES):
            raise LaunchRefused(f"forbidden mount source {text}")
        if not _is_within(Path(text), own):
            raise LaunchRefused(f"mount outside worker {worker!r} workspace: {text}")
        if os.path.normpath(target) != target:
            raise LaunchRefused(f"mount target must be a normalized absolute path: {target}")
        resolved.append((text, target))
    return resolved


def build_launch_argv(
    layout: Layout,
    worker: str,
    *,
    image: str,
    command: Sequence[str],
    budget: Budget,
    env_file: Path | None = None,
    extra_mounts: Sequence[tuple[str, str]] = (),
    network: str = DEFAULT_NETWORK,
    extra_env_files: Sequence[Path] = (),
    env: Mapping[str, str] | None = None,
    publish_port: int | None = None,
    credential_mounts: Sequence[tuple[str, str]] = (),
    tmpfs_exec: bool = False,
) -> list[str]:
    budget = budget.validated()
    checkout = layout.checkout(worker)
    home = layout.home(worker)
    if not checkout.is_dir():
        raise LaunchRefused(f"worker {worker!r} has no checkout; create it first")
    for _source, target in extra_mounts:
        if not str(target).startswith(EXTRA_MOUNT_PREFIX):
            raise LaunchRefused(f"extra mount target must be under {EXTRA_MOUNT_PREFIX}: {target}")
    mounts = validate_mounts(
        layout, worker, [(str(checkout), CONTAINER_WORKSPACE), (str(home), CONTAINER_HOME), *extra_mounts]
    )
    if not _IMAGE.match(image):
        raise LaunchRefused(f"invalid image reference {image!r}")
    if not _NETWORK.match(network) or network == "host":
        raise LaunchRefused(f"network mode {network!r} refused")
    argv = [
        "docker", "create",
        "--name", layout.container_name(worker),
        "--label", f"{LABEL_EPIC}={layout.epic}",
        "--label", f"{LABEL_WORKER}={worker}",
        "--cpus", budget.cpus,
        "--memory", budget.memory,
        "--memory-swap", budget.memory,
        "--pids-limit", str(budget.pids),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--read-only",
        # The upstream agent-server is a self-extracting binary that unpacks into /tmp.
        "--tmpfs", "/tmp:rw,exec,nosuid,size=768m" if tmpfs_exec else "/tmp:rw,nosuid,size=512m",
        "--user", WORKER_UID_GID,
        "--network", network,
        "--env", f"HOME={CONTAINER_HOME}",
        "--workdir", CONTAINER_WORKSPACE,
    ]
    if publish_port is not None:
        if publish_port not in OPENHANDS_PORT_RANGE:
            raise LaunchRefused(f"published port {publish_port} outside the sandbox range")
        argv += ["--publish", f"127.0.0.1:{publish_port}:{OPENHANDS_CONTAINER_PORT}"]
    for key, value in (env or {}).items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) or "\n" in value or "\x00" in value:
            raise LaunchRefused(f"invalid environment entry {key!r}")
        argv += ["--env", f"{key}={value}"]
    for source, target in mounts:
        argv += ["--mount", f"type=bind,source={source},target={target}"]
    for source, target in credential_mounts:
        if not _MOUNT_PATH.match(source) or target != CODEX_HOME_TARGET:
            raise LaunchRefused("invalid credential mount")
        argv += ["--mount", f"type=bind,source={source},target={target}"]
    for path in ([env_file] if env_file is not None else []) + list(extra_env_files):
        argv += ["--env-file", str(path)]
    argv.append(image)
    argv += list(command)
    return argv


@_serialized_worker
def start_worker(
    layout: Layout,
    worker: str,
    *,
    command: Sequence[str],
    image: str = DEFAULT_IMAGE,
    budget: Budget = Budget(),
    env_file: Path | None = None,
    extra_mounts: Sequence[tuple[str, str]] = (),
    engine: str = "claude",
    model: str | None = None,
    network: str = DEFAULT_NETWORK,
    runner: Runner = subprocess.run,
) -> str:
    """Start one replaceable worker container. Refuses before any side effect."""

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    _assert_no_pending_takeover(state["issue_mappings"][str(issue)])
    env_path = _validate_env_file(env_file, layout)
    argv = build_launch_argv(layout, worker, image=image, command=command, budget=budget, env_file=env_path, extra_mounts=extra_mounts, network=network)
    _assert_engine(runner)
    existing = _container_state(layout, worker, runner)
    if existing is not None:
        raise LaunchRefused(f"container for worker {worker!r} already exists ({existing}); stop it before a successor starts")
    preflight = _preflight_start(layout, worker, state["issue_mappings"][str(issue)], runner=runner, image=DEFAULT_IMAGE)
    _begin_start(
        layout, issue, worker, preflight=preflight, runner=runner, inspection_image=DEFAULT_IMAGE,
        # Plain container execution is a recorded bootstrap/diagnostic exception, never the
        # normal delivery path (#6615 owner revision 2026-11-12b).
        runtime="native-exception",
        container=layout.container_name(worker),
        image=image,
        engine=engine,
        model=model,
        budget={"cpus": budget.cpus, "memory": budget.memory, "pids": budget.pids},
        network=network,
        started_at=_now(),
    )
    container_id = _launch(layout, issue, worker, argv, runner)
    _record_worker(layout, issue, state="running", container_id=container_id)
    return container_id


def _container_state(layout: Layout, worker: str, runner: Runner) -> str | None:
    try:
        result = runner(
            ["docker", "ps", "--all", "--filter", f"label={LABEL_EPIC}={layout.epic}", "--filter", f"label={LABEL_WORKER}={worker}", "--format", "{{.State}}"],
            capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EngineUnavailable("cannot read container state; treat worker as possibly running") from exc
    if result.returncode != 0:
        raise EngineUnavailable("cannot read container state; treat worker as possibly running")
    states = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return states[0] if states else None


def _named_container(name: str, labels: Mapping[str, str], runner: Runner) -> str | None:
    """Read one exact name and verify its labels before allowing removal."""
    try:
        found = runner(
            ["docker", "ps", "--all", "--no-trunc", "--filter", f"name=^/{name}$", "--format", "{{.ID}}"],
            capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT,
        )
        ids = (found.stdout or "").splitlines()
        if found.returncode != 0 or len(ids) > 1 or any(not _CONTAINER_ID.fullmatch(cid) for cid in ids):
            raise EngineUnavailable("cannot read exact container identity")
        if not ids:
            return None
        result = runner(["docker", "inspect", "--format", "{{json .Config.Labels}}", ids[0]],
                        capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
        if result.returncode != 0:
            raise EngineUnavailable("cannot read container scope")
        actual = json.loads(result.stdout or "null")
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in labels.items()):
            raise LaunchRefused(f"container named {name!r} does not have the expected scope; refusing removal")
        return ids[0]
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        raise EngineUnavailable("cannot read exact container identity and scope") from exc


def _id_present(cid: str, runner: Runner) -> bool:
    if not _CONTAINER_ID.fullmatch(cid):
        raise EpicWorkspaceError("invalid recorded container ID; refusing reconciliation")
    try:
        result = runner(["docker", "ps", "--all", "--no-trunc", "--filter", f"id={cid}", "--format", "{{.ID}}"],
                        capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EngineUnavailable("cannot verify container absence") from exc
    ids = (result.stdout or "").splitlines()
    if result.returncode != 0 or any(item != cid for item in ids) or len(ids) > 1:
        raise EngineUnavailable("cannot verify container absence")
    return bool(ids)


def _remove_owned(name: str, labels: Mapping[str, str], runner: Runner, *, cid: str | None = None) -> None:
    """Remove only a scope-checked ID; absence of that immutable ID is the stop proof."""
    found = _named_container(name, labels, runner)
    if cid is not None and found is not None and found != cid:
        raise LaunchRefused("container identity changed; refusing removal")
    target = cid or found
    if target is not None:
        if found == target:
            try:
                runner(["docker", "rm", "--force", target], capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if _id_present(target, runner):
            raise EngineUnavailable("container remains present; stop is unverified")
    # Check both exact name and scope after removal, including --rm disappearance.
    if _named_container(name, labels, runner) is not None:
        raise EngineUnavailable("container name remains present; stop is unverified")


def _settle_checkpoint_writer(layout: Layout, worker: str, runner: Runner) -> None:
    state = _load_state(layout)
    marker = state["issue_mappings"][str(_issue_for_worker(state, worker))].get("checkpoint_inspection_unknown")
    if not marker:
        return
    if not isinstance(marker, Mapping) or marker.get("protocol") != LAUNCH_PROTOCOL:
        raise TakeoverRefused("legacy checkpoint inspection has no ID-bound stop proof; trusted reconciliation required")
    name, cid = marker.get("name"), marker.get("container_id")
    if not isinstance(name, str) or not _INSPECT_NAME.fullmatch(name) or not isinstance(cid, str):
        raise TakeoverRefused("checkpoint inspection identity is malformed; preserving the hold")
    _remove_owned(name, {"epic-workspace.inspect": "1"}, runner, cid=cid)
    _mutate_mapping(layout, worker, lambda entry: entry.pop("checkpoint_inspection_unknown", None))


def _stop_worker(
    layout: Layout, worker: str, *, reason: str, runner: Runner, image: str, retain_identity: bool = True,
    expected_container_id: str | None = None,
) -> dict[str, Any]:
    """Remove the worker container, prove absence by engine readback, then preserve its work.

    Absence is recorded before any checkpoint so a failed checkpoint never hides that the
    container is gone; the checkout is never written to (checkpoints live in a controller-owned repo).
    A detached or drifted checkout is checkpointed even without unique work so a continuation can be
    bound to its identity; retirement passes ``retain_identity=False`` because it authorizes no
    continuation and only unique work must be retained. ``expected_container_id`` fences a caller
    that observed one exact container: a different recorded ID refuses before any removal.
    """

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    if state["issue_mappings"][str(issue)].get("state") == "retired":
        raise LaunchRefused(f"worker {worker!r} is retired")
    if expected_container_id is not None and (
            not _CONTAINER_ID.fullmatch(expected_container_id)
            or state["issue_mappings"][str(issue)].get("container_id") != expected_container_id):
        raise EpicWorkspaceError("worker container identity changed before stop")
    _assert_engine(runner)
    _settle_checkpoint_writer(layout, worker, runner)
    mapping = state["issue_mappings"][str(issue)]
    if (mapping.get("state") == "starting" and not mapping.get("container_id")
            and mapping.get("launch_protocol") != LAUNCH_PROTOCOL):
        raise TakeoverRefused("legacy worker launch outcome is unknown; ID-bound stop proof is unavailable")
    cid = mapping.get("container_id")
    if cid is not None and (not isinstance(cid, str) or not _CONTAINER_ID.fullmatch(cid)):
        raise TakeoverRefused("recorded worker container ID is invalid; refusing removal")
    _remove_owned(layout.container_name(worker), {LABEL_EPIC: str(layout.epic), LABEL_WORKER: worker}, runner, cid=cid)
    remaining = _container_state(layout, worker, runner)
    if remaining is not None:
        raise EpicWorkspaceError(f"worker {worker!r} container still present ({remaining}); not verified stopped")
    work, ignored_all = _inspect(layout, worker, runner=runner, image=image)
    stop_id = uuid.uuid4().hex

    def record_stop(entry: dict[str, Any]) -> None:
        needs_takeover = (bool(entry.get("started_at")) or bool(work.get("unique_work"))
                          or not work.get("readable") or work.get("branch") is None
                          or work.get("branch") != entry.get("execution_branch", entry.get("branch")) or any(
            op.get("status") in _OP_UNRESOLVED
            for op in entry.get("publication_ops", []) if isinstance(op, Mapping)
        ))
        entry.update(state="stopped_verified", stopped_at=_now(), stop_id=stop_id, stop_reason=reason, work_at_stop=work)
        if needs_takeover:
            entry["takeover"] = {"status": "required", "reason": reason, "at": _now(), "generation": int(_takeover_of(entry).get("generation", 0))}
        conversation = entry.get("conversation")
        if isinstance(conversation, Mapping):
            entry["conversation"] = {**conversation, "status": CONVERSATION_ENDED, "ended_at": _now()}

    _mutate_mapping(layout, worker, record_stop)
    work = dict(work)
    work["stop_id"] = stop_id
    drifted = work.get("branch") != mapping.get("execution_branch", mapping.get("branch"))
    work["checkpoint"] = _checkpoint(layout, issue, worker, work, ignored_all, reason=reason, runner=runner, image=image,
                                     force=retain_identity and (drifted or work.get("branch") is None))
    return work


@_serialized_worker
def stop_worker(layout: Layout, worker: str, *, reason: str, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE,
                expected_container_id: str | None = None) -> dict[str, Any]:
    return _stop_worker(layout, worker, reason=reason, runner=runner, image=image,
                        expected_container_id=expected_container_id)


def _controller_dir(layout: Layout, *parts: str) -> Path:
    """A controller-owned directory under ``control/``; a symlink anywhere on the path is refused."""

    path = layout.epic_dir
    for part in ("control", *parts):
        path = path / part
        if path.is_symlink():
            raise EpicWorkspaceError(f"controller path {path} is a symlink; refusing")
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir() or path.is_symlink():
            raise EpicWorkspaceError(f"controller path {path} is not a plain directory; refusing")
    return path


_GITDIR_CONFIG = "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = false\n"
_RAW_ATTRIBUTES = "* -text -eol -crlf -ident -filter -working-tree-encoding\n"


def _make_gitdir(path: Path, head: str | None) -> None:
    """Create (or re-verify) a minimal controller-owned git dir without running git.

    Its config is the controller's own, so no worker-planted filter, hook or fsmonitor setting
    can be read from it; objects of the worker checkout are borrowed through alternates.
    """

    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise EpicWorkspaceError(f"git dir {path} is not a plain directory; refusing")
    path.mkdir(mode=0o700, exist_ok=True)
    for sub in ("objects", "objects/info", "objects/pack", "refs", "refs/heads", "refs/checkpoints", "info"):
        entry = path / sub
        if entry.is_symlink():
            raise EpicWorkspaceError(f"git dir entry {entry} is a symlink; refusing")
        entry.mkdir(mode=0o700, exist_ok=True)
    for name, content in (("config", _GITDIR_CONFIG), ("HEAD", f"{head}\n" if head else "ref: refs/heads/epic-scratch\n")):
        entry = path / name
        if entry.is_symlink():
            raise EpicWorkspaceError(f"git dir entry {entry} is a symlink; refusing")
        if name == "HEAD" or not entry.exists():
            entry.write_text(content, encoding="utf-8")
    attributes = path / "info" / "attributes"
    if attributes.is_symlink() or (attributes.exists() and not attributes.is_file()):
        raise EpicWorkspaceError(f"git dir entry {attributes} is not a plain file; refusing")
    # info/attributes takes precedence over the worktree even on Git before 2.40.
    attributes.write_text(_RAW_ATTRIBUTES, encoding="utf-8")


@contextmanager
def _scratch_gitdir(layout: Layout, head: str | None = None) -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="git-", dir=_controller_dir(layout, "scratch")))
    try:
        _make_gitdir(path, head)
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


_GIT_HARDENING = (
    "--no-optional-locks",
    "-c", "core.fsmonitor=false", "-c", "core.ignoreStat=false", "-c", "core.hooksPath=/dev/null",
    "-c", "core.sparseCheckout=false", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
    "-c", "core.commitGraph=false", "-c", "core.multiPackIndex=false",
    "-c", "pack.threads=1", "-c", "pack.windowMemory=64m",
    "-c", f"safe.directory={INSPECT_TARGET}", "-c", f"safe.directory={SCRATCH_TARGET}",
)


def _contained_git(
    checkout: Path,
    args: Sequence[str],
    *,
    runner: Runner,
    image: str,
    scratch: Path | None = None,
    scratch_readonly: bool = False,
    env: Mapping[str, str] | None = None,
    timeout: float = GIT_TIMEOUT,
    input_data: str | None = None,
    cwd: str = INSPECT_TARGET,
    binary: bool = False,
    checkpoint_owner: tuple[Layout, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run git against a worker checkout inside a throwaway container.

    The checkout is always mounted read-only. Its ``.git/config``, attributes and hooks are
    worker-controlled, so two modes exist:

    * ``scratch=None``: the worker's own git dir, used only for ref and commit plumbing, with
      fsmonitor, hooks, ignoreStat and replace objects neutralised.
    * ``scratch=<controller dir>``: a controller-owned git dir (clean config, neutral attributes,
      its own index) whose work tree is the read-only checkout and whose objects borrow the
      checkout's through alternates. Controller info/attributes neutralizes worker attributes;
      filters cannot run because no drivers are configured. Git writes only to the scratch dir.

    A call that exceeds ``timeout`` is killed and reported as a failure, so a hung command is
    treated as unreadable evidence, never as a clean result.
    """

    git_dir = checkout / ".git"
    if checkout.is_symlink() or git_dir.is_symlink() or not git_dir.is_dir() or (git_dir / "objects").is_symlink():
        raise EpicWorkspaceError("checkout or git directory is missing or a symlink")
    source = str(checkout.resolve(strict=True))
    if not _MOUNT_PATH.match(source):
        raise EpicWorkspaceError("checkout path contains unsafe characters")
    environment: dict[str, str] = {
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_ATTR_NOSYSTEM": "1",
    }
    mounts = [f"type=bind,source={source},target={INSPECT_TARGET},readonly"]
    extra_config: list[str] = []
    if scratch is None:
        environment["GIT_DIR"] = f"{INSPECT_TARGET}/.git"
    else:
        scratch_source = str(scratch.resolve(strict=True))
        if scratch.is_symlink() or not _MOUNT_PATH.match(scratch_source):
            raise EpicWorkspaceError("scratch path is a symlink or contains unsafe characters")
        mounts.append(f"type=bind,source={scratch_source},target={SCRATCH_TARGET}" + (",readonly" if scratch_readonly else ""))
        environment.update({
            "GIT_DIR": SCRATCH_TARGET, "GIT_WORK_TREE": INSPECT_TARGET, "GIT_INDEX_FILE": f"{SCRATCH_TARGET}/index",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": f"{INSPECT_TARGET}/.git/objects", "GIT_ATTR_SOURCE": EMPTY_TREE,
        })
        extra_config = ["-c", f"core.excludesFile={INSPECT_TARGET}/.git/info/exclude"]
    environment.update(env or {})
    env_args: list[str] = []
    for key, value in environment.items():
        if not _ENV_KEY.match(key) or "\n" in value or "\x00" in value:
            raise EpicWorkspaceError(f"invalid environment entry {key!r}")
        env_args += ["--env", f"{key}={value}"]
    name = f"{CONTAINER_PREFIX}-git-{uuid.uuid4().hex[:12]}"
    argv = [
        "docker", "run", "--rm", "--name", name, "--label", "epic-workspace.inspect=1",
        "--network", "none", "--read-only", "--cap-drop", "ALL",
        # The writable scratch mount is owned by the controller, which need not have the
        # worker image's UID. Files the controller cannot read remain unreadable evidence.
        "--security-opt", "no-new-privileges", "--user", f"{os.geteuid()}:{os.getegid()}", "--pids-limit", "64",
        "--memory", "256m", "--tmpfs", "/tmp:rw,nosuid,size=16m", "--env", "HOME=/tmp", *env_args,
        *(["--interactive"] if input_data is not None else []),
        *[arg for mount in mounts for arg in ("--mount", mount)],
        image,
        "git", *_GIT_HARDENING, *extra_config, "-C", cwd, *args,
    ]
    options: dict[str, Any] = {"input": input_data} if input_data is not None else {}
    if checkpoint_owner is not None:
        # Unlike disposable inspection scratch, the checkpoint store is reused. Persist its
        # writer's ID before start so recovery can remove even a late start request by that ID.
        create = list(argv)
        create[1] = "create"
        try:
            result = runner(create, capture_output=True, text=True, check=False, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return subprocess.CompletedProcess(argv, 124, "", "checkpoint create outcome unknown (never started)")
        cid = (result.stdout or "").strip()
        if result.returncode != 0 or not _CONTAINER_ID.fullmatch(cid):
            return subprocess.CompletedProcess(argv, 124, "", "checkpoint create failed (never started)")
        owner_layout, owner_worker = checkpoint_owner

        def mark(entry: dict[str, Any]) -> None:
            entry["checkpoint_inspection_unknown"] = {
                "at": _now(), "protocol": LAUNCH_PROTOCOL, "name": name, "container_id": cid,
            }

        _mutate_mapping(owner_layout, owner_worker, mark)
        try:
            result = runner(["docker", "start", "--attach", *(["--interactive"] if input_data is not None else []), cid],
                            capture_output=True, text=not binary, check=False, timeout=timeout, **options)
        except (subprocess.TimeoutExpired, OSError):
            result = subprocess.CompletedProcess(argv, 124, b"" if binary else "", "git inspection timed out or transport failed")
        try:
            _settle_checkpoint_writer(owner_layout, owner_worker, runner)
        except EpicWorkspaceError:
            return subprocess.CompletedProcess(argv, 124, b"" if binary else "", f"inspection cleanup unverified: {name}")
        return result
    try:
        return runner(argv, capture_output=True, text=not binary, check=False, timeout=timeout, **options)
    except (subprocess.TimeoutExpired, OSError) as exc:
        detail = f"git {args[0] if args else ''} {'timed out' if isinstance(exc, subprocess.TimeoutExpired) else 'inspection transport failed'}"
        try:
            _remove_owned(name, {"epic-workspace.inspect": "1"}, runner)
        except EpicWorkspaceError:
            detail += f"; inspection cleanup unverified: {name}"
        return subprocess.CompletedProcess(argv, 124, b"" if binary else "", detail)


class _Unreadable(Exception):
    pass


def _raw_byte_preflight(checkout: Path, repo: Path, *, runner: Runner, image: str,
                        checkpoint_owner: tuple[Layout, str] | None = None) -> None:
    """Fail closed unless contained Git round-trips CRLF against converting attributes."""

    def fail(result: subprocess.CompletedProcess, step: str) -> None:
        detail = result.stderr if isinstance(result.stderr, str) else ""
        suffix = f"; {detail}" if result.returncode == 124 and "inspection cleanup unverified" in detail else ""
        raise _Unreadable(f"raw-byte Git preflight failed: {step}{suffix}")

    fixture = Path(tempfile.mkdtemp(prefix="raw-preflight-", dir=repo))
    try:
        (fixture / ".gitattributes").write_text("*.txt text eol=lf\n", encoding="utf-8")
        expected = b"raw\r\nbytes\r\n"
        (fixture / "raw.txt").write_bytes(expected)
        target = f"{SCRATCH_TARGET}/{fixture.name}"
        env = {"GIT_WORK_TREE": target, "GIT_INDEX_FILE": f"{target}/index"}
        added = _contained_git(checkout, ["add", "-f", "--", "raw.txt"], runner=runner, image=image,
                               scratch=repo, env=env, cwd=target, checkpoint_owner=checkpoint_owner)
        if added.returncode != 0:
            fail(added, "add")
        read = _contained_git(checkout, ["show", ":raw.txt"], runner=runner, image=image,
                              scratch=repo, env=env, cwd=target, binary=True, checkpoint_owner=checkpoint_owner)
        if read.returncode != 0 or read.stdout != expected:
            fail(read, "CRLF did not round-trip")
    finally:
        if checkpoint_owner is None or not _load_state(checkpoint_owner[0])["issue_mappings"][str(
            _issue_for_worker(_load_state(checkpoint_owner[0]), checkpoint_owner[1])
        )].get("checkpoint_inspection_unknown"):
            shutil.rmtree(fixture, ignore_errors=True)


def _copy_worker_index(checkout: Path, repo: Path, index: Path) -> str:
    """Copy and fingerprint index bytes, including split-index bases, without host Git."""

    def copy_plain(source: Path, destination: Path) -> None:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as src:
            if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):
                raise _Unreadable("worker index is not a regular file")
            if destination.exists() or destination.is_symlink():
                if destination.is_symlink() or not destination.is_file() or destination.read_bytes() != src.read():
                    raise _Unreadable("controller index copy collision")
            else:
                with destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst)

    git_dir = checkout / ".git"
    copy_plain(git_dir / "index", index)
    copies = [("index", index)]
    for source in sorted(git_dir.glob("sharedindex.*")):
        if not re.fullmatch(r"sharedindex\.(?:[0-9a-f]{40}|[0-9a-f]{64})", source.name):
            raise _Unreadable("invalid split index name")
        copy_plain(source, repo / source.name)
        copies.append((source.name, repo / source.name))
    digest = hashlib.sha256()
    for name, path in copies:
        part = hashlib.sha256()
        with path.open("rb") as saved:
            for block in iter(lambda: saved.read(1024 * 1024), b""):
                part.update(block)
        digest.update(name.encode("ascii") + b"\0" + part.digest())
    return digest.hexdigest()


def _assert_plain_git_metadata(checkout: Path) -> None:
    """Do not let Git silently skip symlinked or unreadable worker metadata."""

    git_dir = checkout / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise _Unreadable("git directory")
    count = 0

    def fail(exc: OSError) -> None:
        raise exc

    for directory, dirs, files in os.walk(git_dir, followlinks=False, onerror=fail):
        for name in (*dirs, *files):
            count += 1
            if count > MAX_GIT_METADATA_ENTRIES:
                raise _Unreadable("too many git metadata entries")
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise _Unreadable("symlink or special git metadata")
            if stat.S_ISREG(mode) and name.endswith(".lock"):
                raise _Unreadable("unsettled git metadata lock")
            if (path.relative_to(git_dir).parts[0] in ("refs", "logs", "worktrees", "packed-refs")
                    and (not mode & 0o444 or (stat.S_ISDIR(mode) and not mode & 0o111))):
                raise _Unreadable("unreadable ref or reflog metadata")


def _reflog_identity(content_fingerprint: str, oids: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(
        [content_fingerprint, list(oids)], separators=(",", ":"),
    ).encode("ascii")).hexdigest()


def _valid_reflog_evidence(value: Mapping[str, Any]) -> bool:
    content = value.get("reflog_content_fingerprint")
    fingerprint = value.get("reflog_fingerprint")
    oids = value.get("retained_reflog")
    return bool(
        isinstance(content, str) and _DIGEST.fullmatch(content)
        and isinstance(fingerprint, str) and _DIGEST.fullmatch(fingerprint)
        and isinstance(oids, list) and len(oids) <= MAX_RETAINED_REFS
        and all(isinstance(oid, str) and _OID.fullmatch(oid) and set(oid) != {"0"} for oid in oids)
        and oids == sorted(set(oids)) and fingerprint == _reflog_identity(content, oids)
    )


def _retained_marker(value: Mapping[str, Any]) -> str | None:
    """Bind every retained source to the existing checkpoint commit pair."""

    refs = value.get("retained_refs")
    groups = [value.get("retained_heads"), value.get("retained_stash"), value.get("retained_reflog")]
    head = value.get("head")
    fingerprint = value.get("refs_fingerprint")
    if (not _valid_reflog_evidence(value) or not isinstance(head, str) or not _OID.fullmatch(head)
            or not isinstance(fingerprint, str) or not _DIGEST.fullmatch(fingerprint)
            or not isinstance(refs, list) or len(refs) > MAX_RETAINED_REFS
            or not all(isinstance(item, Mapping) and isinstance(item.get("ref"), str)
                       and item["ref"].startswith("refs/") and isinstance(item.get("sha"), str)
                       and _OID.fullmatch(item["sha"]) for item in refs)
            or not all(isinstance(group, list) and len(group) <= MAX_RETAINED_REFS
                       and all(isinstance(oid, str) and _OID.fullmatch(oid) for oid in group) for group in groups)):
        return None
    manifest = [head, fingerprint, refs, *groups, value["reflog_fingerprint"]]
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
    return f"epic-retained-v1 {digest}"


def _read_reflogs(checkout: Path) -> tuple[str, str, list[str], list[str]]:
    """Read common and linked-worktree reflogs, including both sides of every entry.

    Git's reflog commands can silently skip broken lines and missing objects. Read and
    validate the metadata instead; object and connectivity checks still run in contained Git.
    """

    git_dir = checkout / ".git"
    roots = [git_dir / "logs"]
    worktrees = git_dir / "worktrees"
    if worktrees.exists():
        if worktrees.is_symlink() or not worktrees.is_dir():
            raise _Unreadable("linked worktree metadata")
        for worktree in sorted(worktrees.iterdir()):
            if worktree.is_symlink() or not worktree.is_dir():
                raise _Unreadable("linked worktree metadata")
            roots.append(worktree / "logs")

    files: list[Path] = []
    for root in roots:
        if root.is_symlink() or not root.is_dir() or not (root / "HEAD").is_file():
            raise _Unreadable("missing reflog evidence")

        def fail(exc: OSError) -> None:
            raise exc

        for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail):
            if not (Path(directory).stat().st_mode & 0o555):
                raise _Unreadable("unreadable reflog directory")
            dirs.sort()
            files.extend(Path(directory) / name for name in sorted(names))

    digest = hashlib.sha256()
    oids: set[str] = set()
    stash: set[str] = set()
    total = 0
    for path in sorted(files):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as src:
            mode = os.fstat(src.fileno()).st_mode
            if not stat.S_ISREG(mode) or not mode & 0o444:
                raise _Unreadable("unreadable reflog")
            data = src.read(MAX_REFLOG_BYTES - total + 1)
        total += len(data)
        if total > MAX_REFLOG_BYTES or (data and not data.endswith(b"\n")):
            raise _Unreadable("oversized or incomplete reflog")
        digest.update(os.fsencode(path.relative_to(git_dir)) + b"\0" + hashlib.sha256(data).digest())
        # Only LF delimits raw records. splitlines() would also erase CR and
        # could turn an invalid record into an apparently valid one.
        for line in data.split(b"\n")[:-1]:
            match = _REFLOG_LINE.fullmatch(line)
            if (not match or len(match[1]) != len(match[2])
                    or not (match[1].strip(b"0") or match[2].strip(b"0"))):
                raise _Unreadable("malformed reflog")
            for raw in (match[1], match[2]):
                if raw.strip(b"0"):
                    oid = raw.decode("ascii")
                    oids.add(oid)
                    if path == git_dir / "logs" / "refs" / "stash":
                        stash.add(oid)
            if len(oids) > MAX_RETAINED_REFS:
                raise _Unreadable("too many reflog objects")
    content = digest.hexdigest()
    retained = sorted(oids)
    return content, _reflog_identity(content, retained), retained, sorted(stash)


def _parse_status(raw: str) -> tuple[list[str], list[str]]:
    """Split ``status --porcelain=v1 -z`` into (changed, ignored) paths."""

    changed: list[str] = []
    ignored: list[str] = []
    items = raw.split("\0")
    index = 0
    while index < len(items):
        entry = items[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            index += 1  # the rename/copy source follows as a separate field
        (ignored if code == "!!" else changed).append(path)
    return changed, ignored


def _source_tips(layout: Layout) -> list[str]:
    """Object ids of controller-owned ``source.git`` refs (read without running git)."""

    source = layout.source
    if source.is_symlink() or not source.is_dir():
        raise _Unreadable("controller source repository")
    refs: dict[str, str] = {}
    symbolic: dict[str, str] = {}
    packed_path = source / "packed-refs"
    if packed_path.is_symlink():
        raise _Unreadable("symlinked packed controller refs")
    try:
        packed = packed_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        packed = ""
    for line in packed.splitlines():
        if not line or line[0] in "#^":
            continue
        sha, _, ref = line.partition(" ")
        if not _OID.match(sha) or not ref.startswith("refs/"):
            raise _Unreadable("packed controller ref")
        refs[ref] = sha
    refs_dir = source / "refs"
    if refs_dir.is_symlink() or not refs_dir.is_dir():
        raise _Unreadable("controller refs directory")

    def fail(exc: OSError) -> None:
        raise exc

    for directory, dirs, files in os.walk(refs_dir, followlinks=False, onerror=fail):
        if any((Path(directory) / name).is_symlink() for name in dirs):
            raise _Unreadable("symlinked controller refs")
        for name in files:
            path = Path(directory) / name
            ref = "refs/" + path.relative_to(refs_dir).as_posix()
            if path.is_symlink() or not path.is_file():
                raise _Unreadable("controller ref")
            value = path.read_text(encoding="utf-8").strip()
            # A loose ref always overrides a packed value, including symbolic refs.
            refs.pop(ref, None)
            if _OID.match(value):
                refs[ref] = value
            elif value.startswith("ref: refs/"):
                symbolic[ref] = value[5:]
            else:
                raise _Unreadable("malformed controller ref")
    for ref in symbolic:
        target = ref
        seen: set[str] = set()
        while target in symbolic:
            if target in seen:
                raise _Unreadable("cyclic controller ref")
            seen.add(target)
            target = symbolic[target]
        if target not in refs:
            raise _Unreadable("unresolved controller ref")
    return sorted(set(refs.values()))


def _published_tips(layout: Layout, worker: str) -> list[str]:
    """Everything that counts as published, from controller-held evidence only.

    That is the refs of ``source.git`` plus the commit ids the coordinator recorded in
    run-state when it completed or reconciled a publication from GitHub readback. Nothing the worker
    can write (remote-tracking refs, tags, checkpoint-looking refs) is ever consulted.
    """

    tips = set(_source_tips(layout))
    for mapping in _load_state(layout).get("issue_mappings", {}).values():
        if isinstance(mapping, Mapping) and mapping.get("worker") == worker:
            for head in mapping.get("published_heads", []):
                if isinstance(head, Mapping) and isinstance(head.get("sha"), str) and _OID.match(head["sha"]):
                    tips.add(head["sha"])
    if len(tips) > MAX_PUBLISHED_TIPS:
        raise _Unreadable("published tips")
    return sorted(tips)


def _inspect(layout: Layout, worker: str, *, runner: Runner, image: str) -> tuple[dict[str, Any], list[str]]:
    """Return (summary, ignored paths). Unreadable evidence is unique work."""

    checkout = layout.checkout(worker)
    if checkout.is_symlink():
        return {"present": True, "readable": False, "unique_work": True}, []
    if not checkout.is_dir():
        return {"present": False, "readable": False, "unique_work": True}, []

    def git(*args: str, scratch: Path | None = None) -> str:
        result = _contained_git(checkout, args, runner=runner, image=image, scratch=scratch)
        if result.returncode != 0 or (result.stderr or "").strip():
            raise _Unreadable(args[0])
        return result.stdout or ""

    try:
        _assert_plain_git_metadata(checkout)
        _assert_engine(runner)
        tips = _published_tips(layout, worker)
        identity = git("rev-parse", "HEAD", "--abbrev-ref", "HEAD").split()
        if len(identity) != 2 or not _OID.match(identity[0]):
            raise _Unreadable("rev-parse")
        head, abbrev = identity
        branch = None if abbrev == "HEAD" else abbrev
        # Copy the real index into the controller dir. A staged-only edit must not disappear
        # when the worktree happens to match HEAD, and an unmerged index cannot be checkpointed.
        with _scratch_gitdir(layout, head) as scratch:
            _raw_byte_preflight(checkout, scratch, runner=runner, image=image)
            index_fingerprint = _copy_worker_index(checkout, scratch, scratch / "index")
            if git("ls-files", "--unmerged", "-z", scratch=scratch):
                raise _Unreadable("unmerged worker index")
            if any(entry.startswith("160000 ") for entry in git("ls-files", "--stage", "-z", scratch=scratch).split("\0")):
                raise _Unreadable("nested repository in worker index")
            staged_tree = git("write-tree", scratch=scratch).strip()
            if not _OID.match(staged_tree):
                raise _Unreadable("worker index tree")
            staged_paths = [p for p in git("diff-index", "--cached", "--name-only", "-z", "--no-renames", head, scratch=scratch).split("\0") if p]
            (scratch / "index").unlink()
            # A fresh index also catches edits hidden by skip-worktree, assume-unchanged,
            # core.ignoreStat or worker-planted filters.
            git("read-tree", head, scratch=scratch)
            status_changed, ignored_all = _parse_status(git(
                "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching",
                "--ignore-submodules=none", "--no-renames", scratch=scratch,
            ))
            # A cache-looking name does not prove its contents are reproducible. Preserve
            # all ignored paths until a separate, qualified disposal decision exists.
            ignored = ignored_all
            # The scratch index starts at HEAD rather than the worker's index, so its flags and
            # cached stat information cannot suppress a modified file. The scratch configuration
            # and neutral attributes keep worker filters out of both add operations.
            git("add", "-A", "--", ".", scratch=scratch)
            indexed_changed = [p for p in git("diff-index", "--cached", "--name-only", "-z", head, scratch=scratch).split("\0") if p]
            changed = sorted(set(status_changed) | set(indexed_changed) | set(staged_paths))
            for offset in range(0, len(ignored), 100):
                result = _contained_git(
                    checkout, ["add", "-f", "-A", "--", *ignored[offset:offset + 100]],
                    runner=runner, image=image, scratch=scratch, env={"GIT_LITERAL_PATHSPECS": "1"},
                )
                if result.returncode != 0 or (result.stderr or "").strip():
                    raise _Unreadable("add ignored paths")
            gitlinks = [
                entry.split("\t", 1)[1] for entry in git("ls-files", "--stage", "-z", scratch=scratch).split("\0")
                if entry.startswith("160000 ") and "\t" in entry
            ]
            # A gitlink does not capture a nested worktree's ignored or uncommitted files.
            if gitlinks:
                raise _Unreadable("nested repository")
            snapshot_tree = git("write-tree", scratch=scratch).strip()
            if not _OID.match(snapshot_tree):
                raise _Unreadable("snapshot tree")
        refs = [tuple(line.split(" ", 1)) for line in git("for-each-ref", "--format=%(objectname) %(refname)").splitlines() if line]
        if len(refs) > MAX_RETAINED_REFS or any(len(item) != 2 or not _OID.match(item[0]) for item in refs):
            raise _Unreadable("refs")
        reflog_content_fingerprint, reflog_fingerprint, reflog_shas, stash_shas = _read_reflogs(checkout)
        worktree_listing = git("worktree", "list", "--porcelain")
        worktree_heads = [line[5:] for line in worktree_listing.splitlines() if line.startswith("HEAD ")]
        worktree_count = sum(line.startswith("worktree ") for line in worktree_listing.splitlines())
        if not worktree_heads or len(worktree_heads) != worktree_count or any(not _OID.fullmatch(sha) for sha in worktree_heads):
            raise _Unreadable("worktree heads")
        extra_heads = sorted(set(worktree_heads))
        refs_fingerprint = hashlib.sha256(
            json.dumps([refs, worktree_listing, stash_shas], ensure_ascii=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing: list[str] = []
        if tips:
            existing = [sha for sha in git("rev-list", "--no-walk", "--ignore-missing", *tips).split() if _OID.match(sha)]
        not_published = ["--not", *existing] if existing else []

        def count(*positive: str) -> int:
            return int(git("rev-list", "--count", *positive, *not_published).strip() or 0)

        unpublished_total = count("--all", head, *extra_heads, *reflog_shas)
        head_unpublished = 0
        other_branches: list[dict[str, Any]] = []
        other_refs: list[dict[str, Any]] = []
        stash_unpublished = 0
        detail_truncated = False
        if unpublished_total:
            head_unpublished = count("HEAD")
            stash_unpublished = count(*stash_shas) if stash_shas else 0
            queries = 0
            for sha, ref in refs:
                if ref == "refs/stash" or ref == f"refs/heads/{branch}":
                    continue
                if queries >= MAX_DETAIL_QUERIES:
                    detail_truncated = True
                    break
                queries += 1
                unpublished = count(sha)
                if unpublished:
                    (other_branches if ref.startswith("refs/heads/") else other_refs).append({"ref": ref, "unpublished": unpublished})
    except _Unreadable as exc:
        return {"present": True, "readable": False, "unique_work": True, "reason": str(exc)}, []
    except Exception:  # noqa: BLE001 - any failure to read evidence is unique work (fail safe)
        return {"present": True, "readable": False, "unique_work": True}, []
    summary = {
        "present": True,
        "readable": True,
        "head": head,
        "branch": branch,
        "snapshot_tree": snapshot_tree,
        "staged_tree": staged_tree,
        "index_fingerprint": index_fingerprint,
        "staged_paths": staged_paths[:50],
        "staged_count": len(staged_paths),
        "refs_fingerprint": refs_fingerprint,
        "reflog_content_fingerprint": reflog_content_fingerprint,
        "reflog_fingerprint": reflog_fingerprint,
        "retained_reflog": reflog_shas,
        "retained_refs": [{"ref": ref, "sha": sha} for sha, ref in refs],
        "retained_heads": extra_heads,
        "linked_worktrees": worktree_count - 1,
        "retained_stash": stash_shas,
        "uncommitted_paths": changed[:50],
        "uncommitted_count": len(changed),
        "ignored_paths": ignored[:50],
        "ignored_count": len(ignored),
        "disposable_ignored_count": len(ignored_all) - len(ignored),
        "published_tip_count": len(existing),
        "unpublished_total": unpublished_total,
        "unpublished_commits": head_unpublished,
        "other_branches": other_branches,
        "other_refs": other_refs,
        "detail_truncated": detail_truncated,
        "stash_entries": len(stash_shas),
        "stash_unpublished": stash_unpublished,
        "unique_work": bool(changed or ignored or unpublished_total),
    }
    return summary, ignored


_IDENTITY_FIELDS = ("branch", "head", "snapshot_tree", "staged_tree", "index_fingerprint", "refs_fingerprint", "reflog_fingerprint")


def _checkout_identity(work: Mapping[str, Any]) -> dict[str, Any]:
    """Extract a complete immutable inspection identity, including a detached HEAD."""

    branch = work.get("branch")
    if (work.get("present") is not True or work.get("readable") is not True or any(k not in work for k in _IDENTITY_FIELDS)
            or (branch is not None and (not isinstance(branch, str) or not _BRANCH.fullmatch(branch) or ".." in branch))
            or any(not isinstance(work.get(k), str) or not _OID.fullmatch(work[k])
                   for k in ("head", "snapshot_tree", "staged_tree"))
            or any(not isinstance(work.get(k), str) or not _DIGEST.fullmatch(work[k])
                   for k in ("index_fingerprint", "refs_fingerprint", "reflog_fingerprint"))):
        raise TakeoverRefused("checkout identity is missing or unreadable; preserve it and run takeover")
    return {key: work[key] for key in _IDENTITY_FIELDS}


def _fence_authorization(layout: Layout, worker: str, generation: Any) -> None:
    def mutate(entry: dict[str, Any]) -> None:
        pending = _takeover_of(entry)
        if pending.get("status") == "authorized" and pending.get("generation") == generation:
            entry["takeover"] = {**pending, "status": "required", "reason": "authorized checkout identity needs reconciliation"}

    _mutate_mapping(layout, worker, mutate)


def _authorization_record(mapping: Mapping[str, Any]) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
    """Validate the durable binding without consulting a live checkout or engine."""
    pending = _takeover_of(mapping)
    identity = mapping.get("execution_identity")
    if not isinstance(identity, Mapping):
        raise TakeoverRefused("authorized checkout identity is missing; run takeover to reconcile it")
    expected = _checkout_identity({**identity, "present": True, "readable": True})
    stopped = mapping.get("work_at_stop")
    if (not isinstance(stopped, Mapping) or _checkout_identity(stopped) != expected
            or mapping.get("execution_branch", mapping.get("branch")) != expected["branch"]
            or pending.get("execution_branch") != expected["branch"]
            or pending.get("head") != expected["head"] or pending.get("publisher_branch") != mapping.get("branch")):
        raise TakeoverRefused("authorized checkout binding changed; run takeover to reconcile it")
    if "checkpoint_ref" not in identity:
        raise TakeoverRefused("authorized checkpoint binding is missing; run takeover to reconcile it")
    checkpoint_ref = identity.get("checkpoint_ref")
    checkpoint = None
    if checkpoint_ref is not None:
        checkpoints = mapping.get("checkpoints", [])
        if not isinstance(checkpoints, list):
            raise TakeoverRefused("authorized checkpoints are unreadable; run takeover to reconcile them")
        checkpoint = next((c for c in checkpoints if isinstance(c, Mapping)
                           and c.get("ref") == checkpoint_ref and c.get("status") == "preserved"), None)
        if (not checkpoint or checkpoint.get("branch") != expected["branch"]
                or checkpoint.get("head") != expected["head"] or checkpoint.get("tree") != expected["snapshot_tree"]
                or checkpoint.get("staged_tree") != expected["staged_tree"]
                or checkpoint.get("refs_fingerprint") != expected["refs_fingerprint"]
                or checkpoint.get("reflog_fingerprint") != expected["reflog_fingerprint"]
                or not _valid_reflog_evidence(checkpoint) or not _valid_reflog_evidence(stopped)
                or checkpoint.get("retained_reflog") != stopped.get("retained_reflog")
                or checkpoint.get("reflog_content_fingerprint") != stopped.get("reflog_content_fingerprint")
                or not isinstance(checkpoint.get("staged_ref"), str)
                or any(not isinstance(checkpoint.get(k), str) or not _OID.fullmatch(checkpoint[k])
                       for k in ("commit", "staged_commit"))):
            raise TakeoverRefused("authorized checkpoint binding changed; run takeover to reconcile it")
    elif (expected["branch"] is None or stopped.get("unique_work")
          or pending.get("previous_execution_branch") != expected["branch"]):
        raise TakeoverRefused("checkout has no retained checkpoint; run takeover to reconcile it")
    return dict(identity), checkpoint


def _check_authorized_checkout(
    layout: Layout, worker: str, mapping: Mapping[str, Any], *, runner: Runner, image: str,
) -> dict[str, Any]:
    """Preflight the saved authorization against its checkpoint and the actual checkout."""

    identity, checkpoint = _authorization_record(mapping)
    expected = _checkout_identity({**identity, "present": True, "readable": True})
    if mapping.get("checkout") != str(layout.checkout(worker)):
        raise TakeoverRefused("authorized checkout path changed; run takeover to reconcile it")
    if checkpoint is not None and not _checkpoint_present(layout.checkout(worker), _checkpoint_repo(layout, worker), checkpoint, runner, image):
        raise TakeoverRefused("authorized checkpoint is unreadable; run takeover to reconcile it")
    actual, _ = _inspect(layout, worker, runner=runner, image=image)
    if _checkout_identity(actual) != expected:
        raise TakeoverRefused("authorized checkout changed; run takeover to reconcile it")
    _assert_engine(runner)
    if _container_state(layout, worker, runner) is not None:
        raise TakeoverRefused("worker container is present; run takeover before continuation")
    return identity


def _preflight_start(
    layout: Layout, worker: str, mapping: Mapping[str, Any], *, runner: Runner, image: str,
) -> dict[str, Any] | None:
    pending = _takeover_of(mapping)
    if pending.get("status") == "authorized":
        try:
            identity = _check_authorized_checkout(layout, worker, mapping, runner=runner, image=image)
        except EpicWorkspaceError:
            _fence_authorization(layout, worker, pending.get("generation"))
            raise
        return {"identity": identity, "checked_identity": _checkout_identity({**identity, "present": True, "readable": True}),
                "generation": pending.get("generation"), "branch": mapping.get("branch")}
    if mapping.get("state") == "created" or (mapping.get("state") == "stopped_verified" and not mapping.get("started_at")):
        work, _ = _inspect(layout, worker, runner=runner, image=image)
        identity = _checkout_identity(work)
        expected_branch = mapping.get("execution_branch", mapping.get("branch"))
        if not isinstance(expected_branch, str) or identity["branch"] != expected_branch:
            raise TakeoverRefused("checkout does not match its recorded execution branch; run takeover")
        return {"identity": None, "checked_identity": identity, "generation": pending.get("generation"), "branch": mapping.get("branch"),
                "execution_branch": expected_branch}
    return None


def inspect_checkout(layout: Layout, worker: str, *, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE) -> dict[str, Any]:
    """Classify a worker checkout's unique work without executing worker-controlled config.

    Unique work is: staged edits, uncommitted or untracked files (also checked against a fresh index), ignored files,
    any commit reachable from any ref, reflog, stash or linked worktree HEAD that is not
    reachable from controller-held published evidence, and
    anything that cannot be read (fail safe). "Published" is never inferred from refs in the
    checkout.
    """

    return _inspect(layout, worker, runner=runner, image=image)[0]


def checkout_branch(checkout: Path, *, runner: Runner, image: str = DEFAULT_IMAGE) -> str | None:
    """The branch the checkout actually has checked out (``None`` when detached)."""

    _assert_engine(runner)
    result = _contained_git(checkout, ["rev-parse", "--abbrev-ref", "HEAD"], runner=runner, image=image)
    if result.returncode != 0:
        raise EpicWorkspaceError("checkout branch is unreadable")
    name = (result.stdout or "").strip()
    return None if name == "HEAD" else name


def status(layout: Layout, *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Join run-state, engine readback and checkout evidence for each worker."""

    state = _load_state(layout)
    try:
        engine = _assert_engine(runner)
    except EngineUnavailable:
        engine = None
    workers = []
    for key, mapping in sorted(state.get("issue_mappings", {}).items()):
        if not isinstance(mapping, Mapping) or "worker" not in mapping:
            continue
        worker = mapping["worker"]
        container = "unknown"
        if engine is not None:
            try:
                container = _container_state(layout, worker, runner) or "absent"
            except EngineUnavailable:
                container = "unknown"
        identity = mapping.get("execution_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        workers.append({
            "issue": int(key),
            "worker": worker,
            "branch": mapping.get("branch"),
            "execution_branch": mapping.get("execution_branch", mapping.get("branch")),
            "execution_head": identity.get("head"),
            "recorded_state": mapping.get("state"),
            "container": container,
            "engine": mapping.get("engine"),
            "model": mapping.get("model"),
            "next_action": mapping.get("next_action"),
            "next_authorized_action": next_authorized_action(mapping),
            "takeover": _takeover_of(mapping).get("status"),
            "checkpoints": [c.get("ref") for c in mapping.get("checkpoints", []) if c.get("status") == "preserved"],
            "work": inspect_checkout(layout, worker, runner=runner),
        })
    return {
        "schema": SCHEMA,
        "epic": layout.epic,
        "epic_dir": str(layout.epic_dir),
        "engine_version": engine,
        "workers": workers,
        "authority": "coordination evidence only; GitHub Issues/PRs/CI win",
    }


# --------------------------------------------------------------------------- preservation and takeover
#
# Unique work (uncommitted edits, ignored-but-unique files, detached commits) is captured into
# ``refs/checkpoints/ckpt-NNNN`` of a controller-owned repo (``control/checkpoints/<worker>.git``), only
# after the worker container is proven absent. The worker checkout is mounted read-only and never
# written, and worker-planted configuration and filters cannot execute. Objects reachable from
# worker refs, all reflogs and linked-worktree HEADs are also retained in the controller repo.


def _checkpoint_repo(layout: Layout, worker: str) -> Path:
    repo = _controller_dir(layout, "checkpoints") / f"{validate_worker_id(worker)}.git"
    _make_gitdir(repo, None)
    return repo


def _checkpoint_index(repo: Path) -> Path:
    index = repo / "epic-checkpoint.index"
    if index.is_symlink():
        raise EpicWorkspaceError("checkpoint index path is a symlink; refusing")
    index.unlink(missing_ok=True)
    return index


def _checkpoint(
    layout: Layout, issue: int, worker: str, work: Mapping[str, Any], ignored_all: Sequence[str], *, reason: str, runner: Runner, image: str,
    force: bool = False,
) -> dict[str, Any] | None:
    if not work.get("present"):
        return None
    if not work.get("readable"):
        return None  # kept intact as unique work; takeover and retirement refuse on it
    marker = _retained_marker(work)
    if marker is None:
        raise EpicWorkspaceError("checkpoint retained evidence is incomplete; preserving checkout")
    _settle_checkpoint_writer(layout, worker, runner)
    if not work.get("unique_work") and not force:
        return None
    checkout = layout.checkout(worker)
    if (checkout / ".git" / "epic-checkpoint.index").is_symlink():
        raise EpicWorkspaceError("worker checkpoint index path is a symlink; refusing")
    repo = _checkpoint_repo(layout, worker)
    index = _checkpoint_index(repo)
    base_env = {
        "GIT_INDEX_FILE": f"{SCRATCH_TARGET}/{index.name}",
        "GIT_AUTHOR_NAME": "epic-workspace", "GIT_AUTHOR_EMAIL": "epic-workspace@localhost",
        "GIT_COMMITTER_NAME": "epic-workspace", "GIT_COMMITTER_EMAIL": "epic-workspace@localhost",
    }

    def git(*args: str, env: Mapping[str, str] | None = None, input_data: str | None = None) -> str:
        result = _contained_git(
            checkout, args, runner=runner, image=image, scratch=repo, env={**base_env, **(env or {})},
            timeout=GIT_WRITE_TIMEOUT, input_data=input_data, checkpoint_owner=(layout, worker),
        )
        if result.returncode != 0:
            raise EpicWorkspaceError(f"checkpoint step {args[0]} failed: {(result.stderr or '').strip()[:200]}")
        return (result.stdout or "").strip()

    head = work["head"]
    try:
        try:
            _raw_byte_preflight(checkout, repo, runner=runner, image=image, checkpoint_owner=(layout, worker))
            index_fingerprint = _copy_worker_index(checkout, repo, index)
        except (_Unreadable, OSError) as exc:
            raise EpicWorkspaceError(f"checkpoint index or raw-byte preflight unreadable: {exc}") from exc
        if index_fingerprint != work["index_fingerprint"]:
            raise EpicWorkspaceError("worker index changed while the checkpoint was taken")
        staged_tree = git("write-tree")
        if staged_tree != work["staged_tree"]:
            raise EpicWorkspaceError("worker index changed while the checkpoint was taken")
        _checkpoint_index(repo)
        git("read-tree", head)
        git("add", "-A", "--", ".")
        for offset in range(0, len(ignored_all), 100):
            git("add", "-f", "-A", "--", *ignored_all[offset:offset + 100], env={"GIT_LITERAL_PATHSPECS": "1"})
        tree = git("write-tree")
    finally:
        if not _load_state(layout)["issue_mappings"][str(issue)].get("checkpoint_inspection_unknown"):
            _checkpoint_index(repo)
    mapping = _load_state(layout)["issue_mappings"][str(issue)]
    recorded = {c.get("ref"): c for c in mapping.get("checkpoints", []) if isinstance(c, Mapping)}
    present: dict[str, tuple[str, str, str]] = {}
    staged_present: dict[str, tuple[str, str, str]] = {}
    for line in git("for-each-ref", "--format=%(refname)%00%(objectname)%00%(tree)%00%(parent)",
                    CHECKPOINT_REF_PREFIX.rstrip("/"), STAGED_REF_PREFIX.rstrip("/")).splitlines():
        parts = line.split("\0")
        if len(parts) != 4:
            raise EpicWorkspaceError("checkpoint ref is unreadable; preserving checkout")
        ref, commit, ref_tree, parents = parts
        parent_parts = parents.split()
        parent = parent_parts[0] if len(parent_parts) == 1 else ""
        (staged_present if ref.startswith(STAGED_REF_PREFIX) else present)[ref] = (commit, ref_tree, parent)
    # A ref already holding this exact checkpoint (an earlier attempt, or a crash between update-ref
    # and the run-state write) can be adopted only after its objects are made self-contained.
    record: dict[str, Any] | None = None
    already_recorded = False
    for ref, (commit, ref_tree, parent) in sorted(present.items()):
        staged_ref = STAGED_REF_PREFIX + ref.removeprefix(CHECKPOINT_REF_PREFIX)
        staged_data = staged_present.get(staged_ref)
        if ref_tree == tree and parent == head and staged_data and staged_data[1:] == (staged_tree, head):
            staged_commit = staged_data[0]
            prior = recorded.get(ref)
            if (prior and prior.get("status") == "preserved" and prior.get("commit") == commit
                    and prior.get("branch") == work["branch"]
                    and prior.get("refs_fingerprint") == work["refs_fingerprint"]
                    and prior.get("reflog_fingerprint") == work["reflog_fingerprint"]
                    and prior.get("reflog_content_fingerprint") == work["reflog_content_fingerprint"]
                    and prior.get("retained_reflog") == work["retained_reflog"]
                    and _retained_marker(prior) == marker
                    and prior.get("staged_ref") == staged_ref and prior.get("staged_commit") == staged_commit
                    and prior.get("staged_tree") == staged_tree):
                record = dict(prior)
                already_recorded = True
                break
            if (prior is None and git("show", "-s", "--format=%B", commit).splitlines()[-1:] == [marker]
                    and git("show", "-s", "--format=%B", staged_commit).splitlines()[-1:] == [marker]):
                record = {
                    "ref": ref, "commit": commit, "tree": tree, "head": head, "branch": work["branch"], "reason": reason, "at": _now(),
                    "staged_ref": staged_ref, "staged_commit": staged_commit, "staged_tree": staged_tree,
                    "uncommitted_count": work["uncommitted_count"], "ignored_count": work["ignored_count"], "status": "preserved", "adopted": True,
                }
                break
    if record is None:
        staged_names = (CHECKPOINT_REF_PREFIX + ref.removeprefix(STAGED_REF_PREFIX) for ref in staged_present)
        numbers = [int(m.group(1)) for ref in (*present, *recorded, *staged_names) if isinstance(ref, str) and (m := _CKPT_REF.match(ref))]
        ref = f"{CHECKPOINT_REF_PREFIX}ckpt-{(max(numbers) if numbers else 0) + 1:04d}"
        staged_ref = STAGED_REF_PREFIX + ref.removeprefix(CHECKPOINT_REF_PREFIX)
        commit = git("commit-tree", tree, "-p", head, "-m", f"epic-workspace checkpoint ({worker}): {reason[:120]}", "-m", marker)
        staged_commit = git("commit-tree", staged_tree, "-p", head, "-m", f"epic-workspace staged checkpoint ({worker}): {reason[:120]}", "-m", marker)
        git("update-ref", "--stdin", input_data=f"start\ncreate {ref} {commit}\ncreate {staged_ref} {staged_commit}\nprepare\ncommit\n")
        record = {
            "ref": ref, "commit": commit, "tree": tree, "head": head, "branch": work["branch"], "reason": reason, "at": _now(),
            "staged_ref": staged_ref, "staged_commit": staged_commit, "staged_tree": staged_tree,
            "uncommitted_count": work["uncommitted_count"], "ignored_count": work["ignored_count"], "status": "preserved",
        }

    retained = {head, *work["retained_heads"], *work["retained_stash"], *work["retained_reflog"]}
    retained.update(item["sha"] for item in work["retained_refs"])
    if len(retained) > MAX_RETAINED_REFS or any(not _OID.match(sha) for sha in retained):
        raise EpicWorkspaceError("too many or invalid retained objects; preserving checkout")
    existing_retained = dict(
        line.split(" ", 1) for line in git("for-each-ref", "--format=%(refname) %(objectname)", "refs/retained").splitlines()
    )
    create_refs: list[str] = []
    for sha in sorted(retained):
        ref = f"refs/retained/{sha}"
        if ref in existing_retained and existing_retained[ref] != sha:
            raise EpicWorkspaceError("retained ref collision; preserving checkout")
        if ref not in existing_retained:
            create_refs.append(f"create {ref} {sha}\n")
    if create_refs:
        git("update-ref", "--stdin", input_data="".join(create_refs))
    # Repack reachable objects from the read-only checkout into the controller-owned repo. A
    # subsequent connectivity check with alternates disabled proves the ref is independently
    # readable; interruption leaves the checkout intact and the next attempt can retry.
    git("repack", "-a", "-d")
    git("fsck", "--connectivity-only", "--no-reflogs", env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
    record.update(
        refs_fingerprint=work["refs_fingerprint"], retained_refs=work["retained_refs"],
        retained_heads=work["retained_heads"], retained_stash=work["retained_stash"],
        reflog_content_fingerprint=work["reflog_content_fingerprint"],
        reflog_fingerprint=work["reflog_fingerprint"], retained_reflog=work["retained_reflog"],
    )
    if not _checkpoint_present(checkout, repo, record, runner, image):
        raise EpicWorkspaceError(f"checkpoint {record['ref']} could not be read back")
    return record if already_recorded else _record_checkpoint(layout, issue, record)


def _record_checkpoint(layout: Layout, issue: int, record: dict[str, Any]) -> dict[str, Any]:
    def updater(state: dict[str, Any]) -> dict[str, Any]:
        entry = state["issue_mappings"][str(issue)]
        entry["checkpoints"] = [*entry.get("checkpoints", []), record]
        entry["updated_at"] = _now()
        return state

    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic)
    return record


def _checkpoint_present(checkout: Path, repo: Path, record: Mapping[str, Any], runner: Runner, image: str) -> bool:
    ref = record.get("ref")
    staged_ref = record.get("staged_ref")
    marker = _retained_marker(record)
    if (not isinstance(ref, str) or not _CKPT_REF.fullmatch(ref)
            or staged_ref != STAGED_REF_PREFIX + ref.removeprefix(CHECKPOINT_REF_PREFIX)
            or marker is None
            or any(not isinstance(record.get(k), str) or not _OID.fullmatch(record[k])
                   for k in ("head", "tree", "commit", "staged_tree", "staged_commit"))):
        return False
    groups = [record.get("retained_heads"), record.get("retained_stash"), record.get("retained_reflog")]
    refs = record.get("retained_refs")
    if (not all(isinstance(group, list) and all(isinstance(oid, str) and _OID.fullmatch(oid) for oid in group)
                for group in groups)
            or not isinstance(refs, list)
            or not all(isinstance(item, Mapping) and isinstance(item.get("ref"), str)
                       and isinstance(item.get("sha"), str) and _OID.fullmatch(item["sha"]) for item in refs)):
        return False
    retained = {record["head"], *(item["sha"] for item in refs)}
    for group in groups:
        if isinstance(group, list):
            retained.update(group)
    if len(retained) > MAX_RETAINED_REFS:
        return False

    def rev(spec: str) -> str | None:
        result = _contained_git(checkout, ["rev-parse", "--verify", "--quiet", spec], runner=runner, image=image, scratch=repo, scratch_readonly=True,
                                env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
        return (result.stdout or "").strip() if result.returncode == 0 else None

    present = (rev(f"{record['ref']}^{{tree}}") == record["tree"] and rev(f"{record['ref']}^{{commit}}") == record["commit"]
            and rev(f"{record['ref']}^1") == record["head"]
            and rev(f"{record['staged_ref']}^{{tree}}") == record["staged_tree"]
            and rev(f"{record['staged_ref']}^{{commit}}") == record["staged_commit"]
            and rev(f"{record['staged_ref']}^1") == record["head"])
    if not present:
        return False
    for commit in (record["commit"], record["staged_commit"]):
        message = _contained_git(checkout, ["show", "-s", "--format=%B", commit], runner=runner, image=image,
                                 scratch=repo, scratch_readonly=True, env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
        if message.returncode != 0 or (message.stdout or "").strip().splitlines()[-1:] != [marker]:
            return False
    result = _contained_git(checkout, ["for-each-ref", "--format=%(refname) %(objectname)", "refs/retained"],
                            runner=runner, image=image, scratch=repo, scratch_readonly=True,
                            env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
    if result.returncode != 0:
        return False
    lines = (result.stdout or "").splitlines()
    observed = {line for line in lines}
    if any(f"refs/retained/{sha} {sha}" not in observed for sha in retained):
        return False
    check = _contained_git(checkout, ["fsck", "--connectivity-only", "--no-reflogs"],
                           runner=runner, image=image, scratch=repo, scratch_readonly=True,
                           env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
    return check.returncode == 0


@_serialized_worker
def checkpoint_worker(layout: Layout, worker: str, *, reason: str, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE) -> dict[str, Any] | None:
    """Checkpoint a worker whose container is already proven absent; refuse otherwise."""

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    _assert_engine(runner)
    _settle_checkpoint_writer(layout, worker, runner)
    if state["issue_mappings"][str(issue)].get("state") in ("starting", "running"):
        raise EpicWorkspaceError("worker launch or execution is unresolved; run worker-stop before checkpoint")
    if _container_state(layout, worker, runner) is not None:
        raise EpicWorkspaceError("worker container is present; a checkpoint would compete with it. Stop it first")
    work, ignored_all = _inspect(layout, worker, runner=runner, image=image)
    if not work.get("readable"):
        raise EpicWorkspaceError("checkout is missing or unreadable; it is treated as unique work and cannot be checkpointed")
    return _checkpoint(layout, issue, worker, work, ignored_all, reason=reason, runner=runner, image=image)


@_serialized_worker
def release_checkpoint(
    layout: Layout, worker: str, *, ref: str, published_commit: str, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE
) -> dict[str, Any]:
    """Mark a checkpoint superseded once every path it captured is identical in a published commit.

    ``published_commit`` must itself be reachable from controller-held published evidence.
    """

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    record = next((c for c in mapping.get("checkpoints", []) if c.get("ref") == ref), None)
    if record is None or record.get("status") != "preserved":
        raise EpicWorkspaceError(f"no preserved checkpoint {ref!r} for worker {worker!r}")
    if not _OID.match(published_commit):
        raise EpicWorkspaceError("published commit must be a full object id")
    _assert_engine(runner)
    _settle_checkpoint_writer(layout, worker, runner)
    checkout = layout.checkout(worker)
    repo = _checkpoint_repo(layout, worker)
    if not all(isinstance(record.get(key), str) for key in ("staged_ref", "staged_commit", "staged_tree")):
        raise EpicWorkspaceError("checkpoint lacks staged-index evidence; preserving it")
    if not _valid_reflog_evidence(record):
        raise EpicWorkspaceError("checkpoint lacks complete reflog evidence; preserving it")
    if not _checkpoint_present(checkout, repo, record, runner, image):
        raise EpicWorkspaceError("checkpoint or retained object evidence is unreadable; preserving it")

    def read(*args: str, env: Mapping[str, str] | None = None) -> str:
        result = _contained_git(checkout, args, runner=runner, image=image, scratch=repo, scratch_readonly=True, env=env)
        if result.returncode != 0:
            raise EpicWorkspaceError(f"cannot verify release: {args[0]} failed")
        return result.stdout or ""

    try:
        tips = _published_tips(layout, worker)
    except (_Unreadable, OSError, UnicodeError, epic_run_state.EpicRunStateError) as exc:
        raise EpicWorkspaceError("cannot verify release: published evidence is unreadable") from exc
    existing = [sha for sha in read("rev-list", "--no-walk", "--ignore-missing", *tips).split() if _OID.match(sha)] if tips else []
    if not existing or int(read("rev-list", "--count", published_commit, "--not", *existing).strip() or 1) != 0:
        raise EpicWorkspaceError("commit is not reachable from controller-held published evidence; not published")
    retained = {record["head"], *record["retained_heads"], *record["retained_stash"], *record["retained_reflog"]}
    retained.update(item["sha"] for item in record.get("retained_refs", []))
    if not all(isinstance(sha, str) and _OID.match(sha) for sha in retained):
        raise EpicWorkspaceError("checkpoint retained object evidence is malformed")
    if int(read("rev-list", "--count", *sorted(retained), "--not", *existing).strip() or 1) != 0:
        raise EpicWorkspaceError("checkpoint contains retained commits not published by the coordinator")
    for captured in (record["commit"], record["staged_commit"]):
        paths = [p for p in read("diff", "--no-renames", "--name-only", "-z", record["head"], captured).split("\0") if p]
        for offset in range(0, len(paths), 100):
            differing = read("diff", "--no-renames", "--name-only", "-z", captured, published_commit, "--",
                             *paths[offset:offset + 100], env={"GIT_LITERAL_PATHSPECS": "1"}).split("\0")
            differing = [p for p in differing if p]
            if differing:
                raise EpicWorkspaceError(f"checkpoint content not in the published commit: {differing[:5]}")

    def updater(current: dict[str, Any]) -> dict[str, Any]:
        entry = current["issue_mappings"][str(issue)]
        if not any(c == record and c.get("status") == "preserved" for c in entry.get("checkpoints", []) if isinstance(c, Mapping)):
            raise EpicWorkspaceError("checkpoint changed during release; preserving it")
        entry["checkpoints"] = [
            {**c, "status": "released", "released_at": _now(), "released_by": published_commit} if c.get("ref") == ref else c
            for c in entry.get("checkpoints", [])
        ]
        return current

    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic)
    return {**record, "status": "released", "released_by": published_commit}


# ---- publication operations: intent is recorded before the external effect, so an unknown
# outcome is reconciled by branch/PR readback and never replayed.


def _mutate_mapping(layout: Layout, worker: str, mutate: Callable[[dict[str, Any]], Any]) -> Any:
    issue = _issue_for_worker(_load_state(layout), worker)
    box: list[Any] = []

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        entry = state["issue_mappings"][str(issue)]
        if entry.get("worker") != worker:
            raise EpicWorkspaceError(f"issue #{issue} no longer belongs to worker {worker!r}")
        box.append(mutate(entry))
        entry["updated_at"] = _now()
        return state

    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic)
    return box[0]


@_serialized_worker
def begin_publication(layout: Layout, worker: str, *, kind: str, expect_sha: str | None = None) -> dict[str, Any]:
    """Record the intent to publish the worker's branch. Refused while an earlier attempt is unresolved."""

    if kind not in PUBLICATION_KINDS:
        raise EpicWorkspaceError(f"unknown publication kind {kind!r}")
    if kind == "branch_push" and expect_sha is None:
        raise EpicWorkspaceError("branch_push requires expect_sha before the effect")
    if expect_sha is not None and (not isinstance(expect_sha, str) or not _OID.fullmatch(expect_sha)):
        raise EpicWorkspaceError("expect_sha must be a full object id")

    def mutate(entry: dict[str, Any]) -> dict[str, Any]:
        if entry.get("state") == "retired" or not entry.get("branch"):
            raise EpicWorkspaceError("worker has no active branch to publish")
        if entry.get("checkpoint_inspection_unknown"):
            raise TakeoverRefused("checkpoint inspection cleanup is unknown; settle it before starting publication")
        if entry.get("state") == "starting":
            raise TakeoverRefused("worker launch is unresolved; settle it before starting publication")
        ops = list(entry.get("publication_ops", []))
        same = [op for op in ops if op["kind"] == kind and op["branch"] == entry["branch"]]
        for op in same:
            if op["status"] in _OP_UNRESOLVED:
                raise EpicWorkspaceError(f"{kind} {op['id']} is {op['status']}; reconcile it by readback, do not replay")
            if op["status"] == "confirmed":
                confirmed_sha = (op.get("result") or {}).get("sha")
                if (kind != "branch_push" or expect_sha is None or not isinstance(confirmed_sha, str)
                        or not _OID.match(confirmed_sha) or confirmed_sha == expect_sha):
                    raise EpicWorkspaceError(f"{kind} {op['id']} is already confirmed")
            elif op["status"] not in _OP_UNRESOLVED:
                raise EpicWorkspaceError(f"{kind} {op['id']} has an unrecognized outcome; preserve it")
        op = {"id": f"{kind}-{len(ops) + 1}", "kind": kind, "branch": entry["branch"], "expect_sha": expect_sha, "status": "intended", "intent_at": _now()}
        entry["publication_ops"] = [*ops, op]
        return op

    return _mutate_mapping(layout, worker, mutate)


def _find_op(entry: Mapping[str, Any], op_id: str) -> dict[str, Any]:
    for op in entry.get("publication_ops", []):
        if op["id"] == op_id:
            return op
    raise EpicWorkspaceError(f"unknown publication operation {op_id!r}")


def complete_publication(layout: Layout, worker: str, *, op_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Record a positively observed outcome of an ``intended`` operation."""

    def mutate(entry: dict[str, Any]) -> dict[str, Any]:
        op = _find_op(entry, op_id)
        sha = result.get("sha")
        if not isinstance(sha, str) or not _OID.match(sha):
            raise EpicWorkspaceError("result sha must be a full object id")
        if result.get("branch") != op["branch"] or op.get("expect_sha") not in (None, sha):
            raise EpicWorkspaceError("publication readback does not match the intended branch and head")
        if op["kind"] == "pr_create" and (
            type(result.get("number")) is not int or result["number"] <= 0
        ):
            raise EpicWorkspaceError("pull request readback must include its positive number")
        if op["status"] == "confirmed":
            if op.get("result") != _publication_result(result):
                raise EpicWorkspaceError(f"{op_id} is already confirmed with a different result")
            return dict(op)
        if op["status"] not in _OP_UNRESOLVED:
            raise EpicWorkspaceError(f"{op_id} is {op['status']}, not unresolved")
        op.update(status="confirmed", confirmed_at=_now(), result=_publication_result(result))
        op.pop("reason", None)
        _record_published_head(entry, op)
        return dict(op)

    return _mutate_mapping(layout, worker, mutate)


def _publication_result(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"number": int, "url": str, "sha": str, "state": str, "branch": str}
    result = {k: value[k] for k, t in allowed.items() if isinstance(value.get(k), t) and not isinstance(value.get(k), bool)}
    if "sha" in result and not _OID.match(result["sha"]):
        del result["sha"]
    return result


def _record_published_head(entry: dict[str, Any], op: Mapping[str, Any]) -> None:
    """Remember the commit GitHub readback showed on the remote branch or PR head.

    This is the only worker-independent evidence that commits are published: squash merges leave
    worker commits out of main, so the exact head the coordinator observed is what counts.
    """

    sha = (op.get("result") or {}).get("sha")
    if not isinstance(sha, str) or not _OID.match(sha):
        return
    heads = list(entry.get("published_heads", []))
    if sha not in [h.get("sha") for h in heads if isinstance(h, Mapping)]:
        heads.append({"sha": sha, "op": op["id"], "kind": op["kind"], "at": _now()})
    entry["published_heads"] = heads


def _judge_readback(op: Mapping[str, Any], readback: Mapping[str, Any] | None) -> tuple[str, dict[str, Any], str | None]:
    """(status, result, reason) from coordinator-supplied GitHub readback. Anything unclear is quarantine."""

    if not isinstance(readback, Mapping) or readback.get("complete") is not True:
        return "quarantined", {}, "readback missing or incomplete"
    if op["kind"] == "branch_push":
        branch = readback.get("branch")
        if not isinstance(branch, Mapping) or not isinstance(branch.get("exists"), bool):
            return "quarantined", {}, "branch readback malformed"
        if branch.get("name") != op["branch"]:
            return "quarantined", {}, "branch readback does not identify the intended branch"
        if not branch["exists"]:
            return "quarantined", {}, "branch absence does not settle a possibly in-flight push"
        sha = branch.get("sha")
        if not isinstance(sha, str) or not _OID.match(sha):
            return "quarantined", {}, "branch sha missing or malformed"
        if op.get("expect_sha") == sha:
            return "confirmed", {"sha": sha, "branch": op["branch"]}, None
        return "quarantined", {"sha": sha}, "remote branch differs from the intended commit"
    prs = readback.get("pull_requests")
    if readback.get("branch") != op["branch"]:
        return "quarantined", {}, "pull request readback does not identify the intended branch"
    if not isinstance(prs, list) or not all(isinstance(pr, Mapping) for pr in prs):
        return "quarantined", {}, "pull request readback malformed"
    if not prs:
        return "quarantined", {}, "empty PR readback does not settle a possibly in-flight create"
    if len(prs) == 1:
        pr = prs[0]
        sha = pr.get("sha")
        if (type(pr.get("number")) is not int or pr["number"] <= 0 or pr.get("branch") != op["branch"]
                or not isinstance(sha, str) or not _OID.match(sha)
                or op.get("expect_sha") not in (None, sha)):
            return "quarantined", {}, "pull request readback does not establish the intended branch and head"
        return "confirmed", _publication_result(pr), None
    return "quarantined", {}, "several pull requests exist for the branch"


def reconcile_publication(layout: Layout, worker: str, *, op_id: str, readback: Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve an unresolved operation from readback. Only that operation is quarantined on doubt."""

    def mutate(entry: dict[str, Any]) -> dict[str, Any]:
        op = _find_op(entry, op_id)
        if op["status"] not in _OP_UNRESOLVED:
            return dict(op)
        status, result, reason = _judge_readback(op, readback)
        if status == "confirmed" and op["kind"] == "pr_create" and any(
            other.get("id") != op_id and other.get("kind") == "pr_create"
            and other.get("branch") == op["branch"] and other.get("status") in (*_OP_UNRESOLVED, "confirmed")
            for other in entry.get("publication_ops", []) if isinstance(other, Mapping)
        ):
            # A legacy retry can make a matching PR attributable to either request.
            # Preserve both until operation-specific evidence settles each one.
            status, result, reason = "quarantined", {}, "matching PR cannot distinguish multiple create attempts"
        op.update(status=status, reconciled_at=_now(), result=result)
        op.pop("reason", None)
        if reason:
            op["reason"] = reason
        if status == "confirmed":
            _record_published_head(entry, op)
        return dict(op)

    return _mutate_mapping(layout, worker, mutate)


# ---- next authorized action and takeover


def next_authorized_action(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Derive what may happen next from one run-state mapping alone."""

    ops = [op for op in mapping.get("publication_ops", []) if isinstance(op, Mapping)]
    blocked = [{"id": op["id"], "kind": op["kind"], "status": op["status"], "reason": op.get("reason")} for op in ops if op["status"] in _OP_UNRESOLVED]
    # This controller has no authenticated no-effect settlement receipt. In particular,
    # legacy absent_confirmed records came from a point-in-time readback, not settlement.
    retry: list[str] = []
    takeover = _takeover_of(mapping)
    if mapping.get("state") == "retired":
        action = "none: worker retired"
    elif mapping.get("checkpoint_inspection_unknown"):
        marker = mapping["checkpoint_inspection_unknown"]
        action = ("run worker-stop or takeover to settle the unknown checkpoint inspection before continuation"
                  if isinstance(marker, Mapping) and marker.get("protocol") == LAUNCH_PROTOCOL else
                  "preserve the legacy checkpoint hold; its old writer has no ID-bound stop proof")
    elif mapping.get("state") == "starting":
        action = ("preserve the legacy launch hold; its old request has no ID-bound stop proof"
                  if not mapping.get("container_id") and mapping.get("launch_protocol") != LAUNCH_PROTOCOL else
                  "run worker-stop or takeover to settle the unknown worker launch before continuation")
    elif takeover.get("status") == "required":
        action = "run takeover: reconcile files and publication before any successor writes"
    elif takeover.get("status") == "authorized":
        try:
            _authorization_record(mapping)
        except EpicWorkspaceError:
            action = "run takeover: reconcile the incomplete authorized checkout identity before any successor writes"
        else:
            action = f"start exactly one continuation (generation {takeover.get('generation')}): {mapping.get('next_action')}"
    else:
        action = str(mapping.get("next_action"))
    return {"action": action, "recorded_next_action": mapping.get("next_action"), "blocked_operations": blocked, "retry_authorized": retry}


def continuation_brief(layout: Layout, worker: str) -> dict[str, Any]:
    """Rebuild a successor's briefing from durable records only; the predecessor writes nothing."""

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    action = next_authorized_action(mapping)
    checkpoints = [
        {k: c.get(k) for k in ("ref", "commit", "status", "uncommitted_count", "ignored_count", "at")}
        for c in mapping.get("checkpoints", []) if c.get("status") == "preserved"
    ]
    conversations = [*mapping.get("conversation_history", []), *([mapping["conversation"]] if isinstance(mapping.get("conversation"), Mapping) else [])]
    identity = mapping.get("execution_identity")
    observed = mapping.get("work_at_stop")
    identity = identity if isinstance(identity, Mapping) else {}
    observed = observed if isinstance(observed, Mapping) else {}
    brief: dict[str, Any] = {
        "schema": "epic_continuation_brief.v1",
        "epic": layout.epic, "issue": issue, "worker": worker, "branch": mapping.get("branch"),
        "execution_branch": mapping.get("execution_branch", mapping.get("branch")),
        "execution_head": identity.get("head"),
        "observed_checkout": {k: observed.get(k) for k in ("readable", "branch", "head")},
        "generation": _takeover_of(mapping).get("generation"),
        "next_authorized_action": action,
        "checkpoints": checkpoints,
        "publication_operations": [
            {k: op.get(k) for k in ("id", "kind", "status", "result", "reason")} for op in mapping.get("publication_ops", [])
        ],
        "predecessors": [{k: c.get(k) for k in ("id", "engine", "model", "status")} for c in conversations],
    }
    brief["prompt"] = _render_continuation_prompt(brief)
    return brief


def _render_continuation_prompt(brief: Mapping[str, Any]) -> str:
    action = brief["next_authorized_action"]
    execution = (f"detached HEAD `{brief['execution_head']}`" if brief["execution_branch"] is None
                 else f"execution branch `{brief['execution_branch']}`")
    lines = [
        f"You are continuing GitHub Issue #{brief['issue']} (epic #{brief['epic']}) on {execution} in /workspace.",
        f"The parent publisher/claim branch is `{brief['branch']}`; branch reconciliation does not grant publication authority.",
        "A previous worker was replaced. Do not rely on any summary from it: its work is in this checkout.",
        "First run `git status`, `git branch -a`, `git stash list` and `git log --oneline -5`; uncommitted and ignored files are real work, keep them.",
        f"Next authorized action: {action['action']}",
    ]
    if brief["checkpoints"]:
        lines.append("Controller-held safety checkpoints of the predecessor's uncommitted and ignored files (the files themselves are still in this checkout): " + ", ".join(c["ref"] for c in brief["checkpoints"]))
    if action["blocked_operations"]:
        lines.append("Do NOT attempt these publication operations; their outcome is unknown and only the coordinator reconciles them: " + ", ".join(f"{b['kind']} ({b['id']})" for b in action["blocked_operations"]))
    lines.append("You have no GitHub credentials: never push or open pull requests; commit locally and record the state in `.codex-tmp/epic-continuation.md`.")
    return "\n".join(lines)


@_serialized_worker
def takeover(
    layout: Layout,
    worker: str,
    *,
    reason: str,
    readbacks: Mapping[str, Mapping[str, Any]] | None = None,
    runner: Runner = subprocess.run,
    image: str = DEFAULT_IMAGE,
) -> dict[str, Any]:
    """Permit exactly one continuation after the predecessor is proven gone and its effects reconciled.

    Order: (1) container removed and absence read back from the engine (a lease or timeout proves
    nothing), (2) files checkpointed and branch identity confirmed, (3) every unresolved publication
    attempt reconciled from coordinator-supplied readback, quarantining only the ones that stay
    unclear, (4) one continuation recorded under the run-state lock.
    """

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    if mapping.get("state") == "retired":
        raise TakeoverRefused("worker is retired")
    recorded = mapping.get("branch")
    previous_execution = mapping.get("execution_branch", recorded)
    generation = int(_takeover_of(mapping).get("generation", 0))
    prior_identity = mapping.get("execution_identity")
    detached_previously_bound = False
    if previous_execution is None and isinstance(prior_identity, Mapping):
        try:
            detached_previously_bound = (
                _checkout_identity({**prior_identity, "present": True, "readable": True})["branch"] is None
                and isinstance(prior_identity.get("checkpoint_ref"), str)
            )
        except TakeoverRefused:
            pass
    if (not isinstance(recorded, str) or not (isinstance(previous_execution, str) or detached_previously_bound)
            or mapping.get("checkout") != str(layout.checkout(worker))):
        raise TakeoverRefused("worker mapping scope or branch is unreadable; preserving checkout")
    _settle_checkpoint_writer(layout, worker, runner)
    if _takeover_of(mapping).get("status") == "authorized":
        try:
            _check_authorized_checkout(layout, worker, mapping, runner=runner, image=image)
        except EpicWorkspaceError:
            _fence_authorization(layout, worker, generation)
        else:
            return {**continuation_brief(layout, worker), "already_authorized": True}
    stopped = _stop_worker(layout, worker, reason=f"takeover: {reason}", runner=runner, image=image)
    stop_id = stopped.get("stop_id")

    def require_reconciliation(entry: dict[str, Any]) -> None:
        if entry.get("stop_id") != stop_id or entry.get("state") != "stopped_verified":
            raise TakeoverRefused("worker state changed after the stop was verified")
        prior = _takeover_of(entry)
        entry["takeover"] = {
            "status": "required", "generation": int(prior.get("generation", 0)),
            "reason": reason, "at": _now(),
        }

    # Any later failed validation must leave the start gate closed, even if the first
    # inspection happened to report a clean checkout.
    _mutate_mapping(layout, worker, require_reconciliation)
    # Authorize only from evidence read after the checkpoint, never from the pre-checkpoint view.
    after, _ignored = _inspect(layout, worker, runner=runner, image=image)
    if not after.get("present") or not after.get("readable"):
        raise TakeoverRefused("checkout evidence is missing or unreadable; treated as unique work, no continuation permitted")
    if after.get("head") != stopped.get("head"):
        raise TakeoverRefused("checkout HEAD moved while the checkpoint was taken; no continuation permitted")
    if any(after.get(key) != stopped.get(key) for key in _IDENTITY_FIELDS):
        raise TakeoverRefused("checkout content or refs changed while the checkpoint was taken; no continuation permitted")
    checkpoint = stopped.get("checkpoint")
    if checkpoint is not None and checkpoint.get("tree") != after.get("snapshot_tree"):
        raise TakeoverRefused("checkpoint does not match the post-checkpoint checkout; no continuation permitted")
    if checkpoint is not None and checkpoint.get("staged_tree") != after.get("staged_tree"):
        raise TakeoverRefused("checkpoint does not match the post-checkpoint index; no continuation permitted")
    if checkpoint is not None and (
        checkpoint.get("reflog_fingerprint") != after.get("reflog_fingerprint")
        or checkpoint.get("retained_reflog") != after.get("retained_reflog")
        or not _valid_reflog_evidence(checkpoint)
    ):
        raise TakeoverRefused("checkpoint does not match the post-checkpoint reflogs; no continuation permitted")
    actual = after.get("branch")
    identity = _checkout_identity(after)
    if (actual is None or actual != previous_execution) and checkpoint is None:
        raise TakeoverRefused("detached checkout or branch drift lacks a retained checkpoint; preserve checkout")
    for op in list(_load_state(layout)["issue_mappings"][str(issue)].get("publication_ops", [])):
        if op["status"] in _OP_UNRESOLVED:
            reconcile_publication(layout, worker, op_id=op["id"], readback=(readbacks or {}).get(op["id"]))
    # The engine is read again immediately before authorizing: a container that appeared since the
    # stop was verified is a competing writer.
    def mutate(entry: dict[str, Any]) -> None:
        if entry.get("stop_id") != stop_id or entry.get("state") != "stopped_verified":
            raise TakeoverRefused("worker state changed after the stop was verified (a start raced the takeover)")
        if (entry.get("branch") != recorded or entry.get("execution_branch", recorded) != previous_execution
                or entry.get("checkout") != str(layout.checkout(worker))
                or int(_takeover_of(entry).get("generation", 0)) != generation):
            raise TakeoverRefused("worker scope, branch mapping or generation changed during takeover")
        observed = entry.get("work_at_stop")
        if not isinstance(observed, Mapping) or any(
            observed.get(key) != after.get(key)
            for key in _IDENTITY_FIELDS
        ):
            raise TakeoverRefused("recorded checkout evidence changed during takeover")
        if checkpoint is not None and not any(
            c == checkpoint and c.get("status") == "preserved"
            for c in entry.get("checkpoints", []) if isinstance(c, Mapping)
        ):
            raise TakeoverRefused("retained checkpoint changed during takeover")
        _assert_engine(runner)
        present = _container_state(layout, worker, runner)
        if present is not None:
            raise TakeoverRefused(f"worker container is present ({present}); not authorizing a continuation beside it")
        latest, _ = _inspect(layout, worker, runner=runner, image=image)
        if _checkout_identity(latest) != identity:
            raise TakeoverRefused("checkout changed after checkpoint reconciliation; no continuation permitted")
        if checkpoint is not None and not _checkpoint_present(layout.checkout(worker), _checkpoint_repo(layout, worker), checkpoint, runner, image):
            raise TakeoverRefused("retained checkpoint is unreadable before authorization")
        prior = _takeover_of(entry)
        if prior.get("status") == "authorized":
            raise TakeoverRefused("another continuation is already authorized")
        entry["execution_branch"] = actual
        entry["execution_identity"] = {**identity, "checkpoint_ref": checkpoint["ref"] if checkpoint is not None else None}
        entry["takeover"] = {
            "status": "authorized", "generation": int(prior.get("generation", 0)) + 1, "reason": reason,
            "authorized_at": _now(), "checkpoints": [c["ref"] for c in entry.get("checkpoints", []) if c.get("status") == "preserved"],
            "execution_branch": actual, "previous_execution_branch": previous_execution,
            "publisher_branch": recorded, "head": after["head"],
        }
        _authorization_record(entry)

    _mutate_mapping(layout, worker, mutate)
    return {**continuation_brief(layout, worker), "already_authorized": False}


@_serialized_worker
def retire_worker(layout: Layout, worker: str, *, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE) -> dict[str, Any]:
    """Remove this worker's container and, only when nothing unique remains, its checkout.

    Only the container carrying this epic/worker label pair is touched; other containers and
    services are never listed for removal. Unique work, unreadable evidence, unreleased
    checkpoints and unresolved publication attempts all refuse the checkout removal.
    """

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    work = _stop_worker(layout, worker, reason="retirement", runner=runner, image=image, retain_identity=False)
    entry = _load_state(layout)["issue_mappings"][str(issue)]
    reasons = []
    if not work.get("present"):
        reasons.append("checkout evidence is missing")
    else:
        if not work.get("readable"):
            reasons.append("checkout evidence is unreadable")
        elif work.get("unique_work"):
            reasons.append("checkout holds unique work (uncommitted, ignored, or unpublished commits/reflogs)")
        if work.get("readable") and work.get("linked_worktrees"):
            reasons.append("linked checkouts share Git metadata and cannot be inspected for retirement")
    checkpoints = entry.get("checkpoints", [])
    if not isinstance(checkpoints, list) or any(not isinstance(c, Mapping) for c in checkpoints):
        reasons.append("checkpoint records are unreadable")
        checkpoints = []
    if any(c.get("status") == "preserved" for c in checkpoints):
        reasons.append("unreleased checkpoints exist")
    if any(c.get("status") not in ("preserved", "released") or not _valid_reflog_evidence(c) for c in checkpoints):
        reasons.append("checkpoint reflog coverage is unknown")
    if not reasons and any(
        not _checkpoint_present(layout.checkout(worker), _checkpoint_repo(layout, worker), c, runner, image)
        for c in checkpoints if c.get("status") == "released"
    ):
        reasons.append("released checkpoint evidence is unreadable")
    checkpoint_path = layout.epic_dir / "control" / "checkpoints" / f"{validate_worker_id(worker)}.git"
    if not reasons and (checkpoint_path.exists() or checkpoint_path.is_symlink()):
        repo = _checkpoint_repo(layout, worker)
        refs = _contained_git(layout.checkout(worker), ["for-each-ref", "--format=%(refname)",
                              CHECKPOINT_REF_PREFIX.rstrip("/"), STAGED_REF_PREFIX.rstrip("/")],
                              runner=runner, image=image, scratch=repo, scratch_readonly=True,
                              env={"GIT_ALTERNATE_OBJECT_DIRECTORIES": ""})
        known = {c.get(key) for c in checkpoints for key in ("ref", "staged_ref")}
        if refs.returncode != 0 or any(ref not in known for ref in (refs.stdout or "").splitlines()):
            reasons.append("unrecorded checkpoint refs require reconciliation")
    if any(op.get("status") in _OP_UNRESOLVED for op in entry.get("publication_ops", [])):
        reasons.append("a publication attempt is unresolved")
    if entry.get("checkpoint_inspection_unknown"):
        reasons.append("checkpoint inspection cleanup is unknown")
    if not reasons and work.get("present"):
        # Refuse if the checkout changed after the stop's inspection, even when the new
        # state happens to have the same path counts. The lifecycle lock fences our own starts.
        after, _ = _inspect(layout, worker, runner=runner, image=image)
        if (
            not after.get("readable") or after.get("unique_work")
            or any(after.get(key) != work.get(key) for key in _IDENTITY_FIELDS)
        ):
            reasons.append("checkout changed or became unreadable after the stop")
        _assert_engine(runner)
        if _container_state(layout, worker, runner) is not None:
            reasons.append("worker container reappeared after the stop")
    if reasons:
        def record_refusal(current: dict[str, Any]) -> None:
            current["retirement_refused"] = {"at": _now(), "reasons": reasons}
            if any("changed or became unreadable" in reason or "reappeared" in reason for reason in reasons):
                current["takeover"] = {
                    "status": "required", "generation": int(_takeover_of(current).get("generation", 0)),
                    "reason": "retirement evidence changed", "at": _now(),
                }

        _mutate_mapping(layout, worker, record_refusal)
        raise UniqueWorkPresent("; ".join(reasons) + "; container removed, checkout kept")
    checkout = layout.checkout(worker)
    removed = False
    if work.get("present"):
        if checkout.is_symlink() or not _is_within(checkout, layout.workers):
            raise EpicWorkspaceError("checkout path is not inside the workers directory; refusing to remove")
        try:
            shutil.rmtree(checkout)
        except OSError as exc:
            raise EpicWorkspaceError(f"could not remove checkout: {exc}") from exc
        removed = True
    _record_worker(layout, issue, state="retired", retired_at=_now(), checkout_removed=removed)
    return {"worker": worker, "container_removed": True, "checkout_removed": removed}


# --------------------------------------------------------------------------- OpenHands runtime
#
# The worker container runs the upstream OpenHands agent-server. Conversations, events, ACP
# engine processes and model selection are upstream facilities; this controller adds only the
# epic seams: workspace/isolation, a loopback port and session key per worker, issue/conversation
# association in run-state, and reconciliation of an unknown create outcome.

def _http(method: str, port: int, key: str, path: str, body: Mapping[str, Any] | None, timeout: float) -> tuple[int, Any]:
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
            return None

    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/api{path}", data=data, method=method,
        headers={"X-Session-API-Key": key, "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("agent-server response exceeds size bound")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _control_dir(layout: Layout) -> Path:
    path = layout.epic_dir / "control"
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def _session_key_file(layout: Layout, worker: str) -> Path:
    """Per-worker agent-server key, kept in a controller-only directory (never mounted)."""

    import secrets

    path = _control_dir(layout) / f"{validate_worker_id(worker)}.key"
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"OH_SESSION_API_KEYS_0={secrets.token_urlsafe(32)}\n")
    return path


def _session_key(layout: Layout, worker: str) -> str:
    line = _session_key_file(layout, worker).read_text().strip()
    return line.split("=", 1)[1]


def _allocate_port(runner: Runner) -> int:
    import socket

    try:
        used = runner(["docker", "ps", "--format", "{{.Ports}}"], capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EngineUnavailable("cannot read published ports") from exc
    if used.returncode != 0:
        raise EngineUnavailable("cannot read published ports")
    taken = set(int(m) for m in re.findall(r"127\.0\.0\.1:(\d+)->", used.stdout or ""))
    for port in OPENHANDS_PORT_RANGE:
        if port in taken:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise LaunchRefused("no free sandbox port")


def _validate_codex_home(path: Path | None, layout: Layout, runner: Runner) -> list[tuple[str, str]]:
    """The Terra reserve's single ChatGPT login directory. One mounting worker at a time, because
    refresh tokens rotate and divergent copies would invalidate each other."""

    if path is None:
        return []
    home = Path(path).expanduser()
    if not home.is_dir() or home.is_symlink() or _is_within(home, layout.root):
        raise LaunchRefused("codex home must be an existing directory outside the workspace root")
    if stat.S_IMODE(home.stat().st_mode) & 0o077:
        raise LaunchRefused("codex home must not be group/world accessible")
    try:
        busy = runner(["docker", "ps", "--all", "--filter", "label=epic-workspace.codex-home=1", "--format", "{{.Names}}"],
                      capture_output=True, text=True, check=False, timeout=ENGINE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise EngineUnavailable("cannot read codex-home usage") from exc
    if busy.returncode != 0 or (busy.stdout or "").strip():
        raise LaunchRefused("codex home is already mounted by another running worker (or unknown)")
    return [(str(home.resolve()), CODEX_HOME_TARGET)]


@_serialized_worker
@_serialized_openhands_start
def start_openhands_worker(
    layout: Layout,
    worker: str,
    *,
    budget: Budget = Budget(cpus="1.0", memory="1536m", pids=512),
    claude_env_file: Path | None = None,
    codex_home: Path | None = None,
    image: str = OPENHANDS_IMAGE,
    network: str = DEFAULT_NETWORK,
    runner: Runner = subprocess.run,
    http: Callable[..., tuple[int, Any]] = _http,
    ready_timeout: float = 90.0,
) -> dict[str, Any]:
    """Start the worker's OpenHands agent-server container and wait for authenticated readiness."""

    import time

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    _assert_no_pending_takeover(state["issue_mappings"][str(issue)])
    credential_env = _validate_env_file(claude_env_file, layout)
    _assert_engine(runner)
    if _container_state(layout, worker, runner) is not None:
        raise LaunchRefused(f"container for worker {worker!r} already exists; stop it before a successor starts")
    preflight = _preflight_start(layout, worker, state["issue_mappings"][str(issue)], runner=runner, image=DEFAULT_IMAGE)
    codex_mounts = _validate_codex_home(codex_home, layout, runner)
    key_file = _session_key_file(layout, worker)
    port = _allocate_port(runner)
    env = {
        "HOME": CONTAINER_HOME,
        "OH_ENABLE_VSCODE": "false",
        "OH_CONVERSATIONS_PATH": f"{CONTAINER_HOME}/openhands/conversations",
        "OH_BASH_EVENTS_DIR": f"{CONTAINER_HOME}/openhands/bash_events",
        "OH_WORKSPACE_PATH": CONTAINER_WORKSPACE,
    }
    if codex_mounts:
        env["CODEX_HOME"] = CODEX_HOME_TARGET
    argv = build_launch_argv(
        layout, worker, image=image, command=[], budget=budget, env_file=credential_env,
        extra_env_files=[key_file], env=env, publish_port=port, credential_mounts=codex_mounts,
        network=network, tmpfs_exec=True,
    )
    if codex_mounts:
        argv[argv.index("--label"):argv.index("--label")] = ["--label", "epic-workspace.codex-home=1"]
    _begin_start(
        layout, issue, worker, preflight=preflight, runner=runner, inspection_image=DEFAULT_IMAGE,
        runtime="openhands", container=layout.container_name(worker), image=image, port=port,
        budget={"cpus": budget.cpus, "memory": budget.memory, "pids": budget.pids}, network=network,
        credentials={"claude": "oauth-token-env" if credential_env else None, "codex": "chatgpt-login-dir" if codex_mounts else None},
        started_at=_now(),
    )
    _record_worker(layout, issue, container_id=_launch(layout, issue, worker, argv, runner))
    key = _session_key(layout, worker)
    deadline = time.monotonic() + ready_timeout
    while True:
        try:
            code, _ = http("GET", port, key, "/conversations/search?limit=1", None, 5.0)
        except OSError:
            code = 0
        if code == 200:
            break
        if time.monotonic() >= deadline:
            raise EpicWorkspaceError("agent-server did not become ready; inspect container")
        time.sleep(1.0)
    _record_worker(layout, issue, state="running")
    return {"port": port, "container": layout.container_name(worker), "image": image}


def resolve_engine(engine: str, model: str | None) -> tuple[str, str]:
    """Owner-selectable engine/model under the epic policy. Never Astra, never paid API."""

    if engine not in ENGINE_DEFAULT_MODELS:
        raise LaunchRefused(f"unsupported engine {engine!r}; use claude-code or codex")
    chosen = model or ENGINE_DEFAULT_MODELS[engine]
    if "astra" in chosen.lower() or not _ENGINE_MODEL[engine].match(chosen):
        raise LaunchRefused(f"model {chosen!r} is not permitted for engine {engine!r}")
    return engine, chosen


CONVERSATION_ENDED = "ended_with_container"


def _reserve_conversation(layout: Layout, issue: int, worker: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically admit one writer: refuse while any earlier conversation could still write."""

    key = str(int(issue))

    def updater(state: dict[str, Any]) -> dict[str, Any]:
        mapping = dict(state.get("issue_mappings", {}).get(key, {}))
        if mapping.get("worker") != worker or mapping.get("runtime") != "openhands" or mapping.get("state") != "running":
            raise LaunchRefused("worker has no running OpenHands agent-server")
        prior = mapping.get("conversation")
        if isinstance(prior, Mapping) and prior.get("status") != CONVERSATION_ENDED:
            raise LaunchRefused(
                f"conversation {prior.get('id')} is {prior.get('status')!r} and could still write; "
                "continue it, or stop the worker (verified) before a successor conversation starts"
            )
        _assert_no_pending_takeover(mapping)
        pending = _takeover_of(mapping)
        if pending.get("status") == "authorized":
            # Normally consumed when the worker started; a continuation still pending is spent here.
            mapping["takeover"] = {**pending, "status": "consumed", "conversation_id": record["id"], "consumed_at": _now()}
        elif pending.get("status") == "consumed" and not pending.get("conversation_id"):
            mapping["takeover"] = {**pending, "conversation_id": record["id"]}
        history = list(mapping.get("conversation_history", []))
        if isinstance(prior, Mapping):
            history.append(dict(prior))
        mapping.update(conversation=dict(record), conversation_history=history, updated_at=_now())
        state["issue_mappings"][key] = mapping
        return state

    return epic_run_state.update_epic_run_state(
        layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic
    )


@_serialized_worker
def start_conversation(
    layout: Layout,
    worker: str,
    *,
    engine: str,
    model: str | None,
    prompt: str,
    operation_id: str | None = None,
    http: Callable[..., tuple[int, Any]] = _http,
) -> dict[str, Any]:
    """Create one OpenHands conversation for the worker's task.

    One writer per worker: a new conversation is admitted only when no earlier one exists or the
    earlier one ended with a verified container stop. The id is chosen and recorded (under the
    run-state lock) before the request, so a lost response is reconciled by reading that id back;
    a create is never repeated.
    """

    import uuid

    engine, model = resolve_engine(engine, model)
    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    conversation_id = str(uuid.uuid4())
    record: dict[str, Any] = {"id": conversation_id, "engine": engine, "model": model, "status": "creating", "at": _now()}
    if operation_id is not None:
        if not re.fullmatch(r"pr-completion-[0-9a-f]{64}", operation_id):
            raise LaunchRefused("invalid PR completion operation id")
        record["operation_id"] = operation_id
    reserved = _reserve_conversation(layout, issue, worker, record)
    mapping = reserved["issue_mappings"][str(issue)]
    port, key = int(mapping["port"]), _session_key(layout, worker)
    payload = {
        "conversation_id": conversation_id,
        "workspace": {"working_dir": CONTAINER_WORKSPACE},
        "agent_settings": {"agent_kind": "acp", "acp_server": engine, "acp_model": model},
        "autotitle": False,
        "tags": {"epic": str(layout.epic), "issue": str(issue), "worker": worker},
        "initial_message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
    }
    try:
        code, body = http("POST", port, key, "/conversations", payload, 120.0)
    except Exception:  # noqa: BLE001 - any transport/decode failure leaves the outcome unknown
        code, body = 0, None
    if code == 201 and isinstance(body, Mapping) and str(body.get("id")) == conversation_id:
        record.update(status="created", execution_status=body.get("execution_status"))
    else:
        record.update(status=reconcile_conversation(port, key, conversation_id, http=http))
    _record_worker(layout, issue, conversation=record)
    return record


def reconcile_conversation(port: int, key: str, conversation_id: str, *, http: Callable[..., tuple[int, Any]] = _http) -> str:
    """``created`` only on positive readback; anything else stays ``unknown``.

    A 404 right after a lost create is not proof of absence (the server may still be creating
    it). The only way out of ``unknown`` besides positive readback is a verified worker stop.
    """

    try:
        code, body = http("GET", port, key, f"/conversations/{conversation_id}", None, 10.0)
    except Exception:  # noqa: BLE001
        return "unknown"
    if code == 200 and isinstance(body, Mapping) and str(body.get("id")) == conversation_id:
        return "created"
    return "unknown"


@_serialized_worker
def reconcile_worker_conversation(layout: Layout, worker: str, *, http: Callable[..., tuple[int, Any]] = _http) -> dict[str, Any]:
    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    record = mapping.get("conversation")
    if not isinstance(record, Mapping):
        raise EpicWorkspaceError("worker has no conversation to reconcile")
    if record.get("status") not in ("creating", "unknown"):
        return dict(record)
    if mapping.get("state") != "running":
        raise EpicWorkspaceError("worker is not running; a verified stop already ends its conversation")
    updated = {**record, "status": reconcile_conversation(int(mapping["port"]), _session_key(layout, worker), record["id"], http=http)}
    _record_worker(layout, issue, conversation=updated)
    return updated


_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # A paid-API credential in use violates the subscription-only policy; never a handoff trigger.
    ("policy", re.compile(r"credit balance|ANTHROPIC_API_KEY|OPENAI_API_KEY|billing", re.I)),
    ("authentication", re.compile(
        r"authentication required|ACPAuthRequired|unauthori[sz]ed|invalid (api key|token|bearer)|"
        r"token (has )?expired|refresh token|sign in again|log ?in again|not logged in|oauth", re.I)),
    # Subscription quota phrasing from Claude Code and Codex only; no bare "429" or "rate limit".
    ("quota_exhausted", re.compile(
        r"usage limit (reached|has been reached)|claude ai usage limit|you'?ve hit your usage limit|"
        r"you['’]ve hit your (weekly|session) limit\b|"
        r"usage_limit_reached|(5|five)-hour limit|weekly limit reached|out of (extra )?usage", re.I)),
    ("context_exhausted", re.compile(r"context (length|window)|prompt is too long|maximum context|too many tokens", re.I)),
    ("transient_network", re.compile(
        r"ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|socket hang up|connection (reset|refused|closed)|"
        r"timed out|overloaded|\b50[234] (bad gateway|service unavailable|gateway time-?out)", re.I)),
)


def classify_failure(text: str) -> str:
    """Map an engine-level (ACP/conversation) error to one class.

    Only ``quota_exhausted`` may trigger an engine handoff. Tool output is never classified here.
    """

    for name, pattern in _FAILURE_PATTERNS:
        if pattern.search(text or ""):
            return name
    return "task_failure" if text else "unclassified"


def conversation_status(layout: Layout, worker: str, *, http: Callable[..., tuple[int, Any]] = _http,
                        limit: int = 50, include_messages: bool = True) -> dict[str, Any]:
    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    record = mapping.get("conversation")
    if not isinstance(record, Mapping):
        return {"issue": issue, "worker": worker, "conversation": None}
    port, key, cid = int(mapping["port"]), _session_key(layout, worker), record["id"]
    try:
        code, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
        ecode, events = http("GET", port, key, f"/conversations/{cid}/events/search?limit={int(limit)}&sort_order=TIMESTAMP_DESC", None, 10.0)
    except OSError:
        return {"issue": issue, "worker": worker, "conversation": dict(record), "reachable": False}
    # The server returns the newest page first; retain chronological order within that page.
    items = list(reversed(events.get("items", []))) if ecode == 200 and isinstance(events, Mapping) else []
    errors = [
        f"{e.get('code') or ''} {e.get('detail') or e.get('error') or ''}".strip()
        for e in items if isinstance(e, Mapping) and e.get("kind") == "ConversationErrorEvent"
    ]
    last_agent_message = next(
        (e for e in reversed(items) if isinstance(e, Mapping) and e.get("kind") == "MessageEvent" and e.get("source") == "agent"),
        None,
    ) if include_messages else None
    return {
        "issue": issue,
        "worker": worker,
        "conversation": dict(record),
        "reachable": code == 200,
        "execution_status": info.get("execution_status") if isinstance(info, Mapping) else None,
        "event_kinds": [e.get("kind") for e in items if isinstance(e, Mapping)][-limit:],
        "errors": errors,
        "failure_class": classify_failure(errors[-1]) if errors else None,
        "last_agent_message": last_agent_message,
    }


# --------------------------------------------------------------------------- CLI


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="epic_workspace", description=__doc__.splitlines()[0])
    p.add_argument("--root", required=True, help="persistent workspace root on the worker VM")
    p.add_argument("--epic", required=True, type=int)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--repo-url", required=True)
    c = sub.add_parser("worker-create")
    c.add_argument("--worker", required=True)
    c.add_argument("--issue", required=True, type=int)
    c.add_argument("--branch", required=True)
    c.add_argument("--base", default="main")
    c.add_argument("--next-action", required=True)
    s = sub.add_parser("worker-start")
    s.add_argument("--worker", required=True)
    s.add_argument("--image", default=DEFAULT_IMAGE)
    s.add_argument("--cpus", default=Budget.cpus)
    s.add_argument("--memory", default=Budget.memory)
    s.add_argument("--pids", type=int, default=Budget.pids)
    s.add_argument("--env-file")
    s.add_argument("--mount", action="append", default=[], help="extra SOURCE:TARGET (validated; normally refused)")
    s.add_argument("--engine", default="claude")
    s.add_argument("--model")
    s.add_argument("--network", default=DEFAULT_NETWORK)
    s.add_argument("command", nargs=argparse.REMAINDER)
    t = sub.add_parser("worker-stop")
    t.add_argument("--worker", required=True)
    t.add_argument("--reason", required=True)
    sub.add_parser("status")
    o = sub.add_parser("openhands-start", help="start the worker's pinned OpenHands agent-server container")
    o.add_argument("--worker", required=True)
    o.add_argument("--cpus", default="1.0")
    o.add_argument("--memory", default="1536m")
    o.add_argument("--pids", type=int, default=512)
    o.add_argument("--claude-env-file", help="file holding CLAUDE_CODE_OAUTH_TOKEN (mode 0600, outside the root)")
    o.add_argument("--codex-home", help="Terra reserve ChatGPT login directory (mode 0700, outside the root)")
    cs = sub.add_parser("conversation-start", help="start an OpenHands conversation with the selected engine/model")
    cs.add_argument("--worker", required=True)
    cs.add_argument("--engine", default="claude-code", choices=sorted(ENGINE_DEFAULT_MODELS))
    cs.add_argument("--model")
    cs.add_argument("--prompt-file", help="task text; required unless --continuation")
    cs.add_argument("--continuation", action="store_true", help="prefix the prompt with the brief rebuilt from run-state")
    ct = sub.add_parser("conversation-status")
    ct.add_argument("--worker", required=True)
    cr = sub.add_parser("conversation-reconcile", help="resolve a creating/unknown conversation by id readback")
    cr.add_argument("--worker", required=True)
    cp = sub.add_parser("worker-checkpoint", help="checkpoint unique work of a worker whose container is already gone")
    cp.add_argument("--worker", required=True)
    cp.add_argument("--reason", required=True)
    rl = sub.add_parser("checkpoint-release", help="supersede a checkpoint whose content is in a published commit")
    rl.add_argument("--worker", required=True)
    rl.add_argument("--ref", required=True)
    rl.add_argument("--published-commit", required=True)
    tk = sub.add_parser("takeover", help="prove the predecessor gone, reconcile, and permit exactly one continuation")
    tk.add_argument("--worker", required=True)
    tk.add_argument("--reason", required=True)
    tk.add_argument("--readback-file", help="JSON {operation-id: readback} supplied by the coordinator")
    cb = sub.add_parser("continuation-brief", help="rebuild the next authorized action from run-state alone")
    cb.add_argument("--worker", required=True)
    rt = sub.add_parser("worker-retire", help="remove the worker's container and, if nothing unique remains, its checkout")
    rt.add_argument("--worker", required=True)
    pb = sub.add_parser("publication-begin", help="record the intent to push/open a PR before doing it")
    pb.add_argument("--worker", required=True)
    pb.add_argument("--kind", required=True, choices=PUBLICATION_KINDS)
    pb.add_argument("--expect-sha", help="full intended commit; required for branch_push before its effect")
    pc = sub.add_parser("publication-complete", help="record an observed publication outcome")
    pc.add_argument("--worker", required=True)
    pc.add_argument("--op", required=True)
    pc.add_argument("--result-file", required=True)
    pr = sub.add_parser("publication-reconcile", help="resolve an unresolved publication from coordinator readback")
    pr.add_argument("--worker", required=True)
    pr.add_argument("--op", required=True)
    pr.add_argument("--readback-file")
    return p


def _read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EpicWorkspaceError(f"cannot read JSON from {path}: {exc}") from exc


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = subprocess.run,
    http: Callable[..., tuple[int, Any]] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    _http_kw: dict[str, Any] = {"http": http} if http is not None else {}
    root = Path(args.root).expanduser().resolve()
    layout = Layout(root, args.epic)
    try:
        if args.cmd == "init":
            init_workspace(root, args.epic, args.repo_url, runner=runner)
            out: Any = {"initialized": str(layout.epic_dir)}
        elif args.cmd == "worker-create":
            out = {"checkout": str(create_worker(layout, args.worker, issue=args.issue, branch=args.branch, base=args.base, next_action=args.next_action, runner=runner))}
        elif args.cmd == "worker-start":
            command = [c for c in args.command if c != "--"] or ["sleep", "infinity"]
            mounts = [tuple(m.split(":", 1)) for m in args.mount]
            if any(len(m) != 2 for m in mounts):
                raise LaunchRefused("--mount must be SOURCE:TARGET")
            cid = start_worker(
                layout, args.worker, command=command, image=args.image,
                budget=Budget(args.cpus, args.memory, args.pids),
                env_file=Path(args.env_file) if args.env_file else None,
                extra_mounts=mounts, engine=args.engine, model=args.model, network=args.network, runner=runner,
            )
            out = {"container_id": cid}
        elif args.cmd == "openhands-start":
            out = start_openhands_worker(
                layout, args.worker, budget=Budget(args.cpus, args.memory, args.pids),
                claude_env_file=Path(args.claude_env_file) if args.claude_env_file else None,
                codex_home=Path(args.codex_home) if args.codex_home else None, runner=runner, **_http_kw,
            )
        elif args.cmd == "conversation-start":
            if not args.prompt_file and not args.continuation:
                raise LaunchRefused("--prompt-file is required unless --continuation is given")
            parts = [continuation_brief(layout, args.worker)["prompt"]] if args.continuation else []
            if args.prompt_file:
                parts.append(Path(args.prompt_file).read_text(encoding="utf-8"))
            prompt = "\n\n".join(parts)
            out = start_conversation(layout, args.worker, engine=args.engine, model=args.model, prompt=prompt, **_http_kw)
        elif args.cmd == "conversation-status":
            out = conversation_status(layout, args.worker, **_http_kw)
        elif args.cmd == "conversation-reconcile":
            out = reconcile_worker_conversation(layout, args.worker, **_http_kw)
        elif args.cmd == "worker-checkpoint":
            out = {"checkpoint": checkpoint_worker(layout, args.worker, reason=args.reason, runner=runner)}
        elif args.cmd == "checkpoint-release":
            out = release_checkpoint(layout, args.worker, ref=args.ref, published_commit=args.published_commit, runner=runner)
        elif args.cmd == "takeover":
            out = takeover(layout, args.worker, reason=args.reason, readbacks=_read_json(args.readback_file) if args.readback_file else None, runner=runner)
        elif args.cmd == "continuation-brief":
            out = continuation_brief(layout, args.worker)
        elif args.cmd == "worker-retire":
            out = retire_worker(layout, args.worker, runner=runner)
        elif args.cmd == "publication-begin":
            out = begin_publication(layout, args.worker, kind=args.kind, expect_sha=args.expect_sha)
        elif args.cmd == "publication-complete":
            out = complete_publication(layout, args.worker, op_id=args.op, result=_read_json(args.result_file))
        elif args.cmd == "publication-reconcile":
            out = reconcile_publication(layout, args.worker, op_id=args.op, readback=_read_json(args.readback_file) if args.readback_file else None)
        elif args.cmd == "worker-stop":
            out = {"work_at_stop": stop_worker(layout, args.worker, reason=args.reason, runner=runner)}
        else:
            out = status(layout, runner=runner)
    except EpicWorkspaceError as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
