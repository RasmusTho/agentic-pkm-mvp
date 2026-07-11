from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.select_pr_tests import select_tests


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_companion_ui_change_selects_companion_and_api_targets() -> None:
    selection = select_tests(["companion-ui/companion-app/src/workspace.ts", "tests/api/test_status_api.py"])

    assert selection.full_suite is False
    assert "companion_ui" in selection.subsystems
    assert "tests/companion_ui" in selection.targets
    assert "tests/api" in selection.targets
    assert "tests/e2e/test_panel_to_promotion_consume.py" in selection.targets
    assert "tests/e2e" not in selection.targets
    assert selection.pytest_args.startswith('-q -m "not pg and not alpha_llm')
    assert "not panel_llm_e2e" in selection.pytest_args


def test_ci_workflow_change_selects_governance_contract_tests() -> None:
    selection = select_tests([".github/workflows/ci.yml"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert "tests/governance" in selection.targets


def test_governance_docs_change_selects_governance_tests() -> None:
    selection = select_tests(["docs/development/TEST_STRATEGY_HOT_PATH.md"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert "tests/governance" in selection.targets


def test_unknown_runtime_surface_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests(["app/new_surface/example.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert selection.unowned_paths == ("app/new_surface/example.py",)


def test_watcher_change_selects_only_watcher_owned_e2e_files() -> None:
    selection = select_tests(["app/watcher/registry.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync",)
    assert "tests/watcher" in selection.targets
    assert "tests/e2e/test_runtime_loop_vault_test.py" in selection.targets
    assert "tests/e2e/test_watcher_registry_e2e.py" in selection.targets
    assert "tests/e2e/test_panel_watcher_e2e.py" in selection.targets
    assert "tests/e2e/test_reality_mvp_pipeline.py" not in selection.targets
    assert "tests/e2e" not in selection.targets


def test_runtime_health_change_has_a_ci_owner() -> None:
    selection = select_tests(
        [
            "app/runtime/health_probe.py",
            "app/cli/health.py",
            "docker-compose.yaml",
            "tests/invariants/test_health_probe.py",
            "docs/OBSERVABILITY_STABILIZATION/CONTAINER_HEALTH_SIGNALS.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("runtime_health",)
    assert selection.unowned_paths == ()
    assert "tests/health" in selection.targets
    assert "tests/invariants" in selection.targets
    assert "tests/api" in selection.targets


def test_shared_panel_watcher_e2e_file_selects_both_owning_subsystems() -> None:
    selection = select_tests(["tests/e2e/test_panel_watcher_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync", "promotion_panel")
    assert "tests/watcher" in selection.targets
    assert "tests/promotion" in selection.targets
    assert selection.targets.count("tests/e2e/test_panel_watcher_e2e.py") == 1


def test_unowned_e2e_file_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests(["tests/e2e/test_new_cross_system_flow.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert "unowned e2e" in selection.reason


@pytest.mark.parametrize(
    ("changed_files", "expected_subsystems", "changed_test_path"),
    [
        pytest.param(
            ["docs/development/TEST_STRATEGY_HOT_PATH.md", "tests/governance/test_new_thing.py"],
            ("governance",),
            "tests/governance/test_new_thing.py",
            id="docs-only+test",
        ),
        pytest.param(
            [".codex/skills/publish-pr/SKILL.md", "tests/scripts/test_new_helper.py"],
            ("governance",),
            "tests/scripts/test_new_helper.py",
            id="governance-only+test",
        ),
        pytest.param(
            ["scripts/x.sh", "tests/governance/test_y.py"],
            ("ops_deploy",),
            "tests/governance/test_y.py",
            id="subsystem+out-of-subsystem-test",
        ),
    ],
)
def test_changed_test_files_always_selected(
    changed_files: list[str], expected_subsystems: tuple[str, ...], changed_test_path: str
) -> None:
    selection = select_tests(changed_files)

    assert selection.full_suite is False
    assert selection.subsystems == expected_subsystems
    assert changed_test_path in selection.targets


def test_3383_shape_scripts_change_still_selects_out_of_subsystem_governance_test() -> None:
    # Reproduces the #3383 false-green: an ops_deploy-scoped change (scripts/x.sh)
    # must not silently drop a co-changed tests/governance/** file from the run.
    selection = select_tests(["scripts/x.sh", "tests/governance/test_y.py"])

    assert selection.full_suite is False
    assert "ops_deploy" in selection.subsystems
    assert "tests/governance/test_y.py" in selection.targets


def test_docs_file_with_foreign_subsystem_test_still_gets_full_subsystem_coverage() -> None:
    # A tests/** file OUTSIDE this branch's own blanket target dirs (DOCS_TARGETS)
    # must still route the PR through the subsystem loop instead of being absorbed
    # into a narrower docs-only run that drops the rest of that subsystem's tests.
    selection = select_tests(["docs/foo.md", "tests/watcher/test_x.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync",)
    assert "tests/watcher" in selection.targets
    assert "tests/e2e/test_watcher_registry_e2e.py" in selection.targets


def test_docs_file_with_unmapped_test_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests(["docs/foo.md", "tests/brandnew_subsystem/test_a.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert "no subsystem owner" in selection.reason


def test_governance_file_with_foreign_subsystem_test_still_gets_full_subsystem_coverage() -> None:
    # Governance-only analog of the docs-only case above: _is_governance_only
    # shares the same _non_test_signal/_within_target_dirs tolerance logic,
    # parameterized on GOVERNANCE_TARGETS instead of DOCS_TARGETS.
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/watcher/test_x.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync",)
    assert "tests/watcher" in selection.targets
    assert "tests/e2e/test_watcher_registry_e2e.py" in selection.targets


def test_governance_file_with_unmapped_test_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/brandnew_subsystem/test_a.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert "no subsystem owner" in selection.reason


def test_governance_target_exact_file_entry_is_tolerated() -> None:
    # GOVERNANCE_TARGETS' one non-directory entry (tests/ops/test_ci_workflow.py)
    # must be matched by _within_target_dirs' exact-equality branch, not just
    # its directory-prefix branch.
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/ops/test_ci_workflow.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)


def test_existing_static_targets_survive_the_cli_existence_filter(tmp_path: Path) -> None:
    output = tmp_path / "github-output.txt"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/settings/runtime.py",
            "--github-output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    # The only cross-subsystem target is the dedicated CI contract suite;
    # selector/governance tests run when their own subsystem changes.
    assert "tests/ci" in result.stdout
    assert "tests/governance/test_branch_guardrail_packet.py" not in result.stdout


def test_deleted_test_file_is_not_appended_to_cli_output(tmp_path: Path) -> None:
    output = tmp_path / "github-output.txt"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "scripts/x.sh",
            "--changed-file",
            "tests/governance/test_does_not_exist_at_head.py",
            "--github-output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "tests/governance/test_does_not_exist_at_head.py" not in result.stdout
    text = output.read_text(encoding="utf-8")
    assert "tests/governance/test_does_not_exist_at_head.py" not in text


def test_cli_writes_github_output(tmp_path: Path) -> None:
    output = tmp_path / "github-output.txt"

    subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/settings/runtime.py",
            "--github-output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    text = output.read_text(encoding="utf-8")
    assert "full_suite=false" in text
    assert "subsystems=settings" in text
    assert 'pytest_args=-q -m "not pg and not alpha_llm' in text
    assert "tests/settings" in text


def test_panel_live_e2e_is_owned_but_not_selected_by_generic_pr_pytest() -> None:
    selection = select_tests(["tests/e2e/test_panel_llm_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("llm_eval", "promotion_panel")
    assert "tests/e2e/test_panel_llm_e2e.py" not in selection.targets
    assert "not panel_llm_e2e" in selection.pytest_args


def test_panel_agent_package_change_selects_promotion_panel_coverage() -> None:
    selection = select_tests(["app/agents/panel_agent/runtime.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("promotion_panel",)
    assert "tests/panel" in selection.targets


def test_panel_agent_regression_change_selects_its_owned_coverage() -> None:
    selection = select_tests(["tests/agents/panel_agent/test_runtime.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("promotion_panel",)
    assert "tests/agents/panel_agent" in selection.targets


def test_top_level_panel_agent_regression_change_selects_its_owned_coverage() -> None:
    selection = select_tests(["tests/agents/test_panel_pipeline_integration.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("promotion_panel",)
    assert "tests/agents/test_panel_pipeline_integration.py" in selection.targets


def test_panel_agent_support_runtime_change_selects_promotion_panel_coverage() -> None:
    selection = select_tests(["app/agents/panel/runtime.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("promotion_panel",)
    assert "tests/agents/panel_agent" in selection.targets


def test_llm_runtime_configuration_change_selects_llm_coverage() -> None:
    selection = select_tests(["app/config/llm.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("llm_eval",)
    assert "tests/llm" in selection.targets


def test_voice_contract_and_runtime_change_selects_voice_coverage() -> None:
    selection = select_tests(
        [
            "app/voice/transcription.py",
            "tests/voice/test_transcription_sharing.py",
            "docs/MIMER_VOICE_LOOP/SHARE_TRANSCRIPTION_CAPABILITY.md",
            "docs/contracts/MIMER_CLIENT_CONTRACT.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("voice",)
    assert selection.unowned_paths == ()
    assert "tests/voice" in selection.targets
    assert "tests/voice/test_transcription_sharing.py" in selection.targets


def test_builder_system_change_selects_its_own_regression_tests() -> None:
    selection = select_tests(["app/builderops/cli.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert "tests/builderops" in selection.targets
    assert "tests/governance" in selection.targets


def test_cli_rejects_an_unowned_path() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/select_pr_tests.py", "--changed-file", "app/new_surface/example.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "subsystems=unowned" in result.stdout
    assert "unowned_paths=app/new_surface/example.py" in result.stdout
