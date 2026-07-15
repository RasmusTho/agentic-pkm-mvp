from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.builderops.epic_run_context_budget import (
    EpicRunContextBudgetError,
    build_3229_pilot_replay,
    evaluate_slice_boundary_context_budget,
    normalize_context_budget_receipt,
)
from app.builderops.epic_run_state import (
    EpicRunStateError,
    apply_epic_run_update,
    create_epic_run_state,
    load_epic_run_state,
    new_epic_run_state,
    normalize_epic_run_state,
    record_context_budget_receipt,
    save_epic_run_state,
)


def _evaluate(**overrides: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "slice_id": "issue-3798",
        "slice_status": "validated",
        "decision_log_delta": ["keep evaluator observer-only"],
        "open_review_findings": [],
        "external_state_marker": {
            "issue": "3798:open",
            "head_sha": "abc123",
            "ci": "green",
            "review": "clean",
        },
        "context_measurement": {
            "value": 72_000,
            "unit": "tokens",
            "source": "provider_usage",
        },
        "context_pressure": "high",
        "completed_slices_since_checkpoint": 3,
        "repairs": {"implementation": 1, "ci": 0, "review": 0},
        "uncertainty": {"level": "medium", "reasons": ["first observation"]},
        "next_slice": {
            "worker_isolated": True,
            "setup_cost_high": False,
            "merge_risk_low": True,
        },
        "policy": {
            "schema_version": 1,
            "rotate_on_high_context_pressure": True,
            "thin_worker_when_isolated": True,
        },
        "cost_inputs": {},
        "accepted_slice_count": None,
    }
    inputs.update(overrides)
    return evaluate_slice_boundary_context_budget(**inputs)  # type: ignore[arg-type]


def _assert_receipt_rejected_on_update_and_load(
    receipt: dict[str, object],
    *,
    run_id: str,
) -> None:
    state = new_epic_run_state(3229, run_id)
    with pytest.raises(EpicRunContextBudgetError):
        apply_epic_run_update(state, context_budget_receipts=[receipt])

    state["context_budget_receipts"] = [receipt]
    with pytest.raises(EpicRunContextBudgetError):
        normalize_epic_run_state(state)


def test_context_budget_round_trips_in_run_state(tmp_path: Path) -> None:
    state = create_epic_run_state(3229, "measure-context", root=tmp_path)
    receipt = _evaluate()
    updated = record_context_budget_receipt(state, receipt)
    save_epic_run_state(updated, root=tmp_path)

    loaded = load_epic_run_state("measure-context", root=tmp_path)

    assert loaded["context_budget_receipts"] == [receipt]
    assert loaded["dispatcher_status"] == {}
    assert loaded["validation_status"] == {}
    assert loaded["ci_handoffs"] == []
    assert record_context_budget_receipt(loaded, receipt)["context_budget_receipts"] == [
        receipt
    ]


@pytest.mark.parametrize("invalid_version", [True, 1.0])
@pytest.mark.parametrize("surface", ["receipt", "policy", "run_state"])
def test_schema_versions_require_exact_builtin_integers(
    invalid_version: object,
    surface: str,
) -> None:
    if surface == "run_state":
        state = new_epic_run_state(3229, "strict-state-version")
        state["schema_version"] = invalid_version
        with pytest.raises(EpicRunStateError, match="schema_version must be an integer"):
            normalize_epic_run_state(state)
        return

    receipt = deepcopy(_evaluate())
    if surface == "receipt":
        receipt["schema_version"] = invalid_version
    else:
        receipt["policy"]["schema_version"] = invalid_version
        with pytest.raises(EpicRunContextBudgetError):
            _evaluate(policy=receipt["policy"])
    _assert_receipt_rejected_on_update_and_load(
        receipt,
        run_id=f"strict-{surface}-{type(invalid_version).__name__}",
    )


