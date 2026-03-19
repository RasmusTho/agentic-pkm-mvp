from __future__ import annotations

from typing import Any, Mapping


def normalize_promotion_target(payload: Mapping[str, Any]) -> str:
    transition = payload.get("transition")
    if isinstance(transition, Mapping):
        target = transition.get("target_maturity")
        if target:
            return str(target).strip()
    maturity = payload.get("maturity")
    if maturity:
        return str(maturity).strip()
    action = payload.get("action")
    if isinstance(action, Mapping):
        action_id = action.get("id")
        if action_id:
            return str(action_id).strip()
    return ""


def build_promotion_transition(*, target_maturity: str) -> dict[str, str]:
    cleaned = str(target_maturity).strip()
    return {
        "family": "promotion",
        "target_maturity": cleaned,
    }


def review_state_for_maturity(maturity: str) -> str:
    cleaned = str(maturity).strip().lower()
    if cleaned == "evergreen":
        return "reviewed"
    if cleaned:
        return cleaned
    return "processed"


__all__ = ["normalize_promotion_target", "build_promotion_transition", "review_state_for_maturity"]
