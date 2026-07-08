from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_issue_readiness import classify_issue_body


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/issue_readiness"


@pytest.mark.parametrize(
    ("fixture_name", "expected_classification", "guidance_snippet"),
    [
        ("valid_ready_candidate.md", "ready_candidate", "No repair required"),
        ("missing_constraints.md", "missing_required_sections", "Constraints"),
        ("missing_source_docs.md", "missing_source_docs", "Source Docs"),
        ("ac_without_verify.md", "missing_verify_markers", "Verify"),
        ("ambiguous_intent.md", "ambiguous_intent", "vague intent"),
        ("authority_risk.md", "authority_risk", "authority question"),
        ("legacy_malformed_body.md", "unknown", "canonical task template"),
    ],
)
def test_fixture_classifications(
    fixture_name: str,
    expected_classification: str,
    guidance_snippet: str,
) -> None:
    body = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

    report = classify_issue_body(body, issue_number=3212, labels=["type:task", "prio:high"])

    assert report.issue_number == 3212
    assert report.readiness_classification == expected_classification
    assert any(guidance_snippet in item for item in report.repair_guidance)


def test_ready_candidate_reports_required_detail() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    report = classify_issue_body(body, labels=["prio:high", "agent:ready", "prio:high"])

    assert report.labels == ["agent:ready", "prio:high"]
    assert report.required_sections.missing == []
    assert report.source_docs_present is True
    assert report.source_docs_missing is False
    assert report.acceptance_criteria.present is True
    assert report.acceptance_criteria.count == 2
    assert report.verify_markers_present is True
    assert report.verify_markers_missing is False
    assert report.human_exception_required is False


def test_missing_verify_reports_exact_item_guidance() -> None:
    body = (FIXTURE_DIR / "ac_without_verify.md").read_text(encoding="utf-8")

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker identifies acceptance criteria without verify markers."
    ]
    assert "acceptance criteria without verify markers" in report.repair_guidance[-1]


def test_blocked_or_needs_human_labels_are_not_agentable() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    blocked = classify_issue_body(body, labels=["agent:blocked"])
    needs_human = classify_issue_body(body, labels=["agent:needs-human"])

    assert blocked.readiness_classification == "not_agentable"
    assert blocked.human_exception_required is True
    assert needs_human.readiness_classification == "not_agentable"
    assert needs_human.human_exception_required is True


def test_cli_observe_only_writes_json_and_markdown(tmp_path: Path) -> None:
    json_path = tmp_path / "readiness.json"
    markdown_path = tmp_path / "readiness.md"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_issue_readiness.py",
            "--body-file",
            str(FIXTURE_DIR / "ac_without_verify.md"),
            "--issue-number",
            "3212",
            "--label",
            "agent:ready,lane:governance",
            "--output-json",
            str(json_path),
            "--output-markdown",
            str(markdown_path),
            "--observe-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout == ""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["readiness_classification"] == "missing_verify_markers"
    assert payload["issue_number"] == 3212
    assert payload["labels"] == ["agent:ready", "lane:governance"]
    assert "Classification: `missing_verify_markers`" in markdown_path.read_text(encoding="utf-8")


def test_cli_fails_non_ready_without_observe_only() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_issue_readiness.py",
            "--body-file",
            str(FIXTURE_DIR / "missing_constraints.md"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["readiness_classification"] == "missing_required_sections"


def test_cli_reads_issue_number_from_environment(tmp_path: Path) -> None:
    json_path = tmp_path / "readiness.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_issue_readiness.py",
            "--body-file",
            str(FIXTURE_DIR / "valid_ready_candidate.md"),
            "--output-json",
            str(json_path),
            "--observe-only",
        ],
        cwd=REPO_ROOT,
        env={"ISSUE_NUMBER": "3212", **os.environ},
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout == ""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["issue_number"] == 3212
