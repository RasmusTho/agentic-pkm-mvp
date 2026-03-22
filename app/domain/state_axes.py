from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CANONICAL_REVIEW_STATES = (
    "draft",
    "provisional",
    "reviewed",
    "protected",
    "archived",
)
CANONICAL_MATURITY_VALUES = (
    "raw",
    "draft",
    "developing",
    "stable",
    "evergreen",
)
LEGACY_REVIEW_STATES = (
    "evergreen",
    "processed",
    "promoted",
    "inbox",
    "logged",
)

_LEGACY_REVIEW_STATE_ALIASES = {
    "evergreen": "reviewed",
    "processed": "provisional",
    "promoted": "reviewed",
    "inbox": "draft",
    "logged": "provisional",
}

_ALLOWED_REVIEW_STATE_VALUES = set(CANONICAL_REVIEW_STATES) | set(LEGACY_REVIEW_STATES)
_ALLOWED_MATURITY_VALUES = set(CANONICAL_MATURITY_VALUES)


@dataclass(frozen=True)
class PromotionAxes:
    maturity: str | None
    review_state: str


def _cleaned_state_value(value: Any) -> str:
    return str(value or "").strip().lower()


def is_legacy_review_state(value: Any) -> bool:
    return _cleaned_state_value(value) in _LEGACY_REVIEW_STATE_ALIASES


def normalize_review_state(value: Any) -> str:
    cleaned = _cleaned_state_value(value)
    if not cleaned:
        return ""
    if cleaned in _LEGACY_REVIEW_STATE_ALIASES:
        return _LEGACY_REVIEW_STATE_ALIASES[cleaned]
    if cleaned in _ALLOWED_REVIEW_STATE_VALUES:
        return cleaned
    return ""


def normalize_maturity(value: Any) -> str:
    cleaned = _cleaned_state_value(value)
    if not cleaned:
        return ""
    if cleaned in _ALLOWED_MATURITY_VALUES:
        return cleaned
    return ""


def legacy_maturity_from_review_state(review_state: Any) -> str:
    cleaned = _cleaned_state_value(review_state)
    if cleaned == "evergreen":
        return "evergreen"
    return ""


def review_state_for_maturity(maturity: Any) -> str:
    cleaned = normalize_maturity(maturity)
    if cleaned in {"stable", "evergreen"}:
        return "reviewed"
    if cleaned:
        return "draft"
    return "provisional"


def normalize_artifact_state_axes(
    fields: Mapping[str, Any],
    *,
    default_review_state: str = "draft",
    workflow_state: Any = None,
) -> dict[str, Any]:
    normalized_fields = dict(fields)
    raw_review_state = _cleaned_state_value(fields.get("review_state"))
    normalized_maturity = normalize_maturity(fields.get("maturity"))
    if not normalized_maturity:
        normalized_maturity = legacy_maturity_from_review_state(raw_review_state)

    normalized_review_state = normalize_review_state(raw_review_state)
    if not normalized_review_state:
        if normalized_maturity:
            normalized_review_state = review_state_for_maturity(normalized_maturity)
        else:
            normalized_review_state = normalize_review_state(default_review_state) or "draft"

    effective_workflow_state = _cleaned_state_value(workflow_state or fields.get("workflow_state"))
    if raw_review_state == "inbox" and not effective_workflow_state:
        effective_workflow_state = "inbox"

    normalized_fields["review_state"] = normalized_review_state
    if normalized_maturity:
        normalized_fields["maturity"] = normalized_maturity
    else:
        normalized_fields.pop("maturity", None)

    if effective_workflow_state:
        normalized_fields["workflow_state"] = effective_workflow_state
    else:
        normalized_fields.pop("workflow_state", None)

    if raw_review_state and is_legacy_review_state(raw_review_state):
        normalized_fields["legacy_review_state"] = raw_review_state
    else:
        normalized_fields.pop("legacy_review_state", None)

    return normalized_fields


