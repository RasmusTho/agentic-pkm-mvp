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

Issue #4518: `InventoryError` refusals from the legacy-owner path named neither
the offending root nor the domain that claimed it, which made a real refusal
undiagnosable without monkeypatching the module. These tests pin every such
refusal to carry a domain, a source, and (where a root is involved) a redacted
identifier for it -- while still never emitting the raw host path.
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


# --- Issue #4538: a running deployment must not observe its own subshells ---

CONTROLLER_PID = 900
CONTROLLER_PGID = 900
CONTROLLER_TOKEN = "linux:" + "a" * 64


def _controller_record(argv=("deploy_channel.sh",)):
    return writer_inventory.ProcessRecord(
        pid=CONTROLLER_PID,
        ppid=1,
        pgid=CONTROLLER_PGID,
        start_token=CONTROLLER_TOKEN,
        argv=argv,
    )


def test_controller_subshell_is_not_a_native_writer(monkeypatch):
    """A forked child of the controller that shares the controller's argv (the
    shape of `deploy_channel_compose()`'s `( ... )` subshell) and process group
    must not be reported as a native writer, even though it is not the
    controller pid itself.
    """

    fork = writer_inventory.ProcessRecord(
        pid=CONTROLLER_PID + 1,
        ppid=CONTROLLER_PID,
        pgid=CONTROLLER_PGID,
        start_token="linux:" + "b" * 64,
        argv=("/bin/bash", "scripts/deploy_channel.sh", "deploy"),
    )
    monkeypatch.setattr(
        writer_inventory, "_native_processes", lambda *, linux_boot_id=None: [fork]
    )

    writers = writer_inventory._native_writers(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        controller_pgid=CONTROLLER_PGID,
        linux_boot_id=None,
    )

    assert writers == []


def test_foreign_deployment_is_still_detected(monkeypatch):
    """A `deploy_channel` process outside the controller's process tree (its
    own, distinct process group) must still be reported as a live writer.
    """

    foreign = writer_inventory.ProcessRecord(
        pid=7777,
        ppid=1,
        pgid=7777,
        start_token="linux:" + "c" * 64,
        argv=("/bin/bash", "scripts/deploy_channel.sh", "deploy"),
    )
    monkeypatch.setattr(
        writer_inventory, "_native_processes", lambda *, linux_boot_id=None: [foreign]
    )

    writers = writer_inventory._native_writers(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        controller_pgid=CONTROLLER_PGID,
        linux_boot_id=None,
    )

    assert writers == [
        {
            "domain": "native",
            "role": "deploy_channel",
            "pid": 7777,
            "start_token": "linux:" + "c" * 64,
        }
    ]


def test_non_launcher_writer_sharing_controller_process_group_is_still_detected(
    monkeypatch,
):
    """The process-group exclusion is scoped to launcher roles only. A
    non-launcher native writer (watcher, worker, uvicorn, celery, heimdal
    capture-watch) that happens to share the controller's process group must
    still be reported -- the exclusion must not widen to any process merely
    because it matches a writer role.
    """

    same_group_uvicorn = writer_inventory.ProcessRecord(
        pid=CONTROLLER_PID + 2,
        ppid=CONTROLLER_PID,
        pgid=CONTROLLER_PGID,
        start_token="linux:" + "e" * 64,
        argv=("uvicorn", "app.api.app:app"),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_native_processes",
        lambda *, linux_boot_id=None: [same_group_uvicorn],
    )

    writers = writer_inventory._native_writers(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        controller_pgid=CONTROLLER_PGID,
        linux_boot_id=None,
    )

    assert writers == [
        {
            "domain": "native",
            "role": "uvicorn",
            "pid": CONTROLLER_PID + 2,
            "start_token": "linux:" + "e" * 64,
        }
    ]


@pytest.fixture
def _proof_stubs(monkeypatch):
    """Stub the platform-specific probes `prove_quiescent` -> `_snapshot` calls."""

    monkeypatch.setattr(writer_inventory, "_read_linux_boot_id", lambda: "boot-fixture")
    monkeypatch.setattr(
        writer_inventory,
        "_record_for_pid",
        lambda pid, *, linux_boot_id=None: _controller_record(),
    )
    monkeypatch.setattr(writer_inventory, "_docker_writers", lambda: [])


