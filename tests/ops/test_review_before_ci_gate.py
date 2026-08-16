from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.review_before_ci_gate import (
    ReviewBeforeCiGateError,
    evaluate_review_before_ci_gate,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_PR_SKILL = REPO_ROOT / ".codex/skills/publish-pr/SKILL.md"
ISSUE_TO_CODE_SKILL = REPO_ROOT / ".codex/skills/issue-to-code/SKILL.md"
VERIFICATION_SKILL = REPO_ROOT / ".codex/skills/verification-and-closure/SKILL.md"
REVIEW_REPAIR_CONTRACT = (
    REPO_ROOT / "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md"
)
DEV_WORKFLOW = REPO_ROOT / "docs/development/DEV_WORKFLOW.md"
PROCESS_MAP = REPO_ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"
DISPATCHER_CONTRACT = REPO_ROOT / "docs/AGENT_ISSUE_DISPATCHER.md"
AGENTS = REPO_ROOT / "AGENTS.md"
PR_HOT_PATH = REPO_ROOT / "docs/development/PR_HOT_PATH.md"
PR_ESCALATION_PATHS = REPO_ROOT / "docs/development/PR_ESCALATION_PATHS.md"
VERIFICATION_AGENT_LOOP = REPO_ROOT / "app/dispatcher/verification_agent_loop.py"
PR_INTEGRATION_SKILL = REPO_ROOT / ".codex/skills/pr-integration/SKILL.md"


def test_rejects_stale_workflow_review_receipt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "config", "user.name", "test"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    workflow = repo / ".github/workflows/check.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: check\n'on': push\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    workflow.write_text("name: check\n'on': pull_request\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "reviewed", "-q"], cwd=repo, check=True)
    reviewed_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    from scripts.workflow_review_risk import workflow_risk_evidence_from_git

    evidence = workflow_risk_evidence_from_git(repo, base=base, head=reviewed_head)
    receipt_path = repo / "receipt.json"
    receipt_path.write_text(
        json.dumps(
            {
                "version": 1,
                "base_sha": evidence.base_sha,
                "head_sha": evidence.head_sha,
                "diff_digest": evidence.diff_digest,
                "risks": list(evidence.risks),
                "verdict": "pass",
                "reviewer": "independent reviewer",
                "scenario_matrix_complete": True,
            }
        ),
        encoding="utf-8",
    )
    workflow.write_text(
        "name: check\n'on': {push: {}, pull_request: {}}\n", encoding="utf-8"
    )
    subprocess.run(["git", "commit", "-am", "stale receipt", "-q"], cwd=repo, check=True)

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/review_before_ci_gate.py"),
            "--lane",
            "governance",
            "--changed-file",
            ".github/workflows/check.yml",
            "--risk-assessment-complete",
            "--review-gate-complete",
            "--workflow-risk-base",
            base,
            "--workflow-review-receipt",
            str(receipt_path),
        ],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "head_sha" in result.stderr


