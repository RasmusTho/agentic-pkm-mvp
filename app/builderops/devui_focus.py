"""Pure subject-centred Focus projection for devUI.

The composer validates source-owned inputs and returns a detached per-read view.
It owns no source reads, persistence, correlation, workflow state, or effect.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any


CONTRACT_VERSION = "focus-view.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ISSUE_STABLE_ID = re.compile(
    r"github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z"
)
_CAPABILITY_STABLE_ID = re.compile(r"[a-z][a-z0-9_.:-]{2,127}\Z")
_SUBJECT_KINDS = {"issue", "capability"}
_SUBJECT_SOURCE_TYPES = {
    "issue": {"github_issue"},
    "capability": {"owner_document"},
}
_AVAILABILITY = {"available", "unavailable", "refused", "unsupported"}
_FRESHNESS = {"fresh", "stale", "unknown"}
_COVERAGE = {"complete", "partial", "unread", "missing", "not_applicable"}
_CARDINALITY = {"nonempty", "measured_empty", "not_measured", "not_countable"}
_LINKAGE = {"linked", "unlinked", "not_assessed", "not_applicable"}
_OBSERVATION_LINKAGE = {"linked", "unlinked", "not_assessed"}
_CORRELATION_METHODS = {"governed_reference", "explicit_receipt"}
_ACTOR_CLASSES = {"agent", "owner", "system"}
_LEGALITY = {"legal", "blocked", "unavailable", "unknown"}
_PROVENANCE_ONLY_SOURCE_PARTS = {"session", "transcript"}


class FocusContractError(ValueError):
    """Raised when a proposed Focus view contradicts its authority contract."""


Now = Callable[[], datetime]


def _detached(value: Any, *, label: str) -> Any:
    try:
        _require_string_mapping_keys(value, label=label)
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8", errors="strict")
        return json.loads(encoded)
    except FocusContractError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FocusContractError(f"{label} must be JSON-safe") from exc


def _require_string_mapping_keys(value: Any, *, label: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FocusContractError(f"{label} objects require string keys")
            _require_string_mapping_keys(item, label=label)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _require_string_mapping_keys(item, label=label)


def _mapping(value: Any, *, label: str) -> dict[str, Any]:
    detached = _detached(value, label=label)
    if not isinstance(detached, dict) or any(
        not isinstance(key, str) for key in detached
    ):
        raise FocusContractError(f"{label} must be an object")
    return detached


def _items(value: Any, *, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise FocusContractError(f"{label} must be a list")
    detached = _detached(list(value), label=label)
    if not isinstance(detached, list):
        raise FocusContractError(f"{label} must be a list")
    return detached


def _nonempty(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FocusContractError(f"{label} must be a non-empty string")
    return value


def _keys(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    label: str,
) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise FocusContractError(f"{label} has unknown field(s): {sorted(unknown)}")
    if missing:
        raise FocusContractError(f"{label} is missing field(s): {sorted(missing)}")


def _timestamp(value: Any, *, label: str) -> str:
    raw = _nonempty(value, label=label)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FocusContractError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise FocusContractError(f"{label} must be timezone-aware")
    return raw


def _enum(value: Any, allowed: set[str], *, label: str) -> str:
    if value not in allowed:
        raise FocusContractError(f"{label} is unsupported")
    return value


def _source_ref(value: Any, *, label: str) -> dict[str, Any]:
    ref = _mapping(value, label=label)
    _keys(
        ref,
        allowed={
            "source_type",
            "source_id",
            "version",
            "snapshot",
            "content_hash",
            "locator",
        },
        required={"source_type", "source_id", "locator"},
        label=label,
    )
    _nonempty(ref.get("source_type"), label=f"{label}.source_type")
    _nonempty(ref.get("source_id"), label=f"{label}.source_id")
    _nonempty(ref.get("locator"), label=f"{label}.locator")

    version = ref.get("version")
    snapshot = ref.get("snapshot")
    content_hash = ref.get("content_hash")
    if version is not None:
        _nonempty(version, label=f"{label}.version")
    if snapshot is not None:
        _nonempty(snapshot, label=f"{label}.snapshot")
    if content_hash is not None and (
        not isinstance(content_hash, str) or not _SHA256.fullmatch(content_hash)
    ):
        raise FocusContractError(f"{label}.content_hash must be canonical SHA-256")
    if version is None and snapshot is None and content_hash is None:
        raise FocusContractError(
            f"{label} requires a version, snapshot, or content hash"
        )
    return ref


def _is_provenance_only(ref: Mapping[str, Any]) -> bool:
    parts = set(re.split(r"[^a-z0-9]+", str(ref["source_type"]).lower()))
    return bool(parts & _PROVENANCE_ONLY_SOURCE_PARTS)


def _require_authority_source(ref: Mapping[str, Any], *, label: str) -> None:
    if _is_provenance_only(ref):
        raise FocusContractError(
            f"{label} cannot use a provider session or transcript as authority"
        )


def _correlation_authority_ref(
    value: Any,
    *,
    subject: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    authority_ref = _source_ref(value, label=label)
    _require_authority_source(authority_ref, label="correlation")
    subject_authority = subject["authority_ref"]
    if (
        authority_ref["source_type"],
        authority_ref["source_id"],
    ) != (
        subject_authority["source_type"],
        subject_authority["source_id"],
    ):
        raise FocusContractError("correlation authority must match the selected subject")
    return authority_ref


def _subject_ref(value: Any) -> dict[str, Any]:
    subject = _mapping(value, label="subject")
    _keys(
        subject,
        allowed={"kind", "stable_id", "authority_ref", "title"},
        required={"kind", "stable_id", "authority_ref", "title"},
        label="subject",
    )
    kind = subject.get("kind")
    if kind not in _SUBJECT_KINDS:
        raise FocusContractError("subject must be a governed Issue or capability")
    stable_id = _nonempty(subject.get("stable_id"), label="subject.stable_id")
    _nonempty(subject.get("title"), label="subject.title")
    authority_ref = _source_ref(subject.get("authority_ref"), label="subject.authority_ref")
    if kind == "capability" and authority_ref["source_type"] != "owner_document":
        raise FocusContractError(
            "capability subject requires owner-document authority"
        )
    if authority_ref["source_type"] not in _SUBJECT_SOURCE_TYPES[kind]:
        raise FocusContractError("subject authority does not match its governed kind")
    if kind == "issue" and (
        not _ISSUE_STABLE_ID.fullmatch(stable_id)
        or stable_id.removeprefix("github:") != authority_ref["source_id"]
    ):
        raise FocusContractError("Issue subject requires an exact GitHub Issue identity")
    if kind == "capability" and not _CAPABILITY_STABLE_ID.fullmatch(stable_id):
        raise FocusContractError("capability subject requires a stable governed identity")
    subject["authority_ref"] = authority_ref
    return subject


def _owner_state(claim: Mapping[str, Any]) -> str:
    availability = claim["availability"]
    if availability != "available":
        return str(availability)
    coverage = claim["coverage"]
    if coverage in {"unread", "missing"}:
        return str(coverage)
    linkage = claim["linkage"]
    if linkage in {"unlinked", "not_assessed"}:
        return str(linkage)
    if claim["cardinality"] == "measured_empty":
        return "measured_empty"
    if claim["freshness"] == "stale":
        return "stale"
    if coverage == "partial":
        return "partial"
    return "fresh"


def _source_claim(value: Any, *, label: str) -> dict[str, Any]:
    claim = _mapping(value, label=label)
    _keys(
        claim,
        allowed={
            "claim_id",
            "claim",
            "source_ref",
            "availability",
            "freshness",
            "coverage",
            "cardinality",
            "linkage",
            "captured_at",
            "limitation",
            "read_watermark",
        },
        required={
            "claim_id",
            "claim",
            "source_ref",
            "availability",
            "freshness",
            "coverage",
            "cardinality",
            "linkage",
            "captured_at",
            "limitation",
        },
        label=label,
    )
    _nonempty(claim.get("claim_id"), label=f"{label}.claim_id")
    claim["source_ref"] = _source_ref(
        claim.get("source_ref"), label=f"{label}.source_ref"
    )
    claim["availability"] = _enum(
        claim.get("availability"), _AVAILABILITY, label=f"{label}.availability"
    )
    claim["freshness"] = _enum(
        claim.get("freshness"), _FRESHNESS, label=f"{label}.freshness"
    )
    claim["coverage"] = _enum(
        claim.get("coverage"), _COVERAGE, label=f"{label}.coverage"
    )
    claim["cardinality"] = _enum(
        claim.get("cardinality"), _CARDINALITY, label=f"{label}.cardinality"
    )
    claim["linkage"] = _enum(
        claim.get("linkage"), _LINKAGE, label=f"{label}.linkage"
    )
    _timestamp(claim.get("captured_at"), label=f"{label}.captured_at")

    supported_claim = claim.get("claim")
    if supported_claim is not None:
        _nonempty(supported_claim, label=f"{label}.claim")
        if _is_provenance_only(claim["source_ref"]):
            raise FocusContractError(
                "provider session or transcript evidence is provenance only"
            )
        if claim["linkage"] != "linked":
            raise FocusContractError("unlinked evidence cannot support a subject claim")
        if claim["availability"] != "available":
            raise FocusContractError("unavailable evidence cannot support a subject claim")
    else:
        _nonempty(claim.get("limitation"), label=f"{label}.limitation")

    if claim["cardinality"] == "measured_empty":
        watermark = claim.get("read_watermark")
        if (
            claim["availability"] != "available"
            or claim["coverage"] != "complete"
            or claim["linkage"] != "linked"
            or not isinstance(watermark, str)
            or not watermark.strip()
        ):
            raise FocusContractError(
                "measured_empty requires an available complete linked read watermark"
            )
    if claim["coverage"] in {"unread", "missing"} and claim["cardinality"] in {
        "nonempty",
        "measured_empty",
    }:
        raise FocusContractError("unread or missing coverage cannot claim a cardinality")
    if claim["coverage"] == "not_applicable" and (
        claim["cardinality"] != "not_countable"
        or claim["linkage"] != "not_applicable"
    ):
        raise FocusContractError(
            "not_applicable coverage requires non-countable, non-linkable evidence"
        )
    claim["owner_state"] = _owner_state(claim)
    return claim


def _owner_intent(value: Any) -> dict[str, Any]:
    intent = _mapping(value, label="owner_intent")
    _keys(
        intent,
        allowed={"summary", "source_ref"},
        required={"summary", "source_ref"},
        label="owner_intent",
    )
    _nonempty(intent.get("summary"), label="owner_intent.summary")
    intent["source_ref"] = _source_ref(
        intent.get("source_ref"), label="owner_intent.source_ref"
    )
    _require_authority_source(intent["source_ref"], label="owner intent")
    return intent


def _next_legal_step(value: Any) -> dict[str, Any]:
    step = _mapping(value, label="next_legal_step")
    _keys(
        step,
        allowed={"workflow_ref", "actor_class", "legality", "reason"},
        required={"workflow_ref", "actor_class", "legality", "reason"},
        label="next_legal_step",
    )
    step["actor_class"] = _enum(
        step.get("actor_class"), _ACTOR_CLASSES, label="next_legal_step.actor_class"
    )
    step["legality"] = _enum(
        step.get("legality"), _LEGALITY, label="next_legal_step.legality"
    )
    _nonempty(step.get("reason"), label="next_legal_step.reason")
    workflow_ref = step.get("workflow_ref")
    if step["legality"] == "legal" and (
        not isinstance(workflow_ref, str) or not workflow_ref.strip()
    ):
        raise FocusContractError("legal next step requires a workflow reference")
    if workflow_ref is not None:
        _nonempty(workflow_ref, label="next_legal_step.workflow_ref")
    return step


def _observation(
    value: Any, *, subject: Mapping[str, Any], label: str
) -> dict[str, Any]:
    observation = _mapping(value, label=label)
    _keys(
        observation,
        allowed={
            "observation_ref",
            "observed_at",
            "provider",
            "summary",
            "source_ref",
            "correlation",
        },
        required={
            "observation_ref",
            "observed_at",
            "provider",
            "summary",
            "source_ref",
            "correlation",
        },
        label=label,
    )
    _nonempty(observation.get("observation_ref"), label=f"{label}.observation_ref")
    _timestamp(observation.get("observed_at"), label=f"{label}.observed_at")
    _nonempty(observation.get("provider"), label=f"{label}.provider")
    _nonempty(observation.get("summary"), label=f"{label}.summary")
    observation["source_ref"] = _source_ref(
        observation.get("source_ref"), label=f"{label}.source_ref"
    )
    correlation = _mapping(
        observation.get("correlation"), label=f"{label}.correlation"
    )
    _keys(
        correlation,
        allowed={"status", "method", "authority_ref"},
        required={"status", "method", "authority_ref"},
        label=f"{label}.correlation",
    )
    status = _enum(
        correlation.get("status"),
        _OBSERVATION_LINKAGE,
        label=f"{label}.correlation.status",
    )
    method = correlation.get("method")
    authority_ref = correlation.get("authority_ref")
    if status == "linked":
        if method not in _CORRELATION_METHODS or authority_ref is None:
            raise FocusContractError(
                "linked observation requires governed reference or explicit receipt"
            )
        correlation["authority_ref"] = _correlation_authority_ref(
            authority_ref,
            subject=subject,
            label=f"{label}.correlation.authority_ref",
        )
    elif method != "none" or authority_ref is not None:
        raise FocusContractError(
            "unlinked observation cannot carry a correlation authority"
        )
    observation["correlation"] = correlation
    return observation


def _receipt(
    value: Any, *, subject: Mapping[str, Any], label: str
) -> dict[str, Any]:
    receipt = _mapping(value, label=label)
    _keys(
        receipt,
        allowed={"receipt_ref", "source_ref", "correlation"},
        required={"receipt_ref", "source_ref", "correlation"},
        label=label,
    )
    _nonempty(receipt.get("receipt_ref"), label=f"{label}.receipt_ref")
    receipt["source_ref"] = _source_ref(
        receipt.get("source_ref"), label=f"{label}.source_ref"
    )
    _require_authority_source(receipt["source_ref"], label="receipt")
    correlation = _mapping(receipt.get("correlation"), label=f"{label}.correlation")
    _keys(
        correlation,
        allowed={"status", "method", "authority_ref"},
        required={"status", "method", "authority_ref"},
        label=f"{label}.correlation",
    )
    if correlation.get("status") != "linked" or correlation.get("method") not in {
        "governed_reference",
        "explicit_receipt",
    }:
        raise FocusContractError("receipt requires explicit subject correlation")
    correlation["authority_ref"] = _correlation_authority_ref(
        correlation.get("authority_ref"),
        subject=subject,
        label=f"{label}.correlation.authority_ref",
    )
    receipt["correlation"] = correlation
    return receipt


def _risk(value: Any, *, label: str) -> dict[str, Any]:
    risk = _mapping(value, label=label)
    _keys(
        risk,
        allowed={"risk_id", "summary", "source_ref"},
        required={"risk_id", "summary", "source_ref"},
        label=label,
    )
    _nonempty(risk.get("risk_id"), label=f"{label}.risk_id")
    _nonempty(risk.get("summary"), label=f"{label}.summary")
    risk["source_ref"] = _source_ref(
        risk.get("source_ref"), label=f"{label}.source_ref"
    )
    _require_authority_source(risk["source_ref"], label="risk")
    return risk


def _conversation_port(value: Any) -> dict[str, Any]:
    port = _mapping(value, label="conversation_port")
    _keys(
        port,
        allowed={"availability", "reason"},
        required={"availability", "reason"},
        label="conversation_port",
    )
    port["availability"] = _enum(
        port.get("availability"), _AVAILABILITY, label="conversation_port.availability"
    )
    _nonempty(port.get("reason"), label="conversation_port.reason")
    return port


def _limitation(value: Any, *, label: str) -> dict[str, Any]:
    limitation = _mapping(value, label=label)
    _keys(
        limitation,
        allowed={
            "kind",
            "reason",
            "source_ref",
            "evidence_state",
            "observation_ref",
            "linkage",
            "provider",
            "observed_at",
        },
        required={"kind", "reason"},
        label=label,
    )
    _nonempty(limitation.get("kind"), label=f"{label}.kind")
    _nonempty(limitation.get("reason"), label=f"{label}.reason")
    if limitation.get("source_ref") is not None:
        limitation["source_ref"] = _source_ref(
            limitation["source_ref"], label=f"{label}.source_ref"
        )
    if limitation.get("observed_at") is not None:
        _timestamp(limitation["observed_at"], label=f"{label}.observed_at")
    return limitation


def _focus_state(
    governing_sources: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    *,
    has_unlinked_observation: bool,
) -> str:
    if any(
        source["availability"] != "available"
        or source["coverage"] in {"unread", "missing"}
        or source["linkage"] != "linked"
        for source in governing_sources
    ):
        return "focus_blocked"
    if has_unlinked_observation or any(
        claim["owner_state"] != "fresh" for claim in evidence
    ):
        return "focus_partial"
    return "focus_ready"


def compose_focus_view(
    *,
    subject: Mapping[str, Any],
    owner_intent: Mapping[str, Any],
    governing_sources: Sequence[Mapping[str, Any]],
    evidence: Sequence[Mapping[str, Any]],
    receipts: Sequence[Mapping[str, Any]],
    risks: Sequence[Mapping[str, Any]],
    next_legal_step: Mapping[str, Any],
    execution_observations: Sequence[Mapping[str, Any]],
    conversation_port: Mapping[str, Any],
    limitations: Sequence[Mapping[str, Any]],
    now: Now | None = None,
) -> dict[str, Any]:
    """Validate source-owned inputs and compose one detached Focus view."""

    captured_at = (now or (lambda: datetime.now(timezone.utc)))()
    if captured_at.tzinfo is None:
        raise FocusContractError("composition time must be timezone-aware")

    normalized_subject = _subject_ref(subject)
    normalized_intent = _owner_intent(owner_intent)
    normalized_governing = [
        _source_claim(item, label=f"governing_sources[{index}]")
        for index, item in enumerate(_items(governing_sources, label="governing_sources"))
    ]
    if not normalized_governing:
        raise FocusContractError("Focus requires at least one governing source")
    for source in normalized_governing:
        _require_authority_source(source["source_ref"], label="governing source")
    normalized_evidence = [
        _source_claim(item, label=f"evidence[{index}]")
        for index, item in enumerate(_items(evidence, label="evidence"))
    ]
    normalized_receipts = [
        _receipt(item, subject=normalized_subject, label=f"receipts[{index}]")
        for index, item in enumerate(_items(receipts, label="receipts"))
    ]
    normalized_risks = [
        _risk(item, label=f"risks[{index}]")
        for index, item in enumerate(_items(risks, label="risks"))
    ]
    normalized_limitations = [
        _limitation(item, label=f"limitations[{index}]")
        for index, item in enumerate(_items(limitations, label="limitations"))
    ]

    claim_ids = [
        claim["claim_id"] for claim in (*normalized_governing, *normalized_evidence)
    ]
    if len(claim_ids) != len(set(claim_ids)):
        raise FocusContractError("Focus claim identities must be unique")

    linked_observations: list[dict[str, Any]] = []
    has_unlinked_observation = False
    for index, item in enumerate(
        _items(execution_observations, label="execution_observations")
    ):
        observation = _observation(
            item,
            subject=normalized_subject,
            label=f"execution_observations[{index}]",
        )
        linkage = observation["correlation"]["status"]
        if linkage == "linked":
            linked_observations.append(observation)
            continue
        has_unlinked_observation = True
        normalized_limitations.append(
            {
                "kind": "unlinked_execution_observation",
                "observation_ref": observation["observation_ref"],
                "linkage": linkage,
                "provider": observation["provider"],
                "observed_at": observation["observed_at"],
                "source_ref": observation["source_ref"],
                "reason": "Observation has no source-owned subject correlation",
            }
        )

    state = _focus_state(
        normalized_governing,
        normalized_evidence,
        has_unlinked_observation=has_unlinked_observation,
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "authority": "projection_only",
        "composed_at": captured_at.isoformat(),
        "state": state,
        "subject": normalized_subject,
        "owner_intent": normalized_intent,
        "governing_sources": normalized_governing,
        "evidence": normalized_evidence,
        "receipts": normalized_receipts,
        "risks": normalized_risks,
        "next_legal_step": _next_legal_step(next_legal_step),
        "execution_observations": linked_observations,
        "conversation_port": _conversation_port(conversation_port),
        "limitations": normalized_limitations,
    }


__all__ = ["CONTRACT_VERSION", "FocusContractError", "compose_focus_view"]
