from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.post_merge_docs_classifier import classify, render_markdown


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pr(body: str, *, title: str = "Test PR") -> dict[str, object]:
    return {
        "number": 42,
        "title": title,
        "body": body,
        "head": {"sha": "abc123"},
        "merge_commit": {"sha": "def456"},
    }


def _body(owner_doc_line: str, extra: str = "") -> str:
    return f"""Closes #3217

## Owner-Doc Writeback
- [ ] No owner-doc change implied.
- [ ] Owner-doc updated in this PR.
- [ ] Owner-doc follow-up issue created and linked.

{owner_doc_line}

{extra}
"""


def test_classifier_emits_markdown_and_json(tmp_path: Path) -> None:
    pr_json = tmp_path / "pr.json"
    files_json = tmp_path / "files.json"
    issue_json = tmp_path / "issue.json"
    out_json = tmp_path / "classification.json"
    out_md = tmp_path / "classification.md"
    pr_json.write_text(
        json.dumps(_pr(_body("- [x] No owner-doc change implied."))),
        encoding="utf-8",
    )
    files_json.write_text(json.dumps([{"filename": "tests/scripts/test_example.py"}]), encoding="utf-8")
    issue_json.write_text(json.dumps({"number": 3217}), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "scripts/post_merge_docs_classifier.py",
            "--pr-json",
            str(pr_json),
            "--files-json",
            str(files_json),
            "--issue-json",
            str(issue_json),
            "--output-json",
            str(out_json),
            "--output-markdown",
            str(out_md),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    markdown = out_md.read_text(encoding="utf-8")
    assert payload["merged_pr_number"] == 42
    assert payload["merged_pr_sha"] == "def456"
    assert payload["impact_classification"] == "no_change_likely"
    assert "# Post-Merge Docs/Spec Classifier" in markdown


def test_classifier_fixture_matrix() -> None:
    cases = [
        (
            "no_change_likely",
            _body("- [x] No owner-doc change implied."),
            ["tests/governance/test_policy.py"],
        ),
        (
            "docs_update_likely",
            _body("- [x] Owner-doc updated in this PR."),
            ["docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"],
        ),
        (
            "followup_issue_likely",
            _body("- [x] Owner-doc follow-up issue created and linked."),
            ["app/runtime.py"],
        ),
        (
            "human_exception_likely",
            _body(
                "- [x] No owner-doc change implied.",
                "This has strategic ambiguity and needs an owner decision.",
            ),
            ["docs/ROADMAP.md"],
        ),
        ("unknown", "", []),
    ]

    for expected, body, files in cases:
        result = classify(pr=_pr(body), files_payload=files, issue={"number": 3217})
        assert result.impact_classification == expected


def test_unknown_data_is_marked_unknown_not_guessed() -> None:
    result = classify(pr={}, files_payload=[], issue={})

    assert result.impact_classification == "unknown"
    assert "PR payload unavailable" in result.unknowns_missing_evidence
    assert "changed files unavailable" in result.unknowns_missing_evidence
    assert "insufficient evidence" in " ".join(result.evidence)


def test_human_exception_requires_authority_or_contradiction_evidence() -> None:
    normal = classify(
        pr=_pr(_body("- [x] No owner-doc change implied.")),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )
    authority = classify(
        pr=_pr(_body("- [x] No owner-doc change implied.", "Owner authority is ambiguous.")),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )
    contradiction = classify(
        pr=_pr(_body("- [x] No owner-doc change implied.", "Shipped behavior contradicts target spec.")),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )
    ordinary_owner_doc_update = classify(
        pr=_pr(_body("- [x] Owner-doc updated in this PR.", "No human exception is needed.")),
        files_payload=["docs/ARCHITECTURE.md"],
        issue={"number": 3217},
    )
    no_exception_phrase = classify(
        pr=_pr(_body("- [x] No owner-doc change implied.", "No human exception is needed.")),
        files_payload=["tests/governance/test_policy.py"],
        issue={"number": 3217},
    )

    assert normal.impact_classification != "human_exception_likely"
    assert authority.impact_classification == "human_exception_likely"
    assert contradiction.impact_classification == "human_exception_likely"
    assert ordinary_owner_doc_update.impact_classification == "docs_update_likely"
    assert no_exception_phrase.impact_classification == "no_change_likely"
    assert "Human Exception" in render_markdown(authority)
