from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import review_before_ci_gate as review_gate


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "review_before_ci_gate.py"

HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40
WORKFLOW_PATH = ".github/workflows/ci-smoke.yaml"
PR_HOT_PATH = MODULE_PATH.parents[1] / "docs" / "development" / "PR_HOT_PATH.md"


def _diff(*lines: str) -> str:
    return "\n".join(
        [
            "diff --git a/.github/workflows/ci-smoke.yaml b/.github/workflows/ci-smoke.yaml",
            "index 1111111..2222222 100644",
            "--- a/.github/workflows/ci-smoke.yaml",
            "+++ b/.github/workflows/ci-smoke.yaml",
            "@@ -1,4 +1,4 @@",
            *lines,
            "",
        ]
    )


def _passing_receipt(workflow_diff: str, inferred_risks: list[str]) -> dict[str, object]:
    receipt = review_gate.build_workflow_review_receipt_template(
        head_sha=HEAD_SHA,
        base_sha=BASE_SHA,
        workflow_diff=workflow_diff,
        inferred_risks=inferred_risks,
    )
    receipt["verdict"] = "pass"
    receipt["reviewer"] = "independent-sol-review"
    receipt["scenarios"] = {
        name: "pass" for name in review_gate.WORKFLOW_REVIEW_SCENARIOS
    }
    return receipt


def _evaluate(workflow_diff: str, **overrides: object):
    params: dict[str, object] = {
        "lane": "governance",
        "changed_files": [WORKFLOW_PATH],
        "risk_assessment_complete": True,
        "workflow_diff": workflow_diff,
        "head_sha": HEAD_SHA,
        "base_sha": BASE_SHA,
    }
    params.update(overrides)
    return review_gate.evaluate_review_before_ci_gate(**params)


def test_workflow_concurrency_diff_infers_risk_without_manual_declaration() -> None:
    workflow_diff = _diff(
        " concurrency:",
        "-  group: ci-smoke-${{ github.ref }}",
        "+  group: ci-smoke-${{ github.event_name }}-${{ github.ref }}",
        "   cancel-in-progress: true",
    )

    result = _evaluate(workflow_diff)

    assert result.declared_risk_surfaces == []
    assert result.inferred_risk_surfaces == ["concurrency"]
    assert "risk:concurrency" in result.matched_surfaces
    assert result.workflow_review_receipt_required is True
    assert result.may_handoff_to_ci is False


def test_workflow_event_admission_diff_infers_state_machine_risk() -> None:
    trigger_diff = _diff(
        " on:",
        "   pull_request:",
        "-    types: [opened, synchronize, reopened]",
        "+    types: [opened, synchronize, reopened, edited]",
    )
    admission_diff = _diff(
        " jobs:",
        "   unit:",
        "-    if: github.event_name == 'pull_request'",
        "+    if: github.event.action != 'edited' || github.event.changes.base.ref.from != null",
    )

    assert _evaluate(trigger_diff).inferred_risk_surfaces == ["state-machine"]
    assert _evaluate(admission_diff).inferred_risk_surfaces == ["state-machine"]


def test_inferred_workflow_risk_cannot_be_suppressed_by_declared_input() -> None:
    workflow_diff = _diff(
        " concurrency:",
        "-  cancel-in-progress: false",
        "+  cancel-in-progress: true",
        " jobs:",
        "   unit:",
        "+    if: github.event.action != 'edited'",
    )

    result = _evaluate(workflow_diff, risk_surfaces=["security"])

    assert result.declared_risk_surfaces == ["security"]
    assert result.inferred_risk_surfaces == ["concurrency", "state-machine"]
    assert {item for item in result.matched_surfaces if item.startswith("risk:")} == {
        "risk:concurrency",
        "risk:security",
        "risk:state-machine",
    }


def test_inferred_workflow_risk_requires_exact_bound_review_receipt() -> None:
    workflow_diff = _diff(
        " concurrency:",
        "-  group: ci-${{ github.ref }}",
        "+  group: ci-${{ github.event_name }}-${{ github.ref }}",
    )
    without_receipt = _evaluate(workflow_diff, review_gate_complete=True)
    receipt = _passing_receipt(workflow_diff, ["concurrency"])
    with_receipt = _evaluate(
        workflow_diff,
        review_gate_complete=True,
        workflow_review_receipt=receipt,
    )

    assert without_receipt.status == "required"
    assert without_receipt.review_gate_complete is True
    assert without_receipt.workflow_review_receipt_valid is False
    assert "workflow review receipt is required" in without_receipt.workflow_review_receipt_errors
    assert without_receipt.may_handoff_to_ci is False

    assert with_receipt.status == "satisfied"
    assert with_receipt.workflow_review_receipt_valid is True
    assert with_receipt.workflow_review_receipt_errors == []
    assert with_receipt.may_handoff_to_ci is True
    assert with_receipt.preserves_ci_authority is True


