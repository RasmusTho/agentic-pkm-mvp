from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import logging
import os
import uuid

from psycopg import IntegrityError

from app.db.db import conn_rw
from app.settings import settings
from app.stores import resolved_store_backend_hint

logger = logging.getLogger(__name__)

_AUDIT_INSERT_SQL = """
INSERT INTO audit (id, object_id, agent, action, ts, trace_id, details)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
"""


def _audit_pg_backend_selected() -> bool:
    explicit_backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if explicit_backend:
        return explicit_backend == "pg"
    settings_backend = str(getattr(settings, "store_backend", "") or "").strip().lower()
    if settings_backend == "pg":
        return True
    return resolved_store_backend_hint() == "pg"

def audit_event(
    *,
    event: str,
    object_id: str | None,
    agent: str,
    trace_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Best-effort audit logger.
    Writes to audit table if DB is up, otherwise silently no-ops for pytest.
    """
    # Skip unless pg is explicit or already known from the store layer. Calling
    # the auto-detect resolver from this best-effort audit path can perform a
    # DNS/pg probe before the offline no-op below gets a chance to catch it.
    if not _audit_pg_backend_selected():
        return

    details = {
        "event": event,
        "extra": extra or {},
    }
    ts = datetime.now(timezone.utc)

    try:
        # Bound the connect on this best-effort path so an unreachable DB host
        # (e.g. memory/non-pg mode resolving a non-empty DSN to db:5432) cannot
        # stall in DNS/socket resolution before the offline except below catches.
        with conn_rw(connect_timeout=1) as conn:
            _insert_audit_row(
                conn,
                object_id=object_id,
                agent=agent,
                action=event,
                ts=ts,
                trace_id=trace_id,
                details=details,
            )
    except Exception as exc:
        logger.error(
            "audit_event INSERT failed — best-effort audit write dropped",
            exc_info=exc,
            extra={"event": event, "agent": agent, "trace_id": trace_id},
        )
        return


def _insert_audit_row(
    conn,
    *,
    object_id: str | None,
    agent: str,
    action: str,
    ts: datetime,
    trace_id: str,
    details: dict[str, Any],
) -> None:
    """Insert one audit row, falling back to a NULL object_id on FK violation.

    The ``audit.object_id`` FK references the legacy ``objects`` table, but the
    active object store writes to ``store_objects`` (``PgObjectStore``). An
    object-scoped audit call (e.g. the promotion-gate path) therefore carries an
    ``object_id`` that exists in ``store_objects`` but not in ``objects``, so the
    first INSERT raises an FK ``IntegrityError`` and would drop the row entirely.

    To keep the audit trail honest without repointing/dropping the FK (DB audit
    is not the durable system-of-record — that is a separate Storage-lifecycle
    epic), retry once with ``object_id = NULL`` and preserve the original id in
    ``details["object_ref"]``. The first attempt runs inside a SAVEPOINT
    (``conn.transaction()``) so its failure does not poison the surrounding
    transaction before the retry.
    """
    if object_id is None:
        # No FK to satisfy — a single direct insert is enough.
        with conn.cursor() as cur:
            cur.execute(
                _AUDIT_INSERT_SQL,
                (
                    str(uuid.uuid4()),
                    None,
                    agent,
                    action,
                    ts,
                    trace_id,
                    json.dumps(details),
                ),
            )
        return

    try:
        # SAVEPOINT-scoped first attempt: an FK violation here is rolled back to
        # the savepoint, leaving the connection usable for the NULL retry.
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    _AUDIT_INSERT_SQL,
                    (
                        str(uuid.uuid4()),
                        object_id,
                        agent,
                        action,
                        ts,
                        trace_id,
                        json.dumps(details),
                    ),
                )
        return
    except IntegrityError:
        # object_id is not present in the FK-referenced `objects` table (it lives
        # in `store_objects`). Preserve it in details and write with NULL FK.
        logger.warning(
            "audit object_id %s not in objects table (FK); writing row with NULL "
            "object_id and preserving the id in details.object_ref",
            object_id,
        )

    fallback_details = dict(details)
    fallback_details["object_ref"] = object_id
    with conn.cursor() as cur:
        cur.execute(
            _AUDIT_INSERT_SQL,
            (
                str(uuid.uuid4()),
                None,
                agent,
                action,
                ts,
                trace_id,
                json.dumps(fallback_details),
            ),
        )
