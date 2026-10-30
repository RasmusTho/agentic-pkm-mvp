"""Synthetic boundary tests for the fixed DEV/TEST BWS unit lifecycle."""
from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

import pytest

from app.ops import bws_installation_lifecycle as lifecycle
from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401

_REAL_LIFECYCLE_RUN = lifecycle._run
_REAL_LIFECYCLE_PID_TOKEN = lifecycle._pid_token


def _root(path: str, inode: int) -> dict[str, int | str]:
    return {
        "path": path,
        "device": 1,
        "inode": inode,
        "uid": 0,
        "gid": 0,
        "mode": 0o755,
    }


def _qualified_service(monkeypatch, *, token: str | None = None):
    service = lifecycle.FixedBwsService(
        unit="yggdrasil-bws-deploy@dev.service", channel="dev",
    )
    old_token = token or "a" * 64
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    service.runtime_version = (1, 2, 3, 4, 5, 6, 7, 8)
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    monkeypatch.setattr(service, "_call", lambda method, _signature: "/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40dev_2eservice")
    monkeypatch.setattr(service, "_config", lambda: ("start", "cleanup", "unit-hints"))
    monkeypatch.setattr(service, "_state", lambda active: 123 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: old_token)
    monkeypatch.setattr(
        service, "_exec",
        lambda _name, _action=None: [lifecycle.LAUNCHER,
                                     [lifecycle.LAUNCHER, "cleanup", "dev"],
                                     False, 1, 2, 3, 4, 5, 1, 0],
    )
    monkeypatch.setattr(lifecycle, "_run", lambda argv: calls.append(tuple(argv)) or b"")

    payload = b"new launcher"
    service.qualify_old(
        old_token,
        application_root=_root("/srv/yggdrasil/app", 20),
        control_root=_root(lifecycle.CONTROL_DIRECTORY, 30),
        launcher_content={
            "sha256": hashlib.sha256(payload).hexdigest(),
            "base64": base64.b64encode(payload).decode("ascii"),
        },
    )
    return service, calls, payload


def test_config_authenticates_fixed_control_root_without_launcher_or_unit_hint(monkeypatch, secure_tmp_path):
    secure_tmp_path.chmod(0o750)
    control_root = (secure_tmp_path.resolve() / "bws-control").resolve()
    anchor = control_root / "app/ops/postgres_deploy_linux.py"
    anchor.parent.mkdir(mode=0o755, parents=True)
    anchor.write_text("# synthetic fixed deployment anchor\n")
    anchor.chmod(0o644)
    for directory in (control_root, control_root / "app", control_root / "app/ops"):
        directory.chmod(0o755)

    monkeypatch.setattr(lifecycle, "CONTROL_DIRECTORY", str(control_root))
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_UID", os.getuid())
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_GID", os.getgid())
    service = lifecycle.FixedBwsService(
        unit="yggdrasil-bws-deploy@dev.service", channel="dev",
    )
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    monkeypatch.setattr(service, "_call", lambda method, _signature: (
        "/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40dev_2eservice"
        if method == "GetUnit" else pytest.fail("unexpected systemd method")
    ))
    unit = (Path(__file__).resolve().parents[2] / "config/systemd/yggdrasil-bws-deploy@.service")
    unit_lines = unit.read_text().splitlines()
    environment = [line.partition("=")[2] for line in unit_lines if line.startswith("Environment=")]
    assert not any(str(control_root) in value for value in environment)
    launcher = (Path(__file__).resolve().parents[2] / "scripts/postgres_deploy_service.py").read_bytes()
    assert str(control_root).encode() not in launcher

    start = [lifecycle.LAUNCHER, [lifecycle.LAUNCHER, "serve", "dev"], False,
             1, 2, 3, 4, 5, 1, 0]
    cleanup = [lifecycle.LAUNCHER, [lifecycle.LAUNCHER, "cleanup", "dev"], False,
               1, 2, 3, 4, 5, 1, 0]
    properties = {
        ("Unit", "Id"): service.unit,
        ("Unit", "LoadState"): "loaded",
        ("Service", "Type"): "simple",
        ("Service", "User"): "root",
        ("Service", "Group"): "root",
        ("Service", "KillMode"): "control-group",
        ("Service", "Restart"): "on-failure",
        ("Unit", "OnFailure"): [],
        ("Unit", "OnSuccess"): [],
        ("Unit", "TriggeredBy"): [],
        ("Service", "ExecCondition"): [],
        ("Service", "ExecStartPre"): [],
        ("Service", "ExecStartPost"): [],
        ("Service", "ExecStop"): [],
        ("Service", "ExecReload"): [],
        ("Service", "ExecStart"): [start],
        ("Service", "ExecStopPost"): [cleanup],
        ("Service", "Environment"): environment,
        ("Service", "EnvironmentFiles"): [],
    }
    monkeypatch.setattr(service, "_get", lambda interface, name, _signature: properties[(interface, name)])
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: launcher)
    root_info = control_root.stat()
    service.control = {
        "path": str(control_root), "device": root_info.st_dev, "inode": root_info.st_ino,
        "uid": root_info.st_uid, "gid": root_info.st_gid, "mode": root_info.st_mode & 0o777,
    }
    service.launcher_before = launcher
    service.launcher_after = launcher

    contract = service._config()

    assert contract[:2] == (start[:3], cleanup[:3])
    assert service.control["path"] == str(control_root)
    secure_tmp_path.chmod(0o770)
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service._config()
    secure_tmp_path.chmod(0o750)
    control_root.chmod(0o750)
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service._config()
    control_root.chmod(0o755)
    properties[("Service", "ExecCondition")] = [start]
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service._config()


def test_unit_selection_is_fixed_to_dev_or_test():
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        lifecycle.FixedBwsService(unit="yggdrasil-bws-deploy@prod.service", channel="prod")
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        lifecycle.FixedBwsService(unit="unrelated.service", channel="dev")


@pytest.mark.parametrize("hint_source", ["launcher", "environment", "environment_file"])
def test_empty_control_projection_refuses_control_root_hints(
    hint_source, monkeypatch, secure_tmp_path,
):
    secure_tmp_path.chmod(0o750)
    control_root = (secure_tmp_path.resolve() / "bws-control").resolve()
    control_root.mkdir(mode=0o755)
    control_root.chmod(0o755)
    monkeypatch.setattr(lifecycle, "CONTROL_DIRECTORY", str(control_root))
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_UID", os.getuid())
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_GID", os.getgid())
    info = control_root.stat()
    expected_root = {
        "path": str(control_root), "device": info.st_dev, "inode": info.st_ino,
        "uid": info.st_uid, "gid": info.st_gid, "mode": info.st_mode & 0o777,
    }
    # Prove this synthetic root qualifies without hints before exercising the guard.
    assert lifecycle._discovered_control_projection(
        b"fixed launcher", [], [], expected_empty_control_root=expected_root,
    ) == expected_root

    launcher = b"fixed launcher"
    environment = []
    environment_files = []
    if hint_source == "launcher":
        launcher += str(control_root).encode()
    elif hint_source == "environment":
        environment.append(f"PYTHONPATH={control_root}/app")
    else:
        environment_files.append([f"{control_root}/app.env", False])

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        lifecycle._discovered_control_projection(
            launcher,
            environment,
            environment_files,
            expected_empty_control_root=expected_root,
        )


def test_inflight_exec_stop_post_caller_refuses_before_transaction_mutation(monkeypatch, tmp_path):
    proc_root = tmp_path / "proc"
    process = proc_root / "321"
    process.mkdir(parents=True)
    command = process / "cmdline"
    command.write_bytes(
        (lifecycle.RUNTIME + "\0" + lifecycle.LAUNCHER + "\0cleanup\0dev\0").encode()
    )
    monkeypatch.setattr(lifecycle, "PROC", proc_root)

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        lifecycle.require_no_cleanup_callers("dev")


def test_cleanup_caller_census_ignores_fixed_non_cleanup_and_other_channel_processes(monkeypatch, tmp_path):
    proc_root = tmp_path / "proc"
    process = proc_root / "321"
    process.mkdir(parents=True)
    command = process / "cmdline"
    command.write_bytes(
        (lifecycle.RUNTIME + "\0" + lifecycle.LAUNCHER + "\0serve\0dev\0").encode()
    )
    monkeypatch.setattr(lifecycle, "PROC", proc_root)

    lifecycle.require_no_cleanup_callers("dev")
    command.write_bytes(
        (lifecycle.RUNTIME + "\0" + lifecycle.LAUNCHER + "\0cleanup\0prod\0").encode()
    )
    lifecycle.require_no_cleanup_callers("dev")


def test_cleanup_caller_census_refuses_other_dev_rpc_and_allows_current_transaction(monkeypatch, tmp_path):
    proc_root = tmp_path / "proc"
    process = proc_root / "321"
    process.mkdir(parents=True)
    (process / "cmdline").write_bytes(
        (lifecycle.RUNTIME + "\0/opt/yggdrasil/candidate/scripts/postgres_deploy_service.py"
         "\0rpc\0dev\0").encode()
    )
    monkeypatch.setattr(lifecycle, "PROC", proc_root)

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        lifecycle.require_no_cleanup_callers("dev")

    lifecycle.require_no_cleanup_callers("dev", caller_pid=321)