def _bare_repo_wide_not_pg_commands(text: str) -> list[str]:
    commands: list[str] = []
    control_characters = frozenset(";&|()")
    harmless_prefix_flags = frozenset(
        {"-q", "--quiet", "-s", "-x", "--exitfirst", "--lf", "--ff", "--nf", "--sw"}
    )

    def is_leased(tokens: list[str], pytest_index: int) -> bool:
        prefix = tokens[:pytest_index]
        command_start = 0
        while command_start < len(prefix) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", prefix[command_start]
        ):
            command_start += 1
        if prefix[command_start : command_start + 2] not in (
            ["python", "scripts/run_with_host_lease.py"],
            ["python3", "scripts/run_with_host_lease.py"],
        ):
            return False
        wrapper_args = prefix[command_start + 2 :]
        if "--" not in wrapper_args:
            return False
        lease_args = wrapper_args[: wrapper_args.index("--")]
        resource_values: list[str] = []
        for index, token in enumerate(lease_args):
            if token == "--resource":
                if index + 1 >= len(lease_args):
                    return False
                resource_values.append(lease_args[index + 1])
            elif token.startswith("--resource="):
                resource_values.append(token.partition("=")[2])
        return resource_values == ["pytest-not-pg"]

    def is_safely_targeted(pytest_args: list[str]) -> bool:
        targets: list[str] = []
        index = 0
        while index < len(pytest_args):
            token = pytest_args[index]
            if token == "-m":
                if index + 1 >= len(pytest_args):
                    return False
                index += 2
                continue
            if token.startswith("-m="):
                index += 1
                continue
            if token.startswith("-") and not token.startswith("--") and "m" in token:
                if token.endswith("m"):
                    if index + 1 >= len(pytest_args):
                        return False
                    index += 2
                else:
                    index += 1
                continue
            if token in harmless_prefix_flags or re.fullmatch(r"-v+", token):
                index += 1
                continue
            if token.startswith("-"):
                return False
            target_path = token.split("::", maxsplit=1)[0]
            if not target_path.startswith("tests/") or ".." in Path(target_path).parts:
                return False
            targets.append(target_path)
            index += 1
        return bool(targets)

    command_fragments: list[str] = []
    for source_line in text.replace("\\\n", " ").splitlines():
        inline_code = re.findall(r"`([^`]+)`", source_line)
        if inline_code:
            command_fragments.extend(inline_code)
            outside_code = re.sub(r"`[^`]+`", " ", source_line)
            if outside_code.strip():
                command_fragments.append(outside_code)
        else:
            command_fragments.append(source_line)

    for raw_line in command_fragments:
        if "pytest" not in raw_line and "py.test" not in raw_line:
            continue
        lexer = shlex.shlex(raw_line, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        try:
            line_tokens = list(lexer)
        except ValueError:
            if re.search(r"-m(?:=|\s+).*\bnot\s+pg\b", raw_line, re.IGNORECASE):
                commands.append(raw_line)
            continue

        segments: list[list[str]] = [[]]
        for token in line_tokens:
            if token and set(token) <= control_characters:
                if segments[-1]:
                    segments.append([])
                continue
            segments[-1].append(token)

        for tokens in segments:
            pytest_indexes = [
                index
                for index, token in enumerate(tokens)
                if re.fullmatch(
                    r"(?:pytest|py\.test)(?:-?\d+(?:\.\d+)*)?",
                    Path(token).name,
                )
            ]
            if not pytest_indexes:
                continue
            for invocation, pytest_index in enumerate(pytest_indexes):
                next_index = (
                    pytest_indexes[invocation + 1]
                    if invocation + 1 < len(pytest_indexes)
                    else len(tokens)
                )
                pytest_args = tokens[pytest_index + 1 : next_index]

                marker_expressions: list[str] = []
                for index, token in enumerate(pytest_args):
                    if token == "-m" and index + 1 < len(pytest_args):
                        marker_expressions.append(pytest_args[index + 1])
                    elif token.startswith("-m="):
                        marker_expressions.append(token.partition("=")[2])
                    elif token.startswith("-") and not token.startswith("--") and "m" in token:
                        marker_suffix = token.split("m", maxsplit=1)[1]
                        if marker_suffix:
                            marker_expressions.append(marker_suffix.removeprefix("="))
                        elif index + 1 < len(pytest_args):
                            marker_expressions.append(pytest_args[index + 1])
                if not marker_expressions or not re.search(
                    r"\bnot\s+pg\b", marker_expressions[-1], re.IGNORECASE
                ):
                    continue

                if is_leased(tokens, pytest_index):
                    continue

                if not is_safely_targeted(pytest_args):
                    commands.append(" ".join(tokens[pytest_index:next_index]))
    return commands


def test_docs_governance_changes_require_pre_ci_review_gate() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="governance",
        changed_files=[
            "docs/development/PR_HOT_PATH.md",
            ".github/workflows/issue-pr-governance.yml",
        ],
        risk_assessment_complete=True,
    )

    assert gate.requires_review_gate is True
    assert gate.review_gate_complete is False
    assert gate.may_handoff_to_ci is False
    assert gate.status == "required"
    assert "surface:docs" in gate.matched_surfaces
    assert "surface:governance" in gate.matched_surfaces
    assert "generate or preflight the PR body" in gate.required_local_checks[0]


def test_gate_output_preserves_ci_authority() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="docs-authoring",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        review_gate_complete=True,
    )

    assert gate.status == "satisfied"
    assert gate.may_handoff_to_ci is True
    assert gate.preserves_ci_authority is True
    assert "GitHub CI" in gate.summary