def test_prove_quiescent_ignores_own_process_tree(monkeypatch, tmp_path, _proof_stubs):
    """`prove_quiescent` must produce a proof when the only matching native
    processes belong to the controller's own tree.
    """

    fork = writer_inventory.ProcessRecord(
        pid=CONTROLLER_PID + 1,
        ppid=CONTROLLER_PID,
        pgid=CONTROLLER_PGID,
        start_token="linux:" + "b" * 64,
        argv=("/bin/bash", "scripts/deploy_channel.sh", "deploy"),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_native_processes",
        lambda *, linux_boot_id=None: [_controller_record(), fork],
    )
    output = tmp_path / "inventory.json"

    writer_inventory.prove_quiescent(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        output=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["inventory_complete"] is True
    assert payload["domains"] == {"dev": [], "native": [], "prod": [], "test": []}


def test_prove_quiescent_still_detects_native_writers(monkeypatch, tmp_path, _proof_stubs):
    """`prove_quiescent` must still fail closed when a non-launcher native
    writer is running in a foreign process group.
    """

    foreign_writer = writer_inventory.ProcessRecord(
        pid=555,
        ppid=1,
        pgid=555,
        start_token="linux:" + "d" * 64,
        argv=("uvicorn", "app.api.app:app"),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_native_processes",
        lambda *, linux_boot_id=None: [_controller_record(), foreign_writer],
    )
    output = tmp_path / "inventory.json"

    with pytest.raises(InventoryError, match="live or racing"):
        writer_inventory.prove_quiescent(
            controller_pid=CONTROLLER_PID,
            controller_start_token=CONTROLLER_TOKEN,
            output=output,
        )

    assert not output.exists()


def test_prove_quiescent_is_deterministic_across_probes(monkeypatch, tmp_path, _proof_stubs):
    """Repeated `prove_quiescent` invocations on identical host state must
    return the same verdict.
    """

    fork = writer_inventory.ProcessRecord(
        pid=CONTROLLER_PID + 1,
        ppid=CONTROLLER_PID,
        pgid=CONTROLLER_PGID,
        start_token="linux:" + "b" * 64,
        argv=("/bin/bash", "scripts/deploy_channel.sh", "deploy"),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_native_processes",
        lambda *, linux_boot_id=None: [_controller_record(), fork],
    )
    first_output = tmp_path / "inventory-1.json"
    second_output = tmp_path / "inventory-2.json"

    writer_inventory.prove_quiescent(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        output=first_output,
    )
    writer_inventory.prove_quiescent(
        controller_pid=CONTROLLER_PID,
        controller_start_token=CONTROLLER_TOKEN,
        output=second_output,
    )

    first_payload = json.loads(first_output.read_text(encoding="utf-8"))
    second_payload = json.loads(second_output.read_text(encoding="utf-8"))
    assert first_payload["snapshot_digests"] == second_payload["snapshot_digests"]
    assert first_payload["domains"] == second_payload["domains"]


# --- Issue #4518: refusals name domain, source, and a redacted root identity -

MALFORMED_APP_LOCAL_FRONTMATTER = b"---\nnot a mapping line\n---\n"


def test_inventory_errors_name_domain_and_source():
    """Every `InventoryError` this module raises must name which domain and
    which of the four owner sources produced the offending record, so a real
    refusal is diagnosable from the message alone.
    """

    with pytest.raises(InventoryError) as excinfo:
        writer_inventory._parse_app_local_roots(
            MALFORMED_APP_LOCAL_FRONTMATTER, domain="dev", source="config_app_local"
        )

    message = str(excinfo.value)
    assert "domain=dev" in message
    assert "source=config_app_local" in message


def test_missing_and_non_directory_roots_are_distinguishable(tmp_path):
    """A vanished root and a root that exists but is not a directory must
    raise distinguishable reasons, not the same bare message.
    """

    vanished = tmp_path / "does-not-exist"
    not_a_directory = tmp_path / "a-file"
    not_a_directory.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InventoryError) as vanished_excinfo:
        writer_inventory._owner_identity_material(vanished, domain="dev", source="config_env")

    with pytest.raises(InventoryError) as file_excinfo:
        writer_inventory._owner_identity_material(
            not_a_directory, domain="dev", source="config_env"
        )

    vanished_message = str(vanished_excinfo.value)
    file_message = str(file_excinfo.value)
    assert vanished_message != file_message
    assert "reason=vanished" in vanished_message
    assert "reason=not-a-directory" in file_message
    for message in (vanished_message, file_message):
        assert "domain=dev" in message
        assert "source=config_env" in message


