from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.builderops.control_plane import AuthorityEnvelope, DurabilityPending, PostgresBuilderOpsStore
from app.builderops.control_plane import bootstrap
from tests.builderops.bootstrap_fixtures import (
    REPOSITORIES, accept_fixture_authority, authenticated_github_fixture, authority_files, github_pages,
)
from tests.builderops.control_plane.conftest import _base_dsn, _schema_dsn

pytestmark = pytest.mark.pg


@pytest.fixture
def fresh_store():
    base = _base_dsn()
    schema = "rsc07_" + uuid4().hex
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    store = PostgresBuilderOpsStore(_schema_dsn(base, schema))
    try:
        yield store
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def envelope():
    return AuthorityEnvelope(repository=REPOSITORIES[0], scope="issue:5712", stack="builderops",
                             actor="test:bootstrap", source_refs=("github:issue:5712",), schema_version=1)


def task_write(store):
    return store.commit_transition(envelope=envelope(), task_id="test", to_state="ready",
                                   idempotency_key="create", request={})


def assert_fenced(store):
    assert store.bootstrap_status()["writers_enabled"] is False
    with pytest.raises(DurabilityPending):
        task_write(store)
    with pytest.raises(DurabilityPending):
        store.commit_record(envelope=envelope(), record_id="r", record_type="AgentWorklog",
                            state="active", payload={}, idempotency_key="record")
    with pytest.raises(DurabilityPending):
        store.claim_lease(envelope=envelope(), resource_id="resource", holder="worker",
                          ttl_seconds=30, idempotency_key="lease", request={})
    with pytest.raises(DurabilityPending):
        store.replay(REPOSITORIES[0], "absent-history")


def test_empty_database_seeds_inactive_epoch_without_restore_history(fresh_store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: fresh_store.initialize(), range(2)))
    initial = fresh_store.bootstrap_status()
    assert initial["status"] == "unknown"
    assert initial["authority_epoch"] > 1
    assert initial["bootstrap_id"]
    state = fresh_store.recovery_state()
    assert state["restored_lsn"] is None and state["recovery_id"] is None
    fresh_store.initialize()
    assert fresh_store.bootstrap_status() == initial
    assert_fenced(fresh_store)
    with pytest.raises(RuntimeError, match="gate"):
        fresh_store.complete_recovery_reconciliation(recovery_id="invented", authority_epoch=1)
    assert_fenced(fresh_store)


def test_authenticated_readback_must_converge_before_writers_enable(fresh_store, tmp_path):
    fresh_store.initialize()
    files = authority_files(tmp_path)
    with authenticated_github_fixture():
        result = bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert result["status"] == "converged"
    assert fresh_store.bootstrap_status()["writers_enabled"] is True
    task_write(fresh_store)
    # Receipt identity is necessary in addition to enabled booleans.
    with fresh_store._connect() as conn:
        conn.execute("UPDATE builderops_recovery_state SET bootstrap_receipt = "
                     "jsonb_set(bootstrap_receipt, '{bootstrap_id}', '\"foreign\"')")
    assert_fenced(fresh_store)


@pytest.mark.parametrize("failure", ["unauthenticated", "unavailable", "changing", "conflict", "pin", "attestation"])
def test_failed_readback_remains_fenced(fresh_store, tmp_path, failure):
    fresh_store.initialize()
    files = authority_files(tmp_path)
    with authenticated_github_fixture() as attestation:
        if failure == "pin":
            files["pin_file"].write_text("BUILDEROPS_SOURCE_SHA=unknown\n")
        if failure == "attestation":
            attestation.side_effect = bootstrap.BootstrapRefusal("unknown", "candidate_authentication_unavailable")
        calls = 0

        def pages(*args, **kwargs):
            nonlocal calls
            values = github_pages(*args, **kwargs)
            calls += 1
            if failure == "unavailable":
                raise bootstrap.GithubReadError("SECRET MUST NOT ESCAPE")
            if values and failure == "changing" and calls > len(REPOSITORIES) * 2:
                values[0]["state"] = "closed"
            if values and failure == "conflict":
                values[0]["labels"].append({"name": "agent:blocked"})
            return values

        with patch.object(bootstrap, "_paged_rest", side_effect=pages):
            if failure == "unauthenticated":
                with patch.object(bootstrap, "_run_gh", return_value={}):
                    result = bootstrap.bootstrap_from_authority(fresh_store, **files)
            else:
                result = bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert result["status"] in {"unknown", "conflict"}
    assert "SECRET" not in str(result) + str(fresh_store.bootstrap_status())
    assert_fenced(fresh_store)


