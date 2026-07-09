"""Observe-only CKM/Kvasir projection reevaluation helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.builderops.models import BuilderOpsValidationError, validate_source_refs

CKM_PROJECTION_TYPES = frozenset(
    {
        "capability_maturity",
        "missing_evidence",
        "stale_assessment",
        "unlinked_artifact",
        "gap_tension",
    }
)
CKM_REEVALUATION_ROUTES = frozenset(
    {
        "issue_candidate",
        "debt_fitness_candidate",
        "promotion_proposal",
        "discard_supersession",
    }
)


class CkmReevaluationError(BuilderOpsValidationError):
    """Raised when CKM reevaluation input is malformed."""


def build_ckm_reevaluation_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Classify CKM projection findings without granting authority."""

    if not isinstance(payload, Mapping):
        raise CkmReevaluationError("CKM reevaluation payload must be an object")

    projections = _normalize_projections(payload.get("projections", []))
    projection_index = {item["id"]: item for item in projections}
    actions = _normalize_actions(
        payload.get("actions", payload.get("candidate", [])),
        projection_index,
    )

    return {
        "observe_only": True,
        "mutations_performed": False,
        "authority": {
            "projection_only": True,
            "product_runtime_authority": False,
            "requires_normal_issue_pr_promotion_gate": True,
            "ckm_parent": "#3138",
        },
        "mutation_channels": {
            "git_push": False,
            "github_label": False,
            "github_merge": False,
            "github_project": False,
            "product_runtime": False,
            "owner_doc_writeback": False,
            "runtime_memory": False,
        },
        "projection": projections,
        "candidate": actions,
        "routing_outcomes": sorted(CKM_REEVALUATION_ROUTES),
        "receipt_body": _receipt_body(projections, actions),
    }


def _normalize_projections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CkmReevaluationError("projections must be a list")
    projections: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CkmReevaluationError(f"projections[{index}] must be an object")
        projection_id = _required_string(item.get("id"), f"projections[{index}].id")
        if projection_id in seen_ids:
            raise CkmReevaluationError(f"duplicate projection id: {projection_id}")
        seen_ids.add(projection_id)
        projection_type = _required_string(
            item.get("projection_type"),
            f"projections[{index}].projection_type",
        )
        if projection_type not in CKM_PROJECTION_TYPES:
            raise CkmReevaluationError(
                f"projections[{index}].projection_type must be one of "
                f"{sorted(CKM_PROJECTION_TYPES)}"
            )
        projections.append({
            "id": projection_id,
            "projection_type": projection_type,
            "summary": _required_string(
                item.get("summary"),
                f"projections[{index}].summary",
            ),
            "watermark": _required_string(
                item.get("watermark"),
                f"projections[{index}].watermark",
            ),
            "source_refs": _validated_source_refs(
                item.get("source_refs"),
                f"projections[{index}].source_refs",
            ),
        })
    return projections


def _normalize_actions(
    value: Any,
    projection_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CkmReevaluationError("actions must be a list")
    actions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CkmReevaluationError(f"actions[{index}] must be an object")
        action_id = _required_string(item.get("id"), f"actions[{index}].id")
        if action_id in seen_ids:
            raise CkmReevaluationError(f"duplicate action id: {action_id}")
        seen_ids.add(action_id)
        route = _required_string(item.get("route"), f"actions[{index}].route")
        if route not in CKM_REEVALUATION_ROUTES:
            raise CkmReevaluationError(
                f"actions[{index}].route must be one of "
                f"{sorted(CKM_REEVALUATION_ROUTES)}"
            )
        source_projection_id = _required_string(
            item.get("source_projection_id"),
            f"actions[{index}].source_projection_id",
        )
        source_projection = projection_index.get(source_projection_id)
        if source_projection is None:
            raise CkmReevaluationError(
                f"actions[{index}].source_projection_id references unknown projection"
            )
        source_refs = _validated_source_refs(
            item.get("source_refs"),
            f"actions[{index}].source_refs",
        )
        projection_ref = _required_string(
            item.get("source_projection_ref"),
            f"actions[{index}].source_projection_ref",
        )
        if not any(ref.get("ref") == projection_ref for ref in source_refs):
            raise CkmReevaluationError(
                f"actions[{index}].source_refs must include source_projection_ref"
            )
        projection_refs = {
            ref.get("ref")
            for ref in source_projection.get("source_refs", [])
            if isinstance(ref, Mapping)
        }
        if projection_ref not in projection_refs:
            raise CkmReevaluationError(
                f"actions[{index}].source_projection_ref must match the source projection"
            )
        watermark = _required_string(item.get("watermark"), f"actions[{index}].watermark")
        if watermark != source_projection.get("watermark"):
            raise CkmReevaluationError(
                f"actions[{index}].watermark must match the source projection watermark"
            )
        actions.append({
            "id": action_id,
            "route": route,
            "summary": _required_string(item.get("summary"), f"actions[{index}].summary"),
            "source_projection_id": source_projection_id,
            "source_projection_ref": projection_ref,
            "watermark": watermark,
            "source_refs": source_refs,
            "recommendation": _required_string(
                item.get("recommendation"),
                f"actions[{index}].recommendation",
            ),
        })
    return actions


def _validated_source_refs(value: Any, field: str) -> list[dict[str, Any]]:
    try:
        validate_source_refs(value, field)
    except BuilderOpsValidationError as exc:
        raise CkmReevaluationError(str(exc)) from exc
    if not isinstance(value, list):  # validate_source_refs guards this.
        raise CkmReevaluationError(f"{field} must be a non-empty list")
    return list(value)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CkmReevaluationError(f"{field} must be a non-empty string")
    return value.strip()


def _receipt_body(
    projections: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    routes = ", ".join(f"{item['id']}={item['route']}" for item in actions)
    return (
        "CKM reevaluation observe-only report: "
        f"projection_only=true, projections={len(projections)}, candidate={len(actions)}"
        + (f"; routes: {routes}." if routes else ".")
    )


__all__ = [
    "CKM_PROJECTION_TYPES",
    "CKM_REEVALUATION_ROUTES",
    "CkmReevaluationError",
    "build_ckm_reevaluation_report",
]