@pytest.mark.parametrize(
    ("surface", "invalid_value"),
    [
        ("context", True),
        ("context", 72_000.0),
        ("accepted_slice_count", True),
        ("accepted_slice_count", 1.0),
        ("model_input_tokens", True),
        ("model_input_tokens", 1.0),
        ("failed_attempts", True),
        ("failed_attempts", 1.0),
    ],
)
def test_integer_measurements_reject_bool_and_float_substitution(
    surface: str,
    invalid_value: object,
) -> None:
    if surface == "context":
        overrides = {
            "context_measurement": {
                "value": invalid_value,
                "unit": "tokens",
                "source": "provider_usage",
            }
        }
    elif surface == "accepted_slice_count":
        overrides = {"accepted_slice_count": invalid_value}
    else:
        overrides = {
            "cost_inputs": {
                surface: {"value": invalid_value, "source": "run_receipts"}
            }
        }
    with pytest.raises(EpicRunContextBudgetError):
        _evaluate(**overrides)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("human_minutes_are_not_monetized", 1),
        ("known_monetary_cost_per_accepted_slice_usd", False),
        ("known_monetary_cost_per_accepted_slice_usd", 0),
    ],
)
def test_derived_cost_values_require_exact_types_on_update_and_load(
    field: str,
    invalid_value: object,
) -> None:
    receipt = deepcopy(
        _evaluate(
            cost_inputs={
                "model_cost_usd": {"value": 0.0, "source": "provider_receipt"}
            },
            accepted_slice_count=1,
        )
    )
    receipt["cost_per_accepted_slice"][field] = invalid_value
    _assert_receipt_rejected_on_update_and_load(
        receipt,
        run_id=f"strict-derived-{field}-{type(invalid_value).__name__}",
    )


def test_cost_numeric_types_round_trip_and_normalize_idempotently() -> None:
    receipt = _evaluate(
        cost_inputs={
            "model_cost_usd": {"value": 2, "source": "provider_receipt"},
            "tool_minutes": {"value": 1.5, "source": "tool_receipt"},
            "model_input_tokens": {"value": 100, "source": "provider_usage"},
        },
        accepted_slice_count=2,
    )

    normalized = normalize_context_budget_receipt(receipt)

    assert normalized == receipt
    assert normalize_context_budget_receipt(normalized) == normalized


def test_lifecycle_and_execution_decisions_are_independent() -> None:
    rotate_inline = _evaluate(
        next_slice={
            "worker_isolated": False,
            "setup_cost_high": True,
            "merge_risk_low": False,
        }
    )
    keep_worker = _evaluate(context_pressure="low")

    assert rotate_inline["recommendations"]["coordinator_lifecycle"] == "checkpoint_rotate"
    assert rotate_inline["recommendations"]["slice_execution"] == "inline"
    assert keep_worker["recommendations"]["coordinator_lifecycle"] == "keep"
    assert keep_worker["recommendations"]["slice_execution"] == "thin_worker"


def test_unknown_context_measurement_does_not_mean_low_pressure() -> None:
    receipt = _evaluate(
        context_measurement={"value": "unknown", "unit": "tokens", "source": "unavailable"},
        context_pressure="low",
    )

    assert receipt["measurements"]["context"]["value"] == "unknown"
    assert receipt["measurements"]["context"]["source"] == "unavailable"
    assert receipt["signals"]["context_pressure"] == "unknown"
    assert receipt["signals"]["completed_slices_since_checkpoint"] == 3
    assert "low_context_pressure" not in receipt["recommendation_reasons"]
    assert "context_measurement_unknown" in receipt["recommendation_reasons"]


def test_3229_pilot_replay_preserves_observed_routes() -> None:
    replay = build_3229_pilot_replay()

    assert replay["slice_issue_numbers"] == [3701, 3707, 3710]
    assert replay["observed_slice_routes"] == ["inline", "inline", "inline"]
    assert replay["implementation_worker_starts"] == 0
    assert replay["coordinator_model_tier"] == "sol"
    assert replay["long_lived_coordinator_cheapest"] == "unknown"
    assert replay["claim"] == "observation_not_cost_proof"


def test_slice_boundary_checkpoint_requires_refresh_not_unconditional_rotation() -> None:
    receipt = _evaluate(
        context_pressure="low",
        previous_external_state_marker={
            "issue": "3798:open",
            "head_sha": "previous",
            "ci": "pending",
            "review": "open",
        },
    )

    checkpoint = receipt["checkpoint"]
    assert checkpoint["slice_status"] == "validated"
    assert checkpoint["decision_log_delta"] == ["keep evaluator observer-only"]
    assert checkpoint["open_review_findings"] == []
    assert checkpoint["external_state"]["changed"] is True
    assert checkpoint["external_state"]["refresh_required"] is True
    assert receipt["recommendations"]["coordinator_lifecycle"] == "keep"


