from __future__ import annotations

import os
from uuid import UUID

from app.agents.base.audit import audit_log
from app.stores import get_relation_index


class OrphanPromotionError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_object_has_relations(
    object_id: str | UUID,
    *,
    relation_index=None,
    allow_orphans: bool | None = None,
    override_reason: str | None = None,
) -> None:
    """
    Guard that ensures promoted objects participate in the RelationIndex.
    """
    rel_index = relation_index or get_relation_index()
    env_opt = os.getenv("PROMOTION_ALLOW_ORPHANS")
    if allow_orphans is not None:
        allow_flag = allow_orphans
    elif env_opt is not None:
        allow_flag = _truthy(env_opt)
    else:
        allow_flag = False
    try:
        oid = UUID(str(object_id))
    except Exception:
        return
    if rel_index.has_any(oid):
        return
    if allow_flag:
        if not override_reason:
            raise OrphanPromotionError(f"Object {oid} missing relations and override reason is required")
        audit_log(
            object_id=str(oid),
            agent="promotion-gate",
            action="promotion.orphan.override",
            trace_id=None,
            details={"reason": override_reason},
        )
        return
    raise OrphanPromotionError(f"Object {oid} has no recorded relations")
