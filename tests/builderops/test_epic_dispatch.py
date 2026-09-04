from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from app.builderops import epic_dispatch as epic_dispatch_module
from app.builderops.delivery_orchestration_contracts import canonical_hash
from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_dispatch import (
    CodexIssueSessionLauncher,
    EpicDispatchError,
    IssueSessionLaunchError,
    build_dispatch_plan,
    dispatch_issue_sessions,
    frozen_dispatch_plan_hash,
)
from app.builderops.epic_run_state import (
    apply_epic_run_update,
    create_epic_run_state,
    epic_run_state_path,
)


def _candidate(
    issue_number: int,
    *,
    risk: str = "medium",
    expected_value: str = "medium",
    runtime_hint: str | None = None,
    files: list[str] | None = None,
    validation_resources: list[str] | None = None,
    owner_docs: list[str] | None = None,
    owner_doc_writeback_required: bool = False,
    dependencies: list[int] | None = None,
    dependencies_satisfied: bool = False,
    labels: list[str] | None = None,
    project_status: str = "Ready",
    preferred_path: str | None = None,
    scriptable: bool = False,
    worktree: str | None = None,
    issue_local_helper_budget: int = 0,
    issue_local_helper_rationale: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "issue_number": issue_number,
        "title": f"child {issue_number}",
        "url": f"https://example.test/issues/{issue_number}",
        "state": "OPEN",
        "labels": labels if labels is not None else ["agent:ready", "type:task"],
        "project_status": project_status,
        "risk": risk,
        "expected_value": expected_value,
        "runtime_hint": runtime_hint,
        "likely_touched_files": files or [],
        "validation_resources": validation_resources or [],
        "owner_docs": owner_docs or ["docs/development/BUILDER_SUBAGENT_ROLES.md"],
        "owner_doc_writeback_required": owner_doc_writeback_required,
        "dependencies": dependencies or [],
        "dependencies_satisfied": dependencies_satisfied,
        "dependencies_known": True,
        "strict_ready": True,
        "authority_ambiguous": False,
        "has_migration": False,
        "contract_surfaces": [],
        "source_anchors": ["#3229"],
        "known_constraints": ["worker self-claims through issue-to-code"],
        "validation": ["pytest -q tests/builderops/test_epic_dispatch.py"],
        "issue_local_helper_budget": issue_local_helper_budget,
        "issue_local_helper_rationale": issue_local_helper_rationale,
    }
    if preferred_path is not None:
        payload["preferred_path"] = preferred_path
    if scriptable:
        payload["scriptable"] = True
    if worktree is not None:
        payload["worktree"] = worktree
    return payload


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
    )


class _RecordingSessionLauncher:
    def __init__(self, responses: list[object]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def launch(
        self,
        context_pack: Mapping[str, object],
        *,
        execution_routing: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        call = dict(context_pack)
        if execution_routing is not None:
            call["_execution_routing"] = dict(execution_routing)
        self.calls.append(call)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, dict)
        return response


def _worker_receipt(
    issue_number: int,
    *,
    final_state: str = "handoff",
) -> dict[str, object]:
    return {
        "role": "slice_implementer",
        "task": f"#{issue_number}",
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "branch": f"codex/issue-{issue_number}",
        "worktree": f"/tmp/issue-{issue_number}",
        "actions": ["implemented"],
        "ac_verdicts": ["pass"],
        "lifecycle_mutations": [],
        "validation": ["pass"],
        "owner_doc_result": "none",
        "residual_risk": "none",
        "final_state": final_state,
        "next_step": "verify PR",
        "context_cost": {
            "measurement": "proxy",
            "input_tokens": "unknown(runtime-not-exposed)",
            "agent_starts": 1,
            "context_pack_bytes": "unknown(not-recorded)",
            "compactions": "unknown(runtime-not-exposed)",
        },
    }


def test_tcd_decisions_cover_inline_subagent_and_overfan() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-dispatch",
        max_parallel=1,
        candidates=[
            _candidate(1001, risk="low", expected_value="low"),
            _candidate(1002, risk="high", expected_value="high", files=["app/a.py"]),
            _candidate(1003, risk="high", expected_value="high", files=["app/b.py"]),
        ],
    )

    decisions = {item["issue_number"]: item for item in plan["decisions"]}
    assert decisions[1001]["selected_path"] == "inline"
    assert decisions[1001]["skip_reason"] == "inline-local-cheaper"
    assert decisions[1002]["selected_path"] == "subagent"
    assert decisions[1002]["selected_for_dispatch"] is True
    assert decisions[1002]["runtime_model_hint"]["model_class"] == "high-reasoning"
    assert decisions[1003]["selected_path"] == "skip"
    assert decisions[1003]["skip_reason"] == "parallel-slot-cap"
    assert plan["github_mutations"] == []
    assert plan["agent_spawns"] == []


def test_parallel_selection_rejects_file_lease_dependency_and_validation_conflicts() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-conflicts",
        max_parallel=5,
        active_leases=[{"issue_number": "2005"}],
        candidates=[
            _candidate(2001, risk="high", files=["app/a.py"], validation_resources=["unit"]),
            _candidate(2002, risk="high", files=["app/a.py"]),
            _candidate(2003, risk="high", dependencies=[1999]),
            _candidate(2004, risk="high", validation_resources=["unit"]),
            _candidate(2005, risk="high"),
        ],
    )

    decisions = {item["issue_number"]: item for item in plan["decisions"]}
    assert decisions[2001]["selected_for_dispatch"] is True
    assert decisions[2002]["skip_reason"] == "likely-file-conflict"
    assert decisions[2003]["skip_reason"] == "dependency-not-ready"
    assert decisions[2004]["skip_reason"] == "validation-resource-conflict"
    assert decisions[2005]["skip_reason"] == "active-lease-conflict"


def test_project_status_does_not_gate_dispatch() -> None:
    missing = _candidate(2103, risk="high")
    missing.pop("project_status")
    candidates = [
        _candidate(2101, risk="high", project_status="Backlog"),
        _candidate(2102, risk="high", project_status="In Progress"),
        missing,
    ]

    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-project-projection",
        max_parallel=3,
        candidates=candidates,
    )

    assert plan["requested_max_parallel"] == 3
    assert plan["max_parallel"] == 2
    assert plan["parallel_cap_reason"] == "configured-non-root-agent-slot-cap"
    assert plan["selected_count"] == 2
    assert [item["skip_reason"] for item in plan["decisions"]] == [
        None,
        None,
        "parallel-slot-cap",
    ]


