from __future__ import annotations

from pathlib import Path

from app.builderops.epic_run_context_budget import (
    build_3229_pilot_replay,
    evaluate_slice_boundary_context_budget,
)
from app.builderops.epic_run_state import (
    create_epic_run_state,
    load_epic_run_state,
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
            "contract_complete": True,
            "isolated_filescope": True,
            "deterministic_verification": True,
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


def test_lifecycle_and_execution_decisions_are_independent() -> None:
    rotate_inline = _evaluate(
        next_slice={
            "contract_complete": False,
            "isolated_filescope": False,
            "deterministic_verification": False,
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
