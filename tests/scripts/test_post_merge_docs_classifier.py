from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.dispatcher.verified_merge import prepare_verified_merge
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
    return f"""Governing-Issue: #3217

Closes #3217

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
    comments_json = tmp_path / "comments.json"
    out_json = tmp_path / "classification.json"
    out_md = tmp_path / "classification.md"
    pr_json.write_text(
        json.dumps(_pr(_body("- [x] No owner-doc change implied."))),
        encoding="utf-8",
    )
    files_json.write_text(json.dumps([{"filename": "tests/scripts/test_example.py"}]), encoding="utf-8")
    issue_json.write_text(json.dumps({"number": 3217}), encoding="utf-8")
    comments_json.write_text("[]\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.post_merge_docs_classifier",
            "--pr-json",
            str(pr_json),
            "--files-json",
            str(files_json),
            "--issue-json",
            str(issue_json),
            "--comments-json",
            str(comments_json),
            "--repository",
            "RasmusTho/agentic-pkm-mvp",
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


def _neutralized_multi_issue_evidence() -> tuple[dict[str, object], list[dict[str, object]]]:
    head = "a" * 40
    body = (
        "Governing-Issue: #3821\n"
        "Refs #3821\n"
        "Fixes #3820\n"
        "Closes #3823\n"
        "\n## Owner-Doc Writeback\n"
        "- [x] No owner-doc change implied.\n"
    )
    pr = {
        "number": 3822,
        "title": "governance: deterministic issue-set closure",
        "body": body,
        "state": "open",
        "merged_at": None,
        "draft": False,
        "head": {"sha": head},
    }
    plan = prepare_verified_merge(
        context={
            "contract": "verification_closer_dispatch_context.v2",
            "run_id": "vrun-classifier",
            "repository": "RasmusTho/agentic-pkm-mvp",
            "pr_number": 3822,
            "governing_issue": 3821,
            "closing_issues": [3820, 3823],
            "supporting_issues": [3820, 3823],
            "head_sha": head,
            "repair_budget": {
                "policy_version": "v2",
                "mechanism_count": 0,
                "truncated": False,
                "omitted_count": 0,
                "mechanisms": [],
            },
        },
        pr=pr,
        live_closing_issues=[3820, 3823],
        merge_readiness={
            "contract": "verified_issue_set_merge_readiness.v1",
            "further_commits_anticipated": False,
            "head_sha": head,
            "required_checks_green": True,
            "review_gate_resolved": True,
        },
    )
    neutralized_pr = {**pr, "body": plan["neutralized_body"]}
    comments = [
        {
            "author_association": "COLLABORATOR",
            "body": plan["authority_receipt_comment"],
        }
    ]
    return neutralized_pr, comments


def test_classifier_carries_trusted_closing_set_during_neutralized_window() -> None:
    pr, comments = _neutralized_multi_issue_evidence()

    result = classify(
        pr=pr,
        files_payload=["tests/governance/test_policy.py"],
        issue={"number": 3821},
        comments_payload=comments,
        repository="RasmusTho/agentic-pkm-mvp",
    )

    assert result.linked_issues == [3820, 3821, 3823]


def test_classifier_rejects_forged_stale_and_conflicting_merge_authority() -> None:
    pr, comments = _neutralized_multi_issue_evidence()
    forged = [{**comments[0], "author_association": "NONE"}]
    forged_result = classify(
        pr=pr,
        files_payload=["tests/governance/test_policy.py"],
        issue={},
        comments_payload=forged,
        repository="RasmusTho/agentic-pkm-mvp",
    )
    assert forged_result.linked_issues == []

    with pytest.raises(ValueError, match="trusted verified merge authority"):
        classify(
            pr={**pr, "head": {"sha": "b" * 40}},
            files_payload=["tests/governance/test_policy.py"],
            issue={},
            comments_payload=comments,
            repository="RasmusTho/agentic-pkm-mvp",
        )

    conflicting = json.loads(
        str(comments[0]["body"]).split("```json\n", 1)[1].split("\n```", 1)[0]
    )
    conflicting["repair_budget"] = {
        "policy_version": "v2",
        "mechanisms": [],
    }
    conflicting_comment = {
        "author_association": "COLLABORATOR",
        "body": (
            "verified issue-set merge authority:\n```json\n"
            + json.dumps(conflicting, sort_keys=True, separators=(",", ":"))
            + "\n```"
        ),
    }
    with pytest.raises(ValueError, match="trusted verified merge authority"):
        classify(
            pr=pr,
            files_payload=["tests/governance/test_policy.py"],
            issue={},
            comments_payload=[*comments, conflicting_comment],
            repository="RasmusTho/agentic-pkm-mvp",
        )


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


def test_classifier_uses_canonical_closing_keyword_variants() -> None:
    result = classify(
        pr=_pr(
            _body("- [x] No owner-doc change implied.").replace(
                "Closes #3217", "Resolve: #3217"
            )
        ),
        files_payload=["tests/governance/test_policy.py"],
        issue={"number": 3217},
    )

    assert result.linked_issues == [3217]


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


def test_issue_less_governance_pr_uses_declaration_and_files() -> None:
    result = classify(
        pr=_pr(
            _body("- [x] No owner-doc change implied.").replace("Closes #3217\n\n", ""),
            title="governance: tune post-merge classifier",
        ),
        files_payload=["scripts/post_merge_docs_classifier.py"],
        issue={},
    )

    assert result.linked_issues == []
    assert result.impact_classification == "no_change_likely"
    assert "linked issue unavailable" in result.unknowns_missing_evidence
    assert "changed files are governance/tooling surfaces" in result.evidence


def test_target_spec_exception_requires_explicit_contradiction() -> None:
    ordinary_spec_reference = classify(
        pr=_pr(
            _body(
                "- [x] No owner-doc change implied.",
                "Implemented SBI-1. Source docs: docs/foo/SPEC.md.",
            )
        ),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )
    explicit_contradiction = classify(
        pr=_pr(
            _body(
                "- [x] No owner-doc change implied.",
                "Shipped behavior contradicts target spec.",
            )
        ),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )
    negated_contradiction = classify(
        pr=_pr(
            _body(
                "- [x] No owner-doc change implied.",
                "Implemented SBI-1. This does not conflict with target spec.",
            )
        ),
        files_payload=["app/runtime.py"],
        issue={"number": 3217},
    )

    assert ordinary_spec_reference.impact_classification == "docs_update_likely"
    assert explicit_contradiction.impact_classification == "human_exception_likely"
    assert negated_contradiction.impact_classification == "docs_update_likely"


def test_runtime_scripts_are_not_whitelisted_as_governance_only() -> None:
    result = classify(
        pr=_pr(_body("- [x] No owner-doc change implied.")),
        files_payload=["scripts/deploy_channel.sh"],
        issue={"number": 3217},
    )

    assert result.impact_classification == "docs_update_likely"
    assert "changed files are governance/tooling surfaces" not in result.evidence
