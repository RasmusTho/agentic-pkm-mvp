from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.select_pr_tests as selector
from scripts.select_pr_tests import select_tests


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", ("scripts/await_pr_checks.sh", "scripts/ci_stall_classifier.py"))
def test_read_only_ci_wait_helpers_select_covering_governance_contracts(path: str) -> None:
    selection = select_tests([
        path,
        "tests/scripts/test_ci_stall_classifier.py",
        ".codex/skills/_shared/CI_WAIT_CONTRACT.md",
    ])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert "tests/architecture" not in selection.targets
    assert "tests/scripts" not in selection.targets
    assert "tests/scripts/test_ci_stall_classifier.py" in selection.targets
    assert "tests/ops" not in selection.targets
    assert "tests/deploy" not in selection.targets


def test_ci_wait_with_selector_contract_changes_avoids_unrelated_ops_suite() -> None:
    selection = select_tests(list(selector.CI_GOVERNANCE_CONTRACT_PATHS))

    assert selection.subsystems == ("governance",)
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert "tests/ops" not in selection.targets


@pytest.mark.parametrize("test_path", (
    "tests/scripts/test_dev_bootstrap.py", "tests/ops/test_host_global_lease.py",
))
def test_ci_wait_with_unrelated_operational_test_preserves_its_broad_owner(test_path: str) -> None:
    selection = select_tests([
        "scripts/await_pr_checks.sh", test_path,
    ])

    assert {"ops_deploy", "ops"} & set(selection.subsystems)
    assert "tests/ops" in selection.targets


@pytest.mark.parametrize("protected_path", (
    "scripts/deploy_channel.sh", "app/ops/postgres_deploy_linux.py",
    "app/alembic/versions/example.py", "requirements.txt",
))
def test_ci_wait_helper_does_not_narrow_cochanged_protected_source(protected_path: str) -> None:
    selection = select_tests(["scripts/await_pr_checks.sh", protected_path])

    if protected_path in {"app/alembic/versions/example.py", "requirements.txt"}:
        assert selection.full_suite is True
    else:
        assert selection.full_suite is False
        assert "tests/ops" in selection.targets
        assert "tests/deploy" in selection.targets


