from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import shlex
import site
import socket
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator

import pytest

from tests.helpers.runtime_start_harness import run_runtime_start

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/colima_runtime_readiness.sh"
SYSTEMD = ROOT / "ops/host-setup/mac-mini/systemd"
INSTALLER = ROOT / "ops/host-setup/mac-mini/install_colima_runtime_readiness.sh"


@pytest.fixture
def docker_socket_path() -> Iterator[Path]:
    # macOS limits AF_UNIX pathname length; pytest's nested tmp_path is too long.
    with tempfile.TemporaryDirectory(prefix="d", dir="/tmp") as directory:
        yield Path(directory) / "s"


def create_docker_socket(path: Path) -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.close()
    path.chmod(0o660)


@pytest.fixture
def runtime(tmp_path: Path) -> dict[str, str]:
    bins = tmp_path / "bin"
    bins.mkdir()
    fake = bins / "fake"
    fake.write_text(
        f"#!{sys.executable}\n"
        + """
import hashlib, json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['TEST_CALLS'], 'a') as f:
    f.write(json.dumps([name, *args]) + '\\n')
mode = os.environ.get('TEST_MODE', '')
if name == 'findfs':
    print('/dev/resolved')
elif name == 'findmnt':
    field = args[args.index('-o')+1]
    target = args[-1]
    root = '/docker' if target == os.environ['COLIMA_DOCKER_DATA_PATH'] else '/containerd' if target == os.environ['COLIMA_CONTAINERD_DATA_PATH'] else '/'
    print({'SOURCE': '/dev/wrong' if mode == 'wrong-device' else '/dev/resolved', 'FSROOT': '/wrong' if mode == 'wrong-root' else root, 'UUID': 'wrong' if mode == 'wrong-uuid' else 'test-uuid', 'FSTYPE': 'ext4', 'OPTIONS': 'ro' if mode == 'read-only' else 'rw,relatime'}[field])
elif name == 'df':
    print('Filesystem total used available percent mount')
    print('/dev/resolved 9999999 1 ' + ('0' if mode == 'full' else '999999') + ' 1% /')
elif name == 'ctr':
    sys.exit(1 if mode == 'ctr-down' else 0)
elif name == 'docker':
    if args[:2] == ['ps', '-aq']:
        print('1'*64 if mode == 'truncated' else '1'*64 + '\\n' + ('3' if mode == 'wrong-id' else '2')*64)
    elif args[:2] == ['context', 'inspect'] and '--format' in args:
        print('unix:///wrong' if mode == 'wrong-socket' else 'unix://' + os.environ['HOME'] + '/.colima/default/docker.sock')
elif name == 'colima':
    if args[0] == 'status' and mode in ('start-cli-failure', 'cold-start-unapproved'):
        sys.exit(1)
    if args[0] == 'start':
        pathlib.Path(os.environ['TEST_CALLS'] + '.usernet').write_text(os.environ.get('LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT', ''))
        sys.exit(1)
    if args[0] == 'ssh' and args[-1] == '--guest' and mode == 'guest-failure':
        sys.exit(1)
    if args[0] == 'ssh' and 'python3' in args and mode == 'missing-python':
        sys.exit(1)
    if args[0] == 'ssh' and 'mask' in args:
        pathlib.Path(os.environ['TEST_CALLS'] + '.masked').write_text('persistent')
    if args[0] == 'ssh' and 'unmask' in args:
        pathlib.Path(os.environ['TEST_CALLS'] + '.masked').unlink()
    if args[0] == 'ssh' and 'for unit in docker.service' in args[-1] and mode == 'units-active':
        sys.exit(1)
    if args[0] == 'ssh' and 'install' in args and mode == 'install-interrupted':
        sys.exit(1)
    if args[0] == 'ssh' and 'install' in args:
        # Store the exact bytes streamed by the real host installer.
        target = args[-1]
        p = pathlib.Path(os.environ['TEST_INSTALLED']) / target.lstrip('/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(sys.stdin.buffer.read())
    if args[0] == 'ssh' and 'mv' in args:
        base = pathlib.Path(os.environ['TEST_INSTALLED'])
        (base / args[-2].lstrip('/')).replace(base / args[-1].lstrip('/'))
    if args[0] == 'ssh' and 'sha256sum' in args:
        p = pathlib.Path(os.environ['TEST_INSTALLED']) / args[-1].lstrip('/')
        print(hashlib.sha256(p.read_bytes()).hexdigest() + '  artifact')
elif name == 'systemctl' and args[:2] == ['show', 'containerd.service']:
    print('31415')
elif name in ('mountpoint', 'mount') and mode.startswith('mount-'):
    target = args[-1]
    marker = pathlib.Path(os.environ['TEST_CALLS'] + '.' + hashlib.sha256(target.encode()).hexdigest())
    if name == 'mountpoint':
        sys.exit(0 if marker.exists() else 1)
    if mode == 'mount-fail-containerd' and target == os.environ['COLIMA_CONTAINERD_DATA_PATH']:
        sys.exit(1)
    marker.write_text('mounted')
    if '--bind' not in args:
        for child in ('docker', 'containerd'):
            (pathlib.Path(target) / child).mkdir(exist_ok=True)
elif name not in ('mountpoint', 'systemctl', 'mount'):
    sys.exit(99)
"""
    )
    fake.chmod(0o755)
    for name in (
        "findfs",
        "findmnt",
        "df",
        "ctr",
        "docker",
        "colima",
        "mountpoint",
        "systemctl",
        "mount",
    ):
        (bins / name).symlink_to(fake)
    persistent, docker, containerd = (tmp_path / n for n in ("persistent", "docker", "containerd"))
    for p in (persistent, docker, containerd):
        p.mkdir()
    for name in ("1" * 64, "2" * 64):
        p = docker / "containers" / name
        p.mkdir(parents=True)
        (p / "config.v2.json").write_text(
            json.dumps(
                {
                    "ID": name,
                    "State": {"Dead": False, "Running": False},
                    "HasBeenStartedBefore": True,
                    "MountPoints": {},
                }
            )
        )
        (p / "hostconfig.json").write_text(
            json.dumps(
                {
                    "AutoRemove": False,
                    "RestartPolicy": {"Name": "no"},
                }
            )
        )
    home = tmp_path / "runtime-home"
    home.mkdir()
    return {
        **{k: os.environ[k] for k in ("TMPDIR",) if k in os.environ},
        "HOME": str(home),
        "PATH": f"{bins}:{os.environ['PATH']}",
        "TEST_CALLS": str(tmp_path / "calls"),
        "TEST_INSTALLED": str(tmp_path / "installed"),
        "COLIMA_RUNTIME_PROVIDER": "colima",
        "COLIMA_PROFILE": "default",
        "COLIMA_DOCKER_CONTEXT": "colima",
        "LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT": "3",
        "COLIMA_HOST_READY_TIMEOUT_SECONDS": "0",
        "COLIMA_PERSISTENT_DATA_PATH": str(persistent),
        "COLIMA_DOCKER_DATA_PATH": str(docker),
        "COLIMA_CONTAINERD_DATA_PATH": str(containerd),
        "COLIMA_PERSISTED_CONFIG_ROOT": str(docker / "containers"),
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY": "UUID=test-uuid",
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE": "ext4",
        "COLIMA_EXPECTED_PERSISTED_INVENTORY": "2",
        "COLIMA_MIN_FREE_BLOCKS": "1",
        "COLIMA_MIN_FREE_INODES": "1",
        "COLIMA_CONTAINERD_READY_TIMEOUT_SECONDS": "0",
        "COLIMA_CPU": "4",
        "COLIMA_MEMORY": "6",
        "COLIMA_DISK": "60",
        "DOCKER_CONTEXT": "wrong-inherited-context",
    }


