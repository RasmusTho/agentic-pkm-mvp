"""Generated Markdown projections over BuilderOps Vault records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.builderops.models import BuilderOpsValidationError, utc_now
from app.builderops.store import SqliteBuilderOpsStore


@dataclass(frozen=True)
class BuilderOpsProjectionSpec:
    projection_type: str
    filename: str
    title: str
    object_type: str
    description: str
    field_labels: tuple[tuple[str, str], ...]


PROJECTION_SPECS: dict[str, BuilderOpsProjectionSpec] = {
    "learning-summary": BuilderOpsProjectionSpec(
        projection_type="learning-summary",
        filename="learning-summary.md",
        title="BuilderOps Learning Summary Projection",
        object_type="LearningSignal",
        description="LearningSignal records grouped into a repo-readable summary view.",
        field_labels=(
            ("Signal type", "signal_type"),
            ("Content", "content"),
        ),
    ),
    "docs-freshness": BuilderOpsProjectionSpec(
        projection_type="docs-freshness",
        filename="docs-freshness.md",
        title="BuilderOps Docs Freshness Projection",
        object_type="DocsFreshnessRecord",
        description="DocsFreshnessRecord records that describe high-churn documentation freshness state.",
        field_labels=(
            ("Doc ref", "doc_ref"),
            ("Owner", "owner"),
            ("Review cadence", "review_cadence"),
            ("Freshness posture", "freshness_posture"),
            ("Drift status", "drift_status"),
            ("Last reviewed at", "last_reviewed_at"),
            ("Last verified against", "last_verified_against"),
            ("Last verified at", "last_verified_at"),
            ("Next review due at", "next_review_due_at"),
            ("Stale reasons", "stale_reasons"),
            ("Freshness evidence refs", "freshness_evidence_refs"),
            ("Next review owner", "next_review_owner"),
        ),
    ),
    "roadmap-execution": BuilderOpsProjectionSpec(
        projection_type="roadmap-execution",
        filename="roadmap-execution.md",
        title="BuilderOps Roadmap Execution Projection",
        object_type="RoadmapExecutionItem",
        description="RoadmapExecutionItem records that describe operational roadmap execution state.",
        field_labels=(
            ("Roadmap ref", "roadmap_ref"),
            ("Theme", "theme"),
            ("Capability", "capability"),
            ("Execution state", "execution_state"),
            ("Status", "status"),
            ("Owner", "owner"),
            ("Active issues", "active_issues"),
            ("Blockers", "blockers"),
            ("Last movement", "last_movement"),
            ("Next decision", "next_decision"),
            ("Shipped refs", "shipped_refs"),
        ),
    ),
    "promotion-queue": BuilderOpsProjectionSpec(
        projection_type="promotion-queue",
        filename="promotion-queue.md",
        title="BuilderOps Promotion Queue Projection",
        object_type="PromotionIntent",
        description="PromotionIntent records queued for explicit authority-boundary review.",
        field_labels=(
            ("Target authority surface", "target_authority_surface"),
            ("Target action", "target_action"),
            ("Target ref", "target_ref"),
            ("Target authority class", "target_authority_class"),
            ("Intended output", "intended_output"),
        ),
    ),
}


class BuilderOpsProjectionGenerator:
    """Render non-authoritative Markdown projections from a BuilderOps store."""

    def __init__(self, store: SqliteBuilderOpsStore) -> None:
        self._store = store
        self._store.initialize()

    def render_projection(
        self,
        projection_type: str,
        *,
        generated_at: str | None = None,
    ) -> str:
        spec = _projection_spec(projection_type)
        timestamp = generated_at or utc_now()
        records = sorted(
            self._store.list_records(spec.object_type),
            key=lambda record: (
                str(record.get("created_at", "")),
                str(record.get("id", "")),
            ),
        )
        return _render_projection(spec, records, timestamp)

    def write_projections(
        self,
        output_dir: Path,
        *,
        projection_types: Iterable[str] | None = None,
        generated_at: str | None = None,
    ) -> list[dict[str, Any]]:
        selected = _selected_specs(projection_types)
        timestamp = generated_at or utc_now()
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for spec in selected:
            markdown = self.render_projection(
                spec.projection_type,
                generated_at=timestamp,
            )
            record_count = len(self._store.list_records(spec.object_type))
            path = output_dir / spec.filename
            path.write_text(markdown, encoding="utf-8")
            results.append({
                "projection_type": spec.projection_type,
                "object_type": spec.object_type,
                "path": str(path),
                "record_count": record_count,
                "generated_at": timestamp,
            })
        return results


def _projection_spec(projection_type: str) -> BuilderOpsProjectionSpec:
    normalized = projection_type.strip().lower().replace("_", "-")
    spec = PROJECTION_SPECS.get(normalized)
    if spec is None:
        allowed = ", ".join(sorted(PROJECTION_SPECS))
        raise BuilderOpsValidationError(
            f"unsupported BuilderOps projection type: {projection_type}; allowed: {allowed}"
        )
    return spec


def _selected_specs(
    projection_types: Iterable[str] | None,
) -> list[BuilderOpsProjectionSpec]:
    if projection_types is None:
        return [PROJECTION_SPECS[key] for key in sorted(PROJECTION_SPECS)]
    selected = [_projection_spec(projection_type) for projection_type in projection_types]
    if not selected:
        return [PROJECTION_SPECS[key] for key in sorted(PROJECTION_SPECS)]
    return selected


def _render_projection(
    spec: BuilderOpsProjectionSpec,
    records: list[dict[str, Any]],
    generated_at: str,
) -> str:
    lines = [
        "State: Generated projection",
        "Authority: non-authoritative BuilderOps Vault projection",
        "Source of truth: BuilderOps Vault",
        f"Generated at: {generated_at}",
        f"Projection type: {spec.projection_type}",
        "Do not edit: regenerate from BuilderOps Vault records.",
        "",
        f"# {spec.title}",
        "",
        spec.description,
        "",
        "Generated projection over BuilderOps Vault records. This Markdown view is non-authoritative and does not replace BuilderOps Vault operational state.",
        "",
        f"Record count: {len(records)}",
        "",
        "## Records",
        "",
    ]
    if not records:
        lines.append("No BuilderOps records matched this projection.")
        lines.append("")
        return "\n".join(lines)

    for record in records:
        lines.extend(_render_record(record, spec))
    return "\n".join(lines)


def _render_record(
    record: Mapping[str, Any],
    spec: BuilderOpsProjectionSpec,
) -> list[str]:
    lines = [
        f"### {record['id']} - {_single_line(record['summary'])}",
        "",
        f"- Object type: {record['object_type']}",
        f"- Lifecycle state: {record['lifecycle_state']}",
        f"- Promotion status: {record['promotion_status']}",
        f"- Authority class: {record['authority_class']}",
        f"- Created at: {record['created_at']}",
        f"- Updated at: {record['updated_at']}",
    ]
    for label, field in spec.field_labels:
        if field in record:
            lines.append(f"- {label}: {_format_value(record[field])}")
    lines.append("- Source refs:")
    lines.extend(f"  - {line}" for line in _format_refs(record.get("source_refs", [])))
    receipt_refs = record.get("receipt_refs") or []
    if receipt_refs:
        lines.append("- Receipt refs:")
        lines.extend(f"  - `{receipt_ref}`" for receipt_ref in receipt_refs)
    else:
        lines.append("- Receipt refs: none")
    lines.append("")
    return lines


def _format_refs(refs: Any) -> list[str]:
    if not isinstance(refs, list) or not refs:
        return ["none"]
    return [_format_ref(ref) for ref in refs]


def _format_ref(ref: Any) -> str:
    if not isinstance(ref, Mapping):
        return _format_value(ref)
    ref_type = ref.get("ref_type", "unknown")
    ref_value = ref.get("ref", "unknown")
    extras = []
    for key in ("title", "authority_surface", "locator", "url", "observed_at"):
        value = ref.get(key)
        if value:
            extras.append(f"{key}={_single_line(str(value))}")
    suffix = f" ({'; '.join(extras)})" if extras else ""
    return f"{ref_type}:{ref_value}{suffix}"


def _format_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return _format_ref(value) if {"ref_type", "ref"} <= set(value) else _json(value)
    if isinstance(value, list):
        if not value:
            return "none"
        return ", ".join(_format_value(item) for item in value)
    return _single_line(str(value))


def _single_line(value: str) -> str:
    return " ".join(value.split())


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "BuilderOpsProjectionGenerator",
    "BuilderOpsProjectionSpec",
    "PROJECTION_SPECS",
]
