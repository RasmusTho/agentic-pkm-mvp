from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.db.dsn import resolve_dsn
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app import objects as legacy_store
from app.objects import DomainObject, ObjectStore
from app.stores import get_vector_index, reset_store_backends


def _missing_repair_fixture(monkeypatch):
    """Run the production ObjectStore consumer and PG insert SQL against a tiny DB double."""
    from contextlib import nullcontext
    from dataclasses import asdict
    from types import SimpleNamespace
    from app.cli import index_rebuild as repair
    from app.components.embeddings import EmbeddingIdentity
    from app.rebuildability.product_total_loss import product_replay_provenance
    from app.stores import pg

    identity = EmbeddingIdentity(provider="mock", model="selected-model", dim=2, normalize=False)
    payload = dict(content="canonical body", text="stale alias", origin="vault",
                   trust="unreviewed", review_state="provisional", episode_ref="unbound",
                   replay=product_replay_provenance(source_identity="outside.md", source_text="canonical body"))
    row = dict(object_id=uuid4(), kind="note", source_ref="outside.md", payload=payload)
    state = SimpleNamespace(rows=[row], vectors={}, embedded=[], statements=[], fail=None)

    class Cursor:
        result = None

        def execute(self, statement, params):
            state.statements.append(statement)
            if "SELECT object_id FROM store_vector_index" in statement:
                self.result = [dict(object_id=key) for key in state.vectors]
            elif "SELECT kind, source_ref, payload" in statement:
                self.result = {key: row[key] for key in ("kind", "source_ref", "payload")}
                if state.fail == "stale":
                    self.result = {**self.result, "payload": {"content": "changed"}}
            elif "SELECT identity_json" in statement:
                self.result = dict(identity_json=json.dumps(asdict(identity)))
            elif "INSERT INTO store_vector_index" in statement:
                if state.fail == "write":
                    raise RuntimeError("private provider canary")
                assert "DO NOTHING" in statement and "DO UPDATE" not in statement
                state.vectors.setdefault(str(params[1]), params)
            else:
                raise AssertionError(statement)

        def fetchone(self):
            return self.result

        def fetchall(self):
            return self.result

    cursor = Cursor()
    monkeypatch.setattr(pg, "_ensure_tables", lambda: None)
    monkeypatch.setattr(pg, "_connect", lambda: nullcontext(SimpleNamespace(cursor=lambda: nullcontext(cursor))))
    index = pg.PgVectorIndex()
    binding = SimpleNamespace(backend="pg", store=SimpleNamespace(
        vault_binding_id=index.vault_binding_id, list_objects=lambda **kwargs: state.rows))
    monkeypatch.setattr(repair.domain_objects, "resolve_object_store_port", lambda: binding)
    monkeypatch.setattr(repair, "get_vector_index", lambda: index)

    def embed(text):
        state.embedded.append(text)
        if state.fail == "embed":
            raise RuntimeError("private provider canary")
        if state.fail == "race":
            state.vectors[str(row["object_id"])] = "racing winner"
        return [1.0, 2.0]

    monkeypatch.setattr(repair, "get_product_embedding_client", lambda **kwargs: SimpleNamespace(
        identity=identity, embed_text=embed))
    return repair, state, identity


def test_missing_only_repair_never_overwrites_existing_vectors(monkeypatch):
    import copy
    repair, state, identity = _missing_repair_fixture(monkeypatch)
    original = copy.deepcopy(state.rows)
    old_id = str(uuid4())
    state.vectors[old_id] = "preserved"
    state.rows.append({**state.rows[0], "object_id": old_id, "payload": {"content": "existing"}})
    assert repair.repair_missing_vectors() == 1
    assert state.vectors[old_id] == "preserved"
    assert state.rows[0] == original[0]
    assert state.embedded == ["canonical body"]
    inserted = state.vectors[str(state.rows[0]["object_id"])]
    assert inserted[7:10] == (identity.model, identity.provider, identity.normalize)
    projected = json.loads(inserted[4])
    assert projected["text"] == projected["content"] == "canonical body"
    assert projected["replay"] == original[0]["payload"]["replay"]
    assert projected["trust"] == "unreviewed"
    assert repair.repair_missing_vectors() == 0
    assert state.embedded == ["canonical body"]


