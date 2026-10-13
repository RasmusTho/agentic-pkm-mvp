"""PostgreSQL isolation proof for MVR-05A3 (#4577)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.heimdal import meeting_finalization
from app.memory_kv.store import remember
from app.store.membership_store import save_membership
from tests._mvr03_principal_harness import provisioned_instance
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)

pytestmark = [pytest.mark.pg, pytest.mark.usefixtures("product_model_access_gateway")]


@pytest.fixture
def migrated_store_dsn(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, "head")
    return dsn


@pytest.fixture
def isolated_read_process():
    from app.api.routes import active_context_selection as selection_routes
    from app.retrieval import hybrid
    from app.stores import _pg_instances

    selection_routes.reset_selection_store_for_tests()
    _pg_instances.cache_clear()
    hybrid.reset_durable_rebuild_state()
    try:
        yield
    finally:
        hybrid.get_store().set_documents([])
        hybrid.reset_durable_rebuild_state()
        _pg_instances.cache_clear()
        selection_routes.reset_selection_store_for_tests()


def test_binding_scoped_rebuild_preserves_standing_question_and_episode_rows(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Rebuilding binding B cannot erase binding A, even for identical vault ids."""
    from app.jobs import episodes_projection
    from app.standing_questions.projection import _replace_projection_rows

    question_id = "sq-11111111-2222-4333-8444-555555555555"
    question = {
        "question_id": question_id,
        "scope": "work",
        "text": "Same vault-derived question",
        "status": "open",
        "created_at": "2026-08-15T10:00:00Z",
        "registered_via": "explicit",
        "standing_answer_ref": None,
        "candidate_answer_ref": None,
        "evidence": [],
        "last_matched_at": None,
        "last_refreshed_at": None,
    }
    for binding in ("binding-a", "binding-b"):
        _replace_projection_rows(
            [(f"questions/{question_id}.md", question)], vault_binding_id=binding
        )
    _replace_projection_rows([], vault_binding_id="binding-b")

    episode_id = "ep-11111111-2222-4333-8444-555555555555"
    fields = {
        "episode_id": episode_id,
        "scope": "work",
        "title": "Same vault-derived episode",
        "time": {"start": "2026-08-15T10:00:00Z", "closed": False},
        "segmentation": "proposed",
        "parent_episode": None,
        "space": [],
        "protagonists": [],
        "goal": [],
        "causation": [],
        "derived_from": [],
    }
    episode_path = tmp_path / "episode.md"
    episode_path.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(episodes_projection, "_episode_note_paths", lambda _root: [episode_path])
    monkeypatch.setattr(episodes_projection, "parse_validated_episode_note", lambda _text: fields)
    episodes_projection.rebuild_episodes_projection(tmp_path, vault_binding_id="binding-a")
    episodes_projection.rebuild_episodes_projection(tmp_path, vault_binding_id="binding-b")
    monkeypatch.setattr(episodes_projection, "_episode_note_paths", lambda _root: [])
    episodes_projection.rebuild_episodes_projection(tmp_path, vault_binding_id="binding-b")

    with psycopg.connect(migrated_store_dsn) as conn:
        assert conn.execute(
            "SELECT vault_binding_id,question_id FROM standing_questions ORDER BY 1"
        ).fetchall() == [("binding-a", question_id)]
        assert conn.execute(
            "SELECT vault_binding_id,episode_id FROM episodes ORDER BY 1"
        ).fetchall() == [("binding-a", episode_id)]