def test_companion_note_helper_selects_source_boundary_coverage() -> None:
    selection = select_tests(["app/services/companion_note.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert selection.subsystems == ("watcher_sync", "store_ingest", "outbox_worker")
    assert {
        "tests/watcher",
        "tests/workers",
        "tests/ingest",
        "tests/services/test_companion_note.py",
        "tests/services/test_companion_note_write_guard.py",
    } <= set(selection.targets)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/services/companion_note.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "subsystems=watcher_sync,store_ingest,outbox_worker" in result.stdout


@pytest.mark.parametrize(
    "path",
    (
        "app/services/companion_note.py.backup",
        "app/services/companion_note_extra.py",
    ),
)
def test_companion_note_mapping_keeps_unrelated_paths_refused(path: str) -> None:
    selection = select_tests([path])
    assert selection.unowned_paths == (path,)

    result = subprocess.run(
        [sys.executable, "scripts/select_pr_tests.py", "--changed-file", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert f"unowned_paths={path}" in result.stdout


def test_stage_a_aro03_contract_selects_route_tests() -> None:
    for path in selector.ARO03_ROUTE_CONTRACT_PATHS:
        selection = select_tests([path])

        assert selection.full_suite is False
        assert selection.unowned_paths == ()
        assert set(selector.ARO03_ROUTE_TESTS) <= set(selection.targets)


def test_companion_ui_change_selects_companion_and_api_targets() -> None:
    selection = select_tests(["companion-ui/companion-app/src/workspace.ts", "tests/api/test_status_api.py"])

    assert selection.full_suite is False
    assert "companion_ui" in selection.subsystems
    assert "tests/companion_ui" in selection.targets
    assert "tests/api" in selection.targets
    assert "tests/e2e/test_panel_to_promotion_consume.py" not in selection.targets
    assert "tests/e2e" not in selection.targets
    assert selection.pytest_args.startswith('-q -m "not pg and not alpha_llm')
    assert "not panel_llm_e2e" in selection.pytest_args


@pytest.mark.parametrize(
    "changed",
    [
        "app/api/routes/capture.py",
        "app/agents/ask/graph.py",
        "app/mcp/vault_tools.py",
    ],
)
def test_guarded_request_entrypoints_always_run_the_context_boundary_gate(changed: str) -> None:
    """#6136 review: a guarded entrypoint change cannot skip the MVR-05B boundary gate."""

    selection = select_tests([changed])

    assert "tests/architecture/test_multi_vault_context_boundaries.py" in selection.targets


def test_mimer_mcp_adapter_selects_semantic_and_existing_http_contract_tests() -> None:
    selection = select_tests(["app/mimer_mcp/server.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("mimer_mcp",)
    assert selection.unowned_paths == ()
    feature_targets = set(selection.targets) - set(selector.ALWAYS_TARGETS)
    assert feature_targets == {
        "tests/mcp/test_mimer_server.py",
        "tests/mcp/test_mimer_sidecar_semantic_parity.py",
        "tests/mcp/test_mimer_server_transport.py",
        "tests/mcp/test_mimer_server_security.py",
        "tests/mcp/test_mimer_server_smoke.py",
        "tests/architecture/test_mimer_mcp_server_boundaries.py",
        "tests/architecture/test_mimer_mcp_sidecar_isolation.py",
        "tests/architecture/test_requirements_consistency.py",
        "tests/api/test_ask_contract.py",
        "tests/api/test_capture_inbox_api.py",
        "tests/api/test_search_canonical_substrate.py",
        "tests/api/test_artifact_note_read_api.py",
        "tests/api/test_health_contract_api.py",
    }
    assert "tests/api" not in selection.targets


@pytest.mark.parametrize(
    "planner_path",
    ("app/planner/provider.py", "app/planner/prompts.py"),
)
def test_mcp_planner_producers_select_orchestration_and_changed_contract_tests(
    planner_path: str,
) -> None:
    boundary_test = "tests/orchestrator/test_mcp_admission_boundary.py"
    planner_test = "tests/planner/test_llm_planner.py"

    selection = select_tests([planner_path, boundary_test, planner_test])

    assert selection.full_suite is False
    assert selection.subsystems == ("orchestration",)
    assert selection.unowned_paths == ()
    assert "tests/orchestrator" in selection.targets
    assert boundary_test in selection.targets
    assert planner_test in selection.targets


def test_append_plan_regressions_select_orchestration_targets() -> None:
    changed = [
        "tests/execution/test_execution_request.py",
        "tests/planner/test_mock_planner.py",
    ]

    selection = select_tests(changed)

    assert selection.full_suite is False
    assert selection.subsystems == ("orchestration",)
    assert selection.unowned_paths == ()
    assert set(changed) <= set(selection.targets)
    assert "tests/orchestrator" not in selection.targets


@pytest.mark.parametrize(
    "effect_spine_path",
    (
        "app/execution/execution_request.py",
        "app/governance/governed_write.py",
        "tests/invariants/test_governed_effect_spine.py",
    ),
)
def test_governed_effect_spine_paths_select_orchestration_targets(
    effect_spine_path: str,
) -> None:
    selection = select_tests([effect_spine_path])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert selection.subsystems == ("orchestration",)
    if effect_spine_path.startswith("tests/"):
        assert effect_spine_path in selection.targets
    else:
        assert "tests/governance/test_governed_write.py" in selection.targets
    assert "tests/invariants/test_governed_effect_spine.py" in selection.targets


def test_static_web_surface_is_owned_by_builder_system_and_companion_ui() -> None:
    selection = select_tests(["app/web/static/cockpit.html", "app/web/static/signboard.js"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "builder_system" in selection.subsystems
    assert "companion_ui" in selection.subsystems
    assert "tests/dispatcher" in selection.targets
    assert "tests/builderops" in selection.targets
    assert "tests/api" in selection.targets


def test_canvas_chat_change_selects_chat_coverage() -> None:
    selection = select_tests(["app/chat/session_log.py", "tests/chat/test_session_log_writer.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("canvas_chat", "properties")
    assert selection.unowned_paths == ()
    assert "tests/chat" in selection.targets
    assert "tests/chat/test_session_log_writer.py" in selection.targets


def test_briefing_change_selects_briefing_coverage() -> None:
    selection = select_tests(["app/briefing/compose.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("briefing", "properties")
    assert selection.unowned_paths == ()
    assert "tests/briefing" in selection.targets


def test_archival_contract_change_selects_archival_coverage() -> None:
    selection = select_tests(
        [
            "app/archival/contracts.py",
            "docs/contracts/GOVERNED_ARCHIVAL_FLOW.md",
            "tests/archival/test_contracts.py",
            "tests/architecture/test_governed_archival_contract.py",
        ]
    )

    assert selection.full_suite is False
    assert "archival" in selection.subsystems
    assert selection.unowned_paths == ()
    assert "tests/archival" in selection.targets
    assert "tests/architecture/test_governed_archival_contract.py" in selection.targets


def test_instance_registry_change_selects_vault_coverage() -> None:
    selection = select_tests(
        ["app/instance/vault_registry.py", "tests/instance/test_vault_registry.py"]
    )
    vault_module_selection = select_tests(["app/vault/some_new_file.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("vault", "properties")
    assert selection.unowned_paths == ()
    assert "tests/instance" in selection.targets
    assert "tests/vault" in selection.targets
    assert "tests/instance/test_vault_registry.py" in selection.targets
    assert (
        "tests/architecture/test_no_hardcoded_vault_layout.py"
        in vault_module_selection.targets
    )


def test_mvr05_authority_recovery_architecture_test_has_vault_ci_owner() -> None:
    path = "tests/architecture/test_mvr05_authority_recovery.py"

    selection = select_tests([path])

    assert selection.full_suite is False
    assert selection.subsystems == ("vault",)
    assert selection.unowned_paths == ()
    assert path in selection.targets
    assert "tests/ops" not in selection.targets


def test_knowledge_runtime_modules_select_vault_knowledge_and_port_coverage() -> None:
    selection = select_tests(
        [
            "app/knowledge/adapters.py",
            "app/knowledge/contracts.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("vault",)
    assert selection.unowned_paths == ()
    assert "tests/knowledge" in selection.targets
    assert "tests/ports" in selection.targets


def test_profile_authority_and_reviewer_paths_select_vault_regressions() -> None:
    selection = select_tests(
        [
            "app/agents/profile_agent/runtime.py",
            "app/agents/reviewer/agent.py",
        ]
    )

    assert selection.full_suite is False
    assert "vault" in selection.subsystems
    assert selection.unowned_paths == ()
    assert "tests/governance/test_governed_vault_profile_proposals.py" in selection.targets
    assert "tests/agents/test_reviewer.py" in selection.targets
    assert "tests/agents/test_reviewer_single_note.py" in selection.targets


def test_vault_sync_delete_seam_selects_vault_lifecycle_coverage() -> None:
    selection = select_tests(["app/services/vault_sync.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "vault" in selection.subsystems
    assert "tests/services/test_vault_sync_lifecycle.py" in selection.targets
    assert "tests/watcher/test_vault_watcher_delete_required_outbox.py" in selection.targets


def test_ci_workflow_change_selects_governance_contract_tests() -> None:
    selection = select_tests([".github/workflows/ci.yml"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert "tests/governance" in selection.targets


def test_ci_smoke_workflow_change_selects_governance_contract_tests() -> None:
    selection = select_tests([".github/workflows/ci-smoke.yaml"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert selection.reason == "CI contract-only PR"
    assert selection.unowned_paths == ()
    assert "tests/ops/test_ci_workflow.py" in selection.targets
    assert "tests/scripts/test_select_pr_tests.py" in selection.targets
    assert "tests/deploy" not in selection.targets


def test_scoped_deploy_ci_repair_shape_avoids_full_suite_self_validation() -> None:
    selection = select_tests(
        [
            ".github/workflows/ci-smoke.yaml",
            "docs/development/TEST_STRATEGY_HOT_PATH.md",
            "scripts/run_scoped_test_partitions.py",
            "scripts/select_pr_tests.py",
            "tests/ops/test_ci_workflow.py",
            "tests/scripts/test_select_pr_tests.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert selection.unowned_paths == ()
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert not {"tests/deploy", "tests/ops", "tests/scripts"} & set(selection.targets)


def test_contract_selection_remains_conservative_after_deduplication() -> None:
    selection = select_tests([".github/workflows/import-linter.yaml"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert selection.unowned_paths == ()
    # The hot-path module runs once as part of the selected architecture
    # target; it is no longer a second explicit CI Smoke invocation.
    assert "tests/architecture" in selection.targets
    assert selection.targets.count("tests/architecture") == 1

    unknown = select_tests(
        [".github/workflows/import-linter.yaml", "tests/new_area/test_contract.py"]
    )
    assert unknown.subsystems == ("unowned",)
    assert unknown.unowned_paths == (
        ".github/workflows/import-linter.yaml",
        "tests/new_area/test_contract.py",
    )

    mixed_runtime = select_tests(
        [".github/workflows/import-linter.yaml", "app/new_unowned_surface.py"]
    )
    assert mixed_runtime.subsystems == ("unowned",)
    assert mixed_runtime.unowned_paths == ("app/new_unowned_surface.py",)

    selector_owner = select_tests(["scripts/select_pr_tests.py"])
    assert "governance" in selector_owner.subsystems
    assert selector_owner.unowned_paths == ()
    assert "tests/scripts/test_select_pr_tests.py" in selector_owner.targets
    assert "tests/architecture/test_pr_test_selection.py" in selector_owner.targets

    builder_owner = select_tests(["app/builderops/publication.py"])
    assert builder_owner.subsystems == ("governance", "builder_system")
    assert builder_owner.unowned_paths == ()
    assert builder_owner.reason == "PR intake/publication contract PR"
    assert "tests/scripts/test_publication.py" in builder_owner.targets
    assert "tests/dispatcher/test_verified_merge.py" in builder_owner.targets
    assert "tests/architecture/test_pr_hot_path_governance.py" in builder_owner.targets


def test_shared_note_path_normalization_has_exact_vault_ownership() -> None:
    selection = select_tests(
        [
            "app/path_utils.py",
            "app/vault/paths.py",
            "app/vault/path_overlap.py",
            "app/knowledge/locators.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("vault",)
    assert selection.unowned_paths == ()
    assert "tests/vault" in selection.targets
    assert "tests/knowledge" in selection.targets

    same_prefix_sibling = select_tests(["app/path_utils_extra.py"])
    assert same_prefix_sibling.subsystems == ("unowned",)
    assert same_prefix_sibling.unowned_paths == ("app/path_utils_extra.py",)


def test_governance_docs_change_selects_governance_tests() -> None:
    selection = select_tests(["docs/development/TEST_STRATEGY_HOT_PATH.md"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert "tests/governance" in selection.targets


def test_docs_change_with_deferred_e2e_scenario_is_owned() -> None:
    selection = select_tests(
        [
            "docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md",
            "tests/e2e/test_human_need_uat.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("docs",)
    assert selection.unowned_paths == ()
    assert "tests/architecture" in selection.targets
    assert "tests/e2e" not in selection.pytest_args


def test_unknown_runtime_surface_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests(["app/new_surface/example.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert selection.unowned_paths == ("app/new_surface/example.py",)


def test_agent_memory_recall_modules_select_memory_retrieval_coverage() -> None:
    selection = select_tests(
        [
            "app/agent_memory/recall_retrieval.py",
            "app/agent_memory/recall_activation.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert selection.subsystems == ("memory_retrieval",)
    assert "tests/agent_memory" in selection.targets


def test_promoted_memory_review_admission_selects_memory_retrieval_coverage() -> None:
    selection = select_tests(["app/knowledge_compilation/review_admission.py"])

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert selection.subsystems == ("memory_retrieval",)
    assert "tests/agent_memory" in selection.targets
    assert "tests/knowledge_compilation/test_review_admission_handoff.py" in selection.targets


def test_builder_system_architecture_fitness_test_has_ci_owner() -> None:
    path = "tests/architecture/test_builderops_store_boundary.py"

    selection = select_tests([path])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert selection.unowned_paths == ()
    assert path in selection.targets


def test_quality_wave_tests_have_ci_owner() -> None:
    path = "tests/quality_wave/test_cold_rebuild.py"

    selection = select_tests([path])

    assert selection.full_suite is False
    assert selection.subsystems == ("quality_wave",)
    assert selection.unowned_paths == ()
    assert "tests/quality_wave" not in selection.targets
    assert path in selection.targets


def test_proxmox_inventory_boundary_has_builder_system_ci_owner() -> None:
    selection = select_tests(["app/proxmox/inventory.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert selection.unowned_paths == ()
    assert "tests/proxmox" in selection.targets


def test_model_access_kernel_change_selects_contract_and_boundary_coverage() -> None:
    selection = select_tests(["llm_contract/__init__.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("model_access",)
    assert selection.unowned_paths == ()
    assert "tests/model_access" in selection.targets
    assert "tests/builderops/test_model_inquiry_adapters.py" in selection.targets
    assert "tests/builderops/test_model_inquiry_runner.py" in selection.targets
    assert "tests/architecture/test_llm_contract_kernel.py" in selection.targets
    assert "tests/architecture/test_import_boundary.py" in selection.targets


def test_model_access_router_facade_selects_model_access_coverage() -> None:
    selection = select_tests(["app/model_access/router.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("model_access",)
    assert selection.unowned_paths == ()
    assert "tests/model_access" in selection.targets
    assert "tests/builderops/test_model_inquiry_adapters.py" in selection.targets
    assert "tests/builderops/test_model_inquiry_runner.py" in selection.targets
    assert "tests/architecture/test_llm_contract_kernel.py" in selection.targets
    assert "tests/architecture/test_import_boundary.py" in selection.targets


def test_builder_model_access_resolver_selects_model_access_coverage() -> None:
    selection = select_tests(["app/builderops/model_access_resolver.py"])

    assert selection.full_suite is False
    assert "model_access" in selection.subsystems
    assert "tests/model_access" in selection.targets
    assert "tests/builderops/test_model_inquiry_adapters.py" in selection.targets
    assert "tests/builderops/test_model_inquiry_runner.py" in selection.targets
    assert "tests/architecture/test_import_boundary.py" in selection.targets


def test_deploy_pin_file_selects_ops_deploy() -> None:
    selection = select_tests(["config/deploy/dev.env"])

    assert selection.full_suite is False
    assert selection.subsystems == ("ops_deploy",)
    assert selection.unowned_paths == ()
    assert "tests/ops" in selection.targets
    assert "tests/scripts" in selection.targets
    assert "tests/deploy" in selection.targets


def test_release_channels_module_change_has_a_ci_owner() -> None:
    # First registration of app/release_channels/ (#3903 round 5): its own
    # direct suites live in tests/release_channels/, but tests/deploy/ already
    # owns test_cutover_readiness.py, test_fleet_model_fitness.py, and the
    # real deploy-entrypoint suites that exercise these modules -- both must
    # be selected or a change here leaves half its coverage unrun.
    selection = select_tests(
        [
            "app/release_channels/channel_isolation_preflight.py",
            "tests/release_channels/test_channel_isolation_preflight.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("release_channels",)
    assert selection.unowned_paths == ()
    assert "tests/release_channels" in selection.targets
    assert "tests/deploy" in selection.targets
    assert "tests/release_channels/test_channel_isolation_preflight.py" in selection.targets


def test_release_channels_sibling_modules_are_owned() -> None:
    # The other five app/release_channels/ modules (cutover_readiness,
    # fleet_model_fitness, prepare_promotion, prod_ref_fitness,
    # reversibility) must resolve the same way, not just the one module this
    # PR happens to touch.
    for module in (
        "cutover_readiness",
        "fleet_model_fitness",
        "prepare_promotion",
        "prod_ref_fitness",
        "reversibility",
    ):
        selection = select_tests([f"app/release_channels/{module}.py"])
        assert selection.full_suite is False
        assert selection.unowned_paths == ()
        assert "release_channels" in selection.subsystems
        assert "tests/release_channels" in selection.targets
        assert "tests/deploy" in selection.targets


def test_ops_contract_change_selects_ops_coverage() -> None:
    selection = select_tests(["app/ops/host_secret_contract.py", "tests/ops/test_host_secret_contract.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("ops",)
    assert selection.unowned_paths == ()
    assert "tests/ops" in selection.targets
    assert "tests/ops/test_host_secret_contract.py" in selection.targets


def test_deploy_pin_cannot_mask_an_unowned_runtime_path() -> None:
    selection = select_tests(["config/deploy/dev.env", "app/new_surface/example.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert selection.unowned_paths == ("app/new_surface/example.py",)


def test_settings_facade_and_shared_adapters_have_safe_owners() -> None:
    selection = select_tests(
        [
            "app/cli/__init__.py",
            "app/cli/settings_explain.py",
            "app/components/settings/providers_loader.py",
            "app/config/paths.py",
            "app/services/companion_eligibility.py",
            "app/services/settings.py",
        ]
    )

    assert selection.full_suite is True
    assert selection.unowned_paths == ()
    assert selection.reason == "shared CI/test/runtime configuration changed"
    assert "tests --ignore=tests/e2e" in selection.pytest_args

    for adapter_path in (
        "app/cli/settings_explain.py",
        "app/components/settings/providers_loader.py",
        "app/tts/config.py",
        "app/services/companion_eligibility.py",
        "app/services/settings.py",
    ):
        focused_selection = select_tests([adapter_path])
        assert focused_selection.subsystems == ("settings",)
        assert focused_selection.unowned_paths == ()
        assert "tests/cli/test_settings_explain_cli.py" in focused_selection.targets
        assert "tests/services/test_companion_eligibility.py" in focused_selection.targets

    tts_selection = select_tests(["app/tts/config.py", "vault/settings/tts.md"])
    assert tts_selection.subsystems == ("settings",)
    assert tts_selection.unowned_paths == ()
    assert "tests/tts" in tts_selection.targets


def test_settings_adapter_cannot_mask_unknown_runtime_path() -> None:
    selection = select_tests(
        [
            "app/services/settings.py",
            "app/new_surface/example.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert selection.unowned_paths == ("app/new_surface/example.py",)


def test_docs_authoring_and_skill_paths_are_owned() -> None:
    # Reproduces the #3476 / PR #3475 failure: a docs-authoring PR touching
    # docs/contracts/**, docs/HEIMDAL/**, api/openapi.yaml, and .codex/skills/**
    # together must resolve to defined docs/governance test targets instead of
    # unowned_paths, even though none of these four paths individually
    # disqualifies the PR from the docs-only or governance-only fast paths.
    selection = select_tests(
        [
            "docs/contracts/SOME_OTHER_CONTRACT.md",
            "docs/HEIMDAL/SOME_NEW_DOC.md",
            "api/openapi.yaml",
            ".codex/skills/some-skill/SKILL.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.unowned_paths == ()
    assert "unowned" not in selection.subsystems
    assert "docs_authoring" in selection.subsystems
    assert "companion_ui" in selection.subsystems
    assert "tests/governance" in selection.targets
    assert "tests/scripts" in selection.targets
    assert "tests/companion_ui" in selection.targets
    assert "tests/api" in selection.targets
    assert "tests/architecture/test_openapi_sync.py" in selection.targets


def test_unknown_app_module_is_unowned() -> None:
    # A genuinely unknown product/runtime path must still fail closed with
    # unowned_paths and exit 2 — the docs-authoring/skill-contract ownership
    # fix above must not weaken this guarantee.
    selection = select_tests(["app/brand_new_surface/whatever.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert selection.unowned_paths == ("app/brand_new_surface/whatever.py",)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/brand_new_surface/whatever.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unowned_paths=app/brand_new_surface/whatever.py" in result.stdout


def test_heimdal_mimer_contract_change_selects_its_owned_tests() -> None:
    selection = select_tests(
        [
            "docs/KARAKEEP_MIMER_ACQUISITION/DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md",
            "docs/EVENTS.md",
            "tests/heimdal/test_karakeep_handoff_contract.py",
            "tests/knowledge_acquisition/test_karakeep_handoff_consumer.py",
        ]
    )

    assert selection.full_suite is False
    # Heimdal-local ownership and the Heimdal↔Mimer handoff both apply to
    # shared capture/contract surfaces; selection must retain both suites.
    assert selection.subsystems == ("heimdal", "heimdal_mimer")
    assert "tests/heimdal" in selection.targets
    assert "tests/knowledge_acquisition" in selection.targets


def test_watcher_change_defers_e2e_files_to_post_merge() -> None:
    selection = select_tests(["app/watcher/registry.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync",)
    assert "tests/watcher" in selection.targets
    assert "tests/e2e/test_runtime_loop_vault_test.py" not in selection.targets
    assert "tests/e2e/test_watcher_registry_e2e.py" not in selection.targets
    assert "tests/e2e/test_panel_watcher_e2e.py" not in selection.targets
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


def test_relevance_runtime_and_regression_changes_select_relevance_coverage() -> None:
    selection = select_tests(["app/relevance/now_surface.py", "tests/relevance/test_attention_loop.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("relevance",)
    assert "tests/relevance" in selection.targets
    assert "tests/relevance/test_attention_loop.py" in selection.targets
    assert not selection.unowned_paths


def test_index_rebuild_cli_change_selects_memory_retrieval_coverage() -> None:
    selection = select_tests(["app/cli/index_rebuild.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("memory_retrieval", "properties")
    assert selection.unowned_paths == ()
    assert "tests/indexer" in selection.targets
    assert "tests/index" in selection.targets
    assert "tests/search" in selection.targets
    assert "tests/services/test_indexer_worker.py" in selection.targets
    assert "tests/cli/test_index_rebuild_resilience.py" in selection.targets
    assert "tests/cli/test_index_doctor_mixed_identity.py" in selection.targets


def test_runtime_index_producers_select_memory_retrieval_coverage() -> None:
    selection = select_tests(
        [
            "app/indexer/consumer.py",
            "app/search/service.py",
            "app/services/indexer.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("memory_retrieval", "properties")
    assert selection.unowned_paths == ()
    assert "tests/index" in selection.targets
    assert "tests/indexer" in selection.targets
    assert "tests/search" in selection.targets
    assert "tests/services/test_indexer_worker.py" in selection.targets


def test_reasoning_expansion_paths_select_owned_cognition_coverage() -> None:
    selection = select_tests(
        [
            "app/reasoning/schema.py",
            "app/reasoning/provider.py",
            "app/reasoning/multi.py",
            "app/expansion/create.py",
            "tests/reasoning/test_reasoning_multi_note.py",
            "tests/reasoning/test_reasoning_llm_logging.py",
            "tests/expansion/test_create_draft_lifecycle.py",
            "docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("reasoning_expansion", "properties")
    assert selection.unowned_paths == ()
    assert "tests/reasoning" in selection.targets
    assert "tests/expansion" in selection.targets
    assert "tests/invariants" in selection.targets


def test_expansion_uat_paths_are_owned() -> None:
    selection = select_tests(
        [
            "tests/uat/test_expansion_connect_create_accept_test_channel.py",
            "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md",
            "docs/DOCS_INDEX.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("reasoning_expansion",)
    assert selection.unowned_paths == ()
    assert "tests/reasoning" in selection.targets
    assert "tests/expansion" in selection.targets
    assert "tests/invariants" in selection.targets
    assert "tests/uat/test_expansion_connect_create_accept_test_channel.py" in selection.targets


def test_curation_adapter_change_selects_curation_coverage() -> None:
    selection = select_tests(
        [
            "app/curation/contradiction_triage.py",
            "tests/curation/test_contradiction_triage_adapter.py",
            "docs/CONTRADICTION_TRIAGE_BENCH/README.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("curation",)
    assert selection.unowned_paths == ()
    assert "tests/curation" in selection.targets
    assert "tests/invariants" in selection.targets


def test_premortem_admission_change_selects_decision_calibration_coverage() -> None:
    selection = select_tests(
        [
            "app/calibration/premortem_admission.py",
            "tests/calibration/test_premortem_admission.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("decision_calibration",)
    assert "tests/calibration" in selection.targets
    assert "tests/services/test_outcome_receipt_log.py" in selection.targets
    assert "tests/agent_memory/test_ask_synthesis_gate.py" in selection.targets


def test_temporal_posture_change_selects_semantic_noncollapse_coverage() -> None:
    selection = select_tests(
        [
            "app/temporal/posture.py",
            "config/temporal_posture.v1.json",
            "tests/temporal/test_temporal_posture.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("temporal_posture",)
    assert "tests/temporal" in selection.targets
    assert "tests/retrieval/test_view_freshness_metadata.py" in selection.targets


def test_journaling_change_has_a_ci_owner() -> None:
    selection = select_tests(
        ["app/journaling/day_context.py", "tests/journaling/test_assemble_day_context.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("journaling",)
    assert selection.unowned_paths == ()
    assert "tests/journaling" in selection.targets


def test_journal_activation_and_compilation_seams_have_ci_owners() -> None:
    selection = select_tests(
        [
            "app/activation/journal_draft.py",
            "app/knowledge_compilation/proposal_builders.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("journaling",)
    assert selection.unowned_paths == ()
    assert "tests/activation/test_journal_draft_activation.py" in selection.targets
    assert "tests/knowledge_compilation/test_proposal_builders.py" in selection.targets


def test_store_ingest_change_selects_its_owned_contract_tests() -> None:
    selection = select_tests(["app/stores/postgres.py", "tests/ingest/test_vault_root_ingest_pg.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("store_ingest", "properties")
    assert selection.unowned_paths == ()
    assert "tests/stores" in selection.targets
    assert "tests/ingest" in selection.targets
    assert "tests/architecture" in selection.targets
    assert (
        "tests/services/test_outbox_idempotency.py::test_save_object_content_change_emits_new_event"
        in selection.targets
    )


def test_missing_node_id_target_is_filtered(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI path must not pass a missing node-id target to pytest."""
    missing_target = "tests/services/test_removed_target.py::test_removed"
    monkeypatch.setattr(
        selector,
        "SUBSYSTEMS",
        (("store_ingest", ("app/stores/",), (missing_target,)),),
    )
    monkeypatch.setattr(sys, "argv", ["select_pr_tests.py", "--changed-file", "app/stores/postgres.py"])

    assert selector.main() == 0
    assert missing_target not in capsys.readouterr().out


def test_existing_node_id_target_is_selected(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The node-id guard preserves collectable targets on the CLI path."""
    target = "tests/scripts/test_select_pr_tests.py::test_existing_node_id_target_is_selected"
    monkeypatch.setattr(
        selector,
        "SUBSYSTEMS",
        (("store_ingest", ("app/stores/",), (target,)),),
    )
    monkeypatch.setattr(sys, "argv", ["select_pr_tests.py", "--changed-file", "app/stores/postgres.py"])

    assert selector.main() == 0
    assert target in capsys.readouterr().out


def test_static_target_collectability_fitness_is_always_selected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every scoped PR runs the static-target collectability fitness."""
    monkeypatch.setattr(sys, "argv", ["select_pr_tests.py", "--changed-file", "app/stores/postgres.py"])

    assert selector.main() == 0
    assert selector.STATIC_TARGET_COLLECTABILITY_FITNESS in capsys.readouterr().out


def test_missing_static_target_keeps_collectability_fitness_selected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A deleted static target still schedules the fitness that catches it."""
    missing_target = "tests/services/test_removed_target.py::test_removed"
    monkeypatch.setattr(
        selector,
        "SUBSYSTEMS",
        (
            (
                "store_ingest",
                ("app/stores/", missing_target.split("::", 1)[0]),
                (missing_target,),
            ),
        ),
    )
    monkeypatch.setattr(sys, "argv", ["select_pr_tests.py", "--changed-file", missing_target.split("::", 1)[0]])

    assert selector.main() == 0
    output = capsys.readouterr().out
    assert missing_target not in output
    assert selector.STATIC_TARGET_COLLECTABILITY_FITNESS in output


def test_static_selector_targets_are_collectable() -> None:
    """A renamed/deleted static selector target fails in the PR that changes it."""
    targets = tuple(
        target
        for _, _, subsystem_targets in selector.SUBSYSTEMS
        for target in subsystem_targets
        if target.split("::", 1)[0].endswith(".py")
    ) + tuple(
        target
        for target in selector.PR_INTAKE_CONTRACT_TARGETS
        if target.split("::", 1)[0].endswith(".py")
    ) + selector.STATIC_SELECTOR_NODE_ID_TARGETS + tuple(
        target for smoke_targets in selector.ISOLATED_TEST_MODULES.values() for target in smoke_targets
    )
    # The guarded source route may land before its helper/test. Its future test
    # must not become an unconditional missing target in this static census.
    assert selector.BWS_CONTROL_INSTALLATION_TEST not in targets

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr

    isolated_modules = {path.removesuffix(".py").replace("/", ".") for path in selector.ISOLATED_TEST_MODULES}
    for test_file in (REPO_ROOT / "tests").rglob("*.py"):
        module = test_file.relative_to(REPO_ROOT).with_suffix("").as_posix().replace("/", ".")
        if module in isolated_modules:
            continue
        imports: set[str] = set()
        for node in ast.walk(ast.parse(test_file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                name = "." * node.level + (node.module or "")
                base = importlib.util.resolve_name(name, module.rsplit(".", 1)[0]) if node.level else name
                imports.add(base)
                imports.update(f"{base}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                imports.add(node.value)  # also catch literal importlib imports
        assert not imports & isolated_modules, f"{test_file} consumes an isolated test module"


def test_app_change_to_censused_file_selects_properties_subsystem() -> None:
    """A change to an app/ file indexed by a tests/properties/_machinery.py line-keyed
    census (e.g. STORE_PAYLOAD_SINK_CLASSIFICATION, REGISTERED_MIRRORS) must select the
    properties subsystem even when tests/properties/ itself is untouched -- otherwise the
    census silently goes stale for that PR's affected-subsystem CI run (#4269)."""
    selection = select_tests(["app/watcher/vault_watcher.py"])

    assert selection.full_suite is False
    assert "properties" in selection.subsystems
    assert "tests/properties" in selection.targets


def test_object_store_module_selects_store_ingest_regressions() -> None:
    """The shared object-store producer belongs to the store/ingest contracts."""
    selection = select_tests(["app/objects/__init__.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("store_ingest", "properties")
    assert selection.unowned_paths == ()
    assert "tests/stores" in selection.targets
    assert "tests/ingest" in selection.targets
    assert "tests/architecture" in selection.targets
    assert (
        "tests/services/test_outbox_idempotency.py::test_save_object_content_change_emits_new_event"
        in selection.targets
    )


def test_outbox_worker_change_selects_worker_regressions() -> None:
    """Outbox-worker changes must reach pytest, not fail as unowned in CI."""
    selection = select_tests(
        ["app/workers/outbox_worker.py", "tests/workers/test_outbox_worker.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("outbox_worker",)
    assert selection.unowned_paths == ()
    assert "tests/workers" in selection.targets
    assert "tests/worker" in selection.targets
    assert "tests/services/test_outbox_idempotency.py" in selection.targets
    assert "tests/events" in selection.targets
    assert "tests/workers/test_outbox_worker.py" in selection.targets


def test_outbox_embedding_events_select_shared_regressions() -> None:
    """Embedding-event producers require worker delivery and indexer coverage."""
    selection = select_tests(["app/outbox/events.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("memory_retrieval", "outbox_worker")
    assert selection.unowned_paths == ()
    assert "tests/workers" in selection.targets
    assert "tests/events" in selection.targets
    assert "tests/indexer" in selection.targets
    assert "tests/index" in selection.targets
    assert "tests/services/test_indexer_worker.py" in selection.targets
    assert "tests/architecture/test_events_outbox_contracts.py" in selection.targets


def test_shared_cli_entrypoint_change_selects_full_suite() -> None:
    """The shared CLI entrypoint can affect every command's wiring."""
    selection = select_tests(["app/cli.py"])

    assert selection.full_suite is True
    assert selection.unowned_paths == ()


def test_event_diagnostic_and_legacy_outbox_surfaces_select_event_coverage() -> None:
    """Legacy event surfaces must not fail CI selection as unowned paths."""
    selection = select_tests(
        ["app/cli/events_doctor.py", "app/outbox/legacy_events.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("events_receipts",)
    assert selection.unowned_paths == ()
    assert "tests/events" in selection.targets
    assert "tests/receipts" in selection.targets
    assert "tests/contracts" in selection.targets


def test_orientation_runtime_change_selects_observability_coverage() -> None:
    """Derived orientation status belongs to the observability selection."""
    selection = select_tests(["app/orientation/runtime.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("observability",)
    assert selection.unowned_paths == ()
    assert "tests/observability" in selection.targets
    assert "tests/api" in selection.targets


def test_worker_metrics_module_change_has_a_ci_owner() -> None:
    """The worker /metrics endpoint module is outbox_worker surface: its
    coverage lives in tests/workers/test_worker_metrics.py, so a change must
    route to the worker regressions rather than fail-close as unowned."""
    selection = select_tests(
        ["app/workers/metrics.py", "tests/workers/test_worker_metrics.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("outbox_worker",)
    assert selection.unowned_paths == ()
    assert "tests/workers" in selection.targets
    assert "tests/workers/test_worker_metrics.py" in selection.targets


def test_heimdal_capture_adapter_change_has_a_ci_owner() -> None:
    selection = select_tests(["app/heimdal/capture_adapter.py", "tests/heimdal/test_capture_adapter.py"])

    assert selection.full_suite is False
    # Capture adapter changes also exercise the cross-constituent handoff
    # contract, so the narrower Heimdal owner coexists with heimdal_mimer.
    assert selection.subsystems == ("heimdal", "heimdal_mimer")
    assert selection.unowned_paths == ()
    assert "tests/heimdal" in selection.targets
    assert "tests/heimdal/test_capture_adapter.py" in selection.targets


def test_heimdal_cli_change_has_a_ci_owner() -> None:
    """The dedicated Heimdal CLI must select its subsystem suite in PR CI."""
    selection = select_tests(["app/cli/heimdal.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("heimdal",)
    assert selection.unowned_paths == ()
    assert "tests/heimdal" in selection.targets


def test_shared_panel_watcher_e2e_file_is_deferred_to_post_merge() -> None:
    selection = select_tests(["tests/e2e/test_panel_watcher_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("e2e",)
    assert selection.targets == selector.ALWAYS_TARGETS


def test_unowned_e2e_file_is_deferred_to_post_merge() -> None:
    selection = select_tests(["tests/e2e/test_new_cross_system_flow.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("e2e",)
    assert "deferred" in selection.reason


@pytest.mark.parametrize(
    ("changed_files", "expected_subsystems", "changed_test_path"),
    [
        pytest.param(
            ["docs/development/TEST_STRATEGY_HOT_PATH.md", "tests/governance/test_new_thing.py"],
            # tests/governance/ is also builder_system's own scope signal
            # (builder_system's real targets include tests/builderops and
            # tests/dispatcher, not just tests/governance) -- #4336 unions
            # that real subsystem in rather than absorbing it silently into
            # the governance-only branch.
            ("governance", "builder_system"),
            "tests/governance/test_new_thing.py",
            id="docs-only+test",
        ),
        pytest.param(
            [".codex/skills/publish-pr/SKILL.md", "tests/scripts/test_new_helper.py"],
            # tests/scripts/ is also ops_deploy's own scope signal (its real
            # targets include tests/ops and tests/deploy, not just
            # tests/scripts) -- #4336 unions it in instead of dropping it.
            ("governance", "ops_deploy"),
            "tests/scripts/test_new_helper.py",
            id="governance-only+test",
        ),
        pytest.param(
            ["scripts/x.sh", "tests/governance/test_y.py"],
            ("builder_system", "ops_deploy"),
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
    assert "tests/e2e/test_watcher_registry_e2e.py" not in selection.targets


def test_docs_file_with_unmapped_test_fails_closed_until_it_has_an_owner() -> None:
    selection = select_tests(["docs/foo.md", "tests/brandnew_subsystem/test_a.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert "no subsystem owner" in selection.reason


def test_governance_file_with_foreign_subsystem_test_still_gets_full_subsystem_coverage() -> None:
    # Governance-only analog of the docs-only case above: _is_governance_only
    # shares the same _non_test_signal/_within_target_dirs tolerance logic,
    # parameterized on GOVERNANCE_TARGETS instead of DOCS_TARGETS. Since #3476,
    # .codex/skills/** is also an owned docs_authoring path in its own right,
    # so this mixed changeset now retains both the foreign subsystem's
    # coverage (watcher_sync) and the skill-contract owner's own governance
    # coverage (docs_authoring) instead of silently absorbing the skill path.
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/watcher/test_x.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("watcher_sync", "docs_authoring")
    assert "tests/watcher" in selection.targets
    assert "tests/e2e/test_watcher_registry_e2e.py" not in selection.targets
    assert "tests/governance" in selection.targets


def test_governance_file_with_unmapped_test_fails_closed_until_it_has_an_owner() -> None:
    # Uses .codex/agents/ (governance-only eligible, but not a docs_authoring
    # prefix) rather than .codex/skills/, which is now an owned docs_authoring
    # surface in its own right (see test_docs_authoring_and_skill_paths_are_owned)
    # and would no longer reproduce a genuinely unowned combination.
    selection = select_tests([".codex/agents/x.toml", "tests/brandnew_subsystem/test_a.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("unowned",)
    assert "no subsystem owner" in selection.reason


def test_skill_contract_file_with_unmapped_test_still_gets_docs_authoring_coverage() -> None:
    # .codex/skills/** is an owned docs_authoring surface since #3476, so
    # mixing it with an unmapped tests/** subsystem no longer forces the
    # whole changeset to unowned_paths: the skill path resolves via
    # docs_authoring and the unmapped test file still runs as an explicit
    # pytest target (changed test files are always selected directly).
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/brandnew_subsystem/test_a.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("docs_authoring",)
    assert selection.unowned_paths == ()
    assert "tests/governance" in selection.targets
    assert "tests/brandnew_subsystem/test_a.py" in selection.targets


def test_governance_target_exact_file_entry_is_tolerated() -> None:
    # The workflow contract is already selected exactly by GOVERNANCE_TARGETS.
    # Its tests/ops location does not require unrelated host-global tests for
    # an otherwise pure governance diff; unrelated ops tests retain their owner.
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/ops/test_ci_workflow.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("governance",)
    assert "tests/architecture" in selection.targets
    assert "tests/ops/test_ci_workflow.py" in selection.targets
    assert "tests/ops" not in selection.targets


def test_mixed_docs_authoring_and_architecture_test_keeps_builder_targets() -> None:
    # #4336: tests/architecture/test_builderops_store_boundary.py is
    # individually carved out as builder_system's own diagnostic signal
    # (scripts/select_pr_tests.py's builder_system entry), but it also lives
    # inside GOVERNANCE_TARGETS' tolerated tests/architecture directory. A
    # mixed PR combining it with a .codex/skills/** change must not collapse
    # to governance-only and lose builder_system's real targets.
    selection = select_tests(
        [".codex/skills/x/SKILL.md", "tests/architecture/test_builderops_store_boundary.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems != ("governance",)
    assert "tests/builderops" in selection.targets
    assert "tests/dispatcher" in selection.targets
    # The pure governance-only fast path's own coverage must not regress.
    assert "tests/architecture" in selection.targets
    assert "tests/ops/test_review_before_ci_gate.py" in selection.targets


def test_mixed_ci_and_architecture_test_keeps_its_real_owner() -> None:
    # The BuilderOps test retains its owner; the CI helper contributes CI proof,
    # without inventing an operational co-change from its scripts/ location.
    selection = select_tests(
        ["scripts/select_pr_tests.py", "tests/architecture/test_builderops_store_boundary.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems != ("governance",)
    assert "tests/builderops" in selection.targets
    assert "tests/dispatcher" in selection.targets
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert "tests/ops" not in selection.targets
    assert "tests/deploy" not in selection.targets
    assert selection.deferred_targets == ()


def test_mixed_docs_and_review_gate_test_keeps_ci_contracts() -> None:
    selection = select_tests(["docs/STATUS.md", "tests/ops/test_review_before_ci_gate.py"])

    assert selection.full_suite is False
    assert selection.subsystems != ("docs",)
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert "tests/ops" not in selection.targets


def test_docs_plus_architecture_still_stays_governance_only_when_no_foreign_owner() -> None:
    # Sibling assertion to the mixed-PR cases above: an architecture test
    # with no individual subsystem carve-out (unlike
    # test_builderops_store_boundary.py / test_no_hardcoded_vault_layout.py /
    # test_pr_hot_path_governance.py, the last of which gained its own
    # builder_system carve-out under #4343 so a pure change to that one file
    # no longer fails closed as unowned) must still resolve through the plain
    # governance-only fast path.
    selection = select_tests([".codex/skills/x/SKILL.md", "tests/architecture/test_agent_skill_entrypoints.py"])

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


def test_panel_live_e2e_is_deferred_to_post_merge() -> None:
    selection = select_tests(["tests/e2e/test_panel_llm_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("e2e",)
    assert selection.targets == selector.ALWAYS_TARGETS
    assert "tests/e2e/test_panel_llm_e2e.py" not in selection.targets
    assert "not panel_llm_e2e" in selection.pytest_args


def test_panel_agent_package_change_selects_promotion_panel_coverage() -> None:
    selection = select_tests(["app/agents/panel_agent/runtime.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("promotion_panel", "properties")
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


def test_embedding_router_identity_change_selects_complete_llm_coverage() -> None:
    selection = select_tests(
        [
            "app/components/embeddings/legacy.py",
            "app/components/llm/fabric.py",
            "app/components/llm/router.py",
            "docs/LLM_ROUTING.md",
            "tests/components/llm/test_router.py",
            "tests/index/test_identity_migration.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("llm_eval",)
    assert selection.unowned_paths == ()
    assert "tests/components/embeddings" in selection.targets
    assert "tests/components/llm" in selection.targets
    assert "tests/index/test_identity_migration.py" in selection.targets


@pytest.mark.parametrize(
    ("source_path", "subsystem", "target"),
    (
        ("app/cli/embed_probe.py", "llm_eval", "tests/cli/test_embed_probe.py"),
        ("app/components/retrieval.py", "memory_retrieval", "tests/retrieval"),
    ),
)
def test_product_embedding_adapters_select_their_regression_coverage(
    source_path: str, subsystem: str, target: str
) -> None:
    selection = select_tests([source_path])

    assert selection.full_suite is False
    assert selection.subsystems == (subsystem,)
    assert selection.unowned_paths == ()
    assert target in selection.targets


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
    # docs/contracts/MIMER_CLIENT_CONTRACT.md is both voice's specific owner
    # and, since #3476, the generic docs_authoring docs/contracts/** owner;
    # both matches are retained and their targets union.
    assert selection.subsystems == ("voice", "docs_authoring")
    assert selection.unowned_paths == ()
    assert "tests/voice" in selection.targets
    assert "tests/voice/test_transcription_sharing.py" in selection.targets
    assert "tests/governance" in selection.targets


def test_episodes_runtime_change_selects_episodes_coverage() -> None:
    selection = select_tests(
        [
            "app/episodes/stream_registry.py",
            "app/jobs/episodes_projection.py",
            "schemas/episode-note.schema.json",
            "tests/episodes/test_stream_registry.py",
            "docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("episodes",)
    assert selection.unowned_paths == ()
    assert "tests/episodes" in selection.targets
    assert "tests/invariants" in selection.targets
    assert "tests/architecture/test_cross_scope_flow_schema.py" in selection.targets
    assert "tests/episodes/test_stream_registry.py" in selection.targets


@pytest.mark.parametrize(
    "path",
    [
        "docs/architecture/cross-scope-flow.md",
        "schemas/_defs.schema.json",
        "tests/architecture/test_cross_scope_flow_schema.py",
    ],
)
def test_cross_scope_flow_contract_surface_selects_episodes_coverage(path: str) -> None:
    selection = select_tests([path])

    assert selection.full_suite is False
    assert selection.subsystems == ("episodes",)
    assert selection.unowned_paths == ()
    if path.startswith("tests/"):
        assert "tests/episodes" not in selection.targets
    else:
        assert "tests/episodes" in selection.targets
        assert "tests/invariants" in selection.targets
    assert "tests/architecture/test_cross_scope_flow_schema.py" in selection.targets


def test_standing_questions_store_change_selects_owned_coverage() -> None:
    selection = select_tests(
        [
            "app/standing_questions/projection.py",
            "schemas/question-note.schema.json",
            "tests/standing_questions/test_question_projection.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("standing_questions",)
    assert selection.unowned_paths == ()
    assert "tests/standing_questions" in selection.targets
    assert "tests/standing_questions/test_question_projection.py" in selection.targets


def test_standing_questions_migration_change_is_never_narrowed_to_its_owner() -> None:
    # Review finding on PR #3481: the standing_questions migration used to be listed
    # as one of the subsystem's own owned prefixes, which routed a schema change to
    # only tests/standing_questions instead of the full suite -- a migration's blast
    # radius is cross-cutting, not subsystem-local. Mixed with an unrelated owned
    # file too, to prove the migration path forces full-suite rather than just
    # widening the standing_questions selection.
    selection = select_tests(
        [
            "app/standing_questions/projection.py",
            "app/alembic/versions/4d1e0c9a3329_standing_questions_projection.py",
        ]
    )

    assert selection.full_suite is True
    assert selection.reason == "database migration or schema surface changed"


def test_any_alembic_versions_migration_change_selects_full_suite() -> None:
    # The general case behind the standing_questions-specific finding above:
    # app/alembic/versions/ is the real migrations directory in this repo (there is
    # no top-level alembic/), so any migration file -- not just standing_questions'
    # -- must resolve to full-suite, never "unowned" or a narrow subsystem match.
    selection = select_tests(["app/alembic/versions/1a739d9494af_decisions_fk_set_null.py"])

    assert selection.full_suite is True
    assert selection.reason == "database migration or schema surface changed"
    assert "tests --ignore=tests/e2e" in selection.pytest_args


def test_bundle_schema_and_invariant_change_selects_episodes_coverage() -> None:
    selection = select_tests(
        [
            "schemas/metadata-bundle.schema.json",
            "tests/invariants/test_episode_binding.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("episodes",)
    assert selection.unowned_paths == ()
    assert "tests/invariants" in selection.targets
    assert "tests/invariants/test_episode_binding.py" in selection.targets

def test_api_served_static_page_change_selects_api_coverage() -> None:
    """The pages the API serves are co-owned surface, not an unowned app/ path.

    `app/api/app.py` mounts `app/web/static`, and tests/api asserts on the
    served HTML/JS directly, so a Signboard UI-copy change must select that
    coverage instead of failing closed (exit 2) as unowned runtime code.
    builder_system co-owns the prefix because the static pages (signboard,
    cockpit) render dispatcher/BuilderOps state whose regressions live in
    tests/dispatcher and tests/builderops (#4439 + #4406 both declare this
    co-ownership in the subsystem map).
    """
    selection = select_tests(["app/web/static/signboard.js"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system", "companion_ui")
    assert selection.unowned_paths == ()
    assert "tests/api" in selection.targets
    assert "tests/dispatcher" in selection.targets


def test_builder_system_change_selects_its_own_regression_tests() -> None:
    selection = select_tests(["app/builderops/cli.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert "tests/builderops" in selection.targets
    assert "tests/governance" in selection.targets
    assert "tests/architecture/test_builderops_store_boundary.py" in selection.targets


def test_subprocess_pythonpath_helper_change_selects_builder_system_regressions() -> None:
    helper_path = "tests/helpers/subprocess_pythonpath.py"
    regression_path = "tests/helpers/test_subprocess_pythonpath.py"

    selection = select_tests([helper_path, regression_path])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert selection.unowned_paths == ()
    assert "tests/builderops" in selection.targets
    assert "tests/governance" in selection.targets
    assert helper_path in selection.targets
    assert regression_path in selection.targets


def test_runtime_start_harness_change_selects_ops_deploy_regressions() -> None:
    selection = select_tests(
        [
            "tests/helpers/runtime_start_harness.py",
            "tests/runtime/test_start_full_system_version_marker.py",
        ]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("ops_deploy",)
    assert selection.unowned_paths == ()
    assert "tests/ops" in selection.targets
    assert "tests/scripts" in selection.targets
    assert "tests/deploy" in selection.targets
    assert "tests/helpers/runtime_start_harness.py" in selection.targets
    assert "tests/runtime/test_start_full_system_version_marker.py" in selection.targets


def test_governance_test_change_is_owned_by_builder_system() -> None:
    selection = select_tests(["tests/governance/test_project_pickup_deprecation.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert selection.unowned_paths == ()
    assert "tests/governance/test_project_pickup_deprecation.py" in selection.targets


def test_import_linter_config_change_selects_builder_system_regressions() -> None:
    """The architecture-fitness config must not fail selector ownership first."""
    selection = select_tests(["importlinter.ini"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert selection.unowned_paths == ()
    assert "tests/builderops" in selection.targets
    assert "tests/governance" in selection.targets


def test_cli_standing_questions_migration_file_resolves_to_full_suite() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/alembic/versions/4d1e0c9a3329_standing_questions_projection.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "full_suite=true" in result.stdout
    assert "reason=database migration or schema surface changed" in result.stdout


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


def test_agent_surface_combinations_never_resolve_unowned() -> None:
    """#4335: the whole {AGENTS.md, CLAUDE.md, .codex/**, docs/**} surface #4330
    widened `ci-smoke.yaml`'s `code` paths-filter for must never fall through
    every SUBSYSTEMS prefix into `unowned` (exit 2), no matter how its members
    are combined on one PR."""
    import itertools

    universe = (
        "AGENTS.md",
        "CLAUDE.md",
        ".codex/AGENTS.md",
        ".codex/skills/x/SKILL.md",
        ".codex/agents/reviewer.toml",
        ".codex/config.toml",
        "docs/STATUS.md",
        "docs/ARCHITECTURE.md",
        "README.md",
    )

    for size in (1, 2, 3):
        for combo in itertools.combinations(universe, size):
            selection = select_tests(list(combo))
            assert selection.subsystems != ("unowned",), combo
            assert selection.unowned_paths == (), combo
            assert selection.full_suite is False, combo


def test_claude_md_is_symmetric_with_agents_md_in_governance_only() -> None:
    agents_only = select_tests(["AGENTS.md"])
    agents_and_claude = select_tests(["AGENTS.md", "CLAUDE.md"])

    assert agents_only.subsystems == ("governance",)
    assert agents_and_claude.subsystems == ("governance",)
    assert agents_and_claude.reason == "governance-only PR"


def test_docs_only_lane_selects_tests_governance() -> None:
    selection = select_tests(["docs/ARCHITECTURE.md"])

    assert selection.full_suite is False
    assert selection.subsystems == ("docs",)
    assert "tests/governance" in selection.targets


def test_docs_plus_tests_governance_does_not_narrow_mixed_pr() -> None:
    selection = select_tests(
        ["docs/ARCHITECTURE.md", "tests/governance/test_project_pickup_deprecation.py"]
    )

    assert selection.full_suite is False
    assert "builder_system" in selection.subsystems
    assert "tests/governance/test_project_pickup_deprecation.py" in selection.targets


@pytest.mark.parametrize("paths", [
    ["README.md"], ["docs/TESTING.md"], [".codex/skills/issue-to-code/SKILL.md", "AGENTS.md"],
])
def test_text_only_changes_keep_contract_tests_without_product_gates(paths: list[str]) -> None:
    assert selector.requires_runtime_checks(paths) is False
    assert select_tests(paths).targets


@pytest.mark.parametrize("paths", [
    [], ["docs/TESTING.md", "app/cli.py"], ["docs/eval/classification_golden.yaml"],
    [".codex/helper.py"], ["tests/test_example.py"], ["vault/note.md"],
    ["requirements.txt"], [".github/workflows/integration-nightly.yaml"],
])
def test_runtime_gate_selection_is_conservative(paths: list[str]) -> None:
    assert selector.requires_runtime_checks(paths) is True


def test_ci_contract_helpers_have_an_eligible_paired_owner_doc() -> None:
    from scripts.docs_guard_logic import GOVERNANCE_TEMPORAL_ENFORCEMENT, requires_temporal_owner_doc

    for helper in selector.CI_CONTRACT_PATHS:
        if not helper.startswith("scripts/"):
            continue
        owner_doc = GOVERNANCE_TEMPORAL_ENFORCEMENT.get(helper)
        assert owner_doc in selector.CI_CONTRACT_PATHS, helper
        assert not requires_temporal_owner_doc([helper, owner_doc])
        assert requires_temporal_owner_doc([helper])


@pytest.mark.parametrize("path", (
    ".github/workflows/ci-smoke.yaml", "scripts/select_pr_tests.py",
    "scripts/await_pr_checks.sh", "scripts/ci_stall_classifier.py",
    "tests/scripts/test_select_pr_tests.py", "docs/development/DEV_WORKFLOW.md",
))
def test_exact_ci_contracts_execute_focused_proof_without_product_gates(path: str) -> None:
    selection = select_tests([path])

    assert selector.requires_runtime_checks([path]) is False
    assert selection.reason == "CI contract-only PR"
    assert "tests/governance" in selection.targets
    assert "tests/ops/test_ci_workflow.py" in selection.targets
    assert selector.STATIC_TARGET_COLLECTABILITY_FITNESS in selection.targets
    assert not {"tests/architecture", "tests/scripts", "tests/ops"} & set(selection.targets)
    assert not set(selector.ALWAYS_TARGETS[2:]) & set(selection.targets)
    if path.startswith("tests/"):
        assert path in selection.targets


@pytest.mark.parametrize("path", sorted(selector.PR_INTAKE_CONTRACT_SOURCE_PATHS))
def test_pr_intake_publication_sources_select_their_direct_readers(path: str) -> None:
    selection = select_tests([path])

    assert selection.full_suite is False
    assert selection.reason == "PR intake/publication contract PR"
    assert selector.STATIC_TARGET_COLLECTABILITY_FITNESS in selection.targets
    assert set(selector.CI_CONTRACT_TARGETS) <= set(selection.targets)
    assert set(selector.PR_INTAKE_CONTRACT_TARGETS) <= set(selection.targets)
    assert not {"tests/builderops", "tests/dispatcher", "tests/scripts", "tests/ops"} & set(selection.targets)
    assert "tests/deploy" not in selection.targets
    assert selector.requires_runtime_checks([path]) is (
        path in selector.PR_INTAKE_RUNTIME_SOURCE_PATHS
    )


def test_exact_pr_intake_publication_change_keeps_nonclosing_and_fenced_merge_proof() -> None:
    paths = [
        ".github/workflows/issue-pr-governance.yml",
        "app/builderops/publication.py",
        "app/dispatcher/verification_contract.py",
        "docs/ARCHITECTURE.md",
        "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md",
        "docs/development/PR_HOT_PATH.md",
        "scripts/pr_body_generator.py",
        "scripts/review_before_ci_gate.py",
        "tests/governance/test_issue_pr_governance.py",
        "tests/ops/test_review_before_ci_gate.py",
        "tests/scripts/test_pr_body_generator.py",
        "tests/scripts/test_publication.py",
    ]
    selection = select_tests(paths)

    assert selection.full_suite is False
    assert selection.reason == "PR intake/publication contract PR"
    assert selector.requires_runtime_checks(paths) is True
    assert set(selector.PR_INTAKE_CONTRACT_TARGETS) <= set(selection.targets)
    assert "tests/governance" in selection.targets
    assert "tests/ops/test_review_before_ci_gate.py" in selection.targets
    assert "tests/architecture/test_pr_hot_path_governance.py" in selection.targets
    assert "tests/architecture/test_agent_skill_entrypoints.py" in selection.targets
    # These direct readers cover explicit non-closing intake, publication
    # writeback and the verified-merge/fenced authority path.
    assert "tests/scripts/test_pr_body_generator.py" in selection.targets
    assert "tests/scripts/test_publication.py" in selection.targets
    assert "tests/dispatcher/test_verified_merge.py" in selection.targets
    assert "tests/dispatcher/test_verification_dispatch.py" in selection.targets
    assert not {"tests/builderops", "tests/dispatcher", "tests/scripts", "tests/ops"} & set(selection.targets)
    assert "tests/deploy" not in selection.targets


@pytest.mark.parametrize("path", (
    "scripts/pr_body_generator.py",
    "scripts/review_before_ci_gate.py",
    "app/builderops/publication.py",
    "app/dispatcher/verification_contract.py",
))
def test_pr_intake_executable_sources_keep_runtime_and_type_gates(path: str) -> None:
    assert selector.requires_runtime_checks([path]) is True


@pytest.mark.parametrize("path", (
    "scripts/select_pr_tests.py",
    "tests/ops/test_review_before_ci_gate.py",
))
def test_generic_ci_contract_does_not_pay_for_intake_publication_readers(path: str) -> None:
    selection = select_tests([path])

    assert selection.reason == "CI contract-only PR"
    assert selector.requires_runtime_checks([path]) is False
    assert not set(selector.PR_INTAKE_CONTRACT_TARGETS) & set(selection.targets)


@pytest.mark.parametrize("path", selector.PR_INTAKE_CONTRACT_TARGETS)
def test_direct_publication_reader_test_alone_uses_its_contract_scope(path: str) -> None:
    selection = select_tests([path])

    assert selection.reason == "PR intake/publication contract PR"
    assert selector.requires_runtime_checks([path]) is False
    assert set(selector.PR_INTAKE_CONTRACT_TARGETS) <= set(selection.targets)
    assert not {"tests/builderops", "tests/dispatcher", "tests/scripts", "tests/ops"} & set(selection.targets)


def test_architecture_doc_only_change_keeps_the_existing_docs_route() -> None:
    path = "docs/ARCHITECTURE.md"
    selection = select_tests([path])

    assert selection.reason == "docs-only PR"
    assert selector.requires_runtime_checks([path]) is False
    assert selection.subsystems == ("docs",)
    assert "tests/architecture" in selection.targets


@pytest.mark.parametrize("foreign_path", (
    "app/builderops/cli.py",
    "app/dispatcher/verification_dispatch.py",
    "app/agents/panel_agent/runtime.py",
    "app/ops/postgres_deploy_linux.py",
    "scripts/post_merge_heavy_tests_verdict.py",
    "scripts/deploy_channel.sh",
    "requirements.txt",
    "tests/conftest.py",
    "tests/ops/conftest.py",
    ".github/workflows/integration-nightly.yaml",
    "app/unknown_ci_helper.py",
))
def test_pr_intake_source_with_foreign_cochange_retains_normal_owner(foreign_path: str) -> None:
    paths = ["app/dispatcher/verification_contract.py", foreign_path]
    selection = select_tests(paths)

    assert selection.reason != "PR intake/publication contract PR"
    assert selector.requires_runtime_checks(paths) is True
    if foreign_path == "app/unknown_ci_helper.py":
        assert selection.subsystems == ("unowned",)
        assert foreign_path in selection.unowned_paths
    elif foreign_path in {"requirements.txt", "tests/conftest.py"}:
        assert selection.full_suite is True
    elif foreign_path == "app/builderops/cli.py":
        assert "tests/builderops" in selection.targets
        assert "tests/dispatcher" in selection.targets
    elif foreign_path == "app/dispatcher/verification_dispatch.py":
        assert "tests/dispatcher" in selection.targets
    elif foreign_path == "app/agents/panel_agent/runtime.py":
        assert any(target.startswith("tests/agents/panel_agent") for target in selection.targets)
    elif foreign_path == "app/ops/postgres_deploy_linux.py":
        assert "tests/ops" in selection.targets
    elif foreign_path == "scripts/deploy_channel.sh":
        assert "tests/deploy" in selection.targets
        assert "tests/deploy" not in selection.deferred_targets
    else:
        assert selection.full_suite or selection.targets


@pytest.mark.parametrize("path", (
    "app/briefing/compose.py", "app/ops/postgres_deploy_linux.py",
    "app/alembic/versions/example.py", "requirements.txt", "tests/conftest.py",
    "scripts/deploy_channel.sh", "scripts/ci_stall_classifier_extra.py",
    "tests/ops/test_host_global_lease.py", "tests/fixtures/await_pr_checks/new.json",
    ".github/workflows/integration-nightly.yaml", "app/unknown_ci_helper.py",
))
def test_ci_contract_mixed_changes_retain_normal_runtime_coverage(path: str) -> None:
    paths = ["scripts/select_pr_tests.py", path]
    selection = select_tests(paths)

    assert selector.requires_runtime_checks(paths) is True
    assert selection.reason != "CI contract-only PR"
    if selection.full_suite:
        assert selection.pytest_args.startswith('-q -m "')
    elif selection.unowned_paths:
        assert path in selection.unowned_paths
    else:
        assert set(selector.ALWAYS_TARGETS) <= set(selection.targets)


def test_product_and_selector_changes_combine_their_real_owners_without_ops() -> None:
    product_paths = ["app/agents/panel_agent/runtime.py", "app/curation/proposal_writer.py", "app/expansion/accept.py"]
    product = select_tests(product_paths)
    combined = select_tests([*product_paths, "scripts/select_pr_tests.py"])

    assert set(product.targets) <= set(combined.targets)
    assert set(selector.CI_CONTRACT_TARGETS) <= set(combined.targets)
    assert "tests/ops" not in combined.targets
    assert "tests/deploy" not in combined.targets
    assert selector.requires_runtime_checks([*product_paths, "scripts/select_pr_tests.py"]) is True


@pytest.mark.parametrize("path", ("app/ops/postgres_deploy_linux.py", "app/tts/config.py"))
def test_ci_helpers_preserve_deploy_proof_without_widening_source_only_prs(path: str) -> None:
    selection = select_tests([path])

    assert "tests/deploy" not in selection.targets
    selection = select_tests([path, "scripts/await_pr_checks.sh"])
    assert "tests/deploy" in selection.targets
    assert "tests/scripts" not in selection.targets
    assert selection.deferred_targets == ()
    assert "tests/deploy" not in select_tests([path, ".github/workflows/ci-smoke.yaml"]).targets


@pytest.mark.parametrize("path", sorted(selector.ISOLATED_TEST_MODULES))
def test_only_modules_execute_named_smoke_and_shared_integrity_checks(path: str) -> None:
    selection = select_tests([path])

    assert selection.reason == "isolated test-only smoke; exhaustive matrix deferred"
    assert set(selection.targets) == {*selector.CI_INTEGRITY_TARGETS, *selector.ISOLATED_TEST_MODULES[path]}
    assert path not in selection.targets
    assert selector.requires_runtime_checks([path]) is False


def test_isolated_smoke_does_not_change_normal_whole_module_collection() -> None:
    path = "tests/ops/test_dormant_ownership_initialization.py"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", selector.PR_MARKER_EXPRESSION, path],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nodes = {line for line in result.stdout.splitlines() if line.startswith(path + "::")}
    assert set(selector.ISOLATED_TEST_MODULES[path]) < nodes
    assert path + "::test_test_preparation_producer_holds_window_until_explicit_initializer[post_stop_interpreter]" in nodes


@pytest.fixture
def test_module_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def create(files: dict[str, str]) -> Path:
        for relative, content in files.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        monkeypatch.setattr(selector, "REPO_ROOT", tmp_path)
        return tmp_path
    return create


@pytest.fixture
def bws_control_repository(test_module_repository):
    def create(extra: dict[str, str] | None = None) -> Path:
        return test_module_repository({
            selector.BWS_CONTROL_INSTALLATION_SOURCE: "def install_file(): pass\n",
            selector.BWS_CONTROL_INSTALLATION_TEST: (
                "from app.ops.bws_control_installation import install_file\n"
                "shared_fixture = 1\ndef test_installation(): pass\n"
            ),
            "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md": "Deployment owner contract.\n",
            **(extra or {}),
        })
    return create


@pytest.mark.parametrize("cochanges", [
    [],
    [selector.BWS_CONTROL_INSTALLATION_TEST],
    [selector.BWS_CONTROL_INSTALLATION_TEST, "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md"],
])
def test_bws_control_source_contract_keeps_ops_runtime_and_complete_proof(
    bws_control_repository, cochanges: list[str],
) -> None:
    bws_control_repository()
    paths = [selector.BWS_CONTROL_INSTALLATION_SOURCE, *cochanges]
    selection = select_tests(paths)

    assert selection.reason == "BWS control installation contract PR"
    assert selection.subsystems == ("ops",)
    assert selection.full_suite is False
    assert selection.unowned_paths == selection.deferred_targets == ()
    assert set(selection.targets) == {*selector.ALWAYS_TARGETS, selector.BWS_CONTROL_INSTALLATION_TEST}
    assert selector.requires_runtime_checks(paths) is True
    assert "tests/ops" not in selection.targets


def test_bws_control_source_contract_allows_covered_consumers_and_selector_metadata(bws_control_repository) -> None:
    source = selector.BWS_CONTROL_INSTALLATION_SOURCE
    test = selector.BWS_CONTROL_INSTALLATION_TEST
    bws_control_repository({
        "scripts/select_pr_tests.py": f"SOURCE = {source!r}\nTEST = {test!r}\n",
        "tests/scripts/test_select_pr_tests.py": f"TEST = {test!r}\nselect_tests([{source!r}, {test!r}])\n",
        "tests/ci/test_bws_contract.py": "from app.ops.bws_control_installation import install_file\n",
        "tests/architecture/test_outbox_producer_durability.py": "from tests.ci.test_bws_contract import install_file\n",
    })

    assert select_tests([source, test]).reason == "BWS control installation contract PR"


@pytest.mark.parametrize("metadata", ["scripts/select_pr_tests.py", "tests/scripts/test_select_pr_tests.py"])
@pytest.mark.parametrize("statement", [
    "from app.ops.bws_control_installation import install_file",
    "from tests.ops.test_bws_control_installation import shared_fixture",
    "import importlib\nimportlib.import_module('app.ops.bws_control_installation')",
    "from pathlib import Path\nPath('app/ops/bws_control_installation.py').read_text()",
    "from pathlib import Path\nSOURCE = 'app/ops/bws_control_installation.py'\nPath(SOURCE).read_text()",
    "from pathlib import Path\nSOURCE = 'app/ops/bws_control_installation.py'\nPath(SOURCE).read_text()\nSOURCE = 'unrelated'",
    "from pathlib import Path as File\nSOURCE = 'app/ops/bws_control_installation.py'\nFile(SOURCE).read_text()",
    "SOURCE = 'app/ops/bws_control_installation.py'\nimport importlib\nimportlib.import_module(module_name)",
])
def test_bws_control_metadata_execution_consumers_restore_ops_coverage(
    bws_control_repository, metadata: str, statement: str,
) -> None:
    bws_control_repository({metadata: statement + "\n"})

    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets


def test_bws_control_metadata_test_consumer_requires_complete_file_coverage(
    bws_control_repository, monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = selector.STATIC_TARGET_COLLECTABILITY_FITNESS.split("::", 1)[0]
    bws_control_repository({consumer: "from app.ops.bws_control_installation import install_file\n"})
    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets

    monkeypatch.setattr(selector, "ALWAYS_TARGETS", (*selector.ALWAYS_TARGETS, consumer))
    selection = select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE])
    assert selection.reason == "BWS control installation contract PR"
    assert consumer in selection.targets


@pytest.mark.parametrize("consumer,statement", [
    ("app/ops/caller.py", "import app.ops.bws_control_installation"),
    ("app/ops/caller.py", "from .bws_control_installation import install_file"),
    ("tests/ops/test_caller.py", "from app.ops import bws_control_installation"),
    ("tests/ops/test_caller.py", "from bws_control_installation import install_file"),
    ("tests/ops/test_caller.py", "import importlib\nimportlib.import_module('app.ops.bws_control_installation')"),
    ("tests/ops/test_caller.py", "import importlib\nimportlib.import_module('.bws_control_installation', package='app.ops')"),
    ("tests/ops/test_caller.py", "from .test_bws_control_installation import shared_fixture"),
    ("tests/ops/test_caller.py", "from test_bws_control_installation import shared_fixture"),
    ("scripts/read_control.py", "from pathlib import Path\nPath('app/ops/bws_control_installation.py').read_text()"),
    ("scripts/read_control.py", "from pathlib import Path\nPath('tests/ops/test_bws_control_installation.py').read_text()"),
    ("scripts/read_control.py", "from pathlib import Path\nPath('bws_control_installation.py').read_text()"),
    ("scripts/read_control.py", "from pathlib import Path\nPath('./app/ops/bws_control_installation.py').read_text()"),
    ("scripts/read_control.py", "from pathlib import Path\nPath('./tests/ops/test_bws_control_installation.py').read_text()"),
])
def test_bws_control_outside_source_or_fixture_consumers_restore_ops_coverage(
    bws_control_repository, consumer: str, statement: str,
) -> None:
    bws_control_repository({consumer: statement + "\n"})
    selection = select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE, selector.BWS_CONTROL_INSTALLATION_TEST])

    assert selection.reason == "matched subsystem SoI"
    assert "tests/ops" in selection.targets
    assert selector.requires_runtime_checks([selector.BWS_CONTROL_INSTALLATION_SOURCE]) is True


def test_bws_control_transitive_consumer_of_covered_ci_fixture_restores_ops_coverage(bws_control_repository) -> None:
    bws_control_repository({
        "tests/ci/test_control.py": "from app.ops.bws_control_installation import install_file\n",
        "tests/ops/test_caller.py": "from tests.ci.test_control import install_file\n",
    })

    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets


@pytest.mark.parametrize("path,content", [
    (selector.BWS_CONTROL_INSTALLATION_SOURCE, "def invalid(:\n"),
    (selector.BWS_CONTROL_INSTALLATION_SOURCE, "from ...unknown import install_file\n"),
    (selector.BWS_CONTROL_INSTALLATION_SOURCE, "import importlib\nimportlib.import_module(module_name)\n"),
    (selector.BWS_CONTROL_INSTALLATION_TEST, "shared_fixture = 1\n"),
    (selector.BWS_CONTROL_INSTALLATION_TEST, "def pytest_configure(config): pass\ndef test_installation(): pass\n"),
    ("app/ops/unrelated.py", "def invalid(:\n"),
    ("tests/ci/test_control.py", "from app.ops.bws_control_installation import install_file\nexec('generated_code')\n"),
])
def test_bws_control_uncertain_source_or_consumer_restores_ops_coverage(
    bws_control_repository, path: str, content: str,
) -> None:
    bws_control_repository({path: content})

    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets


@pytest.mark.parametrize("missing", sorted(selector.BWS_CONTROL_INSTALLATION_PATHS))
def test_bws_control_deleted_files_restore_ops_coverage(bws_control_repository, missing: str) -> None:
    root = bws_control_repository()
    (root / missing).unlink()

    assert "tests/ops" in select_tests(sorted(selector.BWS_CONTROL_INSTALLATION_PATHS)).targets


@pytest.mark.parametrize("path", [selector.BWS_CONTROL_INSTALLATION_SOURCE, selector.BWS_CONTROL_INSTALLATION_TEST])
@pytest.mark.parametrize("failure", ["untracked", "symlink"])
def test_bws_control_untracked_or_symlink_contract_restores_ops_coverage(
    bws_control_repository, path: str, failure: str,
) -> None:
    root = bws_control_repository()
    if failure == "untracked":
        subprocess.run(["git", "-C", str(root), "rm", "--cached", "--", path], check=True, capture_output=True)
    else:
        target = root / path
        saved = target.with_suffix(".saved")
        target.rename(saved)
        target.symlink_to(saved.name)
    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets


@pytest.mark.parametrize("old", [selector.BWS_CONTROL_INSTALLATION_SOURCE, selector.BWS_CONTROL_INSTALLATION_TEST])
def test_bws_control_renamed_contract_restores_ops_coverage(bws_control_repository, old: str) -> None:
    root = bws_control_repository()
    new = str(Path(old).with_stem(Path(old).stem + "_renamed"))
    (root / old).rename(root / new)

    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE, old, new]).targets


@pytest.mark.parametrize("extra", [
    "app/ops/postgres_deploy_linux.py", "tests/ops/test_other.py", "tests/ops/conftest.py",
    "scripts/select_pr_tests.py", "docs/deployment/OTHER.md", "requirements.txt",
])
def test_bws_control_mixed_changes_keep_normal_owners(bws_control_repository, extra: str) -> None:
    bws_control_repository({extra: ""})
    paths = [selector.BWS_CONTROL_INSTALLATION_SOURCE, extra]
    selection = select_tests(paths)

    assert selection.reason != "BWS control installation contract PR"
    assert selection.full_suite or "tests/ops" in selection.targets
    assert selector.requires_runtime_checks(paths) is True


@pytest.mark.parametrize("failure", ["inventory", "read", "encoding", "symlink"])
def test_bws_control_census_uncertainty_restores_ops_coverage(
    bws_control_repository, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    unrelated = "app/ops/unrelated.py"
    root = bws_control_repository({unrelated: "value = 1\n"})
    if failure == "inventory":
        def failed_inventory(*args, **kwargs):
            raise subprocess.CalledProcessError(1, args[0])
        monkeypatch.setattr(selector.subprocess, "run", failed_inventory)
    elif failure == "read":
        read_text = Path.read_text
        def failed_read(path, *args, **kwargs):
            if path == root / unrelated:
                raise OSError("fixture read failure")
            return read_text(path, *args, **kwargs)
        monkeypatch.setattr(Path, "read_text", failed_read)
    elif failure == "encoding":
        (root / unrelated).write_bytes(b"\xff")
    else:
        (root / unrelated).unlink()
        (root / unrelated).symlink_to("missing.py")

    assert "tests/ops" in select_tests([selector.BWS_CONTROL_INSTALLATION_SOURCE]).targets


def test_bws_control_doc_and_test_only_changes_keep_existing_routes(bws_control_repository) -> None:
    bws_control_repository()

    assert select_tests(["docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md"]).reason == "docs-only PR"
    assert select_tests([selector.BWS_CONTROL_INSTALLATION_TEST]).reason == "test modules and their static consumers"
    assert select_tests(["scripts/select_pr_tests.py"]).reason == "CI contract-only PR"
    assert select_tests(["app/builderops/publication.py"]).reason == "PR intake/publication contract PR"
    isolated = next(iter(selector.ISOLATED_TEST_MODULES))
    assert select_tests([isolated]).reason == "isolated test-only smoke; exhaustive matrix deferred"


def test_deploy_test_only_change_keeps_real_consumers_without_sibling_suites() -> None:
    paths = ["tests/deploy/test_postmerge_pg_acceptance.py", "tests/deploy/test_postmerge_dev_test.py"]
    selection = select_tests(paths)

    assert selection.reason == "test modules and their static consumers"
    assert "ops_deploy" in selection.subsystems
    assert set(paths) | set(selector.CI_INTEGRITY_TARGETS) | {
        "tests/release_channels/test_pr_candidate_verification_workflow.py",
        "tests/release_channels/test_stable_promotion_from_test.py",
        "tests/ops/test_native_web_lock_lifecycle.py",
        "tests/ops/test_native_journaling_acceptance.py",
        "tests/ops/test_native_web_acceptance.py",
    } <= set(selection.targets)
    assert not {"tests/ops", "tests/scripts", "tests/deploy", *selector.ALWAYS_TARGETS[2:]} & set(selection.targets)
    assert selector.requires_runtime_checks(paths) is True


@pytest.mark.parametrize("statement", [
    "from tests.deploy.test_seed import shared",
    "from .test_seed import shared",
    "from test_seed import shared",
    "import importlib\nshared = importlib.import_module('tests.deploy.test_seed')",
    "import importlib\nshared = importlib.import_module('.test_seed', package='tests.deploy')",
])
def test_test_module_consumers_follow_absolute_relative_bare_and_literal_imports(
    test_module_repository, statement: str,
) -> None:
    test_module_repository({
        "tests/deploy/test_seed.py": "shared = 1\ndef test_seed(): pass\n",
        "tests/deploy/test_consumer.py": statement + "\ndef test_consumer(): pass\n",
        "tests/deploy/test_unrelated.py": "def test_unrelated(): pass\n",
    })
    selection = select_tests(["tests/deploy/test_seed.py"])
    assert set(selection.targets) == {*selector.CI_INTEGRITY_TARGETS,
                                      "tests/deploy/test_seed.py", "tests/deploy/test_consumer.py"}


def test_test_module_consumers_follow_helpers_transitively_and_terminate_cycles(test_module_repository) -> None:
    test_module_repository({
        "tests/deploy/test_seed.py": "from tests.ops.test_consumer import marker\ndef test_seed(): pass\n",
        "tests/ops/helper.py": "from tests.deploy.test_seed import test_seed\n",
        "tests/ops/test_consumer.py": "from .helper import test_seed\nmarker = 1\ndef test_consumer(): pass\n",
    })
    selection = select_tests(["tests/deploy/test_seed.py"])
    assert set(selection.targets) == {*selector.CI_INTEGRITY_TARGETS,
                                      "tests/deploy/test_seed.py", "tests/ops/test_consumer.py"}


@pytest.mark.parametrize("consumer,content", [
    ("app/consumer.py", "from tests.deploy.test_seed import shared\n"),
    ("tests/conftest.py", "from tests.deploy.test_seed import shared\n"),
    ("tests/ops/__init__.py", "from tests.deploy.test_seed import shared\n"),
    ("tests/ops/test_consumer.py", "from tests.deploy.test_seed import shared\npytest_plugins = []\n"),
    ("tests/ops/test_consumer.py", "from tests.deploy.test_seed import shared\ndef pytest_configure(config): pass\n"),
    ("tests/ops/test_consumer.py", "from tests.deploy.test_seed import shared\nimport importlib\nimportlib.import_module(name)\n"),
])
def test_test_module_shared_or_unclear_consumers_keep_broad_ownership(
    test_module_repository, consumer: str, content: str,
) -> None:
    test_module_repository({"tests/deploy/test_seed.py": "shared = 1\ndef test_seed(): pass\n", consumer: content})
    selection = select_tests(["tests/deploy/test_seed.py"])
    assert selection.reason == "matched subsystem SoI"
    assert {"tests/ops", "tests/scripts"} <= set(selection.targets)


@pytest.mark.parametrize("content", [
    "import importlib\nimportlib.import_module(module_name)\ndef test_seed(): pass\n",
    "from unknown import *\ndef test_seed(): pass\n",
    "exec('import generated_helper')\ndef test_seed(): pass\n",
    "def test_seed(:\n",
    "shared = 1\n",  # A helper does not become a test module through its filename.
])
def test_test_module_opaque_changed_code_keeps_broad_ownership(test_module_repository, content: str) -> None:
    test_module_repository({"tests/deploy/test_seed.py": content})
    assert select_tests(["tests/deploy/test_seed.py"]).reason == "matched subsystem SoI"


@pytest.mark.parametrize("extra", [
    "tests/ops/conftest.py", "tests/helpers/test_support.py", "tests/fixtures/test_data.py",
    "tests/ops/support.py", "requirements.txt", ".github/workflows/ci-smoke.yaml",
    "app/ops/postgres_deploy_linux.py", "tests/unknown_area/test_unknown.py",
])
def test_test_module_shared_configuration_mixed_and_unknown_paths_keep_existing_routes(
    test_module_repository, extra: str,
) -> None:
    test_module_repository({"tests/deploy/test_seed.py": "def test_seed(): pass\n", extra: ""})
    assert select_tests(["tests/deploy/test_seed.py", extra]).reason != "test modules and their static consumers"


def test_test_module_deleted_and_renamed_paths_keep_broad_ownership(
    test_module_repository, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = test_module_repository({"tests/deploy/test_old.py": "def test_old(): pass\n"})
    monkeypatch.chdir(root)
    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                        "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)
    git("commit", "-qm", "initial")
    git("mv", "tests/deploy/test_old.py", "tests/deploy/test_new.py")
    git("commit", "-qm", "rename")

    paths = selector.changed_files_from_git("HEAD^", "HEAD")
    assert set(paths) == {"tests/deploy/test_old.py", "tests/deploy/test_new.py"}
    selection = select_tests(paths)
    assert selection.reason == "matched subsystem SoI"
    assert {"tests/ops", "tests/scripts"} <= set(selection.targets)
    assert "tests/deploy/test_old.py" not in selector._existing_test_targets(selection.targets)
    assert "tests/deploy/test_new.py" in selector._existing_test_targets(selection.targets)


@pytest.mark.parametrize("shared_path", (
    "tests/conftest.py", "tests/ops/conftest.py", "tests/helpers/test_runtime_support.py",
    "tests/fixtures/test_case.py", "app/ops/native_source_admission.py",
    "tests/integration/test_watcher_cross_process_rebind.py",
))
def test_shared_fixture_and_product_changes_are_not_test_only(shared_path: str) -> None:
    paths = ["tests/ops/test_dormant_ownership_initialization.py", shared_path]
    selection = select_tests(paths)

    assert selection.subsystems != ("tests",)
    assert "tests/ops" in selection.targets or selection.full_suite
    assert selector.requires_runtime_checks([shared_path]) is True
    assert selector.requires_runtime_checks(paths) is True


def test_github_output_exposes_text_only_runtime_gate_decision(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, "scripts/select_pr_tests.py", "--changed-file", "AGENTS.md",
        "--github-output", str(output),
    ], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields["runtime_checks"] == "false"
    assert fields["pytest_args"]


# --- Heavy-target deferral (#6154) -------------------------------------------

POST_MERGE_HEAVY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "post-merge-heavy-tests.yml"


@pytest.mark.parametrize("paths,deferred", [
    (["scripts/select_pr_tests.py"], ()),
    (["scripts/select_pr_tests.py", "docs/development/PR_HOT_PATH.md", "AGENTS.md"], ()),
    (["scripts/validate_issue_readiness.py", ".github/workflows/issue-pr-governance.yml"], ("tests/deploy",)),
    (["tests/scripts/test_select_pr_tests.py"], ()),
])
def test_selector_change_keeps_heavy_deploy_off_pr_path(paths: list[str], deferred: tuple[str, ...]) -> None:
    selection = select_tests(paths)

    assert selection.full_suite is False
    assert "tests/deploy" not in selection.targets
    assert all(
        not target.startswith("tests/deploy/")
        or target == "tests/deploy/test_dockerfile_python_alignment.py"
        for target in selection.targets
    )
    if "scripts/select_pr_tests.py" in paths:
        assert selection.subsystems == ("governance",)
        assert "tests/ops" not in selection.targets
    assert selection.deferred_targets == deferred
    assert "tests/scripts" in selection.targets or "tests/scripts/test_select_pr_tests.py" in selection.targets


def test_selector_reports_deferred_targets_to_github_output(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, "scripts/select_pr_tests.py", "--changed-file", "scripts/validate_issue_readiness.py",
        "--github-output", str(output),
    ], cwd=REPO_ROOT, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "deferred_targets=tests/deploy" in result.stdout
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert fields["deferred_targets"] == "tests/deploy"
    assert "tests/deploy" not in fields["pytest_args"]


@pytest.mark.parametrize("path", [
    ".github/workflows/postmerge-channel-bug.yml",
    "scripts/postmerge_channel_bug.py",
    "scripts/deploy_channel.sh",
    "scripts/lib/deploy_channel_compose.sh",
    "config/deploy/prod.env",
    "app/config/database.py",
    "app/release_channels/prepare_promotion.py",
    "ops/scalar-rollback/nginx.conf",
    "tests/deploy/conftest.py",
    "docker-compose.test.yml",
    "requirements.txt",
    "Dockerfile",
])
def test_deploy_trigger_keeps_heavy_deploy_suite_on_pr_path(path: str) -> None:
    selection = select_tests([path])

    assert selection.deferred_targets == ()
    if path in selector.FULL_SUITE_EXACT:
        assert selection.full_suite is True
    # Full-suite inputs (compose, requirements) run all of tests/ without an
    # --ignore; unowned paths fail selection closed before any deferral.
    assert (
        "tests/deploy" in selection.targets
        or (selection.full_suite and "--ignore=tests/deploy" not in selection.pytest_args)
        or selection.unowned_paths == (path,)
    )


def test_scoped_deploy_partitions_preserve_selected_targets(tmp_path: Path) -> None:
    changed = [
        "app/ops/postgres_deploy_linux.py",
        "scripts/postmerge_dev_test.py",
        "tests/deploy/test_postmerge_dev_test.py",
    ]
    selection = select_tests(changed)
    partitions = selector.scoped_deploy_partitions(selection)
    assert selection.full_suite is False
    assert selection.deferred_targets == ()
    assert "tests/deploy" in selection.targets
    assert "tests/deploy/test_postmerge_dev_test.py" in selection.targets
    assert 1 <= len(partitions) <= 4
    flattened = [target for partition in partitions for target in partition]
    assert sorted(flattened) == sorted(selection.targets)
    assert len(flattened) == len(set(flattened))
    assert all(partition for partition in partitions)
    assert all(target.split("::", 1)[0].startswith("tests/ops") for target in partitions[-1])
    assert all(
        not target.split("::", 1)[0].startswith("tests/ops")
        for partition in partitions[:-1]
        for target in partition
    )
    output = tmp_path / "github-output"
    result = subprocess.run(
        [
            sys.executable, "scripts/select_pr_tests.py",
            *(arg for path in changed for arg in ("--changed-file", path)),
            "--github-output", str(output),
        ],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert json.loads(fields["pytest_targets_json"]) == list(selection.targets)
    assert json.loads(fields["scoped_partitions_json"]) == [
        list(partition) for partition in partitions
    ]
    assert json.loads(fields["scoped_execution_units_json"]) == [
        list(unit) for unit in selector.scoped_deploy_execution_units(selection)
    ]
    assert json.loads(fields["scoped_serial_boundary_json"]) == list(
        selector.SCOPED_DEPLOY_SERIAL_BOUNDARY
    )

    release_output = tmp_path / "release-output"
    release_result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/release_channels/prepare_promotion.py",
            "--github-output",
            str(release_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert release_result.returncode == 0, release_result.stdout + release_result.stderr
    release_fields = dict(
        line.split("=", 1) for line in release_output.read_text().splitlines()
    )
    assert json.loads(release_fields["scoped_partitions_json"])
    assert json.loads(release_fields["scoped_serial_boundary_json"]) == []

    mixed_output = tmp_path / "mixed-output"
    mixed_result = subprocess.run(
        [
            sys.executable,
            "scripts/select_pr_tests.py",
            "--changed-file",
            "app/release_channels/prepare_promotion.py",
            "--changed-file",
            "app/instance/runtime.py",
            "--github-output",
            str(mixed_output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert mixed_result.returncode == 0, mixed_result.stdout + mixed_result.stderr
    mixed_fields = dict(line.split("=", 1) for line in mixed_output.read_text().splitlines())
    assert json.loads(mixed_fields["scoped_serial_boundary_json"]) == [
        "tests/ops/test_instance_state_volume_contract.py"
    ]


@pytest.mark.parametrize("path", [
    "docs/RELEASE_CHANNELS/README.md",
    "tests/release_channels/test_channel_isolation_preflight.py",
])
def test_release_channel_docs_and_tests_do_not_pull_heavy_deploy_suite(path: str) -> None:
    # Neither is read by tests/deploy; only the release-channel code is.
    assert "tests/deploy" not in select_tests([path]).targets


def test_scoped_deploy_execution_units_balance_slow_directory_without_coverage_drift() -> None:
    selection = select_tests([
        "app/ops/postgres_deploy_linux.py",
        "scripts/postmerge_dev_test.py",
    ])

    units = selector.scoped_deploy_execution_units(selection)
    assert selection.full_suite is False
    assert "tests/deploy" in selection.targets
    assert 1 <= len(units) <= selector.SCOPED_EXECUTION_MAX_WORK_UNITS
    assert all(unit for unit in units)

    serial = units[-1]
    assert all(
        target.split("::", 1)[0] == "tests/ops"
        or target.split("::", 1)[0].startswith("tests/ops/")
        for target in serial
    )
    parallel = units[:-1]
    flattened = [target for unit in parallel for target in unit]
    deploy_files = set(selector._scoped_deploy_test_files())
    assert deploy_files <= {
        target.split("::", 1)[0]
        for target in flattened
        if target.split("::", 1)[0].startswith("tests/deploy/")
    }
    assert len(flattened) == len(set(flattened))
    assert "tests/deploy" not in flattened
    assert all(
        target.split("::", 1)[0] != "tests/ops"
        and not target.split("::", 1)[0].startswith("tests/ops/")
        for target in flattened
    )


def test_changed_heavy_test_file_still_runs_on_pr_path() -> None:
    changed = "tests/deploy/test_deploy_channel.py"
    selection = select_tests([changed])

    assert changed in selection.targets
    assert "tests/deploy" not in selection.targets
    assert selection.deferred_targets == ("tests/deploy",)


def test_full_suite_selection_ignores_deferred_heavy_targets() -> None:
    selection = select_tests(["pyproject.toml"])

    assert selection.full_suite is True
    assert selection.deferred_targets == ("tests/deploy",)
    assert "--ignore=tests/deploy" in selection.pytest_args
    assert "tests/deploy" not in select_tests(["pyproject.toml", "scripts/deploy_channel.sh"]).deferred_targets


def test_liveness_checker_source_selects_its_contract_tests(tmp_path: Path) -> None:
    target = "tests/governance/test_dev_delivery_liveness_workflow.py"
    selection = select_tests(["scripts/dev_delivery_liveness.py"])
    assert target in selection.targets
    assert selection.deferred_targets == ("tests/deploy",)
    assert "tests/governance" in select_tests([".github/workflows/dev-delivery-liveness.yml"]).targets
    assert target not in select_tests(["scripts/postmerge_channel_bug.py"]).targets
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, "scripts/select_pr_tests.py", "--changed-file", "scripts/dev_delivery_liveness.py",
        "--github-output", str(output),
    ], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert target in fields["pytest_args"].split()
    assert fields["deferred_targets"] == "tests/deploy"


def test_deploy_heavy_triggers_cover_scripts_referenced_by_deploy_tests() -> None:
    # Census: every repo file tests/deploy reads directly (scripts, compose
    # files, requirements, Dockerfile, deploy config, app/ modules by path)
    # must keep the heavy deploy suite on the PR path, or a change to that
    # input would merge before the post-merge heavy run sees it.
    import re

    triggers = selector.HEAVY_PR_DEFERRED_TARGETS["tests/deploy"]
    literal = re.compile(r"[\"']([A-Za-z0-9_./][A-Za-z0-9_./@+=,-]*)[\"']")
    joined = re.compile(r'"([A-Za-z0-9_.@+=,-]+)"\s*/\s*"([A-Za-z0-9_.@+=,-]+)"')
    single = re.compile(r'/\s*"([A-Za-z0-9_.@+=,-]+)"')
    referenced: set[str] = set()
    for test_file in (REPO_ROOT / "tests" / "deploy").rglob("*.py"):
        text = test_file.read_text(encoding="utf-8")
        referenced.update(match.group(1).removeprefix("./") for match in literal.finditer(text))
        referenced.update(f"{a}/{b}" for a, b in joined.findall(text))
        referenced.update(single.findall(text))
    existing = {
        path for path in referenced
        if path and not path.startswith(("/", "tests/")) and path != ".git"
        and (REPO_ROOT / path).is_file()
    }

    for required in (
        "scripts/deploy_channel.sh", "docker-compose.test.yml", "requirements.txt", "Dockerfile",
        "config/systemd/yggdrasil-bws-deploy@.service",
    ):
        assert required in existing, f"census no longer sees {required}"
    uncovered = sorted(
        path for path in existing
        if path not in triggers
        and not any(t.endswith("/") and path.startswith(t) for t in triggers)
    )
    assert uncovered == []


def test_post_merge_heavy_workflow_runs_selector_heavy_targets() -> None:
    import yaml

    workflow = yaml.safe_load(POST_MERGE_HEAVY_WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML parses the bare `on:` key as boolean True.

    # The VM verdict replaced the per-push run (#6158); the GitHub-hosted job
    # is the watchdog/manual fallback.
    assert "push" not in triggers
    assert triggers["schedule"]
    assert "workflow_dispatch" in triggers
    assert workflow["concurrency"]["cancel-in-progress"] is False
    heavy = workflow["jobs"]["heavy-tests"]
    text = POST_MERGE_HEAVY_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/select_pr_tests.py --print-heavy-targets" in text
    assert "refusing a vacuous green run" in text
    run_step = next(s for s in heavy["steps"] if s.get("name") == "Run heavy not-pg tests")
    assert run_step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
    assert "set -o pipefail" in run_step["run"]
    assert "PR_MARKER_EXPRESSION" in run_step["run"]

    result = subprocess.run(
        [sys.executable, "scripts/select_pr_tests.py", "--print-heavy-targets"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    assert result.stdout.split() == list(selector.HEAVY_PR_DEFERRED_TARGETS)


def test_post_merge_heavy_alert_body_passes_readiness_validation(tmp_path: Path) -> None:
    import yaml

    import scripts.post_merge_heavy_tests_alert as alert
    from scripts.validate_issue_readiness import classify_issue_body

    body = alert.render_alert_body(
        sha="0123abc", run_url="https://github.com/o/r/actions/runs/1", targets="tests/deploy"
    )
    report = classify_issue_body(body, labels=list(alert.ALERT_LABELS))
    assert report.readiness_classification == "ready_candidate", report
    assert {"type:bug", "prio:high"} <= set(alert.ALERT_LABELS)
    assert "0123abc" in body and "tests/deploy" in body

    workflow = yaml.safe_load(POST_MERGE_HEAVY_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["alert"]
    assert "heavy-tests" in job["needs"]
    assert "always()" in job["if"] and "cancelled" in job["if"]
    assert job["permissions"]["issues"] == "write"
    script = job["steps"][-1]["run"]
    assert "gh issue create" in script and "scripts/post_merge_heavy_tests_alert.py" in script
    assert "gh issue comment" in script and "gh issue close" in script
    # A red run must also leave the workflow red, never a quietly green alert job.
    assert script.rstrip().endswith("exit 1")


def test_full_suite_lane_skips_deferred_heavy_shards(tmp_path: Path) -> None:
    import os
    import re

    import yaml

    for name in ("tests/alpha/test_a.py", "tests/deploy/test_heavy.py", "tests/ops/test_host.py",
                 "tests/invariants/test_vault_multiwriter.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "print('RAN ' + ' '.join(a for a in sys.argv[1:] if a.startswith('tests/')))\n"
        "print('1 passed')\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    smoke = yaml.safe_load((REPO_ROOT / ".github/workflows/ci-smoke.yaml").read_text(encoding="utf-8"))
    step = next(s for s in smoke["jobs"]["pr-unit-tests-not-pg"]["steps"]
                if s.get("name") == "Run shared not-pg unit tests in process shards")
    assert step["env"]["DEFERRED_TARGETS"] == "${{ steps.select-tests.outputs.deferred_targets }}"
    script = re.sub(r"\$\{\{.*?\}\}", "fixture", step["run"])
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=30,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **step["env"],
             "DEFERRED_TARGETS": "tests/deploy", "RUNNER_TEMP": str(tmp_path / "runner")},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SHARD DEFERRED to post-merge heavy tests: tests/deploy" in result.stderr
    assert "SHARD FINISHED (0): tests/alpha" in result.stdout
    assert "tests/deploy" not in (tmp_path / "runner/pytest-not-pg-shards/shards").read_text()


def test_owner_docs_describe_heavy_target_deferral() -> None:
    strategy = (REPO_ROOT / "docs/development/TEST_STRATEGY_HOT_PATH.md").read_text(encoding="utf-8")
    testing = (REPO_ROOT / "docs/TESTING.md").read_text(encoding="utf-8")
    hot_path = (REPO_ROOT / "docs/development/PR_HOT_PATH.md").read_text(encoding="utf-8")

    assert "## Post-merge heavy tests" in strategy
    for doc in (strategy, testing, hot_path):
        assert "post-merge-heavy-tests.yml" in doc
    assert "HEAVY_PR_DEFERRED_TARGETS" in strategy
    assert "prio:high" in strategy



def test_pinned_controller_bootstrap_selects_real_runtime_and_liveness_coverage(tmp_path: Path) -> None:
    selection = select_tests(['scripts/postmerge_controller.py'])
    assert 'tests/deploy' in selection.targets
    assert 'tests/deploy' not in selection.deferred_targets
    assert 'tests/governance/test_dev_delivery_liveness_workflow.py' in selection.targets
    output = tmp_path / 'pinned-controller-output'
    result = subprocess.run([
        sys.executable, 'scripts/select_pr_tests.py', '--changed-file', 'scripts/postmerge_controller.py',
        '--github-output', str(output),
    ], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    fields = dict(line.split('=', 1) for line in output.read_text().splitlines())
    assert 'tests/deploy' in fields['pytest_args'].split()
    assert 'tests/governance/test_dev_delivery_liveness_workflow.py' in fields['pytest_args'].split()
