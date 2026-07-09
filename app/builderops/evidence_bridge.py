"""Observe-only PR/CI/review evidence bridge helpers."""

from __future__ import annotations

from typing import Any, Mapping

from app.builderops.models import BuilderOpsValidationError, validate_source_refs

OBSERVED_EVIDENCE_KINDS = frozenset(
    {
        "ci_failure",
        "review_finding",
        "missing_evidence",
        "human_exception",
        "tcd_signal",
    }
)
UNKNOWN_EVIDENCE_KINDS = frozenset(
    {
        "unknown_ci_context",
        "unknown_review_context",
        "unknown_artifact",
        "unknown_for_retro",
    }
)
EVIDENCE_BRIDGE_ROUTES = frozenset(
    {
        "learning_signal",
        "issue_candidate",
        "debt_fitness_candidate",
        "discard",
    }
)


class EvidenceBridgeError(BuilderOpsValidationError):
    """Raised when evidence bridge input is malformed."""


def build_evidence_bridge_report(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Classify delivery evidence into observe-only reevaluation candidates."""

    if not isinstance(evidence, Mapping):
        raise EvidenceBridgeError("evidence payload must be an object")

    observed = _normalize_entries(
        evidence.get("observed", []),
        field="observed",
        allowed_kinds=OBSERVED_EVIDENCE_KINDS,
        require_source_refs=True,
    )
    unknown = _normalize_entries(
        evidence.get("unknown", []),
        field="unknown",
        allowed_kinds=UNKNOWN_EVIDENCE_KINDS,
        require_source_refs=False,
    )
    evidence_ids = {item["id"] for item in [*observed, *unknown]}
    candidate = _normalize_candidates(
        evidence.get("candidate", evidence.get("candidates", [])),
        evidence_ids=evidence_ids,
    )

    return {
        "observe_only": True,
        "mutations_performed": False,
        "mutation_channels": {
            "git_push": False,
            "github_label": False,
            "github_merge": False,
            "github_project": False,
            "product_runtime": False,
        },
        "observed": observed,
        "unknown": unknown,
        "candidate": candidate,
        "routing_outcomes": sorted(EVIDENCE_BRIDGE_ROUTES),
        "receipt_body": _receipt_body(observed, unknown, candidate),
    }


def _normalize_entries(
    value: Any,
    *,
    field: str,
    allowed_kinds: frozenset[str],
    require_source_refs: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EvidenceBridgeError(f"{field} must be a list")
    entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise EvidenceBridgeError(f"{field}[{index}] must be an object")
        entry_id = _required_string(item.get("id"), f"{field}[{index}].id")
        if entry_id in seen_ids:
            raise EvidenceBridgeError(f"duplicate evidence id: {entry_id}")
        seen_ids.add(entry_id)
        kind = _required_string(item.get("kind"), f"{field}[{index}].kind")
        if kind not in allowed_kinds:
            raise EvidenceBridgeError(
                f"{field}[{index}].kind must be one of {sorted(allowed_kinds)}"
            )
        summary = _required_string(item.get("summary"), f"{field}[{index}].summary")
        entry: dict[str, Any] = {"id": entry_id, "kind": kind, "summary": summary}
        source_refs = item.get("source_refs")
        if source_refs is not None:
            entry["source_refs"] = _validated_source_refs(
                source_refs,
                f"{field}[{index}].source_refs",
            )
        elif require_source_refs:
            raise EvidenceBridgeError(f"{field}[{index}].source_refs must be provided")
        if item.get("notes"):
            entry["notes"] = _required_string(item["notes"], f"{field}[{index}].notes")
        return_unknown_bucket = item.get("unknown_for_retro")
        if return_unknown_bucket is not None:
            entry["unknown_for_retro"] = bool(return_unknown_bucket)
        entries.append(entry)
    return entries


def _normalize_candidates(
    value: Any,
    *,
    evidence_ids: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise EvidenceBridgeError("candidate must be a list")
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise EvidenceBridgeError(f"candidate[{index}] must be an object")
        candidate_id = _required_string(item.get("id"), f"candidate[{index}].id")
        if candidate_id in seen_ids:
            raise EvidenceBridgeError(f"duplicate candidate id: {candidate_id}")
        seen_ids.add(candidate_id)
        route = _required_string(item.get("route"), f"candidate[{index}].route")
        if route not in EVIDENCE_BRIDGE_ROUTES:
            raise EvidenceBridgeError(
                f"candidate[{index}].route must be one of {sorted(EVIDENCE_BRIDGE_ROUTES)}"
            )
        source_refs = _validated_source_refs(
            item.get("source_refs"),
            f"candidate[{index}].source_refs",
        )
        upstream_artifact = _optional_string(
            item.get("upstream_artifact"),
            f"candidate[{index}].upstream_artifact",
        )
        unknown_for_retro = bool(item.get("unknown_for_retro", False))
        if not upstream_artifact and not unknown_for_retro:
            raise EvidenceBridgeError(
                f"candidate[{index}] requires upstream_artifact or unknown_for_retro"
            )
        raw_ids = item.get("evidence_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise EvidenceBridgeError(f"candidate[{index}].evidence_ids must be a non-empty list")
        normalized_ids = [
            _required_string(value, f"candidate[{index}].evidence_ids[{id_index}]")
            for id_index, value in enumerate(raw_ids)
        ]
        missing_ids = [value for value in normalized_ids if value not in evidence_ids]
        if missing_ids:
            raise EvidenceBridgeError(
                f"candidate[{index}].evidence_ids reference unknown evidence: {missing_ids}"
            )
        candidate: dict[str, Any] = {
            "id": candidate_id,
            "route": route,
            "summary": _required_string(item.get("summary"), f"candidate[{index}].summary"),
            "evidence_ids": normalized_ids,
            "source_refs": source_refs,
            "recommendation": _required_string(
                item.get("recommendation"),
                f"candidate[{index}].recommendation",
            ),
            "unknown_for_retro": unknown_for_retro,
        }
        if upstream_artifact:
            candidate["upstream_artifact"] = upstream_artifact
        candidates.append(candidate)
    return candidates


def _validated_source_refs(value: Any, field: str) -> list[dict[str, Any]]:
    try:
        validate_source_refs(value, field)
    except BuilderOpsValidationError as exc:
        raise EvidenceBridgeError(str(exc)) from exc
    if not isinstance(value, list):  # validate_source_refs guards this.
        raise EvidenceBridgeError(f"{field} must be a non-empty list")
    return list(value)


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceBridgeError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field)


def _receipt_body(
    observed: list[dict[str, Any]],
    unknown: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> str:
    routes = ", ".join(
        f"{item['id']}={item['route']}"
        for item in candidates
    )
    return (
        "Evidence bridge observe-only report: "
        f"observed={len(observed)}, unknown={len(unknown)}, "
        f"candidate={len(candidates)}"
        + (f"; routes: {routes}." if routes else ".")
    )


__all__ = [
    "EVIDENCE_BRIDGE_ROUTES",
    "EvidenceBridgeError",
    "OBSERVED_EVIDENCE_KINDS",
    "UNKNOWN_EVIDENCE_KINDS",
    "build_evidence_bridge_report",
]
