from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from typing import Any, Dict, List, Optional

import psycopg

from app.db.db import COMPATIBILITY_BINDING_ID, conn_ro, conn_rw
from app.db.decisions_schema import assert_decisions_schema
from app.db.dsn import resolve_dsn
from app.receipts.decision_receipt_log import append_decision_receipt

# in-memory fallback used only under an explicit memory backend opt-in
# (STORE_BACKEND=memory / test conftest override). See D-7
# (docs/architecture/runtime-semantics.md :: Divergences): a Postgres-configured
# but unreachable database must never silently degrade to this volatile store.
_MEM_DECISIONS: Dict[str, List[dict[str, Any]]] = {}

_ALLOWED_BACKENDS = {"memory", "pg"}


class DecisionsSchemaMigrationRequired(RuntimeError):
    """The active decisions projection still has its pre-#3510 FK parent."""


def _assert_decisions_fk_cutover() -> None:
    _assert_decisions_fk_cutover_for_dsn(resolve_dsn())


@lru_cache(maxsize=8)
def _assert_decisions_fk_cutover_for_dsn(_dsn: str) -> None:
    """Fail before receipt append unless decisions uses the canonical parent.

    This preflight is deliberately read-only and uses ``conn_ro`` so it never
    invokes the legacy ``conn_rw`` schema bootstrap. Receipt-before-ack still
    governs the actual decision write; the schema gate merely proves that the
    rebuildable projection can accept that receipt before the canonical log is
    mutated.
    """
    try:
        with conn_ro() as conn:
            assert_decisions_schema(conn)
    except RuntimeError as exc:
        raise DecisionsSchemaMigrationRequired(
            "#3510 decisions FK migration is required before a durable decision receipt can be "
            "appended: run 'alembic upgrade head' and retry. Expected "
            "public.decisions(vault_binding_id, object_id) -> "
            "public.store_objects(vault_binding_id, object_id) ON DELETE SET NULL (object_id)."
        ) from exc


@lru_cache(maxsize=8)
def _resolved_backend(explicit: Optional[str], dsn: str) -> str:
    """Fail-loud store-backend resolution (KERNEL-03 / I-S4 posture).

    Deliberately duplicated from ``app.stores.provider._resolved_backend``
    instead of imported: ``app.stores`` is a deprecated package
    (`tests/architecture/test_deprecated_store_callers.py`) and
    ``app/services/decisions.py`` is not an existing allowlisted caller, so a
    new import from it would extend the deprecated surface. This mirrors the
    same explicit-opt-in contract: an explicit but unknown backend value
    raises; no configuration raises; a configured-but-unreachable Postgres
    raises. Only an explicit ``STORE_BACKEND=memory`` opt-in routes to the
    in-process memory fallback below.
    """
    if explicit and explicit.strip():
        normalized = explicit.strip().lower()
        if normalized not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{normalized}' is not supported: set STORE_BACKEND to "
                "'pg' or 'memory' (explicit opt-in to volatile state), or unset it to "
                "resolve from DATABASE_URL/DB_DSN."
            )
        return normalized

    if not dsn:
        raise RuntimeError(
            "No store backend configured: set STORE_BACKEND=memory explicitly for the "
            "volatile in-memory backend, or configure DATABASE_URL/DB_DSN for Postgres."
        )

    try:
        conn = psycopg.connect(dsn, connect_timeout=1)
    except Exception as exc:
        raise RuntimeError(
            "Store backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a "
            f"volatile in-memory store. Underlying error: {exc}"
        ) from exc
    else:
        conn.close()
        return "pg"


def _use_memory_backend() -> bool:
    """Resolve the shared fail-loud store-backend contract (KERNEL-03).

    Raises when Postgres is configured but unreachable, or when nothing is
    configured at all. Only an explicit ``STORE_BACKEND=memory`` opt-in (set
    directly or via the test conftest autouse fixtures) routes to the
    in-process memory fallback below.
    """
    backend = _resolved_backend(os.getenv("STORE_BACKEND"), resolve_dsn())
    return backend == "memory"


