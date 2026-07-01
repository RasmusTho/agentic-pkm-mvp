"""EMBEDREL-06 AC 3/4/5 — index reconcile: converge, idempotent, resumable.

``index reconcile`` re-embeds any vector whose full identity differs from the
primary identity, upserting it in place under the primary identity. It must be:

- convergent: after reconcile a mixed index reports a single identity;
- idempotent: a second run on a converged index is a no-op;
- resumable / non-corrupting: interrupting mid-run leaves reconciled rows under
  the primary identity and un-reconciled rows under their prior identity — never
  a partial write, a deleted row, or a missing vector.

Requires a live Postgres backend; skipped when unavailable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from uuid import uuid4

import psycopg
import pytest
from click.testing import CliRunner

from app.cli import index_rebuild as reconcile_mod
from app.cli.index_rebuild import index as index_cli
from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.index import doctor as doctor_mod
from app.stores import pg as pg_store
from app.stores import reset_store_backends

pytestmark = pytest.mark.pg


PRIMARY = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)
FALLBACK = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)


def _dsn() -> str:
    return resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


class _StubClient:
    """Deterministic embedding client that can be made to fail after N calls."""

    def __init__(self, identity: EmbeddingIdentity, fail_after: int | None = None) -> None:
        self.identity = identity
        self._fail_after = fail_after
        self.calls = 0

    def embed_text(self, text: str) -> list[float]:
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise RuntimeError("simulated interruption mid-reconcile")
        # Stable non-degenerate vector at the primary dim.
        base = float(len(text) % 7 + 1)
        return [base, 0.5, 0.25, 0.125][: self.identity.dim]


@pytest.fixture()
def pg_env(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", _dsn())
    monkeypatch.setenv("STORE_BACKEND", "pg")
    reset_store_backends()
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    doctor_mod.reset_diagnose_cache()
    _set_primary_identity(PRIMARY)
    yield
    pg_store.truncate_pg_tables()
    reset_store_backends()
    doctor_mod.reset_diagnose_cache()


def _set_primary_identity(identity: EmbeddingIdentity) -> None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vector_index_meta (id, identity_json, updated_at)
                VALUES (1, %s, now())
                ON CONFLICT (id) DO UPDATE SET identity_json = EXCLUDED.identity_json, updated_at = now()
                """,
                (json.dumps(asdict(identity)),),
            )
        conn.commit()


def _seed_row(identity: EmbeddingIdentity, *, text: str) -> str:
    oid = uuid4()
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            # Seed the durable object of record so reconcile fetches authoritative text.
            cur.execute(
                """
                INSERT INTO store_objects (object_id, kind, source_ref, payload, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, now(), now())
                """,
                (oid, "note", "tests/reconcile", json.dumps({"text": text})),
            )
            cur.execute(
                """
                INSERT INTO store_vector_index (
                    object_id, kind, source_ref, payload, embedding,
                    dim, model, provider, normalize, updated_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, now())
                """,
                (
                    oid,
                    "note",
                    "tests/reconcile",
                    json.dumps({"text": text}),
                    [0.1, 0.2, 0.3, 0.4],
                    identity.dim,
                    identity.model,
                    identity.provider,
                    identity.normalize,
                ),
            )
        conn.commit()
    return str(oid)


def _identity_of(object_id: str) -> tuple:
    with psycopg.connect(_dsn(), row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, model, dim, normalize FROM store_vector_index WHERE object_id = %s",
                (object_id,),
            )
            row = cur.fetchone()
    assert row is not None, f"row {object_id} vanished during reconcile (corruption!)"
    return (row["provider"], row["model"], row["dim"], row["normalize"])


def _count_rows() -> int:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM store_vector_index")
            return int(cur.fetchone()[0])


def _install_client(monkeypatch, client) -> None:
    monkeypatch.setattr(reconcile_mod, "get_embedding_client", lambda *a, **k: client)


PRIMARY_TUPLE = (PRIMARY.provider, PRIMARY.model, PRIMARY.dim, PRIMARY.normalize)
FALLBACK_TUPLE = (FALLBACK.provider, FALLBACK.model, FALLBACK.dim, FALLBACK.normalize)


