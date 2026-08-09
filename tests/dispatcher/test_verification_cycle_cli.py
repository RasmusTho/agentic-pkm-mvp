from __future__ import annotations

import hashlib
import json
import signal
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from app.dispatcher import cli as dispatcher_cli
from app.dispatcher import darwin_containment
from app.dispatcher import verification_consumer
from app.dispatcher import verification_github
from app.dispatcher import verification_merge
from app.dispatcher import verification_runtime
from app.dispatcher.verification_github import HostCredentialManifestResolver
from app.dispatcher.verification_merge import MergeAuthorityError


REPO = "RasmusTho/agentic-pkm-mvp"
HEAD = "a" * 40
CONTAINMENT_PROFILE = "darwin-launchd-resource-coalition-v1"


def _request() -> dict[str, object]:
    return {
        "contract_version": "verification_dispatch_request.v3",
        "repository": REPO,
        "pr_number": 4677,
        "head_sha": HEAD,
        "linked_issue": 4677,
    }


def _cycle_args(request_file: Path) -> list[str]:
    return [
        "verification-cycle",
        str(request_file),
        "--containment-profile",
        CONTAINMENT_PROFILE,
        "--json",
    ]


def _allow_containment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dispatcher_cli,
        "select_verification_containment",
        lambda profile: (
            (lambda: object())
            if profile == CONTAINMENT_PROFILE
            else (_ for _ in ()).throw(ValueError("unsupported containment"))
        ),
    )


class _Client:
    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Runtime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def run_dry_cycle(self, request: dict[str, object]) -> dict[str, object]:
        self.calls.append(("run", request))
        return self._receipt("vrun-test")

    def recover_dry_cycle(self, run_id: str) -> dict[str, object]:
        self.calls.append(("recover", run_id))
        return self._receipt(run_id)

    @staticmethod
    def _receipt(run_id: str) -> dict[str, object]:
        return {
            "contract": "bcp05_demerzel_cycle.v1",
            "governing_issue": 4677,
            "repository": REPO.lower(),
            "pr_number": 4677,
            "head_sha": HEAD,
            "run_id": run_id,
            "terminal_outcome": "dry_run_no_merge",
            "operation_key": "verification:dry-run:test",
            "readback": {
                "merged": False,
                "head_sha": HEAD,
                "outcome": "dry_run_no_merge",
                "credential_binding_resolved": True,
            },
            "merge_authority": {
                "base_sha": "b" * 40,
                "manifest_blob_sha": "c" * 40,
                "manifest_sha256": "d" * 64,
                "credential_id": "repo-reader",
                "credential_generation": 1,
            },
            "raw_secret_count": 0,
        }


