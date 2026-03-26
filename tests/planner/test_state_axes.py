from __future__ import annotations

from app.domain.state_axes import (
    CANONICAL_MATURITY_VALUES,
    CANONICAL_REVIEW_STATES,
    build_promotion_transition,
    is_legacy_review_state,
    normalize_plan_state_action,
    normalize_promotion_payload,
    normalize_promotion_target,
    normalize_review_state,
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
    assert args["transition"] == build_promotion_transition(target_maturity="evergreen")


def test_normalize_plan_state_action_maps_legacy_review_mutation_name() -> None:
    action, args = normalize_plan_state_action("update_review_state", {"review_state": "processed"})

    assert action == "set_review_state"
    assert args["review_state"] == "provisional"


def test_resolve_promotion_axes_prefers_explicit_maturity_sink() -> None:
    axes = resolve_promotion_axes(maturity="evergreen", review_state="evergreen")

    assert axes.maturity == "evergreen"
    assert axes.review_state == "reviewed"


def test_normalize_promotion_payload_accepts_transition_shape() -> None:
    payload = {
        "note": {"uuid": "note-1", "path": "vault/Note.md"},
        "action": {"id": "promote.evergreen", "label": "Promote to evergreen"},
        "transition": {"family": "promotion", "target_maturity": " evergreen "},
    }

    normalized = normalize_promotion_payload(payload)

    assert normalized["transition"] == {
        "family": "promotion",
        "target_maturity": "evergreen",
    }
    assert normalized["maturity"] == "evergreen"


def test_legacy_review_state_values_are_compatibility_only() -> None:
    assert is_legacy_review_state("processed") is True
    assert is_legacy_review_state("draft") is False
    assert normalize_review_state("logged") == "provisional"
    assert normalize_review_state("promoted") == "reviewed"


def test_canonical_axis_value_sets_match_state_axis_contract() -> None:
    assert CANONICAL_REVIEW_STATES == (
        "draft",
        "provisional",
        "reviewed",
        "protected",
        "archived",
    )
    assert CANONICAL_MATURITY_VALUES == (
        "raw",
        "draft",
        "developing",
        "stable",
        "evergreen",
    )
