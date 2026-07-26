"""Fail-closed comparison of retained CKM metric observations.

This adapter is deliberately descriptive: two compatible snapshots establish a
bounded delta, never a trend, cadence, cause, forecast, or machine decision.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any

from app.builderops.ckm.contracts import CkmContractError, canonical_digest
from app.builderops.ckm.metrics import (
    MetricRetentionStore,
    RETENTION_POLICY_VERSION,
    metric_definition,
)

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
_ISO8601_INSTANT = re.compile(
    r"^(?P<date>\d{4}-?\d{2}-?\d{2})[T ]"
    r"(?P<hour>\d{2}):?(?P<minute>\d{2}):?(?P<second>\d{2})"
    r"(?P<fraction>[\.,]\d+)?"
    r"(?P<zone>Z|(?P<offset_sign>[+-])(?P<offset_hour>\d{2})"
    r"(?::?(?P<offset_minute>\d{2}))?"
    r"(?::?(?P<offset_second>\d{2})(?P<offset_fraction>[\.,]\d+)?)?)$"
)

def _at(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return "__missing__"
        current = current[part]
    return current

def _component_delta(states: Sequence[Mapping[str, Any]]) -> int | float | None:
    if all(
        state.get("state") == "measured"
        and isinstance(state.get("value"), (int, float))
        and not isinstance(state.get("value"), bool)
        for state in states
    ):
        return states[-1]["value"] - states[0]["value"]
    return None


def _fractional_seconds(value: str | None) -> Fraction:
    if value is None:
        return Fraction(0)
    digits = value[1:]
    return Fraction(int(digits), 10 ** len(digits))


def _iso8601_instant(value: object) -> Fraction:
    """Return exact UTC seconds for a supported timezone-aware ISO-8601 value."""
    if not isinstance(value, str):
        raise ValueError("retained timestamp must be text")
    match = _ISO8601_INSTANT.fullmatch(value)
    if match is None:
        raise ValueError("retained timestamp is not a supported ISO-8601 value")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("retained timestamp must include a UTC offset")
    local_whole = datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        parsed.hour,
        parsed.minute,
        parsed.second,
        tzinfo=timezone.utc,
    )
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed = local_whole - epoch
    local_seconds = Fraction(elapsed.days * 86400 + elapsed.seconds)
    fraction = _fractional_seconds(match.group("fraction"))
    if match.group("zone") == "Z":
        offset = Fraction(0)
    else:
        offset = Fraction(int(match.group("offset_hour")) * 3600)
        offset += Fraction(int(match.group("offset_minute") or "0") * 60)
        offset += Fraction(int(match.group("offset_second") or "0"))
        offset += _fractional_seconds(match.group("offset_fraction"))
        if match.group("offset_sign") == "-":
            offset = -offset
    return local_seconds + fraction - offset


def _observation(store: MetricRetentionStore, sample_id: str) -> dict[str, Any]:
    if not store.path.exists():
        raise CkmContractError("source_unavailable", "retained source is unavailable for comparison", {"sample_id": sample_id})
    try:
        with sqlite3.connect(f"{store.path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT observation_json, typeof(observation_json), source_payload, "
                "typeof(source_payload), source_digest, policy_version, expires_at, "
                "lifecycle, observation_id FROM ckm_metric_sample_v1 WHERE sample_id = ?",
                (sample_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise CkmContractError("source_unavailable", "retention storage is unavailable or incomplete", {"sample_id": sample_id}) from exc
    now = datetime.now(timezone.utc)
    try:
        expired = row is not None and datetime.fromisoformat(row[6].replace("Z", "+00:00")) <= now
    except (AttributeError, TypeError, ValueError) as exc:
        raise CkmContractError("source_unavailable", "retained source expiry is invalid", {"sample_id": sample_id}) from exc
    if row is None or row[5] != RETENTION_POLICY_VERSION or row[7] != "retained" or expired:
        raise CkmContractError("source_unavailable", "retained source is unavailable for comparison", {"sample_id": sample_id})
    if row[1] != "text" or row[3] != "blob" or not isinstance(row[2], (bytes, bytearray, memoryview)):
        raise CkmContractError("tampered_retained_source", "retained comparison input has invalid storage types", {"sample_id": sample_id})
    try:
        value = json.loads(row[0])
        source = json.loads(bytes(row[2]).decode("utf-8"))
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CkmContractError("corrupt_retained_observation", "retained observation is corrupt", {"sample_id": sample_id}) from exc
    if not isinstance(value, dict) or not isinstance(source, dict) or canonical_digest(source) != row[4]:
        raise CkmContractError("corrupt_retained_observation", "retained observation is corrupt", {"sample_id": sample_id})
    try:
        definition = dict(metric_definition(value["metric_definition"]["id"], value["metric_definition"]["semantic_version"]))
        snapshot = source["snapshot"]
        resources = source["resources"]
        confirmed = [item for item in resources if not item["candidate"]]
        candidates = [item for item in resources if item["candidate"]]
        def distribution(items: list[Mapping[str, Any]]) -> dict[str, int]:
            counts = {state: 0 for state in ("measured", "missing", "unassessed", "unsupported")}
            for item in items:
                for tagged in item["values"].values():
                    counts[tagged["state"]] += 1
            return counts
        expected = {
            "observation_schema_version": 1,
            "projection": {"status": "derived_projection", "authoritative": False},
            "metric_definition": definition,
            "snapshot": snapshot,
            "query": {"digest": source["query_digest"], "resource_type": source["resource_type"]},
            "bindings": {
                "schema": {"envelope": source["schema_version"], "resource": snapshot["resource_schema_version"], "ckm": snapshot["ckm_schema_version"]},
                "taxonomy_digest": snapshot["taxonomy_digest"],
                "formula_digest": canonical_digest(definition["formula"]),
                "detector_digest": canonical_digest(definition["detector_bindings"]),
                "configuration_digest": canonical_digest(definition["configuration_bindings"]),
                "watermark_digest": canonical_digest(snapshot["watermarks"]),
                "provenance_digest": canonical_digest(snapshot["provenance"]),
                "identity_policy_version": "ckm-public-id-v1",
            },
            "vector": {
                "confirmed_population": {"state": "measured", "value": len(confirmed)},
                "candidate_population": {"state": "measured", "value": len(candidates)},
                "provenance_coverage": {"state": "measured", "value": len([item for item in resources if item["provenance"]])},
            },
            "distributions": {"confirmed": distribution(confirmed), "candidate": distribution(candidates)},
            "composition": {"confirmed_public_ids": [item["public_id"] for item in confirmed], "candidate_public_ids": [item["public_id"] for item in candidates]},
            "citations": snapshot["provenance"],
            "freshness": {"state_revision": snapshot["state_revision"], "watermarks": snapshot["watermarks"]},
            "confidence": {"state": "unassessed", "reason": "metric does not infer confidence from descriptive CKM data"},
            "limitations": definition["limitations"],
            "goodhart_warnings": definition["goodhart_warnings"],
            "aggregate": {"label": "human_advisory_only", "value": None, "sole_input_prohibited": True, "machine_authority_prohibited": True},
            "generated_at": value["generated_at"],
        }
    except (AttributeError, KeyError, TypeError, CkmContractError) as exc:
        raise CkmContractError("corrupt_retained_observation", "retained observation cannot be reproduced from its source", {"sample_id": sample_id}) from exc
    expected["semantic_digest"] = canonical_digest({key: item for key, item in expected.items() if key != "generated_at"})
    expected["observation_id"] = f"ckm_observation_{expected['semantic_digest'][:24]}"
    if value != expected or row[8] != expected["observation_id"]:
        raise CkmContractError("observation_source_mismatch", "retained observation does not reproduce from its bound source", {"sample_id": sample_id})
    return value


def newest_active_retained_sample_ids(store: MetricRetentionStore) -> tuple[str, str]:
    """Select exactly the newest active pair without creating or repairing storage."""
    if not store.path.is_file():
        raise CkmContractError(
            "source_unavailable",
            "retention storage is unavailable or incomplete",
            {"path": str(store.path)},
        )
    try:
        with sqlite3.connect(f"{store.path.resolve().as_uri()}?mode=ro", uri=True) as conn:
            instant_cache: dict[str, Fraction] = {}

            def instant(value: object) -> Fraction:
                if not isinstance(value, str):
                    return _iso8601_instant(value)
                if value not in instant_cache:
                    instant_cache[value] = _iso8601_instant(value)
                return instant_cache[value]

            def is_valid_instant(value: object) -> int:
                instant(value)
                return 1

            def compare_instants(left: str, right: str) -> int:
                left_instant = instant(left)
                right_instant = instant(right)
                return (left_instant > right_instant) - (
                    left_instant < right_instant
                )

            conn.create_function(
                "ckm_iso8601_valid_instant",
                1,
                is_valid_instant,
                deterministic=True,
            )
            conn.create_collation(
                "ckm_iso8601_chronological",
                compare_instants,
            )
            rows = conn.execute(
                "SELECT sample_id FROM ckm_metric_sample_v1 "
                "WHERE lifecycle = 'retained' "
                "AND ckm_iso8601_valid_instant(retained_at) "
                "ORDER BY retained_at COLLATE ckm_iso8601_chronological DESC, "
                "sample_id DESC LIMIT 2"
            ).fetchall()
    except sqlite3.Error as exc:
        raise CkmContractError(
            "source_unavailable",
            "retention storage is unavailable or incomplete",
            {"path": str(store.path)},
        ) from exc
    if len(rows) < 2:
        raise CkmContractError(
            "insufficient_retained_samples",
            "two active retained samples are required for comparison",
            {"count": len(rows)},
        )
    newest_first = tuple(str(row[0]) for row in rows)
    return newest_first[1], newest_first[0]


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
        delta = _component_delta(states)
        components.append({"component": key, "states": states, "numeric_delta": delta, "state_transition": [state.get("state") for state in states]})
    limitations = ["Two snapshots prove only a bounded delta, not a trend, cadence, window, minimum evidence count, cause, or forecast.", "No ranking, gating, prioritization, agent score, automated action, or machine authority is exposed."]
    return {"kind": "ckm_compatible_observation_comparison_v1", "inputs": [{"sample_id": sid, "observation_id": obs.get("observation_id"), "semantic_digest": obs.get("semantic_digest")} for sid, obs in zip(sample_ids, observations)], "compatibility": {"compatible": True, "bindings": {name: _at(baseline, path) for name, path in _BINDINGS.items()}}, "components": components, "provenance": [obs.get("citations", []) for obs in observations], "freshness": [obs.get("freshness", {}) for obs in observations], "aggregate": {"label": "human_advisory_only", "value": None, "sole_input_prohibited": True, "machine_authority_prohibited": True, "co_present_components": True}, "limitations": limitations, "comparison_digest": canonical_digest({"inputs": list(sample_ids), "components": components})}
