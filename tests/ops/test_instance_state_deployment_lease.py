from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.instance.runtime import (
    InstanceStatePreflightError,
    RegistryError,
    _any_deployment_lease_exists,
    _begin_instance_state_deployment,
    _deployment_fence_path,
    _deployment_lease_path,
    _legacy_deployment_lease_path,
    _preflight_runtime,
    _release_instance_state_deployment_lease,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WRITER_INVENTORY_HELPER = REPO_ROOT / "scripts/instance_state_writer_inventory.py"


def _controller_token(pid: int) -> str:
    return subprocess.check_output(
        [
            sys.executable,
            str(WRITER_INVENTORY_HELPER),
            "controller-token",
            "--pid",
            str(pid),
        ],
        text=True,
    ).strip()


def _begin(
    tmp_path: Path,
    *,
    channel: str,
    controller_pid: int,
    controller_start_token: str,
) -> tuple[Path, Path, dict[str, object]]:
    state = tmp_path / "state"
    ownership = tmp_path / "ownership"
    state.mkdir(exist_ok=True)
    ownership.mkdir(exist_ok=True)
    fence = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=controller_pid,
        controller_start_token=controller_start_token,
    )
    return state, ownership, fence


def test_failed_deployment_releases_host_global_lease(tmp_path: Path) -> None:
    """AC: a deployment that fails between begin and finish leaves no residue."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    assert _deployment_lease_path(ownership).exists()
    assert _deployment_fence_path(ownership, channel).exists()
    assert _legacy_deployment_lease_path(ownership).exists()

    receipt = _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert receipt["released"] is True
    assert not _deployment_lease_path(ownership).exists()
    assert not _deployment_fence_path(ownership, channel).exists()
    assert not _legacy_deployment_lease_path(ownership).exists()
    assert not _any_deployment_lease_exists(ownership)


def test_release_after_successful_finish_is_a_noop(tmp_path: Path) -> None:
    """A release attempt must not run after deployment-finish already cleared the lease."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    _state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )
    # Simulate deployment-finish already having cleared the lease and fence.
    _deployment_lease_path(ownership).unlink()
    _deployment_fence_path(ownership, channel).unlink()
    _legacy_deployment_lease_path(ownership).unlink()

    receipt = _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert receipt["released"] is False
    assert receipt["reason"] == "no-active-lease"


def test_dead_controller_lease_is_reclaimable(tmp_path: Path) -> None:
    """AC: a lease whose controller process no longer exists is reclaimable."""

    channel = "prod"
    dead_pid = 999_999_998
    dead_token = f"linux:{'3' * 64}"
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=dead_pid,
        controller_start_token=dead_token,
    )

    live_pid = os.getpid()
    live_token = _controller_token(live_pid)
    recovered = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=live_pid,
        controller_start_token=live_token,
    )

    assert recovered["controller"] == {"pid": live_pid, "start_token": live_token}
    lease = json.loads(_deployment_lease_path(ownership).read_text(encoding="utf-8"))
    assert lease["controller"] == {"pid": live_pid, "start_token": live_token}


def test_live_controller_lease_still_blocks(tmp_path: Path) -> None:
    """AC: a live controller with a matching start token still blocks, via the
    production begin path rather than the liveness helper alone."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    with pytest.raises(InstanceStatePreflightError, match="controller is active"):
        _begin_instance_state_deployment(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            legacy_path=tmp_path / "legacy.md",
            controller_pid=999_999_998,
            controller_start_token=f"linux:{'4' * 64}",
        )


def test_recycled_pid_is_not_treated_as_live(tmp_path: Path) -> None:
    """AC: a recycled pid whose start token differs from the recorded lease is dead."""

    channel = "prod"
    recycled_pid = os.getpid()
    stale_token = f"linux:{'5' * 64}"
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=recycled_pid,
        controller_start_token=stale_token,
    )

    live_token = _controller_token(recycled_pid)
    assert live_token != stale_token
    recovered = _begin_instance_state_deployment(
        channel=channel,
        instance_state_root=state,
        host_global_root=ownership,
        legacy_path=tmp_path / "legacy.md",
        controller_pid=recycled_pid,
        controller_start_token=live_token,
    )

    assert recovered["controller"] == {"pid": recycled_pid, "start_token": live_token}


def test_runtime_consumer_unblocked_after_abandoned_deployment(tmp_path: Path) -> None:
    """AC: a runtime consumer started after an abandoned deployment is not
    blocked by residue from that deployment."""

    channel = "prod"
    controller_pid = os.getpid()
    controller_token = _controller_token(controller_pid)
    state, ownership, _fence = _begin(
        tmp_path,
        channel=channel,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    with pytest.raises(RegistryError, match="blocks every runtime consumer"):
        _preflight_runtime(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            consumer="api",
        )

    _release_instance_state_deployment_lease(
        channel=channel,
        host_global_root=ownership,
        controller_pid=controller_pid,
        controller_start_token=controller_token,
    )

    assert not _any_deployment_lease_exists(ownership)
    assert not _deployment_fence_path(ownership, channel).exists()

    # Residue is gone: the preflight now fails later in the chain (the
    # registry producer was never initialized in this test), never on the
    # lease/fence guards the abandoned deployment used to trip.
    with pytest.raises(
        InstanceStatePreflightError,
        match="instance-state registry producer has not initialized",
    ):
        _preflight_runtime(
            channel=channel,
            instance_state_root=state,
            host_global_root=ownership,
            consumer="api",
        )