@pytest.mark.parametrize("failure", ["embed", "write", "stale", "race"])
def test_missing_only_repair_atomic_or_absent(monkeypatch, failure):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    state.fail = failure
    if failure == "race":
        repair.repair_missing_vectors()
        assert list(state.vectors.values()) == ["racing winner"]
    else:
        with pytest.raises(repair.MissingVectorRepairFailure):
            repair.repair_missing_vectors()
        assert state.vectors == {}


def test_missing_only_repair_preserves_core6_metadata(monkeypatch):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    payload = state.rows[0]["payload"]
    payload["core6"] = {"origin": payload.pop("origin"), "trust": "human",
                        "review_state": "protected", "title": "preserved title"}
    payload.pop("trust")
    payload.pop("review_state")
    repair.repair_missing_vectors()
    projected = json.loads(state.vectors[str(state.rows[0]["object_id"])][4])
    assert projected["origin"] == "vault"
    assert projected["trust"] == "human"
    assert projected["review_state"] == "protected"
    assert projected["title"] == "preserved title"
    assert "trust" not in payload and "review_state" not in payload


@pytest.mark.parametrize("change", [
    {"origin": "external"}, {"trust": "untrusted"}, {"review_state": "draft"},
    {"candidate_only": True}, {"authority": {"source_authoritative": False}},
    {"replay": {}}, {"replay": {"source_identity": "secret"}},
])
def test_missing_only_repair_refuses_unadmitted_payload(monkeypatch, change):
    repair, state, _ = _missing_repair_fixture(monkeypatch)
    state.rows[0]["payload"].update(change)
    with pytest.raises(repair.MissingVectorRepairFailure, match="^source_post_rebuild_failed$"):
        repair.repair_missing_vectors()
    assert state.vectors == {} and state.embedded == []


def _seed_object(text: str, *, source_ref: str = "tests") -> str:
    store = ObjectStore()
    obj_id = uuid4()
    store.save_object(
        DomainObject(
            uuid=str(obj_id),
            kind="note",
            payload={"text": text, "content": text},
            source_ref=source_ref,
            created_at=datetime.now(timezone.utc),
        ),
        emit_outbox=False,
        trace_id="trace-seed",
    )
    return str(obj_id)


