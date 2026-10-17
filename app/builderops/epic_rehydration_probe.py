"""Manual, observer-only rehydration evidence for an accepted slice checkpoint.

The module deliberately contains no dispatcher, GitHub, agent-launch, or mutation adapter
imports.  It validates a source context-budget receipt, builds a bounded context pack, and
compares one fresh agent's structured observation against the checkpoint.  The command-line
entrypoint writes only local JSON evidence files supplied by the operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.builderops.epic_run_context_budget import normalize_context_budget_receipt

CONTEXT_PACK_SCHEMA_NAME = "epic_rehydration_context_pack"
OBSERVATION_SCHEMA_NAME = "epic_rehydrated_observation"
COMPARISON_SCHEMA_NAME = "epic_rehydration_comparison_receipt"
PROBE_RECEIPT_SCHEMA_NAME = "shadow_rehydration_probe_receipt"
SCHEMA_VERSION = 1
SOURCE_SCHEMA_NAME = "epic_run_context_budget_receipt"
SOURCE_SCHEMA_VERSION = 1
UNKNOWN = "unknown"
DEFAULT_PROBE_ID = "shadow_rehydration_3798"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_OBSERVATION_FIELDS = (
    "slice_status",
    "decisions_and_invariants",
    "open_review_findings",
    "external_state",
    "recommended_next_action",
    "missing_claims",
    "fabricated_claims",
)
_COMPARED_FIELDS = _OBSERVATION_FIELDS[:5]
_EFFECT_CATEGORIES = (
    "dispatch",
    "leases",
    "ci",
    "review",
    "acceptance",
    "merge",
    "closure",
    "agent_start",
)
_LIVE_TRUTH_PRECEDENCE = (
    "live_github_issue_pr_ci",
    "live_repository_head",
    "live_dispatcher_snapshot",
    "accepted_source_checkpoint",
)


class EpicRehydrationProbeError(ValueError):
    """Raised when a probe input is not a strict v1 JSON contract."""


def parse_strict_json(payload: bytes | str, *, field: str = "json") -> dict[str, Any]:
    """Parse one object with duplicate-key, non-finite, and root-type rejection."""

    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EpicRehydrationProbeError(f"{field} must be UTF-8 JSON") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise EpicRehydrationProbeError(f"{field} must be bytes or string")

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, EpicRehydrationProbeError) as exc:
        raise EpicRehydrationProbeError(f"{field} is not strict JSON: {exc}") from exc
    if type(parsed) is not dict:
        raise EpicRehydrationProbeError(f"{field} root must be an object")
    _assert_json_values(parsed, field)
    return parsed


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a strict object."""

    if type(value) is not dict:
        raise EpicRehydrationProbeError("canonical JSON root must be an object")
    _assert_json_values(value, "canonical JSON")
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EpicRehydrationProbeError("canonical JSON contains unsupported values") from exc


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return deterministic JSON text for a strict object."""

    return canonical_json_bytes(value).decode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    """Hash exact evidence bytes without normalizing them first."""

    return hashlib.sha256(payload).hexdigest()


def build_context_pack(
    source_bytes: bytes | str,
    *,
    source_ref: str,
    source_observed_at: str,
    slice_id: str,
    repository: str,
    issue_number: int,
    pr_number: int,
    verified_pr_head_sha: str,
    merge_sha: str,
    read_instructions: Sequence[str],
    probe_id: str = DEFAULT_PROBE_ID,
) -> dict[str, Any]:
    """Build a deterministic pack bound to one accepted source receipt and live target."""

    raw = _coerce_source_bytes(source_bytes, "source_bytes")
    source = parse_strict_json(raw, field="source_bytes")
    try:
        normalized_source = normalize_context_budget_receipt(source)
    except (TypeError, ValueError) as exc:
        raise EpicRehydrationProbeError(f"source receipt is not valid: {exc}") from exc
    if not _json_exact_equal(source, normalized_source):
        raise EpicRehydrationProbeError(
            "source receipt must already be normalized epic_run_context_budget_receipt.v1"
        )
    if source.get("schema_name") != SOURCE_SCHEMA_NAME:
        raise EpicRehydrationProbeError("source receipt has unsupported schema_name")
    if source.get("schema_version") != SOURCE_SCHEMA_VERSION:
        raise EpicRehydrationProbeError("source receipt has unsupported schema_version")

    source_slice_id = _required_string(source.get("slice_id"), "source.slice_id")
    normalized_slice_id = _required_string(slice_id, "slice_id")
    if source_slice_id != normalized_slice_id:
        raise EpicRehydrationProbeError("slice_id must match the source receipt")
    _validate_source_bytes_binding(sha256_bytes(raw), len(raw), normalized_source)

    instructions = _string_list(read_instructions, "read_instructions", non_empty=True)
    normalized_source_marker = _strict_object(
        source["checkpoint"]["external_state"]["marker"],
        "source.external_state_marker",
    )
    pack = {
        "schema_name": CONTEXT_PACK_SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "probe_id": _required_string(probe_id, "probe_id"),
        "source": {
            "schema_name": SOURCE_SCHEMA_NAME,
            "schema_version": SOURCE_SCHEMA_VERSION,
            "source_ref": _required_string(source_ref, "source_ref"),
            "observed_at": _required_string(source_observed_at, "source_observed_at"),
            "bytes_sha256": sha256_bytes(raw),
            "bytes_length": len(raw),
            "receipt": normalized_source,
            "external_state_marker": normalized_source_marker,
            "origin": "actual_live_evaluator_checkpoint",
        },
        "target": {
            "repository": _required_string(repository, "repository"),
            "issue_number": _positive_int(issue_number, "issue_number"),
            "pr_number": _positive_int(pr_number, "pr_number"),
            "verified_pr_head_sha": _sha(verified_pr_head_sha, "verified_pr_head_sha"),
            "merge_sha": _sha(merge_sha, "merge_sha"),
            "slice_id": normalized_slice_id,
        },
        "read_instructions": instructions,
        "live_truth_precedence": list(_LIVE_TRUTH_PRECEDENCE),
        "forbidden_effects": list(_EFFECT_CATEGORIES),
        "effects": {category: [] for category in _EFFECT_CATEGORIES},
    }
    return normalize_context_pack(pack)


def normalize_context_pack(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a context pack at the pack/CLI boundary."""

    normalized = _strict_object(pack, "context_pack")
    _exact_fields(
        normalized,
        {
            "schema_name",
            "schema_version",
            "probe_id",
            "source",
            "target",
            "read_instructions",
            "live_truth_precedence",
            "forbidden_effects",
            "effects",
        },
        "context_pack",
    )
    if normalized["schema_name"] != CONTEXT_PACK_SCHEMA_NAME:
        raise EpicRehydrationProbeError("unsupported context_pack schema_name")
    _schema_version(normalized["schema_version"], "context_pack.schema_version")
    normalized["probe_id"] = _required_string(normalized["probe_id"], "context_pack.probe_id")

    source = _strict_object(normalized["source"], "context_pack.source")
    _exact_fields(
        source,
        {
            "schema_name",
            "schema_version",
            "source_ref",
            "observed_at",
            "bytes_sha256",
            "bytes_length",
            "receipt",
            "external_state_marker",
            "origin",
        },
        "context_pack.source",
    )
    if source["schema_name"] != SOURCE_SCHEMA_NAME:
        raise EpicRehydrationProbeError("context_pack.source has unsupported schema_name")
    _schema_version(source["schema_version"], "context_pack.source.schema_version")
    source["source_ref"] = _required_string(source["source_ref"], "context_pack.source_ref")
    source["observed_at"] = _required_string(source["observed_at"], "context_pack.source.observed_at")
    _sha256(source["bytes_sha256"], "context_pack.source.bytes_sha256")
    source["bytes_length"] = _non_negative_int(source["bytes_length"], "context_pack.source.bytes_length")
    try:
        source_receipt = normalize_context_budget_receipt(source["receipt"])
    except (TypeError, ValueError) as exc:
        raise EpicRehydrationProbeError(f"context_pack.source.receipt is not valid: {exc}") from exc
    if not _json_exact_equal(source["receipt"], source_receipt):
        raise EpicRehydrationProbeError("context_pack.source.receipt is not normalized")
    source["receipt"] = source_receipt
    _validate_source_bytes_binding(
        source["bytes_sha256"], source["bytes_length"], source_receipt
    )
    source["external_state_marker"] = _strict_object(
        source["external_state_marker"], "context_pack.source.external_state_marker"
    )
    expected_marker = source_receipt["checkpoint"]["external_state"]["marker"]
    if not _json_exact_equal(source["external_state_marker"], expected_marker):
        raise EpicRehydrationProbeError("context_pack source marker is not source-bound")
    if source["origin"] != "actual_live_evaluator_checkpoint":
        raise EpicRehydrationProbeError("context_pack source origin must be an actual evaluator checkpoint")

    target = _strict_object(normalized["target"], "context_pack.target")
    _exact_fields(
        target,
        {"repository", "issue_number", "pr_number", "verified_pr_head_sha", "merge_sha", "slice_id"},
        "context_pack.target",
    )
    target["repository"] = _required_string(target["repository"], "context_pack.target.repository")
    target["issue_number"] = _positive_int(target["issue_number"], "context_pack.target.issue_number")
    target["pr_number"] = _positive_int(target["pr_number"], "context_pack.target.pr_number")
    target["verified_pr_head_sha"] = _sha(
        target["verified_pr_head_sha"], "context_pack.target.verified_pr_head_sha"
    )
    target["merge_sha"] = _sha(target["merge_sha"], "context_pack.target.merge_sha")
    target["slice_id"] = _required_string(target["slice_id"], "context_pack.target.slice_id")
    if target["slice_id"] != source_receipt["slice_id"]:
        raise EpicRehydrationProbeError("context_pack target slice_id is not source-bound")
    _validate_target_against_source_marker(target, source["external_state_marker"])

    normalized["read_instructions"] = _string_list(
        normalized["read_instructions"], "context_pack.read_instructions", non_empty=True
    )
    normalized["live_truth_precedence"] = _string_list(
        normalized["live_truth_precedence"], "context_pack.live_truth_precedence", non_empty=True
    )
    if tuple(normalized["live_truth_precedence"]) != _LIVE_TRUTH_PRECEDENCE:
        raise EpicRehydrationProbeError("context_pack live-truth precedence is unsupported")
    normalized["forbidden_effects"] = _string_list(
        normalized["forbidden_effects"], "context_pack.forbidden_effects", non_empty=True
    )
    if tuple(normalized["forbidden_effects"]) != _EFFECT_CATEGORIES:
        raise EpicRehydrationProbeError("context_pack forbidden effects are incomplete")
    normalized["effects"] = _normalize_effects(normalized["effects"], "context_pack.effects")
    return normalized


