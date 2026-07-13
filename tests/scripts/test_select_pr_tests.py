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
    assert "tests/e2e/test_panel_to_promotion_consume.py" not in selection.targets
    assert "tests/e2e" not in selection.targets
    assert selection.pytest_args.startswith('-q -m "not pg and not alpha_llm')
    assert "not panel_llm_e2e" in selection.pytest_args


def test_canvas_chat_change_selects_chat_coverage() -> None:
    selection = select_tests(["app/chat/session_log.py", "tests/chat/test_session_log_writer.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("canvas_chat",)
    assert selection.unowned_paths == ()
    assert "tests/chat" in selection.targets
    assert "tests/chat/test_session_log_writer.py" in selection.targets


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


def test_unknown_path_is_reported_as_unowned() -> None:
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


def test_journaling_change_has_a_ci_owner() -> None:
    selection = select_tests(
        ["app/journaling/day_context.py", "tests/journaling/test_assemble_day_context.py"]
    )

    assert selection.full_suite is False
    assert selection.subsystems == ("journaling",)
    assert selection.unowned_paths == ()
    assert "tests/journaling" in selection.targets


def test_store_ingest_change_selects_its_owned_contract_tests() -> None:
    selection = select_tests(["app/stores/postgres.py", "tests/ingest/test_vault_root_ingest_pg.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("store_ingest",)
    assert selection.unowned_paths == ()
    assert "tests/stores" in selection.targets
    assert "tests/ingest" in selection.targets
    assert "tests/architecture" in selection.targets


def test_heimdal_capture_adapter_change_has_a_ci_owner() -> None:
    selection = select_tests(["app/heimdal/capture_adapter.py", "tests/heimdal/test_capture_adapter.py"])

    assert selection.full_suite is False
    # Capture adapter changes also exercise the cross-constituent handoff
    # contract, so the narrower Heimdal owner coexists with heimdal_mimer.
    assert selection.subsystems == ("heimdal", "heimdal_mimer")
    assert selection.unowned_paths == ()
    assert "tests/heimdal" in selection.targets
    assert "tests/heimdal/test_capture_adapter.py" in selection.targets


def test_shared_panel_watcher_e2e_file_is_deferred_to_post_merge() -> None:
    selection = select_tests(["tests/e2e/test_panel_watcher_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("e2e",)
    assert selection.targets == ("tests/ci",)


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


def test_panel_live_e2e_is_deferred_to_post_merge() -> None:
    selection = select_tests(["tests/e2e/test_panel_llm_e2e.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("e2e",)
    assert selection.targets == ("tests/ci",)
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
    assert "tests/episodes/test_stream_registry.py" in selection.targets

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

def test_builder_system_change_selects_its_own_regression_tests() -> None:
    selection = select_tests(["app/builderops/cli.py"])

    assert selection.full_suite is False
    assert selection.subsystems == ("builder_system",)
    assert "tests/builderops" in selection.targets
    assert "tests/governance" in selection.targets


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
