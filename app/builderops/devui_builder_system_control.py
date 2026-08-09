"""Pure BSC-01 composer for declared Builder System governing documents.

This is deliberately not a source-discovery adapter.  Callers supply the
already captured declarations and their state evidence for every read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import json
import re
from typing import Any


CONTRACT_VERSION = "builder-system-control-view.v1"
_AUTHORITY_CLASSES = {"normative", "operational", "reference", "projection", "receipt"}
_PHASES = {"draft", "proposed", "accepted", "superseded", "retired", "unknown"}
_TEMPORAL_CLASSES = {"strategic", "operational", "snapshot", "historical", "unknown"}
_AVAILABILITY = {"available", "unavailable", "refused", "unsupported"}
_FRESHNESS = {"fresh", "stale", "unknown"}
_COVERAGE = {"complete", "partial", "unread", "missing", "not_applicable"}
_CARDINALITY = {"nonempty", "measured_empty", "not_measured", "not_countable"}
_LINKAGE = {"linked", "unlinked", "not_assessed", "not_applicable"}
_CAPABILITY_KINDS = {"mcp", "connector", "script", "cli"}
_SIDE_EFFECT_CLASSES = {
    "read_only",
    "governed_write",
    "external_effect",
    "mixed",
    "unknown",
}
_SHA256 = re.compile(r"[a-f0-9]{64}")
_PROVENANCE_ONLY_SOURCE_PARTS = {"provider", "session", "transcript"}


class GoverningDocumentContractError(ValueError):
    """Raised when declarations would overstate governing-document evidence."""


def _json_value(value: Any, *, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise GoverningDocumentContractError(f"{label} must be JSON-safe") from exc


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    detached = _json_value(value, label=label)
    if not isinstance(detached, dict):
        raise GoverningDocumentContractError(f"{label} must be an object")
    return detached


def _nonempty(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoverningDocumentContractError(f"{label} must be a non-empty string")
    return value


def _keys(value: Mapping[str, Any], *, allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise GoverningDocumentContractError(f"{label} has unknown field(s): {sorted(unknown)}")
    if missing:
        raise GoverningDocumentContractError(f"{label} is missing field(s): {sorted(missing)}")


def _timestamp(value: Any, *, label: str) -> str:
    timestamp = _nonempty(value, label=label)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GoverningDocumentContractError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise GoverningDocumentContractError(f"{label} must be timezone-aware")
    return timestamp


def _timestamp_value(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_provenance_only(reference: Mapping[str, Any]) -> bool:
    parts = set(re.split(r"[^a-z0-9]+", str(reference["source_type"]).lower()))
    return bool(parts & _PROVENANCE_ONLY_SOURCE_PARTS)


def _source_ref(value: Any, *, label: str) -> dict[str, Any]:
    reference = _mapping(value, label=label)
    _keys(
        reference,
        allowed={"source_type", "source_id", "version", "snapshot", "content_hash", "locator"},
        required={"source_type", "source_id", "locator"},
        label=label,
    )
    for key in ("source_type", "source_id", "locator"):
        _nonempty(reference.get(key), label=f"{label}.{key}")
    for key in ("version", "snapshot", "content_hash"):
        if reference.get(key) is not None:
            _nonempty(reference[key], label=f"{label}.{key}")
    content_hash = reference.get("content_hash")
    if content_hash is not None and not _SHA256.fullmatch(content_hash):
        raise GoverningDocumentContractError(f"{label}.content_hash must be a canonical SHA-256")
    if not any(reference.get(key) is not None for key in ("version", "snapshot", "content_hash")):
        raise GoverningDocumentContractError(
            f"{label} requires a version, snapshot, or content hash"
        )
    if _is_provenance_only(reference):
        raise GoverningDocumentContractError(
            f"{label} cannot use provider session or transcript provenance as authority"
        )
    return reference


def _limitations(value: Any, *, label: str) -> list[Any]:
    detached = _json_value(value, label=label)
    if not isinstance(detached, list):
        raise GoverningDocumentContractError(f"{label} must be a list")
    return detached


def _state(value: Any, *, label: str, composed_at: datetime) -> dict[str, Any]:
    state = _mapping(value, label=label)
    _keys(
        state,
        allowed={
            "availability",
            "freshness",
            "coverage",
            "cardinality",
            "linkage",
            "captured_at",
            "fresh_until",
            "freshness_rule",
            "read_scope",
            "read_watermark",
            "limitations",
        },
        required={
            "availability",
            "freshness",
            "coverage",
            "cardinality",
            "linkage",
            "captured_at",
            "read_scope",
            "read_watermark",
            "limitations",
        },
        label=label,
    )
    for key, allowed in (
        ("availability", _AVAILABILITY),
        ("freshness", _FRESHNESS),
        ("coverage", _COVERAGE),
        ("cardinality", _CARDINALITY),
        ("linkage", _LINKAGE),
    ):
        if state.get(key) not in allowed:
            raise GoverningDocumentContractError(f"{label}.{key} is unsupported")
    _timestamp(state["captured_at"], label=f"{label}.captured_at")
    _nonempty(state["read_scope"], label=f"{label}.read_scope")
    _nonempty(state["read_watermark"], label=f"{label}.read_watermark")
    fresh_until: datetime | None = None
    if state.get("fresh_until") is not None:
        fresh_until_text = _timestamp(state["fresh_until"], label=f"{label}.fresh_until")
        fresh_until = _timestamp_value(fresh_until_text)
    if state.get("freshness_rule") is not None:
        _nonempty(state["freshness_rule"], label=f"{label}.freshness_rule")
    if fresh_until is None and state.get("freshness_rule") is None:
        raise GoverningDocumentContractError(f"{label} requires a freshness basis")
    if state["freshness"] == "fresh" and fresh_until is not None and fresh_until <= composed_at:
        raise GoverningDocumentContractError(
            f"{label}.fresh_until must be later than composition for fresh evidence"
        )
    state["limitations"] = _limitations(state["limitations"], label=f"{label}.limitations")

    if state["availability"] != "available" and state["cardinality"] == "measured_empty":
        raise GoverningDocumentContractError(f"{label} unavailable source cannot be measured_empty")
    if state["availability"] != "available" and state["cardinality"] != "not_measured":
        raise GoverningDocumentContractError(
            f"{label} unavailable source cannot support a cardinality claim"
        )
    if state["freshness"] != "fresh" and state["cardinality"] == "measured_empty":
        raise GoverningDocumentContractError(
            f"{label} stale or unknown source cannot be measured_empty"
        )
    if state["coverage"] in {"unread", "missing"} and state["cardinality"] != "not_measured":
        raise GoverningDocumentContractError(
            f"{label} unread or missing coverage cannot support a cardinality claim"
        )
    if state["coverage"] == "not_applicable" and (
        state["cardinality"] != "not_countable" or state["linkage"] != "not_applicable"
    ):
        raise GoverningDocumentContractError(
            f"{label} not_applicable coverage requires non-countable, non-linkable evidence"
        )
    if state["cardinality"] == "measured_empty" and not (
        state["availability"] == "available"
        and state["freshness"] == "fresh"
        and state["coverage"] == "complete"
        and state["linkage"] == "linked"
    ):
        raise GoverningDocumentContractError(
            f"{label} measured_empty requires an available fresh complete linked read watermark"
        )
    return state


def _unknown_lifecycle() -> dict[str, Any]:
    return {
        "phase": "unknown",
        "temporal_class": "unknown",
        "review_cadence": "unknown",
        "supersedes_refs": [],
        "superseded_by_refs": [],
    }


def _lifecycle(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return _unknown_lifecycle()
    lifecycle = _mapping(value, label=label)
    _keys(
        lifecycle,
        allowed={
            "phase",
            "temporal_class",
            "review_cadence",
            "supersedes_refs",
            "superseded_by_refs",
        },
        required={
            "phase",
            "temporal_class",
            "review_cadence",
            "supersedes_refs",
            "superseded_by_refs",
        },
        label=label,
    )
    if lifecycle["phase"] not in _PHASES:
        raise GoverningDocumentContractError(f"{label}.phase is unsupported")
    if lifecycle["temporal_class"] not in _TEMPORAL_CLASSES:
        raise GoverningDocumentContractError(f"{label}.temporal_class is unsupported")
    if lifecycle["review_cadence"] != "unknown":
        _nonempty(lifecycle["review_cadence"], label=f"{label}.review_cadence")
    for key in ("supersedes_refs", "superseded_by_refs"):
        references = lifecycle[key]
        if not isinstance(references, list):
            raise GoverningDocumentContractError(f"{label}.{key} must be a list")
        lifecycle[key] = [
            _source_ref(reference, label=f"{label}.{key}[{index}]")
            for index, reference in enumerate(references)
        ]
    return lifecycle


def _governing_document(value: Any, *, index: int, composed_at: datetime) -> dict[str, Any]:
    label = f"declarations[{index}]"
    document = _mapping(value, label=label)
    _keys(
        document,
        allowed={
            "source_ref",
            "role",
            "authority_class",
            "authority_scope",
            "owner_ref",
            "lifecycle",
            "source_state",
            "limitations",
        },
        required={
            "source_ref",
            "role",
            "authority_class",
            "authority_scope",
            "source_state",
            "limitations",
        },
        label=label,
    )
    document["source_ref"] = _source_ref(document["source_ref"], label=f"{label}.source_ref")
    _nonempty(document["role"], label=f"{label}.role")
    if document["authority_class"] not in _AUTHORITY_CLASSES:
        raise GoverningDocumentContractError(f"{label}.authority_class is unsupported")
    _nonempty(document["authority_scope"], label=f"{label}.authority_scope")
    owner = document.get("owner_ref")
    document["owner_ref"] = (
        None if owner is None else _source_ref(owner, label=f"{label}.owner_ref")
    )
    lifecycle_is_missing = document.get("lifecycle") is None
    document["lifecycle"] = _lifecycle(document.get("lifecycle"), label=f"{label}.lifecycle")
    document["source_state"] = _state(
        document["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    document["limitations"] = _limitations(document["limitations"], label=f"{label}.limitations")

    state = document["source_state"]
    if document["owner_ref"] is None and (
        state["coverage"] != "missing"
        or state["cardinality"] != "not_measured"
        or state["linkage"] != "unlinked"
    ):
        raise GoverningDocumentContractError(
            f"{label} missing owner must remain missing and unlinked"
        )
    if lifecycle_is_missing and (
        state["coverage"] != "missing" or state["cardinality"] != "not_measured"
    ):
        raise GoverningDocumentContractError(
            f"{label} missing lifecycle cannot support a completeness claim"
        )
    return document


def _references(value: Any, *, label: str) -> list[dict[str, Any]]:
    references = _json_value(value, label=label)
    if not isinstance(references, list):
        raise GoverningDocumentContractError(f"{label} must be a list")
    return [
        _source_ref(reference, label=f"{label}[{index}]")
        for index, reference in enumerate(references)
    ]


def _strings(value: Any, *, label: str) -> list[str]:
    values = _json_value(value, label=label)
    if not isinstance(values, list):
        raise GoverningDocumentContractError(f"{label} must be a list")
    return [_nonempty(item, label=f"{label}[{index}]") for index, item in enumerate(values)]


def _missing_or_unlinked_state(state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Withdraw claims a declaration cannot support without inventing an owner."""

    rendered = dict(state)
    rendered["coverage"] = "missing"
    rendered["cardinality"] = "not_measured"
    rendered["linkage"] = "unlinked"
    rendered["limitations"] = [*rendered["limitations"], reason]
    return rendered