def normalize_rehydrated_observation(
    observation: Mapping[str, Any],
    *,
    context_pack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Strictly validate the one fresh agent's structured observation."""

    normalized = _strict_object(observation, "observation")
    _exact_fields(
        normalized,
        {
            "schema_name",
            "schema_version",
            "probe_id",
            "observed_at",
            "target",
            "agent",
            "fields",
            "live_reads",
            "limitations",
        },
        "observation",
    )
    if normalized["schema_name"] != OBSERVATION_SCHEMA_NAME:
        raise EpicRehydrationProbeError("unsupported observation schema_name")
    _schema_version(normalized["schema_version"], "observation.schema_version")
    normalized["probe_id"] = _required_string(normalized["probe_id"], "observation.probe_id")
    normalized["observed_at"] = _required_string(normalized["observed_at"], "observation.observed_at")

    target = _strict_object(normalized["target"], "observation.target")
    _exact_fields(
        target,
        {"repository", "issue_number", "pr_number", "verified_pr_head_sha", "merge_sha"},
        "observation.target",
    )
    target["repository"] = _required_string(target["repository"], "observation.target.repository")
    target["issue_number"] = _positive_int(target["issue_number"], "observation.target.issue_number")
    target["pr_number"] = _positive_int(target["pr_number"], "observation.target.pr_number")
    target["verified_pr_head_sha"] = _sha(
        target["verified_pr_head_sha"], "observation.target.verified_pr_head_sha"
    )
    target["merge_sha"] = _sha(target["merge_sha"], "observation.target.merge_sha")
    if context_pack is not None:
        pack = normalize_context_pack(context_pack)
        if not _json_exact_equal(target, pack["target"] | {"slice_id": pack["target"]["slice_id"]}):
            expected = {key: pack["target"][key] for key in target}
            if not _json_exact_equal(target, expected):
                raise EpicRehydrationProbeError("observation target is not context-pack bound")
        if normalized["probe_id"] != pack["probe_id"]:
            raise EpicRehydrationProbeError("observation probe_id is not context-pack bound")

    agent = _strict_object(normalized["agent"], "observation.agent")
    _exact_fields(
        agent,
        {"model", "reasoning_effort", "start_status", "start_observed_at"},
        "observation.agent",
    )
    agent["model"] = _required_string(agent["model"], "observation.agent.model")
    agent["reasoning_effort"] = _required_string(
        agent["reasoning_effort"], "observation.agent.reasoning_effort"
    )
    if agent["start_status"] not in {"succeeded", "failed"}:
        raise EpicRehydrationProbeError("observation.agent.start_status must be succeeded or failed")
    agent["start_observed_at"] = _required_string(
        agent["start_observed_at"], "observation.agent.start_observed_at"
    )

    fields = _strict_object(normalized["fields"], "observation.fields")
    _exact_fields(fields, set(_OBSERVATION_FIELDS), "observation.fields")
    normalized["fields"] = {
        name: _normalize_observation_field(fields[name], f"observation.fields.{name}")
        for name in _OBSERVATION_FIELDS
    }
    _validate_observation_field_types(normalized["fields"], "observation.fields")
    normalized["live_reads"] = _normalize_provenance_list(
        normalized["live_reads"], "observation.live_reads", non_empty=True
    )
    normalized["limitations"] = _string_list(normalized["limitations"], "observation.limitations")
    return normalized


def compare_rehydrated_observation(
    context_pack: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one observation without ranking it or producing a quality aggregate."""

    pack = normalize_context_pack(context_pack)
    obs = normalize_rehydrated_observation(observation, context_pack=pack)
    source = pack["source"]["receipt"]
    expected: dict[str, Any] = {
        "slice_status": source["checkpoint"]["slice_status"],
        "decisions_and_invariants": {
            "decisions": source["checkpoint"]["decision_log_delta"],
            "gate_invariants": source["gate_invariants"],
        },
        "open_review_findings": source["checkpoint"]["open_review_findings"],
        "external_state": source["checkpoint"]["external_state"],
        "recommended_next_action": {
            "recommendations": source["recommendations"],
            "reasons": source["recommendation_reasons"],
        },
    }
    field_results: dict[str, Any] = {}
    for name in _COMPARED_FIELDS:
        observed_value = obs["fields"][name]["value"]
        status = _comparison_status(observed_value, expected[name])
        field_results[name] = {
            "status": status,
            "expected": expected[name],
            "observed": observed_value,
            "provenance": obs["fields"][name]["provenance"],
            "notes": obs["fields"][name]["notes"],
        }

    derived_missing = sorted(
        name for name in _COMPARED_FIELDS if field_results[name]["status"] == "unknown"
    )
    for name, derived in (("missing_claims", derived_missing),):
        observed_value = obs["fields"][name]["value"]
        field_results[name] = {
            "status": _comparison_status(observed_value, derived),
            "expected": derived,
            "observed": observed_value,
            "provenance": obs["fields"][name]["provenance"],
            "notes": obs["fields"][name]["notes"],
        }

    # A mismatch is evidence of drift, not proof that the fresh agent fabricated a claim.
    # Fabrication requires an independently audited claim and therefore remains unknown in
    # this observer-only comparison.
    fabricated = obs["fields"]["fabricated_claims"]
    field_results["fabricated_claims"] = {
        "status": "unknown",
        "expected": UNKNOWN,
        "observed": fabricated["value"],
        "provenance": fabricated["provenance"],
        "notes": fabricated["notes"],
    }

    external_state = field_results["external_state"]
    return {
        "schema_name": COMPARISON_SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "probe_id": pack["probe_id"],
        "target": pack["target"],
        "field_results": field_results,
        "external_refresh": {
            "status": external_state["status"],
            "refresh_required": external_state["status"] != "match",
            "source_marker": pack["source"]["external_state_marker"],
            "observed_marker": obs["fields"]["external_state"]["value"],
            "provenance": obs["fields"]["external_state"]["provenance"],
        },
        "live_truth_precedence": list(_LIVE_TRUTH_PRECEDENCE),
        "limitations": obs["limitations"],
        "effects": {category: [] for category in _EFFECT_CATEGORIES},
    }


def build_probe_receipt(
    context_pack: Mapping[str, Any],
    observation: Mapping[str, Any],
    comparison: Mapping[str, Any],
    *,
    evidence_refs: Mapping[str, str],
    telemetry: Mapping[str, Any],
    source_observed_at: str | None = None,
) -> dict[str, Any]:
    """Build the durable receipt for exactly one initial shadow probe."""

    pack = normalize_context_pack(context_pack)
    obs = normalize_rehydrated_observation(observation, context_pack=pack)
    comp = normalize_comparison(comparison, context_pack=pack, observation=obs)
    normalized_telemetry = _normalize_telemetry(telemetry, "telemetry")
    if normalized_telemetry["probe_count"] != 1:
        raise EpicRehydrationProbeError("probe receipt must record exactly one initial probe")
    if normalized_telemetry["agent_starts"] != 1:
        raise EpicRehydrationProbeError("probe receipt must record exactly one agent start")
    if obs["agent"]["start_status"] != "succeeded":
        raise EpicRehydrationProbeError("probe receipt requires a successful fresh-agent start")
    refs = _normalize_evidence_refs(evidence_refs)
    expected_source_observed_at = pack["source"]["observed_at"]
    if source_observed_at is not None and source_observed_at != expected_source_observed_at:
        raise EpicRehydrationProbeError(
            "source_observed_at must match the context pack source timestamp"
        )
    receipt = {
        "schema_name": PROBE_RECEIPT_SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "probe_id": pack["probe_id"],
        "mode": "one_initial_read_only",
        "source_checkpoint": {
            "origin": pack["source"]["origin"],
            "observed_at": _required_string(expected_source_observed_at, "source_observed_at"),
            "source_ref": pack["source"]["source_ref"],
            "bytes_sha256": pack["source"]["bytes_sha256"],
        },
        "context_pack": {
            "sha256": sha256_bytes(canonical_json_bytes(pack)),
            "ref": refs["context_pack"],
        },
        "observation": {
            "sha256": sha256_bytes(canonical_json_bytes(obs)),
            "ref": refs["agent_response"],
        },
        "comparison": {
            "sha256": sha256_bytes(canonical_json_bytes(comp)),
            "ref": refs["comparison_receipt"],
        },
        "target": pack["target"],
        "agent": obs["agent"],
        "telemetry": normalized_telemetry,
        "evidence": {
            "source_checkpoint": refs["source_checkpoint"],
            "context_pack": refs["context_pack"],
            "agent_response": refs["agent_response"],
            "comparison_receipt": refs["comparison_receipt"],
        },
        "effects": {category: [] for category in _EFFECT_CATEGORIES},
        "limitations": obs["limitations"],
    }
    return normalize_probe_receipt(receipt)


def normalize_comparison(
    comparison: Mapping[str, Any],
    *,
    context_pack: Mapping[str, Any] | None = None,
    observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a comparison receipt and its effect-free boundary."""

    normalized = _strict_object(comparison, "comparison")
    _exact_fields(
        normalized,
        {
            "schema_name",
            "schema_version",
            "probe_id",
            "target",
            "field_results",
            "external_refresh",
            "live_truth_precedence",
            "limitations",
            "effects",
        },
        "comparison",
    )
    if normalized["schema_name"] != COMPARISON_SCHEMA_NAME:
        raise EpicRehydrationProbeError("unsupported comparison schema_name")
    _schema_version(normalized["schema_version"], "comparison.schema_version")
    normalized["probe_id"] = _required_string(normalized["probe_id"], "comparison.probe_id")
    target = _strict_object(normalized["target"], "comparison.target")
    _exact_fields(target, {"repository", "issue_number", "pr_number", "verified_pr_head_sha", "merge_sha", "slice_id"}, "comparison.target")
    target["repository"] = _required_string(target["repository"], "comparison.target.repository")
    target["issue_number"] = _positive_int(target["issue_number"], "comparison.target.issue_number")
    target["pr_number"] = _positive_int(target["pr_number"], "comparison.target.pr_number")
    target["verified_pr_head_sha"] = _sha(target["verified_pr_head_sha"], "comparison.target.verified_pr_head_sha")
    target["merge_sha"] = _sha(target["merge_sha"], "comparison.target.merge_sha")
    target["slice_id"] = _required_string(target["slice_id"], "comparison.target.slice_id")
    if context_pack is not None and not _json_exact_equal(target, normalize_context_pack(context_pack)["target"]):
        raise EpicRehydrationProbeError("comparison target is not context-pack bound")

    field_results = _strict_object(normalized["field_results"], "comparison.field_results")
    _exact_fields(field_results, set(_OBSERVATION_FIELDS), "comparison.field_results")
    for name in _OBSERVATION_FIELDS:
        item = _strict_object(field_results[name], f"comparison.field_results.{name}")
        _exact_fields(item, {"status", "expected", "observed", "provenance", "notes"}, f"comparison.field_results.{name}")
        if item["status"] not in {"match", "mismatch", "unknown"}:
            raise EpicRehydrationProbeError(f"comparison field {name} has invalid status")
        item["provenance"] = _normalize_provenance_list(item["provenance"], f"comparison.field_results.{name}.provenance", non_empty=True)
        item["notes"] = _string_list(item["notes"], f"comparison.field_results.{name}.notes")
        _assert_json_values(item["expected"], f"comparison.field_results.{name}.expected")
        _assert_json_values(item["observed"], f"comparison.field_results.{name}.observed")

    external_refresh = _strict_object(normalized["external_refresh"], "comparison.external_refresh")
    _exact_fields(external_refresh, {"status", "refresh_required", "source_marker", "observed_marker", "provenance"}, "comparison.external_refresh")
    if external_refresh["status"] not in {"match", "mismatch", "unknown"}:
        raise EpicRehydrationProbeError("comparison external_refresh status is invalid")
    if type(external_refresh["refresh_required"]) is not bool:
        raise EpicRehydrationProbeError("comparison external_refresh.refresh_required must be boolean")
    external_refresh["source_marker"] = _strict_object(external_refresh["source_marker"], "comparison.external_refresh.source_marker")
    _assert_json_values(external_refresh["observed_marker"], "comparison.external_refresh.observed_marker")
    external_refresh["provenance"] = _normalize_provenance_list(external_refresh["provenance"], "comparison.external_refresh.provenance", non_empty=True)
    normalized["live_truth_precedence"] = _string_list(normalized["live_truth_precedence"], "comparison.live_truth_precedence", non_empty=True)
    if tuple(normalized["live_truth_precedence"]) != _LIVE_TRUTH_PRECEDENCE:
        raise EpicRehydrationProbeError("comparison live-truth precedence is unsupported")
    normalized["limitations"] = _string_list(normalized["limitations"], "comparison.limitations")
    normalized["effects"] = _normalize_effects(normalized["effects"], "comparison.effects")
    if context_pack is not None and observation is not None:
        expected = compare_rehydrated_observation(context_pack, observation)
        if not _json_exact_equal(normalized, expected):
            raise EpicRehydrationProbeError("comparison does not match context pack and observation")
    return normalized


def normalize_probe_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the final receipt's one-probe and no-authority invariants."""

    normalized = _strict_object(receipt, "probe_receipt")
    _exact_fields(
        normalized,
        {
            "schema_name",
            "schema_version",
            "probe_id",
            "mode",
            "source_checkpoint",
            "context_pack",
            "observation",
            "comparison",
            "target",
            "agent",
            "telemetry",
            "evidence",
            "effects",
            "limitations",
        },
        "probe_receipt",
    )
    if normalized["schema_name"] != PROBE_RECEIPT_SCHEMA_NAME:
        raise EpicRehydrationProbeError("unsupported probe_receipt schema_name")
    _schema_version(normalized["schema_version"], "probe_receipt.schema_version")
    normalized["probe_id"] = _required_string(normalized["probe_id"], "probe_receipt.probe_id")
    if normalized["mode"] != "one_initial_read_only":
        raise EpicRehydrationProbeError("probe_receipt mode must be one_initial_read_only")

    source = _strict_object(normalized["source_checkpoint"], "probe_receipt.source_checkpoint")
    _exact_fields(source, {"origin", "observed_at", "source_ref", "bytes_sha256"}, "probe_receipt.source_checkpoint")
    if source["origin"] != "actual_live_evaluator_checkpoint":
        raise EpicRehydrationProbeError("probe receipt source must be an actual evaluator checkpoint")
    source["observed_at"] = _required_string(source["observed_at"], "probe_receipt.source_checkpoint.observed_at")
    source["source_ref"] = _required_string(source["source_ref"], "probe_receipt.source_checkpoint.source_ref")
    _sha256(source["bytes_sha256"], "probe_receipt.source_checkpoint.bytes_sha256")
    for key in ("context_pack", "observation", "comparison"):
        item = _strict_object(normalized[key], f"probe_receipt.{key}")
        _exact_fields(item, {"sha256", "ref"}, f"probe_receipt.{key}")
        _sha256(item["sha256"], f"probe_receipt.{key}.sha256")
        item["ref"] = _required_string(item["ref"], f"probe_receipt.{key}.ref")

    target = _strict_object(normalized["target"], "probe_receipt.target")
    _exact_fields(target, {"repository", "issue_number", "pr_number", "verified_pr_head_sha", "merge_sha", "slice_id"}, "probe_receipt.target")
    target["repository"] = _required_string(target["repository"], "probe_receipt.target.repository")
    target["issue_number"] = _positive_int(target["issue_number"], "probe_receipt.target.issue_number")
    target["pr_number"] = _positive_int(target["pr_number"], "probe_receipt.target.pr_number")
    target["verified_pr_head_sha"] = _sha(target["verified_pr_head_sha"], "probe_receipt.target.verified_pr_head_sha")
    target["merge_sha"] = _sha(target["merge_sha"], "probe_receipt.target.merge_sha")
    target["slice_id"] = _required_string(target["slice_id"], "probe_receipt.target.slice_id")

    agent = _strict_object(normalized["agent"], "probe_receipt.agent")
    _exact_fields(agent, {"model", "reasoning_effort", "start_status", "start_observed_at"}, "probe_receipt.agent")
    agent["model"] = _required_string(agent["model"], "probe_receipt.agent.model")
    agent["reasoning_effort"] = _required_string(agent["reasoning_effort"], "probe_receipt.agent.reasoning_effort")
    if agent["start_status"] != "succeeded":
        raise EpicRehydrationProbeError("probe receipt requires start_status succeeded")
    agent["start_observed_at"] = _required_string(agent["start_observed_at"], "probe_receipt.agent.start_observed_at")
    normalized["telemetry"] = _normalize_telemetry(normalized["telemetry"], "probe_receipt.telemetry")
    if normalized["telemetry"]["probe_count"] != 1 or normalized["telemetry"]["agent_starts"] != 1:
        raise EpicRehydrationProbeError("probe receipt telemetry must describe exactly one probe and agent start")
    normalized["evidence"] = _normalize_evidence_refs(normalized["evidence"])
    normalized["limitations"] = _string_list(normalized["limitations"], "probe_receipt.limitations")
    normalized["effects"] = _normalize_effects(normalized["effects"], "probe_receipt.effects")
    return normalized


def _normalize_comparison_for_receipt(comparison: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_comparison(comparison)


def _normalize_observation_field(value: Any, field: str) -> dict[str, Any]:
    normalized = _strict_object(value, field)
    _exact_fields(normalized, {"value", "provenance", "notes"}, field)
    _assert_json_values(normalized["value"], f"{field}.value")
    normalized["provenance"] = _normalize_provenance_list(
        normalized["provenance"], f"{field}.provenance", non_empty=True
    )
    normalized["notes"] = _string_list(normalized["notes"], f"{field}.notes")
    return normalized


def _validate_observation_field_types(
    fields: Mapping[str, Mapping[str, Any]], field: str
) -> None:
    """Reject structurally invalid values before comparison can reinterpret them."""

    expected_types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "slice_status": (str,),
        "decisions_and_invariants": (dict,),
        "open_review_findings": (list,),
        "external_state": (dict,),
        "recommended_next_action": (dict, str),
        "missing_claims": (list,),
        "fabricated_claims": (list,),
    }
    for name, value_types in expected_types.items():
        value = fields[name]["value"]
        if value == UNKNOWN:
            continue
        if not isinstance(value, value_types):
            raise EpicRehydrationProbeError(
                f"{field}.{name}.value must be unknown or {value_types}"
            )


def _normalize_provenance_list(value: Any, field: str, *, non_empty: bool) -> list[dict[str, str]]:
    if type(value) is not list or (non_empty and not value):
        raise EpicRehydrationProbeError(f"{field} must be a non-empty list")
    result: list[dict[str, str]] = []
    for index, item in enumerate(value):
        obj = _strict_object(item, f"{field}[{index}]")
        _exact_fields(obj, {"kind", "ref"}, f"{field}[{index}]")
        result.append({
            "kind": _required_string(obj["kind"], f"{field}[{index}].kind"),
            "ref": _required_string(obj["ref"], f"{field}[{index}].ref"),
        })
    return result


def _normalize_effects(value: Any, field: str) -> dict[str, list[Any]]:
    obj = _strict_object(value, field)
    _exact_fields(obj, set(_EFFECT_CATEGORIES), field)
    result: dict[str, list[Any]] = {}
    for category in _EFFECT_CATEGORIES:
        if type(obj[category]) is not list or obj[category]:
            raise EpicRehydrationProbeError(f"{field}.{category} must be an empty list")
        result[category] = []
    return result


def _normalize_telemetry(value: Any, field: str) -> dict[str, Any]:
    obj = _strict_object(value, field)
    _exact_fields(
        obj,
        {
            "probe_count",
            "agent_starts",
            "repairs",
            "handoffs",
            "context_tokens",
            "model_cost_usd",
            "elapsed_minutes",
            "human_minutes",
        },
        field,
    )
    obj["probe_count"] = _positive_int(obj["probe_count"], f"{field}.probe_count")
    obj["agent_starts"] = _non_negative_int(obj["agent_starts"], f"{field}.agent_starts")
    obj["handoffs"] = _non_negative_int(obj["handoffs"], f"{field}.handoffs")
    repairs = _strict_object(obj["repairs"], f"{field}.repairs")
    _exact_fields(repairs, {"implementation", "ci", "review"}, f"{field}.repairs")
    obj["repairs"] = {
        key: _non_negative_int(repairs[key], f"{field}.repairs.{key}")
        for key in ("implementation", "ci", "review")
    }
    for key in ("context_tokens", "model_cost_usd", "elapsed_minutes", "human_minutes"):
        obj[key] = _unknown_or_finite_non_negative(obj[key], f"{field}.{key}")
    return obj


def _normalize_evidence_refs(value: Mapping[str, Any]) -> dict[str, str]:
    obj = _strict_object(value, "evidence_refs")
    expected = {"source_checkpoint", "context_pack", "agent_response", "comparison_receipt"}
    _exact_fields(obj, expected, "evidence_refs")
    return {key: _required_string(obj[key], f"evidence_refs.{key}") for key in sorted(expected)}


def _comparison_status(observed: Any, expected: Any) -> str:
    if observed == UNKNOWN:
        return "unknown"
    return "match" if _json_exact_equal(observed, expected) else "mismatch"


def _coerce_source_bytes(value: bytes | str, field: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise EpicRehydrationProbeError(f"{field} must be bytes or string")


def _validate_source_bytes_binding(
    digest: Any, length: Any, receipt: Mapping[str, Any]
) -> None:
    """Require the source digest/length to describe the canonical accepted receipt bytes."""

    canonical = canonical_json_bytes(receipt)
    candidates = (canonical, canonical + b"\n")
    if not any(
        type(length) is int
        and length == len(candidate)
        and digest == sha256_bytes(candidate)
        for candidate in candidates
    ):
        raise EpicRehydrationProbeError(
            "context_pack source bytes_sha256/bytes_length do not bind the accepted receipt bytes"
        )


def _validate_target_against_source_marker(
    target: Mapping[str, Any], marker: Mapping[str, Any]
) -> None:
    """Bind the target Issue/PR and verified SHAs to the live checkpoint marker."""

    issue_marker = _required_string(marker.get("issue"), "source marker.issue")
    pr_marker = _required_string(marker.get("pr"), "source marker.pr")
    try:
        issue_number = int(issue_marker.split(":", 1)[0])
        pr_number = int(pr_marker.split(":", 1)[0])
    except ValueError as exc:
        raise EpicRehydrationProbeError("source marker Issue/PR values are malformed") from exc
    if issue_number != target["issue_number"] or pr_number != target["pr_number"]:
        raise EpicRehydrationProbeError("context_pack target is foreign to the source marker")
    head_value = marker.get("pr_head_sha", marker.get("head_sha"))
    if _required_string(head_value, "source marker.pr_head_sha") != target["verified_pr_head_sha"]:
        raise EpicRehydrationProbeError("context_pack target head is foreign to the source marker")
    if _required_string(marker.get("merge_sha"), "source marker.merge_sha") != target["merge_sha"]:
        raise EpicRehydrationProbeError("context_pack target merge is foreign to the source marker")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EpicRehydrationProbeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise EpicRehydrationProbeError(f"non-finite JSON number: {value}")


def _assert_json_values(value: Any, field: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise EpicRehydrationProbeError(f"{field} contains a non-finite number")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EpicRehydrationProbeError(f"{field} has a non-string key")
            _assert_json_values(item, f"{field}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_values(item, f"{field}[{index}]")
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise EpicRehydrationProbeError(f"{field} contains a non-JSON value")


def _strict_object(value: Any, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise EpicRehydrationProbeError(f"{field} must be an object")
    _assert_json_values(value, field)
    return dict(value)


def _exact_fields(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise EpicRehydrationProbeError(f"{field} fields mismatch; missing={missing}, extra={extra}")


def _required_string(value: Any, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise EpicRehydrationProbeError(f"{field} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, field: str, *, non_empty: bool = False) -> list[str]:
    if type(value) is not list or (non_empty and not value):
        raise EpicRehydrationProbeError(f"{field} must be a list")
    return [_required_string(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise EpicRehydrationProbeError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise EpicRehydrationProbeError(f"{field} must be a non-negative integer")
    return value


def _schema_version(value: Any, field: str) -> None:
    if type(value) is not int or value != SCHEMA_VERSION:
        raise EpicRehydrationProbeError(f"{field} must be integer {SCHEMA_VERSION}")


def _sha(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA40.fullmatch(value):
        raise EpicRehydrationProbeError(f"{field} must be a lowercase 40-character SHA")
    return value


def _sha256(value: Any, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise EpicRehydrationProbeError(f"{field} must be a lowercase 64-character SHA-256")
    return value


def _unknown_or_finite_non_negative(value: Any, field: str) -> str | int | float:
    if value == UNKNOWN:
        return UNKNOWN
    if type(value) not in {int, float} or isinstance(value, bool):
        raise EpicRehydrationProbeError(f"{field} must be unknown or a non-negative number")
    if isinstance(value, float) and not math.isfinite(value):
        raise EpicRehydrationProbeError(f"{field} must be finite")
    if value < 0:
        raise EpicRehydrationProbeError(f"{field} must be non-negative")
    return value


def _json_exact_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(_json_exact_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_exact_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _read_json_file(path: Path) -> dict[str, Any]:
    return parse_strict_json(path.read_bytes(), field=str(path))


def _write_json_file(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _reject_output_alias(output: Path, *inputs: Path) -> None:
    """Refuse output paths that alias any input, including symlinks or hardlinks."""

    output_resolved = output.resolve()
    for input_path in inputs:
        input_resolved = input_path.resolve()
        if output_resolved == input_resolved:
            raise EpicRehydrationProbeError(
                f"output path aliases input path: {output}"
            )
        if output.exists() and input_path.exists():
            try:
                if output.stat().st_ino == input_path.stat().st_ino and output.stat().st_dev == input_path.stat().st_dev:
                    raise EpicRehydrationProbeError(
                        f"output path aliases input inode: {output}"
                    )
            except OSError as exc:
                raise EpicRehydrationProbeError("unable to verify output/input alias") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual observer-only rehydration probe evidence")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pack = subparsers.add_parser("build-pack", help="build a context pack from a source receipt")
    pack.add_argument("--source-file", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--source-ref", required=True)
    pack.add_argument("--source-observed-at", required=True)
    pack.add_argument("--slice-id", required=True)
    pack.add_argument("--repository", required=True)
    pack.add_argument("--issue-number", type=int, required=True)
    pack.add_argument("--pr-number", type=int, required=True)
    pack.add_argument("--verified-pr-head-sha", required=True)
    pack.add_argument("--merge-sha", required=True)
    pack.add_argument("--read-instruction", action="append", dest="read_instructions", required=True)
    pack.add_argument("--probe-id", default=DEFAULT_PROBE_ID)

    compare = subparsers.add_parser("compare", help="compare one observation against one context pack")
    compare.add_argument("--pack-file", type=Path, required=True)
    compare.add_argument("--observation-file", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)

    receipt = subparsers.add_parser("receipt", help="build one durable probe receipt")
    receipt.add_argument("--pack-file", type=Path, required=True)
    receipt.add_argument("--observation-file", type=Path, required=True)
    receipt.add_argument("--comparison-file", type=Path, required=True)
    receipt.add_argument("--telemetry-file", type=Path, required=True)
    receipt.add_argument("--evidence-file", type=Path, required=True)
    receipt.add_argument("--output", type=Path, required=True)
    receipt.add_argument("--source-observed-at")
    return parser


def cli_main(argv: Sequence[str] | None = None) -> int:
    """Run the intentionally small local evidence CLI."""

    args = _build_parser().parse_args(argv)
    try:
        if args.command == "build-pack":
            _reject_output_alias(args.output, args.source_file)
            pack = build_context_pack(
                args.source_file.read_bytes(),
                source_ref=args.source_ref,
                source_observed_at=args.source_observed_at,
                slice_id=args.slice_id,
                repository=args.repository,
                issue_number=args.issue_number,
                pr_number=args.pr_number,
                verified_pr_head_sha=args.verified_pr_head_sha,
                merge_sha=args.merge_sha,
                read_instructions=args.read_instructions,
                probe_id=args.probe_id,
            )
            _write_json_file(args.output, pack)
        elif args.command == "compare":
            _reject_output_alias(args.output, args.pack_file, args.observation_file)
            pack = normalize_context_pack(_read_json_file(args.pack_file))
            observation = normalize_rehydrated_observation(_read_json_file(args.observation_file), context_pack=pack)
            _write_json_file(args.output, compare_rehydrated_observation(pack, observation))
        elif args.command == "receipt":
            _reject_output_alias(
                args.output,
                args.pack_file,
                args.observation_file,
                args.comparison_file,
                args.telemetry_file,
                args.evidence_file,
            )
            pack = normalize_context_pack(_read_json_file(args.pack_file))
            observation = normalize_rehydrated_observation(_read_json_file(args.observation_file), context_pack=pack)
            comparison = normalize_comparison(_read_json_file(args.comparison_file), context_pack=pack, observation=observation)
            receipt = build_probe_receipt(
                pack,
                observation,
                comparison,
                evidence_refs=_read_json_file(args.evidence_file),
                telemetry=_read_json_file(args.telemetry_file),
                source_observed_at=args.source_observed_at,
            )
            _write_json_file(args.output, receipt)
        else:  # pragma: no cover - argparse constrains commands.
            raise EpicRehydrationProbeError(f"unsupported command: {args.command}")
    except (OSError, EpicRehydrationProbeError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests.
    raise SystemExit(cli_main())


__all__ = [
    "COMPARISON_SCHEMA_NAME",
    "CONTEXT_PACK_SCHEMA_NAME",
    "DEFAULT_PROBE_ID",
    "EpicRehydrationProbeError",
    "OBSERVATION_SCHEMA_NAME",
    "PROBE_RECEIPT_SCHEMA_NAME",
    "build_context_pack",
    "build_probe_receipt",
    "canonical_json",
    "canonical_json_bytes",
    "compare_rehydrated_observation",
    "normalize_comparison",
    "normalize_context_pack",
    "normalize_probe_receipt",
    "normalize_rehydrated_observation",
    "parse_strict_json",
    "sha256_bytes",
]