def test_reconcile_converges_idempotent_resumable(pg_env, monkeypatch):
    """Single test covering convergence, idempotency, and resumability (AC 3/4/5)."""
    # Seed a mixed index: 2 primary rows + 3 fallback rows, all at the same dim.
    primary_ids = [_seed_row(PRIMARY, text=f"primary-{i}") for i in range(2)]
    fallback_ids = [_seed_row(FALLBACK, text=f"fallback-{i}") for i in range(3)]
    total = len(primary_ids) + len(fallback_ids)
    assert _count_rows() == total

    runner = CliRunner()

    # --- Resumability: interrupt after the 2nd fallback re-embed. ---
    failing = _StubClient(PRIMARY, fail_after=2)
    _install_client(monkeypatch, failing)
    result = runner.invoke(index_cli, ["reconcile", "--backend", "pg", "--json"])
    assert result.exit_code == 0, result.output
    partial = json.loads(result.output)
    # 3 mismatched found; 2 reconciled before the simulated crash, 1 dead-lettered.
    assert partial["total_mismatched"] == 3
    assert partial["reconciled"] == 2
    assert partial["error_count"] == 1

    # No corruption: every seeded row still exists (no deletes, no missing vectors).
    assert _count_rows() == total
    for oid in primary_ids:
        assert _identity_of(oid) == PRIMARY_TUPLE
    reconciled_after_partial = [oid for oid in fallback_ids if _identity_of(oid) == PRIMARY_TUPLE]
    still_fallback = [oid for oid in fallback_ids if _identity_of(oid) == FALLBACK_TUPLE]
    assert len(reconciled_after_partial) == 2
    assert len(still_fallback) == 1  # the interrupted row retains its valid fallback identity

    # Doctor accurately reports the index is still mixed (2 identities remain).
    doctor_mod.reset_diagnose_cache()
    diag = doctor_mod.diagnose_index()
    assert diag["status"] == "error"
    assert len(diag["mixed_identities"]) == 2

    # --- Resume: a clean re-run converges the remaining fallback row. ---
    good = _StubClient(PRIMARY)
    _install_client(monkeypatch, good)
    result = runner.invoke(index_cli, ["reconcile", "--backend", "pg", "--json"])
    assert result.exit_code == 0, result.output
    resumed = json.loads(result.output)
    assert resumed["total_mismatched"] == 1
    assert resumed["reconciled"] == 1
    assert resumed["error_count"] == 0

    # Convergence: every row now carries the primary identity, none missing.
    assert _count_rows() == total
    for oid in primary_ids + fallback_ids:
        assert _identity_of(oid) == PRIMARY_TUPLE

    doctor_mod.reset_diagnose_cache()
    diag = doctor_mod.diagnose_index()
    assert diag["mixed_identities"] == []
    assert not any("Mixed embedding identities" in issue for issue in diag["issues"])

    # --- Idempotency: a third run on the converged index is a no-op. ---
    noop = _StubClient(PRIMARY)
    _install_client(monkeypatch, noop)
    result = runner.invoke(index_cli, ["reconcile", "--backend", "pg", "--json"])
    assert result.exit_code == 0, result.output
    again = json.loads(result.output)
    assert again["total_mismatched"] == 0
    assert again["reconciled"] == 0
    assert again["error_count"] == 0
    assert noop.calls == 0  # nothing re-embedded on a converged index


def test_reconcile_converges_mixed_index(pg_env, monkeypatch):
    """AC 3 (spec name): mixed index converges to status=ok after reconcile."""
    _seed_row(PRIMARY, text="primary")
    _seed_row(FALLBACK, text="fallback")
    _install_client(monkeypatch, _StubClient(PRIMARY))

    result = CliRunner().invoke(index_cli, ["reconcile", "--backend", "pg", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["reconciled"] == 1

    doctor_mod.reset_diagnose_cache()
    diag = doctor_mod.diagnose_index()
    assert diag["mixed_identities"] == []


def test_reconcile_idempotent_on_clean_index(pg_env, monkeypatch):
    """AC 4 (spec name): reconcile on a single-identity index is a no-op both runs."""
    _seed_row(PRIMARY, text="primary-a")
    _seed_row(PRIMARY, text="primary-b")
    client = _StubClient(PRIMARY)
    _install_client(monkeypatch, client)

    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(index_cli, ["reconcile", "--backend", "pg", "--json"])
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["total_mismatched"] == 0
        assert summary["reconciled"] == 0
        assert summary["error_count"] == 0
    assert client.calls == 0


def test_reconcile_dry_run_counts_without_writing(pg_env, monkeypatch):
    """--dry-run reports the mismatch count without re-embedding."""
    _seed_row(PRIMARY, text="primary")
    fb = _seed_row(FALLBACK, text="fallback")
    client = _StubClient(PRIMARY)
    _install_client(monkeypatch, client)

    result = CliRunner().invoke(index_cli, ["reconcile", "--backend", "pg", "--json", "--dry-run"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["total_mismatched"] == 1
    assert summary["reconciled"] == 0
    assert client.calls == 0
    # The fallback row is untouched by a dry run.
    assert _identity_of(fb) == FALLBACK_TUPLE
