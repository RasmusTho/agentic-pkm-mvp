"""MVR-06D (#3866): recoverable PostgreSQL claims under independent production workers.

`docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md` (MVR-06D) and
`docs/EVENTS.md :: Outbox envelope (canonical)`. Every row is produced by the real KA-06
stage producer inside its binding's effect window and consumed by the shipped
many-binding dispatcher; the admitted handler's durable effect is its consumer-signal
outbox row, committed atomically with the claim's effect outcome. Missing PostgreSQL or
missing claim constraints fail these tests; they never skip.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time

import psycopg
import pytest

from app.services import outbox_claims as claims
from app.workers import many_binding_dispatch as dispatch
from tests._mvr06b_handoff_harness import stub_settings_reload
from tests._mvr06d_many_binding_harness import (
    PRE_CLAIM_HEAD,
    emit_stage,
    many_binding_instance,
    race_worker,
    ready_signals,
    rows,
    scratch_database,
    supervisor_for,
)

pytestmark = pytest.mark.pg


#: Lease for crash-injection setups: long enough that a slow CI runner finishes the setup
#: ticks before any injected crash's lease could expire and be reclaimed early.
_CRASH_LEASE = 5


class _Crash(BaseException):
    """A process death at an injected point: no in-process cleanup may run."""


@pytest.fixture(autouse=True)
def _no_env_vault(monkeypatch):
    for name in ("VAULT_ROOT", "VAULT_ROOT_PROD", "WATCHER_VAULT_PATH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def pg_many(tmp_path, monkeypatch):
    with scratch_database() as dsn:
        stub_settings_reload(monkeypatch)
        monkeypatch.setenv("WORKER_CLAIM_LEASE_SECONDS", "30")
        monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
        runtime, a, b, _rest = many_binding_instance(tmp_path, monkeypatch, dsn=dsn)
        yield runtime, a.vault_binding_id, b.vault_binding_id, dsn


def _row(dsn: str, row_id: str) -> dict:
    found = rows(
        dsn,
        "select delivered_at is not null, claim_phase, effect_outcome, quarantined_at is not null, "
        "quarantine_reason, consumer_context, claim_token, vault_binding_id, legacy_key::text "
        "from outbox where id = %s",
        (row_id,),
    )
    assert found, row_id
    keys = ("delivered", "phase", "outcome", "quarantined", "reason", "consumer", "token",
            "binding", "legacy_key")
    return dict(zip(keys, found[0]))


def _expire_leases(monkeypatch, seconds: float = _CRASH_LEASE + 0.3) -> None:
    time.sleep(seconds)


def _crash_at(monkeypatch, stage: str, row_id: str) -> None:
    def fault(name, claim=None):
        if name == stage and claim is not None and claim.row_id == row_id:
            raise _Crash(name)

    monkeypatch.setattr(dispatch, "_claim_fault_point", fault)


def test_concurrent_claim_owner_and_crash_redelivery_preserve_at_least_once(
    pg_many, tmp_path, monkeypatch
) -> None:
    runtime, binding_a, binding_b, dsn = pg_many

    # -- no PostgreSQL claim constraints is an error, never a silent unfenced fallback ---
    with scratch_database(PRE_CLAIM_HEAD) as old_dsn:
        with psycopg.connect(old_dsn, autocommit=True) as conn:
            with pytest.raises(claims.OutboxClaimSchemaMissing):
                claims.require_claim_schema(conn)

    # -- raw claim race: eight connections, each row leased by exactly one owner --------
    raced = [emit_stage(runtime, binding_a, f"raw-{index}") for index in range(12)]
    seen: list[tuple[str, str]] = []
    guard = threading.Lock()

    def claimer(owner: str) -> None:
        with psycopg.connect(dsn, autocommit=True) as conn:
            while True:
                claim = claims.claim_next(
                    conn, owner=owner, vault_binding_id=binding_a, lease_seconds=60
                )
                if claim is None:
                    return
                with guard:
                    seen.append((claim.row_id, owner))

    threads = [threading.Thread(target=claimer, args=(f"t{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    claimed_ids = [row_id for row_id, _owner in seen]
    assert sorted(claimed_ids) == sorted(raced), "a row was claimed twice or not at all"
    # Binding B's scope was never touched by binding A's claimers.
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert claims.claim_next(
            conn, owner="probe", vault_binding_id=binding_b, lease_seconds=1
        ) is None
        for row_id in raced:  # release them back for the real dispatch below
            conn.execute(
                "update outbox set claim_phase = null, claim_owner = null, "
                "claim_expires_at = null where id = %s", (row_id,)
            )

    # -- independent production worker processes race the full poll/claim/dispatch/ack --
    sources = raced + [emit_stage(runtime, binding_b, f"race-b-{index}") for index in range(8)]
    log_path = tmp_path / "effect-windows.jsonl"
    context = multiprocessing.get_context("spawn")
    env = dict(os.environ)
    workers = [
        context.Process(
            target=race_worker,
            args=(env, str(runtime.layout.registry_path), str(runtime.ledger.root),
                  runtime.layout.channel_id, f"worker-{index}", str(log_path), 200),
        )
        for index in range(3)
    ]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(timeout=100)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
    assert all(worker.exitcode == 0 for worker in workers), [w.exitcode for w in workers]
    windows: dict[str, list[dict]] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        windows.setdefault(event["row"], []).append(event)
    owners_used = {event["owner"] for events in windows.values() for event in events}
    assert len(owners_used) >= 2, "the workers did not actually race"
    for row_id in sources:
        events = sorted(windows[row_id], key=lambda item: item["t"])
        starts = [item for item in events if item["stage"] == "effect_pending"]
        assert len(starts) == 1, f"row {row_id} had {len(starts)} concurrent claim owners"
        state = _row(dsn, row_id)
        assert state["delivered"] and state["outcome"] == "applied", state
    identities = [f"raw-{i}" for i in range(12)] + [f"race-b-{i}" for i in range(8)]
    for identity in identities:
        assert len(ready_signals(dsn, identity)) == 1, identity
    # Effects stayed attributed to their own binding.
    assert {binding for _id, binding in ready_signals(dsn, "race-b-0")} == {binding_b}

    # -- crash after the handler effect, before acknowledgement -------------------------
    monkeypatch.setenv("WORKER_CLAIM_LEASE_SECONDS", str(_CRASH_LEASE))
    crashed = emit_stage(runtime, binding_a, "crash-after-effect")
    w1 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w1")
    _crash_at(monkeypatch, "effect_committed", crashed)
    with pytest.raises(_Crash):
        for _ in range(5):
            w1.tick()
    stranded = _row(dsn, crashed)
    assert stranded["outcome"] == "applied" and not stranded["delivered"]
    assert stranded["phase"] == "effect_pending"
    monkeypatch.setattr(dispatch, "_claim_fault_point", lambda name, claim=None: None)
    w2 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w2")
    w2.tick()  # the lease is still live: no second owner, no lost row
    assert not _row(dsn, crashed)["delivered"]
    _expire_leases(monkeypatch)
    for _ in range(3):
        w2.tick()
    redelivered = _row(dsn, crashed)
    assert redelivered["delivered"] and redelivered["phase"] is None
    assert redelivered["consumer"]["reconciled"] == "effect_outcome_durable"
    assert len(ready_signals(dsn, "crash-after-effect")) == 1  # absorbed, not replayed

    # -- crash inside the effect transaction: rolled back, redelivered, applied once -----
    rolled = emit_stage(runtime, binding_b, "crash-during-effect")
    _crash_at(monkeypatch, "effect_running", rolled)
    with pytest.raises(_Crash):
        for _ in range(5):
            w1.tick()
    assert _row(dsn, rolled)["outcome"] is None
    assert ready_signals(dsn, "crash-during-effect") == []
    monkeypatch.setattr(dispatch, "_claim_fault_point", lambda name, claim=None: None)
    _expire_leases(monkeypatch)
    for _ in range(3):
        w2.tick()
    assert _row(dsn, rolled)["delivered"]
    assert len(ready_signals(dsn, "crash-during-effect")) == 1
    # Nothing is left claimed or lost.
    assert rows(
        dsn,
        "select count(*) from outbox where delivered_at is null and quarantined_at is null",
    ) == [(0,)]


def test_expired_claim_stale_owner_cannot_effect_after_reclaim(pg_many, monkeypatch) -> None:
    runtime, binding_a, _binding_b, dsn = pg_many
    monkeypatch.setenv("WORKER_CLAIM_LEASE_SECONDS", "1")
    row_id = emit_stage(runtime, binding_a, "stale-owner")
    w1 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w1")
    w2 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w2")
    outcomes: dict[str, object] = {}

    def pause_w1(name, claim=None):
        if name != "effect_pending" or claim is None or claim.owner != "w1:" + binding_a:
            return
        outcomes["w1_token"] = claim.token
        time.sleep(1.3)  # W1 pauses after effect_pending, beyond its lease
        monkeypatch.setattr(dispatch, "_claim_fault_point", lambda *_a, **_k: None)
        reclaimed = w2.tick()  # W2 reclaims the expired row and completes it
        outcomes["w2"] = [item.state for item in reclaimed.outcomes]
        outcomes["after_w2"] = _row(dsn, row_id)

    monkeypatch.setattr(dispatch, "_claim_fault_point", pause_w1)
    w1_tick = w1.tick()
    w1_states = {item.scope: item.state for item in w1_tick.outcomes}
    # W1's stale monotonic token was rejected at the production effect boundary.
    assert w1_states[binding_a] == "stale_claim_rejected"
    assert "processed" in outcomes["w2"]
    final = _row(dsn, row_id)
    assert final["delivered"] and final["outcome"] == "applied"
    assert final["token"] > outcomes["w1_token"]
    assert outcomes["after_w2"]["delivered"]
    assert len(ready_signals(dsn, "stale-owner")) == 1  # exactly one durable effect

    # The boundary itself: a superseded claim cannot open an effect transaction, and an
    # effect attempted under it leaves nothing durable.
    other = emit_stage(runtime, binding_a, "stale-direct")
    with psycopg.connect(dsn, autocommit=True) as conn:
        stage_topic = ("knowledge_acquisition.stage.completed",)
        first = claims.claim_next(conn, owner="old", vault_binding_id=binding_a,
                                  lease_seconds=1, topics=stage_topic)
        assert first is not None and first.row_id == other
        first = claims.mark_effect_pending(conn, first, {"contract": "probe"})
        time.sleep(1.2)
        second = claims.claim_next(conn, owner="new", vault_binding_id=binding_a,
                                   lease_seconds=30, topics=stage_topic)
        assert second is not None and second.row_id == other and second.token > first.token
        assert second.recovered_effect_pending
    txn = psycopg.connect(dsn)
    try:
        with pytest.raises(claims.StaleClaimToken):
            with claims.fenced_effect(txn, first, outcome="applied", receipt={}) as effect:
                effect.execute("update outbox set attempts = attempts + 100 where id = %s",
                               (other,))
    finally:
        txn.close()
    assert rows(dsn, "select attempts, effect_outcome from outbox where id = %s",
                (other,)) == [(0, None)]


@pytest.mark.parametrize("loss", ["revoked", "removed"])
def test_revocation_after_effect_reconciles_receipt_before_authority_quarantine(
    pg_many, monkeypatch, loss
) -> None:
    runtime, binding_a, binding_b, dsn = pg_many
    monkeypatch.setenv("WORKER_CLAIM_LEASE_SECONDS", str(_CRASH_LEASE))
    applied = emit_stage(runtime, binding_b, "applied-before-loss")
    unapplied = emit_stage(runtime, binding_b, "unapplied-before-loss")
    ambiguous = emit_stage(runtime, binding_b, "ambiguous-before-loss")
    w1 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w1")

    _crash_at(monkeypatch, "effect_committed", applied)
    with pytest.raises(_Crash):
        for _ in range(5):
            w1.tick()
    _crash_at(monkeypatch, "effect_running", unapplied)
    with pytest.raises(_Crash):
        for _ in range(5):
            w1.tick()
    # The third crashes after effect_pending under an effect contract this image no
    # longer runs (an upgrade changed it): its missing outcome proves nothing.
    monkeypatch.setattr(dispatch, "EFFECT_CONTRACT_VERSION", "agentic-pkm.mvr06d-effect-contract.v0")
    _crash_at(monkeypatch, "effect_pending", ambiguous)
    with pytest.raises(_Crash):
        for _ in range(5):
            w1.tick()
    monkeypatch.setattr(dispatch, "EFFECT_CONTRACT_VERSION", "agentic-pkm.mvr06d-effect-contract.v1")
    monkeypatch.setattr(dispatch, "_claim_fault_point", lambda name, claim=None: None)
    untouched = emit_stage(runtime, binding_b, "pending-before-loss")

    if loss == "revoked":
        from app.governance.binding_authority import RegistryBindingAuthorizer
        from tests.helpers.revoked_binding_authorizer import RevokedBindingAuthorizer

        original = RegistryBindingAuthorizer.authorize

        def authorize(self, request):
            if request.vault_binding_id != binding_b:
                return original(self, request)
            revoked = RevokedBindingAuthorizer(self)
            revoked.revoke_for_test(binding_b)
            return revoked.authorize(request)

        monkeypatch.setattr(RegistryBindingAuthorizer, "authorize", authorize)
        expected_reason = "authority_lost"
    else:
        time.sleep(_CRASH_LEASE + 0.3)  # the crashed owner is gone; removal drains no live effect
        runtime.remove(binding_b)
        expected_reason = "binding_removed"
    time.sleep(0.1 if loss == "removed" else _CRASH_LEASE + 0.3)
    w2 = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w2")
    for _ in range(3):
        w2.tick()

    proven = _row(dsn, applied)
    assert proven["delivered"] and proven["outcome"] == "applied" and not proven["quarantined"]
    assert proven["consumer"]["reconciled"] == "effect_outcome_durable"
    assert proven["consumer"]["authority_at_recovery"] == expected_reason
    assert len(ready_signals(dsn, "applied-before-loss")) == 1

    no_effect = _row(dsn, unapplied)
    assert no_effect["quarantined"] and no_effect["reason"] == expected_reason
    assert not no_effect["delivered"] and no_effect["outcome"] is None
    assert ready_signals(dsn, "unapplied-before-loss") == []

    blocked = _row(dsn, ambiguous)
    assert blocked["phase"] == "effect_reconciliation_required"
    assert not blocked["delivered"] and not blocked["quarantined"]
    assert ready_signals(dsn, "ambiguous-before-loss") == []

    pending = _row(dsn, untouched)
    assert pending["quarantined"] and pending["reason"] == expected_reason

    # Later ticks neither replay, acknowledge, drop, nor re-quarantine the ambiguous row.
    for _ in range(2):
        w2.tick()
    assert _row(dsn, ambiguous)["phase"] == "effect_reconciliation_required"
    with psycopg.connect(dsn, autocommit=True) as conn:
        assert not claims.drop_quarantined(conn, ambiguous, reason="probe")
    # Binding A was never touched, and readiness is blocked, not healthy.
    from app.instance.background_supervisor import aggregate_background_health

    health = aggregate_background_health()
    assert health["readiness"] == "blocked"
    assert health["queue"]["scopes"][binding_b]["reconciliation_required"] == 1
    assert any(
        item["binding_id"] == binding_a and item["status"] == "running"
        for item in health["lifecycles"]
    )


def test_singleton_drain_never_touches_claim_or_quarantine_state(pg_many) -> None:
    """Regression (convergence review P1): after the MVR-06D floor the reactivation/transfer
    drain still settles rows through the singleton poll, so it must refuse a binding whose
    queue holds quarantine, reconciliation-required, effect-bearing, or live claim state."""

    from pathlib import Path

    from app.workers.outbox_worker import OutboxDrainBlocked, drain_binding_outbox
    from tests._mvr06b_handoff_harness import admin

    runtime, binding_a, binding_b, dsn = pg_many
    root_a = Path(runtime.registry.load().registrations[binding_a].path)
    root_b = Path(runtime.registry.load().registrations[binding_b].path)
    quarantined = emit_stage(runtime, binding_a, "quarantined-before-drain")
    admin(runtime).remove(binding_a)
    dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w").tick()
    assert _row(dsn, quarantined)["quarantined"]
    with pytest.raises(OutboxDrainBlocked, match="quarantined=1"):
        drain_binding_outbox(vault_root=root_a, binding_id=binding_a)
    state = _row(dsn, quarantined)
    assert state["quarantined"] and not state["delivered"]

    ambiguous = emit_stage(runtime, binding_b, "ambiguous-before-drain")
    with psycopg.connect(dsn, autocommit=True) as conn:
        claim = claims.claim_next(conn, owner="crashed", vault_binding_id=binding_b,
                                  lease_seconds=30,
                                  topics=("knowledge_acquisition.stage.completed",))
        assert claim is not None and claim.row_id == ambiguous
        claim = claims.mark_effect_pending(conn, claim, {"contract": "older"})
        with pytest.raises(OutboxDrainBlocked, match="effect_pending=1"):
            drain_binding_outbox(vault_root=root_b, binding_id=binding_b)
        assert claims.mark_reconciliation_required(conn, claim, reason="probe")
    with pytest.raises(OutboxDrainBlocked, match="reconciliation_required=1"):
        drain_binding_outbox(vault_root=root_b, binding_id=binding_b)
    blocked = _row(dsn, ambiguous)
    assert blocked["phase"] == "effect_reconciliation_required" and not blocked["delivered"]
    assert ready_signals(dsn, "ambiguous-before-drain") == []


def test_drain_and_live_workers_share_one_claim_owner_per_row(pg_many, tmp_path, monkeypatch) -> None:
    """Regression (convergence re-review P1): a transfer/reactivation drain may run while
    many-binding workers are live, so it leases rows through the same claim protocol; and
    a worker blocks -- never quarantines -- the queue of a binding that is sealed."""

    from pathlib import Path

    from app.workers.outbox_worker import drain_binding_outbox

    runtime, binding_a, binding_b, dsn = pg_many
    root_a = Path(runtime.registry.load().registrations[binding_a].path)
    identities = [f"drain-race-{index}" for index in range(10)]
    rows_a = [emit_stage(runtime, binding_a, identity) for identity in identities]
    context = multiprocessing.get_context("spawn")
    log_path = tmp_path / "drain-race.jsonl"
    workers = [
        context.Process(
            target=race_worker,
            args=(dict(os.environ), str(runtime.layout.registry_path), str(runtime.ledger.root),
                  runtime.layout.channel_id, f"live-{index}", str(log_path), 200),
        )
        for index in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        receipt = drain_binding_outbox(vault_root=root_a, binding_id=binding_a)
    finally:
        for worker in workers:
            worker.join(timeout=100)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
    assert receipt["unsettled"] == 0
    for row_id in rows_a:
        state = _row(dsn, row_id)
        assert state["delivered"] and not state["quarantined"] and state["outcome"] == "applied"
    for identity in identities:
        # One effect per source row, whoever owned it (the drain or a live worker).
        assert len(ready_signals(dsn, identity)) == 1, identity
    if log_path.exists():
        starts: dict[str, int] = {}
        for line in log_path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["stage"] == "effect_pending":
                starts[event["row"]] = starts.get(event["row"], 0) + 1
        assert all(count == 1 for count in starts.values()), starts

    # A sealed binding (a removal crashed after its draining reservation) is blocked by
    # the worker: its pending rows stay pending, never quarantined, until it settles.
    sealed_row = emit_stage(runtime, binding_b, "sealed-binding")

    def crash(name: str) -> None:
        if name == "binding-removal:reserved":
            raise _Crash(name)

    monkeypatch.setattr("app.instance.binding_removal._fault_point", crash)
    with pytest.raises(_Crash):
        runtime.remove(binding_b)
    worker = dispatch.ManyBindingDispatcher(supervisor_for(runtime, "worker"), owner="w")
    for _ in range(2):
        worker.tick()
    held = _row(dsn, sealed_row)
    assert not held["quarantined"] and not held["delivered"]
