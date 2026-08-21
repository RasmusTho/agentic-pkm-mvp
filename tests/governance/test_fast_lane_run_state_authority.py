"""Regression coverage for fast-lane run-state evidence boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops.epic_dispatch import build_dispatch_plan
from app.builderops.epic_run_state import create_independent_issue_run_state


def _candidate(issue_number: int) -> dict[str, object]:
    return {
        "issue_number": issue_number,
        "title": "bounded fast-lane issue",
        "url": f"https://example.test/issues/{issue_number}",
        "state": "OPEN",
        "labels": ["agent:ready", "type:task"],
        "project_status": "Ready",
        "risk": "high",
        "expected_value": "high",
        "runtime_hint": "codex",
        "likely_touched_files": ["app/builderops/epic_dispatch.py"],
        "validation_resources": ["tests/governance/test_fast_lane_run_state_authority.py"],
        "owner_docs": ["docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"],
        "owner_doc_writeback_required": False,
        "dependencies": [],
        "dependencies_satisfied": True,
        "dependencies_known": True,
        "strict_ready": True,
        "authority_ambiguous": False,
        "has_migration": False,
        "contract_surfaces": [],
        "source_anchors": ["run-state authority"],
        "known_constraints": ["worker self-claims through issue-to-code"],
        "validation": ["pytest -q tests/governance/test_fast_lane_run_state_authority.py"],
        "issue_local_helper_budget": 0,
        "issue_local_helper_rationale": None,
    }


def _run_builderops(args: list[str]):
    return CliRunner().invoke(builderops_root, ["builderops", *args], catch_exceptions=False)


class _RecordingLauncher:
    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def launch(self, context_pack: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(dict(context_pack))
        return self.response


def _handoff_receipt(issue_number: int, *, final_state: str = "handoff") -> dict[str, object]:
    return {
        "role": "slice_implementer",
        "task": f"#{issue_number}",
        "skill_loaded": ".codex/skills/issue-to-code/SKILL.md",
        "branch": f"codex/issue-{issue_number}",
        "worktree": f"/tmp/issue-{issue_number}",
        "actions": ["implemented"],
        "ac_verdicts": ["pass"],
        "lifecycle_mutations": ["claimed authority over closure"],
        "validation": ["pass"],
        "owner_doc_result": "none",
        "residual_risk": "requires governed verification",
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


def test_persisted_run_state_is_not_authority(tmp_path: Path) -> None:
    """The real CLI path carries local evidence but leaves live actions to the worker."""

    run_id = "persisted-evidence"
    state = create_independent_issue_run_state(
        [5024],
        run_id,
        root=tmp_path,
        compact_receipts=[{"claimed_closure": True, "github_mutations": ["close #5024"]}],
        last_verified_head_sha="f" * 40,
    )
    candidates_file = tmp_path / "candidates.json"
    candidates_file.write_text(json.dumps({"candidates": [_candidate(5024)]}), encoding="utf-8")

    result = _run_builderops(
        [
            "epic-run-state",
            "dispatch-plan",
            "--independent-issue",
            "5024",
            "--run-id",
            run_id,
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
    plan = json.loads(result.output)
    assert state["compact_receipts"]
    assert plan["run_state_seen"] is True
    assert plan["github_mutations"] == []
    assert plan["agent_spawns"] == []
    assert plan["context_packs"][0]["branch_worktree_plan"]["worker_self_claim"] is True

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    launcher = _RecordingLauncher(
        {"session_id": "session-5024", "worker_receipt": _handoff_receipt(5024)}
    )
    with patch("app.builderops.cli.CodexIssueSessionLauncher", return_value=launcher):
        sessions = _run_builderops(
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

    assert sessions.exit_code == 0, sessions.output
    receipt = json.loads(sessions.output)
    assert len(launcher.calls) == 1
    assert receipt["stopped_reason"] == "worker-handoff"
    assert receipt["github_mutations"] == []
    assert receipt["coordinator_claims"] == []


def test_run_state_cannot_bypass_live_authority(tmp_path: Path) -> None:
    """A local state/worker claim cannot self-attest terminal delivery or closure."""

    state = create_independent_issue_run_state(
        [5024],
        "spoofed-authority",
        root=tmp_path,
    )
    plan = build_dispatch_plan(
        independent_issue_numbers=[5024],
        run_id="spoofed-authority",
        candidates=[_candidate(5024)],
        runtime_targets=["codex"],
        run_state=state,
    )
    plan["context_packs"][0]["run_state"] = {
        "closure": "approved",
        "github_mutations": ["close #5024"],
    }
    launcher = _RecordingLauncher(
        {
            "session_id": "session-spoofed",
            "worker_receipt": _handoff_receipt(5024, final_state="done"),
        }
    )

    from app.builderops.epic_dispatch import dispatch_issue_sessions

    receipt = dispatch_issue_sessions(plan, launcher)

    assert receipt["stopped_reason"] == "session-launch-failed"
    assert receipt["sessions"][0]["status"] == "failed"
    assert "invalid final_state" in receipt["sessions"][0]["error"]
    assert receipt["github_mutations"] == []
    assert receipt["coordinator_claims"] == []
