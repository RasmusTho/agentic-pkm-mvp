from __future__ import annotations

import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)

pytestmark = pytest.mark.pg

PRE_OUTBOX_BINDING_HEAD = "f5a05a5b0001"
OUTBOX_BINDING_HEAD = "f6a05a7b0001"


def _upgrade(dsn: str, monkeypatch: pytest.MonkeyPatch, revision: str) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(config, revision)


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    name = f"scratch_mvr05a7_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_legacy_rows_keep_their_keys_and_classify_or_quarantine(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upgrade(scratch_db, monkeypatch, PRE_OUTBOX_BINDING_HEAD)
    pending_id = uuid.uuid4()
    delivered_id = uuid.uuid4()
    with psycopg.connect(scratch_db) as conn:
        conn.execute(
            "INSERT INTO outbox (id, topic, payload) VALUES (%s, 'pending', '{}'::jsonb)",
            (pending_id,),
        )
        conn.execute(
            "INSERT INTO outbox (id, topic, payload, delivered_at) "
            "VALUES (%s, 'delivered', '{}'::jsonb, now())",
            (delivered_id,),
        )

    _upgrade(scratch_db, monkeypatch, OUTBOX_BINDING_HEAD)

    with psycopg.connect(scratch_db) as conn:
        rows = conn.execute(
            "SELECT id, legacy_key, vault_binding_id, delivered_at IS NOT NULL "
            "FROM outbox ORDER BY topic"
        ).fetchall()
    assert rows == [
        (delivered_id, delivered_id, COMPATIBILITY_BINDING_ID, True),
        (pending_id, pending_id, COMPATIBILITY_BINDING_ID, False),
    ]
    assert OUTBOX_QUARANTINE_BINDING_ID != COMPATIBILITY_BINDING_ID


def test_partially_upgraded_unprovable_row_is_quarantined(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _upgrade(scratch_db, monkeypatch, PRE_OUTBOX_BINDING_HEAD)
    scoped_id = uuid.uuid4()
    legacy_id = uuid.uuid4()
    with psycopg.connect(scratch_db) as conn:
        conn.execute("ALTER TABLE outbox ADD COLUMN legacy_key uuid")
        conn.execute("ALTER TABLE outbox ADD COLUMN vault_binding_id text")
        conn.execute(
            "INSERT INTO outbox (id, legacy_key, topic, payload) "
            "VALUES (%s, %s, 'partial', '{}'::jsonb)",
            (scoped_id, legacy_id),
        )

    _upgrade(scratch_db, monkeypatch, OUTBOX_BINDING_HEAD)

    with psycopg.connect(scratch_db) as conn:
        row = conn.execute(
            "SELECT id, legacy_key, vault_binding_id FROM outbox WHERE id = %s", (scoped_id,)
        ).fetchone()
    assert row == (scoped_id, legacy_id, OUTBOX_QUARANTINE_BINDING_ID)


# -- MVR-06D (#3866): classification receipt gate and the all-process floor ---------------

#: The last MVR-06C image on main (PR #6596): it understands v1..v3 registries only.
MVR06C_IMAGE_SHA = "6da6e2342ef362319e7810abd1c9370cb2ebe89d"


@pytest.fixture
def mvr06d_db(tmp_path, monkeypatch):
    """An MVR-06B instance over a real outbox carrying MVR-05-classified legacy rows."""

    from tests._mvr06b_handoff_harness import mvr06b_instance, stub_settings_reload
    from tests._mvr06d_many_binding_harness import scratch_database, upgrade, use_database

    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)
    with scratch_database(PRE_OUTBOX_BINDING_HEAD) as dsn:
        legacy_pending = uuid.uuid4()
        unprovable = uuid.uuid4()
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO outbox (id, topic, payload) VALUES (%s, 'legacy.unhandled', '{}'::jsonb)",
                (legacy_pending,),
            )
            conn.execute("ALTER TABLE outbox ADD COLUMN legacy_key uuid")
            conn.execute("ALTER TABLE outbox ADD COLUMN vault_binding_id text")
            conn.execute(
                "INSERT INTO outbox (id, legacy_key, topic, payload) "
                "VALUES (%s, %s, 'legacy.ambiguous', '{}'::jsonb)",
                (unprovable, uuid.uuid4()),
            )
        upgrade(dsn, "head")
        stub_settings_reload(monkeypatch)
        runtime, first, extra = mvr06b_instance(tmp_path, monkeypatch)
        use_database(monkeypatch, dsn)
        monkeypatch.setenv("WORKER_CLAIM_LEASE_SECONDS", "30")
        monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
        yield runtime, first, dsn, str(legacy_pending), str(unprovable)


