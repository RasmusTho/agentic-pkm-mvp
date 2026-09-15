from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from app.builderops.epic_dispatch import (
    CodexIssueSessionLauncher,
    IssueSessionLaunchError,
    build_dispatch_plan,
)
from app.builderops.issue_delivery_worker_isolation import (
    ISOLATION_PROFILE_CONTRACT,
    REQUIRED_SYSTEMD_PROPERTIES_SHA256,
    CredentialProbeResult,
    CredentialProbeSyscalls,
    ExecutableIdentity,
    IssueWorkerIsolationError,
    LinuxSystemdCodexIssueSessionLauncher,
    ResolvedPrincipal,
    WorkerAccessProbeResult,
    canonical_command_sha256,
    file_sha256,
    probe_credential_denial,
    probe_worker_write_access,
    resolve_executable,
    resolve_worktree_git_topology,
    resolve_worktree_head,
)


EXECUTOR = ResolvedPrincipal(
    user="builder-executor",
    uid=os.geteuid(),
    group="builder-executor",
    gid=os.getegid(),
)
WORKER = ResolvedPrincipal(user="issue-worker", uid=2001, group="issue-worker", gid=2001)
FROZEN_HEAD = "a" * 40
SYSTEMD_RUN = ExecutableIdentity(
    path="/usr/bin/systemd-run",
    device=11,
    inode=12,
    sha256="1" * 64,
    mode=0o755,
    owner_uid=0,
    owner_gid=0,
)
ENV_EXECUTABLE = ExecutableIdentity(
    path="/usr/bin/env",
    device=21,
    inode=22,
    sha256="2" * 64,
    mode=0o755,
    owner_uid=0,
    owner_gid=0,
)
GIT_EXECUTABLE = ExecutableIdentity(
    path="/usr/bin/git",
    device=25,
    inode=26,
    sha256="3" * 64,
    mode=0o755,
    owner_uid=0,
    owner_gid=0,
)
CODEX_EXECUTABLE = ExecutableIdentity(
    path="/opt/codex/bin/codex",
    device=31,
    inode=32,
    sha256="4" * 64,
    mode=0o755,
    owner_uid=0,
    owner_gid=0,
)


def _git_admin(worktree: Path) -> Path:
    return _git_common(worktree) / "worktrees" / worktree.name


def _git_common(worktree: Path) -> Path:
    return worktree.parent / f"{worktree.name}-git-common"


def _create_linked_git_metadata(worktree: Path) -> None:
    git_admin = _git_admin(worktree)
    git_common = _git_common(worktree)
    git_admin.mkdir(parents=True)
    (git_common / "objects").mkdir()
    (git_common / "refs").mkdir()
    (git_admin / "HEAD").write_text("ref: refs/heads/codex/issue-5559/worker\n")
    (git_admin / "index").write_bytes(b"synthetic-index")
    (worktree / ".git").write_text(f"gitdir: {git_admin}\n", encoding="utf-8")


def _git_denied_targets(worktree: Path) -> tuple[Path, ...]:
    git_admin = _git_admin(worktree)
    git_common = _git_common(worktree)
    return (
        worktree / ".git",
        git_admin,
        git_admin / "HEAD",
        git_admin / "index",
        git_common,
        git_common / "objects",
        git_common / "refs",
    )


def _context_pack(worktree: Path) -> dict[str, Any]:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5559],
        run_id="issue-worker-isolation",
        candidates=[
            {
                "issue_number": 5559,
                "repository": "RasmusTho/agentic-pkm-mvp",
                "title": "isolate issue worker",
                "url": "https://example.test/issues/5559",
                "state": "OPEN",
                "labels": ["agent:ready", "type:task"],
                "project_status": "Ready",
                "risk": "high",
                "expected_value": "high",
                "likely_touched_files": ["app/builderops/issue_delivery_worker_isolation.py"],
                "validation_resources": ["builderops-worker-isolation"],
                "owner_docs": ["docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"],
                "owner_doc_writeback_required": True,
                "dependencies": [],
                "dependencies_satisfied": True,
                "dependencies_known": True,
                "strict_ready": True,
                "authority_ambiguous": False,
                "has_migration": False,
                "contract_surfaces": ["issue-delivery-worker-isolation.v1"],
                "source_anchors": ["FCA-ID-B"],
                "known_constraints": ["distinct OS principal"],
                "validation": [
                    "pytest -q tests/builderops/test_issue_delivery_worker_isolation.py"
                ],
                "worktree": str(worktree),
                "issue_local_helper_budget": 0,
                "issue_local_helper_rationale": None,
            }
        ],
    )
    return plan["context_packs"][0]


def _worker_receipt() -> dict[str, object]:
    return {
        "role": "slice_implementer",
        "task": "#5559",
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "branch": "codex/5559-distinct-worker-principal",
        "worktree": "/worktrees/issue-5559",
        "actions": ["implemented"],
        "ac_verdicts": ["pass"],
        "lifecycle_mutations": [],
        "validation": ["pass"],
        "owner_doc_result": "updated",
        "residual_risk": "host activation pending",
        "final_state": "handoff",
        "next_step": "review",
        "context_cost": {
            "measurement": "proxy",
            "input_tokens": "unknown(runtime-not-exposed)",
            "agent_starts": 1,
            "context_pack_bytes": "unknown(not-recorded)",
            "compactions": "unknown(runtime-not-exposed)",
        },
    }


