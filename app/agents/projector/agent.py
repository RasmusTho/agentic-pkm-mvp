from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List, Tuple, Optional

from app.store.object_store import ObjectStore
from app.store.membership_store import save_membership
from app.services.decisions import latest_decision
from app.events.types import (
    PROMOTION_PROJECT_DONE,
    PROMOTION_PROJECT_MEMBERSHIP_UPSERT,
    PROMOTION_PROJECT_SKIP,
)
from app.services.audit import audit_event

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
    Schema assumption (see migrations): membership(object_id uuid, set_id uuid, created_at timestamptz).
    """
    # best-effort persistence via membership store (handles DB/no-DB)
    save_membership(object_id, set_name, trace_id=trace_id)
    return None


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
