"""MVR-05D rollout preflight: no worker activates over upgrade-stranded pending rows."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.events.models import new_event
from app.services import outbox_envelope_preflight as preflight
from app.services.outbox import derive_idempotency_key, write_outbox_event
from app.workers import outbox_worker

STAMP = {
    "vault_binding_id": "binding-a",
    "binding_authority": "allow",
    "binding_authorization_epoch": "epoch-a",
    "binding_revision": 7,
    "vault_root": "/vault/a",
}


class _CountConn:
    def __init__(self, count: int) -> None:
        self.count = count
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))
        return SimpleNamespace(fetchone=lambda: (self.count,))

    def close(self) -> None:
        return None


@pytest.mark.not_pg
def test_worker_refuses_activation_over_upgrade_stranded_rows(tmp_path, monkeypatch) -> None:
    assert preflight.evaluate(None, None)["status"] == "skipped"
    clean = _CountConn(0)
    assert preflight.require_upgrade_drained(STAMP, conn=clean)["status"] == "ok"
    sql, params = clean.statements[0]
    assert sql.lower().lstrip().startswith("select count(*)")
    assert params[:2] == ("binding-a", "binding-a") and params[-1] == "mvr05.outbox-envelope.v1"
    with pytest.raises(preflight.OutboxEnvelopeUpgradeBlocked, match="2 pending live-binding"):
        preflight.require_upgrade_drained(STAMP, conn=_CountConn(2))

    # The production worker entry point runs the gate after bootstrap and
    # before its first poll; a blocked gate stops the process loudly.
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(root))
    runtime = SimpleNamespace(
        vault_binding_id="binding-a",
        authority="allow",
        authorization_epoch="epoch-a",
        binding_revision=7,
        root=root,
    )
    monkeypatch.setattr(outbox_worker, "bootstrap", lambda: None)
    monkeypatch.setattr(outbox_worker, "resolve_scalar_binding_runtime", lambda **_: runtime)
    seen: list[dict] = []

    def blocked(stamp):
        seen.append(dict(stamp))
        raise preflight.OutboxEnvelopeUpgradeBlocked(1)

    monkeypatch.setattr(outbox_worker, "require_upgrade_drained", blocked)
    monkeypatch.setattr(
        outbox_worker, "poll_outbox_one", lambda **_: pytest.fail("worker polled before the gate")
    )
    with pytest.raises(preflight.OutboxEnvelopeUpgradeBlocked):
        outbox_worker.run(stop_after_ticks=1, startup_retries=1)
    assert seen == [{**STAMP, "vault_root": str(root)}]

    # A transient failure to evaluate the gate is not a refusal: the worker
    # proceeds to its loop, which re-resolves and degrades as before.
    def transient(_stamp):
        raise RuntimeError("registry briefly unavailable")

    class _PastTheGate(Exception):
        pass

    def past_gate():
        raise _PastTheGate

    monkeypatch.setattr(outbox_worker, "require_upgrade_drained", transient)
    monkeypatch.setattr(outbox_worker, "resolve_worker_heartbeat_path", past_gate)
    with pytest.raises(_PastTheGate):
        outbox_worker.run(stop_after_ticks=1, startup_retries=1)


@pytest.mark.pg
def test_preflight_counts_only_rows_the_previous_worker_could_dispatch(monkeypatch) -> None:
    from tests.services.test_multi_vault_outbox_idempotency import _isolated_outbox

    def stamped(**changes):
        return new_event(
            event_type="mvr05d.preflight", payload={}, meta={**STAMP, **changes}
        ).model_dump_json()

    with _isolated_outbox(monkeypatch) as conn:
        assert preflight.evaluate(conn, STAMP)["status"] == "ok"
        # A complete-envelope row from the production choke point is compatible.
        write_outbox_event(
            new_event(event_type="mvr05d.preflight", payload={"n": 1}, meta=dict(STAMP)),
            conn,
            idempotency_key=derive_idempotency_key("mvr05d.preflight", "n", "1"),
            vault_binding_id="binding-a",
            producer="ingest.vault_sync",
        )
        rows = [
            ("binding-a", stamped(), "NULL"),  # pending, live 05A stamp: stranded by upgrade
            ("binding-a", stamped(), "now()"),  # delivered: drained
            ("binding-a", stamped(binding_revision=6), "NULL"),  # stale: old worker cannot drain
            ("binding-b", stamped(vault_binding_id="binding-b"), "NULL"),  # foreign binding
            ("explicitly-global", stamped(), "NULL"),
            ("legacy-compatibility-binding", stamped(), "NULL"),
        ]
        for binding, payload, delivered in rows:
            conn.execute(
                "INSERT INTO outbox (id, legacy_key, vault_binding_id, topic, payload, delivered_at) "
                f"VALUES (%s, %s, %s, 'mvr05d.preflight', %s::jsonb, {delivered})",
                (uuid4(), uuid4(), binding, payload),
            )
        assert preflight.evaluate(conn, STAMP) == {
            "schema": preflight.PREFLIGHT_SCHEMA,
            "status": "blocked",
            "upgrade_stranded_pending_count": 1,
        }
        with pytest.raises(preflight.OutboxEnvelopeUpgradeBlocked):
            preflight.require_upgrade_drained(STAMP, conn=conn)
        conn.execute(
            "UPDATE outbox SET delivered_at = now() WHERE vault_binding_id = 'binding-a' "
            "AND payload #>> '{meta,outbox_envelope}' IS NULL "
            "AND payload #>> '{meta,binding_revision}' = '7'"
        )
        assert preflight.evaluate(conn, STAMP)["status"] == "ok"

