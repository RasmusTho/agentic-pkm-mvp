from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from click.testing import CliRunner

from app.builderops import epic_dispatch as epic_dispatch_module
from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_dispatch import (
    CodexIssueSessionLauncher,
    EpicDispatchError,
    IssueSessionLaunchError,
    build_dispatch_plan,
    dispatch_issue_sessions,
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

    def launch(self, context_pack: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(dict(context_pack))
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


def test_codex_and_claude_use_same_minimal_context_pack_schema() -> None:
    plan = build_dispatch_plan(
        epic_issue_number=3229,
        run_id="run-runtime",
        runtime_targets=["codex", "claude"],
        candidates=[
            _candidate(3001, risk="high", runtime_hint="codex", files=["app/a.py"]),
            _candidate(3002, risk="high", runtime_hint="claude", files=["app/b.py"]),
        ],
    )

    packs = plan["context_packs"]
    assert [pack["runtime"]["runtime"] for pack in packs] == ["codex", "claude"]
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
            "--runtime",
            "claude",
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
        "discovered_overlap": "typed-coordinator-exception",
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

    for plan in invalid_plans:
        launcher = _RecordingSessionLauncher([])
        try:
            dispatch_issue_sessions(plan, launcher)
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