def test_restart_is_idempotent_and_unknown_effects_are_not_replayed(fresh_store, tmp_path):
    fresh_store.initialize()
    files = authority_files(tmp_path)
    with authenticated_github_fixture():
        first = bootstrap.bootstrap_from_authority(fresh_store, **files)
        fresh_store.initialize()
        second = bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert first == second
    task_write(fresh_store)
    _, lease = fresh_store.claim_task(envelope=envelope(), task_id="test", holder="w",
                                     idempotency_key="claim", request={})
    intent = fresh_store.commit_transition(envelope=envelope(), task_id="test", to_state="effect_pending",
                                 idempotency_key="effect", request={}, lease=lease,
                                 outbox={"effect_type": "github.comment", "payload": {"issue": 5712}})
    claim = fresh_store.claim_outbox(envelope=envelope(), operation_key=intent.operation_key, worker_id="w")
    fresh_store.mark_effect_unknown(claim, detail="process lost; external result unknown")
    before = fresh_store.authority_counts(REPOSITORIES[0])
    with authenticated_github_fixture():
        result = bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert result == {"status": "unknown", "reason": "historical_effects_require_readback"}
    assert fresh_store.effect_eligible(claim) is False
    assert fresh_store.authority_counts(REPOSITORIES[0]) == before
    assert_fenced(fresh_store)


def test_concurrent_reconciliation_cannot_admit_dual_writer(fresh_store, tmp_path):
    fresh_store.initialize()
    entered, release = Event(), Event()
    files = authority_files(tmp_path)

    def attestation(*args):
        entered.set()
        assert release.wait(10)

    with authenticated_github_fixture() as authentication, ThreadPoolExecutor(max_workers=2) as pool:
        authentication.side_effect = attestation
        first = pool.submit(bootstrap.bootstrap_from_authority, fresh_store, **files)
        assert entered.wait(10)
        try:
            second = bootstrap.bootstrap_from_authority(fresh_store, **files)
            assert second == {"status": "conflict", "reason": "reconciliation_in_progress"}
            assert_fenced(fresh_store)
        finally:
            release.set()
        assert first.result()["status"] == "converged"


def test_upgrade_preserves_lineage_and_fences_old_writer(fresh_store):
    from tests.builderops.control_plane.test_migration_lineage import _initialize_schema_at_version

    _initialize_schema_at_version(fresh_store, 4)
    fresh_store.initialize()
    assert_fenced(fresh_store)
    accept_fixture_authority(fresh_store)
    assert fresh_store.bootstrap_status()["writers_enabled"] is True


def test_surviving_task_requires_matching_github_lifecycle(fresh_store, tmp_path):
    import hashlib

    fresh_store.initialize()
    files = authority_files(tmp_path)
    with authenticated_github_fixture():
        assert bootstrap.bootstrap_from_authority(fresh_store, **files)["status"] == "converged"
    repo = REPOSITORIES[0]
    payload = {"repo": repo, "issue_number": 5712, "sync_state": {
        "body_sha256": hashlib.sha256(b"Canonical fixture contract").hexdigest(),
        "source_version": "2026-09-28T00:00:00Z"}}
    fresh_store.commit_transition(envelope=envelope(), task_id=f"github-{repo.replace('/', '--')}-issue-5712",
                                 to_state="ready", idempotency_key="import", request=payload)
    with authenticated_github_fixture():
        assert bootstrap.bootstrap_from_authority(fresh_store, **files)["status"] == "converged"
        def closed(*args, **kwargs):
            items = github_pages(*args, **kwargs)
            for item in items:
                item["state"] = "closed"
            return items
        with patch.object(bootstrap, "_paged_rest", side_effect=closed):
            result = bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert result == {"status": "conflict", "reason": "surviving_task_lifecycle_mismatch"}
    assert_fenced(fresh_store)


