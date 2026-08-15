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
    containerd_dropin = SYSTEMD / "containerd.service.d/20-yggdrasil-persistent-substrate.conf"
    docker_dropin = SYSTEMD / "docker.service.d/20-yggdrasil-containerd-readiness.conf"
    assert "ExecStart=" in substrate_unit.read_text(encoding="utf-8")
    assert "Requires=yggdrasil-colima-persistent-substrate.service" in containerd_dropin.read_text(
        encoding="utf-8"
    )
    docker_dropin_text = docker_dropin.read_text(encoding="utf-8")
    assert "Requires=containerd.service" in docker_dropin_text
    assert "ExecStartPre=" in docker_dropin_text


def test_startup_entrypoints_share_one_bounded_colima_readiness_helper() -> None:
    dev_bootstrap = (ROOT / "scripts/dev_bootstrap.sh").read_text(encoding="utf-8")
    full_start = (ROOT / "scripts/start_full_system.sh").read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")

    assert "colima_runtime_bind_and_ready" in dev_bootstrap
    assert "colima_runtime_bind_and_ready" in full_start
    assert "source \"scripts/lib/colima_runtime_readiness.sh\"" in full_start
    assert "source \"${ROOT}/scripts/lib/colima_runtime_readiness.sh\"" in dev_bootstrap
    assert "DOCKER_CONTEXT" in helper
    assert "COLIMA_USERNET_TIMEOUT" in helper
    assert "COLIMA_RESOURCE_PROFILE_FILE" in helper
    assert "timeout" in helper


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
    assert "prune" not in calls.read_text(encoding="utf-8")
    assert "recreate" not in calls.read_text(encoding="utf-8")
    assert "delete" not in calls.read_text(encoding="utf-8")
    assert receipt.exists()
    assert "failure_reason" in receipt.read_text(encoding="utf-8")
