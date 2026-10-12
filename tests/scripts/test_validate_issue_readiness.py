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


def test_rejects_literal_newline_escaped_headings() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace("\n## SBS Impact", r"\n## SBS Impact")

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_required_sections"
    assert "SBS Impact" in report.required_sections.missing


def test_missing_verify_reports_exact_item_guidance() -> None:
    body = (FIXTURE_DIR / "ac_without_verify.md").read_text(encoding="utf-8")

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker identifies acceptance criteria without verify markers."
    ]
    assert "acceptance criteria without verify markers" in report.repair_guidance[-1]


def test_ready_issue_accepts_new_behavioral_verify_test_file() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "tests/scripts/test_new_readiness_case.py::test_new_readiness_case",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_ready_issue_rejects_missing_root_level_verify_file_path() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "pyproject.tmol::missing_target",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == ["pyproject.tmol"]


def test_ready_issue_rejects_missing_non_behavioral_verify_file_path() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "doc writeback at `docs/missing-readiness-guidance.md :: verify-rule`",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == [
        "docs/missing-readiness-guidance.md"
    ]
    assert "non-test file-based" in report.repair_guidance[0]


def test_prose_prefixed_backticked_verify_path_resolves() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        (
            "doc writeback at `docs/development/DEV_WORKFLOW.md :: "
            "Acceptance verifiability` (step 3)"
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_backticked_missing_verify_path_still_rejected() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "doc writeback at `docs/missing-readiness-guidance.md :: verify-rule` (step 3)",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == [
        "docs/missing-readiness-guidance.md"
    ]


def test_joined_verify_targets_report_the_actual_cause() -> None:
    """A joined multi-target `Verify:` line gets a split hint, not just
    "file not found" for a file that exists (#3857, #3859)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "`tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        "doc writeback at `docs/development/DEV_WORKFLOW.md :: Acceptance verifiability`"
        " + doc writeback at",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == [
        "`docs/development/DEV_WORKFLOW.md"
    ]
    assert report.acceptance_criteria.joined_verify_targets == [
        "doc writeback at `docs/development/DEV_WORKFLOW.md :: Acceptance verifiability`"
        " + doc writeback at"
    ]
    assert any(
        "one `Verify:` line per target" in item for item in report.repair_guidance
    )


def test_multiple_verify_lines_on_one_ac_stay_one_acceptance_item() -> None:
    """Several targets split one per `Verify:` line do not raise the AC count."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "  - Verify: `tests/governance/test_issue_pr_governance.py"
        "::test_issue_readiness_workflow_is_strict_for_agent_ready_only`",
        "  - Verify: `tests/governance/test_issue_pr_governance.py"
        "::test_issue_readiness_workflow_is_strict_for_agent_ready_only`\n"
        "  - Verify: doc writeback at `docs/development/DEV_WORKFLOW.md"
        " :: Acceptance verifiability`",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.count == 2
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_ready_issue_accepts_existing_verify_file_path() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_readiness_accepts_real_path_containing_vague_authority_token() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        (
            "tests/architecture/test_pr_hot_path_governance.py::"
            "test_hot_path_doc_defers_escalation_and_names_direct_repair_contract"
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_readiness_still_rejects_nonexistent_path_with_vague_token() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "tests/architecture/test_nonexistent_hot_path_thing.py::test_x",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == [
        "tests/architecture/test_nonexistent_hot_path_thing.py"
    ]


def test_ready_issue_accepts_existing_root_level_verify_file_path() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "pyproject.toml::test_new_readiness_case",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_ready_issue_does_not_require_future_verify_test_function() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        "tests/scripts/test_validate_issue_readiness.py::test_new_readiness_case",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"


@pytest.mark.parametrize(
    "verify_path",
    [
        "/tests/scripts/test_validate_issue_readiness.py",
        "../tests/scripts/test_validate_issue_readiness.py",
    ],
)
def test_ready_issue_rejects_non_repo_relative_verify_file_path(verify_path: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
        f"{verify_path}::test_fixture_classifications",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"


def test_diff_of_file_target_is_concrete() -> None:
    """Contract-legal workflow-diff targets are concrete observables (#4464);
    the #4448-shaped body classifies ready_candidate."""
    body = (FIXTURE_DIR / "nonbehavioral_verify_targets.md").read_text(encoding="utf-8")

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_items == []
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_diff_of_file_target_requires_existing_file() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "`tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        "diff of `.github/workflows/does-not-exist.yml` adding a lane step",
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "missing_verify_file_paths"
    assert report.acceptance_criteria.missing_verify_file_paths == [
        ".github/workflows/does-not-exist.yml"
    ]


def test_marker_presence_target_is_concrete() -> None:
    """A backticked literal asserted present in a durable repo file is a
    concrete observable (#4464, #4448 AC shape)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        (
            "Verify: `pytestmark = pytest.mark.browser_runtime` present in "
            "`tests/companion_ui/test_cockpit_journeys.py`, deselected by the "
            "PR marker expression in `scripts/select_pr_tests.py`"
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_trailing_prose_annotation_is_concrete() -> None:
    """A backticked canonical target followed by explanatory prose stays
    concrete, and path extraction carries no backtick residue (#4464)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        (
            "Verify: `tests/scripts/test_validate_issue_readiness.py::"
            "test_fixture_classifications` (enforcement: exercises the "
            "production `classify_issue_body` call site)"
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_annotated_repo_anchor_target_is_concrete() -> None:
    """The canonical DEV_WORKFLOW example form — a backticked repo anchor plus
    'removed or rewritten as delivered.' — is concrete (#4464)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        (
            "Verify: `docs/development/DEV_WORKFLOW.md :: Acceptance "
            "verifiability` removed or rewritten as delivered."
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


@pytest.mark.parametrize(
    "target",
    [
        "diff of uncommitted local changes",
        "`some marker` present in the deployed environment",
        "`` present in `tests/scripts/test_validate_issue_readiness.py`",
        "diff of `<workflow file>` adding a step",
        "`<marker>` present in `tests/scripts/test_validate_issue_readiness.py`",
    ],
)
def test_unresolvable_target_still_rejected(target: str) -> None:
    """Extending the grammar (#4464) must not admit genuinely unresolvable
    targets: no durable repo path, placeholder tokens, or prose-only claims."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        f"Verify: {target}",
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


def test_inline_tail_marker_with_resolvable_target_is_declared() -> None:
    """The inline tail form (`- [ ] text. Verify: <target>`) used by the
    model-inquiry proposal contract stays a declared marker (#4464)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        (
            "- [ ] The checker reports a ready candidate for canonical issue bodies.\n"
            "  - Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`"
        ),
        (
            "- [ ] The seam is deterministic. Verify: "
            "`tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`"
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


def test_inline_marker_mention_in_prose_is_not_a_target() -> None:
    """A mid-line mention inside AC prose whose tail is not a resolvable
    target is not parsed as a marker declaration (#4464)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "- [ ] The checker reports a ready candidate for canonical issue bodies.",
        (
            "- [ ] The checker accepts ACs whose prose mentions the "
            "Verify: marker grammar without carrying a second target."
        ),
    )

    report = classify_issue_body(body, labels=["agent:ready"])

    assert report.readiness_classification == "ready_candidate"
    assert report.acceptance_criteria.missing_verify_file_paths == []


@pytest.mark.parametrize("target", ["<test pointer>", "none", "n/a", "TBD"])
def test_placeholder_verify_targets_are_not_concrete(target: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        f"Verify: {target}",
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


@pytest.mark.parametrize(
    "target",
    [
        "tests/<module>/test_<name>.py::test_<case>",
        "doc writeback at docs/<PATH>.md :: <anchor>",
    ],
)
def test_template_shaped_verify_targets_are_not_concrete(target: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        f"Verify: {target}",
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


@pytest.mark.parametrize(
    "target",
    [
        "manual QA",
        "tests/scripts/test_validate_issue_readiness.py",
        "runtime receipt: delivery_receipt",
        "doc writeback at docs/STATUS.md",
    ],
)
def test_readiness_rejects_verify_targets_without_resolvable_authority(
    target: str,
) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(
        encoding="utf-8"
    )
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        f"Verify: {target}",
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


@pytest.mark.parametrize("invalid_target", ["manual QA", ""])
def test_readiness_rejects_mixed_resolvable_verify_markers(
    invalid_target: str,
) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(
        encoding="utf-8"
    )
    body = body.replace(
        "Verify: `tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`",
        (
            "Verify: "
            "`tests/scripts/test_validate_issue_readiness.py::"
            "test_fixture_classifications`\n"
            f"  Verify: {invalid_target}"
        ),
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


def test_readiness_rejects_duplicate_resolvable_verify_markers() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(
        encoding="utf-8"
    )
    marker = (
        "Verify: `tests/scripts/test_validate_issue_readiness.py::"
        "test_fixture_classifications`"
    )
    body = body.replace(marker, f"{marker}\n  {marker}")

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_verify_markers"
    assert report.acceptance_criteria.missing_verify_items == [
        "- [ ] The checker reports a ready candidate for canonical issue bodies."
    ]


@pytest.mark.parametrize("source_docs", ["- <path>", "- `<path>`", "- `docs/<path>.md`", "- TBD"])
def test_placeholder_source_docs_are_missing(source_docs: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
    body = body.replace(
        "## Source Docs\n- `.codex/skills/_shared/ISSUE_CONTRACT.md`\n- `.github/workflows/issue-pr-governance.yml`",
        f"## Source Docs\n{source_docs}",
    )

    report = classify_issue_body(body)

    assert report.readiness_classification == "missing_source_docs"
    assert report.source_docs_present is False
    assert report.source_docs_missing is True


def test_blocked_or_needs_human_labels_are_not_agentable() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    blocked = classify_issue_body(body, labels=["agent:blocked"])
    needs_human = classify_issue_body(body, labels=["agent:needs-human"])

    assert blocked.readiness_classification == "not_agentable"
    assert blocked.human_exception_required is False
    assert needs_human.readiness_classification == "not_agentable"
    assert needs_human.human_exception_required is True


@pytest.mark.parametrize("fixture,labels,extra", [
    ("valid_ready_candidate.md", ["agent:blocked"], ""),
    ("legacy_malformed_body.md", [], ""),
    ("ambiguous_intent.md", [], ""),
    ("valid_ready_candidate.md", [], "\nBlocked until CI evidence is restored."),
    ("valid_ready_candidate.md", [], "\nDo not pick up before dependency delivery."),
])
def test_technical_unreadiness_does_not_require_human(fixture, labels, extra) -> None:
    report = classify_issue_body((FIXTURE_DIR / fixture).read_text() + extra, labels=labels)
    assert report.readiness_classification != "ready_candidate"
    assert report.human_exception_required is False
    assert report.repair_guidance


@pytest.mark.parametrize("extra", ["", "\nHuman only.", "\nOperator gated.", "\nRequires an owner decision."])
@pytest.mark.parametrize("fixture", ["valid_ready_candidate.md", "legacy_malformed_body.md"])
def test_explicit_human_evidence_survives_technical_unreadiness(extra, fixture) -> None:
    labels = ["agent:blocked"] if extra else ["agent:needs-human"]
    report = classify_issue_body((FIXTURE_DIR / fixture).read_text() + extra, labels=labels)
    assert report.readiness_classification != "ready_candidate"
    assert report.human_exception_required is True


@pytest.mark.parametrize("hold", [
    "Requires operator UAT.", "Waiting for live/operator acceptance.", "Needs manual acceptance.",
    "UAT is required before closure.", "Requires UAT.", "Live acceptance is required.",
    "A human must run the acceptance test.",
])
def test_generic_acceptance_hold_is_builder_repair_not_human_decision(hold: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body = body.replace("## Suggested Validation", f"## Validation / Acceptance Path\n{hold}\n\n## Suggested Validation")
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ambiguous_intent"
    assert report.human_exception_required is False
    assert any("qualified automated TEST proof" in item for item in report.repair_guidance)


def test_body_only_validator_keeps_human_hold_until_receipt_reconciliation() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.readiness_classification == "not_agentable"
    assert report.human_exception_required is True
    assert any("action:restore-environment" in item for item in report.repair_guidance)
    assert any("latest blocker receipt" in item for item in report.repair_guidance)
    assert not any("Replace generic" in item for item in report.repair_guidance)


_HUMAN_ACCEPTANCE_EXCEPTION = (
    "\nHuman acceptance exception: personal accessibility preference.\n"
    "Observable choice: owner selects the comfortable spoken cadence.\n"
    "Cannot be automated because: only the owner can report their listening experience.\n"
    "Owner: owner\n"
    "unblocks_when: the owner records the chosen cadence on this Issue.\n"
)


def _with_current_exception(body: str, exception: str = _HUMAN_ACCEPTANCE_EXCEPTION) -> str:
    return body.replace("## Acceptance Criteria", exception + "\n## Acceptance Criteria")


def test_specific_human_acceptance_exception_preserves_human_gate() -> None:
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text())
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.readiness_classification == "not_agentable"
    assert report.human_exception_required is True
    assert not any("Replace generic" in item for item in report.repair_guidance)
    body += "\n## Validation / Acceptance Path\nRequires human acceptance."
    assert classify_issue_body(body, labels=["agent:ready"]).readiness_classification == "not_agentable"


def test_retained_exception_history_without_a_current_hold_does_not_block_ready() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text() + _HUMAN_ACCEPTANCE_EXCEPTION
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ready_candidate"
    assert report.human_exception_required is False


@pytest.mark.parametrize("missing_fact", _HUMAN_ACCEPTANCE_EXCEPTION.strip().splitlines()[1:])
def test_incomplete_human_acceptance_exception_requires_concrete_repair(missing_fact: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body = _with_current_exception(body, _HUMAN_ACCEPTANCE_EXCEPTION.replace(missing_fact, ""))
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.human_exception_required is True
    assert report.readiness_classification == "not_agentable"
    assert any("observable choice/observation" in item for item in report.repair_guidance)


def test_technical_acceptance_lint_does_not_weaken_separate_authority_gate() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text() + "\nRequires an owner decision."
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.human_exception_required is True
    assert report.readiness_classification == "not_agentable"
    report = classify_issue_body(body, labels=["action:human-acceptance"])
    assert report.human_exception_required is True
    assert report.readiness_classification == "authority_risk"


@pytest.mark.parametrize("value", ["", "<name>", "TBD", "none"])
def test_placeholder_human_exception_fact_requires_body_repair(value: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body = _with_current_exception(body, _HUMAN_ACCEPTANCE_EXCEPTION.replace("Owner: owner", f"Owner: {value}"))
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.human_exception_required is True
    assert report.readiness_classification == "not_agentable"
    assert any("Issue body" in item for item in report.repair_guidance)


def test_explicit_no_manual_acceptance_default_is_not_rejected() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += "\n## Validation / Acceptance Path\nDoes not require operator UAT."
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ready_candidate"
    assert report.human_exception_required is False


@pytest.mark.parametrize("line", [
    "Automated UAT is required before closure.", "Scripted UAT is required.",
    "Requires automated UAT in TEST.", "The checker rejects `Requires UAT` as a bare hold.",
])
def test_automatic_uat_and_quoted_examples_are_not_manual_holds(line: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += f"\n## Validation / Acceptance Path\n{line}"
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ready_candidate"
    assert report.human_exception_required is False


def test_human_need_and_automated_acceptance_do_not_create_manual_gate() -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += "\nHuman-need acceptance uses qualified automatic TEST journeys and synthetic actors."
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ready_candidate"
    assert report.human_exception_required is False


@pytest.mark.parametrize("hold", [
    "Requires **operator UAT** before closure.", "Requires `operator UAT` before closure.",
    "Requires ``operator UAT`` before closure.", "Requires ```operator UAT``` before closure.",
    "__UAT__ is required before closure.", "A **human** must run the acceptance test.",
    "Requires [operator UAT](https://example.test/acceptance) before closure.",
    "Requires [operator UAT][walkthrough] before closure.",
    "Requires <strong>operator UAT</strong> before closure.",
])
def test_markdown_manual_acceptance_hold_is_not_ready(hold: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += f"\n## Validation / Acceptance Path\n- {hold}"
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ambiguous_intent"
    assert report.human_exception_required is False


@pytest.mark.parametrize("section", [
    "Scope", "Constraints", "Acceptance Criteria", "Validation / Acceptance Path", "Suggested Validation",
])
def test_current_acceptance_descendants_cannot_hide_manual_hold(section: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += f"\n## {section}\n### Required live acceptance\nRequires **operator UAT**."
    for mode in (True, False):
        report = classify_issue_body(body, labels=["agent:ready"], _resolve_verify_files=mode)
        assert report.readiness_classification == "ambiguous_intent"
        assert report.human_exception_required is False


@pytest.mark.parametrize("prefix", ["", "- ", "- [ ] ", "1. "])
def test_nested_current_human_choice_stays_held_without_labels(prefix: str) -> None:
    body = _with_current_exception(
        (FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        "### Current human acceptance\n" + _HUMAN_ACCEPTANCE_EXCEPTION.replace(
            "Human acceptance exception:", prefix + "Human acceptance exception:"),
    )
    for mode in (True, False):
        report = classify_issue_body(body, labels=["agent:ready"], _resolve_verify_files=mode)
        assert report.readiness_classification == "not_agentable"
        assert report.human_exception_required is True


@pytest.mark.parametrize("completion", [
    "- Resolution: cadence chosen and completed.", "* Status: completed.",
    "Resolution: cadence chosen and completed.",
    "Human acceptance exception: prior cadence decision resolved and completed.",
    "Human acceptance exception: cadence selected; Status: completed.",
])
def test_completed_exception_format_cannot_supply_current_authority(completion: str) -> None:
    exception = _HUMAN_ACCEPTANCE_EXCEPTION
    if completion.startswith("Human acceptance exception:"):
        exception = exception.replace("Human acceptance exception: personal accessibility preference.", completion)
    else:
        exception += completion + "\n"
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(), exception)
    for mode in (True, False):
        report = classify_issue_body(body, labels=["agent:ready"], _resolve_verify_files=mode)
        assert report.readiness_classification == "ready_candidate"
        assert report.human_exception_required is False
        held = classify_issue_body(body + "\n## Validation / Acceptance Path\nRequires operator UAT.",
                                   labels=["agent:ready"], _resolve_verify_files=mode)
        assert held.readiness_classification == "ambiguous_intent"
        assert held.human_exception_required is False
    labelled = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert labelled.readiness_classification == "not_agentable"
    assert labelled.human_exception_required is True


@pytest.mark.parametrize("status", [
    "- Status: pending until the cadence is chosen; not completed.",
    "- Status: completed when the owner selects a cadence.",
])
def test_current_human_choice_is_not_completed_by_prospective_status(status: str) -> None:
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        _HUMAN_ACCEPTANCE_EXCEPTION + status + "\n")
    assert classify_issue_body(body).human_exception_required is True
    assert classify_issue_body(body).readiness_classification == "not_agentable"


@pytest.mark.parametrize("topic", [
    "accessibility preference for a completed audio sample.",
    "completed audio sample accessibility preference.",
    "resolved transcript accessibility preference.", "closed audio run accessibility preference.",
    "done audio sample accessibility preference.", "settled audio cache accessibility preference.",
])
def test_completed_sample_does_not_resolve_a_current_human_choice(topic: str) -> None:
    exception = _HUMAN_ACCEPTANCE_EXCEPTION.replace("personal accessibility preference.",
                                                   topic).replace("Human acceptance exception:", "Current human acceptance exception:")
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(), exception)
    for mode in (True, False):
        report = classify_issue_body(body, labels=["agent:ready"], _resolve_verify_files=mode)
        assert report.human_exception_required is True
        assert report.readiness_classification == "not_agentable"
    closed = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
                                    exception + "- Status: completed.\n")
    assert classify_issue_body(closed).readiness_classification == "ready_candidate"
    assert not classify_issue_body(closed).human_exception_required
    titled = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
                                     "### " + topic + "\n" + exception)
    assert classify_issue_body(titled).human_exception_required is True
    assert classify_issue_body(titled).readiness_classification == "not_agentable"


def test_conflicting_choice_status_keeps_the_current_human_condition() -> None:
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        _HUMAN_ACCEPTANCE_EXCEPTION + "- Status: unresolved.\n- Resolution: completed.\n")
    assert classify_issue_body(body).human_exception_required is True
    assert classify_issue_body(body).readiness_classification == "not_agentable"


@pytest.mark.parametrize("heading", [
    "Completed acceptance samples", "Completed audio samples", "Resolved acceptance examples",
    "Closed choices snapshots", "Settled exceptions samples", "Completed decisions", "Resolved human acceptance",
])
@pytest.mark.parametrize("current_marker", [True, False])
def test_scope_topic_cannot_erase_explicitly_unresolved_choice(heading: str, current_marker: bool) -> None:
    exception = _HUMAN_ACCEPTANCE_EXCEPTION.replace("personal accessibility preference.",
        "completed audio sample accessibility preference.")
    if current_marker:
        exception = exception.replace("Human acceptance exception:", "Current human acceptance exception:")
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        f"### {heading}\n" + exception + "- Status: unresolved.\n")
    for mode in (True, False):
        report = classify_issue_body(body, labels=["agent:ready"], _resolve_verify_files=mode)
        assert report.readiness_classification == "not_agentable"
        assert report.human_exception_required is True


def test_closed_scope_cannot_erase_a_current_descendant_requirement() -> None:
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        "### Completed decisions\n#### Current acceptance\nRequires operator UAT.\n")
    assert classify_issue_body(body).readiness_classification == "ambiguous_intent"
    assert not classify_issue_body(body).human_exception_required


@pytest.mark.parametrize("heading", ["Historical decisions", "Completed decisions", "Resolved human acceptance"])
def test_true_history_or_closed_choice_scope_remains_context(heading: str) -> None:
    exception = _HUMAN_ACCEPTANCE_EXCEPTION + "- Status: completed.\n"
    if heading == "Historical decisions":
        exception = exception.replace("Human acceptance exception:", "Current human acceptance exception:").replace(
            "Status: completed", "Status: unresolved")
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text(),
        f"### {heading}\n" + exception)
    assert classify_issue_body(body).readiness_classification == "ready_candidate"
    assert not classify_issue_body(body).human_exception_required


@pytest.mark.parametrize("history_heading", ["Historical acceptance", "**Historical acceptance**", "`Historical acceptance`"])
def test_historical_descendants_and_multi_tick_examples_remain_context(history_heading: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += (f"\n## Validation / Acceptance Path\n### {history_heading}\nRequires ``operator UAT``.\n"
             "### Current automated acceptance\nThe checker rejects ``Requires operator UAT``.\n"
             "```markdown\n## Constraints\nRequires operator UAT.\n```\n")
    assert classify_issue_body(body).readiness_classification == "ready_candidate"
    assert classify_issue_body(body).human_exception_required is False


@pytest.mark.parametrize("target", [
    "docs/TESTING.md::", "doc writeback at `docs/TESTING.md :: later`",
    "`docs/TESTING.md::` (step 3)", "doc writeback at `docs/TESTING.md :: later` (step 3)",
])
def test_file_locator_never_overrides_missing_or_vague_verify_selector(target: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text().replace(
        "`tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications`", target,
    )
    for mode in (True, False):
        assert classify_issue_body(body, _resolve_verify_files=mode).readiness_classification == "missing_verify_markers"


@pytest.mark.parametrize("history", [
    "## Historical decisions\n" + _HUMAN_ACCEPTANCE_EXCEPTION + "Resolution: cadence chosen and completed.",
    "## Constraints\n" + _HUMAN_ACCEPTANCE_EXCEPTION + "Resolution: cadence chosen and completed.",
    "## Source Docs\n" + _HUMAN_ACCEPTANCE_EXCEPTION,
])
def test_historical_or_completed_exception_does_not_justify_current_manual_hold(history: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    body += "\n## Validation / Acceptance Path\nRequires operator UAT.\n" + history
    report = classify_issue_body(body, labels=["agent:ready"])
    assert report.readiness_classification == "ambiguous_intent"
    assert report.human_exception_required is False
    assert any("qualified automated TEST proof" in value for value in report.repair_guidance)


def test_current_exception_cannot_exempt_another_generic_execution_gate() -> None:
    body = _with_current_exception((FIXTURE_DIR / "valid_ready_candidate.md").read_text())
    body += "\n## Validation / Acceptance Path\nRequires operator UAT."
    report = classify_issue_body(body, labels=["agent:needs-human", "action:human-acceptance"])
    assert report.readiness_classification == "not_agentable"
    assert report.human_exception_required is True
    assert any("unsupported generic hold" in value for value in report.repair_guidance)


def test_retained_source_mode_preserves_content_and_separate_file_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_issue_readiness as readiness

    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text()
    def forbidden_file_read(*_args: object) -> bool:
        raise AssertionError("retained-source classification consulted checkout files")
    monkeypatch.setattr(readiness, "_target_has_missing_file_path", forbidden_file_read)
    monkeypatch.setattr(readiness, "_target_has_existing_file_path", forbidden_file_read)
    assert classify_issue_body(body, _resolve_verify_files=False).readiness_classification == "ready_candidate"
    held = body + "\n## Validation / Acceptance Path\nRequires **operator UAT**."
    assert classify_issue_body(held, _resolve_verify_files=False).readiness_classification == "ambiguous_intent"


@pytest.mark.parametrize("target", [
    "doc writeback at `docs/development/DEV_WORKFLOW.md :: Acceptance verifiability` (step 3)",
    "tests/architecture/test_pr_hot_path_governance.py::test_hot_path_doc_defers_escalation_and_names_direct_repair_contract",
])
def test_file_resolution_mode_does_not_change_authority_target_grammar(target: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text().replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications", target,
    )
    for mode in (True, False):
        assert classify_issue_body(body, _resolve_verify_files=mode).readiness_classification == "ready_candidate"


@pytest.mark.parametrize("target", ["../outside.md::criterion", "/tmp/criterion.md::criterion"])
def test_retained_source_mode_does_not_bypass_unsafe_target_shape(target: str) -> None:
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text().replace(
        "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications", target,
    )
    for mode in (True, False):
        assert classify_issue_body(body, _resolve_verify_files=mode).readiness_classification != "ready_candidate"


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


def test_cli_succeeds_ready_candidate_without_observe_only() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_issue_readiness.py",
            "--body-file",
            str(FIXTURE_DIR / "valid_ready_candidate.md"),
            "--label",
            "agent:ready",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["readiness_classification"] == "ready_candidate"


@pytest.mark.parametrize(
    ("fixture_name", "expected_classification"),
    [
        ("missing_constraints.md", "missing_required_sections"),
        ("ac_without_verify.md", "missing_verify_markers"),
    ],
)
def test_cli_fails_non_ready_without_observe_only(
    fixture_name: str,
    expected_classification: str,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_issue_readiness.py",
            "--body-file",
            str(FIXTURE_DIR / fixture_name),
            "--label",
            "agent:ready",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["readiness_classification"] == expected_classification


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


def test_declared_parent_reference_must_be_machine_parseable() -> None:
    """A declared child->parent reference must be exactly one canonical
    ``Parent: #<N>`` line (INV-DG-3, #4443)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    canonical = body + "\nParent: #4447\n"
    report = classify_issue_body(canonical, issue_number=1, labels=["type:task"])
    assert report.readiness_classification == "ready_candidate"

    for malformed_line in (
        "Parent: **#4447**",
        "Parent: #4447 and #4448",
        "Parent: see #4447",
    ):
        report = classify_issue_body(
            body + f"\n{malformed_line}\n", issue_number=1, labels=["type:task"]
        )
        assert report.readiness_classification == "malformed_parent_reference", malformed_line
        assert any("Parent: #<N>" in item for item in report.repair_guidance)

    duplicated = body + "\nParent: #4447\nParent: #4448\n"
    report = classify_issue_body(duplicated, issue_number=1, labels=["type:task"])
    assert report.readiness_classification == "malformed_parent_reference"


def test_body_without_parent_reference_stays_ready() -> None:
    """Orphan slices (no declared parent) remain valid, including legacy
    prose like ``Parent feature issue: #N`` that is not the declaration
    grammar (#4443)."""
    body = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")

    report = classify_issue_body(body, issue_number=1, labels=["type:task"])
    assert report.readiness_classification == "ready_candidate"

    legacy_prose = body + "\nParent feature issue: #3325 (validation hub).\n"
    report = classify_issue_body(legacy_prose, issue_number=1, labels=["type:task"])
    assert report.readiness_classification == "ready_candidate"

    descriptive_no_number = body + "\nParent: the governing validation hub for this track.\n"
    report = classify_issue_body(descriptive_no_number, issue_number=1, labels=["type:task"])
    assert report.readiness_classification == "ready_candidate"
