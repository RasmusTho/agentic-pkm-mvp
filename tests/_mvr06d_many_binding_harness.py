"""Shared MVR-06D harness: production activation, many-binding enrollment, and queue drive.

Every state transition is produced by a shipped producer: the MVR-06B handoff harness, the
``background-many-binding-activate`` CLI inside a proved stopped window, the governed
background-intent admin service, owner-native ``production_register``, and the real
knowledge-acquisition stage producer emitting inside a binding's effect window. Queue
rows are only ever written by ``write_outbox_event``; nothing here seeds the registry,
intent, ledger, or outbox state machine directly.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
import pytest

from app.instance.background_supervisor import (
    BackgroundLifecycleSupervisor,
    stored_intent,
)
from app.instance.runtime import _finish_instance_state_deployment
from tests._mvr06_background_harness import cli
from tests._mvr06b_handoff_harness import admin, mvr06b_instance
from tests._mvr06c_relocation_harness import initialized_registration
from tests._mvr_default_vault_harness import deployment_authority

CLAIM_HEAD = "fa06d0c00001"
PRE_CLAIM_HEAD = "c9d0e1f2a3b4"


def stopped_window_cli(runtime, command: str, *extra: str) -> dict:
    """Run one shipped instance-state command inside a proved stopped deployment window."""

    legacy_path = runtime.layout.root / "missing-legacy.md"
    proof, inventory_path = deployment_authority(runtime, legacy_path)
    args = [
        command,
        "--channel",
        runtime.layout.channel_id,
        "--registry-path",
        str(runtime.layout.registry_path),
        "--host-global-root",
        str(runtime.ledger.root),
        "--quiescence-proof-path",
        str(runtime.ledger.root / "deployment-quiescence-proof.json"),
        "--consumer",
        "bootstrap-init",
        *extra,
    ]
    try:
        return cli(*args)
    finally:
        _finish_instance_state_deployment(
            channel=runtime.layout.channel_id,
            instance_state_root=runtime.layout.root.parent,
            host_global_root=runtime.ledger.root,
            legacy_path=legacy_path,
            inventory_path=inventory_path,
            backup_root=runtime.layout.root / f"backup-{uuid.uuid4().hex[:6]}",
            restore_root=None,
            quiescence_proof=proof,
        )


def activate_many_binding(runtime) -> dict:
    receipt = stopped_window_cli(runtime, "background-many-binding-activate")
    return receipt


def supervisor_for(runtime, consumer: str) -> BackgroundLifecycleSupervisor:
    return BackgroundLifecycleSupervisor.for_runtime(
        registry_path=runtime.layout.registry_path,
        ownership_root=runtime.ledger.root,
        channel_id=runtime.layout.channel_id,
        consumer=consumer,
    )


def enroll_exactly(runtime, binding_ids: tuple[str, ...]) -> None:
    """Governed explicit intent of exactly ``binding_ids`` (production admin service)."""

    service = admin(runtime)
    for binding in binding_ids:
        service.add(binding)
    for member in stored_intent(runtime.registry.load()).effective_binding_ids():
        if member not in binding_ids:
            service.remove(member)


def many_binding_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    enroll: bool = True,
    dsn: str | None = None,
):
    """MVR-06B instance -> MVR-06D activation -> explicit {A, B} on two initialized vaults.

    With ``dsn`` the process uses that migrated PostgreSQL before activation, so the
    activation gate classifies the real outbox and every later row is durable.
    """

    runtime, first, extra = mvr06b_instance(tmp_path, monkeypatch)
    if dsn is not None:
        use_database(monkeypatch, dsn)
    receipt = activate_many_binding(runtime)
    assert receipt["_exit_code"] == 0, receipt
    a = initialized_registration(runtime, tmp_path / "alpha")
    b = initialized_registration(runtime, tmp_path / "beta")
    if enroll:
        enroll_exactly(runtime, (a.vault_binding_id, b.vault_binding_id))
    return runtime, a, b, (first, *extra)


# -- PostgreSQL ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    raw = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if not raw:
        # The MVR-06D claim contract is never skipped: no PostgreSQL is an error.
        pytest.fail("MVR-06D claim tests require PostgreSQL (DATABASE_URL/DB_DSN)")
    return resolve_dsn(raw)


def upgrade(dsn: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", dsn)
    previous = {name: os.environ.get(name) for name in ("DATABASE_URL", "DB_DSN")}
    os.environ["DATABASE_URL"] = dsn
    os.environ["DB_DSN"] = dsn
    try:
        command.upgrade(config, revision)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def scratch_database(revision: str = "head") -> Iterator[str]:
    admin_dsn = _admin_dsn()
    name = f"scratch_mvr06d_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        upgrade(dsn, revision)
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def use_database(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")


def rows(dsn: str, sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def emit_stage(runtime, binding_id: str, identity: str, *, stage: str = "candidate") -> str:
    """The real KA-06 producer, emitting inside ``binding_id``'s effect window."""

    from app.instance.scalar_binding_runtime import (
        background_effect_runtime,
        frozen_binding_effect,
    )
    from app.knowledge_acquisition.stage_events import emit_stage_completed

    producer = supervisor_for(runtime, "producer")
    producer.start_all()
    with producer.effect(binding_id) as lifecycle:
        with frozen_binding_effect(background_effect_runtime(producer, lifecycle)):
            row_id = emit_stage_completed(
                stage=stage, stage_version=1, content_identity=identity
            )
    assert row_id, "the stage producer deduplicated a fresh emission"
    return row_id


def ready_signals(dsn: str, identity: str) -> list[tuple]:
    """The admitted handler's durable store effect: consumer-signal rows per identity."""

    return rows(
        dsn,
        "select id, vault_binding_id from outbox where topic = "
        "'knowledge_acquisition.candidate.ready_for_triage' "
        "and payload #>> '{payload,content_identity}' = %s",
        (identity,),
    )


__all__ = [
    "CLAIM_HEAD",
    "PRE_CLAIM_HEAD",
    "activate_many_binding",
    "emit_stage",
    "enroll_exactly",
    "many_binding_instance",
    "ready_signals",
    "rows",
    "scratch_database",
    "stopped_window_cli",
    "supervisor_for",
    "upgrade",
    "use_database",
]


def race_worker(env: dict[str, str], registry_path: str, ownership_root: str, channel: str,
                owner: str, log_path: str, max_ticks: int) -> None:
    """One independent production worker process racing the claim/dispatch/ack path.

    Spawned (not forked) with the parent's environment; it builds its own supervisor and
    dispatcher exactly like a worker container and records each claim's effect window.
    """

    import json as _json
    import time as _time

    os.environ.clear()
    os.environ.update(env)
    from app.workers import many_binding_dispatch as dispatch

    def record(stage: str, claim=None) -> None:
        if claim is None:
            return
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(_json.dumps({
                "stage": stage, "row": claim.row_id, "token": claim.token,
                "owner": owner, "t": _time.monotonic(),
            }) + "\n")
        if stage == "effect_pending":
            _time.sleep(0.02)  # widen the window a second owner would have to hit

    dispatch._claim_fault_point = record  # type: ignore[assignment]
    supervisor = BackgroundLifecycleSupervisor.for_runtime(
        registry_path=Path(registry_path),
        ownership_root=Path(ownership_root),
        channel_id=channel,
        consumer="worker",
    )
    dispatcher = dispatch.ManyBindingDispatcher(supervisor, owner=owner)
    idle = 0
    for _ in range(max_ticks):
        tick = dispatcher.tick()
        idle = idle + 1 if tick.processed == 0 else 0
        if idle >= 3:
            return
