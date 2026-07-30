"""Regression tests for the legacy-owner source inventory (Issue #4423).

`produce_legacy_owners` requires two consecutive snapshots of unchanged host state
to be byte-identical. The per-container fingerprint embeds the `Mounts` array from
`docker inspect`, and Docker does not guarantee that array's ordering. These tests
pin the fingerprint to mount *content* rather than to Docker's arbitrary ordering,
while keeping the guard's ability to detect a genuine change.
"""

import json
from pathlib import Path

import pytest

import scripts.instance_state_writer_inventory as writer_inventory
from scripts.instance_state_writer_inventory import InventoryError

CONTAINER_ID = "a" * 64

MOUNTS = [
    {"Type": "bind", "Source": "/Users", "Destination": "/Users", "RW": True},
    {"Type": "bind", "Source": "/Volumes", "Destination": "/Volumes", "RW": True},
    {"Type": "volume", "Name": "pkm-dev-tmp", "Destination": "/app/tmp", "RW": True},
    {"Type": "volume", "Name": "pkm-dev-tts", "Destination": "/data/tts", "RW": False},
]

ENV = ["PKM_ENVIRONMENT=dev", "PATH=/usr/local/bin"]


def _inspect_payload(mounts):
    return [
        {
            "Id": CONTAINER_ID,
            "Config": {
                "Env": list(ENV),
                "Labels": {
                    "com.docker.compose.project": "pkm-dev",
                    "com.docker.compose.service": "api",
                },
            },
            "Mounts": [dict(mount) for mount in mounts],
        }
    ]


@pytest.fixture
def docker_stub(monkeypatch):
    """Drive `_docker_legacy_owner_sources` from a scripted sequence of mount orders."""

    state = {"orders": [], "calls": 0}

    def fake_run_checked(command, *, label, env=None):
        command = list(command)
        if command[:2] == ["docker", "ps"]:
            return f"{CONTAINER_ID}\n"
        if command[:2] == ["docker", "inspect"]:
            index = min(state["calls"], len(state["orders"]) - 1)
            state["calls"] += 1
            return json.dumps(_inspect_payload(state["orders"][index]))
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(writer_inventory, "_run_checked", fake_run_checked)
    monkeypatch.setattr(writer_inventory, "_docker_copy_file", lambda *_args: None)
    return state


def test_docker_legacy_owner_fingerprint_is_mount_order_invariant(docker_stub):
    """Reordered mounts describe the same host state and must hash identically."""

    reordered = [MOUNTS[2], MOUNTS[3], MOUNTS[0], MOUNTS[1]]
    docker_stub["orders"] = [MOUNTS, reordered]

    _, first = writer_inventory._docker_legacy_owner_sources()
    _, second = writer_inventory._docker_legacy_owner_sources()

    assert first == second


def test_docker_legacy_owner_fingerprint_detects_mount_change(docker_stub):
    """A real mount change must still move the fingerprint."""

    changed = [dict(mount) for mount in MOUNTS]
    changed[0]["Source"] = "/Users/someone-else"
    docker_stub["orders"] = [MOUNTS, changed]

    _, first = writer_inventory._docker_legacy_owner_sources()
    _, second = writer_inventory._docker_legacy_owner_sources()

    assert first != second

    docker_stub["calls"] = 0
    docker_stub["orders"] = [MOUNTS, MOUNTS[:-1]]

    _, full = writer_inventory._docker_legacy_owner_sources()
    _, dropped = writer_inventory._docker_legacy_owner_sources()

    assert full != dropped


@pytest.fixture
def stub_config_sources(monkeypatch):
    """Pin the config half of the snapshot so the docker half is what varies."""

    monkeypatch.setattr(
        writer_inventory,
        "_config_legacy_owner_sources",
        lambda repo_root, *, active_channel: ([], ["config:stub"]),
    )


def test_produce_legacy_owners_tolerates_mount_reordering(
    docker_stub, stub_config_sources, tmp_path
):
    """The production entrypoint must not report a race for reordered mounts."""

    docker_stub["orders"] = [MOUNTS, [MOUNTS[3], MOUNTS[1], MOUNTS[2], MOUNTS[0]]]
    output = tmp_path / "legacy-owners.json"

    writer_inventory.produce_legacy_owners(
        repo_root=Path.cwd(), active_channel="dev", output=output
    )

    # Real-path assertion: the production call site wrote its inventory receipt,
    # rather than the helper merely returning a stable value in isolation.
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == writer_inventory.LEGACY_OWNER_INVENTORY_SCHEMA
    assert payload["inventory_complete"] is True
    assert payload["source_probe_count"] == 2
    assert docker_stub["calls"] == 2


def test_produce_legacy_owners_still_detects_real_race(
    docker_stub, stub_config_sources, tmp_path
):
    """A genuine change between the two probes must still fail closed."""

    raced = [dict(mount) for mount in MOUNTS]
    raced[1]["Source"] = "/Volumes/OtherDisk"
    docker_stub["orders"] = [MOUNTS, raced]
    output = tmp_path / "legacy-owners.json"

    with pytest.raises(InventoryError, match="incomplete or racing"):
        writer_inventory.produce_legacy_owners(
            repo_root=Path.cwd(), active_channel="dev", output=output
        )

    assert not output.exists()
