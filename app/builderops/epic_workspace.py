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
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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

Runner = Callable[..., subprocess.CompletedProcess]


class EpicWorkspaceError(RuntimeError):
    """Base error; the operation it names did not take effect."""


class EngineUnavailable(EpicWorkspaceError):
    """The container engine cannot be used. Never fall back to the host."""


class LaunchRefused(EpicWorkspaceError):
    """A launch request violates the workspace or resource boundary."""


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


def _run(runner: Runner, argv: Sequence[str], *, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    result = runner(list(argv), capture_output=True, text=True, cwd=str(cwd) if cwd else None, check=False)
    if check and result.returncode != 0:
        raise EpicWorkspaceError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} failed: {(result.stderr or '').strip()[:400]}")
    return result


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(base.resolve(strict=False))
        return True
    except ValueError:
        return False


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


def create_worker(
    layout: Layout,
    *,
    worker: str,
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
    _reserve_worker(layout, issue, worker, state="creating")
    if not checkout.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        _run(runner, ["git", "clone", "--quiet", "--no-hardlinks", str(layout.source), str(checkout)])
        exists = _run(runner, ["git", "-C", str(checkout), "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], check=False)
        start = f"origin/{branch}" if exists.returncode == 0 else f"origin/{base}"
        _run(runner, ["git", "-C", str(checkout), "checkout", "--quiet", "-B", branch, start])
    layout.home(worker).mkdir(parents=True, exist_ok=True)
    _reserve_worker(
        layout,
        issue,
        worker,
        branch=branch,
        checkout=str(checkout),
        state="created",
        next_action=next_action,
    )
    return checkout


def _assert_engine(runner: Runner) -> str:
    try:
        result = runner(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:  # docker CLI missing
        raise EngineUnavailable("docker CLI not found; refusing (no host fallback)") from exc
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
        "docker", "run", "--detach",
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
    env_path = _validate_env_file(env_file, layout)
    argv = build_launch_argv(layout, worker, image=image, command=command, budget=budget, env_file=env_path, extra_mounts=extra_mounts, network=network)
    _assert_engine(runner)
    existing = _container_state(layout, worker, runner)
    if existing is not None:
        raise LaunchRefused(f"container for worker {worker!r} already exists ({existing}); stop it before a successor starts")
    result = _run(runner, argv)
    container_id = (result.stdout or "").strip()[:64]
    _record_worker(
        layout,
        issue,
        state="running",
        # Plain container execution is a recorded bootstrap/diagnostic exception, never the
        # normal delivery path (#6615 owner revision 2026-11-12b).
        runtime="native-exception",
        container=layout.container_name(worker),
        container_id=container_id,
        image=image,
        engine=engine,
        model=model,
        budget={"cpus": budget.cpus, "memory": budget.memory, "pids": budget.pids},
        network=network,
        started_at=_now(),
    )
    return container_id


def _container_state(layout: Layout, worker: str, runner: Runner) -> str | None:
    result = runner(
        ["docker", "ps", "--all", "--filter", f"label={LABEL_EPIC}={layout.epic}", "--filter", f"label={LABEL_WORKER}={worker}", "--format", "{{.State}}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise EngineUnavailable("cannot read container state; treat worker as possibly running")
    states = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return states[0] if states else None


def stop_worker(layout: Layout, worker: str, *, reason: str, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Remove the worker container and prove absence by engine readback."""

    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    _assert_engine(runner)
    runner(["docker", "rm", "--force", layout.container_name(worker)], capture_output=True, text=True, check=False)
    remaining = _container_state(layout, worker, runner)
    if remaining is not None:
        raise EpicWorkspaceError(f"worker {worker!r} container still present ({remaining}); not verified stopped")
    work = inspect_checkout(layout.checkout(worker), runner=runner)
    fields: dict[str, Any] = {"state": "stopped_verified", "stopped_at": _now(), "stop_reason": reason, "work_at_stop": work}
    conversation = state["issue_mappings"][str(issue)].get("conversation")
    if isinstance(conversation, Mapping):
        # The hosting container is verified absent, so this conversation can no longer write.
        fields["conversation"] = {**conversation, "status": CONVERSATION_ENDED, "ended_at": _now()}
    _record_worker(layout, issue, **fields)
    return work


def _contained_git(checkout: Path, args: Sequence[str], *, runner: Runner, image: str) -> subprocess.CompletedProcess:
    """Run git against a worker checkout inside a throwaway container.

    The checkout's ``.git/config`` and ``.gitattributes`` are worker-controlled (fsmonitor,
    filter drivers, hooks). Running git on the host would execute that config as the
    controller user, so inspection runs contained: read-only mount, no network, no
    capabilities, no writes, uid 1000.
    """

    source = str(checkout.resolve(strict=True))
    if not _MOUNT_PATH.match(source):
        raise EpicWorkspaceError("checkout path contains unsafe characters")
    argv = [
        "docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", WORKER_UID_GID, "--pids-limit", "64",
        "--memory", "256m", "--tmpfs", "/tmp:rw,nosuid,size=16m", "--env", "HOME=/tmp",
        "--env", "GIT_CONFIG_NOSYSTEM=1", "--env", "GIT_CONFIG_GLOBAL=/dev/null",
        "--mount", f"type=bind,source={source},target={INSPECT_TARGET},readonly",
        image,
        "git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
        "-c", f"safe.directory={INSPECT_TARGET}", "-C", INSPECT_TARGET, *args,
    ]
    return runner(argv, capture_output=True, text=True, check=False)


def inspect_checkout(checkout: Path, *, runner: Runner = subprocess.run, image: str = DEFAULT_IMAGE) -> dict[str, Any]:
    """Classify a checkout's unique work without executing worker-controlled config on the host."""

    if not checkout.is_dir():
        return {"present": False}
    try:
        _assert_engine(runner)
        head = _contained_git(checkout, ["rev-parse", "HEAD"], runner=runner, image=image)
        porcelain = _contained_git(
            checkout, ["status", "--porcelain", "--untracked-files=all", "--ignored=matching"], runner=runner, image=image
        )
        unpublished = _contained_git(checkout, ["rev-list", "--count", "HEAD", "--not", "--remotes"], runner=runner, image=image)
    except EpicWorkspaceError:
        return {"present": True, "readable": False, "unique_work": True}
    lines = [line for line in (porcelain.stdout or "").splitlines() if line.strip()]
    changed = [line[3:] for line in lines if not line.startswith("!! ")]
    # Ignored files (e.g. ``*.txt``, ``.codex-tmp/``) may still be unique work; report them
    # separately so a reclaim decision can see them instead of treating them as absent.
    ignored = [line[3:] for line in lines if line.startswith("!! ")]
    count = int((unpublished.stdout or "0").strip() or 0) if unpublished.returncode == 0 else -1
    readable = porcelain.returncode == 0 and unpublished.returncode == 0
    return {
        "present": True,
        "readable": readable,
        "head": (head.stdout or "").strip() or None,
        "uncommitted_paths": changed[:50],
        "uncommitted_count": len(changed),
        "ignored_paths": ignored[:50],
        "ignored_count": len(ignored),
        "unpublished_commits": count,
        # Unreadable evidence is treated as unique work (fail safe).
        "unique_work": (not readable) or bool(changed) or count != 0,
    }


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
        workers.append({
            "issue": int(key),
            "worker": worker,
            "branch": mapping.get("branch"),
            "recorded_state": mapping.get("state"),
            "container": container,
            "engine": mapping.get("engine"),
            "model": mapping.get("model"),
            "next_action": mapping.get("next_action"),
            "work": inspect_checkout(layout.checkout(worker), runner=runner),
        })
    return {
        "schema": SCHEMA,
        "epic": layout.epic,
        "epic_dir": str(layout.epic_dir),
        "engine_version": engine,
        "workers": workers,
        "authority": "coordination evidence only; GitHub Issues/PRs/CI win",
    }


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

    used = runner(["docker", "ps", "--format", "{{.Ports}}"], capture_output=True, text=True, check=False)
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
    busy = runner(["docker", "ps", "--filter", "label=epic-workspace.codex-home=1", "--format", "{{.Names}}"],
                  capture_output=True, text=True, check=False)
    if busy.returncode != 0 or (busy.stdout or "").strip():
        raise LaunchRefused("codex home is already mounted by another running worker (or unknown)")
    return [(str(home.resolve()), CODEX_HOME_TARGET)]


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
    credential_env = _validate_env_file(claude_env_file, layout)
    _assert_engine(runner)
    if _container_state(layout, worker, runner) is not None:
        raise LaunchRefused(f"container for worker {worker!r} already exists; stop it before a successor starts")
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
    result = _run(runner, argv)
    _record_worker(
        layout, issue, state="starting", runtime="openhands", container=layout.container_name(worker),
        container_id=(result.stdout or "").strip()[:64], image=image, port=port,
        budget={"cpus": budget.cpus, "memory": budget.memory, "pids": budget.pids}, network=network,
        credentials={"claude": "oauth-token-env" if credential_env else None, "codex": "chatgpt-login-dir" if codex_mounts else None},
        started_at=_now(),
    )
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
        history = list(mapping.get("conversation_history", []))
        if isinstance(prior, Mapping):
            history.append(dict(prior))
        mapping.update(conversation=dict(record), conversation_history=history, updated_at=_now())
        state["issue_mappings"][key] = mapping
        return state

    return epic_run_state.update_epic_run_state(
        layout.run_id, root=layout.run_state_dir, updater=updater, expected_epic_issue_number=layout.epic
    )


def start_conversation(
    layout: Layout,
    worker: str,
    *,
    engine: str,
    model: str | None,
    prompt: str,
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


def conversation_status(layout: Layout, worker: str, *, http: Callable[..., tuple[int, Any]] = _http, limit: int = 50) -> dict[str, Any]:
    state = _load_state(layout)
    issue = _issue_for_worker(state, worker)
    mapping = state["issue_mappings"][str(issue)]
    record = mapping.get("conversation")
    if not isinstance(record, Mapping):
        return {"issue": issue, "worker": worker, "conversation": None}
    port, key, cid = int(mapping["port"]), _session_key(layout, worker), record["id"]
    try:
        code, info = http("GET", port, key, f"/conversations/{cid}", None, 10.0)
        ecode, events = http("GET", port, key, f"/conversations/{cid}/events/search?limit={int(limit)}", None, 10.0)
    except OSError:
        return {"issue": issue, "worker": worker, "conversation": dict(record), "reachable": False}
    items = events.get("items", []) if ecode == 200 and isinstance(events, Mapping) else []
    errors = [
        f"{e.get('code') or ''} {e.get('detail') or e.get('error') or ''}".strip()
        for e in items if isinstance(e, Mapping) and e.get("kind") == "ConversationErrorEvent"
    ]
    last_agent_message = next(
        (e for e in reversed(items) if isinstance(e, Mapping) and e.get("kind") == "MessageEvent" and e.get("source") == "agent"),
        None,
    )
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
    cs.add_argument("--prompt-file", required=True)
    ct = sub.add_parser("conversation-status")
    ct.add_argument("--worker", required=True)
    cr = sub.add_parser("conversation-reconcile", help="resolve a creating/unknown conversation by id readback")
    cr.add_argument("--worker", required=True)
    return p


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
            out = {"checkout": str(create_worker(layout, worker=args.worker, issue=args.issue, branch=args.branch, base=args.base, next_action=args.next_action, runner=runner))}
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
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            out = start_conversation(layout, args.worker, engine=args.engine, model=args.model, prompt=prompt, **_http_kw)
        elif args.cmd == "conversation-status":
            out = conversation_status(layout, args.worker, **_http_kw)
        elif args.cmd == "conversation-reconcile":
            out = reconcile_worker_conversation(layout, args.worker, **_http_kw)
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