def test_cycle_command_composes_api_outbox_and_host_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = _Client()
    credentials = SimpleNamespace(
        resolve_repository_read_token=lambda repository: (
            "github-secret" if repository == REPO else None
        )
    )
    outbox = object()
    ledger = SimpleNamespace(effect_outbox=outbox)
    truth = object()
    auth = object()
    launcher = object()
    exact_launcher = object()
    containment_factory = lambda: object()
    consumer = object()
    repository = SimpleNamespace(close=lambda: None)
    executor = object()
    runtime = _Runtime()
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        verification_github.HostCredentialManifestResolver,
        "from_env",
        classmethod(lambda cls: credentials),
    )
    monkeypatch.setattr(
        verification_merge,
        "BuilderOpsOutboxExecutor",
        lambda actual_client, *, repository, worker_id: (
            seen.update(
                client=actual_client,
                outbox_repository=repository,
                worker_id=worker_id,
            )
            or outbox
        ),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_new_verification_ledger",
        lambda actual_client, *, repository, effect_outbox: (
            seen.update(
                ledger_client=actual_client,
                ledger_repository=repository,
                ledger_outbox=effect_outbox,
            )
            or ledger
        ),
    )
    monkeypatch.setattr(
        verification_consumer,
        "GhCliVerificationSource",
        lambda: truth,
    )
    monkeypatch.setattr(
        verification_consumer,
        "CodexChatGPTAuthPreflight",
        lambda config_path: seen.update(config_path=config_path) or auth,
    )
    monkeypatch.setattr(
        verification_consumer,
        "CodexExecLauncher",
        lambda worktree, receipt_schema, context_path, *, containment_factory: (
            seen.update(
                worktree=worktree,
                receipt_schema=receipt_schema,
                context_path=context_path,
                containment_factory=containment_factory,
            )
            or launcher
        ),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_InstalledMainExactHeadLauncher",
        lambda actual_launcher, *, installed_main, context_path: (
            seen.update(
                raw_launcher=actual_launcher,
                installed_main=installed_main,
                exact_context_path=context_path,
            )
            or exact_launcher
        ),
    )
    monkeypatch.setattr(
        verification_consumer,
        "VerificationConsumer",
        lambda actual_ledger, actual_truth, actual_auth, actual_launcher, holder: (
            seen.update(
                consumer_ledger=actual_ledger,
                truth=actual_truth,
                auth=actual_auth,
                launcher=actual_launcher,
                consumer_holder=holder,
            )
            or consumer
        ),
    )
    monkeypatch.setattr(
        verification_github,
        "GitHubProtectedRepositoryAuthority",
        lambda token: seen.update(read_token=token) or repository,
    )
    monkeypatch.setattr(
        verification_merge,
        "VerificationMergeExecutor",
        lambda actual_ledger, actual_outbox, actual_repository, actual_credentials: (
            seen.update(
                executor_ledger=actual_ledger,
                executor_outbox=actual_outbox,
                repository=actual_repository,
                credentials=actual_credentials,
            )
            or executor
        ),
    )
    monkeypatch.setattr(
        verification_runtime,
        "HostFencedVerificationCycle",
        lambda actual_ledger, actual_consumer, actual_executor, *, holder: (
            seen.update(
                runtime_ledger=actual_ledger,
                consumer=actual_consumer,
                executor=actual_executor,
                runtime_holder=holder,
            )
            or runtime
        ),
    )

    built, close_repository = dispatcher_cli._build_host_fenced_verification_cycle(
        client,
        repository=REPO,
        holder="verification-host",
        worktree=tmp_path,
        context_path=tmp_path / "context.json",
        containment_factory=containment_factory,
    )

    assert built is runtime
    assert close_repository is repository.close
    assert seen["client"] is client
    assert seen["ledger_client"] is client
    assert seen["ledger_outbox"] is outbox
    assert seen["consumer_ledger"] is ledger
    assert seen["raw_launcher"] is launcher
    assert seen["containment_factory"] is containment_factory
    assert seen["launcher"] is exact_launcher
    assert seen["executor_ledger"] is ledger
    assert seen["executor_outbox"] is outbox
    assert seen["runtime_ledger"] is ledger
    assert seen["credentials"] is credentials
    assert seen["read_token"] == "github-secret"
    assert seen["consumer_holder"] == "verification-host"
    assert seen["runtime_holder"] == "verification-host"


def test_exact_head_launcher_supplies_immutable_review_patch(
    tmp_path: Path,
) -> None:
    head_sha = "a" * 40
    context_path = tmp_path / "context.json"
    calls: list[tuple[list[str], dict[str, object]]] = []

    class _Inner:
        config = SimpleNamespace(adapter_name="verification_closer")

        def launch(self, context_pack, **kwargs):
            source = context_pack["review_source"]
            patch_path = Path(source["patch_path"])
            assert patch_path.read_text(encoding="utf-8") == "diff --git exact\n"
            calls.append((["inner"], {**kwargs, "source": source}))
            return "session", {"verdict": "verified"}

    def _git(command: list[str], **_kwargs: object) -> SimpleNamespace:
        if command[3:5] == ["cat-file", "-e"]:
            return SimpleNamespace(returncode=0, stdout="")
        assert command[3:6] == ["diff", "--binary", "--no-ext-diff"]
        return SimpleNamespace(returncode=0, stdout="diff --git exact\n")

    launcher = dispatcher_cli._InstalledMainExactHeadLauncher(
        _Inner(),
        installed_main=tmp_path,
        context_path=context_path,
        git_runner=_git,
    )
    result = launcher.launch(
        {
            "head_sha": head_sha,
            "merge_execution_mode": "host_fenced_executor",
        },
        resume_session_id="session-prior",
    )

    assert result[0] == "session"
    source = calls[0][1]["source"]
    assert source["head_sha"] == head_sha
    assert source["patch_sha256"] == hashlib.sha256(
        b"diff --git exact\n"
    ).hexdigest()
    assert not Path(source["patch_path"]).exists()