def run(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$1"; ' + command, "test", str(HELPER)],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )


def calls(env: dict[str, str]) -> list[list[str]]:
    p = Path(env["TEST_CALLS"])
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def startup_entrypoint(
    tmp_path: Path, runtime: dict[str, str], channel: str
) -> tuple[Path, dict[str, str]]:
    """Run the real launcher/libraries while replacing external effect ports."""
    repo = tmp_path / "startup-repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copytree(ROOT / "scripts/lib", repo / "scripts/lib")
    for name in ("start_full_system.sh", "export_runtime_env.sh"):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "config/deploy").mkdir(parents=True)
    for name in ("runtime.defaults.env", f"deploy/{channel}.env"):
        shutil.copy2(ROOT / "config" / name, repo / "config" / name)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **runtime,
        "HOME": str(home),
        "PYTHONPATH": str(ROOT),
        "PYTHONUSERBASE": site.USER_BASE,
        "PKM_ENVIRONMENT": channel,
        "LLM_PROVIDER": "mock",
        "LLM_MODEL": "mock",
        "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(tmp_path / "ownership"),
        "RUNTIME_ENV_PATH": str(tmp_path / "runtime.env"),
        "STARTUP_DISK_MIN_FREE_MIB": "1",
        "STARTUP_DISK_WARN_FREE_MIB": "0",
        "STARTUP_CHECK_OBSIDIAN": "0",
        "BUILDEROPS_BOOTSTRAP": "1",
        "START_FLIGHT_RECORDER": "1",
        "TEST_DOCKER_BINDINGS": str(tmp_path / "docker-bindings"),
    }
    profile = tmp_path / "profile.env"
    profile.write_text(
        "".join(
            f"{key}={value}\n"
            for key, value in runtime.items()
            if key.startswith("COLIMA_") or key == "LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT"
        )
    )
    env["COLIMA_RESOURCE_PROFILE_FILE"] = str(profile)
    # HOME is deliberately isolated; avoid pyenv selecting a different Python
    # without the test environment's dependencies under that empty home.
    for name in ("python", "python3"):
        interpreter = Path(runtime["PATH"].split(os.pathsep)[0]) / name
        interpreter.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
        interpreter.chmod(0o755)
    docker = Path(runtime["PATH"].split(os.pathsep)[0]) / "docker"
    fake = docker.resolve()
    docker.unlink()
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['TEST_DOCKER_BINDINGS'], 'a') as f:\n"
        " f.write(json.dumps({'args': args, 'context': os.environ.get('DOCKER_CONTEXT'), 'host': os.environ.get('DOCKER_HOST')}) + '\\n')\n"
        "if args and args[0] == 'compose':\n"
        " with open(os.environ['TEST_CALLS'], 'a') as f: f.write(json.dumps(['docker', *args]) + '\\n')\n"
        " sys.exit(83)  # Stop at the first fully fake Compose boundary.\n"
        # Preserve argv[0]: the shared fake dispatches by executable name.
        f"exec(compile(pathlib.Path({str(fake)!r}).read_text(), {str(fake)!r}, 'exec'))\n"
    )
    docker.chmod(0o755)
    for name, event in (
        ("start_builderops_services.sh", "builderops-bootstrap"),
        ("flight_recorder.sh", "flight-recorder"),
    ):
        auxiliary = repo / "scripts" / name
        auxiliary.write_text(
            f"#!{sys.executable}\n"
            "import json, os, pathlib, sys\n"
            f"with open(os.environ['TEST_CALLS'], 'a') as f: f.write(json.dumps([{event!r}]) + '\\n')\n"
            "if '--log-path' in sys.argv: pathlib.Path(sys.argv[sys.argv.index('--log-path')+1]).touch()\n"
        )
        auxiliary.chmod(0o755)
    return repo, env