def test_context_routing_cannot_bypass_acceptance_gates() -> None:
    receipt = _evaluate()

    assert receipt["mode"] == "advisory_shadow"
    assert receipt["effects"] == {
        "dispatch_mutations": [],
        "agent_spawns": [],
        "acceptance_mutations": [],
        "ci_mutations": [],
        "review_mutations": [],
        "closure_mutations": [],
    }
    assert receipt["gate_invariants"] == {
        "ci": "unchanged_required",
        "independent_review": "unchanged_required",
        "merge": "unchanged_required",
        "closure": "unchanged_required",
    }


def test_cost_per_accepted_slice_includes_repairs_handoffs_and_unknowns() -> None:
    receipt = _evaluate(
        cost_inputs={
            "model_cost_usd": {"value": 3.0, "source": "provider_receipt"},
            "tool_cost_usd": {"value": "unknown", "source": "unavailable"},
            "wait_minutes": {"value": 12, "source": "ci_handoff"},
            "failed_attempts": {"value": 2, "source": "run_receipts"},
            "implementation_repairs": {"value": 1, "source": "run_receipts"},
            "ci_repairs": {"value": 1, "source": "ci_receipts"},
            "review_repairs": {"value": 2, "source": "review_receipts"},
            "handoffs": {"value": 1, "source": "dispatch_receipts"},
            "worker_starts": {"value": 0, "source": "dispatch_receipts"},
            "human_minutes": {"value": "unknown", "source": "unavailable"},
        },
        accepted_slice_count=2,
    )

    cost = receipt["cost_per_accepted_slice"]
    assert cost["inputs"]["model_cost_usd"]["value"] == 3.0
    assert cost["inputs"]["tool_cost_usd"]["value"] == "unknown"
    assert cost["inputs"]["human_minutes"]["value"] == "unknown"
    assert cost["inputs"]["review_repairs"]["value"] == 2
    assert cost["inputs"]["handoffs"]["value"] == 1
    assert cost["inputs"]["worker_starts"]["value"] == 0
    assert cost["accepted_slice_count"] == {"value": 2, "source": "caller"}
    assert cost["known_monetary_cost_per_accepted_slice_usd"] == 1.5
    assert cost["completeness"] == "partial"

    without_denominator = _evaluate(cost_inputs={}, accepted_slice_count=None)
    assert without_denominator["cost_per_accepted_slice"]["accepted_slice_count"]["value"] == "unknown"
    assert (
        without_denominator["cost_per_accepted_slice"]
        ["known_monetary_cost_per_accepted_slice_usd"]
        == "unknown"
    )


@pytest.mark.parametrize(
    "malformation",
    [
        "accepted_authority",
        "dispatch_effect",
        "bypassed_gate",
        "missing_measurement",
        "extra_measurement_field",
        "missing_signal",
        "missing_next_slice_input",
        "extra_policy_field",
        "invalid_recommendation",
        "missing_checkpoint_field",
        "fractional_accepted_count",
        "unknown_context_with_low_pressure",
    ],
)
def test_malformed_or_authority_bearing_receipts_cannot_persist(
    malformation: str,
) -> None:
    receipt = deepcopy(_evaluate())
    if malformation == "accepted_authority":
        receipt["accepted"] = True
    elif malformation == "dispatch_effect":
        receipt["effects"]["dispatch_mutations"] = [{"action": "start"}]
    elif malformation == "bypassed_gate":
        receipt["gate_invariants"]["ci"] = "bypassed"
    elif malformation == "missing_measurement":
        del receipt["measurements"]["context"]
    elif malformation == "extra_measurement_field":
        receipt["measurements"]["context"]["confidence"] = "guessed"
    elif malformation == "missing_signal":
        del receipt["signals"]["repairs"]
    elif malformation == "missing_next_slice_input":
        del receipt["next_slice"]["merge_risk_low"]
    elif malformation == "extra_policy_field":
        receipt["policy"]["universal_token_threshold"] = 1000
    elif malformation == "invalid_recommendation":
        receipt["recommendations"]["coordinator_lifecycle"] = "rotate_now"
    elif malformation == "missing_checkpoint_field":
        del receipt["checkpoint"]["open_review_findings"]
    elif malformation == "fractional_accepted_count":
        receipt["cost_per_accepted_slice"]["accepted_slice_count"] = {
            "value": 1.5,
            "source": "caller",
        }
    elif malformation == "unknown_context_with_low_pressure":
        receipt["measurements"]["context"] = {
            "value": "unknown",
            "unit": "tokens",
            "source": "unavailable",
        }
        receipt["signals"]["context_pressure"] = "low"

    state = new_epic_run_state(3229, f"reject-{malformation}")
    with pytest.raises(EpicRunContextBudgetError):
        apply_epic_run_update(state, context_budget_receipts=[receipt])

    state_with_untrusted_receipt = dict(state)
    state_with_untrusted_receipt["context_budget_receipts"] = [receipt]
    with pytest.raises(EpicRunContextBudgetError):
        normalize_epic_run_state(state_with_untrusted_receipt)