def test_cycle_command_runs_and_recovers_dry_cycle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    _allow_containment(monkeypatch)
    runtime = _Runtime()
    monkeypatch.setattr(
        dispatcher_cli,
        "_make_verification_client",
        lambda: _Client(),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_build_host_fenced_verification_cycle",
        lambda *_args, **_kwargs: (runtime, lambda: None),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_assert_installed_main_worktree",
        lambda _worktree, _repository: None,
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_make_store",
        lambda: (_ for _ in ()).throw(
            AssertionError("verification command opened dispatcher SQLite")
        ),
    )

    assert (
        dispatcher_cli.main(
            [
                "verification-cycle",
                str(request_file),
                "--holder",
                "verification-host",
                "--containment-profile",
                CONTAINMENT_PROFILE,
                "--json",
            ]
        )
        == 0
    )
    run_output = json.loads(capsys.readouterr().out)
    assert run_output["receipt"]["run_id"] == "vrun-test"
    assert runtime.calls == [("run", _request())]

    assert (
        dispatcher_cli.main(
            [
                "verification-cycle",
                "--recover-run-id",
                "vrun-test",
                "--repo",
                REPO,
                "--holder",
                "verification-host",
                "--containment-profile",
                CONTAINMENT_PROFILE,
                "--json",
            ]
        )
        == 0
    )
    recover_output = json.loads(capsys.readouterr().out)
    assert recover_output["receipt"]["run_id"] == "vrun-test"
    assert runtime.calls[-1] == ("recover", "vrun-test")