def test_old_unit_qualification_is_read_only(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)

    assert service.phase == "qualified"
    assert service.old_pid == 123
    assert service.old_token == "a" * 64
    assert calls == []


def test_old_generation_is_captured_fresh_without_saved_identity(monkeypatch):
    service = lifecycle.FixedBwsService(
        unit="yggdrasil-bws-deploy@dev.service", channel="dev",
    )
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    service.runtime_version = (1, 2, 3, 4, 5, 6, 7, 8)
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    monkeypatch.setattr(service, "_call", lambda *_args: "/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40dev_2eservice")
    monkeypatch.setattr(service, "_config", lambda: ("start", "cleanup", "unit-hints"))
    monkeypatch.setattr(service, "_state", lambda active: 123 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: "f" * 64)
    monkeypatch.setattr(
        service, "_exec",
        lambda _name, _action=None: [lifecycle.LAUNCHER,
                                     [lifecycle.LAUNCHER, "cleanup", "dev"],
                                     False, 1, 2, 3, 4, 5, 1, 0],
    )
    service.qualify_old(
        application_root=_root("/srv/yggdrasil/app", 20),
        control_root=_root(lifecycle.CONTROL_DIRECTORY, 30),
        launcher_content={
            "sha256": hashlib.sha256(b"new launcher").hexdigest(),
            "base64": base64.b64encode(b"new launcher").decode("ascii"),
        },
    )

    assert service.phase == "qualified"
    assert service.old_token == "f" * 64


def test_compensation_starts_only_the_restored_old_launcher_generation(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: _payload)
    service.require_old_kernel(launcher_content=_payload)
    tokens = iter(("a" * 64, "b" * 64, "b" * 64))
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: next(tokens))
    monkeypatch.setattr(service, "_stopped", lambda: None)
    service.stop_old()
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    service.start_restored_old()
    service.require_restored_old_kernel()
    service.require_same_restored_old_kernel()

    assert calls[-2:] == [
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "stop", "yggdrasil-bws-deploy@dev.service"),
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "start", "yggdrasil-bws-deploy@dev.service"),
    ]
    assert service.phase == "old_kernel_restored"


def test_old_generation_mismatch_refuses_before_lifecycle_effect(monkeypatch):
    service = lifecycle.FixedBwsService(
        unit="yggdrasil-bws-deploy@dev.service", channel="dev",
    )
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    service.runtime_version = (1, 2, 3, 4, 5, 6, 7, 8)
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    monkeypatch.setattr(service, "_call", lambda *_args: "/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40dev_2eservice")
    monkeypatch.setattr(service, "_config", lambda: ("start", "cleanup", "unit-hints"))
    monkeypatch.setattr(service, "_state", lambda active: 123 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: "b" * 64)
    monkeypatch.setattr(
        service, "_exec",
        lambda _name, _action=None: [lifecycle.LAUNCHER,
                                     [lifecycle.LAUNCHER, "cleanup", "dev"],
                                     False, 1, 2, 3, 4, 5, 1, 0],
    )
    monkeypatch.setattr(lifecycle, "_run", lambda argv: calls.append(tuple(argv)) or b"")
    payload = b"new launcher"

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service.qualify_old(
            "a" * 64,
            application_root=_root("/srv/yggdrasil/app", 20),
            control_root=_root(lifecycle.CONTROL_DIRECTORY, 30),
            launcher_content={
                "sha256": hashlib.sha256(payload).hexdigest(),
                "base64": base64.b64encode(payload).decode("ascii"),
            },
        )

    assert calls == []
    assert service.phase != "qualified"


def test_stop_and_start_are_one_shot_fixed_unit_actions(monkeypatch):
    service, calls, payload = _qualified_service(monkeypatch)
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: payload)
    service.require_old_kernel(launcher_content=payload)
    monkeypatch.setattr(service, "_stopped", lambda: None)
    service.stop_old()
    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service.stop_old()
    service.start_new()

    assert service.phase == "start_requested"
    assert calls == [
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "stop", "yggdrasil-bws-deploy@dev.service"),
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "start", "yggdrasil-bws-deploy@dev.service"),
    ]


def test_stop_old_refuses_before_candidate_launcher_is_staged(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service.stop_old()

    assert calls == []
    assert service.phase == "qualified"


def test_fixed_unit_stops_legacy_process_with_staged_candidate_launcher(monkeypatch, secure_tmp_path):
    control_root = secure_tmp_path.resolve() / "bws-control"
    anchor = control_root / "app/ops/postgres_deploy_linux.py"
    anchor.parent.mkdir(mode=0o755, parents=True)
    anchor.write_text("# synthetic fixed deployment anchor\n")
    anchor.chmod(0o644)
    for directory in (control_root, control_root / "app", control_root / "app/ops"):
        directory.chmod(0o755)
    monkeypatch.setattr(lifecycle, "CONTROL_DIRECTORY", str(control_root))
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_UID", os.getuid())
    monkeypatch.setattr(lifecycle, "_CONTROL_OWNER_GID", os.getgid())

    old_launcher = b"old launcher bytes"
    candidate_launcher = b"candidate launcher bytes\n"
    current_launcher = [old_launcher]
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: current_launcher[0])
    service = lifecycle.FixedBwsService(
        unit="yggdrasil-bws-deploy@dev.service", channel="dev",
    )
    monkeypatch.setattr(service, "_held_runtime", lambda: None)
    service.runtime_version = (1, 2, 3, 4, 5, 6, 7, 8)

    start = [lifecycle.LAUNCHER, [lifecycle.LAUNCHER, "serve", "dev"], False,
             1, 2, 3, 4, 5, 1, 0]
    cleanup = [lifecycle.LAUNCHER, [lifecycle.LAUNCHER, "cleanup", "dev"], False,
               1, 2, 3, 4, 5, 1, 0]
    properties = {
        ("Unit", "Id"): service.unit,
        ("Unit", "LoadState"): "loaded",
        ("Service", "Type"): "simple",
        ("Service", "User"): "root",
        ("Service", "Group"): "root",
        ("Service", "KillMode"): "control-group",
        ("Service", "Restart"): "on-failure",
        ("Unit", "OnFailure"): [],
        ("Unit", "OnSuccess"): [],
        ("Unit", "TriggeredBy"): [],
        ("Service", "ExecCondition"): [],
        ("Service", "ExecStartPre"): [],
        ("Service", "ExecStartPost"): [],
        ("Service", "ExecStop"): [],
        ("Service", "ExecReload"): [],
        ("Service", "ExecStart"): [start],
        ("Service", "ExecStopPost"): [cleanup],
        ("Service", "Environment"): [],
        ("Service", "EnvironmentFiles"): [],
        ("Unit", "ActiveState"): "active",
        ("Unit", "SubState"): "running",
        ("Unit", "Job"): [0, "/"],
        ("Service", "ControlPID"): 0,
        ("Service", "MainPID"): 123,
    }
    monkeypatch.setattr(service, "_get", lambda interface, name, _signature: properties[(interface, name)])
    unit_object = "/org/freedesktop/systemd1/unit/yggdrasil_2dbws_2ddeploy_40dev_2eservice"
    monkeypatch.setattr(service, "_call", lambda method, _signature: unit_object
                        if method == "GetUnit" else [["main", 123, "/system.slice/bws.service"]])
    monkeypatch.setattr(service, "_state", lambda active: 123 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: "a" * 64)
    commands = []
    monkeypatch.setattr(lifecycle, "_run", lambda argv: commands.append(tuple(argv)) or b"")

    service.qualify_old(
        "a" * 64,
        application_root={
            **_root("/srv/yggdrasil/app", 20), "uid": os.getuid(), "gid": os.getgid(),
        },
        control_root={
            "path": str(control_root), "device": control_root.stat().st_dev,
            "inode": control_root.stat().st_ino, "uid": os.getuid(), "gid": os.getgid(),
            "mode": control_root.stat().st_mode & 0o777,
        },
        launcher_content={
            "sha256": hashlib.sha256(candidate_launcher).hexdigest(),
            "base64": base64.b64encode(candidate_launcher).decode("ascii"),
        },
    )
    current_launcher[0] = candidate_launcher
    service.require_old_kernel(launcher_content=candidate_launcher)
    monkeypatch.setattr(service, "_stopped", lambda: service._config())

    service.stop_old()

    assert service.phase == "stopped_checked"
    assert commands == [(
        "systemctl", "--system", "--no-pager", "--no-ask-password",
        "--job-mode=ignore-dependencies", "stop", service.unit,
    )]


def test_start_refuses_when_launcher_is_not_the_proposed_final_bytes(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)
    service.phase = "stopped_checked"
    monkeypatch.setattr(service, "_stopped", lambda: None)

    with pytest.raises(RuntimeError, match="bws_lifecycle_unproven"):
        service.start_new()

    assert calls == []
    assert service.phase == "stopped_checked"


