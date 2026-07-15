"""Observer-only context-budget receipts for epic slice boundaries."""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

RECEIPT_SCHEMA_NAME = "epic_run_context_budget_receipt"
RECEIPT_SCHEMA_VERSION = 1
POLICY_SCHEMA_VERSION = 1
UNKNOWN = "unknown"

CONTEXT_PRESSURES = {"low", "high", UNKNOWN}
UNCERTAINTY_LEVELS = {"low", "medium", "high", UNKNOWN}
MONETARY_COST_FIELDS = (
    "model_cost_usd",
    "tool_cost_usd",
    "wait_cost_usd",
)
COST_INPUT_FIELDS = (
    *MONETARY_COST_FIELDS,
    "model_input_tokens",
    "model_output_tokens",
    "tool_minutes",
    "wait_minutes",
    "failed_attempts",
    "implementation_repairs",
    "ci_repairs",
    "review_repairs",
    "handoffs",
    "worker_starts",
    "human_minutes",
)


class EpicRunContextBudgetError(ValueError):
    """Raised when an advisory context-budget observation is malformed."""


def evaluate_slice_boundary_context_budget(
    *,
    slice_id: str,
    slice_status: str,
    decision_log_delta: list[Any],
    open_review_findings: list[Any],
    external_state_marker: Mapping[str, Any],
    context_measurement: Mapping[str, Any],
    context_pressure: str,
    completed_slices_since_checkpoint: int,
    repairs: Mapping[str, int],
    uncertainty: Mapping[str, Any],
    next_slice: Mapping[str, Any],
    policy: Mapping[str, Any],
    cost_inputs: Mapping[str, Any],
    accepted_slice_count: int | None,
    previous_external_state_marker: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one slice boundary without executing any recommendation.

    All policy inputs are explicit and versioned. The returned receipt has no
    mutation instructions and cannot claim acceptance or gate completion.
    """

    normalized_policy = _normalize_policy(policy)
    normalized_context = _normalize_measurement(
        context_measurement,
        "context_measurement",
        expected_unit="tokens",
    )
    normalized_pressure = _enum(context_pressure, CONTEXT_PRESSURES, "context_pressure")
    if normalized_context["value"] == UNKNOWN:
        normalized_pressure = UNKNOWN
    if (
        isinstance(completed_slices_since_checkpoint, bool)
        or not isinstance(completed_slices_since_checkpoint, int)
        or completed_slices_since_checkpoint < 0
    ):
        raise EpicRunContextBudgetError(
            "completed_slices_since_checkpoint must be a non-negative integer"
        )
    normalized_uncertainty = _normalize_uncertainty(uncertainty)
    normalized_next_slice = _normalize_next_slice(next_slice)
    normalized_repairs = _normalize_repairs(repairs)
    marker = _json_object(external_state_marker, "external_state_marker")
    previous_marker = (
        None
        if previous_external_state_marker is None
        else _json_object(previous_external_state_marker, "previous_external_state_marker")
    )
    external_state_changed = previous_marker is not None and marker != previous_marker

    recommendations, reasons = _build_recommendations_and_reasons(
        context_pressure=normalized_pressure,
        uncertainty=normalized_uncertainty,
        next_slice=normalized_next_slice,
        policy=normalized_policy,
        external_state_changed=external_state_changed,
    )

    return {
        "schema_name": RECEIPT_SCHEMA_NAME,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "mode": "advisory_shadow",
        "slice_id": _required_string(slice_id, "slice_id"),
        "measurements": {"context": normalized_context},
        "signals": {
            "context_pressure": normalized_pressure,
            "completed_slices_since_checkpoint": completed_slices_since_checkpoint,
            "repairs": normalized_repairs,
            "uncertainty": normalized_uncertainty,
        },
        "next_slice": normalized_next_slice,
        "policy": normalized_policy,
        "checkpoint": {
            "slice_status": _required_string(slice_status, "slice_status"),
            "decision_log_delta": _json_list(decision_log_delta, "decision_log_delta"),
            "open_review_findings": _json_list(
                open_review_findings,
                "open_review_findings",
            ),
            "external_state": {
                "marker": marker,
                "previous_marker": previous_marker,
                "changed": external_state_changed,
                "refresh_required": external_state_changed,
            },
        },
        "recommendations": recommendations,
        "recommendation_reasons": reasons,
        "cost_per_accepted_slice": _build_cost_observation(
            cost_inputs,
            accepted_slice_count=accepted_slice_count,
        ),
        "effects": {
            "dispatch_mutations": [],
            "agent_spawns": [],
            "acceptance_mutations": [],
            "ci_mutations": [],
            "review_mutations": [],
            "closure_mutations": [],
        },
        "gate_invariants": {
            "ci": "unchanged_required",
            "independent_review": "unchanged_required",
            "merge": "unchanged_required",
            "closure": "unchanged_required",
        },
    }


def normalize_context_budget_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a receipt before it enters dispatcher-backed epic run-state."""

    normalized = _json_object(receipt, "context_budget_receipt")
    expected_top_level = {
        "schema_name",
        "schema_version",
        "mode",
        "slice_id",
        "measurements",
        "signals",
        "next_slice",
        "policy",
        "checkpoint",
        "recommendations",
        "recommendation_reasons",
        "cost_per_accepted_slice",
        "effects",
        "gate_invariants",
    }
    if set(normalized) != expected_top_level:
        raise EpicRunContextBudgetError(
            "context-budget receipt fields must be exactly "
            f"{sorted(expected_top_level)}"
        )
    if normalized.get("schema_name") != RECEIPT_SCHEMA_NAME:
        raise EpicRunContextBudgetError("unsupported context-budget receipt schema_name")
    if normalized.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise EpicRunContextBudgetError("unsupported context-budget receipt schema_version")
    if normalized.get("mode") != "advisory_shadow":
        raise EpicRunContextBudgetError("context-budget receipt must be advisory_shadow")
    normalized["slice_id"] = _required_string(normalized["slice_id"], "slice_id")

    measurements = _json_object(normalized["measurements"], "measurements")
    if set(measurements) != {"context"}:
        raise EpicRunContextBudgetError("measurements must contain exactly context")
    normalized_context = _normalize_measurement(
        measurements["context"],
        "measurements.context",
        expected_unit="tokens",
    )
    normalized["measurements"] = {"context": normalized_context}

    signals = _json_object(normalized["signals"], "signals")
    if set(signals) != {
        "context_pressure",
        "completed_slices_since_checkpoint",
        "repairs",
        "uncertainty",
    }:
        raise EpicRunContextBudgetError(
            "signals fields must be context_pressure, "
            "completed_slices_since_checkpoint, repairs, and uncertainty"
        )
    pressure = _enum(
        signals["context_pressure"],
        CONTEXT_PRESSURES,
        "signals.context_pressure",
    )
    if normalized_context["value"] == UNKNOWN and pressure != UNKNOWN:
        raise EpicRunContextBudgetError(
            "unknown context measurement requires unknown context_pressure"
        )
    completed_slices = signals["completed_slices_since_checkpoint"]
    if (
        isinstance(completed_slices, bool)
        or not isinstance(completed_slices, int)
        or completed_slices < 0
    ):
        raise EpicRunContextBudgetError(
            "signals.completed_slices_since_checkpoint must be a non-negative integer"
        )
    normalized["signals"] = {
        "context_pressure": pressure,
        "completed_slices_since_checkpoint": completed_slices,
        "repairs": _normalize_repairs(signals["repairs"]),
        "uncertainty": _normalize_uncertainty(signals["uncertainty"]),
    }
    normalized["next_slice"] = _normalize_next_slice(normalized["next_slice"])
    normalized["policy"] = _normalize_policy(normalized["policy"])

    recommendations = _json_object(normalized["recommendations"], "recommendations")
    if set(recommendations) != {
        "coordinator_lifecycle",
        "slice_execution",
        "model_tier",
    }:
        raise EpicRunContextBudgetError(
            "recommendations fields must be coordinator_lifecycle, "
            "slice_execution, and model_tier"
        )
    if recommendations.get("coordinator_lifecycle") not in {
        "keep",
        "checkpoint_rotate",
    }:
        raise EpicRunContextBudgetError("invalid coordinator lifecycle recommendation")
    if recommendations.get("slice_execution") not in {"inline", "thin_worker"}:
        raise EpicRunContextBudgetError("invalid slice execution recommendation")
    if recommendations.get("model_tier") not in {"luna", "terra", "sol"}:
        raise EpicRunContextBudgetError("invalid model tier recommendation")
    recommendation_reasons = [
        _required_string(item, f"recommendation_reasons[{index}]")
        for index, item in enumerate(
            _json_list(normalized["recommendation_reasons"], "recommendation_reasons")
        )
    ]

    normalized["checkpoint"] = _normalize_checkpoint(normalized["checkpoint"])
    expected_recommendations, expected_reasons = _build_recommendations_and_reasons(
        context_pressure=normalized["signals"]["context_pressure"],
        uncertainty=normalized["signals"]["uncertainty"],
        next_slice=normalized["next_slice"],
        policy=normalized["policy"],
        external_state_changed=normalized["checkpoint"]["external_state"]["changed"],
    )
    if recommendations != expected_recommendations:
        raise EpicRunContextBudgetError(
            "recommendations contradict the persisted evaluator evidence"
        )
    if recommendation_reasons != expected_reasons:
        raise EpicRunContextBudgetError(
            "recommendation_reasons contradict the persisted evaluator evidence"
        )
    normalized["recommendations"] = expected_recommendations
    normalized["recommendation_reasons"] = expected_reasons
    normalized["cost_per_accepted_slice"] = _normalize_cost_observation(
        normalized["cost_per_accepted_slice"]
    )

    expected_effects: dict[str, list[Any]] = {
        "dispatch_mutations": [],
        "agent_spawns": [],
        "acceptance_mutations": [],
        "ci_mutations": [],
        "review_mutations": [],
        "closure_mutations": [],
    }
    if normalized.get("effects") != expected_effects:
        raise EpicRunContextBudgetError("advisory receipt cannot carry mutations")
    normalized["effects"] = expected_effects

    expected_gate_invariants = {
        "ci": "unchanged_required",
        "independent_review": "unchanged_required",
        "merge": "unchanged_required",
        "closure": "unchanged_required",
    }
    if normalized.get("gate_invariants") != expected_gate_invariants:
        raise EpicRunContextBudgetError(
            "context-budget receipt cannot weaken or replace gate invariants"
        )
    normalized["gate_invariants"] = expected_gate_invariants
    return normalized


def build_3229_pilot_replay() -> dict[str, Any]:
    """Return the bounded pilot facts without making an unmeasured cost claim."""

    return {
        "schema_name": "epic_run_context_budget_pilot_replay",
        "schema_version": 1,
        "source_epic_issue": 3229,
        "slice_issue_numbers": [3701, 3707, 3710],
        "observed_slice_routes": ["inline", "inline", "inline"],
        "implementation_worker_starts": 0,
        "coordinator_model_tier": "sol",
        "long_lived_coordinator_cheapest": UNKNOWN,
        "claim": "observation_not_cost_proof",
    }


def _normalize_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_object(policy, "policy")
    expected = {
        "schema_version",
        "rotate_on_high_context_pressure",
        "thin_worker_when_isolated",
    }
    if set(normalized) != expected:
        raise EpicRunContextBudgetError(
            f"policy fields must be exactly {sorted(expected)}"
        )
    if normalized["schema_version"] != POLICY_SCHEMA_VERSION:
        raise EpicRunContextBudgetError("unsupported policy schema_version")
    for field in ("rotate_on_high_context_pressure", "thin_worker_when_isolated"):
        if not isinstance(normalized[field], bool):
            raise EpicRunContextBudgetError(f"policy.{field} must be boolean")
    return normalized


def _normalize_measurement(
    measurement: Mapping[str, Any],
    field: str,
    *,
    expected_unit: str | None = None,
) -> dict[str, Any]:
    normalized = _json_object(measurement, field)
    if set(normalized) != {"value", "unit", "source"}:
        raise EpicRunContextBudgetError(
            f"{field} fields must be exactly value, unit, source"
        )
    value = normalized["value"]
    if value != UNKNOWN and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not _is_finite_number(value)
        or value < 0
    ):
        raise EpicRunContextBudgetError(
            f"{field}.value must be finite, non-negative, or unknown"
        )
    normalized["source"] = _required_string(normalized["source"], f"{field}.source")
    normalized["unit"] = _required_string(normalized["unit"], f"{field}.unit")
    if expected_unit is not None and normalized["unit"] != expected_unit:
        raise EpicRunContextBudgetError(f"{field}.unit must be {expected_unit}")
    return normalized