def test_crash_after_readback_retains_fence_and_restart_identity(fresh_store, tmp_path):
    fresh_store.initialize()
    before = fresh_store.bootstrap_status()["bootstrap_id"]
    files = authority_files(tmp_path)
    with authenticated_github_fixture(), patch.object(bootstrap, "_readback", side_effect=SystemExit):
        with pytest.raises(SystemExit):
            bootstrap.bootstrap_from_authority(fresh_store, **files)
    assert_fenced(fresh_store)
    restart = PostgresBuilderOpsStore(fresh_store.dsn)
    restart.initialize()
    with authenticated_github_fixture():
        result = bootstrap.bootstrap_from_authority(restart, **files)
    assert result["receipt"]["bootstrap_id"] == before


def test_database_loss_refuses_old_clients_store_and_effects(fresh_store, tmp_path):
    from fastapi.testclient import TestClient
    from app.builderops.control_plane.models import StaleFencingToken
    from app.builderops.control_plane.service import create_app
    from tests.builderops.control_plane.test_service_auth import _registry, _lease_payload

    fresh_store.initialize()
    accept_fixture_authority(fresh_store)
    old_epoch = fresh_store.readiness()["authority_epoch"]
    task_write(fresh_store)
    registry = _registry(tmp_path)
    old_process = TestClient(create_app(store=fresh_store, credentials=registry))
    with fresh_store._connect() as conn:
        schema = conn.execute("SELECT current_schema() AS name").fetchone()["name"]
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    replacement = PostgresBuilderOpsStore(fresh_store.dsn)
    replacement.initialize()
    accept_fixture_authority(replacement)
    assert replacement.readiness()["authority_epoch"] != old_epoch
    with pytest.raises(StaleFencingToken):
        task_write(fresh_store)
    service = TestClient(create_app(store=replacement, credentials=registry))
    headers = {"Authorization": "Bearer client-token"}
    assert service.post("/v1/leases/claim", headers=headers, json=_lease_payload()).status_code == 428
    headers["X-BuilderOps-Authority-Epoch"] = str(old_epoch)
    assert service.post("/v1/leases/claim", headers=headers, json=_lease_payload()).status_code == 409
    assert old_process.post("/v1/leases/claim", headers=headers, json=_lease_payload()).status_code == 503
    assert replacement.authority_counts(REPOSITORIES[0])["outbox"] == 0
    assert replacement.authority_counts(REPOSITORIES[0])["tasks"] == 0
    assert replacement.authority_counts(REPOSITORIES[0])["receipts"] == 0


def test_old_binary_sql_cannot_bypass_upgrade_fence(fresh_store):
    from psycopg.types.json import Jsonb
    from tests.builderops.control_plane.test_migration_lineage import _initialize_schema_at_version

    _initialize_schema_at_version(fresh_store, 4)
    with fresh_store._connect() as old_connection:
        old_connection.commit()
        fresh_store.initialize()
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="epoch admission"):
            old_connection.execute("INSERT INTO builderops_tasks(repository,task_id,state,authority_envelope) "
                                   "VALUES (%s,'legacy','ready',%s)",
                                   (REPOSITORIES[0], Jsonb(envelope().as_json())))
        old_connection.rollback()
        accept_fixture_authority(fresh_store)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="epoch admission"):
            old_connection.execute("INSERT INTO builderops_tasks(repository,task_id,state,authority_envelope) "
                                   "VALUES (%s,'legacy','ready',%s)",
                                   (REPOSITORIES[0], Jsonb(envelope().as_json())))
        old_connection.rollback()


def test_readiness_is_false_during_network_reconciliation(fresh_store, tmp_path):
    from app.builderops.control_plane.health import HealthService, OperationalStatus
    from tests.builderops.control_plane.test_service_health import _registry

    fresh_store.initialize()
    accept_fixture_authority(fresh_store)
    health = HealthService(fresh_store, _registry(tmp_path),
                           type("Operational", (), {"snapshot": lambda self: OperationalStatus()})())
    assert health.status()["ready"] is True
    with fresh_store._connect() as conn:
        conn.execute("UPDATE builderops_recovery_state SET recovery_id='old-recovery'")
    def interrupted(*args):
        assert health.status()["ready"] is False
        with pytest.raises(RuntimeError, match="gate"):
            fresh_store.complete_recovery_reconciliation(
                recovery_id="old-recovery", authority_epoch=fresh_store.readiness()["authority_epoch"])
        raise bootstrap.GithubReadError("readback unavailable")
    with authenticated_github_fixture(), patch.object(bootstrap, "_readback", side_effect=interrupted):
        result = bootstrap.bootstrap_from_authority(fresh_store, **authority_files(tmp_path))
    assert result["status"] == "unknown"
    assert health.status()["ready"] is False
    assert_fenced(fresh_store)


