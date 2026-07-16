#!/usr/bin/env python3
"""Classify merged PR owner-doc/spec impact from GitHub evidence snapshots."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from app.dispatcher.verification_contract import IssueAuthority, resolve_issue_authority
from app.dispatcher.verified_merge import resolve_post_merge_issue_authority


CLASSIFICATIONS: tuple[str, ...] = (
    "no_change_likely",
    "docs_update_likely",
    "followup_issue_likely",
    "human_exception_likely",
    "unknown",
)
_GOVERNANCE_SCRIPT_FILES = {
    "scripts/build_pr_evidence_pack.py",
    "scripts/docs_guard.py",
    "scripts/lint_skills_consistency.py",
    "scripts/post_merge_docs_classifier.py",
    "scripts/validate_issue_readiness.py",
    "scripts/validate_source_anchors.py",
}


@dataclass(frozen=True)
class PostMergeDocsClassification:
    merged_pr_number: int | None
    merged_pr_title: str
    merged_pr_sha: str
    linked_issues: list[int]
    changed_files: list[str]
    owner_doc_spec_declaration: str
    changed_docs_spec_files: list[str]
    impact_classification: str
    evidence: list[str]
    unknowns_missing_evidence: list[str]
    recommended_next_action: str


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


def _linked_issues(
    body: str,
    issue: dict[str, object],
    trusted_authority: IssueAuthority | None = None,
) -> list[int]:
    authority = trusted_authority or resolve_issue_authority(body)
    numbers = set(authority.closing_issues) if authority is not None else set()
    issue_number = issue.get("number")
    if isinstance(issue_number, int):
        numbers.add(issue_number)
    return sorted(numbers)


def _changed_files(files_payload: object) -> list[str]:
    files: list[str] = []
    for item in _as_list(files_payload):
        if isinstance(item, str):
            files.append(item)
        elif isinstance(item, dict):
            filename = item.get("filename") or item.get("path")
            if isinstance(filename, str):
                files.append(filename)
    return sorted(set(files))


def _owner_doc_declaration(body: str) -> str:
    patterns = (
        ("no_change_declared", r"-\s+\[x\]\s+No owner-doc change implied\."),
        ("updated_in_pr", r"-\s+\[x\]\s+Owner-doc updated in this PR\."),
        ("followup_created", r"-\s+\[x\]\s+Owner-doc follow-up issue created and linked\."),
    )
    matched = [name for name, pattern in patterns if re.search(pattern, body, re.I)]
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "conflicting_declarations"
    return "unknown"


def _docs_spec_files(files: list[str]) -> list[str]:
    prefixes = (
        "docs/",
        ".codex/skills/",
        ".github/ISSUE_TEMPLATE/",
    )
    exact = {"AGENTS.md", ".github/pull_request_template.md"}
    return sorted(
        filename
        for filename in files
        if filename in exact
        or filename.startswith(prefixes)
        or re.search(r"(?:^|/)(?:ADR|SPEC|README)[A-Za-z0-9_.-]*\.md$", filename)
    )


def _runtime_or_contract_files(files: list[str]) -> list[str]:
    prefixes = (
        "app/",
        "alembic/",
        "infra/",
        "schemas/",
        "scripts/",
        ".github/workflows/",
    )
    return sorted(filename for filename in files if filename.startswith(prefixes))


def _governance_only_files(files: list[str]) -> bool:
    allowed_prefixes = (
        ".github/workflows/",
        ".github/ISSUE_TEMPLATE/",
        ".codex/skills/",
        "tests/governance/",
        "tests/scripts/",
    )
    allowed_exact = {".github/pull_request_template.md", "AGENTS.md"}
    return bool(files) and all(
        filename in allowed_exact
        or filename in _GOVERNANCE_SCRIPT_FILES
        or filename.startswith(allowed_prefixes)
        for filename in files
    )


def _authority_or_contradiction_evidence(body: str, files: list[str]) -> list[str]:
    evidence: list[str] = []
    if _owner_doc_declaration(body) == "conflicting_declarations":
        evidence.append("owner-doc writeback declaration has conflicting checked options")
    if re.search(r"\b(owner authority|strategic ambiguity|owner decision)\b", body, re.I):
        evidence.append("PR body names owner authority, strategic ambiguity, or owner decision")
    if _has_explicit_target_contradiction(body):
        evidence.append("PR body indicates shipped-vs-target/spec contradiction")
    return evidence


def _has_explicit_target_contradiction(body: str) -> bool:
    for phrase in re.split(r"[\n.;]+", body):
        normalized = " ".join(phrase.lower().split())
        if not normalized:
            continue
        if not re.search(r"\b(?:target|planned|roadmap|spec)\b", normalized):
            continue
        if not re.search(r"\b(?:contradict\w*|conflict\w*)\b", normalized):
            continue
        if re.search(
            r"\b(?:does not|do not|did not|no|not|never|without)\s+"
            r"(?:\w+\s+){0,3}(?:contradict\w*|conflict\w*)\b",
            normalized,
        ):
            continue
        return True
    return False


def _unknowns(
    *,
    pr: dict[str, object],
    linked_issues: list[int],
    files: list[str],
    owner_doc_declaration: str,
) -> list[str]:
    unknowns: list[str] = []
    if not pr:
        unknowns.append("PR payload unavailable")
    if not linked_issues:
        unknowns.append("linked issue unavailable")
    if not files:
        unknowns.append("changed files unavailable")
    if owner_doc_declaration == "unknown":
        unknowns.append("owner-doc/spec declaration unavailable")
    return unknowns


def classify(
    *,
    pr: dict[str, object],
    files_payload: object,
    issue: dict[str, object],
    comments_payload: object | None = None,
    repository: str | None = None,
) -> PostMergeDocsClassification:
    raw_body = pr.get("body")
    body = raw_body if isinstance(raw_body, str) else ""
    files = _changed_files(files_payload)
    docs_files = _docs_spec_files(files)
    runtime_files = _runtime_or_contract_files(files)
    declaration = _owner_doc_declaration(body)
    if (comments_payload is None) != (repository is None):
        raise ValueError("post-merge authority inputs must be supplied together")
    trusted_authority: IssueAuthority | None = None
    if comments_payload is not None and repository is not None:
        if (
            not isinstance(comments_payload, list)
            or any(not isinstance(comment, dict) for comment in comments_payload)
            or not repository
        ):
            raise ValueError("post-merge authority inputs are malformed")
        trusted_authority = resolve_post_merge_issue_authority(
            comments_payload,
            pr=pr,
            repository=repository,
        )
    linked = _linked_issues(body, issue, trusted_authority)
    unknowns = _unknowns(
        pr=pr,
        linked_issues=linked,
        files=files,
        owner_doc_declaration=declaration,
    )
    evidence: list[str] = []
    authority_evidence = _authority_or_contradiction_evidence(body, files)
    blocking_unknowns = list(unknowns)
    if (
        blocking_unknowns == ["linked issue unavailable"]
        and declaration in {"no_change_declared", "updated_in_pr", "followup_created"}
        and files
    ):
        blocking_unknowns = []

    if blocking_unknowns and not evidence and not authority_evidence:
        classification = "unknown"
        evidence.append("insufficient evidence; classifier did not infer missing facts")
        action = "Collect PR body, linked issue, changed files, and owner-doc declaration before deciding."
    elif authority_evidence:
        classification = "human_exception_likely"
        evidence.extend(authority_evidence)
        action = "Escalate with a Human Exception packet before changing owner docs or follow-up state."
    elif declaration == "followup_created":
        classification = "followup_issue_likely"
        evidence.append("PR declares an owner-doc follow-up issue was created and linked")
        action = "Verify the linked follow-up issue exists; do not create another artifact automatically."
    elif declaration == "updated_in_pr" or docs_files:
        classification = "docs_update_likely"
        if declaration == "updated_in_pr":
            evidence.append("PR declares owner-doc/spec updated in this PR")
        if docs_files:
            evidence.append("PR changed docs/spec files")
        action = "Review changed docs/spec files and record a post-merge owner-doc receipt."
    elif declaration == "no_change_declared" and (not runtime_files or _governance_only_files(files)):
        classification = "no_change_likely"
        evidence.append("PR declares no owner-doc change implied")
        if _governance_only_files(files):
            evidence.append("changed files are governance/tooling surfaces")
        action = "Record no-change post-merge owner-doc receipt; no docs PR is recommended."
    elif runtime_files:
        classification = "docs_update_likely"
        evidence.append("PR changed runtime, workflow, script, or contract files without docs/spec update evidence")
        action = "Review owner docs/specs for shipped behavior drift before closing the feedback loop."
    else:
        classification = "unknown"
        evidence.append("available evidence does not match a deterministic classification rule")
        action = "Collect missing evidence or classify manually; do not mutate owner docs automatically."

    raw_number = pr.get("number")
    raw_title = pr.get("title")
    return PostMergeDocsClassification(
        merged_pr_number=raw_number if isinstance(raw_number, int) else None,
        merged_pr_title=raw_title if isinstance(raw_title, str) else "",
        merged_pr_sha=_nested_str(pr, "merge_commit", "sha") or _nested_str(pr, "head", "sha"),
        linked_issues=linked,
        changed_files=files,
        owner_doc_spec_declaration=declaration,
        changed_docs_spec_files=docs_files,
        impact_classification=classification,
        evidence=evidence,
        unknowns_missing_evidence=unknowns,
        recommended_next_action=action,
    )


def render_markdown(result: PostMergeDocsClassification) -> str:
    linked = ", ".join(f"#{number}" for number in result.linked_issues) or "unknown"
    files = "\n".join(f"- `{filename}`" for filename in result.changed_files) or "- unknown"
    docs = "\n".join(f"- `{filename}`" for filename in result.changed_docs_spec_files) or "- none"
    evidence = "\n".join(f"- {item}" for item in result.evidence) or "- none"
    unknowns = "\n".join(f"- {item}" for item in result.unknowns_missing_evidence) or "- none"
    return "\n".join(
        [
            "# Post-Merge Docs/Spec Classifier",
            "",
            f"- Merged PR: #{result.merged_pr_number or 'unknown'}",
            f"- Title: {result.merged_pr_title or 'unknown'}",
            f"- Merge/head SHA: `{result.merged_pr_sha or 'unknown'}`",
            f"- Linked issue(s): {linked}",
            f"- Owner-doc/spec declaration: `{result.owner_doc_spec_declaration}`",
            f"- Impact classification: `{result.impact_classification}`",
            f"- Recommended next action: {result.recommended_next_action}",
            "",
            "## Changed Files",
            "",
            files,
            "",
            "## Changed Docs/Spec Files",
            "",
            docs,
            "",
            "## Evidence",
            "",
            evidence,
            "",
            "## Unknowns / Missing Evidence",
            "",
            unknowns,
            "",
        ]
    )


def _write_outputs(
    result: PostMergeDocsClassification,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--files-json", type=Path, required=True)
    parser.add_argument("--issue-json", type=Path)
    parser.add_argument("--comments-json", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = classify(
        pr=_as_dict(_load_json(args.pr_json, {})),
        files_payload=_load_json(args.files_json, []),
        issue=_as_dict(_load_json(args.issue_json, {})),
        comments_payload=_load_json(args.comments_json, []),
        repository=args.repository,
    )
    _write_outputs(result, args.output_json, args.output_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