def test_cycle_command_rejects_missing_or_ambiguous_host_credential_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("never-print", encoding="utf-8")
    manifest = tmp_path / "credentials.json"
    monkeypatch.setenv(
        "BUILDEROPS_EXECUTOR_CREDENTIAL_MANIFEST_FILE",
        str(manifest),
    )

    for credentials in ([], [
        {
            "repository": REPO,
            "credential_id": "one",
            "rotation_generation": 1,
            "secret_file": str(secret_file),
        },
        {
            "repository": REPO,
            "credential_id": "two",
            "rotation_generation": 1,
            "secret_file": str(secret_file),
        },
    ]):
        manifest.write_text(
            json.dumps({"credentials": credentials}),
            encoding="utf-8",
        )
        resolver = HostCredentialManifestResolver.from_env()
        with pytest.raises(
            MergeAuthorityError,
            match="repository credential binding is missing or ambiguous",
        ):
            resolver.resolve_repository_read_token(REPO)

    for invalid_generation in (True, 1.0, 0):
        manifest.write_text(
            json.dumps(
                {
                    "credentials": [
                        {
                            "repository": REPO,
                            "credential_id": "one",
                            "rotation_generation": invalid_generation,
                            "secret_file": str(secret_file),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        resolver = HostCredentialManifestResolver.from_env()
        with pytest.raises(
            MergeAuthorityError, match="credential manifest is malformed"
        ):
            resolver.resolve(
                repository=REPO,
                credential_id="one",
                rotation_generation=1,
            )


def test_cycle_command_output_is_secret_free_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "github_pat_NEVER_PRINT_THIS_VALUE"
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    _allow_containment(monkeypatch)
    monkeypatch.setattr(
        dispatcher_cli,
        "_make_verification_client",
        lambda: _Client(),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_build_host_fenced_verification_cycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_assert_installed_main_worktree",
        lambda _worktree, _repository: None,
    )

    assert (
        dispatcher_cli.main(
            _cycle_args(request_file)
        )
        == 1
    )
    output = capsys.readouterr()
    encoded = output.out + output.err
    assert secret not in encoded
    payload = json.loads(output.out)
    assert payload == {
        "ok": False,
        "error": "verification cycle failed closed",
        "error_type": "RuntimeError",
    }

    runtime = _Runtime()
    original_run = runtime.run_dry_cycle

    def _unsafe_success(
        request: dict[str, object],
    ) -> dict[str, object]:
        return {**original_run(request), "raw_token": secret}

    runtime.run_dry_cycle = _unsafe_success  # type: ignore[method-assign]
    monkeypatch.setattr(
        dispatcher_cli,
        "_build_host_fenced_verification_cycle",
        lambda *_args, **_kwargs: (runtime, lambda: None),
    )
    assert (
        dispatcher_cli.main(
            _cycle_args(request_file)
        )
        == 1
    )
    output = capsys.readouterr()
    encoded = output.out + output.err
    assert secret not in encoded
    assert json.loads(output.out)["error_type"] == "ValueError"

    runtime = _Runtime()
    original_run = runtime.run_dry_cycle

    def _nested_unsafe_success(
        request: dict[str, object],
    ) -> dict[str, object]:
        receipt = original_run(request)
        return {
            **receipt,
            "readback": {
                **dict(receipt["readback"]),  # type: ignore[arg-type]
                "api_token": secret,
            },
        }

    runtime.run_dry_cycle = _nested_unsafe_success  # type: ignore[method-assign]
    monkeypatch.setattr(
        dispatcher_cli,
        "_build_host_fenced_verification_cycle",
        lambda *_args, **_kwargs: (runtime, lambda: None),
    )
    assert (
        dispatcher_cli.main(
            _cycle_args(request_file)
        )
        == 1
    )
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert json.loads(output.out)["error_type"] == "ValueError"

    unsafe_authority = _Runtime._receipt("vrun-test")
    unsafe_authority["merge_authority"] = {
        **dict(unsafe_authority["merge_authority"]),  # type: ignore[arg-type]
        "credential_id": {"api_token": secret},
    }
    with pytest.raises(ValueError, match="receipt is malformed"):
        dispatcher_cli._public_verification_cycle_receipt(unsafe_authority)


def test_cycle_command_rejects_non_installed_main_worktree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    built = False

    def _unexpected_build(*_args: object, **_kwargs: object) -> object:
        nonlocal built
        built = True
        raise AssertionError("composition ran before worktree preflight")

    monkeypatch.setattr(
        dispatcher_cli,
        "_assert_installed_main_worktree",
        lambda _worktree, _repository: (_ for _ in ()).throw(
            ValueError("verification worktree must be exact clean main")
        ),
    )
    monkeypatch.setattr(
        dispatcher_cli,
        "_build_host_fenced_verification_cycle",
        _unexpected_build,
    )

    assert (
        dispatcher_cli.main(
            ["verification-cycle", str(request_file), "--json"]
        )
        == 1
    )
    assert built is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_type"] == "ValueError"


def test_installed_main_preflight_binds_source_and_target_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "app" / "dispatcher" / "cli.py"
    source_file.parent.mkdir(parents=True)
    source_file.touch()
    monkeypatch.setattr(dispatcher_cli, "__file__", str(source_file))

    responses = {
        ("rev-parse", "--show-toplevel"): str(tmp_path),
        ("symbolic-ref", "--short", "HEAD"): "main",
        ("rev-parse", "HEAD"): HEAD,
        ("rev-parse", "refs/remotes/origin/main"): HEAD,
        ("remote", "get-url", "origin"): (
            "git@github.com:someone/another-repo.git"
        ),
        ("status", "--porcelain"): "",
    }

    def _run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0,
            stdout=responses[tuple(command[3:])],
        )

    monkeypatch.setattr(dispatcher_cli.subprocess, "run", _run)

    with pytest.raises(ValueError, match="exact clean origin/main"):
        dispatcher_cli._assert_installed_main_worktree(tmp_path, REPO)

    responses[("remote", "get-url", "origin")] = (
        "https://github.com/RasmusTho/agentic-pkm-mvp.git"
    )
    dispatcher_cli._assert_installed_main_worktree(tmp_path, REPO)

    monkeypatch.setattr(
        dispatcher_cli,
        "__file__",
        str(tmp_path.parent / "other" / "app" / "dispatcher" / "cli.py"),
    )
    with pytest.raises(ValueError, match="exact clean origin/main"):
        dispatcher_cli._assert_installed_main_worktree(tmp_path, REPO)


class _FakeDarwinKernel:
    def __init__(self) -> None:
        self.identities = {
            1: darwin_containment.ProcessIdentity(1, 1, 10, 0, 99),
            90: darwin_containment.ProcessIdentity(90, 2, 90, 10, 7),
            100: darwin_containment.ProcessIdentity(100, 3, 100, 90, 7),
        }
        self.task_count_override: int | None = None
        self.pid_reads: list[tuple[int, ...]] = []
        self.signal_callback: Callable[[int, int], None] | None = None

    def list_pids(self) -> tuple[int, ...]:
        if self.pid_reads:
            return self.pid_reads.pop(0)
        return tuple(self.identities)

    def inspect(self, pid: int) -> darwin_containment.ProcessIdentity | None:
        return self.identities.get(pid)

    def coalition_task_count(self, coalition_id: int) -> int:
        if self.task_count_override is not None:
            return self.task_count_override
        return sum(
            identity.coalition_id == coalition_id
            for identity in self.identities.values()
        )

    def signal(
        self, identity: darwin_containment.ProcessIdentity, sig: int
    ) -> bool:
        current = self.identities.get(identity.pid)
        if current is None or (
            current.pid_version,
            current.unique_id,
            current.coalition_id,
        ) != (
            identity.pid_version,
            identity.unique_id,
            identity.coalition_id,
        ):
            return False
        if self.signal_callback is not None:
            self.signal_callback(identity.pid, sig)
        else:
            self.identities.pop(identity.pid, None)
        return True


def test_cycle_requires_supported_containment_profile_before_api_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    client_opened = False

    def _unexpected_client() -> _Client:
        nonlocal client_opened
        client_opened = True
        return _Client()

    monkeypatch.setattr(
        dispatcher_cli, "_assert_installed_main_worktree", lambda *_args: None
    )
    monkeypatch.setattr(
        dispatcher_cli, "_make_verification_client", _unexpected_client
    )

    assert dispatcher_cli.main(
        ["verification-cycle", str(request_file), "--json"]
    ) == 1
    assert json.loads(capsys.readouterr().out)["error_type"] == "ValueError"
    assert client_opened is False

    assert dispatcher_cli.main(
        [
            "verification-cycle",
            str(request_file),
            "--containment-profile",
            "unsupported-profile",
            "--json",
        ]
    ) == 1
    assert json.loads(capsys.readouterr().out)["error_type"] == "ValueError"
    assert client_opened is False


def test_cycle_composition_injects_darwin_launchd_coalition_containment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    kernel = _FakeDarwinKernel()
    signalled: list[tuple[int, int]] = []

    def signaler(pid: int, sig: int) -> None:
        signalled.append((pid, sig))
        kernel.identities.pop(pid, None)

    kernel.signal_callback = signaler

    factory = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
    )
    containment = factory()
    assert containment.environment({"SAFE": "yes"}) == {"SAFE": "yes"}

    kernel.identities[200] = darwin_containment.ProcessIdentity(200, 4, 200, 100, 7)
    containment.attach(200)
    assert containment.cleanup() is True
    assert (200, signal.SIGTERM) in signalled


def test_darwin_private_abi_reads_pid_version_unique_ancestry_and_coalition() -> None:
    kernel = darwin_containment.DarwinLibprocKernel.__new__(
        darwin_containment.DarwinLibprocKernel
    )
    calls: list[tuple[int, int]] = []

    def pid_info(pid: int, flavor: int, _arg: int, buffer, size: int) -> int:
        calls.append((flavor, size))
        if flavor == 17:
            value = darwin_containment._ProcUniqIdentifierInfo.from_address(  # noqa: SLF001
                darwin_containment.ctypes.addressof(buffer._obj)
            )
            value.p_uniqueid = 900
            value.p_puniqueid = 800
            value.p_idversion = 7
            return darwin_containment.ctypes.sizeof(value)
        value = darwin_containment._ProcPidCoalitionInfo.from_address(  # noqa: SLF001
            darwin_containment.ctypes.addressof(buffer._obj)
        )
        value.coalition_id[0] = 42
        return darwin_containment.ctypes.sizeof(value)

    kernel._pid_info = pid_info  # type: ignore[attr-defined]  # noqa: SLF001

    assert kernel.inspect(123) == darwin_containment.ProcessIdentity(
        123, 7, 900, 800, 42
    )
    assert calls == [(17, 56), (20, 40), (17, 56)]


def test_darwin_signal_uses_pid_version_bound_audit_token() -> None:
    kernel = darwin_containment.DarwinLibprocKernel.__new__(
        darwin_containment.DarwinLibprocKernel
    )
    seen: dict[str, object] = {}

    def signal_with_token(token_pointer, sig: int) -> int:
        token = token_pointer._obj
        seen.update(pid=token.val[5], pid_version=token.val[7], sig=sig)
        return 0

    kernel._signal_with_audit_token = signal_with_token  # type: ignore[attr-defined]  # noqa: SLF001
    identity = darwin_containment.ProcessIdentity(123, 7, 900, 800, 42)

    assert kernel.signal(identity, signal.SIGKILL) is True
    assert seen == {"pid": 123, "pid_version": 7, "sig": signal.SIGKILL}


def test_containment_refuses_pid_reuse_between_snapshot_and_signal() -> None:
    class ReusingKernel(_FakeDarwinKernel):
        def __init__(self) -> None:
            super().__init__()
            self.child_inspections = 0
            self.reuse_at: int | None = None

        def inspect(self, pid: int) -> darwin_containment.ProcessIdentity | None:
            if pid == 200:
                self.child_inspections += 1
                if self.reuse_at == self.child_inspections:
                    self.identities[200] = darwin_containment.ProcessIdentity(
                        200, 5, 201, 100, 7
                    )
            return super().inspect(pid)

    kernel = ReusingKernel()
    factory = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
        sleeper=lambda _seconds: None,
    )
    containment = factory()
    containment.environment({})
    kernel.identities[200] = darwin_containment.ProcessIdentity(
        200, 4, 200, 100, 7
    )
    containment.attach(200)
    original_signal = kernel.signal

    def reuse_before_atomic_signal(
        identity: darwin_containment.ProcessIdentity, sig: int
    ) -> bool:
        kernel.identities[200] = darwin_containment.ProcessIdentity(
            200, 5, 201, 100, 7
        )
        return original_signal(identity, sig)

    kernel.signal = reuse_before_atomic_signal  # type: ignore[method-assign]

    assert containment.cleanup() is False
    assert kernel.identities[200].pid_version == 5


def test_cleanup_accepts_child_reparented_after_parent_signal() -> None:
    kernel = _FakeDarwinKernel()
    signalled: list[int] = []

    def signaler(pid: int, _sig: int) -> None:
        signalled.append(pid)
        kernel.identities.pop(pid, None)
        if pid == 200:
            child = kernel.identities[201]
            kernel.identities[201] = darwin_containment.ProcessIdentity(
                child.pid,
                child.pid_version,
                child.unique_id,
                100,
                child.coalition_id,
            )

    kernel.signal_callback = signaler
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
        sleeper=lambda _seconds: None,
    )()
    containment.environment({})
    kernel.identities[200] = darwin_containment.ProcessIdentity(
        200, 4, 200, 100, 7
    )
    kernel.identities[201] = darwin_containment.ProcessIdentity(
        201, 4, 201, 200, 7
    )
    containment.attach(200)

    assert containment.cleanup() is True
    assert signalled == [200, 201]


def test_cleanup_reaps_detached_child_when_root_exits_before_attach() -> None:
    """A vanished Popen root must not strand its proven coalition child."""

    kernel = _FakeDarwinKernel()
    signalled: list[int] = []

    def signaler(pid: int, _sig: int) -> None:
        signalled.append(pid)
        kernel.identities.pop(pid, None)

    kernel.signal_callback = signaler
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
        sleeper=lambda _seconds: None,
    )()
    containment.environment({})
    # PID 200 was the Popen root but exited after creating this detached
    # same-coalition child.  Its unique identity remains the child's parent.
    kernel.identities[201] = darwin_containment.ProcessIdentity(
        201, 4, 201, 200, 7
    )

    with pytest.raises(ValueError, match="root exited before attach"):
        containment.attach(200)

    assert containment.cleanup() is True
    assert signalled == [201]
    assert 201 not in kernel.identities


