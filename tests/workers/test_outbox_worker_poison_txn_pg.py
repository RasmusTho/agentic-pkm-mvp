"""Real-Postgres atomicity of the poison-path bookkeeping (#3930).

Ground truth for what the fake-conn tests in
``tests/workers/test_outbox_worker_poison_txn.py`` model: against a live
migrated database, a crash injected between the poison-path statements must
leave NO partial durable state (the bump, the dead-letter audit row, and the
ack are one transaction), and the recovery run must dead-letter exactly once.

Scratch-database fixture mirrors
``tests/services/test_outbox_bootstrap_assert_only.py``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.workers import outbox_worker

pytestmark = pytest.mark.pg

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    """A throwaway database at `alembic upgrade head`, wired into DATABASE_URL."""
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_outbox_poisontxn_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    # An earlier migration declares `embedding VECTOR`, so pgvector must exist.
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _run_one_tick() -> None:
    outbox_worker.run(
        interval=0.0,
        heartbeat_interval=9999,
        log_heartbeat_interval=None,
        stop_after_ticks=1,
    )


def test_poison_bookkeeping_atomic_pg(
    scratch_db: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Crash between poison-path statements => full rollback; recovery => exactly once."""
    from app.events.models import new_event
    from app.services import outbox as outbox_service

    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", "1")
    monkeypatch.setattr(outbox_worker, "write_worker_heartbeat", lambda **_: None)

    payload = {"vault_path": "x.md", "relative_path": "x.md", "mtime": 1.0, "hash": "h"}
    event = new_event(event_type="ingest.vault.changed", payload=payload, trace_id="trace-pg")
    key = outbox_service.derive_idempotency_key(
        "ingest.vault.changed", "x.md", outbox_service.payload_fingerprint(payload)
    )
    row_id = outbox_service.write_outbox_event(event, idempotency_key=key)
    assert row_id

    def _permanent_failure(*_a: Any, **_k: Any) -> None:
        raise ValueError("permanent poison payload")

    monkeypatch.setattr(outbox_worker, "_dispatch_topic", _permanent_failure)

    real_ack = outbox_worker.ack_outbox

    def _crash_after_ack(*args: Any, **kwargs: Any) -> Any:
        real_ack(*args, **kwargs)
        raise RuntimeError("injected crash before commit")

    monkeypatch.setattr(outbox_worker, "ack_outbox", _crash_after_ack)
    outbox_worker._EVENT_DEDUP._seen.clear()

    with pytest.raises(RuntimeError, match="injected crash before commit"):
        _run_one_tick()

    # Ground truth after the crash: the whole cycle rolled back. No stranded
    # attempts bookkeeping, no ack, no dead-letter audit row.
    with psycopg.connect(scratch_db) as conn:
        row = conn.execute(
            "select attempts, delivered_at from outbox where id = %s", (row_id,)
        ).fetchone()
        assert row == (0, None)
        dl_count = conn.execute(
            "select count(*) from outbox where topic = %s",
            (outbox_worker.OUTBOX_EVENT_DEAD_LETTERED,),
        ).fetchone()
        assert dl_count == (0,)

    # Recovery run (supervised restart): the row dead-letters exactly once.
    monkeypatch.setattr(outbox_worker, "ack_outbox", real_ack)
    outbox_worker._EVENT_DEDUP._seen.clear()
    _run_one_tick()

    with psycopg.connect(scratch_db) as conn:
        row = conn.execute(
            "select attempts, delivered_at from outbox where id = %s", (row_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] is not None
        dl_rows = conn.execute(
            "select payload from outbox where topic = %s",
            (outbox_worker.OUTBOX_EVENT_DEAD_LETTERED,),
        ).fetchall()
        assert len(dl_rows) == 1
        stored = dl_rows[0][0]
        assert stored["payload"]["outbox_id"] == str(row_id)
        assert stored["payload"]["attempts"] == 1
        assert stored["payload"]["reason"] == "dispatch_failed:ValueError"
