from __future__ import annotations

import argparse
import ast
from functools import lru_cache
import importlib.util
import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


STATIC_TARGET_COLLECTABILITY_FITNESS = (
    "tests/scripts/test_select_pr_tests.py::test_static_selector_targets_are_collectable"
)

CI_INTEGRITY_TARGETS = (
    "tests/ci",
    # This test must run on every scoped PR: a deleting/renaming PR otherwise
    # filters its missing static target before pytest has a chance to detect it.
    STATIC_TARGET_COLLECTABILITY_FITNESS,
)

ALWAYS_TARGETS = (
    *CI_INTEGRITY_TARGETS,
    # The outbox producer gates are repo-wide AST censuses over app/, so the PR
    # that breaks them is by definition a PR that adds or edits a producer —
    # and every producer today lives in an OWNED subsystem (heimdal, watcher,
    # api routes, panel, workers, services, receipts, knowledge_acquisition).
    # A scoped selection therefore excluded exactly the PRs these gates exist
    # to catch, and a new producer defaulting to the dropping path could merge
    # with a green required check (#4214 D5). Keep these on Product/runtime
    # scoped PRs; the closed CI-only scope cannot change an app/ producer.
    "tests/architecture/test_outbox_producer_durability.py",
    "tests/architecture/test_outbox_producer_idempotency.py",
    # The MVR-05B context-boundary gate is the same kind of cheap AST census,
    # over request entrypoints spread across many owned subsystems (api routes,
    # agents, MCP, CLI). Scoping it to its own files would skip exactly the PRs
    # that add a global vault lookup to a guarded entrypoint (#6136 review).
    "tests/architecture/test_multi_vault_context_boundaries.py",
)

PR_MARKER_EXPRESSION = (
    "not pg and not alpha_llm and not alpha_llm_live and not panel_llm_e2e "
    "and not eval and not browser_runtime and not human_uat and not uat_integrated_runtime"
)

FULL_SUITE_REASONS = (
    "shared CI/test/runtime configuration changed",
    "database migration or schema surface changed",
    "changed files have no subsystem owner",
)

FULL_SUITE_EXACT = {
    # Shared CLI registration and path resolution affect many runtime
    # subsystems. Never narrow their coverage to a single feature owner.
    "app/cli.py",
    "app/cli/__init__.py",
    # The top-level package initializer is a shared import seam. A change
    # here can alter every runtime package's boot behavior, so require the
    # broad non-PG lane rather than guessing one subsystem owner.
    "app/__init__.py",
    "app/config/paths.py",
    # Canonical runtime DSN resolution. `app/db/db.py::_psycopg_dsn` (already a
    # FULL_SUITE_PREFIX via app/db/) resolves every connection through this
    # module, and the self-owned outbox skip predicate resolves the same
    # question with it (#4214 D1) — so a change here can move any DB-touching
    # subsystem between "connect" and "skip". Never narrow it to one owner.
    "app/config/database.py",
    "conftest.py",
    "pytest.ini",
    "pyproject.toml",
    "requirements.txt",
    "dev-requirements.txt",
    "docker-compose.test.yml",
}

FULL_SUITE_PREFIXES = (
    "alembic/",
    "tests/conftest.py",
    "app/db/",
    "app/testing/",
)

DOCS_TARGETS = (
    "tests/docs",
    "tests/architecture",
    # Human-need E2E scenarios are deferred to post-merge/nightly. Treat a
    # co-changed E2E scenario as scope-neutral for a docs-only PR so the docs
    # contract does not fall through to the fail-closed unowned path.
    "tests/e2e",
    # test_review_before_ci_gate.py reads docs/TESTING.md content directly
    # (#4281); a docs/**-only PR must run it, not only tests/architecture.
    "tests/ops/test_review_before_ci_gate.py",
    # tests/governance/** asserts on docs/** content that routes through THIS
    # branch, not the governance one: only docs/development/** matches
    # _is_governance_only's prefixes, so edits to docs/AGENT_ISSUE_DISPATCHER.md,
    # docs/ARCHITECTURE.md, docs/architecture/SBS_OPERATING_MODEL.md,
    # docs/STATUS.md, docs/ROADMAP.md, docs/DESIGN_HANDOFF_GOVERNANCE.md,
    # docs/adr/**, or docs/testing/invariant-tests.md landed here and never ran
    # test_project_pickup_deprecation.py, test_codex_agents_contract.py,
    # test_known_defects_registry.py, test_issue_pr_governance.py, or
    # test_vault_multiwriter_frontmatter.py — the suites that read those exact
    # files — while the required check still reported success.
    "tests/governance",
)

DOCS_ONLY_EXCLUDED_EXACT = {
    # This owner document is executable CrossScopeFlow contract surface. Route
    # even a docs-only edit through Episodes instead of the generic docs lane.
    "docs/architecture/cross-scope-flow.md",
}

# ARO-03 is an executable route contract despite living in the Stage A docs
# directory.  Its direct supporting documents specify the admitted Overview
# route that these four production-path tests protect; generic docs coverage
# alone would otherwise leave a contract-only change without route proof.
ARO03_ROUTE_CONTRACT_PATHS = (
    "docs/DEVUI.md",
    "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md",
    "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/PARENT_FEATURE_ISSUE.md",
    "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/EXPOSE_LOCAL_OVERVIEW_GET_ROUTE.md",
)

ARO03_ROUTE_TESTS = (
    "tests/api/test_devui_api.py::test_overview_route_reuses_local_admission_and_exact_contract",
    "tests/api/test_devui_api.py::test_overview_route_preserves_no_source_withdrawals",
    "tests/api/test_devui_api.py::test_overview_route_is_get_only",
    "tests/api/test_devui_api.py::test_overview_route_uses_live_composition_and_delivered_composer",
)

DEV_LIVENESS_TESTS = ("tests/governance/test_dev_delivery_liveness_workflow.py",)

# Targets outside SUBSYSTEMS still need the always-run static census.
# Otherwise a renamed proof could be filtered out before CI asks pytest to
# collect it, leaving the exact-path selector green without proof.
STATIC_SELECTOR_NODE_ID_TARGETS = (*ARO03_ROUTE_TESTS, *DEV_LIVENESS_TESTS)

GOVERNANCE_TARGETS = (
    "tests/governance",
    "tests/scripts",
    "tests/ops/test_ci_workflow.py",
    # AGENTS.md and .codex/** route through the governance-only branch (their
    # prefixes are checked before docs-only), but the tests that actually
    # assert on their content live in tests/architecture
    # (test_agent_skill_entrypoints.py, test_pr_hot_path_governance.py) and
    # tests/ops/test_review_before_ci_gate.py (reads AGENTS.md,
    # .codex/skills/verify-promotion/SKILL.md, and
    # .github/pull_request_template.md). Without these, extending the
    # ci-smoke.yaml paths-filter alone would run pytest but still miss the
    # covering assertions for AGENTS.md/.codex/** changes (#4281).
    "tests/architecture",
    "tests/ops/test_review_before_ci_gate.py",
)

# Read-only CI inspection/selection contracts already covered by GOVERNANCE_TARGETS.
# Keep this exact: unrelated scripts, fixtures and operational co-changes retain their owners.
CI_GOVERNANCE_CONTRACT_PATHS = frozenset({
    "scripts/select_pr_tests.py",
    "scripts/replay_pr_test_selection.py",
    "scripts/run_scoped_test_partitions.py",
    "scripts/plan_full_suite_node_shards.py",
    "scripts/await_pr_checks.sh",
    "scripts/ci_stall_classifier.py",
    "scripts/docs_guard_logic.py",
    "scripts/docs_guard.py",
    "tests/scripts/test_select_pr_tests.py",
    "tests/scripts/test_await_pr_checks.py",
    "tests/scripts/test_await_pr_checks_dedupe.py",
    "tests/scripts/test_ci_stall_classifier.py",
    "tests/scripts/test_docs_guard.py",
    "tests/ops/test_ci_workflow.py",
})

# A CI-only edit cannot change Product producers, schemas or runtime behavior.
# Exercise the CI commands and their consumers instead of all script/architecture suites.
CI_CONTRACT_TARGETS = (
    *CI_INTEGRITY_TARGETS,
    "tests/governance",
    "tests/scripts/test_select_pr_tests.py",
    "tests/scripts/test_replay_pr_test_selection.py",
    "tests/scripts/test_await_pr_checks.py",
    "tests/scripts/test_await_pr_checks_dedupe.py",
    "tests/scripts/test_ci_stall_classifier.py",
    "tests/scripts/test_docs_guard.py",
    "tests/ops/test_ci_workflow.py",
    "tests/ops/test_ci_smoke_workflow.py",
    "tests/ops/test_review_before_ci_gate.py",
    "tests/deploy/test_dockerfile_python_alignment.py",
    "tests/architecture/test_ci_smoke_contract.py",
    "tests/architecture/test_companion_ui_sys_path.py",
    "tests/architecture/test_import_boundary.py",
    "tests/architecture/test_pr_hot_path_governance.py",
    "tests/architecture/test_pr_test_selection.py",
    "tests/architecture/test_requirements_consistency.py",
    "tests/architecture/test_agent_skill_entrypoints.py",
    "tests/architecture/test_dispatcher_skill_integration.py",
)
CI_CONTRACT_PATHS = CI_GOVERNANCE_CONTRACT_PATHS | frozenset({
    ".github/workflows/ci-smoke.yaml",
    ".codex/skills/_shared/CI_WAIT_CONTRACT.md",
    "docs/development/TEST_STRATEGY_HOT_PATH.md",
    "docs/development/DEV_WORKFLOW.md",
    "docs/development/DOCUMENTATION_GUARD.md",
    "docs/development/PR_HOT_PATH.md",
    "tests/governance/test_ci_smoke_docs_only_gate.py",
}) | frozenset(
    target.split("::", 1)[0]
    for target in CI_CONTRACT_TARGETS
    if target.split("::", 1)[0].endswith(".py")
)

# Exact PR-intake/publication contract sources have many direct readers across
# BuilderOps, dispatcher, scripts, governance docs and the publication workflow.
# Keep this scope explicit: a changed source selects its complete direct-reader
# set, while an unrelated BuilderOps/dispatcher/script co-change keeps normal
# subsystem routing. The architecture doc is only a tolerated co-change here;
# its own edits continue through the ordinary docs lane.
PR_INTAKE_CONTRACT_SOURCE_PATHS = frozenset({
    ".github/workflows/issue-pr-governance.yml",
    "app/builderops/publication.py",
    "app/dispatcher/verification_contract.py",
    "scripts/pr_body_generator.py",
    "scripts/review_before_ci_gate.py",
})
PR_INTAKE_RUNTIME_SOURCE_PATHS = PR_INTAKE_CONTRACT_SOURCE_PATHS - {
    ".github/workflows/issue-pr-governance.yml",
}
PR_INTAKE_CONTRACT_READER_PATHS = frozenset({
    "docs/ARCHITECTURE.md",
    "docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md",
    "docs/development/PR_HOT_PATH.md",
    "tests/architecture/test_agent_skill_entrypoints.py",
    "tests/architecture/test_pr_hot_path_governance.py",
    "tests/governance/test_autonomous_escalation_contract.py",
    "tests/governance/test_epic_pr_batching_policy.py",
    "tests/governance/test_issue_pr_governance.py",
    "tests/governance/test_project_pickup_deprecation.py",
    "tests/governance/test_skills_consistency_lint.py",
    "tests/governance/test_verification_dispatch_request.py",
    "tests/governance/test_verification_dispatch_workflow.py",
    "tests/governance/test_pr_evidence_pack_workflow.py",
    "tests/ops/test_builderops_package_smoke.py",
    "tests/ops/test_review_before_ci_gate.py",
    "tests/scripts/test_build_pr_evidence_pack.py",
    "tests/scripts/test_closure.py",
    "tests/scripts/test_pr_body_generator.py",
    "tests/scripts/test_publication.py",
    "tests/dispatcher/test_verification_dispatch.py",
    "tests/dispatcher/test_verified_merge.py",
})
PR_INTAKE_CONTRACT_TARGETS = (
    # Direct imports/consumers not already covered by CI_CONTRACT_TARGETS' full
    # governance suite and exact review/architecture readers.
    "tests/dispatcher/test_verification_dispatch.py",
    "tests/dispatcher/test_verified_merge.py",
    "tests/ops/test_builderops_package_smoke.py",
    "tests/scripts/test_build_pr_evidence_pack.py",
    "tests/scripts/test_closure.py",
    "tests/scripts/test_pr_body_generator.py",
    "tests/scripts/test_publication.py",
)