def test_failed_candidate_generation_stops_only_the_authenticated_candidate(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)
    service.phase = "new_kernel_checked"
    service.new_pid = 456
    service.new_token = "c" * 64
    monkeypatch.setattr(service, "_config", lambda: service.contract)
    monkeypatch.setattr(service, "_state", lambda active: 456 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: service.new_token)
    monkeypatch.setattr(service, "_stopped", lambda: None)

    service.stop_new()

    assert calls == [
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "stop", "yggdrasil-bws-deploy@dev.service"),
    ]
    assert service.phase == "new_stopped_checked"


def test_final_restored_old_mismatch_can_stop_only_that_restored_process(monkeypatch):
    service, calls, _payload = _qualified_service(monkeypatch)
    service.phase = "old_kernel_restored"
    service.new_pid = 789
    service.new_token = "d" * 64
    monkeypatch.setattr(lifecycle, "_public_launcher_bytes", lambda: b"old launcher")
    monkeypatch.setattr(service, "_config", lambda: service.contract)
    monkeypatch.setattr(service, "_state", lambda active: 789 if active else 0)
    monkeypatch.setattr(service, "_single_process", lambda _pid: None)
    monkeypatch.setattr(lifecycle, "_pid_token", lambda *_args: service.new_token)
    monkeypatch.setattr(service, "_stopped", lambda: None)

    service.stop_restored_old()

    assert calls == [
        ("systemctl", "--system", "--no-pager", "--no-ask-password",
         "--job-mode=ignore-dependencies", "stop", "yggdrasil-bws-deploy@dev.service"),
    ]
    assert service.phase == "restored_stopped_checked"


@pytest.mark.parametrize("fault,expected", [
    ("setup", "setup"), ("runtime", "retained_runtime"),
    ("transport", "unit_properties"), ("property", "unit_properties"),
    ("root", "root_control"), ("launcher", "launcher"),
    ("state", "service_process"), ("pid_token", "service_process"),
    ("cleanup", "cleanup_contract"),
])
def test_old_qualification_refusals_are_finite_and_value_free(
    monkeypatch, secure_tmp_path, capsys, fault, expected,
):
    # Share only synthetic input/transport assembly; qualification stays real.
    from tests.ops.test_bws_installation_transaction import _old_qualification_case

    _request, ports, _admission, service, _events, control, properties, faults = _old_qualification_case(
        monkeypatch, secure_tmp_path,
    )
    old = ports.old_state(None, None)
    arguments = dict(
        application_root={"path": "/srv/app", **old["roots"]["application"]},
        control_root={"path": str(control), **old["roots"]["control"]},
        launcher_content={"sha256": hashlib.sha256(b"new launcher").hexdigest(),
                          "base64": base64.b64encode(b"new launcher").decode()},
        control_inventory_empty=True,
    )
    if fault == "transport":
        # Real _run normalizes private stderr and a nonzero transport exit.
        monkeypatch.setattr(lifecycle, "_run", _REAL_LIFECYCLE_RUN)
        monkeypatch.setattr(lifecycle.os, "geteuid", lambda: 0)
        monkeypatch.setattr(lifecycle.sys, "platform", "linux")
        from types import SimpleNamespace
        monkeypatch.setattr(lifecycle.subprocess, "run", lambda *_a, **_k: SimpleNamespace(
            returncode=1, stdout=b"PRIVATE_CANARY", stderr=b"PRIVATE_CANARY",
        ))
    elif fault == "property":
        properties[("Service", "EnvironmentFiles")] = [["PRIVATE_CANARY", "PRIVATE_CANARY"]]
    elif fault == "root":
        properties[("Service", "Environment")] = [f"PRIVATE_CANARY={control}/app"]
    elif fault == "launcher":
        arguments["launcher_content"] = {"base64": "PRIVATE_CANARY", "sha256": "PRIVATE_CANARY"}
    elif fault == "state":
        properties[("Unit", "Job")] = ["PRIVATE_CANARY", "PRIVATE_CANARY"]
    elif fault == "pid_token":
        monkeypatch.setattr(lifecycle, "_pid_token", _REAL_LIFECYCLE_PID_TOKEN)
        monkeypatch.setattr(service, "_state", lambda _active: 0)
    elif fault == "cleanup":
        properties[("Service", "ExecStopPost")][0][0] = "PRIVATE_CANARY"

    with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
        if fault == "setup":
            lifecycle.FixedBwsService(unit="PRIVATE_CANARY", channel="dev")
        elif fault == "runtime":
            monkeypatch.setattr(lifecycle, "RUNTIME", str(control / "PRIVATE_CANARY"))
            with type(service).retained_runtime(service):
                pytest.fail("runtime refusal must precede yield")
        else:
            service.qualify_old(**arguments)
    assert type(caught.value) is lifecycle._OldQualificationRefusal
    assert caught.value.subgate == expected
    assert str(caught.value) == "bws_lifecycle_unproven"
    assert "PRIVATE_CANARY" not in repr(caught.value)
    assert "PRIVATE_CANARY" not in repr(capsys.readouterr())
    assert service.phase != "qualified"


# A synthetic kernel port, shared by direct guards and the assembled real RPC.
# Core snapshot/manifest/profile/Git readers are never replaced by this port.
# Only lifecycle's OS view uses it; its root identity is the real producer's.
class RootControlOS:
    def __init__(self, control, *, application=None, runtime=None, channel='dev', anchored=False):
        from types import SimpleNamespace
        import stat
        self.real = os
        self.control = str(control)
        self.runtime = str(runtime) if runtime else None
        self.application = application
        self.channel = channel
        self.nodes = {}
        self.data = {}
        self.fds = {}
        self.runtime_fds = set()
        self.opened = []
        self.closed = []
        self.trace = []
        self.counts = {}
        self.discovery = 0
        self.fault = None
        self.fired = False
        self.close_failures = 0
        self._namespace = SimpleNamespace
        self._stat = stat
        for index, path in enumerate(reversed(Path(control).parents)):
            self.add(str(path), stat.S_IFDIR | 0o755, inode=100 + index, uid=0, gid=0)
        if Path(control).exists():
            info = Path(control).stat()
            self.add(self.control, info.st_mode, inode=info.st_ino, device=info.st_dev,
                     uid=info.st_uid, gid=info.st_gid)
        else:
            self.add(self.control, stat.S_IFDIR | 0o755)
        if anchored:
            self.add_anchor(self.control)
        if runtime:
            self.add('/proc/123', stat.S_IFDIR | 0o755, uid=0, gid=0)
            self.add('/proc/123/task', stat.S_IFDIR | 0o755, uid=0, gid=0)
            for name, raw in {
                'stat': b'123 (PRIVATE_CANARY) R ' + b'0 ' * 18 + b'777\n',
                'status': b'Uid:\t0\t0\t0\t0\n',
                'cmdline': b'\0'.join(value.encode() for value in (
                    str(runtime), lifecycle.LAUNCHER, 'serve', channel,
                )) + b'\0',
            }.items():
                path = '/proc/123/' + name
                self.add(path, stat.S_IFREG | 0o644, uid=0, gid=0, size=len(raw))
                self.data[path] = raw

    def add(self, path, mode, *, inode=None, device=1, uid=None, gid=None, size=1):
        self.nodes[path] = self._namespace(
            st_mode=mode, st_dev=device, st_ino=inode or len(self.nodes) + 1000,
            st_uid=os.geteuid() if uid is None else uid,
            st_gid=os.getegid() if gid is None else gid, st_nlink=1,
            st_size=size, st_mtime_ns=1, st_ctime_ns=1,
        )

    def add_anchor(self, root):
        for suffix in ('app', 'app/ops'):
            self.add(root + '/' + suffix, self._stat.S_IFDIR | 0o755)
        self.add(root + '/app/ops/postgres_deploy_linux.py', self._stat.S_IFREG | 0o644)

    def arm(self, fault, *, discovery=1):
        self.fault = {**fault, 'discovery': discovery}
        self.fired = False

    def _path(self, path, dir_fd=None):
        return (self.fds[dir_fd] + '/' + str(path)).replace('//', '/') if dir_fd in self.fds else str(path)

    def _observe(self, operation, path, value=None):
        key = (operation, path)
        count = self.counts.get(key, 0)
        self.counts[key] = count + 1
        self.trace.append((self.discovery, operation, path, count))
        fault = self.fault
        if (fault and not self.fired and self.discovery == fault['discovery']
                and (operation, path, count) == (fault['operation'], fault['path'], fault['occurrence'])):
            self.fired = True
            change = fault['change']
            if change == 'missing':
                raise FileNotFoundError('PRIVATE_CANARY')
            if change == 'error':
                raise OSError('PRIVATE_CANARY')
            if change == 'construction_error':
                class BrokenStat:
                    def __getattr__(self, name):
                        if name == 'st_dev':
                            raise OSError('PRIVATE_CANARY')
                        return getattr(value, name)
                return BrokenStat()
            if isinstance(change, dict):
                return self._namespace(**{**(vars(value) if value is not None else {}), **change})
            return change
        return value

    def open(self, path, flags, *, dir_fd=None):
        resolved = self._path(path, dir_fd)
        if resolved == '/':
            self.discovery += 1
            # Reopen belongs to the same discovery, not another launcher side.
            if self.fds:
                self.discovery -= 1
            else:
                self.counts = {}
                callback = getattr(self, 'on_discovery', None)
                if callback:
                    callback(self.discovery)
        if resolved not in self.nodes and dir_fd not in self.fds and resolved != '/':
            fd = os.open(path, flags, **({} if dir_fd is None else {'dir_fd': dir_fd}))
            if resolved == self.runtime:
                self.runtime_fds.add(fd)
            return fd
        assert flags & os.O_NOFOLLOW
        if resolved in self.nodes and self._stat.S_ISDIR(self.nodes[resolved].st_mode):
            assert flags & os.O_DIRECTORY
        self._observe('open', resolved)
        if resolved not in self.nodes:
            raise FileNotFoundError('PRIVATE_CANARY')
        fd = 100000 + len(self.opened)
        self.fds[fd] = resolved
        self.opened.append(fd)
        return fd

    def fstat(self, fd):
        if fd not in self.fds:
            info = os.fstat(fd)
            return self._namespace(**{**{n: getattr(info, n) for n in dir(info) if n.startswith('st_')},
                                      'st_uid': 0, 'st_gid': 0}) if fd in self.runtime_fds else info
        path = self.fds[fd]
        return self._observe('fstat', path, self.nodes[path])

    def stat(self, path, *, dir_fd=None, follow_symlinks=True):
        resolved = self._path(path, dir_fd)
        if resolved == '/proc/123/cwd':
            return os.stat(self.application)
        if resolved == '/proc/123/exe' or resolved == self.runtime:
            info = os.stat(self.runtime)
            return self._namespace(**{**{n: getattr(info, n) for n in dir(info) if n.startswith('st_')},
                                      'st_uid': 0, 'st_gid': 0})
        if dir_fd not in self.fds and resolved not in self.nodes:
            return os.stat(path, **({} if dir_fd is None else {'dir_fd': dir_fd}),
                           follow_symlinks=follow_symlinks)
        assert follow_symlinks is False
        value = self._observe('stat', resolved, self.nodes.get(resolved))
        if value is None:
            raise FileNotFoundError('PRIVATE_CANARY')
        return value

    def get_inheritable(self, fd):
        if fd not in self.fds:
            return os.get_inheritable(fd)
        return self._observe('inheritable', self.fds[fd], False)

    def close(self, fd):
        if fd not in self.fds:
            runtime = fd in self.runtime_fds
            self.runtime_fds.discard(fd)
            os.close(fd)
            if runtime and getattr(self, 'runtime_close_failure', False):
                raise OSError('PRIVATE_CANARY')
            return None
        self.closed.append(fd)
        del self.fds[fd]
        if self.close_failures:
            self.close_failures -= 1
            raise OSError('PRIVATE_CANARY')

    def read(self, fd, size):
        return self.data[self.fds[fd]][:size] if fd in self.fds else os.read(fd, size)

    def listdir(self, fd):
        return ['123'] if fd in self.fds and self.fds[fd] == '/proc/123/task' else os.listdir(fd)

    def readlink(self, path, *, dir_fd=None):
        if self._path(path, dir_fd) == '/proc/123/cwd':
            return str(self.application)
        return os.readlink(path, **({} if dir_fd is None else {'dir_fd': dir_fd}))

    def port(self):
        value = vars(os).copy()
        value.update({name: getattr(self, name) for name in (
            'open', 'stat', 'fstat', 'close', 'get_inheritable', 'read', 'listdir', 'readlink',
        )})
        return self._namespace(**value)