@pytest.mark.parametrize(
    "mutator, expected_error",
    [
        (lambda receipt: receipt.__setitem__("head_sha", "c" * 40), "head_sha"),
        (lambda receipt: receipt.__setitem__("base_sha", "c" * 40), "base_sha"),
        (lambda receipt: receipt.__setitem__("diff_sha256", "0" * 64), "diff_sha256"),
        (lambda receipt: receipt.__setitem__("verdict", "blocking"), "verdict"),
        (
            lambda receipt: receipt["scenarios"].pop("base_ref_retarget"),
            "closed workflow scenario set",
        ),
        (
            lambda receipt: receipt["scenarios"].__setitem__("same_sha_rerun", "pending"),
            "not all pass",
        ),
        (lambda receipt: receipt.__setitem__("contract", "wrong.v1"), "contract"),
    ],
)
def test_workflow_review_receipt_rejects_stale_or_incomplete_evidence(
    mutator, expected_error: str
) -> None:
    workflow_diff = _diff(
        " concurrency:",
        "-  cancel-in-progress: false",
        "+  cancel-in-progress: true",
    )
    receipt = _passing_receipt(workflow_diff, ["concurrency"])
    mutator(receipt)

    result = _evaluate(
        workflow_diff,
        review_gate_complete=True,
        workflow_review_receipt=receipt,
    )

    assert result.may_handoff_to_ci is False
    assert result.workflow_review_receipt_valid is False
    assert any(expected_error in error for error in result.workflow_review_receipt_errors)


def test_nonsemantic_workflow_edit_does_not_overclassify_risk() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   lint:",
        "-    name: Lint source",
        "+    name: Lint source and tests",
        "     steps:",
        "-      - run: echo ${{ github.ref }}",
        "+      - run: echo ref=${{ github.ref }}",
    )

    result = _evaluate(workflow_diff, review_gate_complete=True)

    assert result.inferred_risk_surfaces == []
    assert result.workflow_review_receipt_required is False
    assert result.may_handoff_to_ci is True


def test_explicit_high_risk_flow_remains_compatible_without_workflow_receipt() -> None:
    result = review_gate.evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/oauth/service.py", "tests/oauth/test_service.py"],
        risk_surfaces=["auth", "state-machine"],
        risk_assessment_complete=True,
        review_gate_complete=True,
    )

    assert result.declared_risk_surfaces == ["auth", "state-machine"]
    assert result.inferred_risk_surfaces == []
    assert result.workflow_review_receipt_required is False
    assert result.workflow_review_receipt_valid is False
    assert result.may_handoff_to_ci is True


def test_review_before_ci_owner_guidance_preserves_final_authority() -> None:
    script = " ".join(MODULE_PATH.read_text(encoding="utf-8").split())
    owner_doc = " ".join(PR_HOT_PATH.read_text(encoding="utf-8").split())

    assert "actual `origin/main...HEAD` patch" in owner_doc
    assert "cannot be suppressed" in owner_doc
    assert "review-before-ci-workflow-risk.v1" in owner_doc
    assert "current-head hosted CI" in script and "current-head hosted CI" in owner_doc
    assert "final independent review" in script and "final independent review" in owner_doc
    assert "ordering evidence only" in script and "ordering evidence only" in owner_doc
    assert "never merge authority" not in script + owner_doc


def test_flow_style_pull_request_trigger_infers_state_machine_risk() -> None:
    workflow_diff = _diff(
        "-on: [push]",
        "+on: [push, pull_request]",
        " jobs:",
        "   lint:",
    )

    assert _evaluate(workflow_diff).inferred_risk_surfaces == ["state-machine"]


def test_multiline_concurrency_group_value_infers_concurrency_risk() -> None:
    workflow_diff = _diff(
        " concurrency:",
        "   group: >-",
        "-    ci-${{ github.ref }}",
        "+    ci-${{ github.event_name }}-${{ github.ref }}",
        "   cancel-in-progress: true",
    )

    assert _evaluate(workflow_diff).inferred_risk_surfaces == ["concurrency"]


