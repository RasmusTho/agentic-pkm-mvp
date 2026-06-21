"""Conformance checks for retrieval-emitted ContextBundles (#2359)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.retrieval.bundle_emission import RetrievalBundleResult

_ENGINE_LOCAL_FIELDS = frozenset(
    {
        "doc_id",
        "payload",
        "score",
        "snippet",
        "source_ref",
        "text",
    }
)


class RetrievalContextBundleConformanceError(ValueError):
    """Raised when a retrieval output does not meet the ContextBundle contract."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        detail = "; ".join(self.errors)
        super().__init__(f"retrieval ContextBundle conformance failed: {detail}")


def validate_retrieval_context_bundle(result: RetrievalBundleResult) -> list[str]:
    """Return conformance errors for a retrieval-emitted ContextBundle.

    The check is intentionally narrow: it verifies the production retrieval
    output path emits candidate evidence with the required ContextBundle fields,
    keeps non-authority posture, and leaves raw retrieval-engine fields out of
    the bundle envelope.
    """
    bundle = result.bundle
    errors: list[str] = []

    if not bundle.id:
        errors.append("id is required")
    if bundle.created_at.tzinfo is None:
        errors.append("created_at must be timezone-aware")
    if bundle.trigger.type != "retrieval":
        errors.append("trigger.type must be retrieval")
    if not bundle.intended_use:
        errors.append("intended_use is required")
    if bundle.scope is None:
        errors.append("scope is required")
    if bundle.authority.may_write is not False:
        errors.append("authority.may_write must remain false")
    if not bundle.expiry.reason:
        errors.append("expiry.reason must state freshness or uncertainty posture")
    if bundle.receipts is None:
        errors.append("receipts field is required")

    for index, item in enumerate(bundle.included):
        prefix = f"included[{index}]"
        if not item.artifact_id:
            errors.append(f"{prefix}.artifact_id is required")
        if not item.reason:
            errors.append(f"{prefix}.reason is required")
        if item.retrieval_score is None:
            errors.append(f"{prefix}.retrieval_score is required")
        if item.provenance is None or not item.provenance.origin:
            errors.append(f"{prefix}.provenance.origin is required")

    for index, item in enumerate(bundle.excluded):
        prefix = f"excluded[{index}]"
        if not item.artifact_id:
            errors.append(f"{prefix}.artifact_id is required")
        if not item.reason:
            errors.append(f"{prefix}.reason is required")

    leaked_fields = _engine_local_fields_in_bundle(bundle.model_dump(mode="json"))
    if leaked_fields:
        leaked = ", ".join(sorted(leaked_fields))
        errors.append(
            "engine-specific retrieval fields must remain diagnostics-only or "
            f"adapter-local: {leaked}"
        )

    return errors


def assert_retrieval_context_bundle_conformant(
    result: RetrievalBundleResult,
) -> RetrievalBundleResult:
    """Raise if ``result`` violates the retrieval ContextBundle contract."""
    errors = validate_retrieval_context_bundle(result)
    if errors:
        raise RetrievalContextBundleConformanceError(errors)
    return result


def _engine_local_fields_in_bundle(value: Any) -> set[str]:
    if isinstance(value, dict):
        fields = set(value) & _ENGINE_LOCAL_FIELDS
        for child in value.values():
            fields.update(_engine_local_fields_in_bundle(child))
        return fields
    if isinstance(value, list):
        fields: set[str] = set()
        for child in value:
            fields.update(_engine_local_fields_in_bundle(child))
        return fields
    return set()


__all__ = [
    "RetrievalContextBundleConformanceError",
    "assert_retrieval_context_bundle_conformant",
    "validate_retrieval_context_bundle",
]