def test_index_rebuild_dry_run(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("alpha beta knowledge")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("alpha beta knowledge")
    hits = idx.search(query, k=1, identity=identity)
    assert hits == []

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_populates_index(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    obj_uuid = _seed_object("agentic policy note")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"])

    assert result.exit_code == 0
    assert "total=1 processed=1 skipped=0 errors=0" in result.output

    idx = get_vector_index()
    embedder = get_embedding_client()
    identity = get_embedding_identity(client=embedder)
    query = embedder.embed_text("agentic policy")
    hits = idx.search(query, k=1, identity=identity)
    assert hits
    assert str(hits[0].object_id) == obj_uuid

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_json_summary(monkeypatch) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("json summary object")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["processed"] == 1
    assert data["errors"] == []

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_reports_failures(monkeypatch, tmp_path) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    obj_uuid = _seed_object("failure object")
    failures_path = tmp_path / "failures.jsonl"

    idx = get_vector_index()
    original_upsert = idx.upsert

    def _failing_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    idx.upsert = _failing_upsert  # type: ignore[assignment]
    runner = CliRunner()
    try:
        result = runner.invoke(
            cli,
            ["index", "rebuild", "--json", "--failures-path", str(failures_path)],
        )
    finally:
        idx.upsert = original_upsert

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["errors"]
    error = data["errors"][0]
    assert error["object_id"] == obj_uuid
    assert error["source_ref"] == "tests"
    assert error["stage"] == "upsert"
    assert error["exception_type"] == "ValueError"
    assert data["failures_path"] == str(failures_path)
    assert failures_path.exists()

    with open(failures_path, encoding="utf-8") as fh:
        first_line = fh.readline().strip()
    assert first_line
    failure_entry = json.loads(first_line)
    assert failure_entry["object_id"] == obj_uuid
    assert failure_entry["stage"] == "upsert"
    assert failure_entry["source_ref"] == "tests"
    assert failure_entry["identity"]["provider"] == "mock"

    legacy_store._MEMORY_STORE.clear()


def test_index_rebuild_strict_fails_on_error(monkeypatch, tmp_path) -> None:
    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("will fail")
    failures_path = tmp_path / "strict-failures.jsonl"

    idx = get_vector_index()
    original_upsert = idx.upsert

    def _failing_upsert(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    idx.upsert = _failing_upsert  # type: ignore[assignment]
    runner = CliRunner()
    try:
        result = runner.invoke(
            cli,
            [
                "index",
                "rebuild",
                "--json",
                "--strict",
                "--failures-path",
                str(failures_path),
            ],
        )
    finally:
        idx.upsert = original_upsert

    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data["failures_path"] == str(failures_path)
    assert data["errors"]
    assert data["errors"][0]["stage"] == "upsert"
    assert failures_path.exists()

    legacy_store._MEMORY_STORE.clear()

@pytest.mark.pg
def test_index_rebuild_sets_pg_meta(monkeypatch) -> None:
    try:
        from tests.stores.test_store_contract_pg import _pg_available  # reuse helper
    except Exception:  # pragma: no cover - fallback when module moves
        pytest.skip("Postgres helper unavailable")

    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    dsn = resolve_dsn()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("pg domain object", source_ref="pg-test")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"], env={"DATABASE_URL": dsn})
    assert result.exit_code == 0

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1")
            row = cur.fetchone()
            assert row is not None
            data = json.loads(row[0])
            assert data.get("provider")
            assert data.get("model")
            assert int(data.get("dim", 0)) > 0

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()

@pytest.mark.pg
def test_index_rebuild_resets_missing_meta(monkeypatch) -> None:
    try:
        from tests.stores.test_store_contract_pg import _pg_available
    except Exception:
        pytest.skip("Postgres helper unavailable")

    if not _pg_available():
        pytest.skip("Postgres backend not available")

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
    dsn = resolve_dsn()
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_object("pg meta reset object", source_ref="pg-test")

    get_vector_index()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM vector_index_meta WHERE vault_binding_id = %s",
                (COMPATIBILITY_BINDING_ID,),
            )
            cur.execute(
                "DELETE FROM store_vector_index WHERE vault_binding_id = %s",
                (COMPATIBILITY_BINDING_ID,),
            )
            cur.execute(
                "INSERT INTO store_vector_index "
                "(vault_binding_id, object_id, kind, source_ref, payload, embedding, dim, model, updated_at) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, now())",
                (
                    COMPATIBILITY_BINDING_ID,
                    uuid4(),
                    "note",
                    "stale",
                    json.dumps({}),
                    [0.1, 0.2],
                    2,
                    "stale-model",
                ),
            )

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "rebuild"], env={"DATABASE_URL": dsn})
    assert result.exit_code == 0

    expected = get_embedding_identity(client=get_embedding_client())
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT identity_json FROM vector_index_meta WHERE id = 1")
            row = cur.fetchone()
            assert row is not None
            data = json.loads(row[0])
            assert data.get("provider") == expected.provider
            assert data.get("model") == expected.model
            assert int(data.get("dim", 0)) == expected.dim
            cur.execute("SELECT DISTINCT dim FROM store_vector_index")
            dims = {int(row[0]) for row in cur.fetchall() if row and row[0] is not None}
            assert dims == {expected.dim}
            cur.execute("SELECT count(*) FROM store_vector_index")
            count_row = cur.fetchone()
            assert int(count_row[0]) > 0

    reset_store_backends()
    legacy_store._MEMORY_STORE.clear()