# This filesystem-only helper has one direct test contract and no tracked
# operational caller. New consumers restore ordinary Ops ownership below.
BWS_CONTROL_INSTALLATION_SOURCE = "app/ops/bws_control_installation.py"
BWS_CONTROL_INSTALLATION_TEST = "tests/ops/test_bws_control_installation.py"
BWS_CONTROL_INSTALLATION_PATHS = frozenset({
    BWS_CONTROL_INSTALLATION_SOURCE,
    BWS_CONTROL_INSTALLATION_TEST,
    "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md",
})

# Test-only edits to these unconsumed modules need representative harness proof.
# Product/shared-fixture co-changes and nightly retain their complete matrices.
ISOLATED_TEST_MODULES = {
    "tests/ops/test_dormant_ownership_initialization.py": (
        "tests/ops/test_dormant_ownership_initialization.py::test_exact_admission_preserves_source_and_registry_and_produces_one_authenticated_lease",
        "tests/ops/test_dormant_ownership_initialization.py::test_refusal_matrix_is_before_effects[receipt]",
        "tests/ops/test_dormant_ownership_initialization.py::test_concurrency_and_stale_proof_recheck_all_locks",
        "tests/ops/test_dormant_ownership_initialization.py::test_test_preparation_producer_holds_window_until_explicit_initializer[exact]",
        "tests/ops/test_dormant_ownership_initialization.py::test_test_preparation_producer_holds_window_until_explicit_initializer[foreign_owner]",
        "tests/ops/test_dormant_ownership_initialization.py::test_test_preparation_producer_holds_window_until_explicit_initializer[post_bind_source]",
        "tests/ops/test_dormant_ownership_initialization.py::test_test_preparation_producer_holds_window_until_explicit_initializer[cleanup_retry_exact]",
        "tests/ops/test_dormant_ownership_initialization.py::test_test_preparation_producer_holds_window_until_explicit_initializer[native_error_prove_barrier]",
    ),
}

# Every app/ file indexed by a (file, line)-keyed census registry in
# tests/properties/_machinery.py (REGISTERED_MIRRORS, WRITE_FRONTMATTER_SITE_CLASSIFICATION,
# WRITE_MISSING_SITE_CLASSIFICATION, WRITE_NOTE_RELATIVE_SITE_CLASSIFICATION,
# STORE_PAYLOAD_SINK_CLASSIFICATION). An ordinary edit to one of these files can shift a
# censused call site's line number without touching tests/properties/ at all, so the
# "properties" subsystem below needs its own app/ trigger set instead of relying only on the
# tests/properties/ prefix (#4269). This list is exact files, not directory prefixes, so it
# does not widen "properties" to all of app/ broadly; keep it in sync with the file set the
# _machinery.py registries actually key on when either side changes.
PROPERTIES_CENSUSED_APP_SITES = (
    "app/agent_memory/materialization.py",
    "app/agent_memory/provisional_write.py",
    "app/agents/normalizer/agent.py",
    "app/agents/panel/writeback.py",
    "app/agents/panel_agent/execution.py",
    "app/agents/panel_agent/runtime.py",
    "app/agents/planner/agent.py",
    "app/agents/planner/graph.py",
    "app/briefing/compose.py",
    "app/chat/session_log.py",
    "app/cli/alpha_human_flows.py",
    "app/cli/index_rebuild.py",
    "app/cli/smoke.py",
    "app/episodes/segmenter.py",
    "app/episodes/store.py",
    "app/eval/failure_capture.py",
    "app/fitness/metrics.py",
    "app/heimdal/candidate_projection.py",
    "app/heimdal/capture_note.py",
    "app/heimdal/entity_register.py",
    "app/heimdal/settings_notes.py",
    "app/heimdal/time_spend.py",
    "app/indexer/consumer.py",
    "app/ingest/api.py",
    "app/ingest/external.py",
    "app/ingest/reflection_consumer.py",
    "app/ingest/vault_alpha.py",
    "app/ingest/vault_root.py",
    "app/instance/vault_registry.py",
    "app/knowledge_acquisition/raw_record.py",
    "app/mcp/vault_tools.py",
    "app/objects/__init__.py",
    "app/ports/filesystem_vault_adapter.py",
    "app/promotion/consumer.py",
    "app/reasoning/multi.py",
    "app/relevance/materialization.py",
    "app/search/service.py",
    "app/services/commitment_persistence.py",
    "app/services/indexer.py",
    "app/standing_questions/question_store.py",
    "app/stores/postgres.py",
    "app/vault/manager.py",
    "app/vault/settings_service.py",
    "app/watcher/vault_watcher.py",
)

E2E_TARGETS = {
    "companion_ui": (
        "tests/e2e/test_panel_to_promotion_consume.py",
        "tests/e2e/test_panel_watcher_e2e.py",
    ),
    "watcher_sync": (
        "tests/e2e/test_runtime_loop_vault_test.py",
        "tests/e2e/test_watcher_registry_e2e.py",
        "tests/e2e/test_panel_watcher_e2e.py",
    ),
    "orchestration": (
        "tests/e2e/test_pipe_graph.py",
        "tests/e2e/test_runtime_contract_regressions.py",
    ),
    "memory_retrieval": (
        "tests/e2e/test_index_rules_e2e.py",
        "tests/e2e/test_promotion_intent_to_index.py",
        "tests/e2e/test_reality_mvp_pipeline.py",
    ),
    "llm_eval": (
        "tests/e2e/test_llm_routing_e2e.py",
    ),
    "promotion_panel": (
        "tests/e2e/test_panel_to_promotion_consume.py",
        "tests/e2e/test_panel_watcher_e2e.py",
        "tests/e2e/test_promotion_intent_to_index.py",
    ),
    "ops_deploy": (
        "tests/e2e/test_operator_workflows.py",
        "tests/e2e/test_human_need_uat.py",
    ),
}

E2E_OWNER_BY_FILE = {
    target: subsystem for subsystem, targets in E2E_TARGETS.items() for target in targets
}
E2E_OWNER_BY_FILE["tests/e2e/test_panel_llm_e2e.py"] = "promotion_panel"

GENERIC_PR_EXCLUDED_TARGETS = frozenset({"tests/e2e/test_panel_llm_e2e.py"})

# Heavy test targets run on the PR path only when the PR changes a source they
# exercise; otherwise they run after merge on the ygg `test` VM, and
# .github/workflows/post-merge-heavy-tests.yml records the verdict and files a
# high-priority alert Issue when it is red or missing (#6154, #6158). Admit
# a target here only with a timing receipt. `tests/deploy` was ~1497 s of PR
# #6134's 2287 s unit step and timed out PR #6152, because ops_deploy owns all
# of `scripts/` and any script change unioned it in. A changed test module
# inside a deferred directory still runs as its own changed-file target; any
# other changed file inside the directory (conftest, helpers) keeps it whole.
HEAVY_PR_DEFERRED_TARGETS: dict[str, tuple[str, ...]] = {
    "tests/deploy": (
        # Every repo file tests/deploy reads directly -- scripts, compose
        # files, requirements, Dockerfile, deploy config and the app/ modules
        # it imports by path -- census-enforced by
        # tests/scripts/test_select_pr_tests.py, plus the deploy-channel
        # directories it exercises.
        "scripts/lib/",
        "ops/",
        "config/deploy/",
        "app/release_channels/",
        "tests/helpers/runtime_start_harness.py",
        "tests/runtime/test_start_full_system_version_marker.py",
        ".dockerignore",
        ".github/workflows/app-image-build.yml",
        ".github/workflows/ci-smoke.yaml",
        ".github/workflows/postmerge-channel-bug.yml",
        ".github/workflows/postmerge-dev-test.yml",
        "Dockerfile",
        "Makefile",
        "alembic.ini",
        "app/__init__.py",
        "app/alembic/versions/e7b4c9d2a6f1_heimdal_raw_representation.py",
        "app/api/app.py",
        "app/cli.py",
        "app/config/activation_scope.py",
        "app/config/database.py",
        "app/instance/mvr05_cutover.py",
        "app/instance/runtime.py",
        "app/instance/settings_rebind.py",
        "app/instance/settings_rebind_runtime_capability.json",
        "app/ops/__init__.py",
        "app/ops/bws_control_installation.py",
        "app/ops/bws_secret_reader.py",
        "app/ops/heavy_acceptance.py",
        "app/ops/heavy_acceptance_runner.py",
        "app/ops/host_secret_bootstrap.py",
        "app/ops/host_secret_contract.py",
        "app/ops/host_secret_controller.py",
        "app/ops/native_source_bootstrap.py",
        "app/ops/postgres_deploy_host.py",
        "app/ops/postgres_deploy_linux.py",
        "app/tts/config.py",
        "companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md",
        "config/model_access/executor_network_paths.yaml",
        "config/runtime.defaults.env",
        "config/secrets/bws_reader_token_targets.json",
        "config/secrets/host_secret_contract.json",
        "config/systemd/yggdrasil-bws-deploy@.service",
        "config/tts-disabled/.gitkeep",
        "docker-compose.app-bind.yml",
        "docker-compose.bws-external.yml",
        "docker-compose.bws.yml",
        "docker-compose.dev.yml",
        "docker-compose.full-host-vault.yml",
        "docker-compose.legacy-vault.yml",
        "docker-compose.prod.yml",
        "docker-compose.scalar-rollback.yml",
        "docker-compose.test-vault.yml",
        "docker-compose.test.yml",
        "docker-compose.yaml",
        "docs/EPISODE_RESOLUTION_ENGINE/stream_registry.md",
        "docs/runbooks/RUNBOOK_TTS_PROVISIONING.md",
        "requirements-bws-deploy.txt",
        "requirements-tts.txt",
        "requirements.txt",
        "scripts/companion_ui_postdeploy_smoke.sh",
        "scripts/compose_env.py",
        "scripts/deploy_channel.sh",
        "scripts/dev_test_environment_clobber_preflight.py",
        "scripts/export_runtime_env.sh",
        "scripts/install_bws_deploy_runtime.sh",
        "scripts/install_postmerge_controller.py",
        "scripts/instance_state_writer_inventory.py",
        "scripts/post_merge_heavy_tests_verdict.py",
        "scripts/postgres_deploy_service.py",
        "scripts/postgres_entrypoint.sh",
        "scripts/postmerge_channel_bug.py",
        "scripts/postmerge_controller.py",
        "scripts/postmerge_dev_test.py",
        "scripts/prod_deploy_retry_preflight.py",
        "scripts/prod_devui_gateway_preflight.py",
        "scripts/run_migrations.sh",
        "scripts/start_api.sh",
        "scripts/start_full_system.sh",
    ),
}

SCOPED_DEPLOY_PARALLEL_ROOTS = ("tests/deploy", "tests/scripts")
SCOPED_DEPLOY_SERIAL_ROOT = "tests/ops"
SCOPED_EXECUTION_MAX_WORK_UNITS = 4

