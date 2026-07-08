#!/usr/bin/env python3
"""Build a compact PR evidence pack from GitHub API snapshots."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class CheckSummary:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True)
class EvidencePack:
    pr_number: int | None
    pr_title: str
    head_sha: str
    base_branch: str
    linked_issues: list[int]
    issue_labels: list[str]
    issue_readiness_state: str
    changed_files: list[str]
    lane_classification: str
    validation_check_summary: list[CheckSummary]
    failing_checks: list[CheckSummary]
    pr_contract_status: str
    owner_doc_writeback_declaration: str
    risk_hints: list[str]
    human_exception_required: bool
    unknowns_missing_evidence: list[str]


def _load_json(path: Path | None, default: object) -> object:
    if path is None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _nested_str(data: dict[str, object], *keys: str) -> str:
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return current if isinstance(current, str) else ""


def _linked_issues(body: str) -> list[int]:
    numbers = {
        int(match.group(2))
        for match in re.finditer(
            r"\b(Fixes|Closes|Resolves)\s+#(\d+)\b", body, flags=re.I
        )
    }
    return sorted(numbers)


def _labels(issue: dict[str, object]) -> list[str]:
    labels: list[str] = []
    for label in _as_list(issue.get("labels")):
        if isinstance(label, str):
            labels.append(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            labels.append(str(label["name"]))
    return sorted(labels)


def _readiness(labels: list[str], issue: dict[str, object]) -> str:
    state = issue.get("state")
    if state == "closed":
        return "closed"
    agent_labels = [label for label in labels if label.startswith("agent:")]
    if "agent:ready" in agent_labels:
        return "ready"
    if "agent:blocked" in agent_labels:
        return "blocked"
    if "agent:needs-human" in agent_labels:
        return "needs_human"
    if issue:
        return "open_without_agent_label"
    return "unknown"


def _changed_files(files_payload: object) -> list[str]:
    files: list[str] = []
    for item in _as_list(files_payload):
        if isinstance(item, dict):
            filename = item.get("filename") or item.get("path")
            if isinstance(filename, str):
                files.append(filename)
    return sorted(files)


def _lane(body: str, files: list[str]) -> str:
    if re.search(r"^\s*-\s+\[x\]\s+Docs authoring lane\b", body, re.I | re.M):
        return "docs_authoring"
    if re.search(r"^\s*-\s+\[x\]\s+Governance lane\b", body, re.I | re.M):
        return "governance"
    if any(path.startswith(("app/", "tests/")) for path in files):
        return "implementation"
    return "unknown"


def _checks(checks_payload: object) -> list[CheckSummary]:
    payload = _as_dict(checks_payload)
    raw_checks = payload.get("check_runs", checks_payload)
    checks: list[CheckSummary] = []
    for item in _as_list(raw_checks):
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        status = item.get("status")
        conclusion = item.get("conclusion")
        checks.append(
            CheckSummary(
                name=name if isinstance(name, str) else "unknown",
                status=status if isinstance(status, str) else "unknown",
                conclusion=conclusion if isinstance(conclusion, str) else None,
            )
        )
    return sorted(checks, key=lambda check: check.name)


def _pr_contract_status(checks: list[CheckSummary]) -> str:
    for check in checks:
        if check.name == "pr-contract":
            if check.status != "completed":
                return check.status
            return check.conclusion or "unknown"
    return "unknown"


def _owner_doc_declaration(body: str) -> str:
    patterns = (
        ("no_owner_doc_change", r"-\s+\[x\]\s+No owner-doc change implied\."),
        ("owner_doc_updated", r"-\s+\[x\]\s+Owner-doc updated in this PR\."),
        (
            "owner_doc_followup_created",
            r"-\s+\[x\]\s+Owner-doc follow-up issue created and linked\.",
        ),
    )
    matched = [name for name, pattern in patterns if re.search(pattern, body, re.I)]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "conflicting_declarations"
    return "unknown"


def _codeowner_patterns(path: Path | None) -> list[tuple[str, list[str]]]:
    if path is None or not path.exists():
        return []
    patterns: list[tuple[str, list[str]]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            patterns.append((parts[0].lstrip("/"), parts[1:]))
    return patterns


def _matches_codeowner(pattern: str, filename: str) -> bool:
    normalized = filename.lstrip("/")
    if pattern.endswith("/"):
        return normalized.startswith(pattern)
    return normalized == pattern


def _risk_hints(files: list[str], codeowners_path: Path | None) -> list[str]:
    hints: list[str] = []
    owner_patterns = _codeowner_patterns(codeowners_path)
    for filename in files:
        if filename.startswith(".github/workflows/"):
            hints.append(f"workflow_authority_path:{filename}")
        if filename.startswith((".codex/skills/", "AGENTS.md")):
            hints.append(f"builder_governance_path:{filename}")
        if filename.startswith(("app/", "scripts/")):
            hints.append(f"runtime_or_tooling_path:{filename}")
        for pattern, owners in owner_patterns:
            if _matches_codeowner(pattern, filename):
                hints.append(f"codeowner_required:{filename}:{','.join(owners)}")
    return sorted(set(hints))


def _unknowns(
    linked_issues: list[int],
    issue_labels: list[str],
    checks: list[CheckSummary],
    owner_doc_declaration: str,
) -> list[str]:
    missing: list[str] = []
    if not linked_issues:
        missing.append("linked issue not found in PR body")
    if linked_issues and not issue_labels:
        missing.append("linked issue labels unavailable")
    if not checks:
        missing.append("check run evidence unavailable")
    if owner_doc_declaration == "unknown":
        missing.append("owner-doc writeback declaration unavailable")
    return missing


def build_pack(
    *,
    pr: dict[str, object],
    files_payload: object,
    checks_payload: object,
    issue: dict[str, object],
    codeowners_path: Path | None = None,
) -> EvidencePack:
    body = pr.get("body") if isinstance(pr.get("body"), str) else ""
    files = _changed_files(files_payload)
    checks = _checks(checks_payload)
    linked_issues = _linked_issues(body)
    labels = _labels(issue)
    failing = [
        check
        for check in checks
        if check.status == "completed"
        and check.conclusion not in {None, "success", "neutral", "skipped"}
    ]
    risks = _risk_hints(files, codeowners_path)
    owner_doc = _owner_doc_declaration(body)
    unknowns = _unknowns(linked_issues, labels, checks, owner_doc)
    human_exception_required = (
        owner_doc == "conflicting_declarations"
        or any(hint.startswith("codeowner_required:") for hint in risks)
        or "agent:needs-human" in labels
    )
    return EvidencePack(
        pr_number=pr.get("number") if isinstance(pr.get("number"), int) else None,
        pr_title=pr.get("title") if isinstance(pr.get("title"), str) else "",
        head_sha=_nested_str(pr, "head", "sha"),
        base_branch=_nested_str(pr, "base", "ref"),
        linked_issues=linked_issues,
        issue_labels=labels,
        issue_readiness_state=_readiness(labels, issue),
        changed_files=files,
        lane_classification=_lane(body, files),
        validation_check_summary=checks,
        failing_checks=failing,
        pr_contract_status=_pr_contract_status(checks),
        owner_doc_writeback_declaration=owner_doc,
        risk_hints=risks,
        human_exception_required=human_exception_required,
        unknowns_missing_evidence=unknowns,
    )


def render_markdown(pack: EvidencePack) -> str:
    linked = ", ".join(f"#{number}" for number in pack.linked_issues) or "unknown"
    files = "\n".join(f"- `{filename}`" for filename in pack.changed_files) or "- none"
    checks = (
        "\n".join(
            f"- `{check.name}`: status={check.status}, conclusion={check.conclusion or 'unknown'}"
            for check in pack.validation_check_summary
        )
        or "- unknown"
    )
    failing = (
        "\n".join(
            f"- `{check.name}`: status={check.status}, conclusion={check.conclusion or 'unknown'}"
            for check in pack.failing_checks
        )
        or "- none"
    )
    unknowns = "\n".join(f"- {item}" for item in pack.unknowns_missing_evidence) or "- none"
    risks = "\n".join(f"- {item}" for item in pack.risk_hints) or "- none"
    return "\n".join(
        [
            "# PR Evidence Pack",
            "",
            f"- PR: #{pack.pr_number or 'unknown'}",
            f"- Title: {pack.pr_title or 'unknown'}",
            f"- Head SHA: `{pack.head_sha or 'unknown'}`",
            f"- Base branch: `{pack.base_branch or 'unknown'}`",
            f"- Linked issue(s): {linked}",
            f"- Issue labels: `{', '.join(pack.issue_labels) or 'unknown'}`",
            f"- Issue readiness: `{pack.issue_readiness_state}`",
            f"- Lane: `{pack.lane_classification}`",
            f"- PR contract status: `{pack.pr_contract_status}`",
            f"- Owner-doc writeback: `{pack.owner_doc_writeback_declaration}`",
            f"- Human exception required: `{pack.human_exception_required}`",
            "",
            "## Changed Files",
            "",
            files,
            "",
            "## Checks",
            "",
            checks,
            "",
            "## Failing Checks",
            "",
            failing,
            "",
            "## Risk Hints",
            "",
            risks,
            "",
            "## Unknowns / Missing Evidence",
            "",
            unknowns,
            "",
        ]
    )


def _write_outputs(pack: EvidencePack, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(asdict(pack), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(pack), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--files-json", type=Path, required=True)
    parser.add_argument("--checks-json", type=Path, required=True)
    parser.add_argument("--issue-json", type=Path)
    parser.add_argument("--codeowners", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    pack = build_pack(
        pr=_as_dict(_load_json(args.pr_json, {})),
        files_payload=_load_json(args.files_json, []),
        checks_payload=_load_json(args.checks_json, {}),
        issue=_as_dict(_load_json(args.issue_json, {})),
        codeowners_path=args.codeowners,
    )
    _write_outputs(pack, args.output_json, args.output_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