def insert_decision(object_id: str, key: str, value: dict[str, Any], trace_id: str) -> None:
    created_at = datetime.now(timezone.utc)
    rec = {
        "object_id": object_id,
        "key": key,
        "value": value,
        "trace_id": trace_id,
        "created_at": created_at,
    }

    if _use_memory_backend():
        # Explicit STORE_BACKEND=memory opt-in: volatile by contract (I-S4 /
        # D-7). There is no durable store and no selected vault in this mode, so
        # the durable receipt log does not apply — the in-process bucket is the
        # whole record. The receipt-log commit point below governs the durable
        # Postgres path only.
        bucket = _MEM_DECISIONS.setdefault(object_id, [])
        bucket.append(rec)
        return

    # Durable path — decision-receipt log is CANONICAL, Postgres is the
    # projection (feat #2969, docs/DECISION_RECEIPT_LOG/README.md).
    #
    # The read-only #3510 schema preflight must run before the canonical log is
    # mutated. Otherwise a pre-cutover FK can accept the receipt and then reject
    # its projection with a raw ForeignKeyViolation, leaving an avoidable
    # durable-but-unprojected decision.
    _assert_decisions_fk_cutover()

    # Receipt-before-ack (C-5/P-5): append the WriteGuard-gated durable receipt
    # FIRST — that append is the commit point. A blocked WriteGuard raises
    # (WritesBlockedError) and any I/O failure raises (DecisionReceiptWriteError);
    # either way the whole write fails and the caller sees it. The governance
    # action never silently proceeds DB-only (C-8). Only after the durable
    # receipt lands do we write the derived DB projection row below.
    append_decision_receipt(
        object_id=object_id,
        key=key,
        value=value,
        trace_id=trace_id,
        created_at=created_at,
    )

    # Postgres projection: a failure here must propagate (fail-loud, no silent
    # memory fallback — D-7). _use_memory_backend() already raised above if
    # Postgres was configured but unreachable, so a failure past this point
    # is a genuine write-time error the caller must see. The decision is already
    # durable in the receipt log at this point; the projection is rebuildable
    # (Slice 2) if this row is ever lost.
    #
    # The `decisions` table (app/alembic/versions/202510241200_sot41_amg_core.py)
    # has no `trace_id` column — only `audit` does. `trace_id` is folded
    # into the `value` jsonb envelope instead of adding a schema column,
    # preserving round-trip access via latest_decision() with no migration, and
    # matching the value envelope the receipt log stores.
    stored_value = dict(value)
    stored_value["trace_id"] = trace_id
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions (
                    vault_binding_id, object_id, key, value, created_at
                )
                VALUES (%s, %s, %s, %s::jsonb, %s)
                """,
                (
                    COMPATIBILITY_BINDING_ID,
                    object_id,
                    key,
                    json.dumps(stored_value),
                    rec["created_at"],
                ),
            )


def latest_decision(object_id: str, key: str) -> dict[str, Any] | None:
    """
    Return latest decision with this key for object_id.
    - Under the explicit memory backend, consult in-process memory only.
    - Otherwise, read the most recent persisted decision from Postgres.
      A configured-but-unreachable Postgres raises (fail-loud, D-7).
    """
    if _use_memory_backend():
        items = _MEM_DECISIONS.get(object_id, [])
        for rec in reversed(items):
            if rec["key"] == key:
                return rec
        return None

    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT object_id, key, value, created_at
                FROM decisions
                WHERE vault_binding_id = %s AND object_id = %s AND key = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (COMPATIBILITY_BINDING_ID, object_id, key),
            )
            row = cur.fetchone()
            if not row:
                return None
            # parse jsonb value into dict; trace_id was folded into this
            # envelope by insert_decision() (see comment there — the
            # decisions table has no trace_id column).
            raw_val = row["value"]
            value = raw_val if isinstance(raw_val, dict) else json.loads(raw_val)
            trace_id = value.pop("trace_id", None) if isinstance(value, dict) else None
            return {
                "object_id": row["object_id"],
                "key": row["key"],
                "value": value,
                "trace_id": trace_id,
                "created_at": row.get("created_at"),
            }
