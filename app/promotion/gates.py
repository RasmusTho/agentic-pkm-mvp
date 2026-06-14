from __future__ import annotations

import os
from typing import Any, Mapping
from uuid import UUID

from app.agents.base.audit import audit_log
from app.events.types import PROMOTION_ORPHAN_OVERRIDE, RELATION_MISSING
from app.stores import get_relation_index
from app.stores.relation_index import extract_semantic_relations, register_relation_candidates


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
            action=PROMOTION_ORPHAN_OVERRIDE,
            trace_id=None,
            details={"reason": override_reason},
        )
        return
    raise OrphanPromotionError(f"Object {oid} has no recorded relations")


def prepare_relations_for_promotion(
    object_id: str | UUID,
    *,
    metadata: Mapping[str, Any] | None = None,
    body: str | None = None,
    relation_index=None,
    require_relations: bool | None = None,
) -> int:
    """
    Extract deterministic relations from frontmatter/body and persist them prior to promotion.
    """
    rel_index = relation_index or get_relation_index()
    require_flag = require_relations if require_relations is not None else _truthy(os.getenv("PROMOTION_REQUIRE_RELATIONS"))
    try:
        oid = UUID(str(object_id))
    except Exception:
        return 0
    candidates = extract_semantic_relations(metadata or {}, body or "")
    added, _ = register_relation_candidates(oid, candidates, relation_index=rel_index)
    if require_flag and added == 0:
        audit_log(
            object_id=str(oid),
            agent="promotion-gate",
            action=RELATION_MISSING,
            trace_id=None,
            details={"reason": "extraction_failed"},
        )
        raise OrphanPromotionError(f"Object {oid} is missing required relations")
    return added
