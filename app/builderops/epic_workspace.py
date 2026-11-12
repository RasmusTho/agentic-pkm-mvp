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
        "--tmpfs", "/tmp:rw,nosuid,size=512m",
        "--user", WORKER_UID_GID,
        "--network", network,
        "--env", f"HOME={CONTAINER_HOME}",
        "--workdir", CONTAINER_WORKSPACE,
    ]
    for source, target in mounts:
        argv += ["--mount", f"type=bind,source={source},target={target}"]
    if env_file is not None:
        argv += ["--env-file", str(env_file)]
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
    _record_worker(layout, issue, state="stopped_verified", stopped_at=_now(), stop_reason=reason, work_at_stop=work)
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
    return p


def main(argv: Sequence[str] | None = None, *, runner: Runner = subprocess.run) -> int:
    args = _parser().parse_args(argv)
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