def _outbox(dsn: str, row_id: str) -> tuple:
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "SELECT id::text, legacy_key::text, vault_binding_id, delivered_at IS NOT NULL, "
            "claim_token, quarantined_at IS NOT NULL FROM outbox WHERE id = %s",
            (row_id,),
        ).fetchone()


def test_mvr06_requires_complete_mvr05_classification_receipt(mvr06d_db) -> None:
    from dataclasses import replace

    from app.instance.many_binding_activation import validate_mvr05_classification
    from app.instance.vault_registry import (
        MVR06_MINIMUM_RUNTIME_SCHEMA,
        CapabilityNotReadyError,
        many_binding_dispatch_enabled,
    )
    from app.services.outbox import ack_outbox
    from app.workers.many_binding_dispatch import ManyBindingDispatcher
    from tests._mvr06d_many_binding_harness import (
        activate_many_binding,
        emit_stage,
        enroll_exactly,
        supervisor_for,
    )
    from app.instance.background_supervisor import emit_background_intent_event

    runtime, first, dsn, legacy_pending, unprovable = mvr06d_db
    binding = first.vault_binding_id
    scoped = emit_stage(runtime, binding, "classified-scoped")
    global_row = emit_background_intent_event(runtime.registry.load(), reason="governed_add")
    assert global_row
    assert _outbox(dsn, legacy_pending)[2] == COMPATIBILITY_BINDING_ID
    assert _outbox(dsn, unprovable)[2] == OUTBOX_QUARANTINE_BINDING_ID
    before = runtime.layout.registry_path.read_bytes()

    # An incomplete MVR-05 receipt refuses before any database read.
    snapshot = runtime.registry.load()
    floors = dict(snapshot.extensions["runtimeFloors"])
    floors.pop("mvr05CutoverFence")
    stripped = replace(snapshot, extensions={**snapshot.extensions, "runtimeFloors": floors})
    with pytest.raises(CapabilityNotReadyError, match="MVR-05"):
        validate_mvr05_classification(stripped)

    # A still-dispatchable unscoped compatibility row refuses activation; nothing changes.
    refused = activate_many_binding(runtime)
    assert refused["_exit_code"] == 1 and "unscoped compatibility" in refused["error"]
    assert runtime.layout.registry_path.read_bytes() == before
    assert not many_binding_dispatch_enabled(runtime.registry.load())
    floor = runtime.registry.load().extensions["runtimeFloors"]["minimumRuntimeSchema"]
    assert floor == MVR06_MINIMUM_RUNTIME_SCHEMA

    # Drained through the singleton path (one canonical lineage, acknowledged once) ...
    assert ack_outbox(legacy_pending)
    receipt = activate_many_binding(runtime)
    assert receipt["_exit_code"] == 0, receipt
    assert receipt["classification"] == {
        "mvr05_receipt": "valid",
        "outbox": "postgres",
        "unprovable_quarantined": 1,
        "global_pending": 1,
        "scoped_pending": 1,
        "scoped_unregistered_bindings": 0,
    }
    again = activate_many_binding(runtime)
    assert again["_exit_code"] == 0 and again["activated"] is False

    # ... then the many-binding worker: global keeps one lineage with at-least-once
    # dispatch, the scoped row keeps one lineage under its own binding, and the
    # unprovable row stays quarantined: never claimed, dispatched, or acknowledged.
    enroll_exactly(runtime, (binding,))
    global_before = _outbox(dsn, global_row)
    scoped_before = _outbox(dsn, scoped)
    worker = ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="classifier")
    for _ in range(6):
        worker.tick()
    global_after = _outbox(dsn, global_row)
    scoped_after = _outbox(dsn, scoped)
    assert global_after[:3] == global_before[:3] and global_after[3] is True
    assert scoped_after[:3] == scoped_before[:3] and scoped_after[3] is True
    assert scoped_after[2] == binding
    assert _outbox(dsn, unprovable) == (unprovable, _outbox(dsn, unprovable)[1],
                                        OUTBOX_QUARANTINE_BINDING_ID, False, None, False)
    with psycopg.connect(dsn) as conn:
        duplicates = conn.execute(
            "SELECT count(*) FROM outbox WHERE legacy_key = %s::uuid", (scoped_before[1],)
        ).fetchone()
    assert duplicates == (1,)


