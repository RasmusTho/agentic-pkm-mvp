#!/usr/bin/env python3
"""Generate PR bodies that satisfy the repo lane contract."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


LANES = frozenset({"implementation", "docs-authoring", "governance", "direct-repair"})
DIRECT_REPAIR_TYPES = frozenset({"docs", "governance", "code"})
OWNER_DOC_RESOLUTIONS = frozenset({"none", "updated", "follow-up"})

TEMPLATE_SECTION_HEADINGS = (
    "Change Lane",
    "Linked Issue",
    "SBS Impact",
    "Owner-Doc Writeback",
    "Summary",
    "Implementation Scope Check",
    "Docs Authoring Check",
    "Governance Lane Check",
    "Validation",
    "BuilderOps Routing",
    "Notes",
)

SBS_FIELDS = (
    ("primary_subsystem", "Primary subsystem"),
    ("secondary_subsystems", "Secondary subsystem(s)"),
    ("write_class", "Write class"),
    ("authority_impact", "Authority impact"),
    ("persistence_impact", "Persistence impact"),
    ("derived_rebuildable_impact", "Derived/rebuildable impact"),
    ("human_knowledge_impact", "Human knowledge impact"),
    ("memory_impact", "Memory impact"),
    ("retrieval_context_impact", "Retrieval/context impact"),
    ("sync_deployment_impact", "Sync/deployment impact"),
    ("external_boundary_impact", "External boundary impact"),
    ("new_or_changed_contract", "New or changed contract"),
    ("owner_doc_impact", "Owner-doc impact"),
    ("transition_debt_impact", "Transition debt impact"),
    ("fitness_rule_impact", "Fitness rule impact"),
    ("boundary_risk", "Boundary risk"),
)


class PRBodyGeneratorError(ValueError):
    """Raised when required PR body inputs are missing or invalid."""


@dataclass(frozen=True)
class PRBodyInputs:
    lane: str
    summary: tuple[str, ...]
    sbs_impact: Mapping[str, str]
    owner_doc_resolution: str
    validation: tuple[str, ...]
    final_review_rounds: int = 1
    issue_number: int | None = None
    builderops_records: str | None = None
    builderops_reason: str | None = None
    notes: str = "None."
    direct_repair_type: str | None = None
    direct_repair_reason: str | None = None
    direct_repair_validation: str | None = None
    owner_doc_followup_issue: str | None = None


def generate_pr_body(inputs: PRBodyInputs) -> str:
    """Return a complete PR body for the requested lane."""

    _validate_inputs(inputs)
    sections: list[str] = []
    if inputs.lane == "direct-repair":
        sections.append(_direct_repair_section(inputs))
    sections.extend([
        _change_lane_section(inputs.lane, inputs.final_review_rounds),
        _linked_issue_section(inputs.issue_number),
        _sbs_impact_section(inputs.sbs_impact),
        _owner_doc_section(inputs),
        _summary_section(inputs.summary),
        _implementation_scope_section(inputs),
        _docs_authoring_section(inputs.lane),
        _governance_lane_section(inputs.lane),
        _validation_section(inputs),
        _builderops_section(inputs),
        f"## Notes\n{inputs.notes.strip()}",
    ])
    return "\n\n".join(sections).rstrip() + "\n"


def generate_pr_body_from_mapping(data: Mapping[str, Any]) -> str:
    return generate_pr_body(_inputs_from_mapping(data))


def _inputs_from_mapping(data: Mapping[str, Any]) -> PRBodyInputs:
    summary = data.get("summary", ())
    validation = data.get("validation", ())
    if isinstance(summary, str):
        summary = [summary]
    if isinstance(validation, str):
        validation = [validation]
    issue_number = data.get("issue_number")
    if issue_number is not None:
        issue_number = int(issue_number)
    return PRBodyInputs(
        lane=str(data.get("lane", "")),
        issue_number=issue_number,
        summary=tuple(str(item) for item in summary),
        sbs_impact=_string_mapping(data.get("sbs_impact", {}), "sbs_impact"),
        owner_doc_resolution=str(data.get("owner_doc_resolution", "")),
        owner_doc_followup_issue=_optional_text(data.get("owner_doc_followup_issue")),
        validation=tuple(str(item) for item in validation),
        final_review_rounds=int(data.get("final_review_rounds", 1)),
        builderops_records=_optional_text(data.get("builderops_records")),
        builderops_reason=_optional_text(data.get("builderops_reason")),
        notes=str(data.get("notes", "None.")),
        direct_repair_type=_optional_text(data.get("direct_repair_type")),
        direct_repair_reason=_optional_text(data.get("direct_repair_reason")),
        direct_repair_validation=_optional_text(data.get("direct_repair_validation")),
    )


def _validate_inputs(inputs: PRBodyInputs) -> None:
    if inputs.lane not in LANES:
        raise PRBodyGeneratorError(f"lane must be one of: {', '.join(sorted(LANES))}")
    if inputs.issue_number is not None and inputs.issue_number <= 0:
        raise PRBodyGeneratorError("issue_number must be positive")
    if inputs.final_review_rounds not in {1, 2}:
        raise PRBodyGeneratorError("final_review_rounds must be 1 or 2")
    if inputs.lane == "implementation" and inputs.issue_number is None:
        raise PRBodyGeneratorError("implementation lane requires issue_number")
    if inputs.lane == "direct-repair":
        if inputs.issue_number is not None:
            raise PRBodyGeneratorError("direct-repair lane must not set issue_number")
        if inputs.direct_repair_type not in DIRECT_REPAIR_TYPES:
            raise PRBodyGeneratorError("direct-repair lane requires direct_repair_type")
        _require_text(inputs.direct_repair_reason, "direct_repair_reason")
        _require_text(inputs.direct_repair_validation, "direct_repair_validation")
    if not inputs.summary or any(not item.strip() for item in inputs.summary):
        raise PRBodyGeneratorError("summary must contain at least one non-empty item")
    if not inputs.validation or any(not item.strip() for item in inputs.validation):
        raise PRBodyGeneratorError("validation must contain at least one non-empty item")
    if inputs.owner_doc_resolution not in OWNER_DOC_RESOLUTIONS:
        raise PRBodyGeneratorError(
            "owner_doc_resolution must be one of: none, updated, follow-up"
        )
    if inputs.owner_doc_resolution == "follow-up":
        _require_text(inputs.owner_doc_followup_issue, "owner_doc_followup_issue")
    missing_sbs = [
        key for key, _label in SBS_FIELDS
        if _is_missing_value(inputs.sbs_impact.get(key))
    ]
    if missing_sbs:
        raise PRBodyGeneratorError("missing SBS impact fields: " + ", ".join(missing_sbs))
    if inputs.issue_number is not None or inputs.lane == "direct-repair":
        _require_text(inputs.builderops_records, "builderops_records")
        _require_text(inputs.builderops_reason, "builderops_reason")


def _change_lane_section(lane: str, final_review_rounds: int) -> str:
    return "\n".join([
        "## Change Lane",
        f"- [{'x' if lane == 'implementation' else ' '}] Implementation lane",
        f"- [{'x' if lane == 'docs-authoring' else ' '}] Docs authoring lane",
        f"- [{'x' if lane == 'governance' else ' '}] Governance lane",
        "",
        f"Final-Review-Rounds: {final_review_rounds}",
    ])


def _linked_issue_section(issue_number: int | None) -> str:
    if issue_number is None:
        return "## Linked Issue\n"
    return (
        f"Governing-Issue: #{issue_number}\n\n"
        f"## Linked Issue\nCloses #{issue_number}"
    )


def _sbs_impact_section(values: Mapping[str, str]) -> str:
    lines = ["## SBS Impact"]
    lines.extend(f"- {label}: {values[key].strip()}" for key, label in SBS_FIELDS)
    return "\n".join(lines)


def _owner_doc_section(inputs: PRBodyInputs) -> str:
    labels = {
        "none": "No owner-doc change implied.",
        "updated": "Owner-doc updated in this PR.",
        "follow-up": "Owner-doc follow-up issue created and linked.",
    }
    lines = ["## Owner-Doc Writeback"]
    for key in ("none", "updated", "follow-up"):
        suffix = ""
        if key == "follow-up" and inputs.owner_doc_resolution == "follow-up":
            suffix = f" ({inputs.owner_doc_followup_issue})"
        lines.append(
            f"- [{'x' if inputs.owner_doc_resolution == key else ' '}] {labels[key]}{suffix}"
        )
    return "\n".join(lines)


def _summary_section(summary: Sequence[str]) -> str:
    return "\n".join(["## Summary", *[f"- {item.strip()}" for item in summary]])


def _implementation_scope_section(inputs: PRBodyInputs) -> str:
    checked = inputs.issue_number is not None
    return "\n".join([
        "## Implementation Scope Check",
        f"- [{'x' if checked else ' '}] Change stays within the linked Issue scope.",
        f"- [{'x' if checked else ' '}] Constraints from the linked Issue were followed.",
        f"- [{'x' if checked else ' '}] Acceptance Criteria from the linked Issue are satisfied.",
        f"- [{'x' if checked else ' '}] Docs were updated in the same change when behavior/contracts changed.",
        f"- [{'x' if checked else ' '}] Owner docs and roadmap/plan wording were updated when this PR turns a tracked backlog item into shipped reality.",
    ])


def _docs_authoring_section(lane: str) -> str:
    checked = lane == "docs-authoring"
    return "\n".join([
        "## Docs Authoring Check",
        f"- [{'x' if checked else ' '}] This PR only changes approved docs-authoring surfaces.",
        f"- [{'x' if checked else ' '}] No code, runtime behavior, contracts, or shipped reality changed.",
        f"- [{'x' if checked else ' '}] This PR prepares or clarifies authoritative docs/specification and may later feed `docs-to-issue` extraction.",
    ])


def _governance_lane_section(lane: str) -> str:
    checked = lane == "governance"
    return "\n".join([
        "## Governance Lane Check",
        f"- [{'x' if checked else ' '}] This PR only changes approved governance surfaces.",
        f"- [{'x' if checked else ' '}] The change is limited to repo governance, agent workflow, or lightweight enforcement.",
        f"- [{'x' if checked else ' '}] No product/runtime implementation or shipped feature behavior changed.",
    ])


def _validation_section(inputs: PRBodyInputs) -> str:
    lane_labels = {
        "implementation": "Implementation lane",
        "docs-authoring": "Docs authoring lane",
        "governance": "Governance lane",
        "direct-repair": "Direct repair",
    }
    lines = ["## Validation", f"{lane_labels[inputs.lane]}:"]
    lines.extend(f"- [x] {item.strip()}" for item in inputs.validation)
    return "\n".join(lines)


def _builderops_section(inputs: PRBodyInputs) -> str:
    records = inputs.builderops_records or "none"
    reason = inputs.builderops_reason or "Tier 1 lane with no BuilderOps material routed."
    return "\n".join([
        "## BuilderOps Routing",
        f"- Records/projections/receipts: {records.strip()}",
        f"- Reason: {reason.strip()}",
    ])


def _direct_repair_section(inputs: PRBodyInputs) -> str:
    return "\n".join([
        "## Direct Repair",
        f"Type: {inputs.direct_repair_type}",
        f"Reason: {inputs.direct_repair_reason}",
        f"Validation: {inputs.direct_repair_validation}",
        "Issue required: no",
    ])


def _string_mapping(value: Any, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise PRBodyGeneratorError(f"{field} must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _require_text(value: str | None, field: str) -> None:
    if _is_missing_value(value):
        raise PRBodyGeneratorError(f"{field} is required")


def _is_missing_value(value: str | None) -> bool:
    if value is None:
        return True
    text = value.strip()
    if not text:
        return True
    return text.lower() in {"tbd", "todo", "n/a"} or (text.startswith("<") and text.endswith(">"))


def _parse_sbs(values: Sequence[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise PRBodyGeneratorError("--sbs values must use key=value")
        key, value = item.split("=", 1)
        parsed[key.strip().replace("-", "_")] = value.strip()
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, help="JSON object with PR body inputs.")
    parser.add_argument("--lane", choices=sorted(LANES))
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--summary", action="append", default=[])
    parser.add_argument("--sbs", action="append", default=[], help="SBS field as key=value.")
    parser.add_argument("--owner-doc-resolution", choices=sorted(OWNER_DOC_RESOLUTIONS))
    parser.add_argument("--owner-doc-followup-issue")
    parser.add_argument("--validation", action="append", default=[])
    parser.add_argument("--final-review-rounds", type=int, choices=(1, 2), default=1)
    parser.add_argument("--builderops-records")
    parser.add_argument("--builderops-reason")
    parser.add_argument("--notes", default="None.")
    parser.add_argument("--direct-repair-type", choices=sorted(DIRECT_REPAIR_TYPES))
    parser.add_argument("--direct-repair-reason")
    parser.add_argument("--direct-repair-validation")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.input_json:
            body = generate_pr_body_from_mapping(
                json.loads(args.input_json.read_text(encoding="utf-8"))
            )
        else:
            body = generate_pr_body(PRBodyInputs(
                lane=args.lane or "",
                issue_number=args.issue_number,
                summary=tuple(args.summary),
                sbs_impact=_parse_sbs(args.sbs),
                owner_doc_resolution=args.owner_doc_resolution or "",
                owner_doc_followup_issue=args.owner_doc_followup_issue,
                validation=tuple(args.validation),
                final_review_rounds=args.final_review_rounds,
                builderops_records=args.builderops_records,
                builderops_reason=args.builderops_reason,
                notes=args.notes,
                direct_repair_type=args.direct_repair_type,
                direct_repair_reason=args.direct_repair_reason,
                direct_repair_validation=args.direct_repair_validation,
            ))
    except (OSError, json.JSONDecodeError, PRBodyGeneratorError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