def test_dispatch_runtime_targets_are_codex_only() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-runtime",
        candidates=[
            _candidate(3001, risk="high", runtime_hint="codex", files=["app/a.py"]),
            _candidate(3002, risk="high", files=["app/b.py"]),
        ],
    )

    packs = plan["context_packs"]
    assert plan["runtime_targets"] == ["codex"]
    assert [pack["runtime"]["runtime"] for pack in packs] == ["codex", "codex"]
    assert packs[0].keys() == packs[1].keys()
    assert packs[0]["return_schema"] == packs[1]["return_schema"]
    assert "subagent_handoff_receipt" == packs[0]["return_schema"]["schema_name"]
    assert "full_epic_narrative" not in json.dumps(packs)
    assert packs[0]["branch_worktree_plan"]["coordinator_preclaim"] is False
    assert packs[0]["branch_worktree_plan"]["worker_self_claim"] is True
    assert packs[0]["coordination"] == {
        "routine_worker_to_worker": "prohibited",
        "discovered_overlap": "typed-coordinator-exception",
        "coordinator_scope": "cross_issue_only",
        "worker_scope": "one_issue_end_to_end",
        "issue_local_helper_budget": 0,
        "issue_local_helper_rationale": None,
        "sole_writer": "issue_agent",
    }
    assert "context_cost" in packs[0]["return_schema"]["required_fields"]
    assert packs[0]["return_schema"]["schema_version"] == 2
    baseline = packs[0]["context_cost_baseline"]
    without_baseline = dict(packs[0])
    without_baseline.pop("context_cost_baseline")
    assert baseline["context_pack_bytes_excluding_baseline"] == len(
        json.dumps(without_baseline, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )

    with pytest.raises(EpicDispatchError, match="Codex-only"):
        build_dispatch_plan(
            epic_issue_number=3229,
            run_id="run-claude-rejected",
            runtime_targets=["codex", "claude"],
            candidates=[_candidate(3003, risk="high", files=["app/c.py"])],
        )

    with pytest.raises(EpicDispatchError, match="runtime_hint must be codex"):
        build_dispatch_plan(
            epic_issue_number=3229,
            run_id="run-claude-hint-rejected",
            candidates=[
                _candidate(3004, risk="high", runtime_hint="claude", files=["app/d.py"])
            ],
        )


def test_cli_dispatch_plan_rejects_non_codex_runtime(tmp_path: Path) -> None:
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        json.dumps({"candidates": [_candidate(3005, risk="high", files=["app/a.py"])]}),
        encoding="utf-8",
    )

    result = _run_builderops(
        [
            "epic-run-state",
            "dispatch-plan",
            "--epic-issue-number",
            "3229",
            "--run-id",
            "run-cli-claude-rejected",
            "--root",
            str(tmp_path),
            "--candidates-file",
            str(candidates_file),
            "--runtime",
            "claude",
            "--json",
        ]
    )

    assert result.exit_code != 0
    assert "Codex-only" in result.output


def test_codex_launcher_resolves_model_from_capability_census(tmp_path: Path) -> None:
    census_source = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "settings"
        / "models"
        / "providers.yaml"
    ).read_text(encoding="utf-8")
    configured_model = "configured-sol-model"
    census_path = tmp_path / "providers.yaml"
    census_path.write_text(
        census_source.replace("gpt-5.6-sol", configured_model), encoding="utf-8"
    )
    plan = build_dispatch_plan(
        independent_issue_numbers=[3006],
        run_id="census-model-resolution",
        candidates=[
            _candidate(
                3006,
                risk="high",
                files=["app/a.py"],
                worktree=str(tmp_path / "issue-3006"),
            )
        ],
    )

    launcher = CodexIssueSessionLauncher(
        repo_root=tmp_path,
        provider_census_path=census_path,
    )
    command = launcher.command(plan["context_packs"][0])

    assert command[command.index("--model") + 1] == configured_model


def test_context_pack_overlap_policy_matches_dispatch_scope() -> None:
    overlapping_candidates = [
        _candidate(3001, risk="high", files=["app/shared.py"]),
        _candidate(3002, risk="high", files=["app/shared.py"]),
    ]
    epic_plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-epic-overlap-policy",
        candidates=overlapping_candidates,
    )

    assert epic_plan["selected_count"] == 1
    assert epic_plan["decisions"][1]["skip_reason"] == "likely-file-conflict"
    assert epic_plan["context_packs"][0]["coordination"]["discovered_overlap"] == (
        "typed-coordinator-exception"
    )
    with patch.object(epic_dispatch_module, "_build_context_pack") as build_pack:
        with pytest.raises(EpicDispatchError, match="likely shared mutation surface"):
            build_dispatch_plan(
                independent_issue_numbers=[3001, 3002],
                run_id="run-independent-overlap-policy",
                candidates=overlapping_candidates,
            )
    build_pack.assert_not_called()


def test_context_pack_carries_bounded_issue_local_helper_budget() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-helper-budget",
        candidates=[
            _candidate(
                3051,
                risk="high",
                issue_local_helper_budget=1,
                issue_local_helper_rationale="independent state-machine test design",
            )
        ],
    )

    assert plan["context_packs"][0]["coordination"]["issue_local_helper_budget"] == 1

    invalid = _candidate(3052, risk="high")
    invalid["issue_local_helper_budget"] = 2
    try:
        build_dispatch_plan(
            epic_issue_number=3229,
            run_id="run-invalid-helper-budget",
            candidates=[invalid],
        )
    except EpicDispatchError as exc:
        assert str(exc) == "issue_local_helper_budget must be 0 or 1"
    else:
        raise AssertionError("invalid helper budget was accepted")

    trivial = _candidate(
        3053,
        risk="low",
        issue_local_helper_budget=1,
        issue_local_helper_rationale="unnecessary helper",
    )
    try:
        build_dispatch_plan(
            epic_issue_number=3229,
            run_id="run-trivial-helper-budget",
            candidates=[trivial],
        )
    except EpicDispatchError as exc:
        assert "requires high/critical risk" in str(exc)
    else:
        raise AssertionError("trivial helper allocation was accepted")

    missing_rationale = _candidate(3054, risk="high", issue_local_helper_budget=1)
    try:
        build_dispatch_plan(
            epic_issue_number=3229,
            run_id="run-missing-helper-rationale",
            candidates=[missing_rationale],
        )
    except EpicDispatchError as exc:
        assert "requires an explicit issue_local_helper_rationale" in str(exc)
    else:
        raise AssertionError("helper allocation without rationale was accepted")