# Each row is a real guard negative, with its matching permitted OS observation
# exercised before injection. Occurrences are kernel-operation order, not frame
# inspection, exception-message parsing or a substitute core predicate.
def root_control_os_cases(control):
    import stat
    control = str(control)
    ancestor = '/' + Path(control).parts[1]
    cases = []
    for role, path, occurrence, mode, anchored in (
        ('fixed_origin', '/', 0, 'captured_empty', False),
        ('fixed_ancestor', ancestor, 0, 'captured_empty', False),
        ('fixed_root', control, 0, 'captured_empty', False),
        ('candidate', control + '/app', 0, 'anchored_discovery', True),
        ('anchor_app', control + '/app', 1, 'anchored_discovery', True),
        ('anchor_ops', control + '/app/ops', 1, 'anchored_discovery', True),
        ('reopen_origin', '/', 1, 'captured_empty', False),
        ('reopen_ancestor', ancestor, 1, 'captured_empty', False),
        ('reopen_root', control, 1, 'captured_empty', False),
    ):
        for guard, operation, change in (
            ('open_unknown', 'open', 'error'), ('fstat_unknown', 'fstat', 'error'),
            ('directory_type', 'fstat', {'st_mode': stat.S_IFREG | 0o644}),
            ('owner_pair', 'fstat', {'st_uid': 999999, 'st_gid': 999999}),
            ('directory_mode', 'fstat', {'st_mode': stat.S_IFDIR | 0o777}),
            ('inheritable_unknown', 'inheritable', 'error'), ('inheritable', 'inheritable', True),
        ):
            # Empty-mode fixed_projection adds a fstat before reopen_root.
            nth = occurrence + (1 if role == 'reopen_root' and operation == 'fstat' else 0)
            cases.append((mode, anchored, role, guard, dict(
                operation=operation, path=path, occurrence=nth, change=change,
            )))
    for role, suffix, occurrence in (
        ('anchor_app', '/app', 1), ('anchor_ops', '/app/ops', 1),
    ):
        for guard, change in (
            ('stat_unknown', 'error'), ('loader_symlink', {'st_mode': stat.S_IFLNK | 0o777}),
        ):
            cases.append(('anchored_discovery', True, role, guard, dict(
                operation='stat', path=control + suffix, occurrence=occurrence, change=change,
            )))
    for guard, change in (
        ('stat_unknown', 'error'), ('file_type', {'st_mode': stat.S_IFDIR | 0o755}),
        ('uid', {'st_uid': 999999}), ('gid', {'st_gid': 999999}),
        ('file_mode', {'st_mode': stat.S_IFREG | 0o600}), ('link_count', {'st_nlink': 2}),
    ):
        cases.append(('anchored_discovery', True, 'anchor_file', guard, dict(
            operation='stat', path=control + '/app/ops/postgres_deploy_linux.py', occurrence=1, change=change,
        )))
    for role, occurrence, mode, anchored in (
        ('candidate_projection', 2, 'anchored_discovery', True),
        ('fixed_projection', 1, 'captured_empty', False),
        ('reopen_projection', 3, 'captured_empty', False),
    ):
        for guard, change in (
            ('fstat_unknown', 'error'), ('directory_type', {'st_mode': stat.S_IFREG | 0o644}),
            ('construction_unknown', 'construction_error'),
        ):
            cases.append((mode, anchored, role, guard, dict(
                operation='fstat', path=control, occurrence=occurrence, change=change,
            )))
    for guard, operation, path, occurrence, change in (
        ('stat_unknown', 'stat', control + '/app', 0, 'error'),
        ('symlink', 'stat', control + '/app', 0, {'st_mode': stat.S_IFLNK | 0o777}),
    ):
        cases.append(('anchored_discovery', True, 'candidate', guard, dict(
            operation=operation, path=path, occurrence=occurrence, change=change,
        )))
    for guard, change in (
        ('fstat_unknown', 'error'), ('directory_mode', {'st_mode': stat.S_IFDIR | 0o750}),
    ):
        cases.append(('anchored_discovery', True, 'anchor_root', guard, dict(
            operation='fstat', path=control, occurrence=1, change=change,
        )))
    for role, path, occurrence in (
        ('app_slot', control + '/app', 2), ('scripts_slot', control + '/scripts', 0),
    ):
        cases.append(('captured_empty', False, role, 'stat_unknown', dict(
            operation='stat', path=path, occurrence=occurrence, change='error',
        )))
    for guard, occurrence in (('identity', 1), ('reopen_identity', 3)):
        cases.append(('captured_empty', False, 'empty_root', guard, dict(
            operation='fstat', path=control, occurrence=occurrence, change={'st_ino': 987654321},
        )))
    return cases


def _assert_root_refinement(caught, expected):
    assert type(caught.value) is lifecycle._OldQualificationRefusal
    assert caught.value.subgate == 'root_control'
    assert caught.value.root_control == expected
    assert str(caught.value) == 'bws_lifecycle_unproven'
    assert 'PRIVATE_CANARY' not in repr(caught.value)


