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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.builderops.issue_contract_validation import (  # noqa: E402
    is_resolvable_verify_target,
)


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
    "missing_verify_file_paths",
    "malformed_acceptance_criteria",
    "malformed_parent_reference",
    "ambiguous_intent",
    "authority_risk",
    "admission_contract_conflict",
    "not_agentable",
    "unknown",
)

ADMISSION_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\blocal admission\b",
        r"\b(?:admission|request) proxy(?:ing)?\b",
        r"\bforwarded[- ]identity\b",
        r"\bforwarded[- ](?:for|host|proto)\b",
        r"\bforward(?:ed|ing)? identity\b",
        r"\bproxy(?:ing|ed)?\b",
    )
)
PRODUCTION_SEAM_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnamed production seam\b",
        r"\bproduction seam\b",
        r"\bdirect loopback\b",
        r"\bloopback endpoint\b",
        r"\b(?:gateway|ingress|reverse proxy)\b",
    )
)
NO_FORWARDED_IDENTITY_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bno forwarded identity\b",
        r"\bwithout forwarded identity\b",
        r"\bmust not forward identity\b",
        r"\bdoes not forward identity\b",
        r"\bno forwarded[- ](?:for|host|proto)\b",
    )
)

REPO_ROOT = Path(__file__).resolve().parents[1]
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
    missing_verify_file_paths: list[str]
    joined_verify_targets: list[str]


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
        content = re.sub(r"^[-*]\s+(?:\[[ xX]\]\s+)?", "", line).strip().strip("`").strip()
        if re.search(r"<[^>]+>", content):
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


_ANNOTATED_TARGET = re.compile(r"^`(?P<inner>[^`]+)` \S.*$")
_DIFF_OF_TARGET = re.compile(r"^diff of `(?P<path>[^`]+)`(?: \S.*)?$")
_MARKER_PRESENCE_TARGET = re.compile(
    r"^`[^`]+` present in `(?P<path>[^`]+)`(?:[,;]? \S.*)?$"
)


def _verify_file_path(target: str) -> str | None:
    canonical = target.strip()
    # Mirror the grammar's multi-segment form order (#4464): an annotated
    # backticked canonical target first, then diff-of-file, then
    # marker-presence, before the single-segment unwrap.
    annotated = _ANNOTATED_TARGET.fullmatch(canonical)
    if annotated is not None and "::" in annotated.group("inner"):
        canonical = f"`{annotated.group('inner')}`"
    else:
        diff_target = _DIFF_OF_TARGET.fullmatch(canonical)
        if diff_target is not None:
            return diff_target.group("path")
        presence_target = _MARKER_PRESENCE_TARGET.fullmatch(canonical)
        if presence_target is not None:
            return presence_target.group("path")
    if canonical.startswith("`") and canonical.endswith("`"):
        canonical = canonical[1:-1]
    if canonical.startswith("runtime receipt: "):
        return None
    for prefix in ("doc writeback at ", "roadmap diff: "):
        if canonical.startswith(prefix):
            canonical = canonical.removeprefix(prefix)
            if canonical.startswith("`") and canonical.endswith("`"):
                canonical = canonical[1:-1]
            path, separator, _ = canonical.partition(" :: ")
            if not separator:
                return None
            if _is_joined_verify_target(target):
                return path
            return path.strip("`")
    path, separator, spaced_rest = canonical.partition(" :: ")
    if separator and spaced_rest:
        return path
    path, separator, _ = canonical.partition("::")
    return path if separator else None


def _is_new_behavioral_test_file_target(target: str, path: str) -> bool:
    """Return whether *target* commits the builder to add a test file."""

    return (
        path.startswith("tests/")
        and path.endswith(".py")
        and is_resolvable_verify_target(target)
    )


def _target_has_missing_file_path(target: str) -> bool:
    if re.search(r"<[^>]+>", target):
        return False
    path = _verify_file_path(target)
    if path is None:
        return False
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return True
    return not (REPO_ROOT / candidate).is_file() and not _is_new_behavioral_test_file_target(
        target, path
    )


