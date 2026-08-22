from __future__ import annotations

import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from app.dispatcher import cli as dispatcher_cli
from app.dispatcher import linux_containment
from app.dispatcher.darwin_containment import select_verification_containment
from app.dispatcher.linux_containment import (
    LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE,
    LinuxProcessIdentity,
    LinuxScopeIdentity,
    SystemdCgroupV2Kernel,
)
from app.dispatcher.verification_runtime import (
    validated_containment_receipt_shape,
)


class FakeLinuxKernel:
    def __init__(self) -> None:
        self.available = True
        self.scope_available = True
        self.scope = LinuxScopeIdentity(
            unit=f"yggdrasil-verification-{'f' * 24}.scope",
            cgroup_path="/user.slice/test.scope",
            cgroup_device=7,
            cgroup_inode=11,
        )
        self.identities: dict[int, LinuxProcessIdentity] = {
            200: LinuxProcessIdentity(200, 1000, 1, self.scope.cgroup_path),
            201: LinuxProcessIdentity(201, 1001, 200, self.scope.cgroup_path),
        }
        self.signalled: list[tuple[LinuxProcessIdentity, int]] = []
        self.drift_before_signal: set[int] = set()

    def preflight(self) -> None:
        if not self.available:
            raise ValueError("systemd/cgroup-v2 prerequisites are unavailable")

    def scope_command(
        self, scope_name: str, command: Sequence[str]
    ) -> list[str]:
        assert scope_name == self.scope.unit
        return ["systemd-run", "--user", "--scope", "--unit", scope_name, "--", *command]

    def scope_identity(self, scope_name: str) -> LinuxScopeIdentity:
        if scope_name != self.scope.unit or not self.scope_available:
            raise ValueError("scope identity unavailable")
        return self.scope

    def inspect(self, pid: int) -> LinuxProcessIdentity | None:
        return self.identities.get(pid)

    def scope_members(
        self, scope: LinuxScopeIdentity
    ) -> frozenset[LinuxProcessIdentity]:
        if scope != self.scope:
            raise ValueError("scope identity changed")
        return frozenset(
            identity
            for identity in self.identities.values()
            if identity.cgroup_path == scope.cgroup_path
        )

    def signal(self, identity: LinuxProcessIdentity, sig: int) -> bool:
        if identity.pid in self.drift_before_signal:
            self.drift_before_signal.remove(identity.pid)
            self.identities[identity.pid] = LinuxProcessIdentity(
                identity.pid,
                identity.start_time_ticks + 1,
                1,
                identity.cgroup_path,
            )
        if self.identities.get(identity.pid) != identity:
            return False
        self.signalled.append((identity, sig))
        self.identities.pop(identity.pid)
        return True

    def retire_scope(self, scope: LinuxScopeIdentity) -> bool:
        return scope == self.scope and not self.identities


def _containment(kernel: FakeLinuxKernel):
    factory = select_verification_containment(
        LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE,
        platform="linux",
        linux_kernel=kernel,
        linux_scope_name=kernel.scope.unit,
        sleeper=lambda _seconds: None,
    )
    return factory()


def test_cli_requires_explicit_linux_containment_profile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    kernel = FakeLinuxKernel()

    for profile in (None, "linux", "automatic", "unknown-profile"):
        with pytest.raises(ValueError, match="absent or unsupported"):
            select_verification_containment(
                profile,
                platform="linux",
                linux_kernel=kernel,
            )

    selected = _containment(kernel)
    assert selected.profile_name == LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE
    with pytest.raises(SystemExit, match="0"):
        dispatcher_cli.build_parser().parse_args(["verification-cycle", "--help"])
    help_text = capsys.readouterr().out
    assert "linux-systemd-" in help_text
    assert "cgroup-v2-scope-v1" in help_text


