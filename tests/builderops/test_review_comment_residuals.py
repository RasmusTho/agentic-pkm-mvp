"""Regression coverage for the bounded #3309 review-comment residuals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_root
from app.builderops.completeness_report import _terminal_outcomes_from_receipt
from app.builderops.evidence_bridge import EvidenceBridgeError, build_evidence_bridge_report
from app.builderops.pattern_routing import build_pattern_routing_report
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.leases import claim, reclaim_expired_leases
from app.dispatcher.models import TaskRecord
from app.dispatcher.services import move_task
from app.dispatcher.store import SqliteStore
from scripts.select_pr_tests import select_tests


def _source_ref(ref: str = "#3309") -> dict[str, str]:
    return {"ref_type": "github_issue", "ref": ref}


def _dispatcher_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "dispatcher.sqlite3", JsonlEventWriter(tmp_path / "events.jsonl"))
    store.initialize()
    store.upsert_task(
        TaskRecord(
            task_id="review-residual",
            issue_number=5099,
            title="Review residual",
            status="ready",
            priority="high",
            source_anchor_refs=["#3309"],
            created_at="2026-08-25T00:00:00+00:00",
            updated_at="2026-08-25T00:00:00+00:00",
        )
    )
    return store


def test_pattern_routing_and_dispatcher_review_handoff_residuals(tmp_path: Path) -> None:
    report = build_pattern_routing_report(
        {
            "patterns": [
                {
                    "id": "pattern-5099",
                    "route": "issue_candidate",
                    "summary": "A bounded repeated review finding.",
                    "repeat_count": 2,
                    "source_refs": [_source_ref()],
                    "target_ref": "#5099",
                    "terminal_outcome": "issue_created",
                    "recommendation": "Create the bounded follow-up issue.",
                }
            ]
        }
    )
    outcomes = _terminal_outcomes_from_receipt(
        {
            "target_refs": [{"ref_type": "builderops_object", "ref": "pattern-5099"}],
            "receipt_body": report["receipt_body"],
        }
    )
    assert outcomes == {"pattern-5099": "issue_created"}

    store = _dispatcher_store(tmp_path)
    _, lease = claim(store, "review-residual", "agent-5099", ttl_minutes=1)
    with pytest.raises(ValueError, match="held by agent-5099"):
        move_task(store, "review-residual", "review", "other-agent")
    moved = move_task(store, "review-residual", "review", "agent-5099")

    assert moved.status == "review"
    assert moved.lease_id is None
    assert moved.claimed_by is None
    assert moved.lease_expires_at is None
    assert store.get_lease(lease.lease_id).released_at is not None  # type: ignore[union-attr]
    assert reclaim_expired_leases(store, actor="dispatcher") == []


def test_evidence_index_and_run_state_residuals(tmp_path: Path) -> None:
    duplicate_across_buckets = {
        "observed": [
            {
                "id": "same-evidence",
                "kind": "review_finding",
                "summary": "Observed finding.",
                "source_refs": [_source_ref()],
            }
        ],
        "unknown": [
            {
                "id": "same-evidence",
                "kind": "unknown_for_retro",
                "summary": "Ambiguous duplicate.",
            }
        ],
        "candidate": [],
    }
    with pytest.raises(EvidenceBridgeError, match="duplicate evidence id"):
        build_evidence_bridge_report(duplicate_across_buckets)

    unknown_actionable = {
        "observed": [],
        "unknown": [
            {
                "id": "unknown-5099",
                "kind": "unknown_for_retro",
                "summary": "Artifact still unknown.",
            }
        ],
        "candidate": [
            {
                "id": "candidate-5099",
                "route": "issue_candidate",
                "summary": "This would otherwise be actionable without an owner.",
                "evidence_ids": ["unknown-5099"],
                "source_refs": [_source_ref()],
                "unknown_for_retro": True,
                "recommendation": "Do not create an unanchored issue.",
            }
        ],
    }
    with pytest.raises(EvidenceBridgeError, match="upstream_artifact"):
        build_evidence_bridge_report(unknown_actionable)

    selection = select_tests(["app/index/rules.py"])
    assert "memory_retrieval" in selection.subsystems
    assert "tests/index" in selection.targets

    update_file = tmp_path / "bulk-update.json"
    update_file.write_text(
        json.dumps({"issue_mappings": {"5099": {"branch": "codex/issue-5099"}}}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        builderops_root,
        [
            "builderops",
            "epic-run-state",
            "record",
            "--epic-issue-number",
            "3309",
            "--run-id",
            "review-residuals",
            "--root",
            str(tmp_path),
            "--update-file",
            str(update_file),
            "--update-json",
            json.dumps({"issue_mappings": {"5099": {"pr_number": 5100}}}),
            "--json",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    state = json.loads(result.output)["state"]
    assert state["issue_mappings"]["5099"] == {
        "branch": "codex/issue-5099",
        "pr_number": 5100,
    }