def test_helper_budget_reserves_a_non_root_agent_slot() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-helper-slot-reserve",
        max_parallel=2,
        candidates=[
            _candidate(
                3061,
                risk="high",
                issue_local_helper_budget=1,
                issue_local_helper_rationale="bounded independent log analysis",
            ),
            _candidate(3062, risk="high"),
        ],
    )

    decisions = {item["issue_number"]: item for item in plan["decisions"]}
    assert decisions[3061]["selected_for_dispatch"] is True
    assert decisions[3062]["skip_reason"] == "parallel-helper-capacity-reserve"
    assert plan["selected_count"] == 1
    assert plan["selected_helper_slots"] == 1


def test_run_state_accepts_dispatch_decision_summaries(tmp_path: Path) -> None:
    state = create_epic_run_state(3229, "run-state-dispatch", root=tmp_path)
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-state-dispatch",
        candidates=[_candidate(4001, risk="high")],
    )

    updated = apply_epic_run_update(state, **plan["epic_run_state_update"])

    assert updated["dispatch_decisions"] == [
        {
            "id": "dispatch-4001",
            "issue_number": 4001,
            "selected_path": "subagent",
            "selected_for_dispatch": True,
                "runtime_model_hint": {
                    "runtime": "codex",
                    "model_class": "high-reasoning",
                    "capability": "sol",
                    "runtime_difference": "invocation-hint-only",
                },
            "budget_class": "high",
            "stop_condition": updated["dispatch_decisions"][0]["stop_condition"],
            "skip_reason": None,
            "context_pack_id": "ctx-4001",
        }
    ]


def test_dispatch_context_pack_excludes_reusable_constraints_from_run_state() -> None:
    run_state = {
        "schema_version": 1,
        "epic_issue_number": 3229,
        "run_id": "run-learned-constraints",
        "child_queue": [],
        "learning_evaluation_candidates": [],
        "issue_mappings": {},
        "validation_status": {},
        "review_findings": [],
        "reusable_constraints": [
            {
                "id": "artifact-only-pagination",
                "text": "artifact-only workflow reads must paginate generated artifacts before repair.",
            }
        ],
        "follow_ups": [],
        "stop_conditions": [],
        "dispatch_decisions": [],
        "dispatcher_status": {},
        "compact_receipts": [],
        "last_verified_head_sha": None,
    }

    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-learned-constraints",
        candidates=[_candidate(4051, risk="high")],
        run_state=run_state,
    )

    constraints = plan["context_packs"][0]["known_constraints"]
    assert constraints == ["worker self-claims through issue-to-code"]


def test_existing_run_state_epic_mismatch_rejects_dispatch_plan(tmp_path: Path) -> None:
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        json.dumps({"candidates": [_candidate(4101, risk="high")]}),
        encoding="utf-8",
    )
    create_epic_run_state(111, "same-run", root=tmp_path)

    result = _run_builderops(
        [
            "epic-run-state",
            "dispatch-plan",
            "--epic-issue-number",
            "222",
            "--run-id",
            "same-run",
            "--root",
            str(tmp_path),
            "--candidates-file",
            str(candidates_file),
            "--json",
        ]
    )

    assert result.exit_code != 0
    assert "already belongs to epic 111" in result.output


def test_cli_dispatch_plan_is_dry_run_and_does_not_write_state(tmp_path: Path) -> None:
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(
        json.dumps({"candidates": [_candidate(5001, risk="high")]}),
        encoding="utf-8",
    )

    result = _run_builderops(
        [
            "epic-run-state",
            "dispatch-plan",
            "--epic-issue-number",
            "3229",
            "--run-id",
            "run-cli-dispatch",
            "--root",
            str(tmp_path),
            "--candidates-file",
            str(candidates_file),
            "--runtime",
            "codex",
            "--json",
        ]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["selected_count"] == 1
    assert payload["context_packs"][0]["issue_contract"]["number"] == 5001
    assert payload["epic_run_state_update"]["dispatch_decisions"][0]["id"] == "dispatch-5001"
    assert not epic_run_state_path("run-cli-dispatch", root=tmp_path).exists()


def test_explicit_independent_issue_set_needs_no_synthetic_epic() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5101, 5102],
        run_id="independent-fast-lane",
        candidates=[
            _candidate(5101, risk="high", files=["app/a.py"]),
            _candidate(5102, risk="high", files=["app/b.py"]),
        ],
    )

    assert "epic_issue_number" not in plan
    assert plan["scope"] == {
        "kind": "independent_issue_set",
        "issue_numbers": [5101, 5102],
        "parent_closure": "prohibited-without-real-governed-parent",
    }
    assert plan["selected_count"] == 2