SUBSYSTEMS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("governance", (), CI_CONTRACT_TARGETS),
    (
        "builder_system",
        (
        "app/builderops/",
            "app/dispatcher/",
            # The design-packet resolver is Builder System/CES projection
            # machinery. Keep this ownership exact: sibling app/governance
            # modules are Product GOV runtime boundaries with different tests.
            "app/governance/design_packet_resolver.py",
            # The design-boundary doctor is Builder System/CES report machinery;
            # keep its ownership explicit so the governance tests cannot be
            # filtered out as an unowned app module.
            "app/governance/design_boundary_doctor.py",
            # The TARS inventory boundary is Builder System/CES machinery.
            # It carries an inventory-only PVE token and its direct proof
            # lives in tests/proxmox; leaving this new app prefix unowned
            # fails the required selector before its deny-before-HTTP tests
            # can run.
            "app/proxmox/",
            # Static Builder surfaces (signboard, cockpit) render dispatcher/
            # BuilderOps state; their regressions live in tests/dispatcher and
            # tests/builderops. companion_ui co-owns this prefix because the
            # API process mounts and serves it.
            "app/web/",
            "tests/builderops/",
            "tests/dispatcher/",
            "tests/proxmox/",
            "tests/governance/",
            # BuilderOps store-access inventory fitness. Keep this exact file
            # owned without widening builder_system to all architecture tests.
            "tests/architecture/test_builderops_store_boundary.py",
            "tests/architecture/test_builderops_package_independence.py",
            "tests/ops/test_builderops_package_smoke.py",
            # pr-contract/BuilderOps-routing hot-path governance fitness
            # (#4343): a pure change to this one test file has no non-test
            # governance/docs path alongside it, so `_is_governance_only`
            # (which requires real non-test signal) never fires and the PR
            # fell through the SUBSYSTEMS loop into `unowned` (exit 2). Own
            # this exact file the same way test_builderops_store_boundary.py
            # is owned above, without widening builder_system to all
            # architecture tests.
            "tests/architecture/test_pr_hot_path_governance.py",
            # Durable-table and producer inventory fitness belongs to the
            # Builder System architecture gate. Own this exact file so a
            # count/contract repair cannot fail closed as an unowned PR.
            "tests/architecture/test_multi_vault_projection_inventory.py",
            # The MVR-05B context-boundary gate and its inventory helper are the
            # same kind of architecture fitness; own them exactly (#6136).
            "tests/architecture/context_boundary_inventory.py",
            "tests/architecture/test_multi_vault_context_boundaries.py",
            # Isolated subprocess import wiring is a Builder test-harness
            # contract; own both the helper and its focused regression without
            # widening this subsystem to all helpers.
            "tests/helpers/subprocess_pythonpath.py",
            "tests/helpers/test_subprocess_pythonpath.py",
            "docs/builderops/",
            "importlinter.ini",
        ),
        (
            "tests/builderops",
            "tests/dispatcher",
            "tests/proxmox",
            "tests/governance",
            "tests/architecture/test_builderops_store_boundary.py",
            "tests/architecture/test_builderops_package_independence.py",
            "tests/ops/test_builderops_package_smoke.py",
            "tests/architecture/test_pr_hot_path_governance.py",
            "tests/architecture/test_multi_vault_projection_inventory.py",
        ),
    ),
    (
        "model_access",
        (
            "llm_contract/",
            "app/model_access/",
            "app/builderops/model_access_resolver.py",
            "tests/model_access/",
            "tests/architecture/test_llm_contract_kernel.py",
        ),
        (
            "tests/model_access",
            "tests/builderops/test_model_inquiry_adapters.py",
            "tests/builderops/test_model_inquiry_runner.py",
            "tests/architecture/test_llm_contract_kernel.py",
            "tests/architecture/test_import_boundary.py",
        ),
    ),
    (
        "settings",
        (
            "app/components/settings/",
            "app/settings/",
            "app/cli/settings_explain.py",
            # TTS consumes the compiled Settings Spine directly.  Keep voice
            # and fallback changes on focused TTS regression coverage rather
            # than failing the required check as an unowned runtime path.
            "app/tts/",
            "app/services/companion_eligibility.py",
            "app/services/settings.py",
            "docs/settings/",
            "docs/SETTINGS_SPINE/TTS_SETTINGS.md",
            "vault/settings/tts.md",
            "tests/settings/",
            "tests/tts/",
            "tests/config/",
        ),
        (
            "tests/settings",
            "tests/tts",
            "tests/config",
            "tests/cli/test_settings_explain_cli.py",
            "tests/services/test_companion_eligibility.py",
        ),
    ),
    (
        "vault",
        (
            "app/instance/",
            "app/knowledge/",
            "app/vault/",
            # ProfileAgent persists and writes the canonical owner-vault
            # profile; route it to the GOVPROF runtime regressions instead of
            # failing the PR check as unowned code.
            "app/agents/profile_agent/",
            # Reviewer reads vault-note content. Keep this exact consumer seam
            # on the vault proposal and Reviewer-context regressions.
            "app/agents/reviewer/agent.py",
            # The deletion seam owns vault file-state lifecycle and emits the
            # watcher-consumed tombstone. It is a vault runtime surface, not a
            # generic services module; leaving it unowned fail-closes the
            # required Unit check before its real regression targets run.
            "app/services/vault_sync.py",
            "tests/instance/",
            "tests/vault/",
            "tests/knowledge/",
            "docs/VAULT",
            "docs/builderops/BUILDEROPS_VAULT",
            # Vault-layout hardcoded-literal fitness guard. Keep this exact
            # file owned without widening vault to all architecture tests.
            "tests/architecture/test_no_hardcoded_vault_layout.py",
            # MVR-05 deployment finalization is a vault/ownership authority
            # boundary. Keep its focused architecture regression owned without
            # widening vault to all architecture tests.
            "tests/architecture/test_mvr05_authority_recovery.py",
            # The Sources-zone census protects the selected vault's layout and
            # knowledge writers. Keep its exact module on the vault proof.
            "tests/architecture/test_sources_zone_writers.py",
            # The semanticmd vault-note merge driver/resolver (#4505): cross-
            # device vault-note merging is its real job (uuid: frontmatter
            # identity, near-duplicate/"prefer concise" heuristics), so it was
            # previously unowned runtime code that failed CI selection closed.
            "app/agents/merge_resolver/",
            "app/cli/merge_driver.py",
            "docs/development/SEMANTIC_MARKDOWN_MERGE_DRIVER.md",
            "tests/fixtures/merge/",
        ),
        (
            "tests/instance",
            "tests/vault",
            "tests/knowledge",
            "tests/governance/test_governed_vault_profile_contract.py",
            "tests/governance/test_governed_vault_profile_proposals.py",
            "tests/agents/test_reviewer.py",
            "tests/agents/test_reviewer_single_note.py",
            "tests/ports",
            "tests/services/test_vault_sync_lifecycle.py",
            "tests/services/test_vault_sync_atomicity.py",
            "tests/services/test_vault_sync_delete_note_policy.py",
            "tests/watcher/test_vault_watcher_delete_required_outbox.py",
            "tests/architecture/test_no_hardcoded_vault_layout.py",
            "tests/architecture/test_mvr05_authority_recovery.py",
            "tests/architecture/test_sources_zone_writers.py",
            "tests/agents/test_merge_resolver.py",
            "tests/agents/test_merge_resolver_repo_docs.py",
            "tests/cli/test_merge_driver.py",
            # Pre-merge signal for the instance-state deployment surface that
            # the push-lane `CI gate: vaultwide panel verifier` protects
            # (#4371): a backup/ownership verification defect in
            # `app/instance/**` must fail the changing PR instead of first
            # turning `main`'s post-merge smoke red.
            "tests/ops/test_instance_state_volume_contract.py",
        ),
    ),
    (
        "mimer_mcp",
        (
            # External Mimer MCP is a bounded protocol adapter over the existing
            # client HTTP contract. Keep its semantic server and exact contract
            # proofs owned together so a new adapter module cannot fall through
            # CI's fail-closed unowned-runtime path (#3368).
            "app/mimer_mcp/",
            "mimer-mcp-sidecar/",
            "tests/mcp/test_mimer_server.py",
            "tests/mcp/test_mimer_sidecar_semantic_parity.py",
            "tests/mcp/test_mimer_server_transport.py",
            "tests/mcp/test_mimer_server_security.py",
            "tests/mcp/test_mimer_server_smoke.py",
            "tests/architecture/test_mimer_mcp_server_boundaries.py",
            "tests/architecture/test_mimer_mcp_sidecar_isolation.py",
            "tests/architecture/test_requirements_consistency.py",
        ),
        (
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
        ),
    ),
    (
        "companion_ui",
        (
            "companion-ui/",
            "app/api/",
            # HTTP middleware is API surface: TraceIdMiddleware is wired only
            # into app/api/app.py, and its x-trace-id propagation regression
            # lives in tests/api (test_ask_contract).
            "app/middleware/",
            # Static assets are mounted and served by app/api/app.py; page
            # handlers (/signboard, /cockpit) are API surface, asserted from
            # tests/api (test_signboard_api reads signboard.html/.js), so a
            # UI-copy change selects that coverage instead of failing closed
            # as unowned. builder_system co-owns this prefix for the
            # Builder-state content it renders.
            "app/web/",
            "api/",
            # FastAPI dependency providers (get_agent_repository / get_db)
            # consumed by app/api/routers/agent.py; exercised via tests/api.
            "app/deps.py",
            "tests/companion_ui/",
            "tests/api/",
            "tests/architecture/test_openapi_static_contract.py",
        ),
        (
            "tests/companion_ui",
            "tests/api",
            "tests/architecture/test_openapi_sync.py",
            "tests/architecture/test_openapi_static_contract.py",
            *E2E_TARGETS["companion_ui"],
        ),
    ),
    (
        "canvas_chat",
        ("app/chat/", "tests/chat/"),
        ("tests/chat",),
    ),
    (
        "watcher_sync",
        (
            "app/watcher/",
            "app/sync/",
            # Watcher process entrypoint (`python -m app.cli watcher run`);
            # its CLI regressions live in tests/watcher (same single-file
            # granularity as runtime_health's app/cli/health.py).
            "app/cli/watcher.py",
            # The scripted vault UAT bootstrap mutates watcher ingest scope
            # and runs the watcher path; keep its CLI contract in the same
            # subsystem instead of failing closed as an unowned app module.
            "app/cli/uat.py",
            "scripts/run_live_watcher.sh",
            "tests/watcher/",
            "tests/sync/",
            "tests/e2e/test_runtime_loop_vault_test.py",
            "tests/e2e/test_watcher_registry_e2e.py",
            "tests/e2e/test_panel_watcher_e2e.py",
        ),
        (
            "tests/watcher",
            "tests/sync",
            "tests/cli/test_uat_seed_cli.py",
            *E2E_TARGETS["watcher_sync"],
        ),
    ),
    (
        "runtime_health",
        (
            "app/runtime/health_probe.py",
            "app/cli/health.py",
            # Health snapshot/contract surface: its direct suites live in
            # tests/health, tests/api (test_health_contract_api.py), tests/cli
            # (health-contract CLI + authority spine) and the health-focused
            # tests/observability modules listed in the targets below.
            "app/health_contract.py",
            "docker-compose.yaml",
            "tests/health/",
            "tests/invariants/test_health_probe.py",
            "tests/invariants/test_health_heartbeat_visibility.py",
            # /app/runtime container-writability contract (#3047): no app/
            # module owns it exclusively (it probes the Dockerfile plus the
            # ask_synthesis receipt path as one example writer), so its own
            # suite membership is the only available trigger.
            "tests/invariants/test_receipt_surface_writable.py",
            "docs/OBSERVABILITY_STABILIZATION/",
        ),
        (
            "tests/health",
            "tests/invariants",
            "tests/api",
            "tests/cli/test_health_contract_cli.py",
            "tests/cli/test_health_authority_spine.py",
            "tests/observability/test_health_contract_settings.py",
            "tests/observability/test_health_incidents.py",
            "tests/observability/test_health_state_machine.py",
            "tests/observability/test_status_bounded_reads.py",
        ),
    ),
    (
        # Structured logging / tracing / status-model surface (#3895). Its
        # home suite is tests/observability; the API status routes and the
        # trace-context consumers (app/api/routes/status.py, TraceIdMiddleware
        # binding app.observability.tracer) regress in tests/api. The docs
        # owner file is the exact path docs/OBSERVABILITY.md so this prefix
        # never steals runtime_health's docs/OBSERVABILITY_STABILIZATION/.
        "observability",
        (
            "app/observability/",
            # Orientation is a derived status projection; preserve its
            # unknown-on-corruption proof when its runtime adapter changes.
            "app/orientation/runtime.py",
            # The leave-point cursor is the derived orientation trace the
            # status projection reads (MVR-05B4c4); its route proofs are in tests/api.
            "app/orientation/leave_point_cursor.py",
            "tests/observability/",
            "docs/OBSERVABILITY.md",
        ),
        ("tests/observability", "tests/api"),
    ),
    (
        "store_ingest",
        (
            "app/stores/",
            "app/ingest/",
            "app/rebuildability/",
            # The object-store facade writes canonical objects through the
            # store provider seam and emits ingest lifecycle events. Keep this
            # shared producer on the established store/ingest contracts
            # without claiming the whole app/objects package.
            "app/objects/__init__.py",
            # Product source-backed rebuild admission uses the shared write
            # guard while readiness is unready; keep this exact producer on
            # the Product total-loss integration and guard contract.
            "app/write_guard.py",
            "tests/stores/",
            "tests/ingest/",
            "tests/integration/test_product_total_loss.py",
            "tests/integration/test_projection_rebuild.py",
            "docs/DB_SCHEMA.md",
            "docs/RUNTIME_CORRECTNESS_KERNEL/",
        ),
        (
            "tests/stores",
            "tests/ingest",
            "tests/integration/test_product_total_loss.py",
            "tests/integration/test_projection_rebuild.py",
            "tests/services/test_write_guard.py",
            "tests/architecture",
            "tests/services/test_outbox_idempotency.py::test_save_object_content_change_emits_new_event",
        ),
    ),
    (
        "relevance",
        ("app/relevance/", "tests/relevance/"),
        ("tests/relevance",),
    ),
    (
        # Daily Briefing is a derived HIX read surface. Keep its composer,
        # trigger, and focused contract suite together so a briefing change
        # cannot fail CI selection before its behavioral Verify targets run.
        "briefing",
        ("app/briefing/", "tests/briefing/"),
        ("tests/briefing",),
    ),
    (
        "curation",
        (
            "app/curation/",
            "tests/curation/",
            "docs/CONTRADICTION_TRIAGE_BENCH/",
        ),
        ("tests/curation", "tests/invariants"),
    ),
    (
        "decision_calibration",
        (
            "app/calibration/",
            "tests/calibration/",
            "docs/PREMORTEM_COMPANION/",
            "docs/DECISION_CALIBRATION/",
        ),
        (
            "tests/calibration",
            "tests/services/test_outcome_receipt_log.py",
            "tests/agent_memory/test_ask_synthesis_gate.py",
        ),
    ),
    (
        "temporal_posture",
        (
            "app/temporal/",
            "tests/temporal/",
            "docs/TEMPORAL_POSTURE/",
            "docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md",
            "config/temporal_posture.",
        ),
        (
            "tests/temporal",
            "tests/retrieval/test_view_freshness_metadata.py",
        ),
    ),
    (
        "heimdal",
        (
            "app/heimdal/",
            # The Heimdal runtime has a dedicated CLI command module. Keep it
            # on the Heimdal suite rather than failing CI selection as an
            # unowned app/ path.
            "app/cli/heimdal.py",
            "tests/heimdal/",
            "docs/HEIMDAL/",
            "docs/HEIMDAL_CAPTURE_CLIENT/",
        ),
        ("tests/heimdal",),
    ),
    (
        "archival",
        (
            "app/archival/",
            "tests/archival/",
            "tests/architecture/test_governed_archival_contract.py",
            "docs/contracts/GOVERNED_ARCHIVAL_FLOW.md",
            "docs/GOVERNED_ARCHIVAL_FLOW/",
        ),
        ("tests/archival", "tests/architecture/test_governed_archival_contract.py"),
    ),
    (
        "operations",
        (
            "app/operations/",
            "tests/operations/",
            "tests/architecture/test_autonomous_operations_boundaries.py",
        ),
        (
            "tests/operations",
            "tests/architecture/test_autonomous_operations_boundaries.py",
        ),
    ),
    (
        "orchestration",
        (
            "app/orchestrator/",
            "app/orchestration/",
            # The real-tool effect spine crosses CAO, EXE, and GOV. Keep
            # these exact adapters on the orchestration contract lane so
            # an effect-boundary change cannot fail closed before its
            # real-tool invariant tests run.
            "app/execution/execution_request.py",
            "app/governance/governed_write.py",
            "tests/orchestrator/",
            "tests/orchestration/",
            "tests/invariants/test_governed_effect_spine.py",
            # These execution/planner regressions exercise the orchestration
            # admission boundary directly. Keep their exact test files owned
            # so a focused fix cannot fail closed before pytest selection.
            "tests/execution/test_execution_request.py",
            "tests/planner/test_mock_planner.py",
            "tests/e2e/test_pipe_graph.py",
            "tests/e2e/test_runtime_contract_regressions.py",
        ),
        (
            "tests/orchestrator",
            "tests/orchestration",
            "tests/invariants/test_governed_effect_spine.py",
            "tests/execution/test_execution_request.py",
            "tests/governance/test_governed_write.py",
            "tests/planner/test_mock_planner.py",
            *E2E_TARGETS["orchestration"],
        ),
    ),
    (
        "memory_retrieval",
        (
            "app/memory/",
            # Promoted and provisional agent-memory recall is consumed by the
            # memory/retrieval suites. Keep this runtime package owned so a
            # recall-boundary change cannot fail CI selection as unowned.
            "app/agent_memory/",
            # Review admission is the producer seam that hands an approved
            # candidate to promoted-memory materialization. Its persisted
            # scope/candidate authority must stay on the same acceptance
            # surface as the consumer that later admits the memory to recall.
            "app/knowledge_compilation/review_admission.py",
            "app/retrieval/",
            # Emitted ContextBundles are the retrieval capability's process-local
            # addressability cache (MVR-05B4c5); its route proofs are in tests/api.
            "app/context_bundles/",
            "app/index/",
            # Index rebuild is the memory-retrieval CLI producer for the
            # canonical vector rows exercised by the index suites.
            "app/cli/index_rebuild.py",
            # Runtime vector producers share the same canonical-byte and
            # provenance contract as rebuild/reconcile. Keep changes to these
            # exact seams on the index/search acceptance surface instead of
            # failing closed as unowned after implementation has already run.
            "app/indexer/consumer.py",
            "app/search/service.py",
            "app/services/indexer.py",
            # The embedding-event producer writes DB-outbox records consumed
            # by the indexer. It also remains an outbox-worker producer below.
            "app/outbox/events.py",
            "tests/agent_memory/",
            "tests/retrieval/",
            "tests/context_bundles/",
            "tests/indexer/",
            "tests/e2e/test_index_rules_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_reality_mvp_pipeline.py",
        ),
        (
            "tests/agent_memory",
            "tests/knowledge_compilation/test_review_admission_handoff.py",
            "tests/retrieval",
            "tests/context_bundles",
            "tests/api/test_context_bundle_route.py",
            "tests/api/test_mvr05b4c_emitted_bundle_binding.py",
            "tests/index",
            "tests/indexer",
            "tests/search",
            "tests/services/test_indexer_worker.py",
            "tests/cli/test_index_rebuild_resilience.py",
            "tests/cli/test_index_doctor_mixed_identity.py",
            "tests/architecture/test_events_outbox_contracts.py",
            *E2E_TARGETS["memory_retrieval"],
        ),
    ),
    (
        "ask",
        (
            # The ASK graph is the retrieval CONSUMPTION seam: it binds the active
            # scope (#2921), assembles the ContextEnvelope, and drives recall. It
            # was unowned, so any change here failed closed as unowned runtime
            # code. Its blast radius is retrieval + agent memory + the ASK HTTP
            # contract, which is exactly what these targets cover.
            "app/agents/ask/",
            "app/activation/ask_synthesis.py",
            "app/retrieval/envelope.py",
            # The ASK HTTP surface owns BOTH ask entrypoints. `companion_ui` already
            # claims this path for `tests/api`, and subsystems union rather than steal,
            # so listing it here strictly widens: it adds the ASK graph/retrieval lane
            # plus the voice-contract test that `tests/api` alone does not cover.
            "app/api/routes/ask.py",
            "tests/agents/ask/",
        ),
        (
            "tests/agents/ask",
            "tests/retrieval",
            "tests/agent_memory",
            # `app/agents/ask/state.py` defines AgentState. These two suites are the
            # ONLY gates in the repo asserting the shared RuntimeStateModel authority
            # /trace spine on it. Without them an `ask`-only selection goes green while
            # a state class that dropped the spine merges -- a false-green CI window
            # this subsystem would otherwise newly open (these paths previously exited
            # 2, i.e. fail-closed).
            "tests/architecture/test_agent_state_spine.py",
            "tests/agents/test_runtime_state_contract.py",
            # `app/activation/ask_synthesis.py` is an ask prefix; this invariant
            # hard-codes the receipt path and mkdir+append sequence that module owns.
            "tests/invariants/test_receipt_surface_writable.py",
            "tests/api/test_ask_api.py",
            "tests/api/test_ask_alias.py",
            "tests/api/test_ask_contract.py",
            "tests/api/test_ask_llm_answer.py",
            "tests/api/test_ask_rerank_origin.py",
            "tests/api/test_ask_route.py",
            # `/api/ask/voice` binds the same active scope from a form field. Every other
            # voice test monkeypatches `run_ask_graph` away, so this is the only gate that
            # proves the voice turn is not a scope-isolation hole.
            "tests/voice/test_voice_ask_contract.py",
        ),
    ),
    (
        "episodes",
        (
            "app/episodes/",
            "app/episode_debrief/",
            "app/cli/episode_debrief.py",
            "app/jobs/episodes_projection.py",
            # CrossScopeFlow is an Episodes contract even though its shared
            # definition and owner documentation live outside app/episodes.
            "schemas/_defs.schema.json",
            "schemas/episode-note.schema.json",
            # CI-selection owner only: the bundle schema is SIP surface; its
            # enforcement probes live in tests/invariants. Full-suite routing
            # for bundle-schema changes stays deferred until the pre-existing
            # deprecated-store failure (from #3479) is repaired.
            "schemas/metadata-bundle.schema.json",
            "tests/episodes/",
            "tests/episode_debrief/",
            "tests/architecture/test_cross_scope_flow_schema.py",
            "tests/invariants/test_episode_binding.py",
            "tests/invariants/test_cross_scope_flow.py",
            "docs/architecture/cross-scope-flow.md",
        ),
        (
            "tests/episodes",
            "tests/episode_debrief",
            "tests/invariants",
            "tests/architecture/test_cross_scope_flow_schema.py",
        ),
    ),
    (
        # Shared CAO reasoning plus its governed Expansion caller. Keep this
        # result-contract boundary owned so provider/degradation changes run
        # both cognition suites and the invariants that prevent derived output
        # from acquiring write authority.
        "reasoning_expansion",
        (
            "app/reasoning/",
            "app/expansion/",
            "tests/reasoning/",
            "tests/expansion/",
            "tests/uat/test_expansion_connect_create_accept_test_channel.py",
            "docs/MIMER_CAPABILITY_HARDENING/",
            "docs/runbooks/UAT_EXPANSION_CONNECT_CREATE_ACCEPT.md",
        ),
        ("tests/reasoning", "tests/expansion", "tests/invariants"),
    ),
    (
        "llm_eval",
        (
            "app/llm/",
            "app/components/embeddings/",
            "app/components/llm/",
            "app/services/llm.py",
            "app/config/llm.py",
            "app/eval/",
            "docs/LLM_ROUTING.md",
            "docs/eval/",
            "tests/components/embeddings/",
            "tests/components/llm/",
            "tests/index/test_identity_migration.py",
            "tests/llm/",
            "tests/eval/",
            "tests/evals/",
            "tests/e2e/test_llm_routing_e2e.py",
            "tests/e2e/test_panel_llm_e2e.py",
        ),
        (
            "tests/components/embeddings",
            "tests/components/llm",
            "tests/components/reasoning",
            "tests/index/test_identity_migration.py",
            "tests/llm",
            "tests/cli/test_embed_probe.py",
            "tests/eval",
            "tests/evals",
            *E2E_TARGETS["llm_eval"],
        ),
    ),
    (
        "voice",
        (
            "app/voice/",
            "tests/voice/",
            "docs/MIMER_VOICE_LOOP/",
            "docs/contracts/MIMER_CLIENT_CONTRACT.md",
        ),
        ("tests/voice",),
    ),
    (
        "standing_questions",
        (
            "app/standing_questions/",
            # Deliberately NOT app/alembic/versions/4d1e0c9a3329_...: a migration
            # touching the standing_questions schema has cross-cutting blast radius
            # and must resolve to full-suite via the migration/schema full-suite rule
            # above, never to this subsystem's narrower tests/standing_questions alone.
            "schemas/question-note.schema.json",
            "tests/standing_questions/",
            "docs/STANDING_QUESTIONS/",
        ),
        ("tests/standing_questions",),
    ),
    (
        "media",
        (
            "app/media/",
            # Shared no-egress authority boundary used by transcription and
            # knowledge-acquisition replay.  A seam-only change must exercise
            # every canonical consumer rather than fail as unowned.
            "app/source_egress.py",
        ),
        ("tests/test_transcribe_smoke.py",),
    ),
    (
        "events_receipts",
        (
            "app/events/",
            "app/receipts/",
            # The diagnostic CLI and legacy producer are governed event
            # outbox surfaces even though they predate the app/events/ tree.
            "app/cli/events_doctor.py",
            "app/outbox/legacy_events.py",
            "docs/contracts/events/",
            "tests/events/",
            "tests/receipts/",
        ),
        ("tests/events", "tests/receipts", "tests/contracts"),
    ),
    (
        # The outbox worker is the production consumer for event delivery, but
        # it sits outside app/events/. Keep its poison-row and heartbeat
        # regressions owned so CI runs them rather than fail-closing as
        # unowned before pytest starts.
        "outbox_worker",
        (
            "app/workers/outbox_worker.py",
            # The binding gate is the worker's admission/effect-window seam;
            # keep its rebind regressions on the same worker-owned test lane.
            "app/workers/outbox_binding_gate.py",
            # Opt-in /metrics endpoint for the outbox worker; its coverage
            # lives in tests/workers/test_worker_metrics.py.
            "app/workers/metrics.py",
            # The outbox service owns the queue's DB access (connection
            # binding, idempotent writes, ack/bump) that the worker consumes
            # (#3930); its regressions live in tests/services and tests/workers.
            "app/services/outbox.py",
            # Index embedding events are durable outbox producers; run both
            # delivery-worker and memory/indexing coverage for this exact seam.
            "app/outbox/events.py",
            "tests/workers/",
            "tests/worker/",
            "tests/services/test_outbox_idempotency.py",
            "tests/services/test_outbox_conn_binding.py",
        ),
        (
            "tests/workers",
            "tests/worker",
            "tests/services/test_outbox_idempotency.py",
            "tests/services/test_outbox_conn_binding.py",
            "tests/events",
            "tests/services/test_companion_note.py",
            "tests/services/test_companion_note_write_guard.py",
        ),
    ),
    (
        "heimdal_mimer",
        (
            "app/heimdal/",
            "app/knowledge_acquisition/",
            "app/source_egress.py",
            # The dev-only YouTube Inbox route composes this subsystem's
            # services and nothing else, so it is owned here rather than by a
            # cli-shaped owner. Without it the file fell through the SUBSYSTEMS
            # loop into `unowned` (exit 2) on PR #5614.
            "app/cli/youtube_inbox_dev.py",
            "docs/HEIMDAL/",
            "docs/KARAKEEP_MIMER_ACQUISITION/",
            "docs/KNOWLEDGE_ACQUISITION/",
            "docs/YOUTUBE_SOURCE_SYNC/",
            "docs/EVENTS.md",
            "tests/heimdal/",
            "tests/knowledge_acquisition/",
            "tests/cli/test_youtube_inbox_dev_cli.py",
        ),
        (
            "tests/heimdal",
            "tests/knowledge_acquisition",
            "tests/cli/test_youtube_inbox_dev_cli.py",
        ),
    ),
    (
        "journaling",
        (
            "app/journaling/",
            "app/cli/journaling.py",
            "app/activation/journal_draft.py",
            "app/knowledge_compilation/proposal_builders.py",
            "app/proposals/declined_ledger.py",
            "tests/journaling/",
            "docs/CONVERSATIONAL_JOURNALING/",
        ),
        (
            "tests/journaling",
            "tests/activation/test_journal_draft_activation.py",
            "tests/knowledge_compilation/test_proposal_builders.py",
            "tests/proposals/test_declined_ledger.py",
            "tests/cli/test_journaling_review_cli.py",
        ),
    ),
    (
        "promotion_panel",
        (
            "app/agents/panel_agent/",
            "app/agents/panel/",
            "app/promotion/",
            "app/panel/",
            # OTel tracing shim consumed only by the promotion agent
            # (app/promotion/queue.py, app/agents/promotion/agent.py); its
            # regressions surface through the promotion suites.
            "app/observability/tracing.py",
            # The note-update service is the panel-driven note-body write path
            # (handle_panel_update / upsert_executed_ids); its regression suite
            # is tests/services/test_note_update_service.py.
            "app/services/note_update.py",
            "app/services/note_uuid.py",
            # Note artifact identity resolution gates checkbox projection
            # (app/panel/checkbox_projection.py) and the workspace read; leaving
            # it unowned failed PR selection closed (#5660).
            "app/services/artifact_identity.py",
            "tests/services/test_artifact_identity_service.py",
            "tests/services/test_note_uuid_create_once.py",
            "tests/agents/panel_agent/",
            "tests/agents/test_panel",
            "tests/promotion/",
            "tests/panel/",
            "tests/services/test_note_update_service.py",
            "tests/e2e/test_panel_to_promotion_consume.py",
            "tests/e2e/test_panel_watcher_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_panel_llm_e2e.py",
        ),
        (
            "tests/agents/panel_agent",
            "tests/agents/test_panel_agent.py",
            "tests/agents/test_panel_agent_no_vault.py",
            "tests/agents/test_panel_assist_modes.py",
            "tests/agents/test_panel_event_translation.py",
            "tests/agents/test_panel_intents.py",
            "tests/agents/test_panel_parser.py",
            "tests/agents/test_panel_pipeline_integration.py",
            "tests/agents/test_panel_receipts.py",
            "tests/agents/test_panel_writeback_guard.py",
            "tests/services/test_note_update_service.py",
            "tests/services/test_artifact_identity_service.py",
            "tests/services/test_note_uuid_create_once.py",
            "tests/promotion",
            "tests/panel",
            *E2E_TARGETS["promotion_panel"],
            # `app/agents/panel_agent/state.py` defines PanelAgentState. These two
            # suites are the ONLY gates in the repo asserting the shared
            # RuntimeStateModel authority/trace spine on it. Without them a
            # `promotion_panel`-only selection goes green while a state class
            # that dropped the spine merges -- the same false-green window closed
            # for `ask` in PR #4495 (#2921; #4501).
            "tests/architecture/test_agent_state_spine.py",
            "tests/agents/test_runtime_state_contract.py",
        ),
    ),
    (
        # Quality Wave is the non-blocking acceptance surface for seeded and
        # cold-rebuild scenarios. A direct edit to one of its tests must run
        # the suite rather than fail closed as an unowned path before pytest
        # can exercise the added evidence.
        "quality_wave",
        ("tests/quality_wave/",),
        ("tests/quality_wave",),
    ),
    (
        # The shipped picker controller driven over the real gateway and API
        # (#6368). A test- or harness-only edit must run the module rather
        # than fail closed as unowned; the harness alone has no tests.
        "multi_vault_picker",
        (
            "tests/integration/test_multi_vault_picker_context.py",
            "tests/_mvr05b_picker_browser.py",
        ),
        ("tests/integration/test_multi_vault_picker_context.py",),
    ),
    (
        "ops",
        ("app/ops/", "tests/ops/"),
        ("tests/ops",),
    ),
    (
        "ops_deploy",
        (
            ".github/workflows/postmerge-channel-bug.yml",
            "scripts/",
            "ops/",
            "config/deploy/",
            "tests/scripts/",
            "tests/deploy/",
            "tests/helpers/runtime_start_harness.py",
            "tests/runtime/test_start_full_system_version_marker.py",
        ),
        ("tests/ops", "tests/scripts", "tests/deploy"),
    ),
    (
        # First registration of app/release_channels/ (#3903 round 5): the
        # channel-isolation/fitness/promotion-readiness modules
        # (channel_isolation_preflight.py, cutover_readiness.py,
        # fleet_model_fitness.py, prepare_promotion.py, prod_ref_fitness.py,
        # reversibility.py) have no single test-directory owner. Their own
        # direct suites live in tests/release_channels/
        # (test_channel_isolation_preflight.py, test_harness_fidelity.py,
        # test_migration_reversibility.py, test_prepare_promotion.py), while
        # tests/deploy/ already owns test_cutover_readiness.py,
        # test_fleet_model_fitness.py, and the real deploy-entrypoint suites
        # (test_deploy_channel.py and siblings) that exercise these modules
        # through scripts/deploy_channel.sh. Run both, or a change here can
        # leave either half unowned -- ops_deploy's scripts/-rooted prefixes
        # already reach tests/deploy for the scripts/ callers, but not for
        # this app/ surface itself.
        "release_channels",
        (
            "app/release_channels/",
            "tests/release_channels/",
            # Exact legacy-path contract for model-access rollback in the
            # release_channels module; keep this narrow rather than assigning
            # every test under tests/release/ to this subsystem.
            "tests/release/test_model_access_router_rollback_plan.py",
            "docs/RELEASE_CHANNELS/",
        ),
        ("tests/release_channels", "tests/deploy"),
    ),
    (
        # Startup redesign contract/specification surface (#4914). The first
        # slice is docs + fixtures + static enforcement tests; owning the
        # complete surface runs the gates that certify the frozen contract.
        "startup_redesign_contract",
        (
            "docs/DEV_TEST_PROD_STARTUP_REDESIGN/",
            "tests/fixtures/startup_redesign/",
            "tests/architecture/test_startup_redesign_contract.py",
            "tests/runtime/test_startup_artifact_call_sites.py",
        ),
        (
            "tests/architecture/test_startup_redesign_contract.py",
            "tests/runtime/test_startup_artifact_call_sites.py",
            "tests/architecture/test_docs_index.py::test_all_docs_are_listed_in_docs_index",
        ),
    ),
    (
        # Skill-contract and cross-subsystem docs-contract surfaces: owned so
        # they resolve via the subsystem loop instead of falling to
        # unowned_paths when mixed with a path that already matches another
        # subsystem (e.g. the docs/contracts + docs/HEIMDAL + api/openapi.yaml
        # + .codex/skills mix reproduced by #3476 / PR #3475). Narrower
        # docs/contracts/** files with a more specific subsystem owner (e.g.
        # voice's docs/contracts/MIMER_CLIENT_CONTRACT.md) keep matching that
        # owner too; subsystems dedupe and union their targets.
        "docs_authoring",
        (".codex/skills/", "docs/contracts/"),
        GOVERNANCE_TARGETS,
    ),
    (
        # Property-lane test machinery (RESEARCH-03 P-1..P-7). Owned so a change
        # to a non-test helper like tests/properties/_machinery.py (the
        # write-seam census / classification registry) resolves to the property
        # tests that validate it, instead of fail-closing as unowned (exit 2).
        # A changed test_*.py file already runs directly; this covers the
        # shared machinery those tests import.
        "properties",
        ("tests/properties/", *PROPERTIES_CENSUSED_APP_SITES),
        ("tests/properties",),
    ),
)