def _normalize_uncertainty(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _json_object(value, "uncertainty")
    if set(normalized) != {"level", "reasons"}:
        raise EpicRunContextBudgetError("uncertainty fields must be level and reasons")
    normalized["level"] = _enum(
        normalized["level"],
        UNCERTAINTY_LEVELS,
        "uncertainty.level",
    )
    normalized["reasons"] = [
        _required_string(item, f"uncertainty.reasons[{index}]")
        for index, item in enumerate(_json_list(normalized["reasons"], "uncertainty.reasons"))
    ]
    return normalized


def _normalize_next_slice(value: Mapping[str, Any]) -> dict[str, bool]:
    normalized = _json_object(value, "next_slice")
    expected = {
        "worker_isolated",
        "setup_cost_high",
        "merge_risk_low",
    }
    if set(normalized) != expected:
        raise EpicRunContextBudgetError(
            f"next_slice fields must be exactly {sorted(expected)}"
        )
    for field in expected:
        if not isinstance(normalized[field], bool):
            raise EpicRunContextBudgetError(f"next_slice.{field} must be boolean")
    return {field: normalized[field] for field in sorted(expected)}


def _normalize_repairs(value: Mapping[str, int]) -> dict[str, int]:
    normalized = _json_object(value, "repairs")
    expected = {"implementation", "ci", "review"}
    if set(normalized) != expected:
        raise EpicRunContextBudgetError(f"repairs fields must be exactly {sorted(expected)}")
    for field in expected:
        count = normalized[field]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise EpicRunContextBudgetError(f"repairs.{field} must be non-negative")
    return {field: normalized[field] for field in sorted(expected)}


def _recommend_model_tier(
    uncertainty: Mapping[str, Any],
    next_slice: Mapping[str, bool],
) -> str:
    if uncertainty["level"] in {"high", UNKNOWN}:
        return "sol"
    if uncertainty["level"] == "low" and next_slice["merge_risk_low"]:
        return "luna"
    return "terra"


def _build_recommendations_and_reasons(
    *,
    context_pressure: str,
    uncertainty: Mapping[str, Any],
    next_slice: Mapping[str, bool],
    policy: Mapping[str, Any],
    external_state_changed: bool,
) -> tuple[dict[str, str], list[str]]:
    lifecycle = "keep"
    reasons: list[str] = []
    if context_pressure == UNKNOWN:
        reasons.append("context_measurement_unknown")
    elif context_pressure == "low":
        reasons.append("low_context_pressure")
    elif policy["rotate_on_high_context_pressure"]:
        lifecycle = "checkpoint_rotate"
        reasons.append("explicit_policy_high_context_pressure")
    else:
        reasons.append("high_context_pressure_observed_policy_does_not_rotate")

    if external_state_changed:
        reasons.append("external_state_refresh_required")

    thin_worker_candidate = (
        next_slice["worker_isolated"]
        and not next_slice["setup_cost_high"]
        and next_slice["merge_risk_low"]
    )
    execution = (
        "thin_worker"
        if policy["thin_worker_when_isolated"] and thin_worker_candidate
        else "inline"
    )
    reasons.append(
        "isolated_thin_worker_candidate"
        if execution == "thin_worker"
        else "inline_by_explicit_slice_evidence"
    )

    model_tier = _recommend_model_tier(uncertainty, next_slice)
    reasons.append(f"model_tier_{model_tier}")
    return (
        {
            "coordinator_lifecycle": lifecycle,
            "slice_execution": execution,
            "model_tier": model_tier,
        },
        reasons,
    )


def _normalize_checkpoint(value: Mapping[str, Any]) -> dict[str, Any]:
    checkpoint = _json_object(value, "checkpoint")
    if set(checkpoint) != {
        "slice_status",
        "decision_log_delta",
        "open_review_findings",
        "external_state",
    }:
        raise EpicRunContextBudgetError(
            "checkpoint fields must be slice_status, decision_log_delta, "
            "open_review_findings, and external_state"
        )
    external_state = _json_object(
        checkpoint["external_state"],
        "checkpoint.external_state",
    )
    if set(external_state) != {
        "marker",
        "previous_marker",
        "changed",
        "refresh_required",
    }:
        raise EpicRunContextBudgetError(
            "checkpoint.external_state fields must be marker, previous_marker, "
            "changed, and refresh_required"
        )
    marker = _json_object(external_state["marker"], "checkpoint.external_state.marker")
    previous_raw = external_state["previous_marker"]
    previous = (
        None
        if previous_raw is None
        else _json_object(previous_raw, "checkpoint.external_state.previous_marker")
    )
    expected_changed = previous is not None and marker != previous
    if external_state["changed"] is not expected_changed:
        raise EpicRunContextBudgetError(
            "checkpoint.external_state.changed does not match the markers"
        )
    if external_state["refresh_required"] is not expected_changed:
        raise EpicRunContextBudgetError(
            "changed external state must require refresh, and unchanged state must not"
        )
    return {
        "slice_status": _required_string(checkpoint["slice_status"], "checkpoint.slice_status"),
        "decision_log_delta": _json_list(
            checkpoint["decision_log_delta"],
            "checkpoint.decision_log_delta",
        ),
        "open_review_findings": _json_list(
            checkpoint["open_review_findings"],
            "checkpoint.open_review_findings",
        ),
        "external_state": {
            "marker": marker,
            "previous_marker": previous,
            "changed": expected_changed,
            "refresh_required": expected_changed,
        },
    }


def _normalize_cost_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    observation = _json_object(value, "cost_per_accepted_slice")
    if set(observation) != {
        "accepted_slice_count",
        "inputs",
        "known_monetary_cost_per_accepted_slice_usd",
        "completeness",
        "human_minutes_are_not_monetized",
    }:
        raise EpicRunContextBudgetError(
            "cost_per_accepted_slice has missing or unknown fields"
        )
    denominator = _json_object(
        observation["accepted_slice_count"],
        "cost_per_accepted_slice.accepted_slice_count",
    )
    if set(denominator) != {"value", "source"}:
        raise EpicRunContextBudgetError(
            "accepted_slice_count fields must be value and source"
        )
    denominator_value = denominator["value"]
    if denominator_value == UNKNOWN:
        accepted_slice_count = None
        expected_source = "unavailable"
    else:
        if (
            isinstance(denominator_value, bool)
            or not isinstance(denominator_value, int)
            or denominator_value < 0
        ):
            raise EpicRunContextBudgetError(
                "accepted_slice_count must be a non-negative integer or unknown"
            )
        accepted_slice_count = denominator_value
        expected_source = "caller"
    if denominator.get("source") != expected_source:
        raise EpicRunContextBudgetError(
            f"accepted_slice_count source must be {expected_source}"
        )

    expected = _build_cost_observation(
        _json_object(observation["inputs"], "cost_per_accepted_slice.inputs"),
        accepted_slice_count=accepted_slice_count,
    )
    if observation != expected:
        raise EpicRunContextBudgetError(
            "cost_per_accepted_slice derived values or completeness are inconsistent"
        )
    return expected


def _build_cost_observation(
    inputs: Mapping[str, Any],
    *,
    accepted_slice_count: int | None,
) -> dict[str, Any]:
    raw = _json_object(inputs, "cost_inputs")
    unknown_fields = sorted(set(raw) - set(COST_INPUT_FIELDS))
    if unknown_fields:
        raise EpicRunContextBudgetError(f"unknown cost input field(s): {unknown_fields}")

    normalized_inputs: dict[str, dict[str, Any]] = {}
    for field in COST_INPUT_FIELDS:
        if field not in raw:
            normalized_inputs[field] = {"value": UNKNOWN, "source": "unavailable"}
            continue
        measurement = _json_object(raw[field], f"cost_inputs.{field}")
        if set(measurement) != {"value", "source"}:
            raise EpicRunContextBudgetError(
                f"cost_inputs.{field} fields must be value and source"
            )
        value = measurement["value"]
        if value != UNKNOWN and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not _is_finite_number(value)
            or value < 0
        ):
            raise EpicRunContextBudgetError(
                f"cost_inputs.{field}.value must be finite, non-negative, or unknown"
            )
        normalized_inputs[field] = {
            "value": value,
            "source": _required_string(
                measurement["source"],
                f"cost_inputs.{field}.source",
            ),
        }

    if accepted_slice_count is None:
        denominator: dict[str, Any] = {"value": UNKNOWN, "source": "unavailable"}
    else:
        if (
            isinstance(accepted_slice_count, bool)
            or not isinstance(accepted_slice_count, int)
            or accepted_slice_count < 0
        ):
            raise EpicRunContextBudgetError(
                "accepted_slice_count must be a non-negative integer or unknown"
            )
        denominator = {"value": accepted_slice_count, "source": "caller"}

    known_monetary = [
        normalized_inputs[field]["value"]
        for field in MONETARY_COST_FIELDS
        if normalized_inputs[field]["value"] != UNKNOWN
    ]
    per_accepted: float | str = UNKNOWN
    if (
        denominator["value"] != UNKNOWN
        and denominator["value"] > 0
        and known_monetary
    ):
        known_monetary_total = sum(known_monetary)
        if not _is_finite_number(known_monetary_total):
            raise EpicRunContextBudgetError(
                "known monetary cost total must remain finite"
            )
        try:
            derived_per_accepted = known_monetary_total / denominator["value"]
        except OverflowError as exc:
            raise EpicRunContextBudgetError(
                "known monetary cost per accepted slice must remain finite"
            ) from exc
        if not isinstance(derived_per_accepted, (int, float)) or not math.isfinite(
            derived_per_accepted
        ):
            raise EpicRunContextBudgetError(
                "known monetary cost per accepted slice must remain finite"
            )
        per_accepted = derived_per_accepted

    completeness = (
        "complete"
        if denominator["value"] != UNKNOWN
        and all(item["value"] != UNKNOWN for item in normalized_inputs.values())
        else "partial"
    )
    return {
        "accepted_slice_count": denominator,
        "inputs": normalized_inputs,
        "known_monetary_cost_per_accepted_slice_usd": per_accepted,
        "completeness": completeness,
        "human_minutes_are_not_monetized": True,
    }


def _enum(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EpicRunContextBudgetError(f"{field} must be one of {sorted(allowed)}")
    return value


def _is_finite_number(value: int | float) -> bool:
    if isinstance(value, int):
        return True
    return math.isfinite(value)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EpicRunContextBudgetError(f"{field} must be a non-empty string")
    return value.strip()


def _json_object(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EpicRunContextBudgetError(f"{field} must be an object")
    try:
        return json.loads(json.dumps(dict(value), sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise EpicRunContextBudgetError(
            f"{field} must contain only finite JSON values"
        ) from exc


def _json_list(value: list[Any], field: str) -> list[Any]:
    if not isinstance(value, list):
        raise EpicRunContextBudgetError(f"{field} must be a list")
    try:
        return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise EpicRunContextBudgetError(
            f"{field} must contain only finite JSON values"
        ) from exc