def test_fast_lane_rejects_non_independent_or_over_budget_sets() -> None:
    base = [_candidate(5201, risk="high", files=["app/a.py"])]
    for candidate_overrides, expected in (
        ([ _candidate(5201, risk="high", dependencies=[1])], "dependencies"),
        ([ _candidate(5201, risk="high", files=["app/a.py"]), _candidate(5202, risk="high", files=["app/a.py"])], "shared mutation"),
        ([dict(_candidate(5201, risk="high"), has_migration=True)], "migration"),
        ([dict(_candidate(5201, risk="high"), authority_ambiguous=True)], "authority ambiguity"),
    ):
        try:
            build_dispatch_plan(
                independent_issue_numbers=[item["issue_number"] for item in candidate_overrides],
                run_id="independent-reject",
                candidates=candidate_overrides,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:  # pragma: no cover - assertion keeps each admission rule fail-closed.
            raise AssertionError(f"expected {expected} rejection")

    try:
        build_dispatch_plan(
            independent_issue_numbers=[5201],
            run_id="independent-cap",
            max_parallel=3,
            candidates=base,
        )
    except ValueError as exc:
        assert "must not exceed 2" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected pilot cap rejection")

    missing_fact = _candidate(5203, risk="high")
    missing_fact.pop("strict_ready")
    missing_surfaces = _candidate(5207, risk="high")
    missing_surfaces.pop("likely_touched_files")
    duplicate = [_candidate(5204, risk="high"), _candidate(5204, risk="high")]
    contract_overlap = [
        dict(_candidate(5205, risk="high"), contract_surfaces=["contract/a"]),
        dict(_candidate(5206, risk="high"), contract_surfaces=["contract/a"]),
    ]
    for candidates, scope, expected in (
        ([missing_fact], [5203], "strictly ready"),
        ([missing_surfaces], [5207], "mutation surface evidence"),
        (duplicate, [5204], "match candidates exactly"),
        (contract_overlap, [5205, 5206], "contract overlap"),
    ):
        try:
            build_dispatch_plan(
                independent_issue_numbers=scope,
                run_id="independent-fail-closed",
                candidates=candidates,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:  # pragma: no cover
            raise AssertionError(f"expected {expected} rejection")

    admission_source = inspect.getsource(
        epic_dispatch_module._validate_independent_fast_lane_admission
    )
    assert "len(by_number) != len(candidates)" in admission_source
    assert "defense-in-depth" in admission_source.lower()


def test_fast_lane_context_pack_is_minimal_and_receipted() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5301],
        run_id="independent-pack",
        candidates=[_candidate(5301, risk="high", files=["app/a.py"])],
    )
    pack = plan["context_packs"][0]

    assert pack["issue_contract"]["number"] == 5301
    assert pack["branch_worktree_plan"]["worker_self_claim"] is True
    assert pack["validation_ledger"]
    assert pack["known_constraints"]
    assert pack["return_schema"]["schema_name"] == "subagent_handoff_receipt"
    assert pack["coordination"] == {
        "routine_worker_to_worker": "prohibited",
        "discovered_overlap": "reject-whole-explicit-set-before-dispatch",
        "coordinator_scope": "cross_issue_only",
        "worker_scope": "one_issue_end_to_end",
        "issue_local_helper_budget": 0,
        "issue_local_helper_rationale": None,
        "sole_writer": "issue_agent",
    }
    assert {"child_queue", "dispatch_decisions", "compact_receipts"}.isdisjoint(pack)


def test_dispatch_sessions_stops_at_the_first_nonterminal_worker_handoff() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5401, 5402],
        run_id="serial-sessions",
        candidates=[
            _candidate(5401, risk="high", files=["app/a.py"]),
            _candidate(5402, risk="high", files=["app/b.py"]),
        ],
    )
    launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5401",
                "worker_receipt": _worker_receipt(5401),
            },
            {
                "session_id": "session-5402",
                "worker_receipt": _worker_receipt(5402),
            },
        ]
    )

    receipt = dispatch_issue_sessions(plan, launcher)

    assert [call["issue_contract"]["number"] for call in launcher.calls] == [5401]
    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "worker-handoff"
    assert receipt["execution_mode"] == "serial-fresh-sessions"
    assert [item["session_id"] for item in receipt["sessions"]] == ["session-5401"]
    assert all(item["fresh_session"] is True for item in receipt["sessions"])
    assert all(item["status"] == "handoff" for item in receipt["sessions"])
    assert receipt["github_mutations"] == []
    assert receipt["coordinator_claims"] == []


def test_dispatch_sessions_rejects_invalid_plan_before_launch() -> None:
    valid = build_dispatch_plan(
        independent_issue_numbers=[5501],
        run_id="invalid-plan",
        candidates=[_candidate(5501, risk="high", files=["app/a.py"])],
    )
    invalid_plans = []

    old_schema = json.loads(json.dumps(valid))
    old_schema["schema_version"] = 1
    invalid_plans.append(old_schema)

    missing = json.loads(json.dumps(valid))
    missing["context_packs"] = []
    invalid_plans.append(missing)

    duplicate = json.loads(json.dumps(valid))
    duplicate["context_packs"].append(dict(duplicate["context_packs"][0]))
    invalid_plans.append(duplicate)

    mismatched = json.loads(json.dumps(valid))
    mismatched["context_packs"][0]["issue_contract"]["number"] = 9999
    invalid_plans.append(mismatched)

    unsupported_runtime = json.loads(json.dumps(valid))
    unsupported_runtime["context_packs"][0]["runtime"]["runtime"] = "claude"
    invalid_plans.append(unsupported_runtime)

    routed_candidate = _candidate(
        5502,
        risk="low",
        files=["app/a.py"],
        preferred_path="subagent",
    )
    routed_candidate["execution_routing"] = {
        "mode": "shadow",
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
    }
    tampered_context = build_dispatch_plan(
        independent_issue_numbers=[5502],
        run_id="tampered-routing-context",
        candidates=[routed_candidate],
    )
    preserved_plan_hash = frozen_dispatch_plan_hash(tampered_context)
    valid_routed_launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5502",
                "worker_receipt": _worker_receipt(5502),
            }
        ]
    )
    with pytest.raises(EpicDispatchError, match="independently preserved plan hash"):
        dispatch_issue_sessions(
            tampered_context,
            _RecordingSessionLauncher([]),
        )

    stripped_routing = json.loads(json.dumps(tampered_context))
    del stripped_routing["decisions"][0]["execution_routing"]
    with pytest.raises(EpicDispatchError, match="independently preserved plan hash"):
        dispatch_issue_sessions(
            stripped_routing,
            _RecordingSessionLauncher([]),
        )
    with pytest.raises(EpicDispatchError, match="exactly mirror"):
        dispatch_issue_sessions(
            stripped_routing,
            _RecordingSessionLauncher([]),
            expected_plan_hash=frozen_dispatch_plan_hash(stripped_routing),
        )

    valid_routed_receipt = dispatch_issue_sessions(
        tampered_context,
        valid_routed_launcher,
        expected_plan_hash=preserved_plan_hash,
    )
    assert valid_routed_receipt["sessions"][0]["status"] == "handoff"

    rewritten_frozen_plan = json.loads(json.dumps(tampered_context))
    rewritten_frozen_plan["context_packs"][0]["issue_contract"]["title"] = (
        "coherently rewritten authority"
    )
    with pytest.raises(EpicDispatchError, match="independently preserved hash"):
        dispatch_issue_sessions(
            rewritten_frozen_plan,
            _RecordingSessionLauncher([]),
            expected_plan_hash=preserved_plan_hash,
        )

    wrong_routing_issue = json.loads(json.dumps(tampered_context))
    wrong_routing_issue["decisions"][0]["execution_routing"]["route_request"][
        "issue_number"
    ] = 9999
    invalid_plans.append(wrong_routing_issue)

    forged_target = json.loads(json.dumps(tampered_context))
    forged_target["decisions"][0]["execution_routing"]["proposed_target"][
        "model"
    ] = "evil-model"
    invalid_plans.append(forged_target)

    forged_comparison = json.loads(json.dumps(tampered_context))
    forged_comparison["decisions"][0]["execution_routing"]["shadow_comparison"][
        "proposed_capability"
    ] = "sol"
    invalid_plans.append(forged_comparison)

    forged_incumbent = json.loads(json.dumps(tampered_context))
    forged_incumbent["decisions"][0]["execution_routing"]["route_request"][
        "shadow_against_capability"
    ] = "sol"
    invalid_plans.append(forged_incumbent)

    tampered_context["context_packs"][0]["known_constraints"].append(
        "post-plan mutation"
    )
    invalid_plans.append(tampered_context)

    for plan in invalid_plans:
        launcher = _RecordingSessionLauncher([])
        contains_routing = any(
            "execution_routing" in decision
            for decision in plan.get("decisions", [])
        )
        try:
            dispatch_issue_sessions(
                plan,
                launcher,
                expected_plan_hash=(
                    frozen_dispatch_plan_hash(plan) if contains_routing else None
                ),
            )
        except EpicDispatchError:
            pass
        else:  # pragma: no cover - assertion keeps validation fail closed.
            raise AssertionError("invalid dispatch plan should be rejected")
        assert launcher.calls == []


