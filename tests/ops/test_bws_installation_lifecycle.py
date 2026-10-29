"""Synthetic boundary tests for the fixed DEV/TEST BWS unit lifecycle."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest

from app.ops import bws_installation_lifecycle as lifecycle
from tests.deploy.bws_fixture_support import bws_secure_tmp_path  # noqa: F401


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
