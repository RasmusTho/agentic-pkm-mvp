"""Tests for the cockpit registry read-time join (#4438)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.builderops.cockpit_registry import BANDS, RUNG_ORDER, build_registry
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_store(tmp_path: Path) -> tuple[SqliteStore, Path]:
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    return store, db_path


def _task(
    *,
    status: str,
    issue_number: int = 100,
    title: str = "a task",
    repo: str = "RasmusTho/agentic-pkm-mvp",
    linked_pr: str | None = None,
    blocked_reason: str | None = None,
    sync_state: dict | None = None,
) -> TaskRecord:
    now = _now()
    return TaskRecord(
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        issue_number=issue_number,
        title=title,
        status=status,
        priority="med",
        repo=repo,
        source_anchor_refs=[],
        linked_pr=linked_pr,
        blocked_reason=blocked_reason,
        sync_state=sync_state,
        created_at=now,
        updated_at=now,
    )


def _registry(db_path: Path, tmp_path: Path) -> dict:
    return build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")


def _band(payload: dict, key: str) -> dict:
    return next(band for band in payload["bands"] if band["key"] == key)


def test_band_derivation_fail_closed(tmp_path: Path) -> None:
    store, db_path = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=1, title="working"))
    store.upsert_task(_task(status="completed", issue_number=2, title="done"))
    store.upsert_task(
        _task(status="blocked", issue_number=3, title="flawed", blocked_reason="upstream")
    )
    store.upsert_task(_task(status="ready", issue_number=4, title="forgotten"))
    store.upsert_task(
        _task(
            status="blocked",
            issue_number=5,
            title="needs a human",
            sync_state={"labels": ["type:task", "agent:needs-human"]},
        )
    )
    store.upsert_task(_task(status="mystery_status", issue_number=6, title="odd one"))

    payload = _registry(db_path, tmp_path)

    assert [band["key"] for band in payload["bands"]] == [key for key, _ in BANDS]
    assert _band(payload, "working")["count"] == 1
    assert _band(payload, "done")["count"] == 1
    assert _band(payload, "flawed")["count"] == 1
    assert _band(payload, "forgotten")["count"] == 1
    # The needs-human label routes to the needs-you band even from a mapped status.
    assert _band(payload, "needs_you")["count"] == 1
    # The unknown status is listed, never guessed into a band.
    assert len(payload["unclassified"]) == 1
    assert payload["unclassified"][0]["status"] == "mystery_status"
    all_items = [item for band in payload["bands"] for item in band["items"]]
    assert all(item["status"] != "mystery_status" for item in all_items)
    # The flawed item carries the gate's own wording.
    flawed_item = _band(payload, "flawed")["items"][0]
    assert flawed_item["why_now"] == "blocked: upstream"


def test_refused_emptiness_on_dead_source(tmp_path: Path) -> None:
    missing_db = tmp_path / "nowhere" / "dispatcher.sqlite3"

    payload = build_registry(
        db_path=missing_db, deploy_receipt_dir=tmp_path / "deploys"
    )

    assert payload["claim"]["kind"] == "refused"
    dispatcher_source = next(
        source for source in payload["sources"] if source["name"] == "dispatcher-store"
    )
    assert dispatcher_source["state"] == "unavailable"
    assert dispatcher_source["last_successful_read"] is None
    # No zero counts for bands owned by the dead source — refused, not empty.
    for band in payload["bands"]:
        assert band["countable"] is False
        assert band["count"] is None
    # The database must not have been created by the read.
    assert not missing_db.exists()


def test_true_emptiness_is_dated_claim(tmp_path: Path) -> None:
    _, db_path = _make_store(tmp_path)

    payload = _registry(db_path, tmp_path)

    assert payload["claim"]["kind"] == "counted"
    assert payload["claim"]["text"].startswith("0 threads in motion as of ")
    for band in payload["bands"]:
        assert band["countable"] is True
        assert band["count"] == 0
    for name in ("dispatcher-store", "verification-runs"):
        source = next(s for s in payload["sources"] if s["name"] == name)
        assert source["state"] in ("fresh", "empty")
        assert source["last_successful_read"] is not None
    # A missing deploy receipt is structural absence, not a dead source.
    deploy_source = next(
        s for s in payload["sources"] if s["name"] == "deploy-receipts"
    )
    assert deploy_source["state"] == "empty"


def test_rung_classification_machine_edges_only(tmp_path: Path) -> None:
    store, db_path = _make_store(tmp_path)
    repo = "RasmusTho/agentic-pkm-mvp"
    store.upsert_task(
        _task(status="review", issue_number=4438, linked_pr="4460", repo=repo)
    )
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO verification_runs (run_id, idempotency_key,"
            " contract_version, repository, pr_number, head_sha,"
            " current_head_sha, verified_head_sha, stage, request_json,"
            " status, terminal_receipt_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "idem-1",
                "v1",
                repo,
                4460,
                "a" * 40,
                "a" * 40,
                "a" * 40,
                "verify",
                "{}",
                "completed",
                json.dumps({"outcome": "merged"}),
                now,
                now,
            ),
        )

    payload = _registry(db_path, tmp_path)
    item = _band(payload, "working")["items"][0]
    rungs = {rung["name"]: rung for rung in item["rungs"]}

    assert [rung["name"] for rung in item["rungs"]] == list(RUNG_ORDER)
    # Machine-keyed edges are proven.
    assert rungs["slice"]["class"] == "proven"
    assert rungs["pr"]["class"] == "proven"
    assert rungs["ci_sha"]["class"] == "proven"
    assert rungs["ci_sha"]["value"] == "a" * 12
    assert rungs["receipt"]["class"] == "proven"
    # Levels with no machine-readable object render absent — never proven.
    for name in ("intention", "capability", "epic", "tried"):
        assert rungs[name]["class"] == "absent"