@pytest.mark.parametrize("channel", ["dev", "test"])
@pytest.mark.parametrize("refusal", ["missing-profile", "wrong-socket"])
def test_real_startup_refuses_before_compose_or_auxiliary_effects(
    tmp_path: Path, runtime: dict[str, str], channel: str, refusal: str
) -> None:
    repo, env = startup_entrypoint(tmp_path, runtime, channel)
    if refusal == "missing-profile":
        Path(env["COLIMA_RESOURCE_PROFILE_FILE"]).unlink()
        reason = "resource profile unreadable"
    else:
        env["TEST_MODE"] = "wrong-socket"
        reason = "docker socket mismatch"
    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=repo, env=env, progress_path=Path(env["TEST_CALLS"]),
    )
    assert result.returncode != 0
    assert reason in result.stderr, result.stdout + result.stderr
    assert not any(
        c[0] in {"builderops-bootstrap", "flight-recorder"} or c[:2] == ["docker", "compose"]
        for c in calls(env)
    )


@pytest.mark.parametrize("channel", ["dev", "test"])
def test_real_startup_exports_verified_binding_before_compose(
    tmp_path: Path, runtime: dict[str, str], channel: str
) -> None:
    repo, env = startup_entrypoint(tmp_path, runtime, channel)
    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=repo, env=env, progress_path=Path(env["TEST_CALLS"]),
    )
    assert result.returncode != 0  # The fake deliberately refuses actual Compose execution.
    events = calls(env)
    compose = next(i for i, c in enumerate(events) if c[:2] == ["docker", "compose"])
    guest = next(i for i, c in enumerate(events) if c[0] == "colima" and c[-1] == "--guest")
    inventory = next(i for i, c in enumerate(events) if c == ["docker", "ps", "-aq", "--no-trunc"])
    assert guest < inventory < compose
    assert all(
        i > inventory for i, c in enumerate(events)
        if c[0] in {"builderops-bootstrap", "flight-recorder"}
    )
    bindings = [json.loads(x) for x in Path(env["TEST_DOCKER_BINDINGS"]).read_text().splitlines()]
    actual = next(x for x in bindings if x["args"][0] == "compose")
    assert actual["context"] == "colima"
    assert actual["host"] == f"unix://{env['HOME']}/.colima/default/docker.sock"


