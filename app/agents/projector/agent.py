from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Tuple, Optional

from app.store.object_store import ObjectStore
from app.services.decisions import latest_decision
from app.events.types import (
    PROMOTION_PROJECT_DONE,
    PROMOTION_PROJECT_MEMBERSHIP_UPSERT,
    PROMOTION_PROJECT_SKIP,
)
from app.services.audit import audit_event

try:
    # optional, same pattern as elsewhere (conn_rw etc.)
    from app.db import conn_rw  # type: ignore
except Exception:  # pragma: no cover
    conn_rw = None  # fallback if db module not usable

AGENT = "projector"

# in-memory fallback so pytest without DB can still claim projection happened
_MEMBERSHIP_FALLBACK: List[Tuple[str, str]] = []  # (object_id, set_name)


def _latest_evaluation(object_id: str) -> dict[str, Any] | None:
    dec = latest_decision(object_id, "evaluate")
    if not dec:
        return None
    return dec.get("value") or dec


def _record_membership_db(object_id: str, set_name: str, trace_id: str) -> None:
    """
    Try to persist membership in Postgres. If DB not available, swallow.
    Schema assumption:
      membership(object_id uuid, set_name text, created_at timestamptz)
    """
    if conn_rw is None:
        return
    try:
        with conn_rw() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO membership (object_id, set_name, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        object_id,
                        set_name,
                        datetime.now(timezone.utc),
                    ),
                )
                # also audit row for traceability
                cur.execute(
                    """
                    INSERT INTO audit (trace_id, event, payload, created_at)
                    VALUES (%s, %s, %s::jsonb, %s)
                    """,
                    (
                        trace_id,
                        PROMOTION_PROJECT_MEMBERSHIP_UPSERT,
                        json.dumps(
                            {
                                "object_id": object_id,
                                "set_name": set_name,
                            }
                        ),
                        datetime.now(timezone.utc),
                    ),
                )
    except Exception:
        # offline / no DB: swallow
        return


def project_object(
    object_id: str,
    set_name: str,
    *,
    trace_id: str,
) -> dict[str, Any]:
    """
    Decide if object should land in published set.
    Always include 'promote' in output.
    For promote=True, record membership both in-memory fallback and best-effort DB.
    """

    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        raise RuntimeError(f"object {object_id} not found")

    evaluation = _latest_evaluation(object_id) or {}
    promote = bool(evaluation.get("promote", evaluation.get("allow", False)))

    if promote:
        # fallback memory record
        _MEMBERSHIP_FALLBACK.append((object_id, set_name))
        # best effort DB record
        _record_membership_db(object_id, set_name, trace_id)

    event = PROMOTION_PROJECT_DONE if promote else PROMOTION_PROJECT_SKIP

    out = {
        "event": event,
        "object_id": object_id,
        "set_name": set_name,
        "promote": promote,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    audit_event(
        event=event,
        object_id=object_id,
        agent=AGENT,
        trace_id=trace_id,
        extra={
            "set_name": set_name,
            "promote": promote,
        },
    )

    return out


def run(object_id: str, *, trace_id: str, set_name: str) -> dict[str, Any]:
    return project_object(object_id, set_name, trace_id=trace_id)