EXACT_SUBSYSTEM_FILES: dict[str, frozenset[str]] = {
    "governance": CI_CONTRACT_PATHS,
    # Native request admission and API assembly share this finite scope helper.
    # Own only this file; unknown sibling config modules still fail closed.
    "companion_ui": frozenset({"app/config/activation_scope.py"}),
    "ops_deploy": frozenset({"app/config/activation_scope.py"}),
    # The companion/source predicate is shared by watcher traversal, queued
    # workers and Alpha ingestion. A helper-only edit must execute all three
    # existing source-boundary owners without claiming sibling services.
    "watcher_sync": frozenset({"app/services/companion_note.py"}),
    "store_ingest": frozenset({"app/services/companion_note.py"}),
    "outbox_worker": frozenset({"app/services/companion_note.py"}),
    "llm_eval": frozenset(
        {
            "app/components/reasoning/facade.py",
            # The Product embedding probe now resolves clients through the LLM
            # fabric; keep the CLI entrypoint on the same focused coverage.
            "app/cli/embed_probe.py",
        }
    ),
    # Product retrieval's embedding adapter is an exact seam between the LLM
    # fabric and the memory/indexing owners. Route it through the established
    # retrieval/index suites without claiming other components/ modules.
    "memory_retrieval": frozenset({"app/components/retrieval.py"}),
    # Separator-only note-path normalization is shared by the vault and
    # knowledge modules, both covered by the vault owner's target set. Keep
    # this exact so a similarly named, unowned runtime module still fails closed.
    "vault": frozenset({"app/path_utils.py"}),
    # These two planner producers are part of the orchestration admission
    # boundary. Keep their ownership exact while routing them through the
    # existing orchestration target set.
    "orchestration": frozenset(
        {"app/planner/provider.py", "app/planner/prompts.py"}
    ),
}


