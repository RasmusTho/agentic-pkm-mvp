"""Read-only assertions for migration-owned indexes and triggers.

Alembic is the sole production DDL owner.  Runtime seams may verify the
objects they depend on, but they must never repair or replace those objects on
an already-migrated table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MigrationOwnedTrigger:
    """The trigger/function binding a runtime seam requires."""

    name: str
    function: str
    function_body_fragments: tuple[str, ...] = ()


def _value(row: Any, index: int, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]


def assert_migration_owned_attached_objects(
    conn: Any,
    *,
    table: str,
    indexes: tuple[str, ...],
    error_type: type[Exception],
    migration_hint: str,
    trigger: MigrationOwnedTrigger | None = None,
) -> None:
    """Fail loudly when a migration-owned table group is absent or drifted.

    Every statement is a ``SELECT``.  The caller owns the typed schema error
    so existing boot-ordering/refusal classification remains unchanged.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass(quote_ident(current_schema()) || '.' || quote_ident(%s)) AS oid",
        (table,),
    )
    row = cur.fetchone()
    if row is None or not _value(row, 0, "oid"):
        raise error_type(f"Missing table '{table}'. {migration_hint}")

    cur.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = current_schema() AND tablename = %s",
        (table,),
    )
    present_indexes = {_value(item, 0, "indexname") for item in cur.fetchall()}
    missing_indexes = sorted(set(indexes) - present_indexes)
    if missing_indexes:
        raise error_type(
            f"Table '{table}' is missing migration-owned index(es) {missing_indexes}. "
            f"{migration_hint}"
        )

    if trigger is None:
        return

    cur.execute(
        """
        SELECT trigger.tgname,
               pg_get_triggerdef(trigger.oid) AS trigger_definition,
               trigger.tgenabled,
               procedure.proname,
               pg_get_functiondef(procedure.oid) AS function_definition
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        WHERE namespace.nspname = current_schema()
          AND relation.relname = %s
          AND trigger.tgname = %s
          AND NOT trigger.tgisinternal
        """,
        (table, trigger.name),
    )
    trigger_row = cur.fetchone()
    if trigger_row is None:
        raise error_type(
            f"Table '{table}' is missing migration-owned trigger '{trigger.name}'. "
            f"{migration_hint}"
        )

    definition = str(_value(trigger_row, 1, "trigger_definition")).lower()
    enabled = str(_value(trigger_row, 2, "tgenabled"))
    function_name = str(_value(trigger_row, 3, "proname"))
    function_definition = str(_value(trigger_row, 4, "function_definition")).lower()
    required_trigger_fragments = (" before ", " update ", " delete ", " for each row ")
    malformed = [
        fragment.strip()
        for fragment in required_trigger_fragments
        if fragment not in f" {definition} "
    ]
    if enabled == "D" or function_name != trigger.function or malformed:
        raise error_type(
            f"Migration-owned trigger '{trigger.name}' on '{table}' is incompatible "
            f"(enabled={enabled!r}, function={function_name!r}, missing={malformed}). "
            f"{migration_hint}"
        )

    missing_function_fragments = [
        fragment
        for fragment in trigger.function_body_fragments
        if fragment.lower() not in function_definition
    ]
    if missing_function_fragments:
        raise error_type(
            f"Migration-owned trigger function '{trigger.function}' on '{table}' is missing "
            f"required guard fragment(s) {missing_function_fragments}. {migration_hint}"
        )
