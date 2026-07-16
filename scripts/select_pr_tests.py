from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path


ALWAYS_TARGETS = (
    "tests/ci",
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
)

DOCS_ONLY_EXCLUDED_EXACT = {
    # This owner document is executable CrossScopeFlow contract surface. Route
    # even a docs-only edit through Episodes instead of the generic docs lane.
    "docs/architecture/cross-scope-flow.md",
}

GOVERNANCE_TARGETS = (
    "tests/governance",
    "tests/scripts",
    "tests/ops/test_ci_workflow.py",
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
            "tests/builderops/",
            "tests/dispatcher/",
            "tests/governance/",
            "docs/builderops/",
            "importlinter.ini",
        ),
        ("tests/builderops", "tests/dispatcher", "tests/governance"),
    ),
    (
        "settings",
        (
            "app/settings/",
            "app/cli/settings_explain.py",
            "app/services/companion_eligibility.py",
            "app/services/settings.py",
            "docs/settings/",
            "tests/settings/",
            "tests/config/",
        ),
        ("tests/settings", "tests/config"),
    ),
    (
        "vault",
        ("app/vault/", "tests/vault/", "tests/knowledge/", "docs/VAULT", "docs/builderops/BUILDEROPS_VAULT"),
        ("tests/vault", "tests/knowledge", "tests/ports"),
    ),
    (
        "companion_ui",
        (
            "companion-ui/",
            "app/api/",
            "api/",
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
            "scripts/run_live_watcher.sh",
            "tests/watcher/",
            "tests/sync/",
            "tests/e2e/test_runtime_loop_vault_test.py",
            "tests/e2e/test_watcher_registry_e2e.py",
            "tests/e2e/test_panel_watcher_e2e.py",
        ),
        ("tests/watcher", "tests/sync", *E2E_TARGETS["watcher_sync"]),
    ),
    (
        "runtime_health",
        (
            "app/runtime/health_probe.py",
            "app/cli/health.py",
            "docker-compose.yaml",
            "tests/health/",
            "tests/invariants/test_health_probe.py",
            "tests/invariants/test_health_heartbeat_visibility.py",
            "docs/OBSERVABILITY_STABILIZATION/",
        ),
        ("tests/health", "tests/invariants", "tests/api"),
    ),
    (
        "store_ingest",
        (
            "app/stores/",
            "app/ingest/",
            "tests/stores/",
            "tests/ingest/",
            "docs/DB_SCHEMA.md",
            "docs/RUNTIME_CORRECTNESS_KERNEL/",
        ),
        ("tests/stores", "tests/ingest", "tests/architecture"),
    ),
    (
        "relevance",
        ("app/relevance/", "tests/relevance/"),
        ("tests/relevance",),
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
        ("app/heimdal/", "tests/heimdal/", "docs/HEIMDAL/", "docs/HEIMDAL_CAPTURE_CLIENT/"),
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
            "tests/agent_memory/",
            "tests/retrieval/",
            "tests/indexer/",
            "tests/e2e/test_index_rules_e2e.py",
            "tests/e2e/test_promotion_intent_to_index.py",
            "tests/e2e/test_reality_mvp_pipeline.py",
        ),
        ("tests/agent_memory", "tests/retrieval", "tests/indexer", "tests/search", *E2E_TARGETS["memory_retrieval"]),
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
        ("app/media/",),
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
            "tests/workers/",
            "tests/worker/",
            "tests/services/test_outbox_idempotency.py",
        ),
        (
            "tests/workers",
            "tests/worker",
            "tests/services/test_outbox_idempotency.py",
            "tests/events",
        ),
    ),
    (
        "heimdal_mimer",
        (
            "app/heimdal/",
            "app/knowledge_acquisition/",
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
        ("app/journaling/", "tests/journaling/", "docs/CONVERSATIONAL_JOURNALING/"),
        ("tests/journaling",),
    ),
    (
        "promotion_panel",
        (
            "app/agents/panel_agent/",
            "app/agents/panel/",
            "app/promotion/",
            "app/panel/",
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
        ),
    ),
    (
        "ops_deploy",
        ("scripts/", "ops/", "config/deploy/", "tests/ops/", "tests/scripts/", "tests/deploy/"),
        ("tests/ops", "tests/scripts", "tests/deploy"),
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
        ("tests/properties/",),
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
        and (path.startswith("docs/") or path in {"README.md", "AGENTS.md"})
        for path in non_test
    )


def _is_governance_only(paths: tuple[str, ...]) -> bool:
    governance_prefixes = (".github/", "docs/development/", "AGENTS.md", ".codex/")
    non_test = _non_test_signal(paths, GOVERNANCE_TARGETS)
    return bool(non_test) and all(
        path.startswith(governance_prefixes) or path == "scripts/select_pr_tests.py"
        for path in non_test
    )


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

    if _is_governance_only(paths):
        targets.extend(GOVERNANCE_TARGETS)
        subsystems, reason = ("governance",), "governance-only PR"
    elif _is_docs_only(paths):
        targets.extend(DOCS_TARGETS)
        subsystems, reason = ("docs",), "docs-only PR"
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
    # targets (never end in .py) always pass through unfiltered.
    return tuple(target for target in targets if not target.endswith(".py") or Path(target).is_file())


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