def resolve_promotion_axes(*, maturity: Any = None, review_state: Any = None) -> PromotionAxes:
    normalized_maturity = normalize_maturity(maturity)
    if not normalized_maturity:
        normalized_maturity = legacy_maturity_from_review_state(review_state)

    normalized_review_state = normalize_review_state(review_state)
    if normalized_maturity and not normalized_review_state:
        normalized_review_state = review_state_for_maturity(normalized_maturity)
    if not normalized_review_state:
        normalized_review_state = "reviewed" if normalized_maturity else "provisional"

    return PromotionAxes(maturity=normalized_maturity or None, review_state=normalized_review_state)


def normalize_promotion_target(payload: Mapping[str, Any]) -> str:
    transition = payload.get("transition")
    if isinstance(transition, Mapping):
        family = _cleaned_state_value(transition.get("family"))
        target = normalize_maturity(transition.get("target_maturity"))
        if target and (not family or family == "promotion"):
            return target

    maturity = normalize_maturity(payload.get("maturity"))
    if maturity:
        return maturity

    review_state = payload.get("review_state")
    if review_state:
        legacy = legacy_maturity_from_review_state(review_state)
        if legacy:
            return legacy

    action = payload.get("action")
    if isinstance(action, Mapping):
        action_id = _cleaned_state_value(action.get("id"))
        if action_id.startswith("promote."):
            return normalize_maturity(action_id.split(".", 1)[1])

    return ""


def build_promotion_transition(*, target_maturity: str) -> dict[str, str]:
    cleaned = normalize_maturity(target_maturity)
    return {
        "family": "promotion",
        "target_maturity": cleaned,
    }


def normalize_promotion_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized_payload = dict(payload)
    target_maturity = normalize_promotion_target(normalized_payload)
    if target_maturity:
        normalized_payload["maturity"] = target_maturity
        normalized_payload["transition"] = build_promotion_transition(target_maturity=target_maturity)
    elif "transition" in normalized_payload:
        transition = normalized_payload.get("transition")
        if not isinstance(transition, Mapping) or _cleaned_state_value(transition.get("family")) != "promotion":
            normalized_payload.pop("transition", None)

    axes = resolve_promotion_axes(
        maturity=normalized_payload.get("maturity"),
        review_state=normalized_payload.get("review_state"),
    )
    normalized_payload["review_state"] = axes.review_state
    if axes.maturity:
        normalized_payload["maturity"] = axes.maturity
    else:
        normalized_payload.pop("maturity", None)
        normalized_payload.pop("transition", None)
    return normalized_payload


def normalize_plan_state_action(action_name: str | None, args: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    normalized_action = str(action_name or "noop").strip()
    normalized_args = dict(args or {})

    if normalized_action == "update_review_state":
        normalized_action = "set_review_state"
    elif normalized_action == "promote_to_evergreen":
        normalized_action = "request_promotion_transition"
        normalized_args.setdefault("maturity", "evergreen")

    if normalized_action == "request_promotion_transition":
        normalized_args = normalize_promotion_payload(normalized_args)
    elif normalized_action == "set_review_state":
        normalized_args["review_state"] = normalize_review_state(normalized_args.get("review_state")) or "provisional"
    elif normalized_action == "set_maturity":
        normalized_maturity = normalize_maturity(normalized_args.get("maturity"))
        if normalized_maturity:
            normalized_args["maturity"] = normalized_maturity
        else:
            normalized_args.pop("maturity", None)

    return normalized_action, normalized_args


__all__ = [
    "CANONICAL_MATURITY_VALUES",
    "CANONICAL_REVIEW_STATES",
    "LEGACY_REVIEW_STATES",
    "PromotionAxes",
    "build_promotion_transition",
    "is_legacy_review_state",
    "legacy_maturity_from_review_state",
    "normalize_artifact_state_axes",
    "normalize_maturity",
    "normalize_plan_state_action",
    "normalize_promotion_payload",
    "normalize_promotion_target",
    "normalize_review_state",
    "resolve_promotion_axes",
    "review_state_for_maturity",
]
