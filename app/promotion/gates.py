from __future__ import annotations

import os
from uuid import UUID

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
        policy = (os.getenv("PROMOTION_ORPHAN_POLICY") or "log").strip().lower()
        allow_flag = policy != "block"
    try:
        oid = UUID(str(object_id))
    except Exception:
        return
    if rel_index.has_any(oid) or allow_flag:
        return
    raise OrphanPromotionError(f"Object {oid} has no recorded relations")