def test_unrelated_change_near_concurrency_block_does_not_overclassify() -> None:
    workflow_diff = _diff(
        " concurrency:",
        "   group: ci-${{ github.ref }}",
        " jobs:",
        "   lint:",
        "-    name: Lint source",
        "+    name: Lint source and tests",
    )

    assert _evaluate(workflow_diff, review_gate_complete=True).inferred_risk_surfaces == []


def test_event_reference_in_run_step_below_unchanged_if_is_not_admission() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   lint:",
        "     if: github.event_name == 'pull_request'",
        "     steps:",
        "-      - run: echo ${{ github.ref }}",
        "+      - run: echo ref=${{ github.ref }}",
    )

    assert _evaluate(workflow_diff, review_gate_complete=True).inferred_risk_surfaces == []


def test_multiline_event_admission_value_infers_state_machine_risk() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   lint:",
        "     if: >-",
        "-      github.event.action != 'edited'",
        "+      github.event.action != 'edited' || github.event.changes.base.ref.from != null",
    )

    assert _evaluate(workflow_diff).inferred_risk_surfaces == ["state-machine"]


def test_group_key_outside_concurrency_does_not_overclassify() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   publish:",
        "     steps:",
        "       - uses: example/action@v1",
        "         with:",
        "-          group: artifacts-a",
        "+          group: artifacts-b",
    )

    assert _evaluate(workflow_diff, review_gate_complete=True).inferred_risk_surfaces == []


def test_pull_request_branch_and_path_filters_infer_state_machine_risk() -> None:
    branches_diff = _diff(
        " on:",
        "   pull_request:",
        "-    branches: [main]",
        "+    branches: [main, stable]",
    )
    paths_diff = _diff(
        " on:",
        "   pull_request:",
        "     paths:",
        "-      - app/**",
        "+      - app/**",
        "+      - scripts/**",
    )

    assert _evaluate(branches_diff).inferred_risk_surfaces == ["state-machine"]
    assert _evaluate(paths_diff).inferred_risk_surfaces == ["state-machine"]


def test_pull_request_like_key_outside_on_does_not_overclassify() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   inspect:",
        "     steps:",
        "       - uses: example/action@v1",
        "         with:",
        "-          pull_request: 10",
        "+          pull_request: 11",
    )

    assert _evaluate(workflow_diff, review_gate_complete=True).inferred_risk_surfaces == []


def test_changed_multiline_if_does_not_capture_event_reference_from_run_step() -> None:
    workflow_diff = _diff(
        " jobs:",
        "   lint:",
        "-    if: >-",
        "+    if: |",
        "       always()",
        "     steps:",
        "       - run: echo ${{ github.ref }}",
    )

    assert _evaluate(workflow_diff, review_gate_complete=True).inferred_risk_surfaces == []


@pytest.mark.parametrize("override", ["--diff-file", "--head-sha", "--base-sha", "--base-ref"])
def test_cli_rejects_workflow_evidence_overrides(override: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        review_gate._parser().parse_args(
            ["--lane", "governance", "--changed-file", WORKFLOW_PATH, override, "ignored"]
        )

    assert exc_info.value.code == 2


def test_cli_derives_workflow_paths_when_caller_omits_them(monkeypatch, capsys) -> None:
    workflow_diff = _diff(
        " concurrency:",
        "-  cancel-in-progress: false",
        "+  cancel-in-progress: true",
    )

    def fake_git_output(args: list[str]) -> str:
        if args[:2] == ["diff", "--name-only"]:
            return WORKFLOW_PATH
        if args[:2] == ["diff", "--no-ext-diff"]:
            return workflow_diff
        if args == ["rev-parse", "HEAD"]:
            return HEAD_SHA
        if args == ["rev-parse", review_gate.CANONICAL_WORKFLOW_BASE_REF]:
            return BASE_SHA
        raise AssertionError(f"unexpected Git command: {args}")

    monkeypatch.setattr(review_gate, "_git_output", fake_git_output)

    exit_code = review_gate.main(
        [
            "--lane",
            "governance",
            "--changed-file",
            "scripts/unrelated.py",
            "--risk-assessment-complete",
            "--review-gate-complete",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["inferred_risk_surfaces"] == ["concurrency"]
    assert payload["workflow_review_receipt_required"] is True
    assert payload["may_handoff_to_ci"] is False
