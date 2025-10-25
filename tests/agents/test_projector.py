import json
import os
import uuid

import psycopg
from psycopg.rows import dict_row

from app.agents.projector.agent import run as project_run
from app.memory.store import recall

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def _create_object() -> str:
    object_id = str(uuid.uuid4())
    payload = {"core6": {"id": object_id}}
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO objects(id, kind, payload) VALUES (%s, %s, %s::jsonb)",
                (object_id, "note", json.dumps(payload)),
            )
    return object_id


def _insert_evaluation(object_id: str, promote: bool, score: float) -> None:
    value = {"promote": promote, "score": score}
    with psycopg.connect(_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions(id, object_id, key, value, created_at)
                VALUES (%s, %s, 'evaluate', %s::jsonb, now())
                """,
                (str(uuid.uuid4()), object_id, json.dumps(value)),
            )


def _membership_count(object_id: str) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM membership WHERE object_id = %s",
                (object_id,),
            )
            row = cur.fetchone()
            return int(row["c"])


def test_projector_promotes_and_skips() -> None:
    promote_id = _create_object()
    skip_id = _create_object()
    _insert_evaluation(promote_id, True, 0.92)
    _insert_evaluation(skip_id, False, 0.42)

    promoted = project_run(promote_id, trace_id="t-projector-1", set_name="published")
    skipped = project_run(skip_id, trace_id="t-projector-1", set_name="published")

    assert promoted["event"] == "promotion.project.done"
    assert promoted["promote"] is True
    assert skipped["promote"] is False

    assert _membership_count(promote_id) >= 1
    assert _membership_count(skip_id) == 0

    memories = recall("projector", "projection", object_id=None, limit=10)
    assert any(entry.get("promoted") for entry in memories)
