"""MVR-05A5 replay-projection migration and legacy-attribution proofs."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _pk,
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)


pytestmark = pytest.mark.pg
PRE_REPLAY_HEAD = "f4a05a4b0001"
REPLAY_HEAD = "f5a05a5b0001"


def _seed_legacy_rows(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO standing_questions(question_id,scope,text,status,created_at,registered_via,source_path) "
            "VALUES ('sq-1','work','Question?','open',now(),'explicit','questions/sq-1.md')"
        )
        conn.execute(
            "INSERT INTO episodes(episode_id,scope,title,time_start,segmentation,note_path) "
            "VALUES ('ep-11111111-2222-4333-8444-555555555555','work','Episode',now(),'proposed','episodes/ep.md')"
        )
        conn.execute("INSERT INTO episode_engine_state(key,value) VALUES ('cursor:x','{}')")
        conn.execute(
            "INSERT INTO episode_artifact_binding(artifact_ref,episode_id,scope,basis,confidence,rule) "
            "VALUES ('vault.activity:1','ep-11111111-2222-4333-8444-555555555555','work','provenance',1,'v1')"
        )
        conn.execute(
            "INSERT INTO decisions(key,value) VALUES ('classification','{}'::jsonb)"
        )
        conn.execute(
            "INSERT INTO decision_outcomes(decision_object_id,decision_uuid,rung_index,outcome) "
            "VALUES (%s,%s,0,'held')",
            (uuid.uuid4(), uuid.uuid4()),
        )


def test_replay_backfill_is_unambiguous_or_fails_loud(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = request.getfixturevalue("scratch_db_factory")

    legacy = factory()
    _upgrade(legacy, monkeypatch, PRE_REPLAY_HEAD)
    _seed_legacy_rows(legacy)
    with psycopg.connect(legacy) as conn:
        conn.execute(
            "INSERT INTO decisions(key,value,vault_binding_id) "
            "VALUES ('known-foreign','{}'::jsonb,'binding-already-proven')"
        )
    _upgrade(legacy, monkeypatch, REPLAY_HEAD)
    with psycopg.connect(legacy) as conn:
        for table in (
            "standing_questions",
            "episodes",
            "episode_engine_state",
            "episode_artifact_binding",
            "decision_outcomes",
        ):
            assert conn.execute(
                f"SELECT array_agg(DISTINCT vault_binding_id) FROM {table}"
            ).fetchone() == ([COMPATIBILITY_BINDING_ID],), table
        assert conn.execute(
            "SELECT DISTINCT vault_binding_id FROM decisions ORDER BY 1"
        ).fetchall() == [
            ("binding-already-proven",),
            (COMPATIBILITY_BINDING_ID,),
        ]
        assert _pk(conn, "standing_questions") == ["vault_binding_id", "question_id"]
        assert _pk(conn, "episodes") == ["vault_binding_id", "episode_id"]
        assert _pk(conn, "episode_engine_state") == ["vault_binding_id", "key"]
        assert _pk(conn, "episode_artifact_binding") == [
            "vault_binding_id",
            "artifact_ref",
            "episode_id",
        ]

    ambiguous = factory()
    _upgrade(ambiguous, monkeypatch, PRE_REPLAY_HEAD)
    _seed_legacy_rows(ambiguous)
    with psycopg.connect(ambiguous) as conn:
        conn.execute("ALTER TABLE standing_questions ADD COLUMN vault_binding_id text")
        conn.execute(
            "UPDATE standing_questions SET vault_binding_id='unattributable-foreign-binding'"
        )
    with pytest.raises(DBAPIError, match="MVR-05A5 ambiguous replay binding"):
        _upgrade(ambiguous, monkeypatch, REPLAY_HEAD)
    with psycopg.connect(ambiguous) as conn:
        assert conn.execute(
            "SELECT vault_binding_id FROM standing_questions"
        ).fetchone() == ("unattributable-foreign-binding",)
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='episodes' AND column_name='vault_binding_id'"
        ).fetchone() == (0,)