def test_dispatch_sessions_does_not_launch_a_second_issue_after_handoff() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5601, 5602],
        run_id="session-reuse",
        candidates=[
            _candidate(5601, risk="high", files=["app/a.py"]),
            _candidate(5602, risk="high", files=["app/b.py"]),
        ],
    )
    launcher = _RecordingSessionLauncher(
        [
            {"session_id": "same-session", "worker_receipt": _worker_receipt(5601)},
            {"session_id": "same-session", "worker_receipt": _worker_receipt(5602)},
        ]
    )

    receipt = dispatch_issue_sessions(plan, launcher)

    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "worker-handoff"
    assert len(launcher.calls) == 1
    assert receipt["sessions"][0]["status"] == "handoff"


def test_dispatch_sessions_stops_after_first_failed_session() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5701, 5702],
        run_id="failed-session",
        candidates=[
            _candidate(5701, risk="high", files=["app/a.py"]),
            _candidate(5702, risk="high", files=["app/b.py"]),
        ],
    )
    launcher = _RecordingSessionLauncher(
        [
            IssueSessionLaunchError(
                "codex exec failed",
                session_id="session-5701",
            ),
            {"session_id": "session-5702", "worker_receipt": _worker_receipt(5702)},
        ]
    )

    receipt = dispatch_issue_sessions(plan, launcher)

    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "session-launch-failed"
    assert len(launcher.calls) == 1
    assert receipt["sessions"] == [
        {
            "issue_number": 5701,
            "context_pack_id": "ctx-5701",
            "session_id": "session-5701",
            "fresh_session": True,
            "status": "failed",
            "error_type": "IssueSessionLaunchError",
            "error": "codex exec failed",
        }
    ]

    blocked_launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5701-blocked",
                "worker_receipt": _worker_receipt(5701, final_state="blocked"),
            },
            {"session_id": "session-5702", "worker_receipt": _worker_receipt(5702)},
        ]
    )

    blocked_receipt = dispatch_issue_sessions(plan, blocked_launcher)

    assert blocked_receipt["status"] == "stopped"
    assert blocked_receipt["stopped_reason"] == "worker-blocked"
    assert len(blocked_launcher.calls) == 1
    assert blocked_receipt["sessions"][0]["status"] == "blocked"

    handoff_launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5701-handoff",
                "worker_receipt": _worker_receipt(5701, final_state="handoff"),
            },
            {"session_id": "session-5702", "worker_receipt": _worker_receipt(5702)},
        ]
    )

    handoff_receipt = dispatch_issue_sessions(plan, handoff_launcher)

    assert handoff_receipt["status"] == "stopped"
    assert handoff_receipt["stopped_reason"] == "worker-handoff"
    assert len(handoff_launcher.calls) == 1
    assert handoff_receipt["sessions"][0]["status"] == "handoff"


def test_dispatch_sessions_rejects_malformed_context_cost() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5751],
        run_id="invalid-context-cost",
        candidates=[_candidate(5751, risk="high", files=["app/a.py"])],
    )
    malformed = _worker_receipt(5751)
    malformed["context_cost"] = None
    launcher = _RecordingSessionLauncher(
        [{"session_id": "session-5751", "worker_receipt": malformed}]
    )

    receipt = dispatch_issue_sessions(plan, launcher)

    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "session-launch-failed"
    assert "context_cost must be an object" in receipt["sessions"][0]["error"]


def test_dispatch_sessions_rejects_self_attested_terminal_done() -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5761],
        run_id="unverified-terminal-done",
        candidates=[_candidate(5761, risk="high", files=["app/a.py"])],
    )
    launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5761",
                "worker_receipt": _worker_receipt(5761, final_state="done"),
            }
        ]
    )

    receipt = dispatch_issue_sessions(plan, launcher)

    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "session-launch-failed"
    assert "invalid final_state" in receipt["sessions"][0]["error"]


