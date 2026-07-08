#!/usr/bin/env python3
"""
Classify GitHub Issue readiness without mutating labels, Project state, or comments.

Usage:
  python3 scripts/validate_issue_readiness.py --body-file issue.md
  BODY="issue body" python3 scripts/validate_issue_readiness.py --observe-only
  python3 scripts/validate_issue_readiness.py --issue-number 123 --label agent:ready < issue.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


REQUIRED_SECTIONS: tuple[str, ...] = (
    "Context",
    "Scope",
    "Source Anchors",
    "SBS Impact",
    "Constraints",
    "Acceptance Criteria",
    "Out of Scope",
    "Suggested Validation",
    "Source Docs",
)

READINESS_CLASSES: tuple[str, ...] = (
    "ready_candidate",
    "missing_required_sections",
    "missing_source_docs",
    "missing_verify_markers",
    "malformed_acceptance_criteria",
    "ambiguous_intent",
    "authority_risk",
    "not_agentable",
    "unknown",
)

AMBIGUOUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bTBD\b",
        r"\bTODO\b",
        r"\bunclear\b",
        r"\bnot sure\b",
        r"\bfigure out\b",
        r"\binvestigate\b",
        r"\bmaybe\b",
        r"\betc\.\b",
    )
)

AUTHORITY_RISK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bhuman (?:must|needs to|should) decide\b",
        r"(?<!would )\b(?:requires?|needs|blocked by|waiting for)\s+(?:an?\s+)?owner decision\b",
        r"(?<!would )\b(?:requires?|needs|blocked by|waiting for)\s+(?:an?\s+)?strategic decision\b",
        r"(?<!would )\b(?:requires?|needs|blocked by|waiting for)\s+(?:an?\s+)?authority question\b",
        r"\b(?:may|must|will|should|automatically)\s+change Project status\b",
        r"\b(?:automatically label|automatically add labels?)\b",
        r"\b(?:may|must|will|should|automatically)\s+(?:change|relax|disable|bypass)\s+branch protection\b",
        r"\b(?:may|must|will|should|automatically)\s+(?:enable|turn on|use)\s+auto-?merge\b",
        r"\b(?:may|must|will|should|automatically)\s+(?:touch|change|deploy|promote|write)\s+prod(?:uction)?\b",
        r"\b(?:perform|run|execute|requires?|includes?)\s+stable promotion\b",
        r"\b(?:perform|run|execute|requires?|includes?)\s+irreversible migration\b",
    )
)

NOT_AGENTABLE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnot agentable\b",
        r"\bhuman only\b",
        r"\bmanual only\b",
        r"\bdo not pick up\b",
        r"\bblocked until\b",
        r"\boperator gated\b",
    )
)


@dataclass(frozen=True)
class AcceptanceCriteriaReport:
    present: bool
    count: int
    malformed: bool
    verify_markers_present: bool
    missing_verify_items: list[str]


@dataclass(frozen=True)
class SectionReport:
    present: list[str]
    missing: list[str]


@dataclass(frozen=True)
class IssueReadinessReport:
    issue_number: int | None
    labels: list[str]
    required_sections: SectionReport
    source_docs_present: bool
    source_docs_missing: bool
    acceptance_criteria: AcceptanceCriteriaReport
    verify_markers_present: bool
    verify_markers_missing: bool
    readiness_classification: str
    repair_guidance: list[str]
    human_exception_required: bool


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    heading_pattern = re.compile(r"^#{2,6}\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading_pattern.finditer(body))
    for index, match in enumerate(matches):
        title = re.sub(r"\s+\(optional\)\s*$", "", match.group(1).strip(), flags=re.I)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[_normalize_heading(title)] = body[start:end].strip()
    return sections


def _section_content(sections: dict[str, str], name: str) -> str | None:
    return sections.get(_normalize_heading(name))


def _non_placeholder_lines(section: str | None) -> list[str]:
    if section is None:
        return []
    lines = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line in {"-", "- [ ]"}:
            continue
        content = re.sub(r"^[-*]\s+(?:\[[ xX]\]\s+)?", "", line).strip()
        if re.fullmatch(r"<.*>", content):
            continue
        if re.fullmatch(r"<?(?:none|n/a|todo|tbd|blank|leave blank)>?", content, re.I):
            continue
        lines.append(line)
    return lines


def _extract_acceptance_items(section: str | None) -> list[str]:
    if section is None:
        return []
    item_starts = list(re.finditer(r"(?m)^\s*[-*]\s+\[[ xX]\]\s+.+$", section))
    items = []
    for index, match in enumerate(item_starts):
        start = match.start()
        end = item_starts[index + 1].start() if index + 1 < len(item_starts) else len(section)
        items.append(section[start:end].strip())
    return items


def _summarize_item(item: str) -> str:
    first_line = item.splitlines()[0].strip()
    return re.sub(r"\s+", " ", first_line)


def _has_concrete_verify_marker(item: str) -> bool:
    for match in re.finditer(r"(?im)(?:^|\b)Verify:\s*(.+)$", item):
        target = match.group(1).strip().strip("`").strip()
        if not target:
            continue
        if re.fullmatch(r"<.*>", target):
            continue
        if re.fullmatch(
            r"(?:none|n/a|na|tbd|todo|test pointer|doc anchor|verification target|runtime receipt)",
            target,
            re.IGNORECASE,
        ):
            continue
        return True
    return False


def analyze_acceptance_criteria(section: str | None) -> AcceptanceCriteriaReport:
    lines = _non_placeholder_lines(section)
    items = _extract_acceptance_items(section)
    malformed = bool(lines) and not items
    missing_verify = [
        _summarize_item(item)
        for item in items
        if not _has_concrete_verify_marker(item)
    ]
    return AcceptanceCriteriaReport(
        present=bool(items),
        count=len(items),
        malformed=malformed,
        verify_markers_present=bool(items) and not missing_verify,
        missing_verify_items=missing_verify,
    )


def _contains_any(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _unknown_body(body: str, present: Sequence[str]) -> bool:
    stripped = body.strip()
    if not stripped:
        return True
    if len(present) <= 1 and not re.search(r"^#{2,6}\s+", stripped, re.MULTILINE):
        return True
    if len(present) <= 2 and not any(
        _normalize_heading(section) in present for section in ("Context", "Scope")
    ):
        return True
    return False


def classify_issue_body(
    body: str,
    *,
    issue_number: int | None = None,
    labels: Sequence[str] = (),
) -> IssueReadinessReport:
    sections = extract_sections(body)
    present = [section for section in REQUIRED_SECTIONS if _section_content(sections, section) is not None]
    missing = [section for section in REQUIRED_SECTIONS if section not in present]
    present_normalized = [_normalize_heading(section) for section in present]

    source_docs_lines = _non_placeholder_lines(_section_content(sections, "Source Docs"))
    source_docs_present = bool(source_docs_lines)
    ac_report = analyze_acceptance_criteria(_section_content(sections, "Acceptance Criteria"))
    label_names = sorted(dict.fromkeys(labels))

    classification = "ready_candidate"
    human_exception_required = False

    if _unknown_body(body, present_normalized):
        classification = "unknown"
        human_exception_required = True
    elif "agent:needs-human" in label_names or "agent:blocked" in label_names:
        classification = "not_agentable"
        human_exception_required = True
    elif _contains_any(NOT_AGENTABLE_PATTERNS, body):
        classification = "not_agentable"
        human_exception_required = True
    elif "Source Docs" in missing or not source_docs_present:
        classification = "missing_source_docs"
    elif missing:
        classification = "missing_required_sections"
    elif not ac_report.present or ac_report.malformed:
        classification = "malformed_acceptance_criteria"
    elif not ac_report.verify_markers_present:
        classification = "missing_verify_markers"
    elif _contains_any(AUTHORITY_RISK_PATTERNS, body):
        classification = "authority_risk"
        human_exception_required = True
    elif _contains_any(AMBIGUOUS_PATTERNS, body):
        classification = "ambiguous_intent"
        human_exception_required = True

    guidance = repair_guidance(
        classification=classification,
        missing_sections=missing,
        source_docs_present=source_docs_present,
        ac_report=ac_report,
    )

    return IssueReadinessReport(
        issue_number=issue_number,
        labels=label_names,
        required_sections=SectionReport(present=present, missing=missing),
        source_docs_present=source_docs_present,
        source_docs_missing=not source_docs_present,
        acceptance_criteria=ac_report,
        verify_markers_present=ac_report.verify_markers_present,
        verify_markers_missing=not ac_report.verify_markers_present,
        readiness_classification=classification,
        repair_guidance=guidance,
        human_exception_required=human_exception_required,
    )


def repair_guidance(
    *,
    classification: str,
    missing_sections: Sequence[str],
    source_docs_present: bool,
    ac_report: AcceptanceCriteriaReport,
) -> list[str]:
    if classification == "ready_candidate":
        return ["No repair required before observe-only readiness consideration."]
    if classification == "unknown":
        return [
            "Rewrite the issue with the canonical task template before readiness evaluation.",
            "Include Context, Scope, Source Anchors, SBS Impact, Constraints, Acceptance Criteria, Out of Scope, Suggested Validation, and Source Docs.",
        ]
    if classification == "not_agentable":
        return [
            "Keep the issue out of the agent-ready queue until the blocker or human-only condition is resolved.",
            "Use agent:blocked or agent:needs-human truthfully; do not add agent:ready.",
        ]
    if classification == "authority_risk":
        return [
            "Resolve the named authority question before agent execution.",
            "Split irreversible, Project/label mutation, branch-protection, auto-merge, prod, or strategic-decision work behind an explicit human decision.",
        ]
    if classification == "ambiguous_intent":
        return [
            "Replace vague intent with bounded file/artifact scope and concrete acceptance criteria.",
            "Remove TBD/TODO/maybe/investigate wording or move it to a separate discovery issue.",
        ]
    if classification == "missing_source_docs":
        return [
            "Add a non-empty `## Source Docs` section listing the governing repo documents.",
            "Use stable paths such as `docs/<path>.md` or shared contract files; do not rely on local-only context.",
        ]
    if classification == "missing_required_sections":
        return [
            "Add missing required section(s): " + ", ".join(missing_sections) + ".",
            "Use the canonical task template in `.github/ISSUE_TEMPLATE/task.yml`.",
        ]
    if classification == "malformed_acceptance_criteria":
        return [
            "Rewrite `## Acceptance Criteria` as checkbox bullets (`- [ ] ...`).",
            "Give every acceptance criterion an inline `Verify:` marker naming a test, doc anchor, roadmap diff, or runtime receipt.",
        ]
    if classification == "missing_verify_markers":
        missing_items = "; ".join(ac_report.missing_verify_items)
        return [
            "Add an inline `Verify:` marker to every acceptance criterion.",
            "Missing Verify marker on: " + missing_items + ".",
        ]
    return ["Unable to determine repair guidance; rewrite using the canonical task template."]


def render_markdown(report: IssueReadinessReport) -> str:
    issue = f"#{report.issue_number}" if report.issue_number is not None else "unknown"
    labels = ", ".join(report.labels) if report.labels else "none"
    missing = ", ".join(report.required_sections.missing) or "none"
    present = ", ".join(report.required_sections.present) or "none"
    guidance = "\n".join(f"- {item}" for item in report.repair_guidance)
    missing_verify = (
        "\n".join(f"- {item}" for item in report.acceptance_criteria.missing_verify_items)
        or "- none"
    )
    return "\n".join(
        [
            "# Issue Readiness Report",
            "",
            f"- Issue: {issue}",
            f"- Labels: {labels}",
            f"- Classification: `{report.readiness_classification}`",
            f"- Human Exception required: `{str(report.human_exception_required).lower()}`",
            f"- Source Docs present: `{str(report.source_docs_present).lower()}`",
            f"- Acceptance Criteria present: `{str(report.acceptance_criteria.present).lower()}`",
            f"- Verify markers present: `{str(report.verify_markers_present).lower()}`",
            f"- Required sections present: {present}",
            f"- Required sections missing: {missing}",
            "",
            "## Missing Verify Items",
            missing_verify,
            "",
            "## Repair Guidance",
            guidance,
            "",
        ]
    )


def _read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    body = os.getenv("BODY", "")
    if body:
        return body
    return sys.stdin.read()


def _parse_labels(values: Sequence[str]) -> list[str]:
    labels: list[str] = []
    for value in values:
        labels.extend(label.strip() for label in value.split(",") if label.strip())
    env_labels = os.getenv("LABELS", "")
    if env_labels:
        labels.extend(label.strip() for label in env_labels.split(",") if label.strip())
    return labels


def _issue_number_arg(value: int | None) -> int | None:
    if value is not None:
        return value
    env_value = os.getenv("ISSUE_NUMBER", "").strip()
    if not env_value:
        return None
    return int(env_value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", help="Path to an issue body markdown file.")
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--label", action="append", default=[], help="Issue label; may be repeated or comma-separated.")
    parser.add_argument("--output-json", help="Write JSON report to this path.")
    parser.add_argument("--output-markdown", help="Write Markdown report to this path.")
    parser.add_argument(
        "--observe-only",
        action="store_true",
        help="Always exit 0 after writing the report; intended for artifact-only CI.",
    )
    args = parser.parse_args()

    report = classify_issue_body(
        _read_body(args),
        issue_number=_issue_number_arg(args.issue_number),
        labels=_parse_labels(args.label),
    )
    payload = asdict(report)
    json_text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if args.output_json:
        Path(args.output_json).write_text(json_text, encoding="utf-8")
    if args.output_markdown:
        Path(args.output_markdown).write_text(render_markdown(report), encoding="utf-8")
    if not args.output_json and not args.output_markdown:
        print(json_text, end="")

    if args.observe_only or report.readiness_classification == "ready_candidate":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
