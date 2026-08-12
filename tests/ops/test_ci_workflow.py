from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml


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


def _browser_text() -> str:
    return BROWSER_WORKFLOW.read_text(encoding="utf-8")


def _workflow_step(workflow: str, name: str, next_name: str | None = None) -> str:
    start = workflow.index(f"- name: {name}")
    if next_name is None:
        return workflow[start:]
    return workflow[start : workflow.index(f"- name: {next_name}", start)]


def _workflow_run(name: str) -> str:
    workflow = yaml.safe_load(_browser_text())
    steps = workflow["jobs"]["companion-ui-browser-runtime"]["steps"]
    return next(step["run"] for step in steps if step.get("name") == name)


def _python_heredoc(script: str) -> str:
    match = re.search(r"<<'PY'\n(?P<body>.*?)\nPY(?:\n|$)", script, re.DOTALL)
    assert match is not None
    return match.group("body")


def _unit_tests_job_text() -> str:
    workflow = _smoke_text()
    return workflow[
        workflow.index("pr-unit-tests-not-pg:") : workflow.index("contract-validation:")
    ]


def _contract_job_text() -> str:
    workflow = _smoke_text()
    return workflow[workflow.index("contract-validation:") :]


def _vaultwide_panel_verifier_step_text() -> str:
    workflow = _smoke_text()
    start = workflow.index('- name: "CI gate: vaultwide panel verifier"')
    end = workflow.index("- name: Skip docker smoke for docs-only PR", start)
    return workflow[start:end]


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


def test_ci_smoke_installs_acl_tools_for_linux_acl_fixture() -> None:
    job = _unit_tests_job_text()

    install_start = job.index("- name: Install Linux ACL tools")
    install_end = job.index("- name: Install dependencies", install_start)
    selected_test_run = job.index("- name: Run not-pg unit tests")
    install_step = job[install_start:install_end]

    assert "runs-on: ubuntu-latest" in job
    assert "steps.changes.outputs.code == 'true'" in install_step
    assert "sudo apt-get update" in install_step
    assert "sudo apt-get install -y acl" in install_step
    assert "continue-on-error" not in install_step
    assert install_start < selected_test_run


def test_pr_index_pg_contracts_run_exact_acceptance_surface() -> None:
    workflow = _smoke_text()

    assert "pr-index-pg-contracts:" in workflow
    job = workflow[
        workflow.index("pr-index-pg-contracts:") : workflow.index("contract-validation:")
    ]
    assert "github.event_name == 'pull_request'" in job
    assert "pgvector/pgvector:pg16" in job
    assert "dorny/paths-filter@v3" in job
    assert "app/cli/index_rebuild.py" in job
    assert "app/agents/panel/**" in job
    assert "tests/index/test_provenance_stamp.py" in job
    assert "tests/indexer/test_outbox_roundtrip_pg.py" in job
    assert "app/knowledge_acquisition/youtube_api_client.py" in job
    assert "app/alembic/versions/d9e0f1a2b3c4_yss03_youtube_api_quota.py" in job
    assert "tests/knowledge_acquisition/test_youtube_api_quota_pg.py" in job
    # Entity-review operation journal (EROJ-01, #4350): all its
    # committed-visibility proofs are pg-marked, so this lane is the only
    # PR-path check that can regress-test them.
    assert "app/heimdal/entity_review_operation_journal.py" in job
    assert "app/alembic/versions/e7a2b9c4d1f8_eroj01_entity_review_operations.py" in job
    assert "tests/heimdal/test_entity_review_operation_journal.py" in job
    assert "tests/migrations/test_entity_review_operation_journal_schema_parity.py" in job
    # HAR-02's forward-only raw representation backfill is pg-only. Both the
    # runtime/migration sources must trigger this PR lane and the exact proof
    # must appear in its pytest invocation.
    assert "app/heimdal/raw_store.py" in job
    assert "app/alembic/versions/e7b4c9d2a6f1_heimdal_raw_representation.py" in job
    assert "tests/migrations/test_heimdal_raw_representation_migration.py" in job
    assert "tests/migrations/test_heimdal_raw_representation_migration.py" in (
        INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    )
    assert '-m "pg"' in job


def test_pr_ci_fetches_base_ref_before_diff_selection() -> None:
    job = _unit_tests_job_text()

    assert "fetch-depth: 0" in job
    # Full (non-shallow) base fetch: --depth=1 cuts the base tip's parents when
    # the base branch advances mid-run, breaking merge-base for diff selection.
    assert 'git fetch --no-tags origin "${{ github.base_ref }}"' in job
    assert "--depth=1" not in job