def test_containment_rejects_unrelated_member_when_root_exits_before_attach() -> None:
    kernel = _FakeDarwinKernel()
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
    )()
    containment.environment({})
    kernel.identities[201] = darwin_containment.ProcessIdentity(
        201, 4, 201, 200, 7
    )
    # This member is not descended from the exited launch root: its parent is
    # part of the protected baseline and must never become a cleanup target.
    kernel.identities[300] = darwin_containment.ProcessIdentity(
        300, 4, 300, 100, 7
    )

    with pytest.raises(ValueError, match="ancestry escaped root"):
        containment.attach(200)


def test_containment_rejects_root_pid_reuse_before_orphan_cleanup() -> None:
    kernel = _FakeDarwinKernel()
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
    )()
    containment.environment({})
    kernel.identities[201] = darwin_containment.ProcessIdentity(
        201, 4, 201, 200, 7
    )
    # A reused Popen PID outside the resource coalition invalidates the
    # vanished-root proof before cleanup authority can be established.
    kernel.identities[200] = darwin_containment.ProcessIdentity(
        200, 5, 999, 100, 99
    )

    with pytest.raises(ValueError, match="launch root is unproven"):
        containment.attach(200)
    assert containment.cleanup() is False


def test_containment_rejects_unrelated_member_appearing_before_attach() -> None:
    kernel = _FakeDarwinKernel()
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
    )()
    containment.environment({})
    kernel.identities[200] = darwin_containment.ProcessIdentity(
        200, 4, 200, 100, 7
    )
    kernel.identities[300] = darwin_containment.ProcessIdentity(
        300, 4, 300, 100, 7
    )

    with pytest.raises(ValueError, match="ancestry escaped root"):
        containment.attach(200)


