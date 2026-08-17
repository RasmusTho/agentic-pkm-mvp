from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/colima_runtime_readiness.sh"
SYSTEMD = ROOT / "ops/host-setup/mac-mini/systemd"


def _run_bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env or {})
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=merged,
        check=False,
        capture_output=True,
        text=True,
    )


def test_installed_units_fail_closed_until_exact_persistent_substrate_is_ready(
    tmp_path: Path,
) -> None:
    log = tmp_path / "calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in {
        "findmnt": "printf '/wrong-source\\n'\n",
        "mountpoint": "exit 0\n",
        "df": "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/x 1 0 1 0%% /\\n'\n",
        "ctr": f"printf 'ctr-called\\n' >> '{log}'\nexit 0\n",
        "docker": f"printf 'docker-called\\n' >> '{log}'\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)

    result = _run_bash(
        f"source '{HELPER}'; "
        "COLIMA_PERSISTENT_DATA_PATH=/persistent "
        "COLIMA_DOCKER_DATA_PATH=/var/lib/docker "
        "COLIMA_CONTAINERD_DATA_PATH=/var/lib/containerd "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_MIN_FREE_BLOCKS=1 COLIMA_MIN_FREE_INODES=1 "
        "colima_guest_readiness_gate",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "persistent substrate" in result.stderr.lower()
    assert not log.exists() or log.read_text(encoding="utf-8") == ""

    substrate_unit = SYSTEMD / "yggdrasil-colima-persistent-substrate.service"
    data_mount_unit = SYSTEMD / "colima-data-mount.service"
    containerd_dropin = SYSTEMD / "containerd.service.d/20-yggdrasil-persistent-substrate.conf"
    docker_dropin = SYSTEMD / "docker.service.d/20-yggdrasil-containerd-readiness.conf"
    assert "ExecStart=" in substrate_unit.read_text(encoding="utf-8")
    assert data_mount_unit.exists()
    data_mount_text = data_mount_unit.read_text(encoding="utf-8")
    assert "yggdrasil-colima-data-mount --provision" in data_mount_text
    assert (ROOT / "scripts/lib/colima_data_mount_provision.sh").exists()
    assert "Requires=yggdrasil-colima-persistent-substrate.service" in containerd_dropin.read_text(
        encoding="utf-8"
    )
    assert "--substrate" in substrate_unit.read_text(encoding="utf-8")
    docker_dropin_text = docker_dropin.read_text(encoding="utf-8")
    assert "Requires=containerd.service" in docker_dropin_text
    assert "--docker-preflight" in docker_dropin_text
    assert "ExecStartPre=" in docker_dropin_text


def test_startup_entrypoints_share_one_bounded_colima_readiness_helper() -> None:
    dev_bootstrap = (ROOT / "scripts/dev_bootstrap.sh").read_text(encoding="utf-8")
    full_start = (ROOT / "scripts/start_full_system.sh").read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")

    assert "colima_runtime_bind_and_ready" in dev_bootstrap
    assert "colima_runtime_bind_and_ready" in full_start
    assert "source \"scripts/lib/colima_runtime_readiness.sh\"" in full_start
    assert "source \"${ROOT}/scripts/lib/colima_runtime_readiness.sh\"" in dev_bootstrap
    assert "colima start" not in dev_bootstrap
    assert "colima start >/dev/null" not in full_start
    assert "DOCKER_CONTEXT" in helper
    assert "COLIMA_RUNTIME_PROVIDER" in helper
    assert "COLIMA_EXPECTED_PERSISTENT_IDENTITY" in helper
    assert "COLIMA_EXPECTED_PERSISTED_INVENTORY" in helper
    assert "COLIMA_USERNET_TIMEOUT" in helper
    assert "COLIMA_RESOURCE_PROFILE_FILE" in helper
    assert "timeout" in helper

    installer = (ROOT / "ops/host-setup/mac-mini/install_colima_runtime_readiness.sh").read_text(
        encoding="utf-8"
    )
    assert "COLIMA_RUNTIME_ENV_FILE" in installer
    assert "install_guest_file_atomic" in installer
    assert "COLIMA_EXPECTED_PERSISTENT_IDENTITY" in installer
    assert "colima_data_mount_provision.sh" in installer


def test_persisted_inventory_mismatch_fails_without_mutating_metadata(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "docker.calls"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{calls}'\n"
        "case \"$1 $2\" in\n"
        "  'context inspect') exit 0;;\n"
        "  'ps -aq') printf 'one\\ntwo\\n'; exit 0;;\n"
        "  'prune '*|'rm '*|'volume '*|'system '*|'compose '* ) exit 99;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    persisted = tmp_path / "persisted"
    (persisted / "a").mkdir(parents=True)
    (persisted / "b").mkdir()
    receipt = tmp_path / "receipt.json"

    result = _run_bash(
        f"source '{HELPER}'; "
        "COLIMA_DOCKER_CONTEXT=colima "
        f"COLIMA_PERSISTED_CONFIG_ROOT='{persisted}' "
        "COLIMA_EXPECTED_PERSISTED_INVENTORY=3 "
        f"COLIMA_RUNTIME_RECEIPT_PATH='{receipt}' "
        "colima_runtime_assert_inventory",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "inventory" in result.stderr.lower()
    docker_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "prune" not in docker_calls
    assert "recreate" not in docker_calls
    assert "delete" not in docker_calls
    assert receipt.exists()
    receipt_text = receipt.read_text(encoding="utf-8")
    assert "failure_reason" in receipt_text
    assert str(persisted) not in receipt_text
    assert not calls.exists()


def test_mount_producer_creates_and_verifies_reviewed_mounts(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    mount_calls = tmp_path / "mount.calls"
    mount_state = tmp_path / "mount-state"
    mount_state.mkdir()
    for name, body in {
        "mountpoint": (
            "last=''\n"
            "for arg in \"$@\"; do last=\"$arg\"; done\n"
            "key=$(printf '%s' \"$last\" | tr '/' '_')\n"
            f"test -f \"{mount_state}/$key\"\n"
        ),
        "mount": (
            f"printf '%s\\n' \"$*\" >> '{mount_calls}'\n"
            "last=''\n"
            "for arg in \"$@\"; do last=\"$arg\"; done\n"
            "key=$(printf '%s' \"$last\" | tr '/' '_')\n"
            f"touch \"{mount_state}/$key\"\n"
        ),
        "findmnt": (
            "case \"$*\" in *FSROOT*docker*) printf '/docker\\n';; "
            "*FSROOT*containerd*) printf '/containerd\\n';; "
            "*FSROOT*) printf '/\\n';; "
            "*SOURCE*docker*) printf '/dev/persistent[/docker]\\n';; "
            "*SOURCE*containerd*) printf '/dev/persistent[/containerd]\\n';; "
            "*SOURCE*) printf '/dev/persistent\\n';; "
            "*UUID*) printf 'reviewed-uuid\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; esac\n"
        ),
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)

    persistent = tmp_path / "persistent"
    docker_data = tmp_path / "docker"
    containerd_data = tmp_path / "containerd"
    result = _run_bash(
        f"COLIMA_PERSISTENT_DATA_PATH='{persistent}' "
        f"COLIMA_DOCKER_DATA_PATH='{docker_data}' "
        f"COLIMA_CONTAINERD_DATA_PATH='{containerd_data}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=reviewed-uuid "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        f"bash '{ROOT / 'scripts/lib/colima_data_mount_provision.sh'}' --provision",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert mount_calls.read_text(encoding="utf-8").splitlines() == [
        f"-t ext4 UUID=reviewed-uuid {persistent}",
        f"--bind {persistent}/docker {docker_data}",
        f"--bind {persistent}/containerd {containerd_data}",
    ]


def test_mount_producer_refuses_to_hide_existing_metadata_with_empty_source(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    mount_calls = tmp_path / "mount.calls"
    mount_state = tmp_path / "mount-state"
    mount_state.mkdir()
    for name, body in {
        "mountpoint": (
            "last=''\n"
            "for arg in \"$@\"; do last=\"$arg\"; done\n"
            "key=$(printf '%s' \"$last\" | tr '/' '_')\n"
            f"test -f \"{mount_state}/$key\"\n"
        ),
        "mount": (
            f"printf '%s\\n' \"$*\" >> '{mount_calls}'\n"
            "last=''\n"
            "for arg in \"$@\"; do last=\"$arg\"; done\n"
            "key=$(printf '%s' \"$last\" | tr '/' '_')\n"
            f"touch \"{mount_state}/$key\"\n"
        ),
        "findmnt": (
            "case \"$*\" in *FSROOT*) printf '/\\n';; "
            "*SOURCE*) printf '/dev/persistent\\n';; "
            "*UUID*) printf 'reviewed-uuid\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; esac\n"
        ),
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)

    persistent = tmp_path / "persistent"
    docker_data = tmp_path / "docker"
    docker_data.mkdir()
    (docker_data / "existing-container-metadata").write_text("preserve", encoding="utf-8")
    containerd_data = tmp_path / "containerd"
    result = _run_bash(
        f"COLIMA_PERSISTENT_DATA_PATH='{persistent}' "
        f"COLIMA_DOCKER_DATA_PATH='{docker_data}' "
        f"COLIMA_CONTAINERD_DATA_PATH='{containerd_data}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=reviewed-uuid "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        f"bash '{ROOT / 'scripts/lib/colima_data_mount_provision.sh'}' --provision",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "existing data" in result.stderr
    assert mount_calls.read_text(encoding="utf-8").splitlines() == [
        f"-t ext4 UUID=reviewed-uuid {persistent}",
    ]
    assert (docker_data / "existing-container-metadata").read_text(encoding="utf-8") == "preserve"
    assert not (persistent / "docker").exists()


def test_prestart_inventory_mismatch_refuses_before_docker_api(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_calls = tmp_path / "docker.calls"
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{docker_calls}'\nexit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    persisted = tmp_path / "persisted"
    (persisted / "a").mkdir(parents=True)
    (persisted / "b").mkdir()
    result = _run_bash(
        f"source '{HELPER}'; "
        f"COLIMA_PERSISTED_CONFIG_ROOT='{persisted}' "
        "COLIMA_EXPECTED_PERSISTED_INVENTORY=3 "
        "colima_guest_assert_persisted_inventory",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "inventory" in result.stderr.lower()
    assert not docker_calls.exists()


def test_mount_alias_without_reviewed_canonical_identity_is_refused(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in {
        "findmnt": (
            "case \"$*\" in *SOURCE*) printf '/dev/persistent\\n';; "
            "*UUID*) printf 'unreviewed-alias\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; esac\n"
        ),
        "mountpoint": "exit 0\n",
        "df": "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/x 1 0 999999 0%% /\\n'\n",
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)
    mount = tmp_path / "persistent"
    mount.mkdir()
    result = _run_bash(
        f"source '{HELPER}'; "
        f"COLIMA_PERSISTENT_DATA_PATH='{mount}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=reviewed-identity "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        "colima_guest_check_persistent_substrate",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0


def test_bind_mount_source_suffixes_share_the_reviewed_device_identity(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, body in {
        "findmnt": (
            "case \"$*\" in *UUID*) printf 'reviewed-uuid\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; "
            "*docker*) printf '/dev/persistent[/docker]\\n';; "
            "*containerd*) printf '/dev/persistent[/containerd]\\n';; "
            "*) printf '/dev/persistent\\n';; esac\n"
        ),
        "mountpoint": "exit 0\n",
        "df": "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/x 1 0 999999 0%% /\\n'\n",
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)
    persistent = tmp_path / "persistent"
    docker_data = tmp_path / "docker"
    containerd_data = tmp_path / "containerd"
    for path in (persistent, docker_data, containerd_data):
        path.mkdir()
    result = _run_bash(
        f"source '{HELPER}'; "
        f"COLIMA_PERSISTENT_DATA_PATH='{persistent}' "
        f"COLIMA_DOCKER_DATA_PATH='{docker_data}' "
        f"COLIMA_CONTAINERD_DATA_PATH='{containerd_data}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=reviewed-uuid "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        "colima_guest_check_persistent_substrate",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0


def test_non_colima_provider_passthrough_does_not_change_docker_binding(tmp_path: Path) -> None:
    fake_colima = tmp_path / "colima"
    fake_colima.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_colima.chmod(0o755)
    result = _run_bash(
        f"source '{HELPER}'; "
        "export DOCKER_CONTEXT=desktop COLIMA_BIN='" + str(fake_colima) + "'; "
        "colima_runtime_bind_and_ready /repo; printf '%s' \"$DOCKER_CONTEXT\"",
    )
    assert result.returncode == 0
    assert result.stdout == "desktop"


def test_guest_gate_waits_for_containerd_rpc_and_metadata_after_mounts(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "ctr.calls"
    for name, body in {
        "findmnt": (
            "case \"$*\" in *SOURCE*) printf '/dev/persistent\\n';; "
            "*UUID*) printf 'test-uuid\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; esac\n"
        ),
        "mountpoint": "exit 0\n",
        "df": "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/x 1 0 999999 0%% /\\n'\n",
        "ctr": f"printf '%s\\n' \"$*\" >> '{calls}'\nexit 0\n",
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)
    persistent = tmp_path / "persistent"
    docker_data = tmp_path / "docker"
    containerd_data = tmp_path / "containerd"
    persistent.mkdir()
    docker_data.mkdir()
    containerd_data.mkdir()
    persisted = tmp_path / "persisted"
    persisted.mkdir()

    result = _run_bash(
        f"source '{HELPER}'; "
        f"COLIMA_PERSISTENT_DATA_PATH='{persistent}' "
        f"COLIMA_DOCKER_DATA_PATH='{docker_data}' "
        f"COLIMA_CONTAINERD_DATA_PATH='{containerd_data}' "
        f"COLIMA_PERSISTED_CONFIG_ROOT='{persisted}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=test-uuid "
        "COLIMA_EXPECTED_PERSISTED_INVENTORY=0 "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        "COLIMA_MIN_FREE_BLOCKS=1 COLIMA_MIN_FREE_INODES=1 "
        "COLIMA_READINESS_SLEEP_SECONDS=0 "
        "colima_guest_readiness_gate",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "version",
        "--namespace moby containers list",
        "--namespace moby snapshots list",
    ]


def test_docker_preflight_selector_orders_substrate_ctr_and_inventory_before_docker(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"
    for name, body in {
        "findmnt": (
            f"printf 'findmnt:%s\\n' \"$*\" >> '{calls}'\n"
            "case \"$*\" in *SOURCE*) printf '/dev/persistent\\n';; "
            "*UUID*) printf 'test-uuid\\n';; "
            "*FSTYPE*) printf 'ext4\\n';; esac\n"
        ),
        "mountpoint": f"printf 'mountpoint:%s\\n' \"$*\" >> '{calls}'\nexit 0\n",
        "df": (
            f"printf 'df:%s\\n' \"$*\" >> '{calls}'\n"
            "printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/x 1 0 999999 0%% /\\n'\n"
        ),
        "ctr": f"printf 'ctr:%s\\n' \"$*\" >> '{calls}'\nexit 0\n",
        "docker": f"printf 'docker:%s\\n' \"$*\" >> '{calls}'\nexit 99\n",
    }.items():
        path = fake_bin / name
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)
    persistent = tmp_path / "persistent"
    docker_data = tmp_path / "docker"
    containerd_data = tmp_path / "containerd"
    persisted = tmp_path / "persisted"
    for path in (persistent, docker_data, containerd_data, persisted):
        path.mkdir()

    result = _run_bash(
        f"COLIMA_PERSISTENT_DATA_PATH='{persistent}' "
        f"COLIMA_DOCKER_DATA_PATH='{docker_data}' "
        f"COLIMA_CONTAINERD_DATA_PATH='{containerd_data}' "
        f"COLIMA_PERSISTED_CONFIG_ROOT='{persisted}' "
        "COLIMA_EXPECTED_PERSISTENT_SOURCE=/dev/persistent "
        "COLIMA_EXPECTED_PERSISTENT_IDENTITY=UUID=test-uuid "
        "COLIMA_EXPECTED_PERSISTED_INVENTORY=0 "
        "COLIMA_EXPECTED_PERSISTENT_FSTYPE=ext4 "
        "COLIMA_MIN_FREE_BLOCKS=1 COLIMA_MIN_FREE_INODES=1 "
        f"bash '{HELPER}' --docker-preflight",
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert not any(line.startswith("docker:") for line in lines)
    last_mount_check = max(index for index, line in enumerate(lines) if line.startswith("df:"))
    first_ctr = min(index for index, line in enumerate(lines) if line.startswith("ctr:"))
    assert last_mount_check < first_ctr
    assert [line for line in lines if line.startswith("ctr:")] == [
        "ctr:version",
        "ctr:--namespace moby containers list",
        "ctr:--namespace moby snapshots list",
    ]
