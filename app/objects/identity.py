"""Neutral Postgres read seam for canonical and retained object identity."""

from __future__ import annotations

from typing import Any


_CANONICAL_RETAINED_IDENTITY_FROM_SQL = """
FROM store_objects canonical
LEFT JOIN objects legacy ON legacy.id = canonical.object_id
"""


def _validated_retained_mapping(
    *,
    vault_uuid: str,
    object_id: str,
    match_count: int,
    canonical_alias_exists: bool,
) -> str:
    if match_count > 1:
        raise RuntimeError(
            "ambiguous retained vault UUID mapping; reconcile duplicate objects.uuid rows "
            "before retrying"
        )
    if canonical_alias_exists and object_id != vault_uuid:
        raise RuntimeError(
            "retained vault UUID already names a different canonical object; reconcile the "
            "cross-key identity collision before retrying"
        )
    return object_id


def resolve_vault_uuid_with_connection(conn: Any, vault_uuid: str) -> str:
    """Resolve a retained vault UUID to one unambiguous canonical object id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id::text,
                   count(*) OVER () AS match_count,
                   EXISTS (
                       SELECT 1
                       FROM store_objects
                       WHERE object_id = %s
                   ) AS canonical_alias_exists
            FROM objects
            WHERE uuid = %s
            ORDER BY id
            LIMIT 1
            """,
            (vault_uuid, vault_uuid),
        )
        row = cur.fetchone()
    if not row:
        return str(vault_uuid)
    object_id = row.get("id") if isinstance(row, dict) else row[0]
    match_count = row.get("match_count") if isinstance(row, dict) else row[1]
    canonical_alias_exists = (
        row.get("canonical_alias_exists") if isinstance(row, dict) else row[2]
    )
    return _validated_retained_mapping(
        vault_uuid=str(vault_uuid),
        object_id=str(object_id or vault_uuid),
        match_count=int(match_count or 0),
        canonical_alias_exists=bool(canonical_alias_exists),
    )


def vault_uuid_to_canonical_id_map_with_connection(conn: Any) -> dict[str, str]:
    """Return retained vault UUID -> canonical id from the shared identity join."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT canonical.object_id, "
            "COALESCE(legacy.uuid, canonical.object_id) AS vault_uuid, "
            "CASE WHEN legacy.uuid IS NULL THEN 0 ELSE "
            "(SELECT count(*) FROM objects duplicate WHERE duplicate.uuid = legacy.uuid) END "
            "AS match_count, "
            "CASE WHEN legacy.uuid IS NULL THEN false ELSE EXISTS ("
            "SELECT 1 FROM store_objects alias WHERE alias.object_id = legacy.uuid) END "
            "AS canonical_alias_exists "
            + _CANONICAL_RETAINED_IDENTITY_FROM_SQL
        )
        rows = cur.fetchall()
    result: dict[str, str] = {}
    for row in rows:
        vault_uuid = str(row["vault_uuid"] if isinstance(row, dict) else row[1])
        object_id = str(row["object_id"] if isinstance(row, dict) else row[0])
        match_count = row["match_count"] if isinstance(row, dict) else row[2]
        canonical_alias_exists = (
            row["canonical_alias_exists"] if isinstance(row, dict) else row[3]
        )
        result[vault_uuid] = _validated_retained_mapping(
            vault_uuid=vault_uuid,
            object_id=object_id,
            match_count=int(match_count or 0),
            canonical_alias_exists=bool(canonical_alias_exists),
        )
    return result


def retained_vault_uuid_with_connection(conn: Any, object_id: str) -> str | None:
    """Resolve canonical id -> retained vault UUID without inventing an alias."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT legacy.uuid AS vault_uuid, "
            "CASE WHEN legacy.uuid IS NULL THEN 0 ELSE "
            "(SELECT count(*) FROM objects duplicate WHERE duplicate.uuid = legacy.uuid) END "
            "AS match_count, "
            "CASE WHEN legacy.uuid IS NULL THEN false ELSE EXISTS ("
            "SELECT 1 FROM store_objects alias WHERE alias.object_id = legacy.uuid) END "
            "AS canonical_alias_exists "
            + _CANONICAL_RETAINED_IDENTITY_FROM_SQL
            + " WHERE canonical.object_id = %s",
            (object_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    value = row["vault_uuid"] if isinstance(row, dict) else row[0]
    if value is None:
        return None
    match_count = row["match_count"] if isinstance(row, dict) else row[1]
    canonical_alias_exists = (
        row["canonical_alias_exists"] if isinstance(row, dict) else row[2]
    )
    _validated_retained_mapping(
        vault_uuid=str(value),
        object_id=str(object_id),
        match_count=int(match_count or 0),
        canonical_alias_exists=bool(canonical_alias_exists),
    )
    return str(value)
