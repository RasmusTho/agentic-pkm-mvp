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
    assert selection.pytest_args.startswith('-q -m "not pg"')


def test_shared_ci_change_falls_back_to_full_not_pg_suite() -> None:
    selection = select_tests([".github/workflows/ci.yml"])

    assert selection.full_suite is True
    assert selection.targets == ()
    assert selection.pytest_args == '-q -m "not pg"'
    assert "configuration" in selection.reason


def test_docs_only_change_keeps_pr_ci_governance_scoped() -> None:
    selection = select_tests(["docs/development/TEST_STRATEGY_HOT_PATH.md"])

    assert selection.full_suite is False
    assert selection.subsystems == ("docs",)
    assert "tests/docs" in selection.targets
    assert "tests/governance" in selection.targets


def test_unknown_runtime_surface_uses_safe_full_suite_fallback() -> None:
    selection = select_tests(["app/new_surface/example.py"])

    assert selection.full_suite is True
    assert "no subsystem mapping" in selection.reason


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


def test_shared_panel_watcher_e2e_file_selects_both_owning_subsystems() -> None:
    selection = select_tests(["tests/e2e/test_panel_watcher_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync", "promotion_panel")
    assert "tests/watcher" in selection.targets
    assert "tests/promotion" in selection.targets
    assert selection.targets.count("tests/e2e/test_panel_watcher_e2e.py") == 1


def test_unowned_e2e_file_uses_full_suite_fallback() -> None:
    selection = select_tests(["tests/e2e/test_new_cross_system_flow.py"])

    assert selection.full_suite is True
    assert "unowned e2e" in selection.reason


@pytest.mark.parametrize(
    ("changed_files", "expected_subsystems", "changed_test_path"),
    [
        pytest.param(
            ["docs/development/TEST_STRATEGY_HOT_PATH.md", "tests/governance/test_new_thing.py"],
            ("docs",),
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
    assert 'pytest_args=-q -m "not pg"' in text
    assert "tests/settings" in text