def test_mvr06d_floor_precedes_first_queue_state_write_and_blocks_older_runtime(
    mvr06d_db, monkeypatch
) -> None:
    import subprocess
    import sys
    import types

    from app.instance.runtime import _preflight_runtime
    from app.instance.vault_registry import (
        MANY_BINDING_REGISTRY_SCHEMA,
        RegistryError,
        VaultRegistryStore,
    )
    from app.services import outbox_claims
    from app.services.outbox import ack_outbox
    from app.workers import outbox_worker
    from app.workers.many_binding_dispatch import ManyBindingDispatcher
    from tests._mvr06d_many_binding_harness import (
        activate_many_binding,
        emit_stage,
        supervisor_for,
    )
    from tests._mvr_default_vault_harness import REPO_ROOT
    from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY

    runtime, first, dsn, legacy_pending, _unprovable = mvr06d_db
    binding = first.vault_binding_id
    source = subprocess.check_output(
        ["git", "show", f"{MVR06C_IMAGE_SHA}:app/instance/vault_registry.py"],
        cwd=REPO_ROOT,
        text=True,
    )
    previous = types.ModuleType("tests._mvr06c_previous_registry_image")
    sys.modules[previous.__name__] = previous
    try:
        exec(compile(source, "mvr06c-registry-image.py", "exec"), previous.__dict__)
        # The 06C image still runs against pre-activation state ...
        previous.VaultRegistryStore(runtime.layout.registry_path).read_existing()

        # ... and its singleton worker writes no queue-state field.
        assert ack_outbox(legacy_pending)
        scalar_row = emit_stage(runtime, binding, "pre-floor-singleton")
        for _ in range(3):
            outbox_worker.run_once()
        assert _outbox(dsn, scalar_row)[3:] == (True, None, False)

        # A queue-state field written before the floor refuses activation.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("UPDATE outbox SET quarantined_at = now() WHERE id = %s", (scalar_row,))
        refused = activate_many_binding(runtime)
        assert refused["_exit_code"] == 1 and "before the MVR-06D floor" in refused["error"]
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("UPDATE outbox SET quarantined_at = NULL WHERE id = %s", (scalar_row,))

        # The first claim -- the first queue-state write -- sees the committed floor.
        observed: list[tuple[str, str]] = []
        real_claim = outbox_claims.claim_next

        def recording_claim(conn, **kwargs):
            on_disk = VaultRegistryStore(runtime.layout.registry_path).read_existing()
            observed.append(
                (on_disk.schema, on_disk.extensions["runtimeFloors"]["minimumRuntimeSchema"])
            )
            return real_claim(conn, **kwargs)

        monkeypatch.setattr(outbox_claims, "claim_next", recording_claim)
        activated = activate_many_binding(runtime)
        assert activated["_exit_code"] == 0, activated
        claimed_row = emit_stage(runtime, binding, "post-floor-claim")
        ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="floor").tick()
        assert observed and set(observed) == {(MANY_BINDING_REGISTRY_SCHEMA, "mvr-06d")}
        assert _outbox(dsn, claimed_row)[3] is True

        # Every older API/watcher/worker image refuses the registry before any access,
        # and cannot heal or rewrite it.
        path = runtime.layout.registry_path
        frozen = path.read_bytes()
        with pytest.raises(RuntimeError, match="schema mismatch"):
            previous.VaultRegistryStore(path).read_existing()
        with pytest.raises(RuntimeError):
            previous.VaultRegistryStore(path).load()
        assert path.read_bytes() == frozen
    finally:
        sys.modules.pop(previous.__name__, None)

    # The 06D image starts every consumer.
    for consumer in ("api", "watcher", "worker"):
        assert _preflight_runtime(
            channel=runtime.layout.channel_id,
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            consumer=consumer,
        ) == 0
    # Rollback uses a 06D-compatible image: nothing lowers or compensates the floor.
    with pytest.raises(RegistryError, match="MVR-06 runtime floor cannot be changed"):
        runtime.registry.set_extension_state(
            principal_state={},
            background_state={},
            runtime_floors={"minimumRuntimeSchema": "mvr-06"},
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    with pytest.raises(RegistryError, match="no MVR-06 runtime floor"):
        runtime.registry.compensate_mvr06_runtime_floor(
            expected_revision=runtime.registry.load().revision,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
