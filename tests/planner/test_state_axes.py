from __future__ import annotations

from app.domain.state_axes import (
    normalize_plan_state_action,
    normalize_promotion_target,
    resolve_promotion_axes,
)


def test_normalize_promotion_target_accepts_action_id_fallback() -> None:
    payload = {"action": {"id": "promote.evergreen"}}

    assert normalize_promotion_target(payload) == "evergreen"


def test_normalize_plan_state_action_preserves_legacy_promote_name_as_internal_transition() -> None:
    action, args = normalize_plan_state_action("promote_to_evergreen", {})

    assert action == "request_promotion_transition"
    assert args["maturity"] == "evergreen"
    assert args["review_state"] == "reviewed"


def test_resolve_promotion_axes_prefers_explicit_maturity_sink() -> None:
    axes = resolve_promotion_axes(maturity="evergreen", review_state="evergreen")

    assert axes.maturity == "evergreen"
    assert axes.review_state == "reviewed"