@dataclass(frozen=True)
class Selection:
    full_suite: bool
    subsystems: tuple[str, ...]
    targets: tuple[str, ...]
    reason: str
    unowned_paths: tuple[str, ...] = ()
    deferred_targets: tuple[str, ...] = ()

    @property
    def pytest_args(self) -> str:
        marker = f'-m "{PR_MARKER_EXPRESSION}"'
        if self.full_suite:
            ignores = "".join(f" --ignore={target}" for target in ("tests/e2e", *self.deferred_targets))
            return f"-q {marker} tests{ignores}"
        return " ".join(("-q", marker, *self.targets))


def _normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def _subsystem_owns_path(path: str, name: str, prefixes: tuple[str, ...]) -> bool:
    if name in {"ops", "ops_deploy"} and path in CI_CONTRACT_PATHS:
        return False
    return path in EXACT_SUBSYSTEM_FILES.get(name, frozenset()) or any(
        path.startswith(prefix) for prefix in prefixes
    )


def _is_full_suite_file(path: str) -> bool:
    return path in FULL_SUITE_EXACT or any(path.startswith(prefix) for prefix in FULL_SUITE_PREFIXES)


def _within_target_dirs(path: str, target_dirs: tuple[str, ...]) -> bool:
    return any(path == target or path.startswith(f"{target}/") for target in target_dirs)


def _non_test_signal(paths: tuple[str, ...], tolerated_test_dirs: tuple[str, ...]) -> tuple[str, ...]:
    # A changed tests/** path already inside this branch's own blanket target
    # dirs is scope-neutral: that directory runs either way, so it must not
    # disqualify the classification. A tests/** path OUTSIDE those dirs is real
    # scope signal (another subsystem, or an unmapped surface) and must still
    # be able to route the PR through the subsystem loop / full-suite fallback
    # instead of being silently absorbed into a narrower docs/governance run.
    return tuple(
        path
        for path in paths
        if not (path.startswith("tests/") and _within_target_dirs(path, tolerated_test_dirs))
    )