def _workflow_adapter(value: Any, *, index: int, composed_at: datetime) -> dict[str, Any]:
    label = f"workflow_adapter_declarations[{index}]"
    adapter = _mapping(value, label=label)
    _keys(
        adapter,
        allowed={
            "source_ref",
            "adapter_kind",
            "adapter_id",
            "version_or_digest",
            "owning_workflow_refs",
            "owning_policy_refs",
            "trigger",
            "input_contract_refs",
            "output_and_receipt_refs",
            "refusal_and_authority_limits",
            "source_state",
            "limitations",
        },
        required={
            "source_ref",
            "adapter_kind",
            "adapter_id",
            "version_or_digest",
            "owning_workflow_refs",
            "owning_policy_refs",
            "trigger",
            "input_contract_refs",
            "output_and_receipt_refs",
            "refusal_and_authority_limits",
            "source_state",
            "limitations",
        },
        label=label,
    )
    adapter["source_ref"] = _source_ref(adapter["source_ref"], label=f"{label}.source_ref")
    if adapter["adapter_kind"] != "skill":
        raise GoverningDocumentContractError(f"{label}.adapter_kind must be skill")
    _nonempty(adapter["adapter_id"], label=f"{label}.adapter_id")
    version = adapter["version_or_digest"]
    if version is not None:
        _nonempty(version, label=f"{label}.version_or_digest")
    adapter["version_or_digest"] = "unknown" if version is None else version
    adapter["owning_workflow_refs"] = _references(
        adapter["owning_workflow_refs"], label=f"{label}.owning_workflow_refs"
    )
    adapter["owning_policy_refs"] = _references(
        adapter["owning_policy_refs"], label=f"{label}.owning_policy_refs"
    )
    _nonempty(adapter["trigger"], label=f"{label}.trigger")
    adapter["input_contract_refs"] = _references(
        adapter["input_contract_refs"], label=f"{label}.input_contract_refs"
    )
    adapter["output_and_receipt_refs"] = _references(
        adapter["output_and_receipt_refs"], label=f"{label}.output_and_receipt_refs"
    )
    adapter["refusal_and_authority_limits"] = _strings(
        adapter["refusal_and_authority_limits"],
        label=f"{label}.refusal_and_authority_limits",
    )
    adapter["source_state"] = _state(
        adapter["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    adapter["limitations"] = _limitations(adapter["limitations"], label=f"{label}.limitations")

    if version in {None, "unknown"} or not adapter["owning_workflow_refs"]:
        adapter["source_state"] = _missing_or_unlinked_state(
            adapter["source_state"],
            reason="incomplete explicit adapter declaration withdraws ownership claims",
        )
    return adapter


def _capability_binding(value: Any, *, index: int, composed_at: datetime) -> dict[str, Any]:
    label = f"capability_binding_declarations[{index}]"
    capability = _mapping(value, label=label)
    _keys(
        capability,
        allowed={
            "source_ref",
            "capability_kind",
            "capability_id",
            "version_or_digest",
            "owning_workflow_refs",
            "available_operations",
            "side_effect_class",
            "admission_boundary_ref",
            "explicit_non_authority",
            "source_state",
            "limitations",
        },
        required={
            "source_ref",
            "capability_kind",
            "capability_id",
            "version_or_digest",
            "owning_workflow_refs",
            "available_operations",
            "side_effect_class",
            "admission_boundary_ref",
            "explicit_non_authority",
            "source_state",
            "limitations",
        },
        label=label,
    )
    capability["source_ref"] = _source_ref(capability["source_ref"], label=f"{label}.source_ref")
    if capability["capability_kind"] not in _CAPABILITY_KINDS:
        raise GoverningDocumentContractError(f"{label}.capability_kind is unsupported")
    _nonempty(capability["capability_id"], label=f"{label}.capability_id")
    version = capability["version_or_digest"]
    if version is not None:
        _nonempty(version, label=f"{label}.version_or_digest")
    capability["owning_workflow_refs"] = _references(
        capability["owning_workflow_refs"], label=f"{label}.owning_workflow_refs"
    )
    capability["available_operations"] = _strings(
        capability["available_operations"], label=f"{label}.available_operations"
    )
    if capability["side_effect_class"] not in _SIDE_EFFECT_CLASSES:
        raise GoverningDocumentContractError(f"{label}.side_effect_class is unsupported")
    admission = capability["admission_boundary_ref"]
    capability["admission_boundary_ref"] = (
        None
        if admission is None
        else _source_ref(admission, label=f"{label}.admission_boundary_ref")
    )
    capability["explicit_non_authority"] = _strings(
        capability["explicit_non_authority"], label=f"{label}.explicit_non_authority"
    )
    capability["source_state"] = _state(
        capability["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    capability["limitations"] = _limitations(
        capability["limitations"], label=f"{label}.limitations"
    )

    requires_admission = capability["side_effect_class"] in {
        "governed_write",
        "external_effect",
        "mixed",
    }
    if (
        version is None
        or not capability["owning_workflow_refs"]
        or (requires_admission and capability["admission_boundary_ref"] is None)
    ):
        capability["source_state"] = _missing_or_unlinked_state(
            capability["source_state"],
            reason="incomplete explicit capability declaration withdraws authority claims",
        )
    return capability


def _coverage_exception(
    value: Any, *, index: int, composed_at: datetime
) -> tuple[dict[str, Any] | None, str | None]:
    """Return an admitted exception ref or a truthful unknown marker."""

    label = f"coverage_declarations exception_declarations[{index}]"
    exception = _mapping(value, label=label)
    _keys(
        exception,
        allowed={
            "source_ref",
            "permitting_authority_ref",
            "lifecycle_ref",
            "expires_at",
            "limitations",
        },
        required={
            "source_ref",
            "permitting_authority_ref",
            "lifecycle_ref",
            "expires_at",
            "limitations",
        },
        label=label,
    )
    source_ref = _source_ref(exception["source_ref"], label=f"{label}.source_ref")
    permitting_authority = exception["permitting_authority_ref"]
    lifecycle = exception["lifecycle_ref"]
    expires_at = exception["expires_at"]
    _limitations(exception["limitations"], label=f"{label}.limitations")

    if permitting_authority is None or lifecycle is None or expires_at is None:
        return None, f"exception:{source_ref['source_id']}"
    permitting_authority_ref = _source_ref(
        permitting_authority, label=f"{label}.permitting_authority_ref"
    )
    lifecycle_ref = _source_ref(lifecycle, label=f"{label}.lifecycle_ref")
    expires_at_text = _timestamp(expires_at, label=f"{label}.expires_at")
    if _timestamp_value(expires_at_text) <= composed_at:
        return None, f"exception:{source_ref['source_id']}"
    return {
        "source_ref": source_ref,
        "permitting_authority_ref": permitting_authority_ref,
        "lifecycle_ref": lifecycle_ref,
        "expires_at": expires_at_text,
        "limitations": _limitations(exception["limitations"], label=f"{label}.limitations"),
    }, None


def _drift_observations(value: Any, *, label: str) -> list[dict[str, Any]]:
    observations = _json_value(value, label=label)
    if not isinstance(observations, list):
        raise GoverningDocumentContractError(f"{label} must be a list")
    rendered: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        item_label = f"{label}[{index}]"
        item = _mapping(observation, label=item_label)
        _keys(
            item,
            allowed={"source_ref", "observed_at", "difference"},
            required={"source_ref", "observed_at", "difference"},
            label=item_label,
        )
        item["source_ref"] = _source_ref(item["source_ref"], label=f"{item_label}.source_ref")
        item["observed_at"] = _timestamp(item["observed_at"], label=f"{item_label}.observed_at")
        _nonempty(item["difference"], label=f"{item_label}.difference")
        rendered.append(item)
    return rendered


def _coverage(value: Any, *, index: int, composed_at: datetime) -> dict[str, Any]:
    label = f"coverage_declarations[{index}]"
    coverage = _mapping(value, label=label)
    _keys(
        coverage,
        allowed={
            "claim_id",
            "source_ref",
            "authority_scope",
            "governing_source_refs",
            "completeness_definition_ref",
            "assessed_scope",
            "source_state",
            "drift_observations",
            "exception_declarations",
            "unknowns",
            "limitations",
        },
        required={
            "claim_id",
            "source_ref",
            "authority_scope",
            "governing_source_refs",
            "completeness_definition_ref",
            "assessed_scope",
            "source_state",
            "drift_observations",
            "exception_declarations",
            "unknowns",
            "limitations",
        },
        label=label,
    )
    _nonempty(coverage["claim_id"], label=f"{label}.claim_id")
    coverage["source_ref"] = _source_ref(coverage["source_ref"], label=f"{label}.source_ref")
    _nonempty(coverage["authority_scope"], label=f"{label}.authority_scope")
    coverage["governing_source_refs"] = _references(
        coverage["governing_source_refs"], label=f"{label}.governing_source_refs"
    )
    completeness_definition = coverage["completeness_definition_ref"]
    coverage["completeness_definition_ref"] = (
        None
        if completeness_definition is None
        else _source_ref(
            completeness_definition,
            label=f"{label}.completeness_definition_ref",
        )
    )
    _nonempty(coverage["assessed_scope"], label=f"{label}.assessed_scope")
    coverage["source_state"] = _state(
        coverage["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    coverage["drift_observations"] = _drift_observations(
        coverage["drift_observations"], label=f"{label}.drift_observations"
    )
    exceptions = _json_value(coverage["exception_declarations"], label=f"{label}.exception_declarations")
    if not isinstance(exceptions, list):
        raise GoverningDocumentContractError(f"{label}.exception_declarations must be a list")
    admitted_exceptions: list[dict[str, Any]] = []
    withdrawn_exceptions: list[str] = []
    for exception_index, exception in enumerate(exceptions):
        exception, withdrawn = _coverage_exception(
            exception, index=exception_index, composed_at=composed_at
        )
        if exception is not None:
            admitted_exceptions.append(exception)
        if withdrawn is not None:
            withdrawn_exceptions.append(withdrawn)
    coverage["unknowns"] = [
        *_strings(coverage["unknowns"], label=f"{label}.unknowns"),
        *withdrawn_exceptions,
    ]
    coverage["limitations"] = _limitations(coverage["limitations"], label=f"{label}.limitations")

    state = coverage["source_state"]
    complete_is_admitted = (
        coverage["completeness_definition_ref"] is not None
        and bool(coverage["governing_source_refs"])
        and state["availability"] == "available"
        and state["freshness"] == "fresh"
        and state["linkage"] == "linked"
    )
    if state["coverage"] == "complete" and not complete_is_admitted:
        coverage["source_state"] = _missing_or_unlinked_state(
            state,
            reason="incomplete coverage evidence withdraws the completeness claim",
        )

    return {
        "claim_id": coverage["claim_id"],
        "source_ref": coverage["source_ref"],
        "authority_scope": coverage["authority_scope"],
        "governing_source_refs": coverage["governing_source_refs"],
        "completeness_definition_ref": coverage["completeness_definition_ref"],
        "assessed_scope": coverage["assessed_scope"],
        "source_state": coverage["source_state"],
        "drift_observations": coverage["drift_observations"],
        "exception_refs": [exception["source_ref"] for exception in admitted_exceptions],
        "exceptions": admitted_exceptions,
        "unknowns": coverage["unknowns"],
        "limitations": coverage["limitations"],
    }


def _governed_route(value: Any, *, label: str, composed_at: datetime) -> dict[str, Any]:
    route = _mapping(value, label=label)
    _keys(
        route,
        allowed={
            "route_id",
            "source_ref",
            "entrypoint",
            "authority_or_admission_ref",
            "accepted_inputs",
            "expected_side_effects",
            "expected_non_effects",
            "receipt_ref",
            "source_state",
            "limitations",
        },
        required={
            "route_id",
            "source_ref",
            "entrypoint",
            "authority_or_admission_ref",
            "accepted_inputs",
            "expected_side_effects",
            "expected_non_effects",
            "receipt_ref",
            "source_state",
            "limitations",
        },
        label=label,
    )
    _nonempty(route["route_id"], label=f"{label}.route_id")
    route["source_ref"] = _source_ref(route["source_ref"], label=f"{label}.source_ref")
    _nonempty(route["entrypoint"], label=f"{label}.entrypoint")
    route["authority_or_admission_ref"] = _source_ref(
        route["authority_or_admission_ref"],
        label=f"{label}.authority_or_admission_ref",
    )
    route["accepted_inputs"] = _strings(route["accepted_inputs"], label=f"{label}.accepted_inputs")
    route["expected_side_effects"] = _strings(
        route["expected_side_effects"], label=f"{label}.expected_side_effects"
    )
    route["expected_non_effects"] = _strings(
        route["expected_non_effects"], label=f"{label}.expected_non_effects"
    )
    route["receipt_ref"] = _source_ref(route["receipt_ref"], label=f"{label}.receipt_ref")
    route["source_state"] = _state(
        route["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    route["limitations"] = _limitations(route["limitations"], label=f"{label}.limitations")
    return route


def _route_deviation(value: Any, *, index: int, composed_at: datetime) -> dict[str, Any]:
    label = f"route_deviation_declarations[{index}]"
    deviation = _mapping(value, label=label)
    _keys(
        deviation,
        allowed={
            "deviation_id",
            "source_ref",
            "authority_scope",
            "intended_route_refs",
            "observed_route_refs",
            "correlation_ref",
            "observed_at",
            "difference",
            "source_state",
            "existing_repair_route_ref",
            "repair_route_linkage",
            "repair_route_correlation_ref",
            "limitations",
        },
        required={
            "deviation_id",
            "source_ref",
            "authority_scope",
            "intended_route_refs",
            "observed_route_refs",
            "correlation_ref",
            "observed_at",
            "difference",
            "source_state",
            "existing_repair_route_ref",
            "repair_route_linkage",
            "repair_route_correlation_ref",
            "limitations",
        },
        label=label,
    )
    _nonempty(deviation["deviation_id"], label=f"{label}.deviation_id")
    deviation["source_ref"] = _source_ref(deviation["source_ref"], label=f"{label}.source_ref")
    _nonempty(deviation["authority_scope"], label=f"{label}.authority_scope")
    deviation["intended_route_refs"] = _references(
        deviation["intended_route_refs"], label=f"{label}.intended_route_refs"
    )
    deviation["observed_route_refs"] = _references(
        deviation["observed_route_refs"], label=f"{label}.observed_route_refs"
    )
    if not deviation["intended_route_refs"] or not deviation["observed_route_refs"]:
        raise GoverningDocumentContractError(f"{label} requires intended and observed route refs")
    deviation["correlation_ref"] = _source_ref(
        deviation["correlation_ref"], label=f"{label}.correlation_ref"
    )
    observed_at = _timestamp(deviation["observed_at"], label=f"{label}.observed_at")
    if _timestamp_value(observed_at) > composed_at:
        raise GoverningDocumentContractError(f"{label}.observed_at cannot be after composition")
    deviation["observed_at"] = observed_at
    _nonempty(deviation["difference"], label=f"{label}.difference")
    deviation["source_state"] = _state(
        deviation["source_state"], label=f"{label}.source_state", composed_at=composed_at
    )
    if deviation["source_state"]["linkage"] != "linked":
        raise GoverningDocumentContractError(f"{label}.source_state must remain linked")
    route = deviation["existing_repair_route_ref"]
    linkage = deviation["repair_route_linkage"]
    if linkage not in {"linked", "unlinked", "not_assessed"}:
        raise GoverningDocumentContractError(f"{label}.repair_route_linkage is unsupported")
    correlation = deviation["repair_route_correlation_ref"]
    if route is None:
        if linkage not in {"unlinked", "not_assessed"} or correlation is not None:
            raise GoverningDocumentContractError(
                f"{label} null repair route requires unlinked or not_assessed linkage"
            )
    else:
        if linkage != "linked" or correlation is None:
            raise GoverningDocumentContractError(
                f"{label} linked repair route requires applicability correlation"
            )
        deviation["existing_repair_route_ref"] = _governed_route(
            route,
            label=f"{label}.existing_repair_route_ref",
            composed_at=composed_at,
        )
    deviation["repair_route_correlation_ref"] = (
        None
        if correlation is None
        else _source_ref(correlation, label=f"{label}.repair_route_correlation_ref")
    )
    deviation["limitations"] = _limitations(
        deviation["limitations"], label=f"{label}.limitations"
    )
    return deviation


def compose_governing_document_inventory(
    *,
    repository_ref: str,
    governance_baseline_ref: Mapping[str, Any],
    composed_at: str,
    declarations: Sequence[Mapping[str, Any]],
    limitations: Sequence[Any],
) -> dict[str, Any]:
    """Compose a disposable governing-document inventory from supplied declarations only."""

    _nonempty(repository_ref, label="repository_ref")
    baseline = _source_ref(governance_baseline_ref, label="governance_baseline_ref")
    composed_at_text = _timestamp(composed_at, label="composed_at")
    composed_at_value = _timestamp_value(composed_at_text)
    supplied = _json_value(declarations, label="declarations")
    if not isinstance(supplied, list) or not supplied:
        raise GoverningDocumentContractError(
            "declarations must contain at least one explicit governing document"
        )
    documents = [
        _governing_document(document, index=index, composed_at=composed_at_value)
        for index, document in enumerate(supplied)
    ]
    identities = [
        (document["source_ref"]["source_id"], document["source_ref"].get("version"))
        for document in documents
    ]
    if len(identities) != len(set(identities)):
        raise GoverningDocumentContractError(
            "governing document declarations must have unique exact source references"
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "primary_identity": "builder_system",
        "scope": {
            "kind": "builder_system",
            "repository_ref": repository_ref,
            "governance_baseline_ref": baseline,
        },
        "composed_at": composed_at_text,
        "governing_documents": documents,
        "limitations": _limitations(limitations, label="limitations"),
    }


def compose_builder_system_control_view(
    *,
    repository_ref: str,
    governance_baseline_ref: Mapping[str, Any],
    composed_at: str,
    governing_document_declarations: Sequence[Mapping[str, Any]],
    workflow_adapter_declarations: Sequence[Mapping[str, Any]],
    capability_binding_declarations: Sequence[Mapping[str, Any]],
    coverage_declarations: Sequence[Mapping[str, Any]],
    route_deviation_declarations: Sequence[Mapping[str, Any]],
    governed_route_declarations: Sequence[Mapping[str, Any]],
    limitations: Sequence[Any],
) -> dict[str, Any]:
    """Extend the BSC view from explicit, caller-supplied declarations only."""

    view = compose_governing_document_inventory(
        repository_ref=repository_ref,
        governance_baseline_ref=governance_baseline_ref,
        composed_at=composed_at,
        declarations=governing_document_declarations,
        limitations=limitations,
    )
    composed_at_value = _timestamp_value(view["composed_at"])
    adapters = _json_value(workflow_adapter_declarations, label="workflow_adapter_declarations")
    capabilities = _json_value(
        capability_binding_declarations, label="capability_binding_declarations"
    )
    coverage = _json_value(coverage_declarations, label="coverage_declarations")
    deviations = _json_value(route_deviation_declarations, label="route_deviation_declarations")
    routes = _json_value(governed_route_declarations, label="governed_route_declarations")
    if not isinstance(adapters, list):
        raise GoverningDocumentContractError("workflow_adapter_declarations must be a list")
    if not isinstance(capabilities, list):
        raise GoverningDocumentContractError("capability_binding_declarations must be a list")
    if not isinstance(coverage, list):
        raise GoverningDocumentContractError("coverage_declarations must be a list")
    if not isinstance(deviations, list):
        raise GoverningDocumentContractError("route_deviation_declarations must be a list")
    if not isinstance(routes, list):
        raise GoverningDocumentContractError("governed_route_declarations must be a list")
    view["workflow_adapters"] = [
        _workflow_adapter(adapter, index=index, composed_at=composed_at_value)
        for index, adapter in enumerate(adapters)
    ]
    view["capability_bindings"] = [
        _capability_binding(capability, index=index, composed_at=composed_at_value)
        for index, capability in enumerate(capabilities)
    ]
    view["coverage"] = [
        _coverage(item, index=index, composed_at=composed_at_value)
        for index, item in enumerate(coverage)
    ]
    view["deviations"] = [
        _route_deviation(item, index=index, composed_at=composed_at_value)
        for index, item in enumerate(deviations)
    ]
    view["governed_routes"] = [
        _governed_route(item, label=f"governed_route_declarations[{index}]", composed_at=composed_at_value)
        for index, item in enumerate(routes)
    ]
    return view


__all__ = [
    "CONTRACT_VERSION",
    "GoverningDocumentContractError",
    "compose_builder_system_control_view",
    "compose_governing_document_inventory",
]
