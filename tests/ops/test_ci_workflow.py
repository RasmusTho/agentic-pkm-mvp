from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CI_SMOKE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"
BROWSER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "browser-runtime.yml"
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "app-image-build.yml"
IMPORT_LINTER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "import-linter.yaml"
INTEGRATION_NIGHTLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "integration-nightly.yaml"


def _workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_pr_ci_selects_subsystem_scoped_pytest_targets() -> None:
    workflow = _workflow_text()

    assert "Select subsystem-scoped pytest targets" in workflow
    assert "scripts/select_pr_tests.py" in workflow
    assert "steps.select-tests.outputs.pytest_args" in workflow
    assert 'pytest ${{ steps.select-tests.outputs.pytest_args }} | tee pytest-not-pg.log' in workflow


def test_pr_ci_fetches_base_ref_before_diff_selection() -> None:
    workflow = _workflow_text()

    assert "fetch-depth: 0" in workflow
    # Full (non-shallow) base fetch: --depth=1 cuts the base tip's parents when
    # the base branch advances mid-run, breaking merge-base for diff selection.
    assert 'git fetch --no-tags origin "${{ github.base_ref }}"' in workflow
    assert "--depth=1" not in workflow


def test_panel_llm_e2e_runs_only_after_merge() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    assert "panel_llm_e2e:" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
    assert "'app/agents/panel_agent/**'" in workflow
    assert "'app/agents/panel/**'" in workflow
    assert "'tests/agents/panel_agent/**'" in workflow
    assert "'tests/agents/test_panel*.py'" in workflow
    assert "id: live-llm" in workflow
    assert "steps.live-llm.outputs.enabled == 'true'" in workflow


def test_smoke_docker_runs_for_stable_targeting_pull_requests() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    stable_or_post_merge = "github.event_name != 'pull_request' || github.base_ref == 'stable'"
    ordinary_pull_request = "github.event_name == 'pull_request' && github.base_ref != 'stable'"

    assert workflow.count(f"if: {stable_or_post_merge}") == 2
    assert f"if: {ordinary_pull_request}" in workflow
    assert "Docker smoke is skipped only for ordinary pull requests." in workflow
    assert "types: [opened, synchronize, reopened, edited]" in workflow


def test_dedicated_subsystem_workflows_have_path_filters_and_browser_runs_post_merge() -> None:
    browser = BROWSER_WORKFLOW.read_text(encoding="utf-8")
    image = IMAGE_WORKFLOW.read_text(encoding="utf-8")
    import_linter = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")

    assert "paths:" in browser
    assert "branches: [main]" in browser
    assert "pull_request:" not in browser
    assert "'companion-ui/**'" in browser
    assert "paths:" in image
    assert "'Dockerfile'" in image
    assert "paths:" in import_linter
    assert "'app/**'" in import_linter


def test_legacy_smoke_workflow_is_retired_without_stale_references() -> None:
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    retired = workflows_dir / "smoke.yml"

    # ci-smoke.yaml is the single PR-triggered smoke gate (#3891).
    assert not retired.exists(), "legacy smoke.yml must stay deleted"

    for workflow_path in sorted(workflows_dir.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "smoke.yml" not in text, (
            f"{workflow_path.name} references the retired smoke.yml workflow"
        )

    audit_script = (REPO_ROOT / "tools" / "audit_smoke.sh").read_text(encoding="utf-8")
    assert ".github/workflows/smoke.yml" not in audit_script, (
        "tools/audit_smoke.sh must not require the retired smoke.yml workflow"
    )
    assert ".github/workflows/ci-smoke.yaml" in audit_script, (
        "tools/audit_smoke.sh must require the consolidated ci-smoke.yaml gate"
    )


def test_ci_smoke_keeps_legacy_skills_lint_when_consolidating_smoke() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    assert "cache: pip" in workflow
    assert "python3 scripts/lint_skills_consistency.py" in workflow
    assert "docs/DIAGRAMS.md must not contain literal" in workflow
    assert "Mermaid fences must not be indented" in workflow
    assert "Forbidden math fence syntax inside table detected" in workflow


def test_integration_nightly_installs_required_media_libraries() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "Install media build dependencies" in workflow
    assert "libavformat-dev" in workflow
    assert "libavcodec-dev" in workflow
    assert "pkg-config" in workflow


def test_integration_nightly_uses_collision_safe_test_imports() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    full_suite = workflow[workflow.index("full-suite:") : workflow.index("pg-contracts:")]
    assert "--import-mode=importlib" in full_suite
    assert "-c /dev/null" not in full_suite
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in full_suite
    test_step = full_suite[full_suite.index("Full test suite (memory, not pg)") :]
    assert "continue-on-error: ${{ matrix.experimental }}" in test_step


def test_integration_nightly_prepares_pgvector_before_migrations() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "image: pgvector/pgvector:pg16" in workflow
    extension = workflow.index("CREATE EXTENSION IF NOT EXISTS vector")
    migration = workflow.index("alembic upgrade head")
    assert extension < migration