def _is_docs_only(paths: tuple[str, ...]) -> bool:
    non_test = _non_test_signal(paths, DOCS_TARGETS)
    return bool(non_test) and all(
        path not in DOCS_ONLY_EXCLUDED_EXACT
        # CLAUDE.md is the Claude compatibility entrypoint documented alongside
        # AGENTS.md (#4281); it must resolve here so a CLAUDE.md-only PR routes
        # to tests/architecture instead of falling through to unowned/full-suite.
        # `.codex/` is included so a `.codex/**` path (e.g. `.codex/agents/*.toml`,
        # `.codex/config.toml`) mixed with a `docs/**` path or `CLAUDE.md` still
        # resolves here instead of falling through every SUBSYSTEMS prefix into
        # `unowned` (#4335) -- a pure `.codex/**` diff still resolves via
        # `_is_governance_only` first, since that branch is checked before this
        # one in `select_tests`.
        and (
            path.startswith("docs/")
            or path.startswith(".codex/")
            or path in {"README.md", "AGENTS.md", "CLAUDE.md"}
        )
        for path in non_test
    )


def _is_governance_only(paths: tuple[str, ...]) -> bool:
    # CLAUDE.md is added here symmetrically with AGENTS.md so
    # `select_tests(["AGENTS.md", "CLAUDE.md"])` resolves the same way as
    # `select_tests(["AGENTS.md"])` alone (both governance), instead of the
    # combination silently falling through to the docs branch (#4335).
    governance_prefixes = (".github/", "docs/development/", "AGENTS.md", "CLAUDE.md", ".codex/")
    non_test = _non_test_signal(paths, GOVERNANCE_TARGETS)
    return bool(non_test) and all(
        path.startswith(governance_prefixes)
        # These read-only CI helpers are covered by tests/scripts and the
        # existing governance contracts, without unrelated host/deploy tests.
        # Any co-changed runtime/operational source still disqualifies this lane.
        or path in CI_GOVERNANCE_CONTRACT_PATHS
        for path in non_test
    )


def _is_ci_contract_only(paths: tuple[str, ...]) -> bool:
    return bool(paths) and all(path in CI_CONTRACT_PATHS for path in paths)


def _is_pr_intake_contract_only(paths: tuple[str, ...]) -> bool:
    # Existing exact CI-contract edits may accompany this source contract, for
    # example when selector coverage is updated with its owner documentation.
    # One of the seven added direct-reader targets also qualifies a test-only
    # contract change. General governance/doc readers are tolerated co-changes,
    # not anchors; every other co-change falls back to its owner.
    allowed_paths = CI_CONTRACT_PATHS | PR_INTAKE_CONTRACT_SOURCE_PATHS | PR_INTAKE_CONTRACT_READER_PATHS
    direct_reader_tests = frozenset(PR_INTAKE_CONTRACT_TARGETS)
    return (
        bool(paths)
        and any(
            path in PR_INTAKE_CONTRACT_SOURCE_PATHS or path in direct_reader_tests
            for path in paths
        )
        and all(path in allowed_paths for path in paths)
    )


def _is_test_only(paths: tuple[str, ...]) -> bool:
    return bool(paths) and all(path in ISOLATED_TEST_MODULES for path in paths)


