from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CI_SMOKE_WORKFLOW = WORKFLOWS_DIR / "ci-smoke.yaml"
BROWSER_WORKFLOW = WORKFLOWS_DIR / "browser-runtime.yml"
IMAGE_WORKFLOW = WORKFLOWS_DIR / "app-image-build.yml"
IMPORT_LINTER_WORKFLOW = WORKFLOWS_DIR / "import-linter.yaml"
INTEGRATION_NIGHTLY_WORKFLOW = WORKFLOWS_DIR / "integration-nightly.yaml"
ARCHITECTURE_CI_WORKFLOW = WORKFLOWS_DIR / "architecture-ci.yaml"
FAILURE_CONTEXT_WORKFLOW = WORKFLOWS_DIR / "pr-ci-failure-context.yml"


def _smoke_text() -> str:
    return CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")


def _unit_tests_job_text() -> str:
    workflow = _smoke_text()
    return workflow[
        workflow.index("pr-unit-tests-not-pg:") : workflow.index("contract-validation:")
    ]


def _contract_job_text() -> str:
    workflow = _smoke_text()
    return workflow[workflow.index("contract-validation:") :]


def test_pr_ci_selects_subsystem_scoped_pytest_targets() -> None:
    # Moved from the retired ci.yml into ci-smoke.yaml (#3892); the PR unit
    # test lane must keep subsystem-scoped selection, the mandatory mypy
    # gate, and the intent-classification golden gate.
    job = _unit_tests_job_text()

    assert "Select subsystem-scoped pytest targets" in job
    assert "scripts/select_pr_tests.py" in job
    assert "steps.select-tests.outputs.pytest_args" in job
    assert 'pytest ${{ steps.select-tests.outputs.pytest_args }} | tee pytest-not-pg.log' in job
    assert "mypy app" in job
    assert "tests/eval/test_classification_golden.py" in job


def test_pr_index_pg_contracts_run_exact_acceptance_surface() -> None:
    workflow = _smoke_text()

    assert "pr-index-pg-contracts:" in workflow
    job = workflow[
        workflow.index("pr-index-pg-contracts:") : workflow.index("contract-validation:")
    ]
    assert "if: github.event_name == 'pull_request'" in job
    assert "pgvector/pgvector:pg16" in job
    assert "dorny/paths-filter@v3" in job
    assert "app/cli/index_rebuild.py" in job
    assert "tests/index/test_provenance_stamp.py" in job
    assert "tests/indexer/test_outbox_roundtrip_pg.py" in job
    assert '-m "pg"' in job


def test_pr_ci_fetches_base_ref_before_diff_selection() -> None:
    job = _unit_tests_job_text()

    assert "fetch-depth: 0" in job
    # Full (non-shallow) base fetch: --depth=1 cuts the base tip's parents when
    # the base branch advances mid-run, breaking merge-base for diff selection.
    assert 'git fetch --no-tags origin "${{ github.base_ref }}"' in job
    assert "--depth=1" not in job


def test_panel_llm_e2e_runs_only_after_merge() -> None:
    workflow = _smoke_text()

    assert "panel_llm_e2e:" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
    assert "'app/agents/panel_agent/**'" in workflow
    assert "'app/agents/panel/**'" in workflow
    assert "'tests/agents/panel_agent/**'" in workflow
    assert "'tests/agents/test_panel*.py'" in workflow
    assert "id: live-llm" in workflow
    assert "steps.live-llm.outputs.enabled == 'true'" in workflow


def test_smoke_docker_runs_for_stable_targeting_pull_requests() -> None:
    workflow = _smoke_text()

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
    retired = WORKFLOWS_DIR / "smoke.yml"

    # ci-smoke.yaml is the single PR-triggered smoke gate (#3891).
    assert not retired.exists(), "legacy smoke.yml must stay deleted"

    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
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
    workflow = _smoke_text()

    assert "cache: pip" in workflow
    assert "python3 scripts/lint_skills_consistency.py" in workflow
    assert "docs/DIAGRAMS.md must not contain literal" in workflow
    assert "Mermaid fences must not be indented" in workflow
    assert "Forbidden math fence syntax inside table detected" in workflow


def test_dispatch_only_ci_workflows_are_retired_without_stale_references() -> None:
    # ci.yml and ci-lite.yml were dead workflow_dispatch-era workflows whose
    # live gates moved into ci-smoke.yaml / integration-nightly.yaml (#3892).
    assert not (WORKFLOWS_DIR / "ci.yml").exists(), "ci.yml must stay deleted"
    assert not (WORKFLOWS_DIR / "ci-lite.yml").exists(), "ci-lite.yml must stay deleted"

    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "ci-lite" not in text, (
            f"{workflow_path.name} references the retired ci-lite.yml workflow"
        )

    failure_context = FAILURE_CONTEXT_WORKFLOW.read_text(encoding="utf-8")
    assert "\n      - CI\n" not in failure_context, (
        "pr-ci-failure-context.yml must not watch the retired CI workflow"
    )
    assert "- CI Smoke" in failure_context


def test_ci_smoke_runs_import_linter_on_app_paths() -> None:
    job = _contract_job_text()

    assert "import-linter==2.11" in job
    assert "lint-imports --config importlinter.ini" in job
    assert "'app/**'" in job
    assert "'importlinter.ini'" in job


def test_ci_smoke_validates_openapi_and_contract_surfaces() -> None:
    job = _contract_job_text()

    assert "python -m openapi_spec_validator api/openapi.yaml" in job
    assert "@redocly/cli" in job
    assert "'app/api/**'" in job
    assert "'api/**'" in job
    assert "events/asyncapi.yaml" in job
    assert "yamllint -c .yamllint.yml ." in job
    assert "jsonschema" in job


def test_ci_smoke_new_gates_skip_docs_only_pull_requests() -> None:
    unit_job = _unit_tests_job_text()
    contract_job = _contract_job_text()

    assert "uses: dorny/paths-filter@v3" in unit_job
    assert "steps.changes.outputs.code == 'true'" in unit_job

    assert "uses: dorny/paths-filter@v3" in contract_job
    assert "steps.changes.outputs.imports == 'true'" in contract_job
    assert "steps.changes.outputs.openapi == 'true'" in contract_job
    assert "steps.changes.outputs.yaml_json == 'true'" in contract_job


def test_integration_nightly_keeps_k6_and_pg_contract_lanes_nightly_only() -> None:
    nightly = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "k6-search:" in nightly
    assert "k6 run scripts/k6_search.js" in nightly
    assert "pg-contracts:" in nightly
    # Nightly schedule stays unchanged (out of scope for #3892).
    assert '- cron: "0 2 * * *"' in nightly
    # k6 must not leak onto the PR path.
    assert "k6 run" not in _smoke_text()


def test_architecture_ci_is_stripped_to_unique_dispatch_only_jobs() -> None:
    text = ARCHITECTURE_CI_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch" in text
    assert "pull_request" not in text
    assert "qas-010:" in text
    assert "docs-guard:" in text
    # Absorbed gates must not linger here as dead duplicate steps.
    assert "lint-imports" not in text
    assert "openapi_spec_validator" not in text
    assert "@redocly" not in text
    assert "@asyncapi/cli" not in text
    assert "yamllint" not in text
    assert "k6 run" not in text


def test_no_workflow_silently_ignores_alembic_upgrade_failures() -> None:
    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "alembic upgrade head || true" not in text, (
            f"{workflow_path.name} masks migration failures with '|| true'"
        )


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