def test_optional_panel_llm_e2e_job_is_absent() -> None:
    workflow = _smoke_text()

    assert "panel_llm_e2e:" not in workflow
    assert "id: live-llm" not in workflow
    assert "steps.live-llm.outputs.enabled" not in workflow


def test_smoke_docker_runs_for_stable_targeting_pull_requests() -> None:
    workflow = _smoke_text()

    stable_or_post_merge = "github.event_name != 'pull_request' || github.base_ref == 'stable'"
    ordinary_pull_request = "github.event_name == 'pull_request' && github.base_ref != 'stable'"

    assert workflow.count(f"if: {stable_or_post_merge}") == 2
    assert f"if: {ordinary_pull_request}" in workflow
    assert "Docker smoke is skipped only for ordinary pull requests." in workflow
    assert "types: [opened, synchronize, reopened, edited]" in workflow


def test_vaultwide_panel_verifier_diagnostic_reads_runner_paths() -> None:
    # #4463: the failure diagnostic read the verifier script's workspace-relative
    # tmp/ defaults while the runner overrode LOG_PATH/REPORT_PATH to absolute
    # /tmp paths namespaced by run id and attempt. The two never matched, so a
    # failing gate printed the literal string "verifier artifacts" and nothing
    # else. Both sides must resolve from one declaration.
    step = _vaultwide_panel_verifier_step_text()

    log_declaration = (
        'VAULTWIDE_PANEL_LOG_PATH='
        '"/tmp/verify_vaultwide_panel.${GITHUB_RUN_ID}.${GITHUB_RUN_ATTEMPT}.log"'
    )
    report_declaration = (
        'VAULTWIDE_PANEL_REPORT_PATH='
        '"/tmp/verify_vaultwide_panel.${GITHUB_RUN_ID}.${GITHUB_RUN_ATTEMPT}.report"'
    )
    assert step.count(log_declaration) == 1, (
        "the verifier log path must be declared exactly once, keeping the "
        "run-id/attempt namespacing"
    )
    assert step.count(report_declaration) == 1, (
        "the verifier report path must be declared exactly once, keeping the "
        "run-id/attempt namespacing"
    )

    # The runner writes through the declared paths...
    assert 'LOG_PATH="$VAULTWIDE_PANEL_LOG_PATH"' in step
    assert 'REPORT_PATH="$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert "bash scripts/verify_vaultwide_panel.sh" in step

    # ...and the failure diagnostic reads the same declared paths back.
    assert 'cat "$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert 'tail -n 400 "$VAULTWIDE_PANEL_LOG_PATH"' in step
    assert 'grep -F "FAIL: " "$VAULTWIDE_PANEL_LOG_PATH"' in step

    # The stale workspace-relative glob must be gone; it never matched what the
    # runner wrote, which is exactly how the failure became unreadable.
    assert "tmp/verify_vaultwide_panel.*" not in step


def test_vaultwide_panel_verifier_diagnostic_fails_loud_on_missing_artifact() -> None:
    # #4463: every `ls` in the old diagnostic was swallowed by
    # `2>/dev/null || true`, so "no artifact found" and "artifact found and
    # empty" were indistinguishable from a healthy silent step.
    step = _vaultwide_panel_verifier_step_text()

    marker = "VAULTWIDE_PANEL_VERIFIER_ARTIFACT_MISSING"
    assert f'echo "{marker} report=$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert f'echo "{marker} log=$VAULTWIDE_PANEL_LOG_PATH"' in step

    # The artifact listing must not suppress its own stderr: the "No such file"
    # line names the path that was expected and is itself the evidence.
    listing = 'ls -l "$VAULTWIDE_PANEL_REPORT_PATH" "$VAULTWIDE_PANEL_LOG_PATH"'
    assert listing in step
    assert "2>/dev/null" not in step, (
        "the verifier diagnostic must not discard stderr; a swallowed error is "
        "how #4463 produced a red gate with no readable evidence"
    )


