"""Pure, read-time proof composer for the devUI SoI Evidence View v0.

This module intentionally accepts an already-captured manifest.  It does not
read a store, infer relationships, or retain a projection between calls.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


CONTRACT_VERSION = "devui.soi_evidence_view.v0"
_HORIZONS = {"current", "target", "advisory", "historical"}
_AVAILABILITY = {"available", "unavailable", "refused", "unsupported"}
_FRESHNESS = {"fresh", "stale", "unknown"}
_COVERAGE = {"complete", "partial", "unread", "missing", "not_applicable"}
_CARDINALITY = {"nonempty", "measured_empty", "not_measured", "not_countable"}
_LINKAGE = {"linked", "unlinked", "not_assessed", "not_applicable"}


class SoIEvidenceContractError(ValueError):
    """Raised when a purported evidence manifest would overstate its evidence."""


def _json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    """Detach a JSON-safe manifest without retaining caller-owned objects."""

    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise SoIEvidenceContractError("manifest must be JSON-safe") from error
    if not isinstance(decoded, dict):
        raise SoIEvidenceContractError("manifest must be an object")
    return decoded


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _require_source_ref(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SoIEvidenceContractError(f"{label} must name a source-owned reference")
    required = ("ref", "revision", "authority_class")
    if value.get("source_owned") is not True or any(
        not _nonempty(value.get(key)) for key in required
    ):
        raise SoIEvidenceContractError(
            f"{label} must include source ownership, reference, revision, and authority"
        )
    return value


def _require_state(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SoIEvidenceContractError(f"{label} must be an independent source-state vector")
    allowed = {
        "availability": _AVAILABILITY,
        "freshness": _FRESHNESS,
        "coverage": _COVERAGE,
        "cardinality": _CARDINALITY,
        "linkage": _LINKAGE,
    }
    if any(value.get(axis) not in values for axis, values in allowed.items()):
        raise SoIEvidenceContractError(f"{label} has an unsupported source-state value")
    return {axis: value[axis] for axis in allowed}


def _rendered_state(state: dict[str, str]) -> dict[str, str]:
    """Withdraw a cardinality claim whenever the source cannot support one."""

    rendered = dict(state)
    if (
        rendered["availability"] != "available"
        or rendered["freshness"] != "fresh"
        or rendered["coverage"] == "unread"
    ):
        rendered["cardinality"] = "not_measured"
    return rendered


def _validate_manifest(manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if manifest.get("schema_version") != CONTRACT_VERSION or manifest.get("immutable") is not True:
        raise SoIEvidenceContractError("manifest must be an immutable v0 source manifest")
    scope = manifest.get("scope")
    if not isinstance(scope, dict) or not _nonempty(scope.get("subject_ref")):
        raise SoIEvidenceContractError("manifest must name a source-owned SoI scope")
    _require_source_ref(scope.get("source"), label="scope source")

    denominator = manifest.get("denominator")
    if not isinstance(denominator, dict) or denominator.get("status") not in {"known", "unknown"}:
        raise SoIEvidenceContractError("manifest must name denominator status")
    if denominator.get("horizon") not in _HORIZONS:
        raise SoIEvidenceContractError("denominator must name a claim horizon")
    if denominator["status"] == "known":
        _require_source_ref(denominator.get("source"), label="denominator source")
        for key in ("scope_ref", "observed_at"):
            if not _nonempty(denominator.get(key)):
                raise SoIEvidenceContractError(f"known denominator requires {key}")
        if not isinstance(denominator.get("expected_subject_refs"), list) or not isinstance(
            denominator.get("required_responsibilities"), list
        ):
            raise SoIEvidenceContractError("known denominator requires its expected sets")

    subjects = manifest.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise SoIEvidenceContractError("manifest must contain source-owned subjects")
    subject_refs: set[str] = set()
    for subject in subjects:
        if not isinstance(subject, dict) or not _nonempty(subject.get("subject_ref")):
            raise SoIEvidenceContractError("each subject requires a stable reference")
        _require_source_ref(subject.get("source"), label="subject source")
        subject_ref = subject["subject_ref"]
        if subject_ref in subject_refs:
            raise SoIEvidenceContractError("subject references must be unique")
        subject_refs.add(subject_ref)
    if scope["subject_ref"] not in subject_refs:
        raise SoIEvidenceContractError("scope must occur in the source-owned subject set")

    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        raise SoIEvidenceContractError("manifest must contain claims")
    for claim in claims:
        if (
            not isinstance(claim, dict)
            or not _nonempty(claim.get("claim_id"))
            or claim.get("subject_ref") not in subject_refs
            or not _nonempty(claim.get("responsibility"))
            or claim.get("horizon") not in _HORIZONS
        ):
            raise SoIEvidenceContractError(
                "each claim requires identity, subject, responsibility, and horizon"
            )
        _require_source_ref(claim.get("source"), label="claim source")
        _require_state(claim.get("source_state"), label="claim source state")

    relations = manifest.get("relations")
    unlinked = manifest.get("unlinked_subject_refs")
    if not isinstance(relations, list) or not isinstance(unlinked, list):
        raise SoIEvidenceContractError(
            "manifest must explicitly classify relations or unlinked subjects"
        )
    linked_subjects: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict):
            raise SoIEvidenceContractError("relation must be an object")
        _require_source_ref(relation.get("source"), label="relation source")
        endpoints = (relation.get("from_subject_ref"), relation.get("to_subject_ref"))
        if any(endpoint not in subject_refs for endpoint in endpoints):
            raise SoIEvidenceContractError("relation endpoints must be source-owned subjects")
        linked_subjects.update(endpoints)
    if any(ref not in subject_refs for ref in unlinked) or linked_subjects.intersection(unlinked):
        raise SoIEvidenceContractError("unlinked subjects must be known and cannot also be linked")
    if subject_refs != linked_subjects.union(unlinked):
        raise SoIEvidenceContractError("every subject must be explicitly linked or unlinked")
    if not isinstance(manifest.get("expected_result"), dict):
        raise SoIEvidenceContractError("manifest must retain an expected read result")
    return denominator, {"subject_refs": subject_refs}


def _can_render_complete(denominator: dict[str, Any]) -> bool:
    if denominator.get("status") != "known":
        return False
    children = denominator.get("expected_children")
    if not isinstance(children, list):
        return False
    return all(
        isinstance(child, dict) and child.get("coverage") == "complete" for child in children
    )


def compose_soi_evidence_view(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build one disposable evidence view from a supplied immutable manifest."""

    detached = _json_object(manifest)
    denominator, _ = _validate_manifest(detached)
    can_render_complete = _can_render_complete(denominator)
    if denominator.get("requested_coverage") == "complete" and not can_render_complete:
        raise SoIEvidenceContractError(
            "a complete claim requires a known denominator and complete expected children"
        )

    claims: list[dict[str, Any]] = []
    current_claim_ids: list[str] = []
    for claim in detached["claims"]:
        rendered_claim = dict(claim)
        rendered_claim["source_state"] = _rendered_state(claim["source_state"])
        claims.append(rendered_claim)
        if claim["horizon"] == "current":
            current_claim_ids.append(claim["claim_id"])

    return {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "scope": detached["scope"],
        "denominator": {
            "status": denominator["status"],
            "coverage": "complete" if can_render_complete else "partial",
            "source": denominator.get("source"),
            "scope_ref": denominator.get("scope_ref"),
        },
        "claims": claims,
        "current_claim_ids": current_claim_ids,
        "relations": detached["relations"],
        "unlinked_subject_refs": detached["unlinked_subject_refs"],
        "diagnostics": detached.get("diagnostics", {}),
        "presentation": {
            "ordering_basis": "manifest_source_order",
            "aggregate_controls": [],
        },
    }


__all__ = ["CONTRACT_VERSION", "SoIEvidenceContractError", "compose_soi_evidence_view"]