def test_codex_issue_session_command_is_fresh_and_tcd_bounded(tmp_path: Path) -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5801],
        run_id="codex-command",
        candidates=[
            _candidate(
                5801,
                risk="high",
                files=["app/a.py"],
                worktree=str(tmp_path / "issue-5801"),
            )
        ],
    )
    launcher = CodexIssueSessionLauncher(repo_root=tmp_path)

    command = launcher.command(plan["context_packs"][0])

    assert command[:3] == ["codex", "exec", "--json"]
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="high"' in command
    assert "resume" not in command
    assert command[command.index("--add-dir") + 1] == str(tmp_path)
    assert command[-1] == "-"
    prompt = launcher.prompt(plan["context_packs"][0])
    assert "slice_implementer" in prompt
    assert ".codex/skills/issue-to-code/SKILL.md" in prompt
    assert '"number": 5801' in prompt


def test_bounded_fast_shadow_preflight_uses_configured_route_and_preserves_launch_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambient = tmp_path / "ambient-providers.yaml"
    ambient.write_text("not: the declared census\n", encoding="utf-8")
    monkeypatch.setenv("PROVIDER_CENSUS_PATH", str(ambient))
    candidate = _candidate(
        5811,
        risk="low",
        files=["app/a.py"],
        worktree=str(tmp_path / "issue-5811"),
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "shadow",
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-5811",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:05:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5811],
        run_id="bounded-fast-shadow",
        candidates=[candidate],
    )

    decision = plan["decisions"][0]
    routing = decision["execution_routing"]
    assert routing["mode"] == "shadow"
    assert routing["route_decision"]["selected_capability"] == "spark"
    assert routing["proposed_target"] == {
        "capability": "spark",
        "provider": "openai",
        "model": "gpt-5.3-codex-spark",
        "reasoning_effort": "low",
        "configuration_ref": "docs/settings/models/providers.yaml#builder_execution.dev.spark",
    }
    assert routing["shadow_comparison"]["incumbent_capability"] == "luna"
    assert routing["shadow_comparison"]["proposed_capability"] == "spark"
    assert routing["attempt_observation"]["mode"] == "shadow"
    assert routing["attempt_observation"]["outcome"] == "not_invoked"
    assert routing["attempt_observation"]["requested_capability"] == "spark"
    assert routing["attempt_observation"]["actual_capability"] == "spark"

    # Phase 1 is shadow-first: routing evidence stays outside the immutable
    # worker packet and the incumbent launch policy still wins.
    pack = plan["context_packs"][0]
    assert "execution_routing" not in pack
    assert pack["runtime"]["capability"] == "luna"
    launcher = CodexIssueSessionLauncher(repo_root=tmp_path)
    command = launcher.command(pack)
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert "_TCD_CODEX_ROUTE" not in inspect.getsource(epic_dispatch_module)