def test_high_risk_implementation_requires_convergence_review_before_expensive_gates() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/oauth/service.py", "tests/oauth/test_service.py"],
        risk_surfaces=["auth", "credential-durability", "state-machine"],
        risk_assessment_complete=True,
    )

    assert gate.status == "required"
    assert gate.may_handoff_to_ci is False
    assert "risk:auth" in gate.matched_surfaces
    assert "risk:credential-durability" in gate.matched_surfaces
    assert any("convergence packet" in check for check in gate.required_local_checks)
    assert any("before selected expensive validation" in check for check in gate.required_local_checks)


def test_stateful_fallback_requires_executable_boundary_matrix_before_handoff() -> None:
    blocked = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/model_inquiry/runner.py"],
        risk_surfaces=["credential-durability", "state-machine"],
        risk_assessment_complete=True,
        review_gate_complete=True,
        stateful_fallback=True,
    )
    complete = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/model_inquiry/runner.py"],
        risk_surfaces=["credential-durability", "state-machine"],
        risk_assessment_complete=True,
        review_gate_complete=True,
        stateful_fallback=True,
        stateful_fallback_matrix_complete=True,
    )

    assert blocked.status == "required"
    assert blocked.may_handoff_to_ci is False
    assert blocked.stateful_fallback_matrix_complete is False
    assert any("executable stateful fallback boundary matrix" in check for check in blocked.required_local_checks)
    assert complete.status == "satisfied"
    assert complete.may_handoff_to_ci is True
    assert complete.stateful_fallback_matrix_complete is True


def test_stateful_fallback_matrix_completion_cannot_fail_open() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="stateful_fallback_matrix_complete requires stateful_fallback",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/model_inquiry/runner.py"],
            risk_surfaces=["state-machine"],
            risk_assessment_complete=True,
            stateful_fallback_matrix_complete=True,
        )

    with pytest.raises(
        ReviewBeforeCiGateError,
        match="stateful_fallback requires at least one declared high-risk surface",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/model_inquiry/runner.py"],
            risk_assessment_complete=True,
            stateful_fallback=True,
        )


def test_standard_implementation_keeps_existing_hot_path() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="implementation",
        changed_files=["app/panel/formatting.py", "tests/panel/test_formatting.py"],
        risk_assessment_complete=True,
    )

    assert gate.status == "not_required"
    assert gate.may_handoff_to_ci is True


@pytest.mark.parametrize(
    "lane", ["implmentation", "docs", "code", "maintenance", "promotion"]
)
def test_unknown_lane_is_rejected_instead_of_failing_open(lane: str) -> None:
    with pytest.raises(ReviewBeforeCiGateError, match=f"unknown lane: {lane}"):
        evaluate_review_before_ci_gate(
            lane=lane,
            changed_files=["app/oauth/service.py"],
        )


def test_governance_concurrency_requires_convergence_review() -> None:
    gate = evaluate_review_before_ci_gate(
        lane="governance",
        changed_files=["scripts/run_with_host_lease.py"],
        risk_surfaces=["concurrency"],
        risk_assessment_complete=True,
    )

    assert gate.status == "required"
    assert gate.may_handoff_to_ci is False
    assert "risk:concurrency" in gate.matched_surfaces
    assert any("convergence packet" in check for check in gate.required_local_checks)


def test_bypass_requires_explicit_reason() -> None:
    required = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        risk_assessment_complete=True,
    )
    bypassed = evaluate_review_before_ci_gate(
        lane="direct-repair",
        changed_files=["docs/development/PR_HOT_PATH.md"],
        bypass_reason="Emergency wording repair; receipt will name skipped local gate.",
        risk_assessment_complete=True,
    )

    assert required.may_handoff_to_ci is False
    assert required.bypass_reason is None
    assert bypassed.status == "bypassed"
    assert bypassed.may_handoff_to_ci is True
    assert bypassed.bypass_reason == "Emergency wording repair; receipt will name skipped local gate."
    assert bypassed.preserves_ci_authority is True


def test_high_risk_implementation_cannot_bypass_convergence_review() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="only for an emergency direct-repair",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/oauth/service.py"],
            risk_surfaces=["auth"],
            risk_assessment_complete=True,
            bypass_reason="Skip convergence review.",
        )