def _profile_document(
    *,
    worktree: Path,
    model_home: Path,
    secret_file: Path,
    command_sha256: str,
) -> dict[str, object]:
    worktree_stat = worktree.stat()
    git_admin = _git_admin(worktree)
    git_admin_stat = git_admin.stat()
    git_common = _git_common(worktree)
    git_common_stat = git_common.stat()
    model_home_stat = model_home.stat()
    secret_stat = secret_file.stat()
    return {
        "contract": ISOLATION_PROFILE_CONTRACT,
        "profile_id": "bob-issue-delivery-worker",
        "profile_version": 1,
        "executor": {
            "user": EXECUTOR.user,
            "uid": EXECUTOR.uid,
            "group": EXECUTOR.group,
            "gid": EXECUTOR.gid,
            "supplementary_gids": list(EXECUTOR.supplementary_gids),
        },
        "worker": {
            "user": WORKER.user,
            "uid": WORKER.uid,
            "group": WORKER.group,
            "gid": WORKER.gid,
            "supplementary_gids": list(WORKER.supplementary_gids),
        },
        "worktree": {
            "path": str(worktree),
            "device": worktree_stat.st_dev,
            "inode": worktree_stat.st_ino,
            "git_head": FROZEN_HEAD,
            "git_directory": {
                "path": str(git_admin),
                "device": git_admin_stat.st_dev,
                "inode": git_admin_stat.st_ino,
            },
            "git_common_directory": {
                "path": str(git_common),
                "device": git_common_stat.st_dev,
                "inode": git_common_stat.st_ino,
            },
        },
        "model_auth": {
            "home": str(model_home),
            "reference": "codex-worker-subscription-v1",
            "device": model_home_stat.st_dev,
            "inode": model_home_stat.st_ino,
        },
        "protected_github_credential": {
            "path": str(secret_file),
            "device": secret_stat.st_dev,
            "inode": secret_stat.st_ino,
        },
        "systemd_run": {
            "path": SYSTEMD_RUN.path,
            "device": SYSTEMD_RUN.device,
            "inode": SYSTEMD_RUN.inode,
            "sha256": SYSTEMD_RUN.sha256,
            "mode": SYSTEMD_RUN.mode,
            "owner_uid": SYSTEMD_RUN.owner_uid,
            "owner_gid": SYSTEMD_RUN.owner_gid,
        },
        "environment_executable": {
            "path": ENV_EXECUTABLE.path,
            "device": ENV_EXECUTABLE.device,
            "inode": ENV_EXECUTABLE.inode,
            "sha256": ENV_EXECUTABLE.sha256,
            "mode": ENV_EXECUTABLE.mode,
            "owner_uid": ENV_EXECUTABLE.owner_uid,
            "owner_gid": ENV_EXECUTABLE.owner_gid,
        },
        "git_executable": {
            "path": GIT_EXECUTABLE.path,
            "device": GIT_EXECUTABLE.device,
            "inode": GIT_EXECUTABLE.inode,
            "sha256": GIT_EXECUTABLE.sha256,
            "mode": GIT_EXECUTABLE.mode,
            "owner_uid": GIT_EXECUTABLE.owner_uid,
            "owner_gid": GIT_EXECUTABLE.owner_gid,
        },
        "codex_executable": {
            "path": CODEX_EXECUTABLE.path,
            "device": CODEX_EXECUTABLE.device,
            "inode": CODEX_EXECUTABLE.inode,
            "sha256": CODEX_EXECUTABLE.sha256,
            "mode": CODEX_EXECUTABLE.mode,
            "owner_uid": CODEX_EXECUTABLE.owner_uid,
            "owner_gid": CODEX_EXECUTABLE.owner_gid,
        },
        "command_sha256": command_sha256,
        "environment": {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/opt/codex/bin:/usr/bin:/bin",
        },
        "isolation_properties_sha256": REQUIRED_SYSTEMD_PROPERTIES_SHA256,
    }


def _write_profile(path: Path, document: Mapping[str, object]) -> str:
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return file_sha256(path)


def _principal_resolver(user: str, group: str) -> ResolvedPrincipal:
    principals = {EXECUTOR.user: EXECUTOR, WORKER.user: WORKER}
    principal = principals[user]
    assert principal.group == group
    return principal


def _executable_resolver(path: str) -> ExecutableIdentity:
    identities = {
        SYSTEMD_RUN.path: SYSTEMD_RUN,
        ENV_EXECUTABLE.path: ENV_EXECUTABLE,
        GIT_EXECUTABLE.path: GIT_EXECUTABLE,
        CODEX_EXECUTABLE.path: CODEX_EXECUTABLE,
    }
    return identities[path]


def _model_home_lstat(path: Path) -> os.stat_result:
    metadata = path.lstat()
    if path.name != "worker-model-home":
        return metadata
    values = list(metadata)
    values[0] = (metadata.st_mode & ~0o777) | 0o700
    values[4] = WORKER.uid
    values[5] = WORKER.gid
    return os.stat_result(values)