def test_cleanup_polls_until_delayed_kernel_task_disappearance() -> None:
    kernel = _FakeDarwinKernel()
    clock = [0.0]
    remove_at = [float("inf")]

    def signaler(_pid: int, _sig: int) -> None:
        remove_at[0] = clock[0] + 0.15

    def sleeper(seconds: float) -> None:
        clock[0] += seconds
        if clock[0] >= remove_at[0]:
            kernel.identities.pop(200, None)

    kernel.signal_callback = signaler
    containment = darwin_containment.select_verification_containment(
        CONTAINMENT_PROFILE,
        platform="darwin",
        kernel=kernel,
        current_pid=100,
        sleeper=sleeper,
        monotonic=lambda: clock[0],
    )()
    containment.environment({})
    kernel.identities[200] = darwin_containment.ProcessIdentity(
        200, 4, 200, 100, 7
    )
    containment.attach(200)

    assert containment.cleanup() is True
    assert clock[0] >= 0.15


@pytest.mark.parametrize("failure", ["shared", "count", "changing"])
def test_cycle_rejects_shared_or_unproven_coalition_before_api_claim(
    failure: str,
) -> None:
    kernel = _FakeDarwinKernel()
    if failure == "shared":
        kernel.identities[200] = darwin_containment.ProcessIdentity(200, 4, 200, 10, 7)
    elif failure == "count":
        kernel.task_count_override = 3
    else:
        kernel.pid_reads = [
            (1, 90, 100),
            (1, 90),
            (1, 90, 100),
            (1, 90),
            (1, 90, 100),
            (1, 90),
            (1, 90, 100),
            (1, 90),
        ]

    with pytest.raises(ValueError, match="containment"):
        darwin_containment.select_verification_containment(
            CONTAINMENT_PROFILE,
            platform="darwin",
            kernel=kernel,
            current_pid=100,
        )


def test_cycle_real_launcher_accepts_terminal_receipt_with_proven_containment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from tests.dispatcher.test_verification_consumer import (
        _CleanExitDetachedDescendantProcess,
        _EscapedDescendantContainment,
        _authority_loss_launcher,
    )

    process = _CleanExitDetachedDescendantProcess()
    containment = _EscapedDescendantContainment(process, proven=True)
    monkeypatch.setattr(
        verification_consumer.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        verification_consumer.os,
        "killpg",
        lambda process_group_id, sig: (_ for _ in ()).throw(
            ProcessLookupError(process_group_id)
        ),
    )

    session_id, receipt = _authority_loss_launcher(
        tmp_path,
        containment_factory=lambda: containment,
    ).launch({"head_sha": HEAD})

    assert session_id == "01900000-0000-7000-8000-000000000011"
    assert receipt["verdict"] == "blocked"
    assert containment.cleanup_calls == 1
