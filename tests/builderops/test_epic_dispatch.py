from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_dispatch import build_dispatch_plan
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
    }
    if preferred_path is not None:
        payload["preferred_path"] = preferred_path
    if scriptable:
        payload["scriptable"] = True
    return payload


def _run_builderops(args: list[str]):
    return CliRunner().invoke(
        builderops_standalone_root,
        ["builderops", *args],
        catch_exceptions=False,
    )


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

    assert plan["selected_count"] == 3
    assert all(item["selected_for_dispatch"] for item in plan["decisions"])
    assert all(item["skip_reason"] is None for item in plan["decisions"])


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


def test_dispatch_context_pack_includes_reusable_constraints_from_run_state() -> None:
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
    assert constraints == [
        "worker self-claims through issue-to-code",
        {
            "id": "artifact-only-pagination",
            "text": "artifact-only workflow reads must paginate generated artifacts before repair.",
        },
    ]


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
    duplicate = [_candidate(5204, risk="high"), _candidate(5204, risk="high")]
    contract_overlap = [
        dict(_candidate(5205, risk="high"), contract_surfaces=["contract/a"]),
        dict(_candidate(5206, risk="high"), contract_surfaces=["contract/a"]),
    ]
    for candidates, scope, expected in (
        ([missing_fact], [5203], "strictly ready"),
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
    }
    assert "epic_history" not in json.dumps(pack)
