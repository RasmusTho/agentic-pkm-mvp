from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PromotionAxes:
    maturity: str | None
    review_state: str


def normalize_review_state(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return ""
    if cleaned == "evergreen":
        return "reviewed"
    return cleaned


def normalize_maturity(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    return cleaned


def legacy_maturity_from_review_state(review_state: Any) -> str:
    cleaned = str(review_state or "").strip().lower()
    if cleaned == "evergreen":
        return "evergreen"
    return ""


def review_state_for_maturity(maturity: Any) -> str:
    cleaned = normalize_maturity(maturity)
    if cleaned == "evergreen":
        return "reviewed"
    if cleaned:
        return cleaned
    return "processed"


def resolve_promotion_axes(*, maturity: Any = None, review_state: Any = None) -> PromotionAxes:
    normalized_maturity = normalize_maturity(maturity)
    if not normalized_maturity:
        normalized_maturity = legacy_maturity_from_review_state(review_state)

    normalized_review_state = normalize_review_state(review_state)
    if normalized_maturity and not normalized_review_state:
        normalized_review_state = review_state_for_maturity(normalized_maturity)
    if not normalized_review_state:
        normalized_review_state = "processed"

    return PromotionAxes(maturity=normalized_maturity or None, review_state=normalized_review_state)


def normalize_promotion_target(payload: Mapping[str, Any]) -> str:
    transition = payload.get("transition")
    if isinstance(transition, Mapping):
        target = transition.get("target_maturity")
        if target:
            return normalize_maturity(target)

    maturity = payload.get("maturity")
    if maturity:
        return normalize_maturity(maturity)

    review_state = payload.get("review_state")
    if review_state:
        legacy = legacy_maturity_from_review_state(review_state)
        if legacy:
            return legacy

    action = payload.get("action")
    if isinstance(action, Mapping):
        action_id = str(action.get("id") or "").strip().lower()
        if action_id.startswith("promote."):
            return normalize_maturity(action_id.split(".", 1)[1])

    return ""


def build_promotion_transition(*, target_maturity: str) -> dict[str, str]:
    cleaned = normalize_maturity(target_maturity)
    return {
        "family": "promotion",
        "target_maturity": cleaned,
    }


def normalize_plan_state_action(action_name: str | None, args: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    normalized_action = str(action_name or "noop").strip()
    normalized_args = dict(args or {})

    if normalized_action == "update_review_state":
        normalized_action = "set_review_state"
    elif normalized_action == "promote_to_evergreen":
        normalized_action = "request_promotion_transition"
        normalized_args.setdefault("maturity", "evergreen")

    if normalized_action == "request_promotion_transition":
        axes = resolve_promotion_axes(
            maturity=normalized_args.get("maturity"),
            review_state=normalized_args.get("review_state"),
        )
        normalized_args["review_state"] = axes.review_state
        if axes.maturity:
            normalized_args["maturity"] = axes.maturity
    elif normalized_action == "set_review_state":
        normalized_args["review_state"] = normalize_review_state(normalized_args.get("review_state")) or "processed"
    elif normalized_action == "set_maturity":
        normalized_maturity = normalize_maturity(normalized_args.get("maturity"))
        if normalized_maturity:
            normalized_args["maturity"] = normalized_maturity
        else:
            normalized_args.pop("maturity", None)

    return normalized_action, normalized_args


__all__ = [
    "PromotionAxes",
    "build_promotion_transition",
    "legacy_maturity_from_review_state",
    "normalize_maturity",
    "normalize_plan_state_action",
    "normalize_promotion_target",
    "normalize_review_state",
    "resolve_promotion_axes",
    "review_state_for_maturity",
]