def test_collision_error_names_both_domains(tmp_path):
    """A cross-domain collision (two channels claiming the same host root, the
    ADR-0055-adjacent shape this module refuses) must name both domains and a
    redacted identifier for the shared root.
    """

    shared_root = tmp_path / "shared-vault"
    shared_root.mkdir()
    records = [
        writer_inventory.LegacyOwnerRecord("dev", str(shared_root), source="config_env"),
        writer_inventory.LegacyOwnerRecord("prod", str(shared_root), source="config_env"),
    ]

    with pytest.raises(InventoryError, match="collide across release channels") as excinfo:
        writer_inventory._normalize_legacy_owners(records)

    message = str(excinfo.value)
    assert "domain_a=dev" in message
    assert "domain_b=prod" in message
    assert "id=inode:" in message
    assert str(shared_root) not in message


def test_inventory_errors_never_emit_raw_paths(tmp_path):
    """No emitted error, log line, or receipt may contain a raw host path,
    vault name, or operator name. This asserts against the strings the
    deploy path actually raises, not a redaction helper's return value.
    """

    vanished = tmp_path / "operator-name" / "does-not-exist"

    with pytest.raises(InventoryError) as excinfo:
        writer_inventory._owner_identity_material(vanished, domain="dev", source="config_env")

    message = str(excinfo.value)
    assert str(vanished) not in message
    assert str(tmp_path) not in message
    assert "operator-name" not in message

    with pytest.raises(InventoryError) as parse_excinfo:
        writer_inventory._parse_app_local_roots(
            MALFORMED_APP_LOCAL_FRONTMATTER, domain="dev", source="native_app_local"
        )

    assert "not a mapping line" not in str(parse_excinfo.value)


# --- Issue #4517: owner-root arrangements across domains --------------------

REPO_ROOT = Path(writer_inventory.__file__).resolve().parents[1]


@pytest.fixture
def owner_sources(monkeypatch):
    """Drive the production owner inventory from an explicit owner set.

    Only the two *source enumerators* are stubbed. Everything the deploy
    wrapper actually calls -- the `produce-legacy-owners` entrypoint, the
    two-snapshot stability check, normalization, the cross-domain predicate,
    and the private receipt write -- runs for real.
    """

    state = {"owners": []}

    monkeypatch.setattr(
        writer_inventory, "_docker_legacy_owner_sources", lambda: ([], ["docker:stub"])
    )
    monkeypatch.setattr(
        writer_inventory,
        "_config_legacy_owner_sources",
        lambda repo_root, *, active_channel: (
            [
                writer_inventory.LegacyOwnerRecord(domain, str(root), source="config_env")
                for domain, root in state["owners"]
            ],
            ["config:stub"],
        ),
    )
    return state


def _vault(tmp_path, *parts):
    root = tmp_path.joinpath(*parts)
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_native_and_channel_may_share_a_vault_root(owner_sources, tmp_path):
    """ADR-0055 declares the Mac runtime and a channel runtime as peer writers.

    A vault root shared between `native` and one channel -- equal, or nested in
    either direction -- is the designed topology, so the deploy's owner
    inventory must produce its receipt instead of refusing.
    """

    shared = _vault(tmp_path, "vault")
    nested = _vault(tmp_path, "vault", "project")

    arrangements = {
        "equal roots": [("native", shared), ("prod", shared)],
        "channel nested under native": [("native", shared), ("dev", nested)],
        "native nested under channel": [("test", shared), ("native", nested)],
    }

    for label, owners in arrangements.items():
        owner_sources["owners"] = owners
        output = tmp_path / f"owners-{len(label)}-{label[:4]}.json"

        writer_inventory.produce_legacy_owners(
            repo_root=REPO_ROOT, active_channel="dev", output=output
        )

        # Real-path assertion: the production entrypoint wrote its receipt, and
        # both owners survived normalization rather than one being dropped.
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["schema"] == writer_inventory.LEGACY_OWNER_INVENTORY_SCHEMA, label
        assert payload["inventory_complete"] is True, label
        assert {owner["channel_id"] for owner in payload["owners"]} == {
            domain for domain, _ in owners
        }, label


