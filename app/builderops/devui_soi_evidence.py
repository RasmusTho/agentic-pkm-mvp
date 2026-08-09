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
    """Withdraw coverage and cardinality claims when their source cannot support them."""

    rendered = dict(state)
    if rendered["availability"] != "available":
        rendered["coverage"] = "unread"
        rendered["cardinality"] = "not_measured"
    elif rendered["freshness"] != "fresh" or rendered["coverage"] == "unread":
        rendered["cardinality"] = "not_measured"
    return rendered


def _validate_manifest(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], set[str], set[str]]:
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
        if any(
            not _nonempty(value)
            for value in (
                *denominator["expected_subject_refs"],
                *denominator["required_responsibilities"],
            )
        ):
            raise SoIEvidenceContractError("known denominator expected sets require stable values")

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
    if denominator.get("status") == "known":
        if denominator["scope_ref"] != scope["subject_ref"]:
            raise SoIEvidenceContractError("known denominator must belong to the named scope")
        if not set(denominator["expected_subject_refs"]).issubset(subject_refs):
            raise SoIEvidenceContractError(
                "known denominator expected subjects must be source-owned"
            )

    claims = manifest.get("claims")
    if not isinstance(claims, list) or not claims:
        raise SoIEvidenceContractError("manifest must contain claims")
    claim_ids: set[str] = set()
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
        if claim["claim_id"] in claim_ids:
            raise SoIEvidenceContractError("claim identities must be unique")
        claim_ids.add(claim["claim_id"])
        evidence = claim.get("evidence")
        if not isinstance(evidence, dict):
            raise SoIEvidenceContractError("claim evidence must be an object")
        if any(
            evidence.get(key) not in {None, "unsupported"}
            for key in ("owner_tried", "owner_accepted")
        ):
            raise SoIEvidenceContractError(
                "owner outcomes remain unsupported without an authorized receipt model"
            )

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
        if not _nonempty(relation.get("relation_ref")) or any(
            endpoint not in subject_refs for endpoint in endpoints
        ):
            raise SoIEvidenceContractError("relation endpoints must be source-owned subjects")
        linked_subjects.update(endpoints)
    if any(ref not in subject_refs for ref in unlinked) or linked_subjects.intersection(unlinked):
        raise SoIEvidenceContractError("unlinked subjects must be known and cannot also be linked")
    if subject_refs != linked_subjects.union(unlinked):
        raise SoIEvidenceContractError("every subject must be explicitly linked or unlinked")
    for claim in claims:
        linkage = claim["source_state"]["linkage"]
        if linkage == "linked" and claim["subject_ref"] not in linked_subjects:
            raise SoIEvidenceContractError("linked claim requires an explicit owned relation")
        if linkage == "unlinked" and claim["subject_ref"] not in unlinked:
            raise SoIEvidenceContractError("unlinked claim must match the manifest relation set")
    if not isinstance(manifest.get("expected_result"), dict):
        raise SoIEvidenceContractError("manifest must retain an expected read result")
    return denominator, subject_refs, linked_subjects


def _can_render_complete(
    denominator: dict[str, Any],
    *,
    claims: list[dict[str, Any]],
    linked_subjects: set[str],
    relations: list[dict[str, Any]],
) -> bool:
    if denominator.get("status") != "known":
        return False
    children = denominator.get("expected_children")
    if not isinstance(children, list):
        return False
    expected_subjects = denominator["expected_subject_refs"]
    if len(expected_subjects) != len(set(expected_subjects)) or {
        child.get("subject_ref") for child in children if isinstance(child, dict)
    } != set(expected_subjects):
        return False
    scope_ref = denominator["scope_ref"]
    scope_children = {
        relation["to_subject_ref"]
        if relation["from_subject_ref"] == scope_ref
        else relation["from_subject_ref"]
        for relation in relations
        if scope_ref in (relation["from_subject_ref"], relation["to_subject_ref"])
    }
    if (
        not all(
            isinstance(child, dict) and child.get("coverage") == "complete" for child in children
        )
        or not set(expected_subjects).issubset(linked_subjects)
        or not set(expected_subjects).issubset(scope_children)
    ):
        return False
    required = set(denominator["required_responsibilities"])
    for subject_ref in expected_subjects:
        current_responsibilities = {
            claim["responsibility"]
            for claim in claims
            if claim["subject_ref"] == subject_ref
            and claim["horizon"] == denominator["horizon"]
            and claim["source_state"]["availability"] == "available"
            and claim["source_state"]["freshness"] == "fresh"
            and claim["source_state"]["coverage"] == "complete"
            and claim["source_state"]["linkage"] == "linked"
        }
        if not required.issubset(current_responsibilities):
            return False
    return True


def _proof_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact result that an immutable proof manifest must predict."""

    return {
        "scope_ref": result["scope"]["subject_ref"],
        "denominator": {
            "status": result["denominator"]["status"],
            "coverage": result["denominator"]["coverage"],
        },
        "current_claim_ids": result["current_claim_ids"],
        "unlinked_subject_refs": result["unlinked_subject_refs"],
    }


def compose_soi_evidence_view(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build one disposable evidence view from a supplied immutable manifest."""

    detached = _json_object(manifest)
    denominator, _subject_refs, linked_subjects = _validate_manifest(detached)
    can_render_complete = _can_render_complete(
        denominator,
        claims=detached["claims"],
        linked_subjects=linked_subjects,
        relations=detached["relations"],
    )
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

    result = {
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
    if detached["expected_result"] != _proof_receipt(result):
        raise SoIEvidenceContractError("manifest expected result does not match the proof read")
    return result


__all__ = ["CONTRACT_VERSION", "SoIEvidenceContractError", "compose_soi_evidence_view"]