def test_real_startup_preserves_disk_refusal_before_docker(
    tmp_path: Path, runtime: dict[str, str]
) -> None:
    repo, env = startup_entrypoint(tmp_path, runtime, "dev")
    env["TEST_MODE"] = "full"
    result = run_runtime_start(
        ["bash", "scripts/start_full_system.sh"],
        cwd=repo, env=env, progress_path=Path(env["TEST_CALLS"]),
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "below STARTUP_DISK_MIN_FREE_MIB" in result.stderr
    assert not any(c[0] in {"docker", "colima", "builderops-bootstrap", "flight-recorder"} for c in calls(env))


@pytest.mark.parametrize("mode", ["wrong-device", "wrong-root", "wrong-uuid", "read-only", "full"])
def test_installed_units_fail_closed_until_exact_persistent_substrate_is_ready(
    runtime: dict[str, str], mode: str
) -> None:
    env = {**runtime, "TEST_MODE": mode}
    result = run("colima_guest_readiness_gate", env)
    assert result.returncode != 0
    assert "persistent substrate" in result.stderr
    assert not any(c[0] in ("ctr", "docker", "mount") for c in calls(env))
    containerd = (
        SYSTEMD / "containerd.service.d/20-yggdrasil-persistent-substrate.conf"
    ).read_text()
    docker = (SYSTEMD / "docker.service.d/20-yggdrasil-containerd-readiness.conf").read_text()
    docker_socket = (SYSTEMD / "docker.socket.d/20-yggdrasil-readiness.conf").read_text()
    assert "Requires=yggdrasil-colima-persistent-substrate.service" in containerd
    assert "ExecStartPre=" in containerd and "--substrate" in containerd
    assert "Requires=containerd.service" in docker
    assert (
        "--docker-api-close" in docker and "--docker-preflight" in docker
        and "ExecStartPost=" in docker and "--post-start" in docker
        and "Sockets=docker.socket" in docker
        and "ExecStopPost=" in docker and "--docker-api-cleanup" in docker
    )
    assert "PartOf=docker.service" in docker_socket
    assert "SocketMode=0600" in docker_socket and "SocketGroup=docker" in docker_socket
    assert "Restart=no" in containerd and "Restart=no" in docker
    assert "EnvironmentFile=/etc/yggdrasil/colima-runtime.env" in docker


def test_startup_entrypoints_share_one_bounded_colima_readiness_helper(
    runtime: dict[str, str],
) -> None:
    for name in ("scripts/dev_bootstrap.sh", "scripts/start_full_system.sh"):
        text = (ROOT / name).read_text()
        assert 'colima_runtime_bind_and_ready "$ROOT"' in text
        assert "colima start" not in text
    env = {
        **runtime,
        "TEST_MODE": "start-cli-failure",
        "AUTO_START_COLIMA": "1",
        "COLIMA_COLD_START_AUTHORIZED": "1",
    }
    assert run("colima_runtime_bind_and_ready /repo", env).returncode == 0
    commands = calls(env)
    start = next(c for c in commands if c[:2] == ["colima", "start"])
    assert start == [
        "colima",
        "start",
        "--profile",
        "default",
        "--cpu",
        "4",
        "--memory",
        "6",
        "--disk",
        "60",
    ]
    assert Path(env["TEST_CALLS"] + ".usernet").read_text() == "3"
    assert any(c[-1] == "--guest" for c in commands)
    assert ["docker", "ps", "-aq", "--no-trunc"] in commands


def test_persisted_inventory_mismatch_fails_without_mutating_metadata(
    runtime: dict[str, str],
) -> None:
    env = {
        **runtime,
        "TEST_MODE": "truncated",
        "COLIMA_INVENTORY_EXACT": "true",
        "COLIMA_RUNTIME_RECEIPT_PATH": str(Path(runtime["TEST_CALLS"]).with_suffix(".json")),
    }
    before = {
        p: p.read_bytes()
        for p in Path(env["COLIMA_PERSISTED_CONFIG_ROOT"]).rglob("*")
        if p.is_file()
    }
    result = run("colima_runtime_assert_inventory", env)
    assert result.returncode != 0 and "inventory" in result.stderr
    assert before == {p: p.read_bytes() for p in before}
    assert calls(env) == [
        ["docker", "context", "inspect", "colima"],
        ["docker", "ps", "-aq", "--no-trunc"],
    ]
    receipt = json.loads(Path(env["COLIMA_RUNTIME_RECEIPT_PATH"]).read_text())
    assert receipt["state"] == "refused" and receipt["docker_inventory_count"] == 1
    assert receipt["inventory_exact"] is False
    assert env["COLIMA_PERSISTED_CONFIG_ROOT"] not in json.dumps(receipt)


@pytest.mark.parametrize("mode", ["wrong-socket", "guest-failure", "cold-start-unapproved"])
def test_host_refuses_wrong_socket_failed_guest_and_unserialized_start(
    runtime: dict[str, str], mode: str
) -> None:
    env = {**runtime, "TEST_MODE": mode, "AUTO_START_COLIMA": "1"}
    assert run("colima_runtime_bind_and_ready /repo", env).returncode != 0
    assert not any(c[:2] == ["colima", "start"] for c in calls(env))


def test_containerd_gate_probes_rpc_and_metadata_before_inventory(runtime: dict[str, str]) -> None:
    assert run("colima_guest_readiness_gate", runtime).returncode == 0
    assert [c for c in calls(runtime) if c[0] == "ctr"] == [
        ["ctr", "version"],
        ["ctr", "--namespace", "moby", "containers", "list"],
        ["ctr", "--namespace", "moby", "snapshots", "list"],
    ]
    assert not any(c[0] == "docker" for c in calls(runtime))
    assert run("colima_guest_readiness_gate", {**runtime, "TEST_MODE": "ctr-down"}).returncode != 0


def test_installer_streams_checked_in_units_only_after_host_gates(
    runtime: dict[str, str], tmp_path: Path
) -> None:
    profile = tmp_path / "profile.env"
    keys = [
        k
        for k in runtime
        if k.startswith("COLIMA_")
        and k
        not in ("COLIMA_HOST_READY_TIMEOUT_SECONDS", "COLIMA_CONTAINERD_READY_TIMEOUT_SECONDS")
    ]
    values = {k: runtime[k] for k in keys}
    values["LIMA_USERNET_RESOLVE_IP_ADDRESS_TIMEOUT"] = "3"
    values.update(
        COLIMA_DOCKER_DATA_PATH="/var/lib/docker",
        COLIMA_CONTAINERD_DATA_PATH="/var/lib/containerd",
        COLIMA_PERSISTED_CONFIG_ROOT="/var/lib/docker/containers",
    )
    profile.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    env = {**runtime, "COLIMA_RUNTIME_APPLY": "1", "COLIMA_RUNTIME_ENV_FILE": str(profile)}

    def install(e: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(INSTALLER)], env=e, capture_output=True, text=True, timeout=15, check=False
        )

    assert install(env).returncode != 0
    assert not calls(env)
    env.update(COLIMA_COLD_START_AUTHORIZED="1", COLIMA_ISOLATED_PROOF_ACCEPTED="1")
    start = len(calls(env))
    assert install({**env, "TEST_MODE": "missing-python"}).returncode != 0
    assert not any("mask" in c or "install" in c for c in calls(env)[start:])
    start = len(calls(env))
    assert install({**env, "TEST_MODE": "units-active"}).returncode != 0
    assert not any("mask" in c or "install" in c for c in calls(env)[start:])
    result = install(env)
    assert result.returncode == 0, result.stderr
    installed = Path(env["TEST_INSTALLED"])
    for p in SYSTEMD.rglob("*"):
        if p.is_file():
            assert (
                installed / "etc/systemd/system" / p.relative_to(SYSTEMD)
            ).read_bytes() == p.read_bytes()
    assert (
        installed / "usr/local/libexec/yggdrasil-colima-runtime-readiness"
    ).read_bytes() == HELPER.read_bytes()
    assert (installed / "usr/local/libexec/yggdrasil-colima-inventory.py").read_bytes() == (
        ROOT / "scripts/lib/colima_inventory.py"
    ).read_bytes()
    assert Path(env["TEST_CALLS"] + ".masked").is_file()
    assert not any("restart" in c or "start" in c for c in calls(env))
    assert install({**env, "TEST_MODE": "install-interrupted"}).returncode != 0
    assert Path(env["TEST_CALLS"] + ".masked").is_file()
    assert install(env).returncode == 0
    assert Path(env["TEST_CALLS"] + ".masked").is_file()
    assert install({**env, "COLIMA_RUNTIME_ACTIVATE": "1"}).returncode == 0
    assert not Path(env["TEST_CALLS"] + ".masked").exists()
    values["COLIMA_DOCKER_DATA_PATH"] = "/unrelated/root"
    profile.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    assert install(env).returncode != 0