def _target_has_existing_file_path(target: str) -> bool:
    if re.search(r"<[^>]+>", target):
        return False
    path = _verify_file_path(target)
    if path is None:
        return False
    candidate = Path(path)
    return (
        not candidate.is_absolute()
        and ".." not in candidate.parts
        and (REPO_ROOT / candidate).is_file()
    )


# A `Verify:` marker is declared when it opens its own (optionally bulleted)
# line per the body template, or when an inline tail (`- [ ] text. Verify:
# <target>`) carries a grammar-resolvable target. A mid-line mention inside
# AC prose whose tail is not a resolvable target is not a marker (#4464).
_VERIFY_MARKER_ANY = re.compile(r"(?im)(?:^|\b)Verify:[ \t]*(.*)$")
_VERIFY_LINE_LEAD = re.compile(r"[ \t]*(?:[-*][ \t]+)?(?:\[[ xX]\][ \t]+)?")


def _declared_verify_targets(item: str) -> list[str]:
    declared: list[str] = []
    for match in _VERIFY_MARKER_ANY.finditer(item):
        line_start = item.rfind("\n", 0, match.start()) + 1
        lead = item[line_start : match.start()]
        target = match.group(1).strip()
        if _VERIFY_LINE_LEAD.fullmatch(lead) is not None:
            declared.append(target)
        elif is_resolvable_verify_target(target):
            declared.append(target)
    return declared


def _has_concrete_verify_marker(item: str) -> bool:
    targets = tuple(_declared_verify_targets(item))
    return (
        bool(targets)
        and len(set(targets)) == len(targets)
        and all(
            is_resolvable_verify_target(target)
            or _target_has_existing_file_path(target)
            or _target_has_missing_file_path(target)
            for target in targets
        )
    )


def _verify_targets(item: str) -> list[str]:
    return [target for target in _declared_verify_targets(item) if target]


# Authors who need several targets on one AC sometimes join them on a single
# marker line instead of writing one `Verify:` line each (#3857, #3859). The
# joined line's backticks no longer pair, so the extracted path is a fragment
# and the reported "missing file" names a file that exists.
_JOINED_VERIFY_TARGET = re.compile(r"`\s*(?:\+|and)\s")


def _is_joined_verify_target(target: str) -> bool:
    return (
        _JOINED_VERIFY_TARGET.search(target) is not None
        and not is_resolvable_verify_target(target)
    )


def _joined_verify_targets(item: str) -> list[str]:
    return [
        target
        for target in _verify_targets(item)
        if _is_joined_verify_target(target) and _target_has_missing_file_path(target)
    ]


def _missing_verify_file_paths(item: str) -> list[str]:
    missing_paths: list[str] = []
    for target in _verify_targets(item):
        if _target_has_missing_file_path(target):
            path = _verify_file_path(target)
            if path is not None:
                missing_paths.append(path)
    return missing_paths


def analyze_acceptance_criteria(section: str | None) -> AcceptanceCriteriaReport:
    lines = _non_placeholder_lines(section)
    items = _extract_acceptance_items(section)
    malformed = bool(lines) and not items
    missing_verify = [
        _summarize_item(item)
        for item in items
        if not _has_concrete_verify_marker(item)
    ]
    missing_file_paths = [
        path for item in items for path in _missing_verify_file_paths(item)
    ]
    joined_targets = [
        target for item in items for target in _joined_verify_targets(item)
    ]
    return AcceptanceCriteriaReport(
        present=bool(items),
        count=len(items),
        malformed=malformed,
        verify_markers_present=bool(items) and not missing_verify,
        missing_verify_items=missing_verify,
        missing_verify_file_paths=missing_file_paths,
        joined_verify_targets=joined_targets,
    )


_PARENT_CANONICAL = re.compile(r"^Parent: #[1-9][0-9]*$")
_ISSUE_NUMBER_TOKEN = re.compile(r"#[0-9]+")


