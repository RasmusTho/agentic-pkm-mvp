"""PostgreSQL isolation proof for MVR-05A3 (#4577)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)

pytestmark = pytest.mark.pg


@pytest.fixture
def migrated_store_dsn(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, "head")
    return dsn


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
) -> None:
    object_id = uuid.uuid4()
    set_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    rows = [("binding-a", object_id), ("binding-b", object_id)]
    with psycopg.connect(migrated_store_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO store_objects "
                "(vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, 'note', '{}'::jsonb)",
                rows,
            )
            cur.executemany(
                "INSERT INTO store_vector_index "
                "(vault_binding_id, object_id, kind, payload, embedding, dim, model) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, ARRAY[1.0]::double precision[], 1, 'm')",
                rows,
            )
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
            cur.executemany(
                "INSERT INTO vector_index_meta (vault_binding_id, id, identity_json) "
                "VALUES (%s, 1, '{}')",
                [(binding,) for binding, _ in rows],
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
                cur.execute(
                    "INSERT INTO membership "
                    "(id, vault_binding_id, object_id, set_id) VALUES (%s, %s, %s, %s)",
                    (uuid.uuid4(), binding, oid, set_id),
                )
                cur.execute(
                    "INSERT INTO file_state (vault_binding_id, path, body_hash) "
                    "VALUES (%s, '/same/note.md', %s)",
                    (binding, f"hash-{binding}"),
                )
                cur.execute(
                    "INSERT INTO agent_memories "
                    "(vault_binding_id, id, layer, payload, provenance) "
                    "VALUES (%s, %s, 'short_term', %s::jsonb, %s::jsonb)",
                    (
                        binding,
                        memory_id,
                        '{"binding":"' + binding + '"}',
                        '{"object_id":"' + str(oid) + '"}',
                    ),
                )
                cur.execute(
                    "INSERT INTO heimdal_meeting_finalization_receipt "
                    "(vault_binding_id, session_id, state_sha256, complete, artifact_refs) "
                    "VALUES (%s, 'same-session', 'same-state', true, %s::jsonb)",
                    (binding, '{"binding":"' + binding + '"}'),
                )

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

        assert conn.execute("SELECT to_regclass('public.objects_embeddings')").fetchone() == (
            None,
        )
        for binding in ("binding-a", "binding-b"):
            assert conn.execute(
                "SELECT payload->>'binding' FROM objects "
                "WHERE vault_binding_id=%s AND uuid=%s",
                (binding, object_id),
            ).fetchone() == (binding,)
            assert conn.execute(
                "SELECT artifact_refs->>'binding' "
                "FROM heimdal_meeting_finalization_receipt "
                "WHERE vault_binding_id=%s AND session_id='same-session'",
                (binding,),
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

    from app.stores import pg

    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg.truncate_pg_tables(vault_binding_id="binding-b")
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
                f"SELECT count(*) FROM {table} WHERE vault_binding_id='binding-a'"
            ).fetchone() == (1,), table
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id='binding-b'"
            ).fetchone() == (0,), table


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
