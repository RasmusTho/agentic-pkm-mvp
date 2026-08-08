"""Tests for the cockpit registry read-time join (#4438)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import app.builderops.cockpit_registry as cockpit_registry
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
    """Fail-closed banding, restated over chain position (#4452).

    #4438 shipped a dispatcher-status-word mapping; BOPS-COCKPIT-04 replaced it
    with chain-position derivation, so the *band counts* below moved while
    every honesty contract this test guards stayed put:

    - a fresh unclaimed ``ready`` issue is **in progress**, not forgotten (the
      register's first question includes the queue); forgotten now requires a
      stall, proven separately in ``test_forgotten_needs_stall_not_age``;
    - ``blocked`` is an open chain position that *carries* a flaw rather than
      being a band of its own, so it appears in working **and** flawed;
    - ``completed`` with no verification receipt stays delivered and gains the
      ``delivered_without_verification_receipt`` flaw — gating the position on
      the receipt would hide an unverified merge from the done band entirely.
    """
    store, db_path = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=1, title="working"))
    store.upsert_task(_task(status="completed", issue_number=2, title="done"))
    store.upsert_task(
        _task(status="blocked", issue_number=3, title="flawed", blocked_reason="upstream")
    )
    store.upsert_task(_task(status="ready", issue_number=4, title="fresh queue item"))
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

    # Band order stays locked — the contract #4452 must not weaken.
    assert [band["key"] for band in payload["bands"]] == [key for key, _ in BANDS]
    # in_progress (#1), blocked (#3) and the fresh ready item (#4) all hold an
    # open chain position.
    assert _band(payload, "working")["count"] == 3
    assert _band(payload, "done")["count"] == 1
    # Two threads carry a flaw: #3 (blocked) and #2 (delivered, no receipt).
    assert _band(payload, "flawed")["count"] == 2
    # Nothing has stalled: no card is forgotten on age it does not have.
    assert _band(payload, "forgotten")["count"] == 0
    # The needs-human label routes to the needs-you band even from a mapped status.
    assert _band(payload, "needs_you")["count"] == 1
    # The unknown status is listed, never guessed into a band.
    assert len(payload["unclassified"]) == 1
    assert payload["unclassified"][0]["status"] == "mystery_status"
    all_items = [item for band in payload["bands"] for item in band["items"]]
    assert all(item["status"] != "mystery_status" for item in all_items)
    # The claim counts distinct threads, not band memberships: the two
    # dual-banded threads are each one thread, never two.
    assert payload["claim"]["text"].startswith("5 threads in motion")
    # The flawed item carries the gate's own wording — the predicate's phrasing.
    flawed_item = next(
        item for item in _band(payload, "flawed")["items"] if item["issue_number"] == 3
    )
    assert flawed_item["why_now"] == "blocked: upstream"


def test_chain_derivation_failure_does_not_expose_exception_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, db_path = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=7))

    def fail_derivation(*args, **kwargs):
        raise RuntimeError("secret path: /private/dispatcher.sqlite3")

    monkeypatch.setattr(cockpit_registry, "derive_position", fail_derivation)
    payload = _registry(db_path, tmp_path)

    assert payload["unclassified"][0]["reason"] == "chain-position derivation failed"
    assert "/private/dispatcher.sqlite3" not in repr(payload)


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


def test_unconfigured_github_source_marks_not_configured(tmp_path: Path) -> None:
    """EXT-8: an opt-in plane nobody turned on is unavailable but configured=False.

    ``state`` still says ``unavailable`` — the plane owns no countable facts
    either way — but the payload now carries enough for the surface to tell
    "never enabled" apart from "broken".
    """
    _, db_path = _make_store(tmp_path)

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=None,
    )

    github_source = next(
        s for s in payload["sources"] if s["name"] == "github-live"
    )
    assert github_source["state"] == "unavailable"
    assert github_source["configured"] is False

    # Every other source is configured by construction: only a plane that is
    # optional *and* unset may claim otherwise.
    for source in payload["sources"]:
        if source["name"] != "github-live":
            assert source["configured"] is True


def test_configured_github_failure_stays_configured(tmp_path: Path) -> None:
    """A configured plane that fails is a real outage, and must stay loud."""
    _, db_path = _make_store(tmp_path)

    def failing_reader(repo: str):
        raise RuntimeError("simulated read failure on a configured plane")

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo="RasmusTho/agentic-pkm-mvp",
        github_reader=failing_reader,
    )

    github_source = next(
        s for s in payload["sources"] if s["name"] == "github-live"
    )
    assert github_source["state"] == "unavailable"
    assert github_source["configured"] is True
    assert github_source["last_successful_read"] is None


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