@pytest.mark.parametrize("accepted_slice_count", [False, 1.5, -1])
def test_evaluator_rejects_non_integer_or_negative_accepted_slice_denominator(
    accepted_slice_count: object,
) -> None:
    with pytest.raises(EpicRunContextBudgetError):
        _evaluate(accepted_slice_count=accepted_slice_count)


def test_zero_accepted_slices_preserves_denominator_without_division() -> None:
    receipt = _evaluate(
        accepted_slice_count=0,
        cost_inputs={
            "model_cost_usd": {"value": 3.0, "source": "provider_receipt"}
        },
    )

    cost = receipt["cost_per_accepted_slice"]
    assert cost["accepted_slice_count"] == {"value": 0, "source": "caller"}
    assert cost["known_monetary_cost_per_accepted_slice_usd"] == "unknown"


def test_receipt_recommendations_are_reconstructed_from_persisted_evidence() -> None:
    receipt = _evaluate(
        context_pressure="low",
        uncertainty={"level": "low", "reasons": []},
    )
    assert receipt["next_slice"] == {
        "merge_risk_low": True,
        "setup_cost_high": False,
        "worker_isolated": True,
    }
    assert receipt["recommendations"] == {
        "coordinator_lifecycle": "keep",
        "slice_execution": "thin_worker",
        "model_tier": "luna",
    }

    normalized = normalize_context_budget_receipt(receipt)
    assert normalized == receipt
    assert normalize_context_budget_receipt(normalized) == normalized

    for field, contradiction in (
        ("coordinator_lifecycle", "checkpoint_rotate"),
        ("slice_execution", "inline"),
        ("model_tier", "sol"),
    ):
        contradictory = deepcopy(receipt)
        contradictory["recommendations"][field] = contradiction
        state = new_epic_run_state(3229, f"contradict-{field}")
        with pytest.raises(EpicRunContextBudgetError):
            apply_epic_run_update(
                state,
                context_budget_receipts=[contradictory],
            )
        state["context_budget_receipts"] = [contradictory]
        with pytest.raises(EpicRunContextBudgetError):
            normalize_epic_run_state(state)

    contradictory_reasons = deepcopy(receipt)
    contradictory_reasons["recommendation_reasons"] = ["looks_cheaper"]
    with pytest.raises(EpicRunContextBudgetError):
        apply_epic_run_update(
            new_epic_run_state(3229, "contradict-reasons"),
            context_budget_receipts=[contradictory_reasons],
        )


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("surface", ["context", "cost"])
def test_non_finite_numbers_are_rejected_by_evaluator_and_persistence(
    non_finite: float,
    surface: str,
) -> None:
    if surface == "context":
        evaluator_overrides = {
            "context_measurement": {
                "value": non_finite,
                "unit": "tokens",
                "source": "provider_usage",
            }
        }
    else:
        evaluator_overrides = {
            "cost_inputs": {
                "model_cost_usd": {
                    "value": non_finite,
                    "source": "provider_receipt",
                }
            }
        }
    with pytest.raises(EpicRunContextBudgetError):
        _evaluate(**evaluator_overrides)

    receipt = deepcopy(_evaluate())
    if surface == "context":
        receipt["measurements"]["context"]["value"] = non_finite
    else:
        receipt["cost_per_accepted_slice"]["inputs"]["model_cost_usd"][
            "value"
        ] = non_finite
    state = new_epic_run_state(3229, f"non-finite-{surface}")
    with pytest.raises(EpicRunContextBudgetError):
        apply_epic_run_update(state, context_budget_receipts=[receipt])
    state["context_budget_receipts"] = [receipt]
    with pytest.raises(EpicRunContextBudgetError):
        normalize_epic_run_state(state)