def test_forbidden_cross_domain_arrangements_are_named(owner_sources, tmp_path):
    """The surviving refusal is two *release channels* on one root, and it is documented."""

    docstring = writer_inventory.__doc__ or ""
    assert "Permitted" in docstring
    assert "Forbidden" in docstring
    assert "release channels" in docstring
    assert writer_inventory.CHANNEL_DOMAINS == frozenset({"dev", "prod", "test"})
    assert "native" not in writer_inventory.CHANNEL_DOMAINS

    shared = _vault(tmp_path, "vault")
    nested = _vault(tmp_path, "vault", "project")

    forbidden = {
        "two channels on one root": [("dev", shared), ("prod", shared)],
        "one channel nested under another": [("prod", shared), ("test", nested)],
        "ancestor direction reversed": [("test", nested), ("dev", shared)],
    }

    for label, owners in forbidden.items():
        owner_sources["owners"] = owners
        output = tmp_path / "forbidden-owners.json"

        with pytest.raises(InventoryError, match="collide across release channels"):
            writer_inventory.produce_legacy_owners(
                repo_root=REPO_ROOT, active_channel="dev", output=output
            )

        assert not output.exists(), label


def test_active_writer_during_stopped_window_still_refuses(monkeypatch, tmp_path):
    """Narrowing the ownership predicate must not touch the quiescence proof."""

    controller_pid = 4242
    controller_token = "darwin:" + "b" * 64

    monkeypatch.setattr(
        writer_inventory,
        "_record_for_pid",
        lambda pid, *, linux_boot_id=None: writer_inventory.ProcessRecord(
            pid=controller_pid,
            ppid=1,
            pgid=controller_pid,
            start_token=controller_token,
            argv=("/bin/bash", "scripts/deploy_channel.sh", "deploy"),
        ),
    )
    monkeypatch.setattr(
        writer_inventory,
        "_native_writers",
        lambda **_kwargs: [],
    )

    live_writer = {
        "domain": "dev",
        "role": "watcher",
        "pid": 99001,
        "start_token": "docker:" + "c" * 64,
    }
    monkeypatch.setattr(writer_inventory, "_docker_writers", lambda: [dict(live_writer)])

    output = tmp_path / "quiescence.json"
    with pytest.raises(InventoryError, match="live or racing"):
        writer_inventory.prove_quiescent(
            controller_pid=controller_pid,
            controller_start_token=controller_token,
            output=output,
        )

    assert not output.exists()

    # Control: with the writer drained the same call proves quiescence, so the
    # refusal above is the live writer and not an unconditional failure.
    monkeypatch.setattr(writer_inventory, "_docker_writers", lambda: [])
    writer_inventory.prove_quiescent(
        controller_pid=controller_pid,
        controller_start_token=controller_token,
        output=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["all_consumers_stopped"] is True
    assert payload["domains"] == {domain: [] for domain in writer_inventory.DOMAINS}


def test_deploy_proceeds_past_inventory_with_shared_native_root(owner_sources, tmp_path):
    """`deploy_channel.sh deploy dev <sha>` must reach migrations and recreate."""

    # The inventory really is the deploy's first gate: the wrapper runs this
    # subcommand, and deploy_channel.sh runs the wrapper before migrations and
    # service recreate. That ordering is why a refusal blocks every channel.
    wrapper = (REPO_ROOT / "scripts" / "lib" / "instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "produce-legacy-owners" in wrapper

    # Compare call sites, not the function definitions further up the file.
    deploy = (REPO_ROOT / "scripts" / "deploy_channel.sh").read_text(encoding="utf-8")
    inventory_at = deploy.index("prepare_instance_state_deployment compose")
    migrate_at = deploy.index(
        'run_postmutation_gate "migration execution failed" apply_changed_migrations'
    )
    recreate_at = deploy.index('run_postmutation_gate "service recreate/liveness gate failed"')
    assert inventory_at < migrate_at
    assert inventory_at < recreate_at

    # The observed host arrangement: native and a channel on one iCloud vault.
    shared = _vault(tmp_path, "cloud-sync", "vault")
    owner_sources["owners"] = [("native", shared), ("prod", shared)]
    output = tmp_path / "legacy-owner-inventory.json"

    # Exactly the argv scripts/lib/instance_state_deployment.sh builds.
    exit_code = writer_inventory.main(
        [
            "produce-legacy-owners",
            "--repo-root",
            str(REPO_ROOT),
            "--active-channel",
            "dev",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["inventory_complete"] is True