def _probe_syscalls(
    open_errno: int | None,
    *,
    access_policy: Any = None,
) -> CredentialProbeSyscalls:
    state = {"phase": "initial"}

    def setgroups(groups: Sequence[int]) -> None:
        if list(groups) != [] or state["phase"] != "initial":
            raise AssertionError("supplementary groups must be cleared first")
        state["phase"] = "groups-dropped"

    def setresgid(real: int, effective: int, saved: int) -> None:
        if (real, effective, saved) != (WORKER.gid,) * 3 or state["phase"] != "groups-dropped":
            raise AssertionError("GID must be dropped irreversibly after groups")
        state["phase"] = "gid-dropped"

    def setresuid(real: int, effective: int, saved: int) -> None:
        if (real, effective, saved) != (WORKER.uid,) * 3 or state["phase"] != "gid-dropped":
            raise AssertionError("UID must be dropped irreversibly after GID")
        state["phase"] = "uid-dropped"

    def exact_uid() -> int:
        return WORKER.uid if state["phase"] == "uid-dropped" else EXECUTOR.uid

    def exact_gid() -> int:
        return WORKER.gid if state["phase"] == "uid-dropped" else EXECUTOR.gid

    def open_secret(path: Path, flags: int) -> int:
        required_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if state["phase"] != "uid-dropped" or flags != required_flags or not path.is_absolute():
            raise AssertionError("secret open must follow the exact verified drop")
        if open_errno is not None:
            raise OSError(open_errno, "typed synthetic probe outcome")
        state["phase"] = "opened"
        return 73

    def close_secret(descriptor: int) -> None:
        if descriptor != 73 or state["phase"] != "opened":
            raise AssertionError("only the synthetic secret descriptor may close")
        state["phase"] = "closed"

    def access_path(path: Path, mode: int, *, effective_ids: bool) -> bool:
        if (
            state["phase"] != "uid-dropped"
            or not path.is_absolute()
            or mode not in {os.W_OK, os.W_OK | os.X_OK}
            or effective_ids is not True
        ):
            raise AssertionError("write access must be checked under the exact worker IDs")
        if access_policy is None:
            return True
        return bool(access_policy(path, mode))

    return CredentialProbeSyscalls(
        setgroups=setgroups,
        setresgid=setresgid,
        setresuid=setresuid,
        getuid=exact_uid,
        geteuid=exact_uid,
        getgid=exact_gid,
        getegid=exact_gid,
        getgroups=lambda: [] if state["phase"] == "uid-dropped" else [999],
        open=open_secret,
        close=close_secret,
        access=access_path,
    )


def _production_probe_with_outcome(open_errno: int | None) -> Any:
    def run_probe(
        secret_path: Path,
        worker: ResolvedPrincipal,
        executor: ResolvedPrincipal,
    ) -> CredentialProbeResult:
        return probe_credential_denial(
            secret_path,
            worker,
            executor,
            syscalls=_probe_syscalls(open_errno),
        )

    return run_probe


def _production_access_probe_with_outcome(
    *,
    worktree_access: bool,
    git_metadata_writable: bool,
) -> Any:
    def run_probe(
        writable_roots: Sequence[Path],
        denied_git_metadata: Sequence[Path],
        worker: ResolvedPrincipal,
        executor: ResolvedPrincipal,
    ) -> WorkerAccessProbeResult:
        denied = set(denied_git_metadata)

        def access_policy(path: Path, _mode: int) -> bool:
            if path in denied:
                return git_metadata_writable
            return worktree_access

        return probe_worker_write_access(
            writable_roots,
            denied_git_metadata,
            worker,
            executor,
            syscalls=_probe_syscalls(errno.EACCES, access_policy=access_policy),
        )

    return run_probe


def _prepared_case(
    root: Path,
) -> tuple[dict[str, Any], Path, dict[str, object], Path, Path, Path]:
    root.mkdir(parents=True)
    worktree = root / "issue-5559"
    model_home = root / "worker-model-home"
    worktree.mkdir()
    _create_linked_git_metadata(worktree)
    nested = worktree / "feature"
    nested.mkdir()
    (nested / "change.py").write_text("value = 1\n", encoding="utf-8")
    model_home.mkdir()
    model_home.chmod(0o700)
    secret_file = root / "executor-github.secret"
    secret_file.write_text("github_pat_DO_NOT_LEAK", encoding="utf-8")
    secret_file.chmod(0o600)
    context_pack = _context_pack(worktree)
    direct_launcher = CodexIssueSessionLauncher(
        repo_root=worktree,
        precreated_worktree_only=True,
    )
    direct_command = direct_launcher.command(context_pack)
    direct_command[0] = CODEX_EXECUTABLE.path
    profile = _profile_document(
        worktree=worktree,
        model_home=model_home,
        secret_file=secret_file,
        command_sha256=canonical_command_sha256(direct_command),
    )
    profile_file = root / "worker-isolation.json"
    _write_profile(profile_file, profile)
    return context_pack, profile_file, profile, worktree, model_home, secret_file


def _launcher(
    *,
    worktree: Path,
    profile_file: Path,
    expected_profile_sha256: str,
    runner: Any,
    credential_probe: Any = None,
    worker_access_probe: Any = None,
    principal_resolver: Any = None,
    worktree_head_resolver: Any = None,
    worktree_git_topology_resolver: Any = None,
    systemd_preflight: Any = None,
    executable_resolver: Any = None,
    path_lstat_resolver: Any = None,
    unit_token: Any = None,
    platform_name: str = "linux",
) -> LinuxSystemdCodexIssueSessionLauncher:
    return LinuxSystemdCodexIssueSessionLauncher(
        repo_root=worktree,
        profile_file=profile_file,
        expected_profile_sha256=expected_profile_sha256,
        principal_resolver=principal_resolver or _principal_resolver,
        current_identity=lambda: (EXECUTOR.uid, EXECUTOR.gid),
        credential_probe=(
            credential_probe
            if credential_probe is not None
            else _production_probe_with_outcome(errno.EACCES)
        ),
        worker_access_probe=(
            worker_access_probe
            if worker_access_probe is not None
            else _production_access_probe_with_outcome(
                worktree_access=True,
                git_metadata_writable=False,
            )
        ),
        worktree_head_resolver=(
            worktree_head_resolver
            if worktree_head_resolver is not None
            else lambda _path, _git: FROZEN_HEAD
        ),
        worktree_git_topology_resolver=(
            worktree_git_topology_resolver
            if worktree_git_topology_resolver is not None
            else lambda path, _git: (_git_admin(path), _git_common(path))
        ),
        systemd_preflight=systemd_preflight or (lambda: SYSTEMD_RUN),
        executable_resolver=executable_resolver or _executable_resolver,
        path_lstat_resolver=path_lstat_resolver or _model_home_lstat,
        runner=runner,
        unit_token=unit_token or (lambda: "0123456789abcdef"),
        clock=lambda: "2026-09-15T10:00:00Z",
        platform_name=platform_name,
    )