def test_root_control_leaf_matrix_covers_all_canonical_guards(monkeypatch, secure_tmp_path):
    from app.ops import bws_installation_admission as admission
    control = secure_tmp_path / 'control'
    control.mkdir(mode=0o755)
    control.chmod(0o755)
    monkeypatch.setattr(lifecycle, 'CONTROL_DIRECTORY', str(control))
    monkeypatch.setattr(lifecycle, '_CONTROL_OWNER_UID', os.geteuid())
    monkeypatch.setattr(lifecycle, '_CONTROL_OWNER_GID', os.getegid())
    projection = _root(str(control), 1)
    info = control.stat()
    projection.update(device=info.st_dev, inode=info.st_ino, uid=info.st_uid, gid=info.st_gid)
    proved = set()
    for mode, anchored, role, guard, fault in root_control_os_cases(control):
        port = RootControlOS(control, anchored=anchored)
        monkeypatch.setattr(lifecycle, 'os', port.port())
        expected = projection if mode == 'captured_empty' else None
        assert lifecycle._discovered_control_projection(
            b'fixed launcher', [], [], expected_empty_control_root=expected,
        ) == projection
        golden = root_control_golden_trace(control, anchored=anchored)
        assert [(op, path) for _, op, path, _ in port.trace] == golden
        assert not port.fds and port.closed == list(reversed(port.opened))
        # A fresh invocation reproduces identical observation positions.
        port = RootControlOS(control, anchored=anchored)
        port.arm(fault)
        monkeypatch.setattr(lifecycle, 'os', port.port())
        with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
            lifecycle._discovered_control_projection(
                b'fixed launcher', [], [], expected_empty_control_root=expected,
            )
        context = (mode, 'unknown', role, guard)
        _assert_root_refinement(caught, context)
        assert context in admission._ROOT_CONTROL_REFINEMENTS
        assert port.fired and not port.fds
        assert [(op, path) for _, op, path, _ in port.trace] == golden[:len(port.trace)]
        assert port.trace[-1][1:4] == (fault['operation'], fault['path'], fault['occurrence'])
        assert port.closed == list(reversed(port.opened))
        proved.add((role, guard))
    assert len(proved) == len(root_control_os_cases(control))
    proved |= _root_control_semantic_matrix(monkeypatch, control, projection)
    from tests.ops.test_bws_installation_transaction import test_root_control_leaf_matrix_reaches_canonical_receipt
    test_root_control_leaf_matrix_reaches_canonical_receipt(monkeypatch, secure_tmp_path)
    proved.add(('comparison', 'identity'))
    expected_pairs = {(role, guard) for _, _, roles, guards in admission._ROOT_CONTROL_CONTEXTS
                      for role in roles for guard in guards}
    assert expected_pairs == proved


def root_control_projection_cases(value):
    cases = [('mapping_type', None), ('fields', {}),
             ('path_type', {**value, 'path': 7}),
             ('path_absolute', {**value, 'path': 'PRIVATE_CANARY'}),
             ('path_canonical', {**value, 'path': '/PRIVATE_CANARY/../other'}),
             ('path_backslash', {**value, 'path': '/PRIVATE_CANARY\\other'}),
             ('path_nul', {**value, 'path': '/PRIVATE_CANARY\0other'})]
    cases += [(field + '_type', {**value, field: True})
              for field in ('device', 'inode', 'uid', 'gid', 'mode')]
    cases += [(guard, {**value, field: invalid}) for guard, field, invalid in (
        ('device_range', 'device', -1), ('inode_range', 'inode', 0),
        ('uid', 'uid', 999999), ('gid', 'gid', 999999), ('mode', 'mode', 0o750),
    )]
    type_fields = ('device', 'inode', 'uid', 'gid', 'mode')
    numeric_fields = (('device_range', 'device', -1), ('inode_range', 'inode', 0),
                      ('uid', 'uid', 999999), ('gid', 'gid', 999999), ('mode', 'mode', 0o750))
    for guard, invalid in cases:
        if type(invalid) is dict and set(invalid) == set(value):
            if guard.startswith('path_'):
                invalid.update({key: True for key in type_fields})
            elif guard.endswith('_type') and guard[:-5] in type_fields:
                invalid.update({key: True for key in type_fields[type_fields.index(guard[:-5]) + 1:]})
            elif guard in {row[0] for row in numeric_fields}:
                index = next(i for i, row in enumerate(numeric_fields) if row[0] == guard)
                invalid.update({key: bad for _, key, bad in numeric_fields[index + 1:]})
    return cases


def _root_control_semantic_matrix(monkeypatch, control, projection):
    from types import SimpleNamespace
    import stat
    proved = set()
    for role in ('application', 'control', 'expected_empty'):
        mode = 'captured_empty' if role == 'expected_empty' else 'unknown'
        assert lifecycle._application_projection(projection, role=role, mode=mode) == projection
        for guard, invalid in root_control_projection_cases(projection):
            with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
                lifecycle._application_projection(invalid, role=role, mode=mode)
            _assert_root_refinement(caught, (mode, 'unknown', role, guard))
            proved.add((role, guard))

    def call(port, *, launcher=b'fixed launcher', env=None, files=None, empty=True):
        monkeypatch.setattr(lifecycle, 'os', port.port())
        return lifecycle._discovered_control_projection(
            launcher, env or [], files or [],
            expected_empty_control_root=projection if empty else None,
        )

    def negative(role, guard, *, mode='captured_empty', anchored=False, configure=None, **kwargs):
        port = RootControlOS(control, anchored=anchored)
        if configure:
            configure(port)
        with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
            call(port, **kwargs)
        _assert_root_refinement(caught, (mode, 'unknown', role, guard))
        assert not port.fds
        proved.add((role, guard))

    for guard, kwargs in (
        ('launcher_hint', dict(launcher=str(control).encode())),
        ('environment_hint', dict(env=['PRIVATE_CANARY=' + str(control)])),
        ('environment_files_hint', dict(files=[[str(control) + '/PRIVATE_CANARY', False]])),
    ):
        negative('hints', guard, **kwargs)
    negative('hints', 'candidate_count', mode='anchored_discovery', empty=False,
             env=[' '.join(str(control) + '/' + str(n) for n in range(17))])
    for guard, hint in (
        ('component_count', str(control) + '/' + '/'.join(['a'] * 33)),
        ('components_canonical', str(control) + '/a/../b'),
    ):
        negative('candidate', guard, mode='anchored_discovery', empty=False, env=[hint])
    # A missing hinted tail and a non-directory candidate tail still ascend
    # through false anchor probes to the one valid root, with no added reads.
    for suffix in ('missing/tail', 'app/ops/postgres_deploy_linux.py/tail'):
        assert call(RootControlOS(control, anchored=True), empty=False,
                    env=[str(control) + '/' + suffix]) == projection
    negative('anchored_roots', 'no_anchor', mode='anchored_discovery', empty=False)
    negative('anchored_roots', 'no_anchor', mode='anchored_discovery', empty=False, anchored=True,
             configure=lambda p: p.arm(dict(operation='open', path=str(control) + '/app',
                                            occurrence=1, change='missing')))
    def multiple(port):
        for name in ('one', 'two'):
            port.add(str(control) + '/' + name, stat.S_IFDIR | 0o755)
            port.add_anchor(str(control) + '/' + name)
    negative('anchored_roots', 'multiple_anchors', mode='anchored_discovery', empty=False,
             configure=multiple, env=[str(control) + '/one/app ' + str(control) + '/two/app'])
    negative('empty_root', 'anchored_root_present', anchored=True)
    for name, role in (('app', 'app_slot'), ('scripts', 'scripts_slot')):
        negative(role, 'present', configure=lambda p, n=name: p.add(
            str(control) + '/' + n, stat.S_IFREG | 0o644,
        ))
    negative('discovery_close', 'close_unknown', configure=lambda p: setattr(p, 'close_failures', 2))

    # Unexpected input/construction sites are defensive: the real bus parser and
    # launcher reader produce exact list/str/bytes; neither can produce these
    # subclass behaviours. Their earlier refusal is covered at the real RPC.
    class DecodeFailure(bytes):
        calls = 0
        def decode(self, *_args):
            self.calls += 1
            if self.calls == 2:
                raise ValueError('PRIVATE_CANARY')
            return 'fixed launcher'
    class HintFailure(str):
        def __contains__(self, _other):
            raise ValueError('PRIVATE_CANARY')
    for guard, mode, kwargs in (
        ('decode_unknown', 'unknown', dict(launcher=b'\xff')),
        ('environment_unknown', 'unknown', dict(env=[7])),
        ('environment_files_unknown', 'unknown', dict(files=[[7, False]])),
        ('empty_decode_unknown', 'captured_empty', dict(launcher=DecodeFailure())),
        ('empty_environment_unknown', 'captured_empty', dict(env=[HintFailure('PRIVATE_CANARY')])),
        ('empty_environment_files_unknown', 'captured_empty', dict(files=[[HintFailure('PRIVATE_CANARY'), False]])),
    ):
        negative('discovery', guard, mode=mode, **kwargs)
    original_re, original_path = lifecycle.re, lifecycle.Path
    def unexpected(*_args, **_kwargs):
        raise OSError('PRIVATE_CANARY')
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, 're', SimpleNamespace(escape=original_re.escape, findall=unexpected))
        negative('discovery', 'candidates_unknown', mode='anchored_discovery', empty=False)
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, 'Path', unexpected)
        negative('discovery', 'control_parts_unknown')
    assert original_path(str(control)).is_absolute()
    class BrokenCandidate(str):
        def __getitem__(self, _key):
            raise OSError('PRIVATE_CANARY')
    with monkeypatch.context() as patch:
        patch.setattr(lifecycle, 're', SimpleNamespace(
            escape=original_re.escape, findall=lambda *_a: [BrokenCandidate(str(control) + '/app')],
        ))
        negative('candidate', 'components_unknown', mode='anchored_discovery', empty=False)
    assert all(type(v) is str for v in original_re.findall(r'/[a-z/]+', '/a/b'))

    # Real qualify_old root predicates, before any unit or process effects.
    service = lifecycle.FixedBwsService(unit='yggdrasil-bws-deploy@dev.service', channel='dev')
    monkeypatch.setattr(service, '_held_runtime', lambda: None)
    for guard, app, ctl, empty in (
        ('separation', projection, projection, True),
        ('fixed_subtree', {**projection, 'path': '/application'}, {**projection, 'path': '/foreign'}, False),
        ('empty_fixed_root', {**projection, 'path': '/application'}, {**projection, 'path': str(control) + '/deeper'}, True),
    ):
        service.phase = 'unqualified'
        with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
            service.qualify_old(application_root=app, control_root=ctl, launcher_content={},
                                control_inventory_empty=empty)
        _assert_root_refinement(caught, (
            'captured_empty' if empty else 'anchored_discovery', 'unknown', 'roots', guard,
        ))
        proved.add(('roots', guard))
    for guard, phase, empty, contract, repeated in (
        ('phase', 'unqualified', False, None, None),
        ('empty_required', 'qualified', False, None, None),
        ('contract_missing', 'qualified', True, None, None),
        ('configuration', 'qualified', True, ('saved',), ('changed',)),
    ):
        service.phase, service.control_inventory_empty, service.contract = phase, empty, contract
        monkeypatch.setattr(service, '_config', lambda: repeated)
        with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
            service.revalidate_empty_control_configuration()
        _assert_root_refinement(caught, (
            'unknown' if guard == 'phase' else 'anchored_discovery' if not empty else 'captured_empty',
            'unknown', 'revalidation', guard,
        ))
        proved.add(('revalidation', guard))
    # The configured comparison is also exercised with the real _config below.
    return proved