def test_phase2_canary_preserves_contract_hashes_and_route_lineage() -> None:
    candidate = _candidate(
        5322,
        risk="low",
        files=["app/builderops/execution_routing.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
    }

    plan = build_dispatch_plan(
        independent_issue_numbers=[5322],
        run_id="phase2-canary-hash-preservation",
        candidates=[candidate],
    )

    routing = plan["decisions"][0]["execution_routing"]
    request = routing["route_request"]
    decision = routing["route_decision"]
    attempt = routing["attempt_observation"]
    pack = plan["context_packs"][0]
    assert routing["mode"] == "canary"
    assert routing["canary_admission"] == {
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
    }
    assert routing["authority"] == "evidence-only-no-launch-or-lifecycle-effect"
    assert request["context_pack_hash"] == canonical_hash(pack)
    assert request["authority_hash"] == canonical_hash(pack["issue_contract"])
    assert request["verification_profile_hash"] == canonical_hash(pack["validation_ledger"])
    assert decision["route_lineage_id"] == f"execution-route:{canonical_hash(request)}"
    assert attempt["route_lineage_id"] == decision["route_lineage_id"]
    assert attempt["context_pack_hash"] == request["context_pack_hash"]

    valid_launcher = _RecordingSessionLauncher(
        [{"session_id": "session-5322", "worker_receipt": _worker_receipt(5322)}]
    )
    valid = dispatch_issue_sessions(
        plan, valid_launcher, expected_plan_hash=frozen_dispatch_plan_hash(plan)
    )
    assert valid["stopped_reason"] == "worker-handoff"
    assert valid_launcher.calls[0]["_execution_routing"]["proposed_target"][
        "capability"
    ] == "luna"

    tampered = json.loads(json.dumps(plan))
    tampered["decisions"][0]["execution_routing"]["canary_admission"][
        "sample_limit"
    ] = 2
    rejected_launcher = _RecordingSessionLauncher([])
    with pytest.raises(EpicDispatchError, match="frozen decisions|canary routing requires"):
        dispatch_issue_sessions(
            tampered,
            rejected_launcher,
            expected_plan_hash=frozen_dispatch_plan_hash(tampered),
        )
    assert rejected_launcher.calls == []


def test_phase2_canary_production_path_records_spark_and_launches_one_luna_fallback() -> None:
    candidate = _candidate(
        5323,
        risk="low",
        files=["app/builderops/epic_dispatch.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-production",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:05:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5323],
        run_id="phase2-canary-production-fallback",
        candidates=[candidate],
    )
    launcher = _RecordingSessionLauncher(
        [
            {"allocation_state": "allocation_unavailable"},
            {"session_id": "session-5323", "worker_receipt": _worker_receipt(5323)},
        ]
    )

    receipt = dispatch_issue_sessions(
        plan,
        launcher,
        expected_plan_hash=frozen_dispatch_plan_hash(plan),
        canary_observed_at="2026-08-29T15:00:01Z",
    )

    assert receipt["stopped_reason"] == "worker-handoff"
    assert len(launcher.calls) == 2
    assert launcher.calls[0]["_execution_routing"]["proposed_target"]["capability"] == "spark"
    assert launcher.calls[1]["_execution_routing"]["proposed_target"]["capability"] == "luna"
    canary_receipt = receipt["sessions"][0]["execution_routing_canary_receipt"]
    assert canary_receipt["attempt_count"] == 2
    assert canary_receipt["attempts"][0]["outcome"] == "allocation_unavailable"
    assert canary_receipt["attempts"][1]["transition_kind"] == "capacity_fallback"
    assert canary_receipt["attempts"][1]["actual_capability"] == "luna"


def test_phase2_canary_fallback_launcher_failure_records_redacted_receipt() -> None:
    candidate = _candidate(
        5327,
        risk="low",
        files=["app/builderops/epic_dispatch.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-fallback-launch-failure",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:05:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5327],
        run_id="phase2-canary-fallback-launch-failure",
        candidates=[candidate],
    )
    launcher = _RecordingSessionLauncher(
        [
            {"allocation_state": "allocation_unavailable"},
            RuntimeError("provider payload contained a secret and must not enter the receipt"),
        ]
    )

    receipt = dispatch_issue_sessions(
        plan,
        launcher,
        expected_plan_hash=frozen_dispatch_plan_hash(plan),
        canary_observed_at="2026-08-29T15:00:01Z",
    )

    assert receipt["stopped_reason"] == "session-launch-failed"
    assert len(launcher.calls) == 2
    canary_receipt = receipt["sessions"][0]["execution_routing_canary_receipt"]
    assert canary_receipt["schema_version"] == "builder_execution_routing_canary.v1"
    assert canary_receipt["attempt_count"] == 2
    assert canary_receipt["attempts"][0]["outcome"] == "allocation_unavailable"
    assert canary_receipt["attempts"][1]["outcome"] == "failed"
    assert canary_receipt["attempts"][1]["transition_kind"] == "capacity_fallback"
    assert canary_receipt["accepted_delivery_verification"] == "not_run"
    assert canary_receipt["lifecycle_authority"] == "none"
    assert "provider payload" not in json.dumps(canary_receipt, sort_keys=True)


def test_phase2_canary_plan_bound_is_plan_wide_without_rejecting_independent_work_units() -> None:
    def canary_candidate(issue_number: int, file_name: str) -> dict[str, object]:
        candidate = _candidate(
            issue_number,
            risk="low",
            files=[file_name],
            preferred_path="subagent",
        )
        candidate["execution_routing"] = {
            "mode": "canary",
            "opt_in": True,
            "sample_index": 1,
            "sample_limit": 1,
            "work_class": "bounded_fast",
            "ambiguity": "low",
            "protected_surface": False,
            "decision_at": "2026-08-29T15:00:00Z",
        }
        return candidate

    with pytest.raises(EpicDispatchError, match="sample limit permits one candidate"):
        build_dispatch_plan(
            independent_issue_numbers=[5328, 5329],
            run_id="phase2-canary-plan-wide-bound",
            candidates=[
                canary_candidate(5328, "app/builderops/epic_dispatch.py"),
                canary_candidate(5329, "app/builderops/execution_routing.py"),
            ],
        )

    independent_plan = build_dispatch_plan(
        independent_issue_numbers=[5330, 5331],
        run_id="phase2-independent-work-units-remain-bounded",
        candidates=[
            _candidate(
                5330,
                risk="low",
                files=["app/builderops/epic_dispatch.py"],
                preferred_path="subagent",
            ),
            _candidate(
                5331,
                risk="low",
                files=["app/builderops/execution_routing.py"],
                preferred_path="subagent",
            ),
        ],
    )
    assert independent_plan["selected_count"] == 2
    assert [
        decision["issue_number"]
        for decision in independent_plan["decisions"]
        if decision["selected_for_dispatch"]
    ] == [5330, 5331]


def test_phase2_canary_codex_launcher_normalizes_versioned_usage_limit() -> None:
    candidate = _candidate(
        5326,
        risk="low",
        files=["app/builderops/epic_dispatch.py"],
        preferred_path="subagent",
        worktree="/tmp/issue-5326",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-codex-event",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:05:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5326],
        run_id="phase2-canary-codex-event",
        candidates=[candidate],
    )
    usage_limit = (
        "You've hit your usage limit for gpt-5.3-codex-spark. "
        "Switch to another model now, or try again later."
    )
    worker = _worker_receipt(5326)
    commands: list[list[str]] = []

    def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        model = command[command.index("--model") + 1]
        if model == "gpt-5.3-codex-spark":
            stdout = "\n".join(
                [
                    json.dumps({"type": "thread.started", "thread_id": "spark-5326"}),
                    json.dumps({"type": "error", "message": usage_limit}),
                    json.dumps({"type": "turn.failed", "error": {"message": "failed"}}),
                ]
            )
            return subprocess.CompletedProcess(args=command, returncode=1, stdout=stdout, stderr="")
        assert model == "gpt-5.6-luna"
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "luna-5326"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(worker)},
                    }
                ),
            ]
        )
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")

    launcher = CodexIssueSessionLauncher(repo_root=Path("/tmp"), runner=runner)
    receipt = dispatch_issue_sessions(
        plan,
        launcher,
        expected_plan_hash=frozen_dispatch_plan_hash(plan),
        canary_observed_at="2026-08-29T15:00:01Z",
    )

    assert [command[command.index("--model") + 1] for command in commands] == [
        "gpt-5.3-codex-spark",
        "gpt-5.6-luna",
    ]
    assert receipt["stopped_reason"] == "worker-handoff"
    canary_receipt = receipt["sessions"][0]["execution_routing_canary_receipt"]
    assert canary_receipt["attempts"][0]["outcome"] == "allocation_unavailable"
    assert canary_receipt["attempts"][1]["transition_kind"] == "capacity_fallback"