def test_systemd_worker_runs_as_distinct_unprivileged_principal(tmp_path: Path) -> None:
    worktree = tmp_path / "issue-5559"
    model_home = tmp_path / "worker-model-home"
    worktree.mkdir()
    git_admin = _git_admin(worktree)
    git_common = _git_common(worktree)
    _create_linked_git_metadata(worktree)
    nested = worktree / "feature"
    nested.mkdir()
    nested_file = nested / "change.py"
    nested_file.write_text("value = 1\n", encoding="utf-8")
    model_home.mkdir()
    model_home.chmod(0o700)
    secret_file = tmp_path / "executor-github.secret"
    secret_file.write_text("github_pat_DO_NOT_LEAK", encoding="utf-8")
    secret_file.chmod(0o600)
    context_pack = _context_pack(worktree)
    direct_launcher = CodexIssueSessionLauncher(
        repo_root=worktree,
        precreated_worktree_only=True,
    )
    direct_command = direct_launcher.command(context_pack)
    direct_command[0] = CODEX_EXECUTABLE.path
    profile_file = tmp_path / "worker-isolation.json"
    expected_profile_hash = _write_profile(
        profile_file,
        _profile_document(
            worktree=worktree,
            model_home=model_home,
            secret_file=secret_file,
            command_sha256=canonical_command_sha256(direct_command),
        ),
    )
    events: list[str] = []
    invocations: list[tuple[list[str], dict[str, object]]] = []

    def credential_probe(*_args: object, **_kwargs: object) -> CredentialProbeResult:
        events.append("credential-probe")
        secret_path, worker, executor = _args
        assert isinstance(secret_path, Path)
        assert isinstance(worker, ResolvedPrincipal)
        assert isinstance(executor, ResolvedPrincipal)
        return probe_credential_denial(
            secret_path,
            worker,
            executor,
            syscalls=_probe_syscalls(errno.EACCES),
        )

    def worker_access_probe(*_args: object, **_kwargs: object) -> WorkerAccessProbeResult:
        events.append("worker-access-probe")
        writable_roots, denied_git_metadata, worker, executor = _args
        assert writable_roots == (worktree, model_home)
        assert denied_git_metadata == _git_denied_targets(worktree)
        assert isinstance(worker, ResolvedPrincipal)
        assert isinstance(executor, ResolvedPrincipal)
        denied = set(denied_git_metadata)
        return probe_worker_write_access(
            writable_roots,
            denied_git_metadata,
            worker,
            executor,
            syscalls=_probe_syscalls(
                errno.EACCES,
                access_policy=lambda path, _mode: path not in denied,
            ),
        )

    def runner(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        events.append("systemd-entry")
        invocations.append((list(command), dict(kwargs)))
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "session-5559"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(_worker_receipt()),
                        },
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    launcher = LinuxSystemdCodexIssueSessionLauncher(
        repo_root=worktree,
        profile_file=profile_file,
        expected_profile_sha256=expected_profile_hash,
        principal_resolver=_principal_resolver,
        current_identity=lambda: (EXECUTOR.uid, EXECUTOR.gid),
        credential_probe=credential_probe,
        worker_access_probe=worker_access_probe,
        worktree_head_resolver=lambda _path, _git: FROZEN_HEAD,
        worktree_git_topology_resolver=lambda _path, _git: (git_admin, git_common),
        systemd_preflight=lambda: SYSTEMD_RUN,
        executable_resolver=_executable_resolver,
        path_lstat_resolver=_model_home_lstat,
        runner=runner,
        unit_token=lambda: "0123456789abcdef",
        clock=lambda: "2026-09-15T10:00:00Z",
        platform_name="linux",
    )

    result = launcher.launch(context_pack)

    assert events == ["credential-probe", "worker-access-probe", "systemd-entry"]
    command, kwargs = invocations[0]
    assert command[:5] == [
        SYSTEMD_RUN.path,
        "--wait",
        "--pipe",
        "--collect",
        "--quiet",
    ]
    assert "--service-type=exec" in command
    assert "--property=User=2001" in command
    assert "--property=Group=2001" in command
    assert "--property=SupplementaryGroups=" in command
    assert "--property=NoNewPrivileges=yes" in command
    assert f"--property=WorkingDirectory={worktree}" in command
    assert f"--property=ReadWritePaths={worktree}" in command
    assert f"--property=ReadWritePaths={git_admin}" not in command
    assert f"--property=ReadWritePaths={git_common}" not in command
    assert f"--property=ReadWritePaths={model_home}" in command
    assert f"--property=ReadOnlyPaths={worktree / '.git'}" in command
    assert f"--property=ReadOnlyPaths={git_admin}" in command
    assert f"--property=ReadOnlyPaths={git_common}" in command
    assert f"--property=ReadWritePaths={worktree.parent}" not in command
    assert "--property=KillMode=control-group" in command
    assert "--property=CollectMode=inactive-or-failed" in command
    assert "--property=RuntimeMaxSec=5400" in command
    separator = command.index("--")
    child = command[separator + 1 :]
    assert child[:2] == [ENV_EXECUTABLE.path, "-i"]
    assert CODEX_EXECUTABLE.path in child
    assert all(Path(token).name not in {"sh", "bash", "dash", "zsh"} for token in child)
    assert "--add-dir" not in child
    assert kwargs["cwd"] == worktree
    assert kwargs["env"] == {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    assert kwargs["timeout"] == 5460
    assert result["session_id"] == "session-5559"
    receipt = result["isolation_receipt"]
    assert receipt["executor"] == {
        "uid": EXECUTOR.uid,
        "gid": EXECUTOR.gid,
        "supplementary_gids": [],
    }
    assert receipt["worker"] == {
        "uid": 2001,
        "gid": 2001,
        "supplementary_gids": [],
    }
    assert receipt["no_new_privileges"] is True
    assert receipt["probe_result"] == "denied"
    assert receipt["worker_write_access_probe_result"] == "worktree-writable-git-denied"
    assert receipt["git_metadata_write_denied"] is True

    failed_entries: list[list[str]] = []

    def failed_runner(
        command: Sequence[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        failed_entries.append(list(command))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unit failed")

    with pytest.raises(IssueSessionLaunchError, match="unit failed"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_profile_hash,
            runner=failed_runner,
        ).launch(context_pack)
    assert len(failed_entries) == 1
    assert "--property=KillMode=control-group" in failed_entries[0]
    assert "--property=CollectMode=inactive-or-failed" in failed_entries[0]


def test_worker_cannot_read_host_effect_credential(tmp_path: Path) -> None:
    started: list[list[str]] = []

    def runner(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        started.append(list(command))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="must not start")

    probe_target = tmp_path / "probe-only.secret"
    for open_errno, expected in (
        (None, CredentialProbeResult.READABLE),
        (errno.EACCES, CredentialProbeResult.DENIED),
        (errno.ENOENT, CredentialProbeResult.MISSING),
        (errno.EIO, CredentialProbeResult.FAILED),
    ):
        assert (
            probe_credential_denial(
                probe_target,
                WORKER,
                EXECUTOR,
                syscalls=_probe_syscalls(open_errno),
            )
            is expected
        )

    probe_worktree = tmp_path / "probe-worktree"
    probe_model_home = tmp_path / "probe-model-home"
    probe_worktree.mkdir()
    probe_model_home.mkdir()
    _create_linked_git_metadata(probe_worktree)
    nested = probe_worktree / "nested"
    nested.mkdir()
    tracked_file = nested / "tracked.py"
    tracked_file.write_text("value = 1\n", encoding="utf-8")
    writable_roots = (probe_worktree, probe_model_home)
    denied_git_metadata = _git_denied_targets(probe_worktree)
    denied_set = set(denied_git_metadata)
    assert (
        probe_worker_write_access(
            writable_roots,
            denied_git_metadata,
            WORKER,
            EXECUTOR,
            syscalls=_probe_syscalls(
                errno.EACCES,
                access_policy=lambda path, _mode: path not in denied_set,
            ),
        )
        is WorkerAccessProbeResult.ADMITTED
    )
    assert (
        probe_worker_write_access(
            writable_roots,
            denied_git_metadata,
            WORKER,
            EXECUTOR,
            syscalls=_probe_syscalls(
                errno.EACCES,
                access_policy=lambda path, _mode: path != tracked_file and path not in denied_set,
            ),
        )
        is WorkerAccessProbeResult.WORKTREE_DENIED
    )
    assert (
        probe_worker_write_access(
            writable_roots,
            denied_git_metadata,
            WORKER,
            EXECUTOR,
            syscalls=_probe_syscalls(
                errno.EACCES,
                access_policy=lambda _path, _mode: True,
            ),
        )
        is WorkerAccessProbeResult.GIT_METADATA_WRITABLE
    )

    context_pack, profile_file, _profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "worker-cannot-write"
    )
    with pytest.raises(ValueError, match="worktree access") as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            worker_access_probe=_production_access_probe_with_outcome(
                worktree_access=False,
                git_metadata_writable=False,
            ),
        ).launch(context_pack)
    assert str(secret) not in str(exc_info.value)

    context_pack, profile_file, _profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "worker-can-write-git-metadata"
    )
    with pytest.raises(ValueError, match="Git metadata denial") as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            worker_access_probe=_production_access_probe_with_outcome(
                worktree_access=True,
                git_metadata_writable=True,
            ),
        ).launch(context_pack)
    assert str(secret) not in str(exc_info.value)

    for name, open_errno in (
        ("readable", None),
        ("failed", errno.EIO),
    ):
        context_pack, profile_file, _profile, worktree, _model_home, secret = _prepared_case(
            tmp_path / name
        )
        launcher = _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            credential_probe=_production_probe_with_outcome(open_errno),
        )
        with pytest.raises(ValueError) as exc_info:
            launcher.launch(context_pack)
        assert str(secret) not in str(exc_info.value)

    context_pack, profile_file, profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "missing"
    )
    missing = tmp_path / "missing" / "not-present.secret"
    protected = dict(profile["protected_github_credential"])  # type: ignore[arg-type]
    protected["path"] = str(missing)
    profile["protected_github_credential"] = protected
    expected_hash = _write_profile(profile_file, profile)
    with pytest.raises(ValueError) as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)
    assert str(missing) not in str(exc_info.value)
    assert str(secret) not in str(exc_info.value)

    context_pack, profile_file, profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "aliased"
    )
    alias = tmp_path / "aliased" / "credential-alias"
    alias.symlink_to(secret)
    protected = dict(profile["protected_github_credential"])  # type: ignore[arg-type]
    protected["path"] = str(alias)
    profile["protected_github_credential"] = protected
    expected_hash = _write_profile(profile_file, profile)
    with pytest.raises(ValueError) as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)
    assert str(alias) not in str(exc_info.value)

    context_pack, profile_file, profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "same-principal"
    )
    profile["worker"] = {
        "user": "issue-worker",
        "uid": EXECUTOR.uid,
        "group": "issue-worker",
        "gid": EXECUTOR.gid,
        "supplementary_gids": [],
    }
    expected_hash = _write_profile(profile_file, profile)
    with pytest.raises(ValueError) as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)
    assert str(secret) not in str(exc_info.value)

    context_pack, profile_file, _profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "missing-principal"
    )

    def missing_principal(_user: str, _group: str) -> ResolvedPrincipal:
        raise IssueWorkerIsolationError("worker isolation principal is unavailable")

    with pytest.raises(ValueError, match="principal") as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            principal_resolver=missing_principal,
        ).launch(context_pack)
    assert str(secret) not in str(exc_info.value)

    context_pack, profile_file, _profile, worktree, _model_home, secret = _prepared_case(
        tmp_path / "supplementary-group"
    )

    def supplemented_worker(user: str, group: str) -> ResolvedPrincipal:
        resolved = _principal_resolver(user, group)
        if user != WORKER.user:
            return resolved
        return ResolvedPrincipal(
            user=resolved.user,
            uid=resolved.uid,
            group=resolved.group,
            gid=resolved.gid,
            supplementary_gids=(998,),
        )

    with pytest.raises(ValueError, match="principal") as exc_info:
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            principal_resolver=supplemented_worker,
        ).launch(context_pack)
    assert str(secret) not in str(exc_info.value)
    assert started == []