def test_post_start_failure_stops_socket_and_returns_failure(
    runtime: dict[str, str], docker_socket_path: Path
) -> None:
    socket_path = docker_socket_path
    create_docker_socket(socket_path)
    result = subprocess.run(
        ["bash", str(HELPER), "--post-start"],
        env={**runtime, "TEST_MODE": "truncated", "COLIMA_DOCKER_SOCKET_PATH": str(socket_path)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
    assert ["systemctl", "--no-block", "stop", "docker.socket"] in calls(runtime)
    assert not any("prune" in c or "rm" in c or "recreate" in c for c in calls(runtime))


def test_service_cleanup_closes_socket_and_only_failed_start_queues_activation_stop(
    runtime: dict[str, str], docker_socket_path: Path
) -> None:
    create_docker_socket(docker_socket_path)
    result = subprocess.run(
        ["bash", str(HELPER), "--docker-api-cleanup"],
        env={**runtime, "COLIMA_DOCKER_SOCKET_PATH": str(docker_socket_path)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(docker_socket_path.stat().st_mode) == 0o600

    # Normal stop/restart propagates through the socket unit's PartOf= edge.
    assert ["systemctl", "--no-block", "stop", "docker.socket"] not in calls(runtime)

    docker_socket_path.chmod(0o660)
    result = subprocess.run(
        ["bash", str(HELPER), "--docker-api-cleanup"],
        env={
            **runtime,
            "COLIMA_DOCKER_SOCKET_PATH": str(docker_socket_path),
            "SERVICE_RESULT": "exit-code",
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(docker_socket_path.stat().st_mode) == 0o600
    assert ["systemctl", "--no-block", "stop", "docker.socket"] in calls(runtime)


def test_post_start_opens_socket_only_after_exact_inventory_passes(
    runtime: dict[str, str], docker_socket_path: Path
) -> None:
    socket_path = docker_socket_path
    create_docker_socket(socket_path)
    result = subprocess.run(
        ["bash", str(HELPER), "--post-start"],
        env={**runtime, "COLIMA_DOCKER_SOCKET_PATH": str(socket_path)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660


def test_docker_preflight_closes_a_previously_open_socket_before_containerd_probe(
    runtime: dict[str, str], docker_socket_path: Path,
) -> None:
    socket_path = docker_socket_path
    create_docker_socket(socket_path)
    result = subprocess.run(
        ["bash", str(HELPER), "--docker-preflight"],
        env={**runtime, "TEST_MODE": "ctr-down", "COLIMA_DOCKER_SOCKET_PATH": str(socket_path)},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600


def test_missing_explicit_resource_profile_refuses(runtime: dict[str, str], tmp_path: Path) -> None:
    result = run(
        "colima_runtime_bind_and_ready /repo",
        {**runtime, "COLIMA_RESOURCE_PROFILE_FILE": str(tmp_path / "absent")},
    )
    assert result.returncode != 0
    assert not calls(runtime)


def test_mount_producer_preserves_data_and_resumes_partial_mounts(
    runtime: dict[str, str], tmp_path: Path
) -> None:
    producer = ROOT / "scripts/lib/colima_data_mount_provision.sh"

    def provision(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(producer), "--provision"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    # Refuse to hide retained metadata at a currently unmounted Docker target.
    env = {**runtime, "TEST_MODE": "mount-empty"}
    assert provision(env).returncode != 0
    assert not any(c[0] == "mount" and "--bind" in c for c in calls(env))
    assert (
        json.loads(
            (
                Path(env["COLIMA_DOCKER_DATA_PATH"]) / "containers" / ("1" * 64) / "config.v2.json"
            ).read_text()
        )["ID"]
        == "1" * 64
    )
    # Empty bind targets model boot before their persistent filesystem is bound.
    docker, containerd = tmp_path / "empty-docker", tmp_path / "empty-containerd"
    docker.mkdir()
    containerd.mkdir()
    env.update(
        COLIMA_DOCKER_DATA_PATH=str(docker),
        COLIMA_CONTAINERD_DATA_PATH=str(containerd),
        TEST_MODE="mount-fail-containerd",
    )
    assert provision(env).returncode != 0
    start = len(calls(env))
    env["TEST_MODE"] = "mount-empty"
    assert provision(env).returncode == 0
    assert [c for c in calls(env)[start:] if c[0] == "mount"] == [
        ["mount", "--bind", env["COLIMA_PERSISTENT_DATA_PATH"] + "/containerd", str(containerd)]
    ]
    start = len(calls(env))
    assert provision(env).returncode == 0
    assert not any(c[0] == "mount" for c in calls(env)[start:])


def test_docker_prestart_and_poststart_emit_invocation_bound_containerd_pid(
    runtime: dict[str, str], docker_socket_path: Path,
) -> None:
    create_docker_socket(docker_socket_path)
    env = {**runtime, "COLIMA_DOCKER_SOCKET_PATH": str(docker_socket_path)}
    for selector, phase in (("--docker-preflight", "before"), ("--post-start", "after")):
        result = subprocess.run(
            ["bash", str(HELPER), selector],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert f"containerd-pid-{phase}=31415" in result.stdout


def test_same_count_wrong_identity_refuses(runtime: dict[str, str]) -> None:
    result = run("colima_runtime_assert_inventory", {**runtime, "TEST_MODE": "wrong-id"})
    assert result.returncode != 0


@pytest.mark.parametrize("anonymous,malformed", [(False, False), (True, False), (False, True)])
def test_terminal_residue_requires_proven_volume_preservation(
    runtime: dict[str, str],
    anonymous: bool,
    malformed: bool,
) -> None:
    identity = "3" * 64
    entry = Path(runtime["COLIMA_PERSISTED_CONFIG_ROOT"]) / identity
    entry.mkdir()
    config = {
        "ID": identity,
        "State": {"Dead": True, "Running": False},
        "HasBeenStartedBefore": False,
        "MountPoints": {
            "/data": {"Type": "volume", "Spec": {"Source": "" if anonymous else "named"}}
        },
    }
    (entry / "config.v2.json").write_text("{" if malformed else json.dumps(config))
    (entry / "hostconfig.json").write_text(
        json.dumps(
            {
                "AutoRemove": True,
                "RestartPolicy": {"Name": "no"},
            }
        )
    )
    before = {p: p.read_bytes() for p in entry.iterdir()}
    result = run("colima_runtime_assert_inventory", runtime)
    assert (result.returncode == 0) == (not anonymous and not malformed)
    assert before == {p: p.read_bytes() for p in entry.iterdir()}