def test_phase2_canary_launch_time_staleness_records_fallback_without_spark_launch() -> None:
    candidate = _candidate(
        5324,
        risk="low",
        files=["app/builderops/epic_dispatch.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-stale-at-launch",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:01:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5324],
        run_id="phase2-canary-launch-time-stale",
        candidates=[candidate],
    )
    launcher = _RecordingSessionLauncher(
        [{"session_id": "session-5324", "worker_receipt": _worker_receipt(5324)}]
    )

    receipt = dispatch_issue_sessions(
        plan,
        launcher,
        expected_plan_hash=frozen_dispatch_plan_hash(plan),
        canary_observed_at="2026-08-29T15:01:01Z",
    )

    assert len(launcher.calls) == 1
    assert launcher.calls[0]["_execution_routing"]["proposed_target"]["capability"] == "luna"
    canary_receipt = receipt["sessions"][0]["execution_routing_canary_receipt"]
    assert canary_receipt["attempts"][0]["actual_capability"] == "spark"
    assert canary_receipt["attempts"][0]["outcome"] == "allocation_unavailable"
    assert canary_receipt["attempts"][1]["actual_capability"] == "luna"


def test_phase2_canary_fallback_allocation_failure_does_not_retry() -> None:
    candidate = _candidate(
        5325,
        risk="low",
        files=["app/builderops/epic_dispatch.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "canary",
        "opt_in": True,
        "sample_index": 1,
        "sample_limit": 1,
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "allocation_observation": {
            "observation_id": "spark-observation-no-retry",
            "capability": "spark",
            "state": "bonus_available",
            "observed_at": "2026-08-29T14:55:00Z",
            "valid_until": "2026-08-29T15:05:00Z",
            "source_kind": "operator",
            "source_ref": "operator-observation:codex-spark-bonus",
        },
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5325],
        run_id="phase2-canary-no-retry",
        candidates=[candidate],
    )
    launcher = _RecordingSessionLauncher(
        [
            {"allocation_state": "allocation_unavailable"},
            {"allocation_state": "allocation_unavailable"},
        ]
    )

    receipt = dispatch_issue_sessions(
        plan,
        launcher,
        expected_plan_hash=frozen_dispatch_plan_hash(plan),
        canary_observed_at="2026-08-29T15:00:01Z",
    )

    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "session-launch-failed"
    assert len(launcher.calls) == 2
    assert launcher.calls[0]["_execution_routing"]["proposed_target"]["capability"] == "spark"
    assert launcher.calls[1]["_execution_routing"]["proposed_target"]["capability"] == "luna"
    canary_receipt = receipt["sessions"][0]["execution_routing_canary_receipt"]
    assert canary_receipt["attempts"][1]["outcome"] == "allocation_unavailable"


def test_bounded_fast_shadow_preflight_cannot_override_candidate_risk() -> None:
    candidate = _candidate(
        5812,
        risk="high",
        files=["app/a.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "shadow",
        "work_class": "bounded_fast",
        "risk": "low",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
    }

    with pytest.raises(
        EpicDispatchError,
        match="risk must come from the canonical candidate",
    ):
        build_dispatch_plan(
            independent_issue_numbers=[5812],
            run_id="bounded-fast-risk-override",
            candidates=[candidate],
        )


def test_codex_issue_session_captures_exposed_token_usage_and_pack_bytes(
    tmp_path: Path,
) -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5851],
        run_id="codex-usage",
        candidates=[
            _candidate(
                5851,
                risk="high",
                files=["app/a.py"],
                worktree=str(tmp_path / "issue-5851"),
            )
        ],
    )
    worker = _worker_receipt(5851)
    stdout = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "session-5851"}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 4321}}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(worker)},
                }
            ),
        ]
    )

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    launcher = CodexIssueSessionLauncher(repo_root=tmp_path, runner=runner)
    context_pack = plan["context_packs"][0]

    result = launcher.launch(context_pack)

    cost = result["worker_receipt"]["context_cost"]
    assert cost["measurement"] == "actual"
    assert cost["input_tokens"] == 4321
    assert cost["context_pack_bytes"] == context_pack["context_cost_baseline"][
        "context_pack_bytes_excluding_baseline"
    ]


def test_dispatch_sessions_cli_emits_receipt_without_github_mutations(
    tmp_path: Path,
) -> None:
    plan = build_dispatch_plan(
        independent_issue_numbers=[5901],
        run_id="cli-sessions",
        candidates=[_candidate(5901, risk="high", files=["app/a.py"])],
    )
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5901",
                "worker_receipt": _worker_receipt(5901),
            }
        ]
    )

    with patch(
        "app.builderops.cli.CodexIssueSessionLauncher",
        return_value=launcher,
    ):
        result = _run_builderops(
            [
                "epic-run-state",
                "dispatch-sessions",
                "--plan-file",
                str(plan_file),
                "--repo-root",
                str(tmp_path),
                "--json",
            ]
        )

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["status"] == "stopped"
    assert receipt["stopped_reason"] == "worker-handoff"
    assert receipt["sessions"][0]["session_id"] == "session-5901"
    assert receipt["github_mutations"] == []
    assert receipt["coordinator_claims"] == []


def test_dispatch_sessions_cli_requires_external_hash_for_routed_plan(
    tmp_path: Path,
) -> None:
    candidate = _candidate(
        5902,
        risk="low",
        files=["app/a.py"],
        preferred_path="subagent",
    )
    candidate["execution_routing"] = {
        "mode": "shadow",
        "work_class": "bounded_fast",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
    }
    plan = build_dispatch_plan(
        independent_issue_numbers=[5902],
        run_id="cli-routed-sessions",
        candidates=[candidate],
    )
    plan_file = tmp_path / "routed-plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    launcher = _RecordingSessionLauncher(
        [
            {
                "session_id": "session-5902",
                "worker_receipt": _worker_receipt(5902),
            }
        ]
    )

    with patch(
        "app.builderops.cli.CodexIssueSessionLauncher",
        return_value=launcher,
    ):
        missing_hash = _run_builderops(
            [
                "epic-run-state",
                "dispatch-sessions",
                "--plan-file",
                str(plan_file),
                "--repo-root",
                str(tmp_path),
                "--json",
            ]
        )
        accepted = _run_builderops(
            [
                "epic-run-state",
                "dispatch-sessions",
                "--plan-file",
                str(plan_file),
                "--repo-root",
                str(tmp_path),
                "--expected-plan-hash",
                frozen_dispatch_plan_hash(plan),
                "--json",
            ]
        )

    assert missing_hash.exit_code != 0
    assert "independently preserved plan hash" in missing_hash.output
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["sessions"][0]["status"] == "handoff"
