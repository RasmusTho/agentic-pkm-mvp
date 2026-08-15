from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


STATIC_TARGET_COLLECTABILITY_FITNESS = (
    "tests/scripts/test_select_pr_tests.py::test_static_selector_targets_are_collectable"
)

ALWAYS_TARGETS = (
    "tests/ci",
    # This test must run on every scoped PR: a deleting/renaming PR otherwise
    # filters its missing static target before pytest has a chance to detect it.
    STATIC_TARGET_COLLECTABILITY_FITNESS,
    # The outbox producer gates are repo-wide AST censuses over app/, so the PR
    # that breaks them is by definition a PR that adds or edits a producer —
    # and every producer today lives in an OWNED subsystem (heimdal, watcher,
    # api routes, panel, workers, services, receipts, knowledge_acquisition).
    # A scoped selection therefore excluded exactly the PRs these gates exist
    # to catch, and a new producer defaulting to the dropping path could merge
    # with a green required check (#4214 D5). They are cheap — pure ast.parse
    # over app/, no fixtures, seconds — so run them on every scoped PR.
    "tests/architecture/test_outbox_producer_durability.py",
    "tests/architecture/test_outbox_producer_idempotency.py",
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
    "app/cli/__init__.py",
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

# Node-id targets outside SUBSYSTEMS still need the always-run static census.
# Otherwise a renamed ARO-03 route proof could be filtered out before CI asks
# pytest to collect it, leaving the exact-path selector green without proof.
STATIC_SELECTOR_NODE_ID_TARGETS = ARO03_ROUTE_TESTS

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

SUBSYSTEMS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "builder_system",
        (
            "app/builderops/",
            "app/dispatcher/",
            # Static Builder surfaces (signboard, cockpit) render dispatcher/
            # BuilderOps state; their regressions live in tests/dispatcher and
            # tests/builderops. companion_ui co-owns this prefix because the
            # API process mounts and serves it.
            "app/web/",
            "tests/builderops/",
            "tests/dispatcher/",
            "tests/governance/",
            # BuilderOps store-access inventory fitness. Keep this exact file
            # owned without widening builder_system to all architecture tests.
            "tests/architecture/test_builderops_store_boundary.py",
            # pr-contract/BuilderOps-routing hot-path governance fitness
            # (#4343): a pure change to this one test file has no non-test
            # governance/docs path alongside it, so `_is_governance_only`
            # (which requires real non-test signal) never fires and the PR
            # fell through the SUBSYSTEMS loop into `unowned` (exit 2). Own
            # this exact file the same way test_builderops_store_boundary.py
            # is owned above, without widening builder_system to all
            # architecture tests.
            "tests/architecture/test_pr_hot_path_governance.py",
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
            "tests/governance",
            "tests/architecture/test_builderops_store_boundary.py",
            "tests/architecture/test_pr_hot_path_governance.py",
        ),
    ),
    (
        "model_access",
        (
            "llm_contract/",
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
            "tests/ports",
            "tests/services/test_vault_sync_lifecycle.py",
            "tests/services/test_vault_sync_atomicity.py",
            "tests/services/test_vault_sync_delete_note_policy.py",
            "tests/watcher/test_vault_watcher_delete_required_outbox.py",
            "tests/architecture/test_no_hardcoded_vault_layout.py",
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
            # The object-store facade writes canonical objects through the
            # store provider seam and emits ingest lifecycle events. Keep this
            # shared producer on the established store/ingest contracts
            # without claiming the whole app/objects package.
            "app/objects/__init__.py",
            "tests/stores/",
            "tests/ingest/",
            "docs/DB_SCHEMA.md",
            "docs/RUNTIME_CORRECTNESS_KERNEL/",
        ),
        (
            "tests/stores",
            "tests/ingest",
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
        "orchestration",
        (
            "app/orchestrator/",
            "app/orchestration/",
            "tests/orchestrator/",
            "tests/orchestration/",
            "tests/e2e/test_pipe_graph.py",
            "tests/e2e/test_runtime_contract_regressions.py",
        ),
        ("tests/orchestrator", "tests/orchestration", *E2E_TARGETS["orchestration"]),
    ),
    (
        "memory_retrieval",
        (
            "app/memory/",
            "app/retrieval/",
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
            "tests/indexer/",
            "tests/e2e/test_index_rules_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_reality_mvp_pipeline.py",
        ),
        (
            "tests/agent_memory",
            "tests/retrieval",
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
            "tests/architecture/test_cross_scope_flow_schema.py",
            "tests/invariants/test_episode_binding.py",
            "tests/invariants/test_cross_scope_flow.py",
            "docs/architecture/cross-scope-flow.md",
        ),
        (
            "tests/episodes",
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
            "docs/MIMER_CAPABILITY_HARDENING/",
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
            "tests/index/test_identity_migration.py",
            "tests/llm",
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
        ("app/events/", "app/receipts/", "docs/contracts/events/", "tests/events/", "tests/receipts/"),
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
        ),
    ),
    (
        "heimdal_mimer",
        (
            "app/heimdal/",
            "app/knowledge_acquisition/",
            "app/source_egress.py",
            "docs/HEIMDAL/",
            "docs/KARAKEEP_MIMER_ACQUISITION/",
            "docs/KNOWLEDGE_ACQUISITION/",
            "docs/EVENTS.md",
            "tests/heimdal/",
            "tests/knowledge_acquisition/",
        ),
        ("tests/heimdal", "tests/knowledge_acquisition"),
    ),
    (
        "journaling",
        (
            "app/journaling/",
            "app/activation/journal_draft.py",
            "app/knowledge_compilation/proposal_builders.py",
            "tests/journaling/",
            "docs/CONVERSATIONAL_JOURNALING/",
        ),
        (
            "tests/journaling",
            "tests/activation/test_journal_draft_activation.py",
            "tests/knowledge_compilation/test_proposal_builders.py",
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
        "ops",
        ("app/ops/", "tests/ops/"),
        ("tests/ops",),
    ),
    (
        "ops_deploy",
        (
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
        ("app/release_channels/", "tests/release_channels/", "docs/RELEASE_CHANNELS/"),
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


@dataclass(frozen=True)
class Selection:
    full_suite: bool
    subsystems: tuple[str, ...]
    targets: tuple[str, ...]
    reason: str
    unowned_paths: tuple[str, ...] = ()

    @property
    def pytest_args(self) -> str:
        marker = f'-m "{PR_MARKER_EXPRESSION}"'
        if self.full_suite:
            return f"-q {marker} tests --ignore=tests/e2e"
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
        path.startswith(governance_prefixes) or path == "scripts/select_pr_tests.py"
        for path in non_test
    )


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
        if any(path.startswith(prefix) for path in paths for prefix in prefixes)
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
    return _dedupe(target for target in targets if not target.startswith("tests/e2e/"))


def _unowned_runtime_code_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    runtime_prefixes = ("app/", "companion-ui/")
    owned_prefixes = tuple(prefix for _, prefixes, _ in SUBSYSTEMS for prefix in prefixes)
    return tuple(
        path
        for path in paths
        if path.startswith(runtime_prefixes)
        and not any(path.startswith(prefix) for prefix in owned_prefixes)
    )


def select_tests(changed_files: list[str]) -> Selection:
    paths = tuple(path for path in (_normalize(item) for item in changed_files) if path)
    if not paths:
        return Selection(True, (), (), "no changed files were provided")

    if any(_is_full_suite_file(path) for path in paths):
        return Selection(True, (), (), FULL_SUITE_REASONS[0])

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
        return Selection(True, (), (), FULL_SUITE_REASONS[1])

    unowned_runtime_code = _unowned_runtime_code_paths(paths)
    if unowned_runtime_code:
        return Selection(
            False,
            ("unowned",),
            (),
            FULL_SUITE_REASONS[2],
            unowned_runtime_code,
        )

    changed_tests = _changed_test_targets(paths)
    targets = list(ALWAYS_TARGETS)

    if any(path in ARO03_ROUTE_CONTRACT_PATHS for path in paths):
        targets.extend(ARO03_ROUTE_TESTS)

    governance_only = _is_governance_only(paths)
    docs_only = _is_docs_only(paths) if not governance_only else False

    if governance_only or docs_only:
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
            if any(path.startswith(prefix) for path in paths for prefix in prefixes):
                matched.append(name)
                targets.extend(subsystem_targets)
        if not matched:
            return Selection(False, ("unowned",), (), FULL_SUITE_REASONS[2], paths)
        subsystems, reason = _dedupe(matched), "matched subsystem SoI"

    # Every scoped branch funnels through this single return, so a changed
    # tests/** file is always unioned in exactly once — no per-branch splice
    # to forget if a future branch is added here (the #3383 failure mode).
    return Selection(False, subsystems, _pr_targets([*targets, *changed_tests]), reason)


def changed_files_from_git(base_ref: str, head_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
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


def _write_github_output(path: str, selection: Selection) -> None:
    output = Path(path)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"full_suite={'true' if selection.full_suite else 'false'}\n")
        handle.write(f"subsystems={','.join(selection.subsystems) or 'all'}\n")
        handle.write(f"pytest_args={selection.pytest_args}\n")
        handle.write(f"reason={selection.reason}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Select PR pytest targets from changed subsystem files.")
    parser.add_argument("--changed-file", action="append", default=[], help="Changed file path. Repeatable.")
    parser.add_argument("--base-ref", default="", help="Base git ref for diff selection.")
    parser.add_argument("--head-ref", default="HEAD", help="Head git ref for diff selection.")
    parser.add_argument("--github-output", default="", help="Optional GITHUB_OUTPUT path.")
    args = parser.parse_args()

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
        )
    print(f"full_suite={'true' if selection.full_suite else 'false'}")
    print(f"subsystems={','.join(selection.subsystems) or 'all'}")
    print(f"pytest_args={selection.pytest_args}")
    print(f"reason={selection.reason}")
    if selection.unowned_paths:
        print(f"unowned_paths={','.join(selection.unowned_paths)}")
        return 2

    if args.github_output:
        _write_github_output(args.github_output, selection)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
