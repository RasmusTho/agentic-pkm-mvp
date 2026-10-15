"""Phase A (EMBEDREL-06) — per-vector identity columns and fallback upsert guard.

Covers issue #2442:
- store_vector_index records the full (provider, model, dim, normalize) identity
  for every pg vector upsert.
- existing rows missing provider/normalize are backfilled from vector_index_meta.
- a reconcilable fallback write (same dim, different provider/model/normalize)
  succeeds and records the fallback identity per-row while the primary index
  identity in vector_index_meta stays stable.
- a dim mismatch still fails loud and writes no row (fallback or ordinary).
- ordinary (non-reconcilable) provider/model/normalize drift still fails loud.

These tests require a live Postgres backend; they are skipped under `not pg`.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app.components.embeddings import EmbeddingIdentity
from app.db.dsn import resolve_dsn
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.stores import pg as pg_store

pytestmark = pytest.mark.pg


PRIMARY = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=4, normalize=True)
FALLBACK = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=4, normalize=True)


def _dsn() -> str:
    return resolve_dsn()


def _pg_available() -> bool:
    try:
        conn = psycopg.connect(_dsn(), connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _pg_index(monkeypatch):
    if not _pg_available():
        pytest.skip("Postgres backend not available")
    monkeypatch.setenv("DATABASE_URL", _dsn())
    # Force schema (re)creation against this DSN and start from a clean index.
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    pg_store.truncate_pg_tables()
    index = pg_store.PgVectorIndex()
    yield index
    pg_store.truncate_pg_tables()


def _row(object_id):
    with psycopg.connect(_dsn(), row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, model, dim, normalize FROM store_vector_index WHERE object_id = %s",
                (object_id,),
            )
            return cur.fetchone()


def _count(object_id) -> int:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM store_vector_index WHERE object_id = %s", (object_id,))
            return int(cur.fetchone()[0])


@pytest.mark.parametrize("mode", ["replace", "retire", "existing", "write-failure", "source-race", "row-race", "history", "identity", "retire-source-race", "reverse-identity", "cross-key-alias", "replace-source-alias", "retire-source-alias"])
def test_legacy_source_reconciliation_is_atomic_and_never_overwrites(_pg_index, monkeypatch, mode):
    from copy import deepcopy
    from app.rebuildability.product_total_loss import product_replay_provenance
    store = pg_store.PgObjectStore()
    oid, other = uuid4(), uuid4()
    legacy = {"content": "canonical body"}
    store.put(oid, kind="note", source_ref="source.md", payload=legacy)
    store.put(other, kind="note", source_ref="other.md", payload={"text": "preserved"})
    expected = dict(store.get(oid))
    original = deepcopy(expected)
    source_uuid = uuid4() if mode == "cross-key-alias" else oid
    retained_uuid = uuid4() if mode == "reverse-identity" else source_uuid
    # The identity seam is production SQL, not a mocked resolver.
    from app.db.db import ensure_schema
    with psycopg.connect(_dsn()) as conn:
        ensure_schema(conn)
        conn.execute("INSERT INTO objects (id, uuid, vault_binding_id, kind) VALUES (%s, %s, %s, 'note')",
                     (other if mode == "identity" else oid, retained_uuid, store.vault_binding_id))
    if mode == "cross-key-alias":
        store.put(source_uuid, kind="note", source_ref="unrelated-alias.md", payload={"text": "preserved alias"})
    from pathlib import Path
    from app.rebuildability.legacy_source import assert_unique_projection_source
    source_root = Path("/synthetic-issue6096-vault")
    alias_id = uuid4()
    if mode.endswith("source-alias"):
        store.put(alias_id, kind="note", source_ref=str(source_root / "source.md"), payload={"text": "preserved alias"})
    replacement = dict(frontmatter={}, text="canonical body", origin="vault", trust="human", review_state="reviewed",
        replay=product_replay_provenance(source_identity="source.md", source_text="canonical body"))
    vector = dict(kind="note", source_ref="source.md", payload={"text": "canonical body"},
                  embedding=[1., 0., 0., 0.], model=PRIMARY.model, identity=PRIMARY)
    if mode == "existing":
        _pg_index.upsert(oid, **vector)
    if mode.endswith("source-alias"):
        _pg_index.upsert(alias_id, **{**vector, "source_ref": str(source_root / "source.md")})
    if mode == "row-race":
        store.put(oid, kind="note", source_ref="source.md", payload={"text": "racing state"})
    if mode == "history":
        with psycopg.connect(_dsn()) as conn:
            conn.execute("INSERT INTO decisions (object_id, vault_binding_id, key, value) VALUES (%s, %s, 'receipt', '{}')",
                         (oid, store.vault_binding_id))
    calls = []

    def revalidate():
        calls.append(True)
        if mode in ("source-race", "retire-source-race") and len(calls) == 2:
            raise ValueError("changed source after write")

    if mode == "write-failure":
        monkeypatch.setattr(pg_store.PgVectorIndex, "upsert", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed insert")))
    retiring = mode in ("retire", "history", "retire-source-race", "retire-source-alias")
    kwargs = dict(vault_uuid=str(source_uuid), revalidate=revalidate,
                  check_sources=lambda rows: assert_unique_projection_source(rows, expected_id=str(oid),
                      root=source_root, source_identity="source.md", vault_uuid=str(source_uuid)),
                  replacement=None if retiring else replacement, vector=None if retiring else vector)
    if mode in ("replace", "retire"):
        store.reconcile_legacy_source(expected, **kwargs)
        assert store.get(oid) is None if retiring else store.get(oid)["payload"] == replacement
        assert _count(oid) == (0 if retiring else 1)
        with pytest.raises(ValueError):
            store.reconcile_legacy_source(expected, **kwargs)
    else:
        before = store.get(oid)
        with pytest.raises((RuntimeError, ValueError)):
            store.reconcile_legacy_source(expected, **kwargs)
        assert store.get(oid) == before
        assert _count(oid) == (1 if mode == "existing" else 0)
    assert store.get(other)["payload"] == {"text": "preserved"}
    if mode == "existing":
        assert store.get(oid) == original
        assert _row(oid)["model"] == PRIMARY.model
    if mode == "history":
        with psycopg.connect(_dsn()) as conn:
            assert conn.execute("SELECT object_id FROM decisions WHERE key = 'receipt' AND object_id = %s", (oid,)).fetchone()[0] == oid
    if mode.endswith("source-alias"):
        assert store.get(alias_id)["payload"] == {"text": "preserved alias"}
        assert _count(alias_id) == 1


@pytest.mark.parametrize("mode", ["replace", "retire", "existing", "policy-race", "write-failure"])
@pytest.mark.parametrize("producer_kind", ["filesystem", "registry"])
def test_legacy_producer_policy_reconciliation_is_atomic_and_never_overwrites(_pg_index, monkeypatch, tmp_path, mode, producer_kind):
    from types import SimpleNamespace
    from tests.cli.test_index_rebuild_cli import _legacy_source_fixture
    from app.db.db import ensure_schema
    recovery, state, root, source, raw, original, _, _, _ = _legacy_source_fixture(monkeypatch, tmp_path)
    monkeypatch.setenv("FS_WATCHER_ENABLE", "0" if mode == "retire" else "1")
    monkeypatch.setenv("VAULT_DIR", str(root))
    if producer_kind == "registry":
        from tests.rebuildability.test_legacy_source_reconciliation import _enable_registry
        _enable_registry(monkeypatch, root)
        monkeypatch.setenv("FS_WATCHER_ENABLE", "0")
        if mode == "retire":
            monkeypatch.setenv("WATCHER_ENABLE", "0")
    store, index = pg_store.PgObjectStore(), _pg_index
    oid, other = original["object_id"], uuid4()
    store.put(oid, kind="note", source_ref=str(source), payload=original["payload"])
    store.put(other, kind="note", source_ref="unrelated", payload={"text": "preserved"})
    with psycopg.connect(_dsn()) as conn:
        ensure_schema(conn)
        conn.execute("INSERT INTO objects (id, uuid, vault_binding_id, kind) VALUES (%s, %s, %s, 'note')",
                     (oid, oid, store.vault_binding_id))
    vector = dict(kind="note", source_ref="unrelated", payload={"text": "preserved"},
                  embedding=[1., 0., 0., 0.], model=PRIMARY.model, identity=PRIMARY)
    index.upsert(other, **vector)
    if mode == "existing":
        index.upsert(oid, **{**vector, "source_ref": str(source)})
    before = store.get(oid)
    if mode == "policy-race":
        original_reconcile = store.reconcile_legacy_source
        def reconcile(expected, **kwargs):
            revalidate = kwargs["revalidate"]
            calls = 0
            def raced():
                nonlocal calls
                calls += 1
                if calls == 2:
                    monkeypatch.setenv("WATCHER_ENABLE" if producer_kind == "registry" else "FS_WATCHER_ENABLE", "0")
                revalidate()
            original_reconcile(expected, **{**kwargs, "revalidate": raced})
        monkeypatch.setattr(store, "reconcile_legacy_source", reconcile)
    if mode == "write-failure":
        monkeypatch.setattr(pg_store.PgVectorIndex, "upsert", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private-write-canary")))
    factory = lambda **kwargs: SimpleNamespace(identity=PRIMARY, embed_text=lambda _: [1., 0., 0., 0.])
    binding = SimpleNamespace(backend="pg", store=store)
    if mode in {"policy-race", "write-failure"}:
        with pytest.raises(recovery.LegacySourceRefusal) as caught:
            recovery.reconcile_legacy_sources(binding, index, factory)
        assert caught.value.reason == ("legacy_producer_policy_refused" if mode == "policy-race" else "legacy_write_failed")
        assert store.get(oid) == before and _count(oid) == 0
    else:
        assert recovery.reconcile_legacy_sources(binding, index, factory) == (0 if mode == "existing" else 1)
        if mode == "retire":
            assert store.get(oid) is None and _count(oid) == 0
        elif mode == "existing":
            assert store.get(oid) == before and _count(oid) == 1
        else:
            assert store.get(oid)["payload"]["frontmatter"]["trust"] == "human" and _count(oid) == 1
    assert store.get(other)["payload"] == {"text": "preserved"}
    assert _row(other)["model"] == PRIMARY.model and _count(other) == 1
    assert source.read_bytes() == raw


def test_upsert_records_full_identity_columns(_pg_index):
    index = _pg_index
    oid = uuid4()
    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    row = _row(oid)
    assert row is not None
    assert row["provider"] == PRIMARY.provider
    assert row["model"] == PRIMARY.model
    assert row["dim"] == PRIMARY.dim
    assert row["normalize"] == PRIMARY.normalize


def test_identity_columns_backfill_from_index_meta(_pg_index):
    index = _pg_index
    oid = uuid4()
    # Seed a row with the primary identity, then simulate a pre-migration row by
    # nulling its provider/normalize columns (model/dim predate this slice).
    index.upsert(
        object_id=oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "alpha"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE store_vector_index SET provider = NULL, normalize = NULL "
                "WHERE vault_binding_id = %s AND object_id = %s",
                (COMPATIBILITY_BINDING_ID, oid),
            )
        conn.commit()

    before = _row(oid)
    assert before["provider"] is None and before["normalize"] is None
    # dim/model/embedding must be preserved by the backfill.
    assert before["model"] == PRIMARY.model and before["dim"] == PRIMARY.dim

    # Re-run the migration/backfill (idempotent) — provider/normalize fill from meta.
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()

    after = _row(oid)
    assert after["provider"] == PRIMARY.provider
    assert after["normalize"] == PRIMARY.normalize
    assert after["model"] == PRIMARY.model
    assert after["dim"] == PRIMARY.dim
    assert _count(oid) == 1  # object id unchanged, no duplicate row

    # Second backfill run is a no-op (idempotent / safe on already-migrated db).
    pg_store._TABLES_READY = False
    pg_store._ensure_tables()
    assert _row(oid) == after


def test_reconcilable_fallback_identity_write_preserves_primary_identity(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    fallback_oid = uuid4()
    # Establish the primary index identity.
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )
    # A reconcilable fallback write under a different provider/model succeeds.
    index.upsert(
        object_id=fallback_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "fallback"},
        embedding=[0.0, 1.0, 0.0, 0.0],
        model=FALLBACK.model,
        identity=FALLBACK,
        reconcilable_fallback=True,
    )

    fallback_row = _row(fallback_oid)
    assert fallback_row["provider"] == FALLBACK.provider
    assert fallback_row["model"] == FALLBACK.model
    assert fallback_row["dim"] == FALLBACK.dim
    assert fallback_row["normalize"] == FALLBACK.normalize

    # Primary row identity is unchanged.
    primary_row = _row(primary_oid)
    assert primary_row["provider"] == PRIMARY.provider
    assert primary_row["model"] == PRIMARY.model

    # The index-level (primary) identity in vector_index_meta is still PRIMARY.
    stored_primary = index.get_identity()
    assert stored_primary == PRIMARY


def test_dimension_mismatch_still_refuses_fallback_write(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )

    wrong_dim = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=3, normalize=True)
    fallback_oid = uuid4()
    # Even flagged reconcilable, a dim mismatch must fail loud and write nothing.
    with pytest.raises((ValueError, RuntimeError)):
        index.upsert(
            object_id=fallback_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "fallback"},
            embedding=[0.0, 1.0, 0.0],
            model=wrong_dim.model,
            identity=wrong_dim,
            reconcilable_fallback=True,
        )
    assert _count(fallback_oid) == 0

    # An ordinary (non-fallback) dim mismatch also fails and writes nothing.
    ordinary_oid = uuid4()
    with pytest.raises((ValueError, RuntimeError)):
        index.upsert(
            object_id=ordinary_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "ordinary"},
            embedding=[0.0, 1.0, 0.0],
            model=wrong_dim.model,
            identity=wrong_dim,
        )
    assert _count(ordinary_oid) == 0


def test_non_reconcilable_identity_drift_still_fails(_pg_index):
    index = pg_store.PgVectorIndex()
    primary_oid = uuid4()
    index.upsert(
        object_id=primary_oid,
        kind="note",
        source_ref="unit-test",
        payload={"text": "primary"},
        embedding=[1.0, 0.0, 0.0, 0.0],
        model=PRIMARY.model,
        identity=PRIMARY,
    )

    drift_oid = uuid4()
    # Same dim, different provider/model, but NOT flagged reconcilable → fail loud.
    with pytest.raises(RuntimeError):
        index.upsert(
            object_id=drift_oid,
            kind="note",
            source_ref="unit-test",
            payload={"text": "drift"},
            embedding=[0.0, 1.0, 0.0, 0.0],
            model=FALLBACK.model,
            identity=FALLBACK,
        )
    assert _count(drift_oid) == 0