@pytest.mark.parametrize("previous_status", ["pending", "claimed", "unknown", "upgraded_pending"])
def test_authenticated_recovery_resolves_surviving_effect_while_writers_fenced(fresh_store, tmp_path, previous_status):
    import hashlib
    import json
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.builderops.control_plane.service import create_app
    from tests.builderops.control_plane.test_service_auth import _registry

    if previous_status == "upgraded_pending":
        from tests.builderops.control_plane.test_migration_lineage import _initialize_schema_at_version
        _initialize_schema_at_version(fresh_store, 4)
    else:
        fresh_store.initialize()
        accept_fixture_authority(fresh_store)
    registry = _registry(tmp_path)
    manifest = json.loads(registry.manifest_path.read_text())
    manifest["credentials"][0]["scopes"].append("outbox:write")
    registry.manifest_path.write_text(json.dumps(manifest))
    env = replace(envelope(), actor="client:macbook")
    repo = REPOSITORIES[0]
    task_id = f"github-{repo.replace('/', '--')}-issue-5712"
    payload = {"repo": repo, "issue_number": 5712, "sync_state": {
        "body_sha256": hashlib.sha256(b"Canonical fixture contract").hexdigest(),
        "source_version": "2026-09-28T00:00:00Z"}}
    old_claim = None
    if previous_status == "upgraded_pending":
        from psycopg.types.json import Jsonb
        from types import SimpleNamespace
        intent = SimpleNamespace(operation_key="surviving-v4-intent")
        with fresh_store._connect() as conn:
            conn.execute("INSERT INTO builderops_tasks(repository,task_id,state,payload,authority_envelope) "
                         "VALUES (%s,%s,'completed',%s,%s)",
                         (repo, task_id, Jsonb(payload), Jsonb(env.as_json())))
            sequence = conn.execute("INSERT INTO builderops_receipts(repository,task_id,event_type," 
                                    "idempotency_key,authority_envelope) VALUES (%s,%s,'task.effect_pending'," 
                                    "'surviving-v4-intent',%s) RETURNING receipt_sequence",
                                    (repo, task_id, Jsonb(env.as_json()))).fetchone()["receipt_sequence"]
            conn.execute("INSERT INTO builderops_outbox(repository,operation_key,task_id,effect_type,payload," 
                         "intent_receipt_sequence,authority_envelope) "
                         "VALUES (%s,%s,%s,'github.comment',%s,%s,%s)",
                         (repo, intent.operation_key, task_id, Jsonb({"issue": 5712}), sequence, Jsonb(env.as_json())))
        committed_lsn = fresh_store._flushed_lsn()
        with fresh_store._connect() as conn:
            conn.execute("UPDATE builderops_outbox SET intent_lsn=%s", (committed_lsn,))
            conn.execute("UPDATE builderops_receipts SET recovery_lsn=%s", (committed_lsn,))
        fresh_store.initialize()
        with fresh_store._connect() as conn:
            surviving = conn.execute("SELECT status,worker_id,claim_fencing_token,claim_receipt_sequence "
                                     "FROM builderops_outbox").fetchone()
        assert surviving == {"status": "unknown", "worker_id": None,
                             "claim_fencing_token": 0, "claim_receipt_sequence": None}
    else:
        fresh_store.commit_transition(envelope=env, task_id=task_id, to_state="ready",
                                     idempotency_key="create", request=payload)
        _, lease = fresh_store.claim_task(envelope=env, task_id=task_id, holder="worker",
                                         idempotency_key="claim", request=payload)
        intent = fresh_store.commit_transition(envelope=env, task_id=task_id, to_state="claimed",
                                              idempotency_key="effect", request=payload, lease=lease,
                                              outbox={"effect_type": "github.comment", "payload": {"issue": 5712}})
        old_claim = None
        if previous_status != "pending":
            old_claim = fresh_store.claim_outbox(envelope=env, operation_key=intent.operation_key, worker_id="lost")
            if previous_status == "unknown":
                fresh_store.mark_effect_unknown(old_claim, detail="lost response")
            with fresh_store._connect() as conn:
                fresh_store._assert_executor_enabled(conn)
                conn.execute("UPDATE builderops_outbox SET claim_expires_at=clock_timestamp()-interval '1 second'")
        fresh_store.complete_task(envelope=env, lease=lease, idempotency_key="complete", request=payload)
    def closed(*args, **kwargs):
        items = github_pages(*args, **kwargs)
        for item in items:
            item.update(state="closed", labels=[])
        return items
    files = authority_files(tmp_path)
    with authenticated_github_fixture(), patch.object(bootstrap, "_paged_rest", side_effect=closed):
        assert bootstrap.bootstrap_from_authority(fresh_store, **files)["status"] == "unknown"
        assert_fenced(fresh_store)
        client = TestClient(create_app(store=fresh_store, credentials=registry))
        headers = {"Authorization": "Bearer client-token",
                   "X-BuilderOps-Authority-Epoch": str(fresh_store.readiness()["authority_epoch"])}
        body_envelope = {key: value for key, value in env.as_json().items() if key not in {"actor", "schema_version"}}
        request = {"envelope": body_envelope, "operation_key": intent.operation_key, "worker_id": "reconciler"}
        assert client.post("/v1/executor/outbox/recover", json=request).status_code == 401
        recovered = client.post("/v1/executor/outbox/recover", headers=headers, json=request)
        assert recovered.status_code == 200, recovered.text
        claim_fields = {key: recovered.json()[key] for key in (
            "repository", "operation_key", "worker_id", "fencing_token", "intent_lsn", "claim_lsn",
            "receipt_sequence", "expires_at")}
        if old_claim is not None:
            assert claim_fields["fencing_token"] > old_claim.fencing_token
            assert fresh_store.effect_eligible(old_claim) is False
        rejected = client.post("/v1/executor/outbox/reconcile", headers=headers, json={
            "envelope": body_envelope, "claim": claim_fields, "observed_applied": False,
            "evidence": {"outcome": "not_applied", "transport_invoked": False,
                         "reason_class": "ValueError"}})
        assert rejected.status_code == 400
        assert fresh_store.outbox_status(repo, intent.operation_key) == "unknown"
        assert_fenced(fresh_store)
        reconciled = client.post("/v1/executor/outbox/reconcile", headers=headers, json={
            "envelope": body_envelope, "claim": claim_fields, "observed_applied": False,
            "evidence": {"readback": "not-found", "source": "authenticated-fixture-external-readback"}})
        assert reconciled.status_code == 200, reconciled.text
        assert_fenced(fresh_store)
        result = bootstrap.bootstrap_from_authority(fresh_store, **files)
        assert result["status"] == "converged", result
    # Reconciliation makes a known not-applied intent eligible for later normal
    # scheduling; bootstrap itself has not issued an effect or created a claim.
    assert fresh_store.outbox_status(repo, intent.operation_key) == "pending"


def test_restored_epoch_still_advances_and_requires_new_admission(fresh_store):
    from app.builderops.control_plane.models import StaleFencingToken

    fresh_store.initialize()
    accept_fixture_authority(fresh_store)
    old_epoch = fresh_store.readiness()["authority_epoch"]
    fresh_store.claim_lease(envelope=envelope(), resource_id="old", holder="old", idempotency_key="old", request={})
    advanced = fresh_store.activate_recovered_epoch(recovery_id="isolated-restore", restored_lsn="0/10")
    assert advanced == old_epoch + 1
    with pytest.raises(StaleFencingToken):
        task_write(fresh_store)
    replacement = PostgresBuilderOpsStore(fresh_store.dsn)
    replacement.initialize()
    assert replacement.readiness()["authority_epoch"] == advanced
    assert_fenced(replacement)
    accept_fixture_authority(replacement)
    assert replacement.bootstrap_status()["writers_enabled"] is True
