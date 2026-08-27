"""Read-only authentication for Alembic-owned append-only triggers.

Runtime code may create these objects only while producing a genuinely absent
test-fixture table.  Once the table exists, Alembic is the sole DDL owner and
the runtime's only authority is to authenticate the catalog shape or fail.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RejectMutationTrigger:
    table: str
    trigger: str
    function: str
    body: str


_CATALOG_SQL = """
SELECT
    table_ns.nspname,
    table_class.relname,
    trigger.tgname,
    trigger.tgtype,
    trigger.tgenabled,
    trigger.tgattr::text,
    trigger.tgqual IS NULL,
    function_ns.nspname = table_ns.nspname,
    function.proname,
    function.prokind,
    function.prorettype = 'trigger'::regtype,
    function.pronargs,
    function.proargtypes::text,
    language.lanname,
    function.provolatile,
    function.proisstrict,
    function.prosecdef,
    function.proleakproof,
    function.proparallel,
    function.proconfig,
    function.prosrc
FROM pg_trigger AS trigger
JOIN pg_class AS table_class ON table_class.oid = trigger.tgrelid
JOIN pg_namespace AS table_ns ON table_ns.oid = table_class.relnamespace
JOIN pg_proc AS function ON function.oid = trigger.tgfoid
JOIN pg_namespace AS function_ns ON function_ns.oid = function.pronamespace
JOIN pg_language AS language ON language.oid = function.prolang
WHERE trigger.tgrelid = to_regclass(%s)
  AND table_ns.nspname = current_schema()
  AND trigger.tgname = %s
  AND NOT trigger.tgisinternal
"""


def _canonical_body(value: object) -> str:
    """Remove only wrapper indentation; preserve every body character.

    Collapsing SQL whitespace is unsafe because whitespace inside a quoted
    string is data. PostgreSQL preserves the dollar-quoted ``prosrc`` text, so
    dedenting the common Python/migration wrapper and normalizing line endings
    is sufficient while keeping literals and statement layout exact.
    """

    body = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return textwrap.dedent(body).strip()


def assert_migration_owned_reject_mutation_trigger(
    conn: Any,
    spec: RejectMutationTrigger,
    *,
    error_type: type[RuntimeError],
    migration_hint: str,
) -> None:
    """Authenticate one exact row-level BEFORE UPDATE OR DELETE trigger.

    ``tgenabled`` admits PostgreSQL's two origin-active modes (``O`` and
    ``A``).  Every other trigger and function attribute, including the full
    ``prosrc`` body modulo insignificant whitespace, is exact.
    """

    cur = conn.cursor()
    cur.execute(_CATALOG_SQL, (spec.table, spec.trigger))
    rows = cur.fetchall()
    expected = (
        "public",
        spec.table,
        spec.trigger,
        27,  # ROW | BEFORE | DELETE | UPDATE
        "",
        True,
        True,
        spec.function,
        "f",
        True,
        0,
        "",
        "plpgsql",
        "v",
        False,
        False,
        False,
        "u",
        None,
    )
    valid = False
    if len(rows) == 1:
        row = rows[0]
        valid = (
            tuple(row[:4]) == expected[:4]
            and row[4] in {"O", "A"}
            and tuple(row[5:20]) == expected[4:]
            and _canonical_body(row[20]) == _canonical_body(spec.body)
        )
    if not valid:
        raise error_type(
            f"Trigger '{spec.trigger}' on '{spec.table}' does not match its "
            f"Alembic-owned definition. {migration_hint}"
        )


CONSENT_GRANT_TRIGGER = RejectMutationTrigger(
    table="heimdal_consent_grant",
    trigger="heimdal_consent_grant_no_update",
    function="heimdal_consent_grant_reject_mutation",
    body="""
    BEGIN
        RAISE EXCEPTION 'heimdal_consent_grant is append-only (HEIM-1): % is not permitted', TG_OP;
    END;
    """,
)

MEDIA_RECEIPT_TRIGGER = RejectMutationTrigger(
    table="heimdal_media_receipt",
    trigger="heimdal_media_receipt_no_update",
    function="heimdal_media_receipt_reject_mutation",
    body="""
    BEGIN
        RAISE EXCEPTION 'heimdal_media_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
    END;
    """,
)

OBSERVATION_LOG_TRIGGER = RejectMutationTrigger(
    table="heimdal_observation_log",
    trigger="heimdal_observation_log_no_update",
    function="heimdal_observation_log_reject_mutation",
    body="""
    BEGIN
        RAISE EXCEPTION 'heimdal_observation_log is append-only (HEIM-1): % is not permitted', TG_OP;
    END;
    """,
)

RAW_READ_RECEIPT_TRIGGER = RejectMutationTrigger(
    table="heimdal_raw_read_receipt",
    trigger="heimdal_raw_read_receipt_no_update",
    function="heimdal_raw_read_receipt_reject_mutation",
    body="""
    BEGIN
        RAISE EXCEPTION 'heimdal_raw_read_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
    END;
    """,
)

RAW_DELETION_RECEIPT_TRIGGER = RejectMutationTrigger(
    table="heimdal_raw_deletion_receipt",
    trigger="heimdal_raw_deletion_receipt_no_update",
    function="heimdal_raw_deletion_receipt_reject_mutation",
    body="""
    BEGIN
        IF TG_OP = 'UPDATE'
           AND current_setting('app.heimdal_retention_reconcile', true) = 'true'
           AND NEW.id IS NOT DISTINCT FROM OLD.id
           AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
           AND NEW.content_identity IS NOT DISTINCT FROM OLD.content_identity
           AND NEW.reason IS NOT DISTINCT FROM OLD.reason
           AND NEW.retention_window_days IS NOT DISTINCT FROM OLD.retention_window_days
           AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at
           AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence
           AND (NEW.payload - 'cold_cleanup_location_refs')
               IS NOT DISTINCT FROM (OLD.payload - 'cold_cleanup_location_refs')
           AND heimdal_raw_cleanup_queue_is_subsequence(
               OLD.payload->'cold_cleanup_location_refs',
               NEW.payload->'cold_cleanup_location_refs'
           ) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
    END;
    """,
)

RAW_RECORD_TRIGGER = RejectMutationTrigger(
    table="heimdal_raw_record",
    trigger="heimdal_raw_record_no_update",
    function="heimdal_raw_record_reject_mutation",
    body="""
    BEGIN
        IF TG_OP = 'DELETE'
           AND current_setting('app.heimdal_retention_bypass', true) = 'true'
           AND EXISTS (
               SELECT 1 FROM heimdal_raw_deletion_tombstone
               WHERE record_id = OLD.id
           ) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted '
            'outside the governed tombstone transaction', TG_OP;
    END;
    """,
)