def test_vaultwide_panel_verifier_gate_remains_blocking() -> None:
    # #4463 is bounded to legibility: the gate itself keeps failing the job and
    # the verifier's assertions are untouched.
    workflow = _smoke_text()
    step = _vaultwide_panel_verifier_step_text()

    assert '- name: "CI gate: vaultwide panel verifier"' in workflow
    assert "continue-on-error" not in step

    # The verifier runs bare, so its exit status is the step's exit status, and
    # the cleanup trap re-raises the original status instead of masking it.
    assert "bash scripts/verify_vaultwide_panel.sh ||" not in step
    assert 'exit "$rc"' in step

    verifier = (REPO_ROOT / "scripts" / "verify_vaultwide_panel.sh").read_text(
        encoding="utf-8"
    )
    assert 'if [[ "$FAIL" -eq 0 ]]; then' in verifier
    assert verifier.rstrip().endswith('_log "SUMMARY PASS=$PASS FAIL=$FAIL"\nexit 1')


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


def test_browser_runtime_supports_exact_ref_dispatch_without_pull_request_trigger() -> None:
    browser = _browser_text()
    triggers = browser[: browser.index("concurrency:")]
    checkout = _workflow_step(browser, "Checkout", "Setup Python")

    assert "push:" in triggers
    assert "branches: [main]" in triggers
    assert "workflow_dispatch:" in triggers
    assert "pull_request:" not in triggers
    assert "ref: ${{ github.sha }}" in checkout
    for existing_blocking_module in (
        "tests/companion_ui/test_runtime_unavailable_browser.py",
        "tests/companion_ui/test_overlay_history_browser.py",
        "tests/companion_ui/test_cockpit_journeys.py",
    ):
        assert f"pytest -q {existing_blocking_module}" in browser


def test_browser_runtime_dispatch_requires_non_skipped_overview_journeys(
    tmp_path: Path,
) -> None:
    step = _workflow_step(
        _browser_text(),
        "Run exact-ref Overview browser journeys",
        "Run deterministic Companion UI browser-runtime tests",
    )

    assert "if: github.event_name == 'workflow_dispatch'" in step
    assert "set -euo pipefail" in step
    assert "test -f tests/companion_ui/test_devui_overview_journeys.py" in step
    assert "--junitxml=\"$DEVUI_OVERVIEW_JUNIT\"" in step
    assert "tests/companion_ui/test_devui_overview_journeys.py" in step
    assert "required Overview journey collection is empty" in step
    assert "required Overview journeys were skipped" in step
    assert "\n        continue-on-error:" not in step

    junit_guard = _python_heredoc(
        _workflow_run("Run exact-ref Overview browser journeys")
    )
    junit_path = tmp_path / "junit.xml"
    scenarios = (
        ({"tests": "0", "skipped": "0"}, False, "collection is empty"),
        ({"tests": "2", "skipped": "1"}, False, "journeys were skipped"),
        ({"tests": "2", "skipped": "0"}, True, ""),
    )
    for attributes, should_pass, expected_error in scenarios:
        rendered = " ".join(f'{key}="{value}"' for key, value in attributes.items())
        junit_path.write_text(
            f"<testsuites><testsuite {rendered}/></testsuites>\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-", str(junit_path)],
            input=junit_guard,
            text=True,
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) is should_pass
        assert expected_error in result.stderr