def test_duplicate_uuid_is_namespaced_by_binding(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    isolated_read_process,
) -> None:
    """The shipped readers and scoped route retain five-surface A/B provenance."""
    from app.api.app import _warm_retrieval_cache, app
    from app.api.routes import search as search_routes
    from app.components.embeddings import get_embedding_identity
    from app.retrieval import hybrid
    from app.retrieval.capability import RetrievalRequest, RetrievalResponse
    from app.services.vault_sync import _get_state_by_path, _get_state_by_uuid, _upsert_file_state
    from app.stores import pg
    from app.stores.pg import PgObjectStore, PgVectorIndex

    object_id = uuid.uuid4()
    set_id = uuid.uuid4()
    runtime, first, extra, _principal = provisioned_instance(tmp_path, extra_roots=("two",))
    binding_a, binding_b = first.vault_binding_id, extra[0].vault_binding_id
    registry = runtime.registry
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "0")
    monkeypatch.setattr(pg, "_TABLES_READY", False)

    identity = get_embedding_identity()
    embedding = [0.125] * identity.dim
    objects = {
        binding: PgObjectStore(vault_binding_id=binding) for binding in (binding_a, binding_b)
    }
    indexes = {
        binding: PgVectorIndex(vault_binding_id=binding) for binding in (binding_a, binding_b)
    }

    def payload(binding: str, version: str) -> dict:
        return {
            "binding": binding,
            "version": version,
            "title": f"{binding}-{version}",
            "text": f"needle {binding} {version}",
            "domain": "default",
        }

    def replay(binding: str, version: str) -> None:
        source = f"{binding}/same/note.md"
        objects[binding].put(
            object_id, kind="note", source_ref=source, payload=payload(binding, version)
        )
        indexes[binding].upsert(
            object_id,
            kind="note",
            source_ref=source,
            payload=payload(binding, version),
            embedding=embedding,
            model=identity.model,
            identity=identity,
        )
        with psycopg.connect(migrated_store_dsn) as conn:
            _upsert_file_state(
                conn,
                path="/same/note.md",
                uuid_value=str(object_id),
                fm_hash="same-frontmatter",
                body_hash=f"hash-{binding}-{version}",
                mtime=datetime.now(timezone.utc),
                binding_id=binding,
            )

    for binding in (binding_a, binding_b):
        replay(binding, "original")
    rows = [
        (registration.vault_binding_id, object_id) for registration in registry.list_registrations()
    ]
    with psycopg.connect(migrated_store_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO store_relations "
                "(vault_binding_id, src_id, dst_id, rel) VALUES (%s, %s, %s, 'self')",
                [(binding, oid, oid) for binding, oid in rows],
            )
            cur.executemany(
                "INSERT INTO store_relation_memberships "
                "(vault_binding_id, src_id, rel, value) VALUES (%s, %s, 'tag', 'shared')",
                rows,
            )
            for binding, oid in rows:
                cur.execute(
                    "INSERT INTO sets (vault_binding_id, id, name) "
                    "VALUES (%s, %s, 'shared-isolation-set')",
                    (binding, set_id),
                )
                cur.execute(
                    "INSERT INTO objects "
                    "(vault_binding_id, id, uuid, kind, payload) "
                    "VALUES (%s, %s, %s, 'note', %s::jsonb)",
                    (binding, oid, oid, '{"binding":"' + binding + '"}'),
                )
                chunk_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO chunks "
                    "(id, vault_binding_id, object_id, idx, offset_start, offset_end, text) "
                    "VALUES (%s, %s, %s, 0, 0, 1, 'x')",
                    (chunk_id, binding, oid),
                )
                cur.execute(
                    "INSERT INTO embeddings "
                    "(id, vault_binding_id, object_id, chunk_id, provider, dim, embedding) "
                    "VALUES (%s, %s, %s, %s, 'mock', 1, '[1]'::vector)",
                    (uuid.uuid4(), binding, oid, chunk_id),
                )
                cur.execute(
                    "INSERT INTO relations "
                    "(id, vault_binding_id, src_id, dst_id, type) "
                    "VALUES (%s, %s, %s, %s, 'self')",
                    (uuid.uuid4(), binding, oid, oid),
                )

    receipt_store = meeting_finalization._PgReceiptStore()
    for binding, oid in rows:
        save_membership(
            str(oid),
            "shared-isolation-set",
            vault_binding_id=binding,
        )
        # This retained scalar producer needs its explicit registered root;
        # the production scoped reads below use only their request carriers.
        registration = registry.lookup(binding)
        assert registration is not None
        with monkeypatch.context() as scalar_producer:
            scalar_producer.setenv("VAULT_ROOT", registration.path)
            scalar_producer.setenv("WATCHER_VAULT_PATH", registration.path)
            remember(
                "isolation-agent",
                "isolation-memory",
                str(oid),
                f"trace-{binding}",
                {"binding": binding},
                vault_binding_id=binding,
            )
        assert receipt_store.insert(
            meeting_finalization.FinalizationReceipt(
                session_id="same-session",
                state_sha256="same-state",
                complete=True,
                missing_seqs=[],
                artifact_refs={"binding": binding, "object_id": str(oid), "version": "original"},
                supersedes=None,
                finalized_at=meeting_finalization._utcnow(),
                vault_binding_id=binding,
            )
        )

    with psycopg.connect(migrated_store_dsn) as conn:
        # Ingest projections have independent provenance even for the same UUID.
        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
            "chunks",
            "embeddings",
            "relations",
            "membership",
            "objects",
            "file_state",
            "agent_memories",
            "heimdal_meeting_finalization_receipt",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (2,), table

        assert conn.execute(
            "SELECT count(*) FROM sets WHERE name='shared-isolation-set'"
        ).fetchone() == (2,)

        assert conn.execute("SELECT to_regclass('public.objects_embeddings')").fetchone() == (None,)
        for binding in (binding_a, binding_b):
            assert conn.execute(
                "SELECT payload->>'binding' FROM objects " "WHERE vault_binding_id=%s AND uuid=%s",
                (binding, object_id),
            ).fetchone() == (binding,)
            assert conn.execute(
                "SELECT artifact_refs->>'binding' "
                "FROM heimdal_meeting_finalization_receipt "
                "WHERE vault_binding_id=%s AND session_id='same-session'",
                (binding,),
            ).fetchone() == (binding,)
            assert conn.execute(
                "SELECT payload->>'binding' FROM agent_memories "
                "WHERE vault_binding_id=%s AND provenance->>'object_id'=%s",
                (binding, str(object_id)),
            ).fetchone() == (binding,)

        unique_keys = conn.execute(
            """
            SELECT array_agg(a.attname ORDER BY k.ordinality)
              FROM pg_index i
              JOIN unnest(i.indkey::smallint[]) WITH ORDINALITY k(attnum, ordinality) ON true
              JOIN pg_attribute a
                ON a.attrelid = i.indrelid AND a.attnum = k.attnum
             WHERE i.indrelid = 'public.store_objects'::regclass AND i.indisunique
             GROUP BY i.indexrelid
            """
        ).fetchall()
    assert ["object_id"] not in [list(row[0]) for row in unique_keys]
    assert ["vault_binding_id", "object_id"] in [list(row[0]) for row in unique_keys]

    observed: list[tuple[RetrievalRequest, RetrievalResponse]] = []
    production_retrieve = search_routes.retrieve

    def observe_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        # Observe request propagation/provenance while executing the unchanged
        # production capability, durable index, cache and ranking path.
        response = production_retrieve(request)
        observed.append((request, response))
        return response

    monkeypatch.setattr(search_routes, "retrieve", observe_retrieve)
    # Use the API's real startup seam; never seed the hybrid cache independently.
    _warm_retrieval_cache()
    assert len(hybrid.get_store().all()) == 2
    client = TestClient(app)
    sessions = {}
    for binding in (binding_a, binding_b):
        selection = client.post(
            "/api/companion/active-context/selection",
            json={"vault_binding_ids": [binding]},
        )
        assert selection.status_code == 201, selection.text
        sessions[binding] = selection.json()

    def read(binding: str, version: str, *, state: str = "same-state") -> str:
        stored = objects[binding].get(object_id)
        assert stored is not None
        assert stored["payload"] == payload(binding, version)
        assert stored["source_ref"] == f"{binding}/same/note.md"
        indexed = indexes[binding].all_rows_for_bindings((binding,))
        assert len(indexed) == 1
        assert indexed[0]["object_id"] == object_id
        assert indexed[0]["vault_binding_id"] == binding
        assert indexed[0]["payload"] == payload(binding, version)
        vector_hits = indexes[binding].search(embedding, k=1, identity=identity)
        assert len(vector_hits) == 1
        assert vector_hits[0].object_id == object_id
        assert vector_hits[0].payload == payload(binding, version)
        with psycopg.connect(migrated_store_dsn, row_factory=dict_row) as conn:
            file_state = _get_state_by_path(conn, "/same/note.md", binding_id=binding)
            assert file_state is not None
            assert file_state["uuid"] == str(object_id)
            assert file_state["body_hash"] == f"hash-{binding}-{version}"
            assert _get_state_by_uuid(conn, str(object_id), binding_id=binding) == file_state
        receipt = receipt_store.get(binding, "same-session", state)
        assert receipt is not None
        assert receipt.vault_binding_id == binding
        assert receipt.artifact_refs == {
            "binding": binding,
            "object_id": str(object_id),
            "version": version,
        }

        result = client.get(
            "/search/scoped",
            params={"q": "needle"},
            headers={"X-Active-Context-Session": sessions[binding]["context_selection_id"]},
        )
        assert result.status_code == 200, result.text
        assert result.json()["results"] == [
            {"uuid": str(object_id), "title": f"{binding}-{version}"}
        ]
        request, response = observed[-1]
        assert request.active_context is not None
        assert request.active_context.binding_ids == (binding,)
        assert request.active_context.context_id == sessions[binding]["context"]["context_id"]
        assert len(response.hits) == 1
        hit = response.hits[0]
        assert hit.doc_id == str(object_id)
        assert hit.source_ref == f"{binding}/same/note.md"
        assert hit.payload["vault_binding_id"] == binding
        assert hit.payload["version"] == version
        assert hit.payload["context_generation"] == request.active_context.generation
        provenance = response.metadata["provenance"]["active_context"]
        assert provenance["binding_ids"] == [binding]
        assert provenance["generation"] == request.active_context.generation
        return provenance["cache_key"]

    # Warm B first: its same-UUID result/cache cannot satisfy the subsequent A request.
    b_key = read(binding_b, "original")
    a_key = read(binding_a, "original")
    assert a_key != b_key
    assert {doc.payload["vault_binding_id"] for doc in hybrid.get_store().all()} == {
        binding_a,
        binding_b,
    }

    count = len(observed)
    assert client.get("/search/scoped", params={"q": "needle"}).status_code == 401
    rejected = client.get(
        "/search/scoped",
        params={"q": "needle"},
        headers={
            "X-Active-Context-Session": sessions[binding_a]["context_selection_id"],
            "X-Active-Context-Override": "unknown-override",
        },
    )
    assert rejected.status_code == 401
    assert len(observed) == count  # no default/session fallback reached retrieval

    missing = "unregistered-binding"
    assert PgObjectStore(vault_binding_id=missing).get(object_id) is None
    assert PgVectorIndex(vault_binding_id=missing).all_rows() == []
    assert receipt_store.get(missing, "same-session", "same-state") is None
    with psycopg.connect(migrated_store_dsn, row_factory=dict_row) as conn:
        assert _get_state_by_path(conn, "/same/note.md", binding_id=missing) is None

    second_root = tmp_path / "two"
    unavailable_root = tmp_path / "two-unavailable"
    second_root.rename(unavailable_root)
    try:
        unavailable = client.get(
            "/search/scoped",
            params={"q": "needle"},
            headers={"X-Active-Context-Session": sessions[binding_b]["context_selection_id"]},
        )
        assert unavailable.status_code == 409
        assert unavailable.json()["detail"] == "active_context_read_unavailable"
        assert len(observed) == count  # the real read/effect fence refuses before retrieval
        assert read(binding_a, "original") == a_key
    finally:
        unavailable_root.rename(second_root)

    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg.truncate_pg_tables(vault_binding_id=binding_b)
    with psycopg.connect(migrated_store_dsn) as conn:
        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
            "chunks",
            "embeddings",
            "relations",
            "membership",
        ):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id=%s",
                (binding_a,),
            ).fetchone() == (1,), table
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id=%s",
                (binding_b,),
            ).fetchone() == (0,), table

    # Rebuild the cache from the real reset index. B's old cached hit must disappear.
    hybrid.rebuild_from_durable_index(force=True)
    assert read(binding_a, "original") == a_key
    absent = client.get(
        "/search/scoped",
        params={"q": "needle"},
        headers={"X-Active-Context-Session": sessions[binding_b]["context_selection_id"]},
    )
    assert absent.status_code == 200
    assert absent.json()["results"] == []
    assert objects[binding_b].get(object_id) is None

    replay(binding_b, "replayed")
    assert receipt_store.insert(
        meeting_finalization.FinalizationReceipt(
            session_id="same-session",
            state_sha256="replayed-state",
            complete=True,
            missing_seqs=[],
            artifact_refs={
                "binding": binding_b,
                "object_id": str(object_id),
                "version": "replayed",
            },
            supersedes="same-state",
            finalized_at=meeting_finalization._utcnow(),
            vault_binding_id=binding_b,
        )
    )
    hybrid.rebuild_from_durable_index(force=True)
    # B may rotate its context generation after its unavailable-root request;
    # its recovered/replayed result must still have a cache identity distinct from A.
    assert read(binding_b, "replayed", state="replayed-state") != a_key
    assert read(binding_a, "original") == a_key
    assert receipt_store.get(binding_a, "same-session", "replayed-state") is None
    original_b = receipt_store.get(binding_b, "same-session", "same-state")
    assert original_b is not None and original_b.artifact_refs["version"] == "original"


def test_atomic_create_once_conflict_identity_is_binding_scoped(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A winner in one binding cannot suppress the same UUID in another."""
    import app.stores.pg as pg_store

    monkeypatch.setattr(pg_store, "_TABLES_READY", False)
    object_id = uuid.uuid4()
    binding_a = pg_store.PgObjectStore(vault_binding_id="binding-a")
    binding_b = pg_store.PgObjectStore(vault_binding_id="binding-b")

    assert binding_a.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:first-a",
        payload={"winner": "a"},
    )
    assert not binding_a.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:second-a",
        payload={"winner": "wrong"},
    )
    assert binding_b.put_if_absent(
        object_id,
        kind="immutable",
        source_ref="test:first-b",
        payload={"winner": "b"},
    )

    assert binding_a.get(object_id)["payload"] == {"winner": "a"}
    assert binding_b.get(object_id)["payload"] == {"winner": "b"}
    with psycopg.connect(migrated_store_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone() == (2,)