def _parent_declaration_lines(body: str) -> list[str]:
    """Lines that declare a child->parent reference (INV-DG-3).

    The declaration grammar is a line starting with ``Parent:`` that carries an
    issue-number token. Descriptive ``Parent:`` prose without a ``#<digits>``
    token and legacy ``Parent feature issue: #N`` prose are not declarations,
    so orphan slices and legacy bodies stay valid.
    """
    return [
        stripped
        for line in body.splitlines()
        if (stripped := line.strip()).startswith("Parent:")
        and _ISSUE_NUMBER_TOKEN.search(stripped)
    ]


def _parent_reference_problem(body: str) -> str | None:
    declared = _parent_declaration_lines(body)
    if not declared:
        return None
    if len(declared) > 1:
        return "multiple parent declarations: " + "; ".join(declared)
    if not _PARENT_CANONICAL.fullmatch(declared[0]):
        return f"malformed parent declaration: {declared[0]}"
    return None


def _contains_any(patterns: Sequence[re.Pattern[str]], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def admission_contract_problem(body: str) -> str | None:
    """Reject readiness claims that lack or contradict their production seam."""

    if not _contains_any(ADMISSION_CLAIM_PATTERNS, body):
        return None
    if not _contains_any(PRODUCTION_SEAM_PATTERNS, body):
        return "admission/proxy/forwarded-identity claim has no named production seam"
    if _contains_any(NO_FORWARDED_IDENTITY_PATTERNS, body):
        forwarded_assertion = re.search(
            r"\b(?:forward|preserve|accept|trust|use|require)[a-z -]{0,24}"
            r"(?:forwarded[- ](?:identity|for|host|proto)|forward(?:ed|ing)? identity)\b",
            body,
            re.IGNORECASE,
        )
        forwarded_assertion = forwarded_assertion or re.search(
            r"\bforward identity\b", body, re.IGNORECASE
        )
        if forwarded_assertion is not None:
            return "forwarded-identity assertion contradicts the named no-forwarding seam"
    return None


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
    elif ac_report.missing_verify_file_paths:
        classification = "missing_verify_file_paths"
    elif _parent_reference_problem(body) is not None:
        classification = "malformed_parent_reference"
    elif admission_contract_problem(body) is not None:
        classification = "admission_contract_conflict"
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
    if classification == "admission_contract_conflict":
        return [
            "Name the production admission seam (for example, direct loopback or gateway) in the Issue.",
            "Rewrite readiness claims so forwarded-identity and proxy behavior agree with that seam.",
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
    if classification == "malformed_parent_reference":
        return [
            "Declare the governing parent as exactly one canonical `Parent: #<N>` line (plain text, one parent, no bold or prose around the number).",
            "Orphan slices carry no `Parent:` declaration at all; see `.codex/skills/_shared/ISSUE_CONTRACT.md :: Child to parent reference`.",
        ]
    if classification == "missing_verify_markers":
        missing_items = "; ".join(ac_report.missing_verify_items)
        return [
            "Add an inline `Verify:` marker to every acceptance criterion.",
            "Missing Verify marker on: " + missing_items + ".",
        ]
    if classification == "missing_verify_file_paths":
        guidance = [
            "Update every non-test file-based `Verify:` target to name an existing repository file; a behavioral `tests/...py::test_name` target may name a new test file for the builder to add.",
            "Missing Verify file path(s): "
            + ", ".join(ac_report.missing_verify_file_paths)
            + ".",
        ]
        if ac_report.joined_verify_targets:
            guidance.append(
                "Some `Verify:` line(s) join several targets on one line, so the reported path is a "
                "fragment of a joined line rather than a missing file. Split them into one `Verify:` "
                "line per target under the same acceptance item (the AC count does not change); see "
                "`.codex/skills/_shared/ISSUE_CONTRACT.md :: Verify: marker rule`. Joined line(s): "
                + "; ".join(ac_report.joined_verify_targets)
                + "."
            )
        return guidance
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
