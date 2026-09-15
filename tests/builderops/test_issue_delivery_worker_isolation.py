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
    canonical_command_sha256,
    file_sha256,
    probe_credential_denial,
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
SYSTEMD_RUN = ExecutableIdentity(path="/usr/bin/systemd-run", device=11, inode=12)
ENV_EXECUTABLE = ExecutableIdentity(path="/usr/bin/env", device=21, inode=22)
GIT_EXECUTABLE = ExecutableIdentity(path="/usr/bin/git", device=25, inode=26)
CODEX_EXECUTABLE = ExecutableIdentity(path="/opt/codex/bin/codex", device=31, inode=32)


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
        },
        "environment_executable": {
            "path": ENV_EXECUTABLE.path,
            "device": ENV_EXECUTABLE.device,
            "inode": ENV_EXECUTABLE.inode,
        },
        "git_executable": {
            "path": GIT_EXECUTABLE.path,
            "device": GIT_EXECUTABLE.device,
            "inode": GIT_EXECUTABLE.inode,
        },
        "codex_executable": {
            "path": CODEX_EXECUTABLE.path,
            "device": CODEX_EXECUTABLE.device,
            "inode": CODEX_EXECUTABLE.inode,
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


def _probe_syscalls(open_errno: int | None) -> CredentialProbeSyscalls:
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


def _prepared_case(
    root: Path,
) -> tuple[dict[str, Any], Path, dict[str, object], Path, Path, Path]:
    root.mkdir(parents=True)
    worktree = root / "issue-5559"
    model_home = root / "worker-model-home"
    worktree.mkdir()
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
    principal_resolver: Any = None,
    worktree_head_resolver: Any = None,
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
        worktree_head_resolver=(
            worktree_head_resolver
            if worktree_head_resolver is not None
            else lambda _path, _git: FROZEN_HEAD
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
        worktree_head_resolver=lambda _path, _git: FROZEN_HEAD,
        systemd_preflight=lambda: SYSTEMD_RUN,
        executable_resolver=_executable_resolver,
        path_lstat_resolver=_model_home_lstat,
        runner=runner,
        unit_token=lambda: "0123456789abcdef",
        clock=lambda: "2026-09-15T10:00:00Z",
        platform_name="linux",
    )

    result = launcher.launch(context_pack)

    assert events == ["credential-probe", "systemd-entry"]
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
    assert f"--property=ReadWritePaths={model_home}" in command
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
            return ExecutableIdentity(path=path, device=identity.device, inode=identity.inode + 1)
        return identity

    with pytest.raises(ValueError, match="Git identity"):
        _launcher(
            worktree=worktree,
            profile_file=profile_file,
            expected_profile_sha256=file_sha256(profile_file),
            runner=runner,
            executable_resolver=drifted_git,
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

    frozen_worktree = tmp_path / "frozen-worktree"
    frozen_worktree.mkdir()
    subprocess.run(["git", "init", "-q", str(frozen_worktree)], check=True)
    tracked = frozen_worktree / "tracked.txt"
    tracked.write_text("frozen\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(frozen_worktree), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(frozen_worktree),
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
    assert len(observed_git_calls) == 2
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
    assert receipt["model_auth_reference"] == "codex-worker-subscription-v1"
    assert receipt["child_environment_keys"] == sorted(environment)
    assert receipt["entered_at"] == "2026-09-15T10:00:00Z"
    assert str(secret) not in rendered_receipt
    assert str(model_home) not in rendered_receipt
    assert "github_pat_DO_NOT_LEAK" not in rendered_receipt
