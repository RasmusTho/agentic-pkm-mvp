"""Regression tests for the instance-state writer inventory.

Issue #4423: `produce_legacy_owners` requires two consecutive snapshots of
unchanged host state to be byte-identical. The per-container fingerprint embeds
the `Mounts` array from `docker inspect`, and Docker does not guarantee that
array's ordering. Those tests pin the fingerprint to mount *content* rather than
to Docker's arbitrary ordering, while keeping the guard's ability to detect a
genuine change.

Issue #4434: `ps`'s `command=` column is a display string — argv joined with
single spaces — not shell syntax. Those tests pin the macOS row parser to that
reading, so an ordinary quoted command line cannot abort the whole native
inventory and thereby fail-close a deploy.
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


# --- Issue #4434: macOS ps row parsing --------------------------------------

LSTART = "Thu Jul 30 16:59:37 2026"


def _ps_row(command, pid=98262, ppid=98128, pgid=98262):
    return f"{pid} {ppid} {pgid} {LSTART} {command}"


def test_parse_macos_ps_row_accepts_unbalanced_quotes():
    """An ordinary command line with an odd apostrophe count must still parse.

    This is the exact shape that aborted a real deploy: one agent process whose
    natural-language prompt contained three apostrophes.
    """

    command = "claude --flag You are the hub coordinator. Don't stop; it's fine"
    record = writer_inventory._parse_macos_ps_row(_ps_row(command))

    assert record.pid == 98262
    assert record.argv[0] == "claude"
    assert record.argv == tuple(command.split())


def test_parse_macos_ps_row_preserves_literal_quotes():
    """Quote characters are argument content here, not syntax to be consumed."""

    command = "python -c print('hi') \"double\""
    record = writer_inventory._parse_macos_ps_row(_ps_row(command))

    assert "print('hi')" in record.argv
    assert '"double"' in record.argv


def test_enumerate_macos_survives_quoted_command_row(monkeypatch):
    """One quoted row must not abort the whole native inventory."""

    rows = [
        _ps_row("/sbin/launchd", pid=1, ppid=0, pgid=1),
        _ps_row("claude --flag it's a prompt", pid=98262),
        _ps_row("python -m app.cli watcher run", pid=4242, ppid=1, pgid=4242),
    ]

    def fake_run_checked(command, *, label, env=None):
        assert list(command)[:1] == ["ps"]
        return "\n".join(rows) + "\n"

    monkeypatch.setattr(writer_inventory, "_run_checked", fake_run_checked)

    records = writer_inventory._enumerate_macos()

    assert [record.pid for record in records] == [1, 98262, 4242]


def test_native_role_classifies_known_writers():
    """Whitespace splitting must not lose any writer shape the guard detects."""

    cases = {
        ("python", "-m", "app.cli", "watcher", "run"): "watcher",
        ("python3", "-m", "app.cli", "heimdal", "capture-watch"): "heimdal-capture-watch",
        ("python", "-m", "app.workers.outbox_worker"): "outbox-worker",
        ("python", "-m", "uvicorn", "app.api.app:app"): "uvicorn",
        ("python", "-m", "celery", "worker"): "celery",
        ("/usr/bin/uvicorn", "app.api.app:app"): "uvicorn",
        ("/bin/bash", "scripts/deploy_channel.sh", "deploy"): "deploy_channel",
    }
    for argv, expected in cases.items():
        assert writer_inventory._native_role(argv) == expected, argv

    assert writer_inventory._native_role(("claude", "--flag", "it's")) is None


@pytest.mark.parametrize(
    "row",
    [
        "not a ps row at all",
        f"98262 98128 98262 {LSTART}",
        f"0 1 1 {LSTART} /sbin/launchd",
        "98262 98128 98262 Thu Jul 30 16:59:37 /sbin/launchd",
    ],
)
def test_parse_macos_ps_row_still_rejects_malformed_rows(row):
    """Structurally malformed rows must keep failing closed."""

    with pytest.raises(InventoryError):
        writer_inventory._parse_macos_ps_row(row)