def test_implementation_requires_explicit_risk_assessment_even_when_no_risk_declared() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="require an explicit completed risk assessment",
    ):
        evaluate_review_before_ci_gate(
            lane="implementation",
            changed_files=["app/oauth/service.py"],
        )


def test_high_risk_direct_repair_cannot_use_emergency_bypass() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="no declared high-risk surface",
    ):
        evaluate_review_before_ci_gate(
            lane="direct-repair",
            changed_files=["app/oauth/service.py"],
            risk_surfaces=["auth"],
            bypass_reason="Emergency auth repair.",
            risk_assessment_complete=True,
        )


def test_direct_repair_cannot_omit_risk_assessment_to_reach_bypass() -> None:
    with pytest.raises(
        ReviewBeforeCiGateError,
        match="require an explicit completed risk assessment",
    ):
        evaluate_review_before_ci_gate(
            lane="direct-repair",
            changed_files=["app/oauth/service.py"],
            bypass_reason="Emergency auth repair.",
        )


def test_cli_fails_until_review_gate_is_complete() -> None:
    blocked = subprocess.run(
        [
            sys.executable,
            "scripts/review_before_ci_gate.py",
            "--lane",
            "governance",
            "--changed-file",
            "docs/development/PR_HOT_PATH.md",
            "--risk-assessment-complete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    allowed = subprocess.run(
        [
            sys.executable,
            "scripts/review_before_ci_gate.py",
            "--lane",
            "governance",
            "--changed-file",
            "docs/development/PR_HOT_PATH.md",
            "--risk-assessment-complete",
            "--review-gate-complete",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert blocked.returncode == 1
    assert json.loads(blocked.stdout)["may_handoff_to_ci"] is False
    assert allowed.returncode == 0
    assert json.loads(allowed.stdout)["may_handoff_to_ci"] is True


def test_publish_pr_skill_runs_review_gate_before_push() -> None:
    text = PUBLISH_PR_SKILL.read_text(encoding="utf-8")

    assert "Review-Before-CI Gate" in text
    assert "scripts/review_before_ci_gate.py" in text
    assert text.index("Review-Before-CI Gate") < text.index("### Step 5: Push Branch")
    focused = text.index("Run focused local checks")
    independent_review = text.index("fresh independent high-capability review", focused)
    validation = text.index("run the proportionate validation", independent_review)
    renewed_gate = text.index("Re-run the branch-truth pre-push gate", validation)
    push = text.index("Push only after all four preceding steps pass", renewed_gate)
    assert focused < independent_review < validation < renewed_gate < push
    assert "A repo-wide full suite is not automatic" in text
    assert "Governance-only changes default to targeted" in text


def test_mechanism_convergence_contract_is_wired_across_delivery_skills() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    issue_to_code = ISSUE_TO_CODE_SKILL.read_text(encoding="utf-8")
    publish_pr = PUBLISH_PR_SKILL.read_text(encoding="utf-8")
    verification = VERIFICATION_SKILL.read_text(encoding="utf-8")
    contract = REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8")

    assert "## Mechanism Convergence Gate" in contract
    assert "mechanism/convergence review before an expensive" in agents
    assert "risk-convergence form" in issue_to_code
    assert "TCD_RISK_SURFACES" in publish_pr
    assert "implementation, governance, or direct-repair work" in publish_pr
    assert "implementation, governance, or direct repair" in publish_pr
    assert "Low-convergence circuit breaker" in verification
    assert "credential-durability" in verification
    assert "state-machine surfaces" in verification


def test_one_final_review_round_governs_every_full_path() -> None:
    verification = VERIFICATION_SKILL.read_text(encoding="utf-8")
    contract = REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8")
    process_map = (REPO_ROOT / "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md").read_text(
        encoding="utf-8"
    )
    dispatcher = DISPATCHER_CONTRACT.read_text(encoding="utf-8")
    normalized_verification = " ".join(verification.split())

    assert "one independent final round on the current head SHA" in verification
    assert "No path requires two consecutive clean final reviews" in normalized_verification
    assert "One clean independent final review on the current head SHA is sufficient" in contract
    assert "A P0/P1 fix invalidates the prior review authority" in contract
    normalized_process_map = " ".join(process_map.split())
    assert (
        "Full-path review repair loop: re-run after every substantive P0/P1 fix and stop after "
        "one clean independent round on the repaired current head SHA"
        in normalized_process_map
    )
    assert "Light-path PRs do not enter this loop" in process_map
    assert "two clean rounds for high-risk surfaces" not in process_map
    assert "normal v3 delivery requires one distinct clean review session" in dispatcher
    assert "ledger-visible low-convergence evidence does not raise" in dispatcher
    assert "no-repair delivery still requires two distinct clean review sessions" not in dispatcher


def test_review_severity_routing_blocks_only_p0_and_p1() -> None:
    contract = REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8")
    closure_skill = VERIFICATION_SKILL.read_text(encoding="utf-8")

    for surface in (contract, closure_skill):
        normalized = " ".join(surface.split())
        normalized_lower = normalized.lower()
        assert "no valid `blocking p2`" in normalized_lower
        assert "only p0/p1 findings" in normalized_lower
        assert ".codex/skills/bug-to-issue/SKILL.md" in surface
        assert "leave the pr code unchanged" in normalized_lower
        assert re.search(
            r"reply on the original review finding/thread with the (?:registry )?issue reference",
            normalized_lower,
        )
        assert "without another review round" in normalized_lower
        assert "P3" in surface and "informational" in normalized_lower


def test_fast_lane_consumes_structured_severity_without_weakening_gates() -> None:
    skill = (REPO_ROOT / ".codex/skills/deliver-issue-set/SKILL.md").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "companion-ui/prompts/codex/deliver-epic-autonomous-runner.md").read_text(encoding="utf-8")
    for surface in (skill, runner):
        assert "AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md" in surface
        assert ".codex/skills/bug-to-issue/SKILL.md" in surface or "known-defect contracts" in surface
        assert "P2" in surface
        assert "P0/P1" in surface


def test_protected_review_invariants_cannot_be_downgraded_to_p2() -> None:
    contract = " ".join(REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(VERIFICATION_SKILL.read_text(encoding="utf-8").split())

    for surface in (contract, closure_skill):
        assert "must be P0 or P1" in surface
        for protected_fragment in (
            "data loss or corruption",
            "source, vault, or authority",
            "secrets, authentication, or authorization",
            "migration durability",
            "concurrency or multi-writer safety",
            "irreversible or external",
            "false-green CI",
            "failed governing acceptance criterion",
            "`Verify:`",
            "closure gate",
        ):
            assert protected_fragment in surface


def test_nonblocking_findings_do_not_consume_repair_or_convergence_budget() -> None:
    contract = " ".join(REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(VERIFICATION_SKILL.read_text(encoding="utf-8").split())

    for surface in (contract, closure_skill):
        assert "P2/P3 findings" in surface
        assert "consume no" in surface
        assert "trigger mechanism convergence" in surface
        assert "low-convergence" in surface


def test_severity_routing_preserves_fail_closed_delivery_gates() -> None:
    contract = " ".join(REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(VERIFICATION_SKILL.read_text(encoding="utf-8").split())

    assert "independent review" in contract
    assert "current-head-SHA CI" in contract
    assert "issue acceptance/`Verify:` evidence" in contract
    assert "verified-merge controls" in contract
    assert "closure gates" in contract

    assert "reviewer remains independent" in closure_skill
    assert "current-SHA CI remains mandatory" in closure_skill
    assert "issue acceptance/`Verify:`" in closure_skill
    assert "verified-merge" in closure_skill
    assert "closure gates remain fail-closed" in closure_skill


def test_pr_workflow_uses_the_canonical_severity_dispositions() -> None:
    for path in (PR_HOT_PATH, PR_ESCALATION_PATHS):
        surface = " ".join(path.read_text(encoding="utf-8").split())
        assert "P0/P1 correctness, contract, or safety defect" in surface
        assert "P2 real defect accepted for this PR" in surface
        assert "leave the PR code unchanged" in surface
        assert "through `bug-to-issue`" in surface
        assert "without another review round" in surface
        assert "P3 informational advice or non-defect suggestion" in surface
        assert "no valid `blocking P2`" in surface
        assert "fix if cheap" not in surface


def test_pr_integration_legacy_shorthand_cannot_override_severity_routing() -> None:
    integration = PR_INTEGRATION_SKILL.read_text(encoding="utf-8")
    hot_path = " ".join(PR_HOT_PATH.read_text(encoding="utf-8").split())
    closure_skill = " ".join(VERIFICATION_SKILL.read_text(encoding="utf-8").split())

    assert "Classify the PR with the hot-path fields from `PR_HOT_PATH.md`" in integration
    for surface in (hot_path, closure_skill):
        assert "legacy `cheap fix`" in surface
        assert "not" in surface and "independent" in surface and "severity" in surface
        assert "P0/P1 blocking-repair concepts only" in surface
        assert "do not apply to P2/P3" in surface or "does not include P2/P3" in surface
        assert "true P2" in surface
        assert "fixing commit" in surface

    assert "never requires a fixing commit" in hot_path
    assert "abbreviated bucket list cannot override" in hot_path


def test_p2_dispatcher_compatibility_fails_closed_until_receipts_are_lossless() -> None:
    contract = " ".join(REVIEW_REPAIR_CONTRACT.read_text(encoding="utf-8").split())
    closure_skill = " ".join(VERIFICATION_SKILL.read_text(encoding="utf-8").split())
    agent_loop = VERIFICATION_AGENT_LOOP.read_text(encoding="utf-8")

    # The executable ledger still has only blocking/clean outcomes. Governance
    # must not misrepresent a P2 as clean while that remains true.
    assert 'normalized not in {"blocking", "clean"}' in agent_loop
    assert "review outcome must be blocking or clean" in agent_loop

    for surface in (contract, closure_skill):
        assert "must not" in surface
        assert "P2-bearing review" in surface
        assert "dispatcher `delivered` receipt" in surface
        assert "must not manufacture a clean" in surface
        assert "live-evidence" in surface
        assert "original GitHub" in surface
        assert "Issue" in surface
        assert "reply/disposition" in surface
        assert "immediately before merge" in surface
        assert "protected P1" in surface
        assert "without" in surface and "another review round" in surface


def test_pr_hot_path_requires_explicit_risk_classification_before_bypass() -> None:
    hot_path = PR_HOT_PATH.read_text(encoding="utf-8")

    assert "--risk-assessment-complete" in hot_path
    assert "A declared high-risk surface is never bypassable" in hot_path
    assert (
        "`lane`: `docs-authoring` | `implementation` | `governance` | "
        "`direct-repair`"
    ) in hot_path
    assert "Promotion is not a PR hot-path lane" in hot_path


def test_validation_scope_defaults_to_affected_subsystem_across_owner_docs() -> None:
    workflow = DEV_WORKFLOW.read_text(encoding="utf-8")
    process_map = PROCESS_MAP.read_text(encoding="utf-8")

    assert "governing Issue's `Verify:` targets" in workflow
    assert "uses `scripts/select_pr_tests.py`" in workflow
    assert "repo-wide non-PG suite only when" in workflow
    assert "affected-subsystem pytest" in process_map
    assert "Contract or cross-system full-suite trigger?" in process_map
    assert "Affected-subsystem validation + current-SHA CI" in process_map


def test_host_global_full_suite_uses_atomic_wrapper_in_canonical_workflow() -> None:
    agents = AGENTS.read_text(encoding="utf-8")
    workflow = DEV_WORKFLOW.read_text(encoding="utf-8")
    template = (REPO_ROOT / ".github/pull_request_template.md").read_text(
        encoding="utf-8"
    )
    runtime_chain = (REPO_ROOT / "scripts/verify_runtime_chain.sh").read_text(
        encoding="utf-8"
    )
    py312_smoke = (REPO_ROOT / "scripts/py312_smoke_test.sh").read_text(
        encoding="utf-8"
    )
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    verify_promotion = (REPO_ROOT / ".codex/skills/verify-promotion/SKILL.md").read_text(
        encoding="utf-8"
    )
    testing = (REPO_ROOT / "docs/TESTING.md").read_text(encoding="utf-8")

    assert "scripts/run_with_host_lease.py" in agents
    assert "Chat reservations" in agents
    assert "--resource pytest-not-pg" in workflow
    assert "is not mutual exclusion" in workflow
    assert "scripts/run_with_host_lease.py" in template
    for producer in (
        runtime_chain,
        py312_smoke,
        makefile,
        verify_promotion,
        testing,
    ):
        assert "scripts/run_with_host_lease.py" in producer
        assert "--resource pytest-not-pg" in producer
    for sha_bound_producer in (makefile, runtime_chain, py312_smoke):
        assert "git rev-parse --short HEAD" in sha_bound_producer
    for autoload_disabled_producer in (
        makefile,
        runtime_chain,
        py312_smoke,
        testing,
    ):
        relevant_commands = [
            line
            for line in autoload_disabled_producer.replace("\\\n", " ").splitlines()
            if "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in line
            and "--resource pytest-not-pg" in line
            and "pytest" in line
        ]
        assert relevant_commands
        for command in relevant_commands:
            assert "pytest_asyncio.plugin" in command
            assert "anyio.pytest_plugin" in command


def test_owner_docs_do_not_prescribe_bare_repo_wide_not_pg_suites() -> None:
    owner_docs = (
        REPO_ROOT / "docs/TESTING.md",
        REPO_ROOT / "docs/STATUS.md",
        REPO_ROOT / "docs/eval.md",
    )

    for owner_doc in owner_docs:
        assert _bare_repo_wide_not_pg_commands(
            owner_doc.read_text(encoding="utf-8")
        ) == [], owner_doc


@pytest.mark.parametrize(
    "command",
    [
        "pytest -m 'not pg'",
        'pytest -m "not pg and not alpha_llm"',
        '```bash\npytest -q -m "not pg"\n```',
        'pytest -q -m="not pg"',
        "pytest -q -m='not pg and not alpha_llm'",
        'pytest -m "not pg" --ignore=tests/slow',
        'pytest -m "not pg" --ignore tests/slow',
        'pytest -q -m "not pg" && pytest tests/chat/test_x.py -q',
        'pytest -q -m "not pg"; pytest tests/chat/test_x.py -q',
        'pytest -q -m="not pg" & pytest tests/chat/test_x.py -q',
        '(pytest -q -m "not pg")',
        'pytest tests/chat -q |& pytest -q -m "not pg"',
        'pytest -q -m "smoke" -m "not pg"',
        'pytest -q -m "not pg" --basetemp tests/tmp',
        "pytest -qm 'not pg'",
        r"pytest -q -mnot\ pg",
        "echo scripts/run_with_host_lease.py pytest -q -m 'not pg'",
        "echo python3 scripts/run_with_host_lease.py --resource pytest-not-pg -- "
        "pytest -q -m 'not pg'",
        'pytest -q tests/.. -m "not pg"',
        'pytest -q tests/foo/../.. -m "not pg"',
        "python3 scripts/run_with_host_lease.py --resource other "
        "--execution-id pytest-not-pg -- pytest -m 'not pg'",
        "pytest -m 'not pg' and a targeted example "
        "`pytest tests/chat -m 'not pg'`",
        "python3 scripts/run_with_host_lease.py --resource pytest-not-pg "
        "--resource other -- pytest -q -m 'not pg'",
        "python3 scripts/run_with_host_lease.py --resource other "
        "--resource=pytest-not-pg -- pytest -q -m 'not pg'",
        'pytest -q tests/chat . -m "not pg"',
        'pytest -q tests/chat tests/../.. -m "not pg"',
        'pytest -q tests/chat /tmp/repo -m "not pg"',
        "py.test -q -m 'not pg'",
        "/usr/local/bin/py.test -q -m 'not pg'",
        "pytest-3 -q -m 'not pg'",
        "pytest3 -q -m 'not pg'",
        "py.test-3.12 -q -m 'not pg'",
        "py.test3 -q -m 'not pg'",
    ],
)
def test_bare_repo_wide_not_pg_classifier_rejects_bypasses(command: str) -> None:
    assert _bare_repo_wide_not_pg_commands(command)


def test_bare_repo_wide_not_pg_classifier_allows_targeted_or_leased() -> None:
    assert _bare_repo_wide_not_pg_commands(
        'pytest tests/chat -q -m "not pg"'
    ) == []
    assert _bare_repo_wide_not_pg_commands(
        "python3 scripts/run_with_host_lease.py --resource pytest-not-pg -- "
        'pytest -q -m "not pg"'
    ) == []
    assert _bare_repo_wide_not_pg_commands(
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 "
        "scripts/run_with_host_lease.py --resource=pytest-not-pg -- "
        'pytest -q -m "not pg"'
    ) == []