def test_linux_containment_binds_and_validates_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = FakeLinuxKernel()
    containment = _containment(kernel)

    assert containment.environment({"SAFE": "yes"}) == {"SAFE": "yes"}
    root = containment.capture_launch_root(200)
    containment.attach(200, root)

    receipt = containment.receipt()
    assert receipt["outcome"] == "attached"
    assert receipt["scope_identity"] == kernel.scope.unit

    unavailable = FakeLinuxKernel()
    unavailable.available = False
    with pytest.raises(ValueError, match="prerequisites"):
        select_verification_containment(
            LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE,
            platform="linux",
            linux_kernel=unavailable,
        )

    wrong_membership = FakeLinuxKernel()
    wrong_membership.identities[200] = LinuxProcessIdentity(
        200, 1000, 1, "/user.slice/unrelated.scope"
    )
    with pytest.raises(ValueError, match="scope membership"):
        _containment(wrong_membership).capture_launch_root(200)

    proc_root = tmp_path / "proc"
    cgroup_root = tmp_path / "cgroup"
    scope_name = f"yggdrasil-verification-{'a' * 24}.scope"
    scope_path = f"/user.slice/{scope_name}"
    scope_directory = cgroup_root / scope_path.lstrip("/")
    (proc_root / "self").mkdir(parents=True)
    scope_directory.mkdir(parents=True)
    (cgroup_root / "cgroup.controllers").write_text("cpu memory\n", encoding="utf-8")
    (proc_root / "self" / "cgroup").write_text("0::/user.slice\n", encoding="utf-8")
    process_directory = proc_root / "200"
    process_directory.mkdir()
    stat_fields = ["S", "1", *("0" for _ in range(17)), "1000"]
    (process_directory / "stat").write_text(
        f"200 (systemd-run) {' '.join(stat_fields)}\n", encoding="utf-8"
    )
    (process_directory / "cgroup").write_text(
        f"0::{scope_path}\n", encoding="utf-8"
    )
    (scope_directory / "cgroup.procs").write_text("200\n", encoding="utf-8")

    def runner(command: Sequence[str], **_kwargs: object):
        rendered = " ".join(command)
        if "--help" in command:
            stdout = "--scope --unit --user --property"
        elif "show-environment" in command:
            stdout = ""
        elif " show " in f" {rendered} ":
            stdout = (
                f"Id={scope_name}\nControlGroup={scope_path}\n"
                "ActiveState=active\nKillMode=control-group\n"
            )
        else:  # pragma: no cover - this bounded fixture admits no other call.
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(linux_containment.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(linux_containment.os, "pidfd_open", lambda *_args: 9, raising=False)
    monkeypatch.setattr(
        linux_containment.signal,
        "pidfd_send_signal",
        lambda *_args: None,
        raising=False,
    )
    production_kernel = SystemdCgroupV2Kernel(
        proc_root=proc_root,
        cgroup_root=cgroup_root,
        runner=runner,
    )
    production_kernel.preflight()
    scope = production_kernel.scope_identity(scope_name)
    assert production_kernel.scope_members(scope) == {
        LinuxProcessIdentity(200, 1000, 1, scope_path)
    }
    assert production_kernel.scope_command(scope_name, ["true"])[1:4] == [
        "--user",
        "--scope",
        "--quiet",
    ]


def test_linux_cleanup_revalidates_scope_membership() -> None:
    kernel = FakeLinuxKernel()
    containment = _containment(kernel)
    root = containment.capture_launch_root(200)
    containment.attach(200, root)
    kernel.drift_before_signal.add(201)

    assert containment.cleanup() is False
    assert all(identity.pid != 201 for identity, _sig in kernel.signalled)
    assert containment.receipt()["outcome"] == "cleanup_refused"


def test_linux_receipt_is_secret_safe() -> None:
    kernel = FakeLinuxKernel()
    containment = _containment(kernel)
    root = containment.capture_launch_root(200)
    containment.attach(200, root)
    assert containment.cleanup() is True

    receipt: Mapping[str, object] = containment.receipt()
    assert validated_containment_receipt_shape(receipt) == receipt
    assert receipt == {
        "contract": "builderops_linux_containment.v1",
        "profile_name": LINUX_SYSTEMD_CGROUP_V2_SCOPE_PROFILE,
        "scope_identity": kernel.scope.unit,
        "evidence_digests": {
            "attach": receipt["evidence_digests"]["attach"],  # type: ignore[index]
            "cleanup": receipt["evidence_digests"]["cleanup"],  # type: ignore[index]
        },
        "outcome": "clean",
    }
    assert all(
        len(value) == 64 and set(value) <= set("0123456789abcdef")
        for value in receipt["evidence_digests"].values()  # type: ignore[union-attr]
    )
    rendered = repr(receipt)
    assert "token" not in rendered.lower()
    assert "credential" not in rendered.lower()
    assert "/user.slice" not in rendered
    assert "200" not in rendered
    assert kernel.signalled
    assert all(sig != signal.SIGKILL for _identity, sig in kernel.signalled)