def test_root_control_close_uncertainty_overrides_guard_without_leak(monkeypatch, secure_tmp_path, capsys):
    control = secure_tmp_path / 'control'
    control.mkdir(mode=0o755)
    monkeypatch.setattr(lifecycle, 'CONTROL_DIRECTORY', str(control))
    monkeypatch.setattr(lifecycle, '_CONTROL_OWNER_UID', os.geteuid())
    monkeypatch.setattr(lifecycle, '_CONTROL_OWNER_GID', os.getegid())
    info = control.stat()
    projection = dict(path=str(control), device=info.st_dev, inode=info.st_ino,
                      uid=info.st_uid, gid=info.st_gid, mode=info.st_mode & 0o777)
    for failures in (0, 1, 3):
        for earlier_guard in (False, True):
            port = RootControlOS(control)
            if earlier_guard:
                port.arm(dict(operation='fstat', path=str(control), occurrence=0,
                              change={'st_mode': 0o100644}))
            port.close_failures = failures
            monkeypatch.setattr(lifecycle, 'os', port.port())
            if failures or earlier_guard:
                with pytest.raises(lifecycle._OldQualificationRefusal) as caught:
                    lifecycle._discovered_control_projection(b'PRIVATE_CANARY', [], [],
                                                            expected_empty_control_root=projection)
                _assert_root_refinement(caught, (
                    'captured_empty', 'unknown', 'discovery_close' if failures else 'fixed_root',
                    'close_unknown' if failures else 'directory_type',
                ))
            else:
                assert lifecycle._discovered_control_projection(
                    b'PRIVATE_CANARY', [], [], expected_empty_control_root=projection,
                ) == projection
            assert port.closed == list(reversed(port.opened)) and not port.fds
            assert 'PRIVATE_CANARY' not in repr(capsys.readouterr())


def configure_root_control_rpc(lifecycle_module, transaction_module, state, control, application,
                               runtime, public_launcher, channel, *, anchored):
    """External kernel/bus ports for the real NativePorts and real lifecycle."""
    import copy
    import json
    import stat
    real_os = lifecycle_module.os
    lifecycle_module.CONTROL_DIRECTORY = str(control)
    lifecycle_module._CONTROL_OWNER_UID = os.geteuid()
    lifecycle_module._CONTROL_OWNER_GID = os.getegid()
    lifecycle_module.RUNTIME = str(runtime)
    base_properties = {
        ('Unit', 'Id'): f'yggdrasil-bws-deploy@{channel}.service',
        ('Unit', 'LoadState'): 'loaded', ('Service', 'Type'): 'simple',
        ('Service', 'User'): 'root', ('Service', 'Group'): 'root',
        ('Service', 'KillMode'): 'control-group', ('Service', 'Restart'): 'on-failure',
        ('Unit', 'OnFailure'): [], ('Unit', 'OnSuccess'): [], ('Unit', 'TriggeredBy'): [],
        ('Unit', 'ActiveState'): 'active', ('Unit', 'SubState'): 'running',
        ('Unit', 'Job'): [0, '/'], ('Service', 'ControlPID'): 0, ('Service', 'MainPID'): 123,
        ('Service', 'Environment'): [], ('Service', 'EnvironmentFiles'): [],
    }
    for name in ('ExecCondition', 'ExecStartPre', 'ExecStartPost', 'ExecStop', 'ExecReload'):
        base_properties[('Service', name)] = []
    for name, action in (('ExecStart', 'serve'), ('ExecStopPost', 'cleanup')):
        base_properties[('Service', name)] = [[
            lifecycle_module.LAUNCHER, [lifecycle_module.LAUNCHER, action, channel], False,
            1, 2, 3, 4, 5, 1, 0,
        ]]
    fixture = dict(kernel=None, properties=None, case=None, configurations=0, after_qualification=False)
    def prepare(case):
        lifecycle_module.os = real_os
        port = RootControlOS(control, application=application, runtime=runtime, channel=channel,
                             anchored=anchored)
        public_launcher.write_bytes(state.setdefault('baseline_launcher', public_launcher.read_bytes())
                                    + (str(control).encode() if case.get('launcher_hint') else b'\xff' if case.get('decode_failure') else b''))
        fixture.update(kernel=port, properties=copy.deepcopy(base_properties), case=case,
                       configurations=0, after_qualification=False)
        if case.get('no_anchor'):
            port.nodes = {p: v for p, v in port.nodes.items() if not p.startswith(str(control) + '/app')}
        if case.get('multiple_anchors'):
            for name in ('one', 'two'):
                port.add(str(control) + '/' + name, stat.S_IFDIR | 0o755)
                port.add_anchor(str(control) + '/' + name)
        if case.get('os_fault'):
            port.arm(case['os_fault'], discovery=case.get('discovery', 1))
        port.close_failures = case.get('close_failures', 0)
        port.runtime_close_failure = case.get('runtime_close_failure', False)
        # Empty old inventory may drift only in the later lifecycle observation.
        target_discovery = case.get('discovery', 1)
        def on_discovery(number):
            if number == target_discovery and case.get('anchor_drift'):
                port.add_anchor(str(control))
            if number == target_discovery and case.get('slot'):
                port.add(str(control) + '/' + case['slot'], stat.S_IFREG | 0o644)
        port.on_discovery = on_discovery
        lifecycle_module.os = port.port()
    def transport(argv):
        assert argv[0] == 'busctl', 'source guard failure reached a service effect'
        case, properties = fixture['case'], fixture['properties']
        if argv[7] == 'call':
            method = argv[11]
            signature = 'o' if method == 'GetUnit' else 'a(sus)'
            data = ['/org/freedesktop/systemd1/unit/synthetic'] if method == 'GetUnit' else [
                [['PRIVATE_CANARY', 123, 'PRIVATE_CANARY']],
            ]
        else:
            interface, name = argv[-2].rsplit('.', 1)[-1], argv[-1]
            if (interface, name) == ('Unit', 'Id'):
                fixture['configurations'] += 1
                if fixture['configurations'] == case.get('configuration', 1):
                    properties.update(case.get('properties', {}))
            signature = (lifecycle_module.EXEC_TYPE if name.startswith('Exec') else
                         'a(sb)' if name == 'EnvironmentFiles' else
                         'as' if name in {'OnFailure', 'OnSuccess', 'TriggeredBy', 'Environment'} else
                         '(uo)' if name == 'Job' else 'u' if name in {'ControlPID', 'MainPID'} else 's')
            data = properties[(interface, name)]
        return json.dumps(dict(type=signature, data=data)).encode()
    lifecycle_module._run = transport
    original_sources = transaction_module._NativePorts.verify_caller_sources
    def verify_sources(ports, request):
        original_sources(ports, request)
        assert ports._descriptor_service.phase == 'qualified'
        assert ports._descriptor_service.contract is not None
        assert type(ports._descriptor_service.control_inventory_empty) is bool
        fixture['after_qualification'] = True
        if fixture['case'].get('positive'):
            raise OSError('PRIVATE_CANARY synthetic boundary after successful qualification')
    transaction_module._NativePorts.verify_caller_sources = verify_sources
    fixture['prepare'] = prepare
    return fixture