def test_missing_or_drifted_isolation_profile_refuses_before_child_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[str]] = []

    def runner(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        started.append(list(command))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="must not start")

    context_pack, profile_file, profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "profile-drift"
    )
    expected_hash = file_sha256(profile_file)
    profile["profile_id"] = "mutated-after-approval"
    _write_profile(profile_file, profile)
    with pytest.raises(ValueError, match="profile"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "missing-profile"
    )
    expected_hash = file_sha256(profile_file)
    profile_file.unlink()
    with pytest.raises(ValueError, match="profile"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)

    for name, mutate in (
        (
            "command-drift",
            lambda document: document.__setitem__("command_sha256", "b" * 64),
        ),
        (
            "isolation-property-drift",
            lambda document: document.__setitem__("isolation_properties_sha256", "b" * 64),
        ),
    ):
        context_pack, profile_file, profile, worktree, _model_home, _secret = _prepared_case(
            tmp_path / name
        )
        mutate(profile)
        expected_hash = _write_profile(profile_file, profile)
        with pytest.raises(ValueError):
            _launcher(
                worktree=worktree,
                profile_file=profile_file,
                expected_profile_sha256=expected_hash,
                runner=runner,
            ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "principal-drift"
    )

    def drifted_principal(user: str, group: str) -> ResolvedPrincipal:
        resolved = _principal_resolver(user, group)
        if user == WORKER.user:
            return ResolvedPrincipal(user, WORKER.uid + 1, group, WORKER.gid)
        return resolved

    with pytest.raises(ValueError, match="principal"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            principal_resolver=drifted_principal,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "worktree-drift"
    )
    with pytest.raises(ValueError, match="worktree"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            worktree_head_resolver=lambda _path, _git: "c" * 40,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "systemd-drift"
    )
    with pytest.raises(ValueError, match="systemd"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            systemd_preflight=lambda: ExecutableIdentity(
                path=SYSTEMD_RUN.path,
                device=SYSTEMD_RUN.device,
                inode=SYSTEMD_RUN.inode + 1,
                sha256=SYSTEMD_RUN.sha256,
                mode=SYSTEMD_RUN.mode,
                owner_uid=SYSTEMD_RUN.owner_uid,
                owner_gid=SYSTEMD_RUN.owner_gid,
            ),
        ).launch(context_pack)

    for name, owner_uid, owner_gid, mode in (
        ("model-uid", WORKER.uid + 1, WORKER.gid, 0o700),
        ("model-gid", WORKER.uid, WORKER.gid + 1, 0o700),
        ("model-mode", WORKER.uid, WORKER.gid, 0o750),
    ):
        context_pack, profile_file, _profile, worktree, model_home, _secret = _prepared_case(
            tmp_path / name
        )

        def drifted_model_home(
            path: Path,
            *,
            expected_path: Path = model_home,
            expected_uid: int = owner_uid,
            expected_gid: int = owner_gid,
            expected_mode: int = mode,
        ) -> os.stat_result:
            metadata = _model_home_lstat(path)
            if path != expected_path:
                return metadata
            values = list(metadata)
            values[0] = (metadata.st_mode & ~0o777) | expected_mode
            values[4] = expected_uid
            values[5] = expected_gid
            return os.stat_result(values)

        with pytest.raises(ValueError, match="model auth home"):
            _launcher(
                worktree=worktree,
                profile_file=profile_file,
                expected_profile_sha256=file_sha256(profile_file),
                runner=runner,
                path_lstat_resolver=drifted_model_home,
            ).launch(context_pack)

    context_pack, profile_file, profile, worktree, model_home, _secret = _prepared_case(
        tmp_path / "model-alias"
    )
    model_alias = model_home.parent / "model-home-alias"
    model_alias.symlink_to(model_home, target_is_directory=True)
    model_stat = model_home.stat()
    profile["model_auth"] = {
        "home": str(model_alias),
        "reference": "codex-worker-subscription-v1",
        "device": model_stat.st_dev,
        "inode": model_stat.st_ino,
    }
    expected_hash = _write_profile(profile_file, profile)
    with pytest.raises(ValueError, match="model auth home"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=expected_hash,
            runner=runner,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "git-drift"
    )

    def drifted_git(path: str) -> ExecutableIdentity:
        identity = _executable_resolver(path)
        if path == GIT_EXECUTABLE.path:
            return ExecutableIdentity(
                path=path,
                device=identity.device,
                inode=identity.inode + 1,
                sha256=identity.sha256,
                mode=identity.mode,
                owner_uid=identity.owner_uid,
                owner_gid=identity.owner_gid,
            )
        return identity

    with pytest.raises(ValueError, match="Git executable identity"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            executable_resolver=drifted_git,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "executable-in-place-drift"
    )

    def drifted_codex_content(path: str) -> ExecutableIdentity:
        identity = _executable_resolver(path)
        if path == CODEX_EXECUTABLE.path:
            return ExecutableIdentity(
                path=identity.path,
                device=identity.device,
                inode=identity.inode,
                sha256="f" * 64,
                mode=identity.mode,
                owner_uid=identity.owner_uid,
                owner_gid=identity.owner_gid,
            )
        return identity

    with pytest.raises(ValueError, match="executable identity"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            executable_resolver=drifted_codex_content,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "git-directory-drift"
    )
    wrong_git_directory = worktree.parent / "wrong-git-admin"
    wrong_git_directory.mkdir()
    with pytest.raises(ValueError, match="Git directory"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            worktree_git_topology_resolver=lambda _path, _git: (
                wrong_git_directory,
                _git_common(worktree),
            ),
        ).launch(context_pack)

    context_pack, profile_file, profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "git-common-overlaps-worktree"
    )
    overlapping_common = worktree / "feature"
    overlapping_stat = overlapping_common.stat()
    worktree_profile = dict(profile["worktree"])  # type: ignore[arg-type]
    worktree_profile["git_common_directory"] = {
        "path": str(overlapping_common),
        "device": overlapping_stat.st_dev,
        "inode": overlapping_stat.st_ino,
    }
    profile["worktree"] = worktree_profile
    with pytest.raises(ValueError, match="writable paths overlap"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=_write_profile(profile_file, profile),
            runner=runner,
        ).launch(context_pack)

    executable = tmp_path / "same-inode-tool"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    first_executable = resolve_executable(str(executable))
    executable.write_bytes(b"#!/bin/sh\nexit 1\n")
    second_executable = resolve_executable(str(executable))
    assert first_executable.device == second_executable.device
    assert first_executable.inode == second_executable.inode
    assert first_executable.sha256 != second_executable.sha256
    assert first_executable.mode == 0o755
    assert first_executable.owner_uid == os.geteuid()

    executable.chmod(0o775)
    with pytest.raises(ValueError, match="executable"):
        resolve_executable(str(executable))

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "executable-drift-after-probes"
    )
    executable_calls: dict[str, int] = {}
    ordering: list[str] = []

    def post_probe_executable_drift(path: str) -> ExecutableIdentity:
        identity = _executable_resolver(path)
        executable_calls[path] = executable_calls.get(path, 0) + 1
        if path == CODEX_EXECUTABLE.path and executable_calls[path] == 3:
            ordering.append("final-executable-drift")
            return ExecutableIdentity(
                path=identity.path,
                device=identity.device,
                inode=identity.inode,
                sha256="e" * 64,
                mode=identity.mode,
                owner_uid=identity.owner_uid,
                owner_gid=identity.owner_gid,
            )
        return identity

    def ordered_credential_probe(*args: object) -> CredentialProbeResult:
        ordering.append("credential-probe")
        return _production_probe_with_outcome(errno.EACCES)(*args)

    def ordered_worker_access_probe(*args: object) -> WorkerAccessProbeResult:
        ordering.append("worker-access-probe")
        return _production_access_probe_with_outcome(
            worktree_access=True,
            git_metadata_writable=False,
        )(*args)

    with pytest.raises(ValueError, match="Codex executable identity"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            credential_probe=ordered_credential_probe,
            worker_access_probe=ordered_worker_access_probe,
            executable_resolver=post_probe_executable_drift,
        ).launch(context_pack)
    assert ordering == [
        "credential-probe",
        "worker-access-probe",
        "final-executable-drift",
    ]

    context_pack, profile_file, profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "unsafe-executable-owner"
    )
    codex_profile = dict(profile["codex_executable"])  # type: ignore[arg-type]
    codex_profile["owner_uid"] = WORKER.uid
    profile["codex_executable"] = codex_profile
    with pytest.raises(ValueError, match="executable owner"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=_write_profile(profile_file, profile),
            runner=runner,
        ).launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "unsupported"
    )
    with pytest.raises(ValueError, match="unsupported"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            platform_name="darwin",
        ).launch(context_pack)

    context_pack, profile_file, profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "shell"
    )
    profile["command_sha256"] = canonical_command_sha256(["/bin/sh", "-c", "codex"])
    expected_hash = _write_profile(profile_file, profile)
    launcher = _launcher(
        worktree=worktree,
        profile_file=profile_file,
        expected_profile_sha256=expected_hash,
        runner=runner,
    )
    monkeypatch.setattr(launcher, "command", lambda *_args, **_kwargs: ["/bin/sh", "-c", "codex"])
    with pytest.raises(ValueError, match="shell"):
        launcher.launch(context_pack)

    context_pack, profile_file, _profile, worktree, _model_home, _secret = _prepared_case(
        tmp_path / "unit-token"
    )
    with pytest.raises(ValueError, match="unit identity"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            unit_token=lambda: "../../unsafe",
        ).launch(context_pack)

    source_repository = tmp_path / "linked-worktree-source"
    source_repository.mkdir()
    subprocess.run(["git", "init", "-q", str(source_repository)], check=True)
    source_tracked = source_repository / "tracked.txt"
    source_tracked.write_text("frozen\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source_repository), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source_repository),
            "-c",
            "user.name=Isolation Test",
            "-c",
            "user.email=isolation@example.test",
            "commit",
            "-q",
            "-m",
            "Freeze fixture",
        ],
        check=True,
    )
    frozen_worktree = tmp_path / "frozen-worktree"
    subprocess.run(
        [
            "git",
            "-C",
            str(source_repository),
            "worktree",
            "add",
            "-q",
            "-b",
            "linked-worker-test",
            str(frozen_worktree),
        ],
        check=True,
    )
    tracked = frozen_worktree / "tracked.txt"
    selected_git = shutil.which("git")
    assert selected_git is not None
    git_path = str(Path(selected_git).resolve(strict=True))
    real_run = subprocess.run
    observed_git_calls: list[tuple[list[str], dict[str, object]]] = []

    def capture_git(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed_git_calls.append((list(command), dict(kwargs)))
        return real_run(command, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "app.builderops.issue_delivery_worker_isolation.subprocess.run",
        capture_git,
    )
    assert (
        resolve_worktree_head(frozen_worktree, git_path)
        == real_run(
            [git_path, "-C", str(frozen_worktree), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    resolved_git_directory, resolved_common_directory = resolve_worktree_git_topology(
        frozen_worktree, git_path
    )
    assert resolved_git_directory.is_relative_to(source_repository / ".git" / "worktrees")
    assert not resolved_git_directory.is_relative_to(frozen_worktree)
    assert resolved_common_directory == source_repository / ".git"
    assert len(observed_git_calls) == 3
    for command, kwargs in observed_git_calls:
        assert command[0] == git_path
        assert kwargs["env"] == {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
        }
    tracked.write_text("mutable\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not frozen"):
        resolve_worktree_head(frozen_worktree, git_path)
    with pytest.raises(ValueError, match="linked Git worktree"):
        resolve_worktree_git_topology(source_repository, git_path)
    assert started == []


def test_isolation_receipt_keeps_model_and_repository_authority_separate(
    tmp_path: Path,
) -> None:
    context_pack, profile_file, _profile, worktree, model_home, secret = _prepared_case(
        tmp_path / "receipt"
    )
    invocations: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocations.append((list(command), dict(kwargs)))
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "session-receipt"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": json.dumps(_worker_receipt()),
                        },
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    result = _launcher(
        worktree=worktree,
        profile_file=profile_file,
        expected_profile_sha256=file_sha256(profile_file),
        runner=runner,
    ).launch(context_pack)

    command, kwargs = invocations[0]
    child = command[command.index("--") + 1 :]
    codex_index = child.index(CODEX_EXECUTABLE.path)
    environment = dict(item.split("=", 1) for item in child[2:codex_index])
    assert environment == {
        "CODEX_HOME": str(model_home),
        "HOME": str(model_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/opt/codex/bin:/usr/bin:/bin",
    }
    assert not any(key.startswith(("GH_", "GITHUB_", "GIT_")) for key in environment)
    prompt = str(kwargs["input"])
    assert str(secret) not in prompt
    assert "github_pat_DO_NOT_LEAK" not in prompt
    assert str(secret) not in "\0".join(command)

    receipt = result["isolation_receipt"]
    rendered_receipt = json.dumps(receipt, sort_keys=True)
    assert receipt["contract"] == "builderops_issue_delivery_worker_isolation_receipt.v1"
    assert receipt["profile_id"] == "bob-issue-delivery-worker"
    assert receipt["profile_sha256"] == file_sha256(profile_file)
    assert receipt["command_sha256"] == canonical_command_sha256(
        [CODEX_EXECUTABLE.path, *child[codex_index + 1 :]]
    )
    emitted_properties = [
        item.removeprefix("--property=") for item in command if item.startswith("--property=")
    ]
    assert receipt["isolation_properties_sha256"] == canonical_command_sha256(emitted_properties)
    assert receipt["isolation_template_sha256"] == REQUIRED_SYSTEMD_PROPERTIES_SHA256
    assert len(receipt["executable_set_identity_sha256"]) == 64
    assert receipt["model_auth_reference"] == "codex-worker-subscription-v1"
    assert receipt["child_environment_keys"] == sorted(environment)
    assert receipt["entered_at"] == "2026-09-15T10:00:00Z"
    assert str(secret) not in rendered_receipt
    assert str(model_home) not in rendered_receipt
    assert "github_pat_DO_NOT_LEAK" not in rendered_receipt
