"""Neutral Postgres read seam for canonical and retained object identity."""

from __future__ import annotations

from typing import Any


_CANONICAL_RETAINED_IDENTITY_FROM_SQL = """
FROM store_objects canonical
LEFT JOIN objects legacy ON legacy.id = canonical.object_id
"""


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
    if int(match_count or 0) > 1:
        raise RuntimeError(
            "ambiguous retained vault UUID mapping; reconcile duplicate objects.uuid rows "
            "before retrying"
        )
    if canonical_alias_exists and str(object_id) != str(vault_uuid):
        raise RuntimeError(
            "retained vault UUID already names a different canonical object; reconcile the "
            "cross-key identity collision before retrying"
        )
    return str(object_id or vault_uuid)


def vault_uuid_to_canonical_id_map_with_connection(conn: Any) -> dict[str, str]:
    """Return retained vault UUID -> canonical id from the shared identity join."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT canonical.object_id, "
            "COALESCE(legacy.uuid, canonical.object_id) AS vault_uuid "
            + _CANONICAL_RETAINED_IDENTITY_FROM_SQL
        )
        rows = cur.fetchall()
    return {
        str(row["vault_uuid"] if isinstance(row, dict) else row[1]):
        str(row["object_id"] if isinstance(row, dict) else row[0])
        for row in rows
    }


def retained_vault_uuid_with_connection(conn: Any, object_id: str) -> str | None:
    """Resolve canonical id -> retained vault UUID without inventing an alias."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT legacy.uuid AS vault_uuid "
            + _CANONICAL_RETAINED_IDENTITY_FROM_SQL
            + " WHERE canonical.object_id = %s",
            (object_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    value = row["vault_uuid"] if isinstance(row, dict) else row[0]
    return str(value) if value is not None else None