def test_browser_runtime_dispatch_uploads_exact_sha_overview_evidence(
    tmp_path: Path,
) -> None:
    browser = _browser_text()
    manifest = _workflow_step(
        browser,
        "Build exact-SHA Overview evidence manifest",
        "Upload exact-SHA Overview browser evidence",
    )
    upload = _workflow_step(browser, "Upload exact-SHA Overview browser evidence")

    assert "DEVUI_OVERVIEW_EVIDENCE_DIR: ${{ runner.temp }}/devui-overview" in browser
    assert "DEVUI_OVERVIEW_JUNIT:" in browser
    assert (
        "DEVUI_OVERVIEW_RECEIPT: ${{ runner.temp }}/devui-overview/receipts/"
        "devui-overview-browser-accessibility.v1.json"
    ) in browser
    assert "DEVUI_OVERVIEW_TRACE_DIR:" in browser
    assert "DEVUI_OVERVIEW_SCREENSHOT_DIR:" in browser
    assert "DEVUI_OVERVIEW_MANIFEST: ${{ runner.temp }}/devui-overview/manifest.json" in browser
    assert '["git", "rev-parse", "HEAD"]' in manifest
    assert "GITHUB_SHA" in manifest
    assert 'missing.append("junit")' in manifest
    assert 'missing.append("receipt")' in manifest
    assert "path.stat().st_size > 0" in manifest
    assert "json.loads(receipt_path.read_text" in manifest
    assert "trace" in manifest
    assert "screenshot" in manifest
    assert "name: devui-overview-browser-exact-${{ github.sha }}" in upload
    assert "${{ runner.temp }}/devui-overview/junit.xml" in upload
    assert "${{ runner.temp }}/devui-overview/manifest.json" in upload
    assert "${{ runner.temp }}/devui-overview/receipts/**" in upload
    assert "${{ runner.temp }}/devui-overview/traces/**" in upload
    assert "${{ runner.temp }}/devui-overview/screenshots/**" in upload
    assert "if-no-files-found: error" in upload

    evidence_dir = tmp_path / "devui-overview"
    receipt_path = evidence_dir / "receipts" / "devui-overview-browser-accessibility.v1.json"
    trace_path = evidence_dir / "traces" / "trace.zip"
    screenshot_path = evidence_dir / "screenshots" / "overview.png"
    junit_path = evidence_dir / "junit.xml"
    for parent in (receipt_path.parent, trace_path.parent, screenshot_path.parent):
        parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text('{"contract": "devui-overview-browser-accessibility.v1"}\n', encoding="utf-8")
    trace_path.write_bytes(b"trace")
    screenshot_path.write_bytes(b"screenshot")
    junit_path.write_text(
        '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"/></testsuites>\n',
        encoding="utf-8",
    )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest_path = evidence_dir / "manifest.json"
    env = os.environ | {
        "DEVUI_OVERVIEW_EVIDENCE_DIR": str(evidence_dir),
        "DEVUI_OVERVIEW_JUNIT": str(junit_path),
        "DEVUI_OVERVIEW_RECEIPT": str(receipt_path),
        "DEVUI_OVERVIEW_TRACE_DIR": str(trace_path.parent),
        "DEVUI_OVERVIEW_SCREENSHOT_DIR": str(screenshot_path.parent),
        "DEVUI_OVERVIEW_MANIFEST": str(manifest_path),
        "DEVUI_OVERVIEW_JOURNEY_OUTCOME": "success",
        "GITHUB_REF": "refs/heads/codex/exact-ref-proof",
        "GITHUB_SHA": head_sha,
    }
    manifest_run = _workflow_run("Build exact-SHA Overview evidence manifest").replace(
        "python - <<'PY'", f'"{sys.executable}" - <<\'PY\'', 1
    )
    result = subprocess.run(
        ["bash", "-c", manifest_run],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["artifact_name"] == f"devui-overview-browser-exact-{head_sha}"
    assert payload["checkout_sha"] == head_sha
    assert payload["github_sha"] == head_sha
    assert payload["missing_evidence"] == []
    assert {item["path"] for item in payload["files"]} == {
        "junit.xml",
        "receipts/devui-overview-browser-accessibility.v1.json",
        "screenshots/overview.png",
        "traces/trace.zip",
    }

    mismatch_result = subprocess.run(
        ["bash", "-c", manifest_run],
        cwd=REPO_ROOT,
        env=env | {"GITHUB_SHA": "0" * 40},
        text=True,
        capture_output=True,
        check=False,
    )
    assert mismatch_result.returncode != 0
    assert "exact-ref mismatch" in mismatch_result.stderr

    screenshot_path.unlink()
    missing_result = subprocess.run(
        ["bash", "-c", manifest_run],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_result.returncode != 0
    assert "lack required evidence: screenshot" in missing_result.stderr


def test_browser_runtime_exact_ref_contract_is_owner_documented() -> None:
    strategy = (
        REPO_ROOT / "docs" / "development" / "TEST_STRATEGY_HOT_PATH.md"
    ).read_text(encoding="utf-8")
    normalized_strategy = " ".join(strategy.split())

    assert "#4836" in strategy
    assert "workflow_dispatch" in strategy
    assert ".github/workflows/browser-runtime.yml" in strategy
    assert "${{ github.sha }}" in strategy
    assert "ordinary PR unit CI does not provide" in normalized_strategy


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


def test_integration_nightly_runs_yss01_pg_contract_targets() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    pg_contracts = workflow[
        workflow.index("pg-contracts:") : workflow.index("  k6-search:")
    ]

    assert "tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract" in pg_contracts
    assert (
        "tests/migrations/test_yss01_source_registry_schema_parity.py::"
        "test_yss01_migration_bootstrap_parity_and_legacy_repair"
    ) in pg_contracts
