"""Fail-loud schema guard for MVR-05A5 binding-scoped replay projections."""

from __future__ import annotations

from typing import Any


_EXPECTED_KEYS: dict[str, tuple[str, ...]] = {
    "standing_questions": ("vault_binding_id", "question_id"),
    "episodes": ("vault_binding_id", "episode_id"),
    "episode_engine_state": ("vault_binding_id", "key"),
    "episode_artifact_binding": ("vault_binding_id", "artifact_ref", "episode_id"),
    "decisions": ("id",),
    "decision_outcomes": ("id",),
}

_UNIQUE_CONTRACTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "standing_questions": (
        ("vault_binding_id", "source_path"),
        ("source_path",),
    ),
    "decision_outcomes": (
        ("vault_binding_id", "decision_uuid", "rung_index"),
        ("decision_uuid", "rung_index"),
    ),
}

_MIGRATION_HINT = (
    "Replay projection schema is migration-owned: run 'alembic upgrade head' against "
    "this database. See app/alembic/versions/f5a05a5b0001_mvr05a5_replay_projection_binding_keys.py."
)


class ReplayProjectionSchemaError(RuntimeError):
    """Raised when a replay producer sees a pre-MVR-05A5 schema."""


def assert_replay_projection_schema(conn: Any, table: str) -> None:
    """Require the binding column and the table's MVR-05A5 primary key."""
    expected_key = _EXPECTED_KEYS.get(table)
    if expected_key is None:
        raise ValueError(f"unsupported replay projection table: {table}")
    required_unique, prohibited_unique = _UNIQUE_CONTRACTS.get(table, ((), ()))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT to_regclass(%s) IS NOT NULL AS table_exists,
                   (EXISTS (
                       SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=%s
                          AND column_name='vault_binding_id' AND is_nullable='NO'
                   ) AND (
                       cardinality(%s::text[]) = 0 OR EXISTS (
                           SELECT 1 FROM pg_constraint unique_constraint
                            JOIN unnest(unique_constraint.conkey)
                                 WITH ORDINALITY unique_key(attnum, ordinality) ON true
                            JOIN pg_attribute unique_column
                              ON unique_column.attrelid=unique_constraint.conrelid
                             AND unique_column.attnum=unique_key.attnum
                           WHERE unique_constraint.conrelid=to_regclass(%s)
                             AND unique_constraint.contype='u'
                           GROUP BY unique_constraint.oid
                          HAVING array_agg(unique_column.attname::text ORDER BY unique_key.ordinality)
                                 = %s::text[]
                       )
                   ) AND NOT EXISTS (
                       SELECT 1 FROM pg_constraint global_constraint
                        JOIN unnest(global_constraint.conkey)
                             WITH ORDINALITY global_key(attnum, ordinality) ON true
                        JOIN pg_attribute global_column
                          ON global_column.attrelid=global_constraint.conrelid
                         AND global_column.attnum=global_key.attnum
                       WHERE global_constraint.conrelid=to_regclass(%s)
                         AND global_constraint.contype='u'
                       GROUP BY global_constraint.oid
                      HAVING cardinality(%s::text[]) > 0
                         AND array_agg(global_column.attname::text ORDER BY global_key.ordinality)
                             = %s::text[]
                   )) AS binding_shape_exists,
                   COALESCE((
                       SELECT array_agg(a.attname ORDER BY k.ordinality)
                         FROM pg_constraint c
                         JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true
                         JOIN pg_attribute a
                           ON a.attrelid=c.conrelid AND a.attnum=k.attnum
                        WHERE c.conrelid=to_regclass(%s) AND c.contype='p'
                   ), ARRAY[]::name[]) AS primary_key
            """,
            (
                f"public.{table}",
                table,
                list(required_unique),
                f"public.{table}",
                list(required_unique),
                f"public.{table}",
                list(prohibited_unique),
                list(prohibited_unique),
                f"public.{table}",
            ),
        )
        row = cur.fetchone()
    table_exists = bool(row and (row.get("table_exists") if isinstance(row, dict) else row[0]))
    binding_exists = bool(
        row and (row.get("binding_shape_exists") if isinstance(row, dict) else row[1])
    )
    primary_key = list(
        (row.get("primary_key") if isinstance(row, dict) else row[2]) if row else []
    )
    if not table_exists or not binding_exists or primary_key != list(expected_key):
        raise ReplayProjectionSchemaError(
            f"public.{table} has stale replay-projection shape "
            f"(binding_and_uniqueness={binding_exists}, primary_key={primary_key!r}); "
            f"{_MIGRATION_HINT}"
        )


__all__ = [
    "ReplayProjectionSchemaError",
    "assert_replay_projection_schema",
]