def root_control_rpc_cases(control, *, anchored=False):
    """Reachable lifecycle cases; exact producer-shape exclusions are separate."""
    import stat
    cases = []
    for mode, tree, role, guard, fault in root_control_os_cases(control):
        if (mode == 'anchored_discovery') != anchored:
            continue
        # On empty mode, an anchor observed here is drift after the real empty
        # snapshot/manifest. This is a genuine refusal before its completion.
        # Guard execution and context forwarding are orthogonal. Every semantic
        # row takes the real RPC once; these selected rows additionally prove
        # each distinct stage/side path without four redundant source scans.
        contexts = (1,)
        if not anchored and (role, guard) in {
            ('fixed_root', 'open_unknown'), ('empty_root', 'reopen_identity'),
        }:
            contexts = (1, 2, 3, 4)
        if anchored and (role, guard) == ('anchor_file', 'uid'):
            contexts = (1, 2)
        for discovery in contexts:
            cases.append(dict(
                os_fault=fault, discovery=discovery, anchor_drift=tree and not anchored,
                expected=('anchored_discovery' if anchored else 'captured_empty',
                          'old' if discovery % 2 else 'proposed', role, guard),
                stage='initial' if discovery < 3 else 'empty_control',
            ))
    if not anchored:
        for configuration in (1, 2):
            for guard, prop, value in (
                ('environment_hint', ('Service', 'Environment'), ['PRIVATE_CANARY=' + str(control)]),
                ('environment_files_hint', ('Service', 'EnvironmentFiles'), [[str(control) + '/PRIVATE_CANARY', False]]),
            ):
                cases.append(dict(configuration=configuration, properties={prop: value},
                                  expected=('captured_empty', 'old', 'hints', guard),
                                  stage='initial' if configuration == 1 else 'empty_control'))
            for slot in ('app', 'scripts'):
                cases.append(dict(slot=slot, discovery=1 if configuration == 1 else 3,
                                  expected=('captured_empty', 'old', slot + '_slot', 'present'),
                                  stage='initial' if configuration == 1 else 'empty_control'))
        cases.append(dict(decode_failure=True, expected=('unknown', 'old', 'discovery', 'decode_unknown'), stage='initial'))
        cases.append(dict(properties={('Service', 'Environment'): [7]}, expected_gate='old_kernel_initial_unit_properties'))
        cases.append(dict(properties={('Service', 'EnvironmentFiles'): [[7, False]]}, expected_gate='old_kernel_initial_unit_properties'))
        cases.append(dict(launcher_hint=True, expected=('captured_empty', 'old', 'hints', 'launcher_hint'), stage='initial'))
        cases.append(dict(anchor_drift=True, expected=('captured_empty', 'old', 'empty_root', 'anchored_root_present'),
                          stage='initial'))
        cases.append(dict(close_failures=3, expected=('captured_empty', 'old', 'discovery_close', 'close_unknown'),
                          stage='initial'))
        cases.append(dict(os_fault=dict(operation='fstat', path=str(control), occurrence=0,
                                       change={'st_mode': stat.S_IFREG | 0o644}), close_failures=3,
                          expected=('captured_empty', 'old', 'discovery_close', 'close_unknown'), stage='initial'))
        cases.append(dict(configuration=2, properties={('Service', 'Environment'): ['PRIVATE_CANARY=value']},
                          expected=('captured_empty', 'unknown', 'revalidation', 'configuration'), stage='empty_control'))
    else:
        cases.append(dict(no_anchor=True, expected=('anchored_discovery', 'old', 'anchored_roots', 'no_anchor'), stage='initial'))
        cases.append(dict(multiple_anchors=True,
                          properties={('Service', 'Environment'): [str(control) + '/one/app ' + str(control) + '/two/app']},
                          expected=('anchored_discovery', 'old', 'anchored_roots', 'multiple_anchors'), stage='initial'))
        for guard, hint in (
            ('candidate_count', ' '.join(str(control) + '/' + str(i) for i in range(17))),
            ('component_count', str(control) + '/' + '/'.join(['a'] * 33)),
            ('components_canonical', str(control) + '/a/../b'),
        ):
            role = 'hints' if guard == 'candidate_count' else 'candidate'
            cases.append(dict(properties={('Service', 'Environment'): [hint]},
                              expected=('anchored_discovery', 'old', role, guard), stage='initial'))
        # The actual proposed Git launcher is unchanged; only the kernel's
        # projection observation drifts on its own second side.
        for discovery in (1, 2):
            cases.append(dict(os_fault=dict(operation='fstat', path=str(control), occurrence=2,
                                           change={'st_ino': 987654321}), discovery=discovery,
                              expected=('anchored_discovery', 'old' if discovery == 1 else 'proposed',
                                        'comparison', 'identity'), stage='initial'))
    cases.append(dict(positive=True, expected_gate='generation_qualification'))
    return cases


def root_control_golden_trace(control, *, anchored):
    """Original public OS-call sequence for the two successful fixed shapes."""
    root = str(control)
    trace = []
    def directory(path):
        trace.extend((op, path) for op in ('open', 'fstat', 'inheritable'))
    def walk():
        directory('/')
        path = ''
        for name in Path(control).parts[1:]:
            path += '/' + name
            directory(path)
    walk()
    if anchored:
        for suffix in ('/app', '/app/ops'):
            trace.append(('stat', root + suffix))
            directory(root + suffix)
        trace.extend((
            ('stat', root + '/app/ops/postgres_deploy_linux.py'),
            ('stat', root + '/app/ops/app'), ('stat', root + '/app/app'),
        ))
        for suffix in ('/app', '/app/ops'):
            trace.append(('stat', root + suffix))
            directory(root + suffix)
        trace.extend((('stat', root + '/app/ops/postgres_deploy_linux.py'),
                      ('fstat', root), ('fstat', root)))
    else:
        trace.extend((('stat', root + '/app'), ('stat', root + '/app'), ('fstat', root),
                      ('stat', root + '/app'), ('stat', root + '/scripts')))
        walk()
        trace.append(('fstat', root))
    return trace