@lru_cache(maxsize=4096)
def _module_dependencies(
    path: Path, module: str, _mtime: int, _size: int, *, strict: bool = False,
    metadata_literals: bool = False, allow_dynamic_code: bool = False,
) -> tuple[frozenset[str], bool, bool]:
    """Cache parsed imports by source stat; strict censuses reject unreadable/invalid sources."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        if strict:
            raise
        return frozenset(), True, False
    package = module.removesuffix(".__init__") if module.endswith(".__init__") else module.rpartition(".")[0]
    imports: set[str] = set()
    if metadata_literals:
        # Plain selector path data is not a consumer. Keep imports, literals in
        # executable calls, and simple literal bindings passed to consumers.
        bindings: dict[str, set[str]] = {}  # Reassignment cannot erase a possible consumer.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    if isinstance(target, ast.Name):
                        bindings.setdefault(target.id, set()).add(node.value.value)
        literal_uses = set()
        for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
            name = call.func.id if isinstance(call.func, ast.Name) else call.func.attr if isinstance(call.func, ast.Attribute) else ""
            if name in {"select_tests", "requires_runtime_checks", "_pr_targets", "Selection", "frozenset", "set"}:
                continue  # Known selector data construction, not a reader.
            literal_uses.update(id(node) for node in ast.walk(call) if isinstance(node, ast.Constant))
            imports.update(
                value for argument in [*call.args, *(keyword.value for keyword in call.keywords)]
                for node in ast.walk(argument) if isinstance(node, ast.Name) and node.id in bindings
                for value in bindings[node.id]
            )
    has_tests = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        or isinstance(node, ast.ClassDef) and (
            node.name.startswith("Test") or any(
                isinstance(base, ast.Name) and base.id == "TestCase"
                or isinstance(base, ast.Attribute) and base.attr == "TestCase"
                for base in node.bases
            )
        ) and any(
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_")
            for child in node.body
        )
        for node in tree.body
    )
    opaque = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("pytest_")
        or isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
            isinstance(target, ast.Name) and target.id == "pytest_plugins"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
        for node in tree.body
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            try:
                base = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
            except (ImportError, ValueError):
                if strict:
                    raise
                return frozenset(), True, has_tests
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names)
            opaque |= not allow_dynamic_code and any(alias.name == "*" for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if metadata_literals and id(node) not in literal_uses:
                continue
            imports.add(node.value)  # Includes literal importlib module names.
            if node.value.startswith("."):
                imports.add(node.value.lstrip("."))  # Relative literal importlib calls.
            if module.startswith("tests.") and node.value.startswith("tests/"):
                imports.add(node.value.split("::", 1)[0].removesuffix(".py").replace("/", "."))
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if not allow_dynamic_code and name in {"__import__", "import_module", "spec_from_file_location", "run_module", "run_path", "exec", "eval"}:
                opaque |= not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str)
                if name in {"spec_from_file_location", "run_path", "exec", "eval"}:
                    opaque = True  # File/code loaders do not establish a module import edge.
    return frozenset(imports), opaque, has_tests


def _is_bws_control_installation_contract_only(paths: tuple[str, ...]) -> bool:
    """Admit the exact source contract only while every static consumer is covered."""
    required = {BWS_CONTROL_INSTALLATION_SOURCE, BWS_CONTROL_INSTALLATION_TEST}
    if BWS_CONTROL_INSTALLATION_SOURCE not in paths or not set(paths) <= BWS_CONTROL_INSTALLATION_PATHS:
        return False
    metadata_paths = {"scripts/select_pr_tests.py", STATIC_TARGET_COLLECTABILITY_FITNESS.split("::", 1)[0]}
    try:
        if any(not (REPO_ROOT / path).is_file() or (REPO_ROOT / path).is_symlink() for path in required | set(paths)):
            return False
        inventory = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"], cwd=REPO_ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.split("\0")
        modules = {path.removesuffix(".py").replace("/", "."): path for path in inventory if path}
        selected = {path.removesuffix(".py").replace("/", ".") for path in required}
        if not selected <= modules.keys():
            return False
        dependencies = {}
        for module, relative in modules.items():
            file = REPO_ROOT / relative
            if file.is_symlink():
                return False
            stat = file.stat()
            dependencies[module] = _module_dependencies(
                file, module, stat.st_mtime_ns, stat.st_size, strict=True,
                metadata_literals=relative in metadata_paths,
            )
    except (OSError, UnicodeError, SyntaxError, ImportError, ValueError, subprocess.SubprocessError):
        return False
    if any(dependencies[module][1] for module in selected) or not dependencies[
        BWS_CONTROL_INSTALLATION_TEST.removesuffix(".py").replace("/", ".")
    ][2]:
        return False
    if any(opaque for module, (_, opaque, _) in dependencies.items() if modules[module] in metadata_paths):
        return False
    # A single collected node does not cover another consumer in that file.
    covered_paths = tuple(target for target in ALWAYS_TARGETS if "::" not in target)
    while True:
        aliases = selected | {module.rsplit(".", 1)[-1] for module in selected}
        for module in selected:
            relative = modules[module]
            aliases.update({relative, Path(relative).name, str(REPO_ROOT / relative)})
        consumers = {
            module for module, (imports, _, _) in dependencies.items()
            if any(
                reference in aliases
                or reference.startswith("./") and Path(reference.split("::", 1)[0]).as_posix() in aliases
                for reference in imports
            )
        }
        added = consumers - selected
        if not added:
            return True
        if any(
            not _within_target_dirs(modules[module], covered_paths) or dependencies[module][1]
            for module in added
        ):
            return False
        selected.update(added)


def _test_module_targets(paths: tuple[str, ...]) -> tuple[str, ...] | None:
    """Select test modules and their consumers; shared/unclear boundaries keep normal ownership."""
    if not paths or not all(
        path.startswith("tests/") and _is_test_module(path)
        and not {"..", "helpers", "fixtures", "support", "utils", "_shared"}.intersection(Path(path).parts)
        and (REPO_ROOT / path).is_file() and not (REPO_ROOT / path).is_symlink()
        and (
            any(_subsystem_owns_path(path, name, prefixes) for name, prefixes, _ in SUBSYSTEMS)
            # Documentation contract tests are normally selected by docs-only PRs,
            # but their own test-only edits still need the bounded module route.
            or path.startswith("tests/docs/")
        )
        for path in paths
    ):
        return None
    try:
        inventory = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"], cwd=REPO_ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.split("\0")
        modules = {path.removesuffix(".py").replace("/", "."): path for path in inventory if path}
        changed_modules = {path.removesuffix(".py").replace("/", ".") for path in paths}
        selected = set(changed_modules)
        if not selected <= modules.keys():
            return None
        dependencies = {}
        for module, relative in modules.items():
            file = REPO_ROOT / relative
            if file.is_symlink():
                return None
            stat = file.stat()
            # Outgoing dynamic code does not identify additional incoming consumers.
            # Hooks/plugins remain opaque even in these complete changed modules.
            dependencies[module] = _module_dependencies(
                file, module, stat.st_mtime_ns, stat.st_size,
                allow_dynamic_code=module in changed_modules,
            )
    except (OSError, subprocess.SubprocessError):
        return None
    while True:
        # Pytest's import mode can also expose a sibling by its bare module name.
        aliases = selected | {module.rsplit(".", 1)[-1] for module in selected}
        consumers = {module for module, (imports, _, _) in dependencies.items() if imports & aliases}
        if consumers <= selected:
            break
        selected.update(consumers)
    if any(
        not modules[module].startswith("tests/")
        or Path(modules[module]).name in {"__init__.py", "conftest.py"}
        or dependencies[module][1]
        for module in selected
    ) or any(not dependencies[path.removesuffix(".py").replace("/", ".")][2] for path in paths):
        return None
    return _dedupe([*paths, *sorted(modules[module] for module in selected if _is_test_module(modules[module]))])


def _foreign_subsystem_matches(
    paths: tuple[str, ...], tolerated_targets: tuple[str, ...]
) -> list[tuple[str, tuple[str, ...]]]:
    # `_is_docs_only`/`_is_governance_only` treat any tests/** path inside
    # `tolerated_targets` (DOCS_TARGETS / GOVERNANCE_TARGETS) as scope-neutral
    # so a *pure* docs-only/governance-only diff keeps resolving to that
    # lane. But several of those same directories/files are ALSO real
    # per-subsystem scope signal in SUBSYSTEMS -- e.g.
    # `tests/architecture/test_builderops_store_boundary.py` is individually
    # carved out for builder_system, `tests/ops/` for ops, `tests/scripts/`/
    # `scripts/` for ops_deploy. On a *mixed* PR, silently absorbing that
    # signal into the governance/docs branch drops the subsystem's real
    # target tests from the selection (#4336) even though a non-empty,
    # non-full-suite selection still runs -- nothing signals the coverage
    # loss. Return every subsystem match whose OWN targets are not already a
    # subset of `tolerated_targets` (docs_authoring's targets ARE
    # GOVERNANCE_TARGETS, so it never appears here) so the caller can union
    # that subsystem's real targets into the selection instead of it being
    # silently dropped.
    return [
        (name, subsystem_targets)
        for name, prefixes, subsystem_targets in SUBSYSTEMS
        if any(_subsystem_owns_path(path, name, prefixes) for path in paths)
        and any(target not in tolerated_targets for target in subsystem_targets)
    ]


def _changed_test_targets(paths: tuple[str, ...]) -> tuple[str, ...]:
    # Restricted to .py so a co-changed non-test tests/** artifact (fixture,
    # README, etc.) is never handed to pytest as a positional target — pytest
    # errors hard ("not found") on a path it can't collect as a test module.
    return tuple(
        path
        for path in paths
        if (
            path.startswith("tests/")
            and not path.startswith("tests/e2e/")
            and path.endswith(".py")
            and path not in GENERIC_PR_EXCLUDED_TARGETS
        )
    )


def _pr_targets(targets: list[str]) -> tuple[str, ...]:
    """Keep slower end-to-end coverage in the post-merge/nightly lanes."""
    return _dedupe(
        target
        for target in targets
        if target != "tests/e2e" and not target.startswith("tests/e2e/")
    )


def _is_test_module(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _heavy_target_triggered(target: str, triggers: tuple[str, ...], paths: tuple[str, ...]) -> bool:
    return any(
        path in triggers
        or any(trigger.endswith("/") and path.startswith(trigger) for trigger in triggers)
        or (_within_target_dirs(path, (target,)) and not _is_test_module(path))
        for path in paths
    )


def _deferred_heavy_targets(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        target
        for target, triggers in HEAVY_PR_DEFERRED_TARGETS.items()
        if not _heavy_target_triggered(target, triggers, paths)
    )


def _defer_heavy(selection: Selection, paths: tuple[str, ...]) -> Selection:
    deferred = _deferred_heavy_targets(paths)
    if not selection.full_suite:
        deferred = tuple(target for target in deferred if target in selection.targets)
    if not deferred:
        return selection
    return Selection(
        selection.full_suite,
        selection.subsystems,
        tuple(target for target in selection.targets if target not in deferred),
        selection.reason,
        selection.unowned_paths,
        deferred,
    )


def _uses_ops_execution_profile(selection: Selection) -> bool:
    # The suffix is emitted only after the closed BWS source/path/input guards.
    # Its changed RPC test adds ops_deploy ownership while tests/deploy is deferred.
    return selection.subsystems == ("ops",) or selection.reason.endswith("; BWS source installation scope")


def scoped_deploy_partitions(selection: Selection) -> tuple[tuple[str, ...], ...]:
    """Partition source-triggered deploy coverage without changing its targets."""
    if selection.full_suite:
        return ()
    if "tests/deploy" not in selection.targets:
        return (selection.targets,) if _uses_ops_execution_profile(selection) and _ops_test_files() else ()
    buckets: list[list[str]] = [[] for _ in SCOPED_DEPLOY_PARALLEL_ROOTS]
    remainder: list[str] = []
    serial: list[str] = []
    for target in selection.targets:
        target_file = target.split("::", 1)[0]
        if target_file == SCOPED_DEPLOY_SERIAL_ROOT or target_file.startswith(
            f"{SCOPED_DEPLOY_SERIAL_ROOT}/"
        ):
            serial.append(target)
            continue
        for index, root in enumerate(SCOPED_DEPLOY_PARALLEL_ROOTS):
            if target_file == root or target_file.startswith(f"{root}/"):
                buckets[index].append(target)
                break
        else:
            remainder.append(target)
    partitions = [tuple(bucket) for bucket in buckets if bucket]
    if remainder:
        partitions.append(tuple(remainder))
    if serial:
        partitions.append(tuple(serial))
    return tuple(partitions)


def _ops_test_files() -> tuple[str, ...]:
    root = Path("tests/ops")
    if not root.is_dir() or root.is_symlink():
        return ()
    files = tuple(str(path) for path in sorted(root.rglob("*.py")) if _is_test_module(str(path)))
    if any(not Path(path).is_file() or Path(path).is_symlink() for path in files):
        return ()
    return files


def _scoped_deploy_test_files() -> tuple[str, ...]:
    """Return the deploy test inventory in stable order.

    The selector runs before the pytest environment is installed, so this
    inventory is deliberately filesystem-only.  The runner performs the
    later collection step that can split a very large file into node-level
    work units.  Keeping this first expansion deterministic gives the
    workflow a reviewable, authenticated plan without making selection depend
    on an interpreter/plugin installation.
    """

    root = Path("tests/deploy")
    if not root.is_dir():
        return ()
    return tuple(
        str(path)
        for path in sorted(root.rglob("*.py"))
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    )


def _target_weight(target: str) -> int:
    """Use a stable, cheap proxy for balancing selector work units."""

    path = Path(target.split("::", 1)[0])
    try:
        if path.is_file():
            return max(1, len(path.read_text(encoding="utf-8").splitlines()))
    except (OSError, UnicodeError):
        pass
    return 1


def _balanced_work_units(
    targets: list[str], *, max_units: int = SCOPED_EXECUTION_MAX_WORK_UNITS
) -> tuple[tuple[str, ...], ...]:
    """Greedily balance stable target units without changing their identity."""

    if not targets:
        return ()
    buckets: list[list[str]] = [[] for _ in range(min(max_units, len(targets)))]
    weights = [0] * len(buckets)
    # Largest-first with the lexical target tie-break makes the plan stable and
    # prevents one large source file from being appended to an already-heavy
    # bucket.  The runner may refine deploy files into collected node IDs.
    ordered = sorted(set(targets), key=lambda target: (-_target_weight(target), target))
    for target in ordered:
        index = min(range(len(buckets)), key=lambda candidate: (weights[candidate], candidate))
        buckets[index].append(target)
        weights[index] += _target_weight(target)
    return tuple(tuple(bucket) for bucket in buckets if bucket)


def scoped_deploy_execution_units(selection: Selection) -> tuple[tuple[str, ...], ...]:
    """Build deterministic bounded work units for source-triggered deploy tests.

    ``scoped_deploy_partitions`` remains the authenticated selected-target
    inventory.  This derived plan expands ``tests/deploy`` into its concrete
    files, removes directory/file overlap, and balances the files into at
    most four units.  The runtime runner can refine those file units further
    into collected node IDs after dependencies are installed; no selected
    target is dropped or silently deferred.
    """

    partitions = scoped_deploy_partitions(selection)
    if not partitions:
        return ()

    if "tests/deploy" not in selection.targets and _uses_ops_execution_profile(selection):
        files = _ops_test_files()
        expanded = _dedupe([
            item for target in selection.targets
            for item in (files if target == "tests/ops" else (target,))
            if "tests/ops" not in selection.targets or target == "tests/ops"
            or not target.startswith("tests/ops/")
        ])
        serial = tuple(path for path in SCOPED_DEPLOY_SERIAL_BOUNDARY if path in expanded)
        parallel = [path for path in expanded if path not in serial]
        units = _balanced_work_units(parallel, max_units=SCOPED_EXECUTION_MAX_WORK_UNITS - bool(serial))
        return (*units, serial) if serial else units

    serial = partitions[-1] if any(
        target.split("::", 1)[0] == SCOPED_DEPLOY_SERIAL_ROOT
        or target.split("::", 1)[0].startswith(f"{SCOPED_DEPLOY_SERIAL_ROOT}/")
        for target in partitions[-1]
    ) else ()
    parallel = partitions[:-1] if serial else partitions

    expanded: list[str] = []
    deploy_directory_selected = any(
        target.split("::", 1)[0] == "tests/deploy" for partition in parallel for target in partition
    )
    deploy_files = _scoped_deploy_test_files() if deploy_directory_selected else ()
    for partition in parallel:
        for target in partition:
            path = target.split("::", 1)[0]
            if path == "tests/deploy":
                expanded.extend(deploy_files)
            elif deploy_directory_selected and path.startswith("tests/deploy/"):
                # The directory's file expansion already authenticates this
                # explicit changed-file target.  Keeping it again would run
                # the same collected tests twice (the #6193 failure shape).
                if path not in deploy_files:
                    expanded.append(target)
            else:
                expanded.append(target)

    parallel_limit = SCOPED_EXECUTION_MAX_WORK_UNITS - (1 if serial else 0)
    balanced = _balanced_work_units(expanded, max_units=max(1, parallel_limit))
    return (*balanced, serial) if serial else balanced


SCOPED_DEPLOY_SERIAL_BOUNDARY = (
    "tests/ops/test_dormant_ownership_initialization.py",
    "tests/ops/test_git_hygiene.py",
    "tests/ops/test_instance_state_deployment_lease.py",
    "tests/ops/test_instance_state_volume_contract.py",
    "tests/ops/test_instance_state_writer_inventory.py",
    "tests/ops/test_mvr05_mixed_version_fence.py",
    "tests/ops/test_native_journaling_acceptance.py",
    "tests/ops/test_start_full_runtime_health.py",
)

# These control-only changes do not change the seven sibling serial producers.
# Keep all other normal coverage, including the shared native-journaling locks.
NATIVE_DEPLOY_CONTROL_SOURCES = frozenset({
    "app/ops/host_secret_controller.py",
    "app/ops/postgres_deploy.py",
    "app/ops/postgres_deploy_linux.py",
    "app/ops/postgres_deploy_host.py",
})
NATIVE_DEPLOY_CONTROL_PATHS = NATIVE_DEPLOY_CONTROL_SOURCES | frozenset({
    "tests/deploy/test_deploy_channel.py",
    "tests/deploy/test_deploy_channel_script.py",
    "tests/deploy/test_host_deploy_metadata.py",
    "tests/deploy/test_native_image_acquisition_failure.py",
    "tests/deploy/test_native_operator_identity_restoration.py",
    "tests/deploy/test_postgres_deploy_authority_cutover.py",
    "tests/deploy/test_postgres_deploy_authority_metadata.py",
    "tests/deploy/test_postgres_deploy_linux.py",
    "tests/deploy/test_postgres_deploy_principal_cutover.py",
    "tests/deploy/test_postgres_deploy_service.py",
    "tests/deploy/test_postmerge_dev_test.py",
    "tests/deploy/test_postmerge_heavy_acceptance.py",
    "tests/deploy/test_postmerge_pg_acceptance.py",
    "tests/deploy/test_secret_token_push.py",
    "tests/deploy/test_text_capture_activation.py",
    "tests/ops/test_bws_installation_lifecycle.py",
    "tests/ops/test_bws_installation_transaction.py",
    "tests/ops/test_host_secret_bootstrap.py",
    "tests/ops/test_host_secret_contract.py",
    "tests/ops/test_native_guard_diagnostics.py",
    "tests/ops/test_native_journaling_acceptance.py",
    "tests/ops/test_native_source_diagnostic_admission.py",
    "tests/ops/test_native_source_identity_persistence.py",
    "tests/ops/test_native_web_acceptance.py",
    "tests/ops/test_native_web_lock_lifecycle.py",
    "tests/ops/test_postgres_deploy_bws_installation.py",
    "tests/ops/test_secret_admin.py",
    "docs/OPERATIONS.md",
    "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md",
    "docs/CLOUD_SECRET_PROVISIONING/README.md",
})
NATIVE_DEPLOY_UNRELATED_SERIAL = frozenset({
    "tests/ops/test_dormant_ownership_initialization.py",
    "tests/ops/test_git_hygiene.py",
    "tests/ops/test_instance_state_deployment_lease.py",
    "tests/ops/test_instance_state_volume_contract.py",
    "tests/ops/test_instance_state_writer_inventory.py",
    "tests/ops/test_mvr05_mixed_version_fence.py",
    "tests/ops/test_start_full_runtime_health.py",
})


def _native_deploy_control_selection(selection: Selection, paths: tuple[str, ...]) -> Selection:
    """Remove only audited sibling suites for a closed control-source diff."""
    if (
        selection.full_suite
        or "tests/ops" not in selection.targets
        or not NATIVE_DEPLOY_CONTROL_SOURCES.intersection(paths)
        or not set(paths) <= NATIVE_DEPLOY_CONTROL_PATHS
        or any(not Path(path).is_file() or Path(path).is_symlink() for path in paths)
    ):
        return selection
    root = Path("tests/ops")
    if not root.is_dir() or root.is_symlink():
        return selection
    modules = tuple(str(path) for path in sorted(root.rglob("*.py")) if _is_test_module(str(path)))
    if (
        not NATIVE_DEPLOY_UNRELATED_SERIAL <= set(modules)
        or any(not Path(path).is_file() or Path(path).is_symlink() for path in modules)
    ):
        return selection
    targets = _dedupe([
        item
        for target in selection.targets
        for item in (modules if target == "tests/ops" else (target,))
        if item.split("::", 1)[0] not in NATIVE_DEPLOY_UNRELATED_SERIAL
    ])
    return replace(selection, targets=targets, reason=selection.reason + "; native deploy control scope")


BWS_SOURCE_INSTALLATION_SOURCES = frozenset({
    "app/ops/bws_installation_transaction.py", "app/ops/postgres_deploy_linux.py",
})
BWS_SOURCE_INSTALLATION_PATHS = BWS_SOURCE_INSTALLATION_SOURCES | frozenset({
    "app/ops/bws_installation_admission.py",
    "app/ops/bws_installation_lifecycle.py",
    "tests/ops/test_bws_installation_admission.py",
    "tests/ops/test_bws_installation_lifecycle.py",
    "tests/ops/test_bws_installation_transaction.py",
    "tests/ops/test_bws_control_installation.py",
    "tests/ops/fixtures/host_secret_contract_legacy.json",
    "tests/deploy/test_bws_source_rpc_assembly.py",
    "docs/OPERATIONS.md",
    "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md",
})


def _bws_source_installation_selection(selection: Selection, paths: tuple[str, ...]) -> Selection:
    # The pre-existing native control profile has precedence. This additional
    # closed profile excludes only the independent dormant TEST initializer.
    if (selection.full_suite or "tests/ops" not in selection.targets
        or not BWS_SOURCE_INSTALLATION_SOURCES.intersection(paths)
        or not set(paths) <= BWS_SOURCE_INSTALLATION_PATHS
        or any(not Path(path).is_file() or Path(path).is_symlink() for path in paths)):
        return selection
    files = _ops_test_files()
    dormant = "tests/ops/test_dormant_ownership_initialization.py"
    if not set(SCOPED_DEPLOY_SERIAL_BOUNDARY) <= set(files):
        return selection
    targets = _dedupe([
        item for target in selection.targets
        for item in (files if target == "tests/ops" else (target,))
        if item != dormant
    ])
    return replace(selection, targets=targets, reason=selection.reason + "; BWS source installation scope")


def _unowned_runtime_code_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    runtime_prefixes = ("app/", "companion-ui/")
    owned_prefixes = tuple(prefix for _, prefixes, _ in SUBSYSTEMS for prefix in prefixes)
    owned_exact_paths = frozenset(
        path for exact_paths in EXACT_SUBSYSTEM_FILES.values() for path in exact_paths
    )
    return tuple(
        path
        for path in paths
        if path.startswith(runtime_prefixes)
        and path not in owned_exact_paths
        and not any(path.startswith(prefix) for prefix in owned_prefixes)
    )


def select_tests(changed_files: list[str]) -> Selection:
    paths = tuple(path for path in (_normalize(item) for item in changed_files) if path)
    if not paths:
        return Selection(True, (), (), "no changed files were provided")

    if any(_is_full_suite_file(path) for path in paths):
        return _defer_heavy(Selection(True, (), (), FULL_SUITE_REASONS[0]), paths)

    non_e2e_paths = tuple(path for path in paths if not path.startswith("tests/e2e/"))
    if not non_e2e_paths:
        return Selection(False, ("e2e",), ALWAYS_TARGETS, "E2E coverage is deferred to post-merge/nightly")

    # "alembic/" never matches a real path in this repo -- migrations live under
    # app/alembic/versions/ -- so that arm alone left every migration file routing
    # through the subsystem loop (or unowned) instead of full-suite. A subsystem that
    # happens to also list a migration path as one of its own prefixes (e.g.
    # standing_questions and app/alembic/versions/4d1e0c9a3329_...) would otherwise
    # "steal" the match and narrow a schema change no owner's suite alone can cover.
    if any(
        path.startswith("alembic/")
        or path.startswith("app/alembic/versions/")
        or path.startswith("tests/migrations/")
        for path in paths
    ):
        return _defer_heavy(Selection(True, (), (), FULL_SUITE_REASONS[1]), paths)

    unowned_runtime_code = _unowned_runtime_code_paths(paths)
    if unowned_runtime_code:
        return Selection(
            False,
            ("unowned",),
            (),
            FULL_SUITE_REASONS[2],
            unowned_runtime_code,
        )

    ci_contract_only = _is_ci_contract_only(paths)
    pr_intake_contract_only = _is_pr_intake_contract_only(paths)
    test_only = _is_test_only(paths)
    if not (ci_contract_only or pr_intake_contract_only or test_only):
        if _is_bws_control_installation_contract_only(paths):
            return Selection(
                False, ("ops",), _pr_targets([*ALWAYS_TARGETS, BWS_CONTROL_INSTALLATION_TEST]),
                "BWS control installation contract PR",
            )
        test_modules = _test_module_targets(paths)
        if test_modules is not None:
            owners = _dedupe([
                name for name, prefixes, _ in SUBSYSTEMS
                if any(_subsystem_owns_path(path, name, prefixes) for path in paths)
            ] + (["docs"] if any(path.startswith("tests/docs/") for path in paths) else []))
            return Selection(False, owners, _pr_targets([*CI_INTEGRITY_TARGETS, *test_modules]),
                             "test modules and their static consumers")
    changed_tests = (
        tuple(target for path in paths for target in ISOLATED_TEST_MODULES[path])
        if test_only else _changed_test_targets(paths)
    )
    targets = list(
        CI_CONTRACT_TARGETS if ci_contract_only
        else (*CI_CONTRACT_TARGETS, *PR_INTAKE_CONTRACT_TARGETS) if pr_intake_contract_only
        else CI_INTEGRITY_TARGETS if test_only
        else ALWAYS_TARGETS
    )
    if any(
        path in CI_CONTRACT_PATHS and path.startswith(("scripts/", "tests/scripts/"))
        for path in paths
    ) and any(
        path not in CI_CONTRACT_PATHS and _heavy_target_triggered(
            "tests/deploy", HEAVY_PR_DEFERRED_TARGETS["tests/deploy"], (path,)
        )
        for path in paths
    ):
        # Preserve deploy proof formerly selected by a CI helper's scripts/
        # ownership when it accompanies a real deploy input. The retention
        # inventory is a filter, not new source-only subsystem ownership.
        targets.append("tests/deploy")

    if any(path in ARO03_ROUTE_CONTRACT_PATHS for path in paths):
        targets.extend(ARO03_ROUTE_TESTS)

    if any(path in {"scripts/dev_delivery_liveness.py", "scripts/postmerge_controller.py"} for path in paths):
        targets.extend(DEV_LIVENESS_TESTS)

    governance_only = _is_governance_only(paths)
    docs_only = _is_docs_only(paths) if not governance_only else False

    if ci_contract_only:
        subsystems, reason = ("governance",), "CI contract-only PR"
    elif pr_intake_contract_only:
        subsystems, reason = ("governance", "builder_system"), "PR intake/publication contract PR"
    elif test_only:
        subsystems, reason = ("tests",), "isolated test-only smoke; exhaustive matrix deferred"
    elif governance_only or docs_only:
        tolerated_targets = GOVERNANCE_TARGETS if governance_only else DOCS_TARGETS
        targets.extend(tolerated_targets)
        subsystems_list = ["governance" if governance_only else "docs"]
        # A mixed PR can still have a real subsystem owner behind one of the
        # tolerated GOVERNANCE_TARGETS/DOCS_TARGETS test directories (#4336) --
        # union that subsystem's own targets in rather than silently dropping
        # them, instead of collapsing the whole diff to governance/docs-only.
        for name, subsystem_targets in _foreign_subsystem_matches(paths, tolerated_targets):
            subsystems_list.append(name)
            targets.extend(subsystem_targets)
        subsystems = _dedupe(subsystems_list)
        reason = (
            "governance-only PR"
            if governance_only and len(subsystems) == 1
            else "docs-only PR"
            if docs_only and len(subsystems) == 1
            else "mixed governance/docs PR with a foreign subsystem-owned test path"
        )
    else:
        matched: list[str] = []
        for name, prefixes, subsystem_targets in SUBSYSTEMS:
            if any(_subsystem_owns_path(path, name, prefixes) for path in paths):
                matched.append(name)
                targets.extend(subsystem_targets)
        if not matched:
            return Selection(False, ("unowned",), (), FULL_SUITE_REASONS[2], paths)
        subsystems, reason = _dedupe(matched), "matched subsystem SoI"

    # Subsystem and docs branches funnel through this return, so changed
    # test coverage (or the explicit isolated smoke) is unioned once — no splice
    # to forget if a future branch is added here (the #3383 failure mode).
    selection = _defer_heavy(
        Selection(False, subsystems, _pr_targets([*targets, *changed_tests]), reason), paths
    )
    return _bws_source_installation_selection(_native_deploy_control_selection(selection, paths), paths)


def changed_files_from_git(base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        # Keep both old and new paths for renames. The missing old module must
        # disqualify test-only selection rather than hiding broken import users.
        ["git", "diff", "--no-renames", "--name-only", f"{base_ref}...{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _existing_test_targets(targets: tuple[str, ...]) -> tuple[str, ...]:
    # Deleted/renamed test files must never reach pytest as a positional
    # target (pytest errors hard on a path that no longer exists). Directory
    # targets pass through unfiltered; file and node-id targets check their
    # file portion before pytest receives them.
    return tuple(
        target
        for target in targets
        if not (target_file := target.split("::", 1)[0]).endswith(".py")
        or Path(target_file).is_file()
    )


def requires_runtime_checks(changed_files: list[str]) -> bool:
    """Text, CI-only and isolated-test changes omit unrelated Product gates.

    Executable paths outside the exact CI contract set, fixtures, configuration
    and mixed changes stay conservative. A Markdown suffix alone is insufficient.
    """
    paths = tuple(_normalize(path) for path in changed_files if _normalize(path))
    if _is_pr_intake_contract_only(paths) and any(
        path in PR_INTAKE_RUNTIME_SOURCE_PATHS for path in paths
    ):
        # App and executable publication/review helpers still receive the
        # mandatory Product type/runtime gates, even though pytest is scoped to
        # the exact contracts that read them.
        return True
    if _is_pr_intake_contract_only(paths):
        # The GitHub workflow contract has its direct governance readers and
        # does not change the Python application type surface.
        return False
    if _is_ci_contract_only(paths) or _is_test_only(paths):
        return False
    return not paths or not all(
        path in {"README.md", "CHANGELOG.md", "AGENTS.md", "CLAUDE.md"}
        or (path.endswith(".md") and path.startswith(("docs/", ".codex/")))
        for path in paths
    )


def _write_github_output(path: str, selection: Selection, *, runtime_checks: bool = True) -> None:
    output = Path(path)
    partitions = scoped_deploy_partitions(selection)
    execution_units = scoped_deploy_execution_units(selection)
    target_files = {target.split("::", 1)[0] for target in selection.targets}
    serial_boundary = (
        SCOPED_DEPLOY_SERIAL_BOUNDARY
        if SCOPED_DEPLOY_SERIAL_ROOT in target_files
        else tuple(path for path in SCOPED_DEPLOY_SERIAL_BOUNDARY if path in target_files)
    )
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"full_suite={'true' if selection.full_suite else 'false'}\n")
        handle.write(f"subsystems={','.join(selection.subsystems) or 'all'}\n")
        handle.write(f"pytest_args={selection.pytest_args}\n")
        handle.write(f"reason={selection.reason}\n")
        handle.write(f"deferred_targets={' '.join(selection.deferred_targets)}\n")
        handle.write(f"runtime_checks={'true' if runtime_checks else 'false'}\n")
        handle.write(f"pytest_targets_json={json.dumps(selection.targets, separators=(',', ':'))}\n")
        handle.write(f"scoped_partitions_json={json.dumps(partitions, separators=(',', ':'))}\n")
        handle.write(
            "scoped_execution_units_json="
            f"{json.dumps(execution_units, separators=(',', ':'))}\n"
        )
        handle.write(
            "scoped_serial_boundary_json="
            f"{json.dumps(serial_boundary, separators=(',', ':'))}\n"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Select PR pytest targets from changed subsystem files.")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file path. Repeatable.")
    parser.add_argument("--base-ref", default="", help="Base git ref for diff selection.")
    parser.add_argument("--head-ref", default="HEAD", help="Head git ref for diff selection.")
    parser.add_argument("--github-output", default="", help="Optional GITHUB_OUTPUT path.")
    parser.add_argument(
        "--print-heavy-targets",
        action="store_true",
        help="Print the heavy targets the post-merge/nightly heavy-tests workflow runs, then exit.",
    )
    args = parser.parse_args()

    if args.print_heavy_targets:
        print(" ".join(HEAVY_PR_DEFERRED_TARGETS))
        return 0

    changed = args.changed_file
    if not changed and args.base_ref:
        changed = changed_files_from_git(args.base_ref, args.head_ref)

    selection = select_tests(changed)
    if not selection.full_suite:
        selection = Selection(
            selection.full_suite,
            selection.subsystems,
            _existing_test_targets(selection.targets),
            selection.reason,
            selection.unowned_paths,
            selection.deferred_targets,
        )
    print(f"full_suite={'true' if selection.full_suite else 'false'}")
    print(f"subsystems={','.join(selection.subsystems) or 'all'}")
    print(f"pytest_args={selection.pytest_args}")
    print(f"reason={selection.reason}")
    print(f"deferred_targets={' '.join(selection.deferred_targets)}")
    if selection.unowned_paths:
        print(f"unowned_paths={','.join(selection.unowned_paths)}")
        return 2

    if args.github_output:
        _write_github_output(
            args.github_output, selection, runtime_checks=requires_runtime_checks(changed)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
