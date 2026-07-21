"""Fail-closed comparison of retained CKM metric observations.

This adapter is deliberately descriptive: two compatible snapshots establish a
bounded delta, never a trend, cadence, cause, forecast, or machine decision.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.builderops.ckm.contracts import CkmContractError, canonical_digest
from app.builderops.ckm.metrics import MetricRetentionStore, RETENTION_POLICY_VERSION

_BINDINGS = {
    "metric.id": ("metric_definition", "id"),
    "metric.semantic_version": ("metric_definition", "semantic_version"),
    "metric.definition_digest": ("metric_definition", "definition_digest"),
    "formula_digest": ("bindings", "formula_digest"),
    "detector_digest": ("bindings", "detector_digest"),
    "configuration_digest": ("bindings", "configuration_digest"),
    "schema.envelope": ("bindings", "schema", "envelope"),
    "schema.resource": ("bindings", "schema", "resource"),
    "schema.ckm": ("bindings", "schema", "ckm"),
    "taxonomy_digest": ("bindings", "taxonomy_digest"),
    "canonical_query_digest": ("query", "digest"),
    "value_state_schema": ("metric_definition", "output_schema", "value_state"),
    "candidate_confirmed_policy": ("metric_definition", "eligible_population"),
    "identity_policy_version": ("bindings", "identity_policy_version"),
    "access_policy_version": ("snapshot", "access_policy_version"),
    "redaction_policy_version": ("snapshot", "redaction_profile"),
}

def _at(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return "__missing__"
        current = current[part]
    return current

def _observation(store: MetricRetentionStore, sample_id: str) -> dict[str, Any]:
    # replay first: unavailable, expired/pruned, or tampered payloads refuse before
    # any comparison result is assembled. It performs no retention mutation.
    if not store.path.exists():
        raise CkmContractError("source_unavailable", "retained source is unavailable for comparison", {"sample_id": sample_id})
    store.replay(sample_id)
    with sqlite3.connect(store.path) as conn:
        row = conn.execute("SELECT observation_json, policy_version, expires_at, lifecycle FROM ckm_metric_sample_v1 WHERE sample_id = ?", (sample_id,)).fetchone()
    now = datetime.now(timezone.utc)
    expired = row is not None and row[2] is not None and datetime.fromisoformat(row[2].replace("Z", "+00:00")) <= now
    if row is None or row[1] != RETENTION_POLICY_VERSION or row[2] is None or row[3] != "retained" or expired:
        raise CkmContractError("source_unavailable", "retained source is unavailable for comparison", {"sample_id": sample_id})
    try:
        value = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise CkmContractError("corrupt_retained_observation", "retained observation is corrupt", {"sample_id": sample_id}) from exc
    if not isinstance(value, dict):
        raise CkmContractError("corrupt_retained_observation", "retained observation is corrupt", {"sample_id": sample_id})
    return value

def compare_retained_observations(store: MetricRetentionStore, sample_ids: Sequence[str]) -> dict[str, Any]:
    """Return one all-or-nothing, deterministic descriptive comparison."""
    if len(sample_ids) < 2 or len(set(sample_ids)) != len(sample_ids):
        raise CkmContractError("invalid_comparison_inputs", "comparison requires two or more distinct retained samples", {})
    observations = [_observation(store, sample_id) for sample_id in sample_ids]
    baseline = observations[0]
    mismatches: dict[str, list[Any]] = {}
    for name, path in _BINDINGS.items():
        values = [_at(item, path) for item in observations]
        if "__missing__" in values or any(value != values[0] for value in values[1:]):
            mismatches[name] = values
    if mismatches:
        raise CkmContractError("incompatible_observations", "observations have incompatible semantic bindings", {"mismatched_fields": mismatches})
    components: list[dict[str, Any]] = []
    keys = sorted(set().union(*(item.get("vector", {}).keys() for item in observations)))
    for key in keys:
        states = [item.get("vector", {}).get(key, {"state": "unsupported", "reason": "component absent"}) for item in observations]
        if all(state.get("state") == "measured" and isinstance(state.get("value"), (int, float)) for state in states):
            delta: Any = states[-1]["value"] - states[0]["value"]
        else:
            delta = None
        components.append({"component": key, "states": states, "numeric_delta": delta, "state_transition": [state.get("state") for state in states]})
    limitations = ["Two snapshots prove only a bounded delta, not a trend, cadence, window, minimum evidence count, cause, or forecast.", "No ranking, gating, prioritization, agent score, automated action, or machine authority is exposed."]
    return {"kind": "ckm_compatible_observation_comparison_v1", "inputs": [{"sample_id": sid, "observation_id": obs.get("observation_id"), "semantic_digest": obs.get("semantic_digest")} for sid, obs in zip(sample_ids, observations)], "compatibility": {"compatible": True, "bindings": {name: _at(baseline, path) for name, path in _BINDINGS.items()}}, "components": components, "provenance": [obs.get("citations", []) for obs in observations], "freshness": [obs.get("freshness", {}) for obs in observations], "aggregate": {"label": "human_advisory_only", "value": None, "sole_input_prohibited": True, "machine_authority_prohibited": True, "co_present_components": True}, "limitations": limitations, "comparison_digest": canonical_digest({"inputs": list(sample_ids), "components": components})}