def configure_control_path_service(module, patch, state, control, application, runtime,
                                   public_launcher, channel, environment):
    """Real typed producer/lifecycle; replace only external kernel/service metadata."""
    import copy
    import json
    import time
    from types import SimpleNamespace
    patch.setattr(module, 'CONTROL_DIRECTORY', str(control))
    patch.setattr(module, '_CONTROL_OWNER_UID', os.geteuid())
    patch.setattr(module, '_CONTROL_OWNER_GID', os.getegid())
    patch.setattr(module, 'RUNTIME', str(runtime))
    patch.setattr(module, 'LAUNCHER', str(public_launcher))
    patch.setattr(module, 'PROC', application / 'absent-proc')
    real_os = module.os
    runtime_inode = runtime.stat().st_ino
    def observed(info):
        if info.st_ino != runtime_inode:
            return info
        return SimpleNamespace(**{**{name: getattr(info, name) for name in dir(info)
                                     if name.startswith('st_')}, 'st_uid': 0, 'st_gid': 0})
    patch.setattr(module, 'os', SimpleNamespace(**{
        **vars(real_os), 'fstat': lambda fd: observed(real_os.fstat(fd)),
        'stat': lambda *a, **kw: observed(real_os.stat(*a, **kw)),
    }))
    if sys.platform != 'linux':
        # macOS has no Linux statx. Replace only that OS metadata port; Linux CI
        # exercises the actual syscall, including mount IDs on held directories.
        patch.setattr(module, '_control_path_mount', lambda fd: real_os.fstat(fd).st_dev)
    properties = {
        ('Unit', 'Id'): f'yggdrasil-bws-deploy@{channel}.service',
        ('Unit', 'LoadState'): 'loaded', ('Service', 'Type'): 'simple',
        ('Service', 'User'): 'root', ('Service', 'Group'): 'root',
        ('Service', 'KillMode'): 'control-group', ('Service', 'Restart'): 'on-failure',
        ('Unit', 'ActiveState'): 'active', ('Unit', 'SubState'): 'running',
        ('Unit', 'Job'): [0, '/'], ('Service', 'ControlPID'): 0, ('Service', 'MainPID'): 123,
        ('Service', 'Environment'): list(environment), ('Service', 'EnvironmentFiles'): [],
        ('Service', 'Result'): 'success',
    }
    for name in ('OnFailure', 'OnSuccess', 'TriggeredBy', 'DropInPaths', 'JoinsNamespaceOf'):
        properties['Unit', name] = []
    for name in ('ExecCondition', 'ExecStartPre', 'ExecStartPost', 'ExecStop', 'ExecReload',
                 'BindPaths', 'BindReadOnlyPaths', 'TemporaryFileSystem', 'ReadOnlyPaths',
                 'ReadWritePaths', 'InaccessiblePaths', 'PassEnvironment', 'UnsetEnvironment', 'ExecSearchPath',
                 'ExtensionDirectories', 'MountImages', 'ExtensionImages'):
        properties['Service', name] = []
    for name in ('RootDirectory', 'RootImage', 'WorkingDirectory', 'PAMName'):
        properties['Service', name] = ''
    for name in ('PrivateMounts', 'PrivateTmp', 'PrivateDevices', 'PrivateUsers', 'DynamicUser'):
        properties['Service', name] = False
    for name in ('ProtectHome', 'ProtectSystem'):
        properties['Service', name] = 'no'
    for name, action in (('ExecStart', 'serve'), ('ExecStopPost', 'cleanup')):
        properties['Service', name] = [[module.LAUNCHER, [module.LAUNCHER, action, channel],
                                        False, 1, 2, 3, 4, 5, 1, 0]]
    def transport(argv):
        if argv[0] == 'systemctl':
            action = argv[-2]
            state['events'].append(action)
            if action == 'stop':
                properties['Unit', 'ActiveState'], properties['Unit', 'SubState'] = 'inactive', 'dead'
                properties['Service', 'MainPID'] = 0
                now = time.monotonic_ns() // 1000
                row = properties['Service', 'ExecStopPost'][0]
                row[3:] = [1, now, 2, now, 900, 1, 0]
            else:
                properties['Unit', 'ActiveState'], properties['Unit', 'SubState'] = 'active', 'running'
                properties['Service', 'MainPID'] = 456
                if state.get('consume_start'):
                    state['consume_start']()
            return b''
        if argv[7] == 'call':
            method = argv[11]
            signature = 'o' if method == 'GetUnit' else 'a(sus)'
            pid = properties['Service', 'MainPID']
            data = ['/org/freedesktop/systemd1/unit/synthetic'] if method == 'GetUnit' else [
                [['synthetic', pid, 'synthetic']] if pid else [],
            ]
        else:
            interface, name = argv[-2].rsplit('.', 1)[-1], argv[-1]
            value = properties[interface, name]
            signature = (module.EXEC_TYPE if name.startswith('Exec') and name != 'ExecSearchPath' else
                         'a(sb)' if name == 'EnvironmentFiles' else 'a(ssbt)' if name in {'BindPaths', 'BindReadOnlyPaths'} else
                         'a(ss)' if name == 'TemporaryFileSystem' else
                         'a(ssba(ss))' if name == 'MountImages' else
                         'a(sba(ss))' if name == 'ExtensionImages' else '(uo)' if name == 'Job' else
                         'b' if type(value) is bool else 'u' if type(value) is int else
                         'as' if type(value) is list else 's')
            data = copy.deepcopy(value)
        return json.dumps(dict(type=signature, data=data)).encode()
    patch.setattr(module, '_run', transport)
    patch.setattr(module, '_pid_token', lambda _u, _c, pid, _a, _r: ('5' if pid == 123 else '6') * 64)
    return properties


def control_path_fixture(monkeypatch, secure_tmp_path, *, channel='dev', slot='descendant'):
    from types import SimpleNamespace
    base = secure_tmp_path.resolve()
    roots = {}
    for name in ('control', 'application', 'launcher', 'backup'):
        path = base / name
        path.mkdir(mode=0o755)
        roots[name] = path
    runtime = base / 'runtime'
    runtime.write_bytes(b'runtime')
    runtime.chmod(0o755)
    launcher = roots['launcher'] / 'yggdrasil-bws-deploy'
    launcher.write_bytes(b'old launcher')
    launcher.chmod(0o755)
    control = roots['control']
    if slot == 'descendant':
        (control / 'lookup').mkdir(mode=0o755)
    path = control if slot == 'root' else control / ('lookup' if slot == 'descendant' else 'absent/deeper')
    environment = ['LLM_PROVIDER=mock', f'PATH=/usr/bin:{path}:/bin', 'UNCHANGED=exact value']
    state = {'events': []}
    properties = configure_control_path_service(lifecycle, monkeypatch, state, control,
        roots['application'], runtime, launcher, channel, environment)
    monkeypatch.setattr(lifecycle, '_public_launcher_bytes', launcher.read_bytes)
    def identity(path):
        info = path.stat()
        return dict(path=str(path), device=info.st_dev, inode=info.st_ino,
                    uid=info.st_uid, gid=info.st_gid, mode=info.st_mode & 0o777)
    service = lifecycle.FixedBwsService(unit=f'yggdrasil-bws-deploy@{channel}.service', channel=channel)
    payload = launcher.read_bytes()
    arguments = dict(application_root=identity(roots['application']), control_root=identity(control),
                     control_inventory_empty=True, installation_footprint=tuple(identity(roots[n])
                         for n in ('application', 'launcher', 'backup')),
                     launcher_content=dict(sha256=hashlib.sha256(payload).hexdigest(),
                                           base64=base64.b64encode(payload).decode()))
    return SimpleNamespace(service=service, arguments=arguments, properties=properties,
                           state=state, roots=roots, slot=path, environment=environment)


@pytest.mark.parametrize('slot', ['root', 'descendant', 'absent'])
def test_control_path_projection_preserves_typed_environment(monkeypatch, secure_tmp_path, slot):
    fixture = control_path_fixture(monkeypatch, secure_tmp_path, slot=slot)
    with fixture.service.retained_runtime():
        fixture.service.qualify_old(**fixture.arguments)
        contract = fixture.service.contract
        assert contract[2] == tuple(fixture.environment)
        assert fixture.service._config() == contract
        fixture.service.revalidate_empty_control_configuration()
        assert fixture.service.control_path_binding.fds
    assert fixture.service.runtime_close_completed
    assert not fixture.service.control_path_binding.fds
    assert not fixture.state['events']


@pytest.mark.parametrize('fault', ['executable', 'symlink', 'fifo', 'hardlink', 'writable',
    'foreign', 'relative', 'duplicate', 'empty', 'unknown_hint', 'environment_file', 'loader',
    'namespace', 'changed_environment', 'changed_lookup', 'changed_mount', 'overlap'])
def test_control_path_slot_refusal_matrix(monkeypatch, secure_tmp_path, fault):
    fixture = control_path_fixture(monkeypatch, secure_tmp_path)
    slot, properties = fixture.slot, fixture.properties
    if fault in {'executable', 'hardlink', 'writable'}:
        item = slot / 'candidate'
        item.write_bytes(b'unread PRIVATE_CANARY')
        item.chmod(0o755 if fault == 'executable' else 0o666 if fault == 'writable' else 0o644)
        if fault == 'hardlink':
            os.link(item, slot / 'second')
    if fault == 'symlink':
        (slot / 'candidate').symlink_to('/outside/PRIVATE_CANARY')
    if fault == 'fifo':
        os.mkfifo(slot / 'candidate')
    if fault == 'foreign':
        monkeypatch.setattr(lifecycle, '_CONTROL_OWNER_UID', os.geteuid() + 1)
    if fault == 'relative':
        properties['Service', 'Environment'][1] += ':relative'
    if fault == 'duplicate':
        properties['Service', 'Environment'].append('PATH=/usr/bin')
    if fault == 'empty':
        properties['Service', 'Environment'][1] += ':'
    if fault == 'unknown_hint':
        properties['Service', 'Environment'].append('PYTHONPATH=' + str(slot))
    if fault == 'environment_file':
        properties['Service', 'EnvironmentFiles'] = [['/private/PRIVATE_CANARY', False]]
    if fault == 'loader':
        (fixture.roots['control'] / 'app').mkdir()
    if fault == 'namespace':
        properties['Service', 'RootDirectory'] = '/private/PRIVATE_CANARY'
    if fault == 'overlap':
        fixture.arguments['installation_footprint'] = (fixture.arguments['control_root'],) * 3
    with fixture.service.retained_runtime():
        if fault.startswith('changed_'):
            fixture.service.qualify_old(**fixture.arguments)
            if fault == 'changed_environment':
                properties['Service', 'Environment'].reverse()
            elif fault == 'changed_lookup':
                slot.rename(slot.with_name('old'))
                slot.mkdir(mode=0o755)
            else:
                original = lifecycle._control_path_mount
                monkeypatch.setattr(lifecycle, '_control_path_mount', lambda fd: original(fd) + 1)
            with pytest.raises(RuntimeError):
                fixture.service.revalidate_empty_control_configuration()
        else:
            with pytest.raises(RuntimeError):
                fixture.service.qualify_old(**fixture.arguments)
    assert not fixture.state['events']
    assert fixture.service.runtime_close_completed
    if fixture.service.control_path_binding:
        assert not fixture.service.control_path_binding.fds
