"""Tests for the GitHub live plane join (BOPS-COCKPIT-03, #4450).

Every test injects a fake ``github_reader`` — no test in this file performs
network I/O, matching decision Q5
(docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q5) and the issue's own
constraint ("Tests use an injected fake reader; no network in CI").
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.builderops import cockpit_github_plane
from app.builderops.cockpit_github_plane import (
    GithubIssue,
    GithubLiveSnapshot,
    GithubPull,
    GithubReadError,
)
from app.builderops.cockpit_registry import build_registry
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore

REPO = "RasmusTho/agentic-pkm-mvp"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_store(tmp_path: Path) -> tuple[Path, SqliteStore]:
    db_path = tmp_path / "dispatcher.sqlite3"
    store = SqliteStore(db_path)
    store.initialize()
    return db_path, store


def _task(
    *,
    status: str,
    issue_number: int,
    title: str = "a task",
    repo: str = REPO,
    linked_pr: str | None = None,
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
        sync_state=sync_state,
        created_at=now,
        updated_at=now,
    )


def _item_by_issue(payload: dict, issue_number: int) -> dict:
    for band in payload["bands"]:
        for item in band["items"]:
            if item["issue_number"] == issue_number:
                return item
    raise AssertionError(f"no item for issue {issue_number} in payload")


def _source(payload: dict, name: str) -> dict:
    return next(s for s in payload["sources"] if s["name"] == name)


# ---------------------------------------------------------------------------
# test_github_failure_refuses_not_zeroes
# ---------------------------------------------------------------------------


def test_github_failure_refuses_not_zeroes(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=1))

    def failing_reader(repo: str) -> GithubLiveSnapshot:
        raise GithubReadError("simulated rate limit / read failure")

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=failing_reader,
    )

    github_source = _source(payload, "github-live")
    assert github_source["state"] == "unavailable"
    assert github_source["last_successful_read"] is None

    # GitHub-owned facts refuse — never zero, never stale-as-fresh.
    assert payload["github"]["countable"] is False
    assert payload["github"]["open_issues"] is None
    assert payload["github"]["open_prs"] is None
    assert payload["github"]["branches"] is None

    # A dead github-live source must not fabricate unsynced-thread cards.
    assert payload["unsynced_threads"] == []

    # The production join path (`build_registry`) is what emits the refusal —
    # not a wrapper — and the dispatcher-owned bands are unaffected by the
    # unrelated github-live failure.
    assert payload["claim"]["kind"] == "counted"


def test_missing_repo_config_refuses_without_network(tmp_path: Path) -> None:
    """No ``github_repo`` configured is itself a safe, silent refusal.

    This is the exact posture the production API route relies on: an
    unconfigured host must never attempt a network call, only refuse.
    """
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=1))

    calls: list[str] = []

    def reader_that_must_not_be_called(repo: str) -> GithubLiveSnapshot:
        calls.append(repo)
        raise AssertionError("reader must not be invoked with no repo configured")

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=None,
        github_reader=reader_that_must_not_be_called,
    )

    assert calls == []
    github_source = _source(payload, "github-live")
    assert github_source["state"] == "unavailable"
    assert payload["github"]["countable"] is False


# ---------------------------------------------------------------------------
# test_live_keys_upgrade_rungs_and_surface_unsynced_threads
# ---------------------------------------------------------------------------


def test_live_keys_upgrade_rungs_and_surface_unsynced_threads(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    # Issue #100 is tracked by the dispatcher store, but the store has no
    # linked_pr yet and no verification run — the owner already pushed a PR
    # for it in GitHub, and this plane should surface that.
    store.upsert_task(_task(status="ready", issue_number=100, title="unsynced pr"))

    head_sha = "a" * 40

    def fake_reader(repo: str) -> GithubLiveSnapshot:
        assert repo == REPO
        return GithubLiveSnapshot(
            read_at=_now(),
            issues={
                100: GithubIssue(
                    number=100,
                    title="unsynced pr",
                    state="open",
                    html_url=f"https://github.com/{REPO}/issues/100",
                )
            },
            pulls={
                55: GithubPull(
                    number=55,
                    title="Fix #100",
                    state="open",
                    html_url=f"https://github.com/{REPO}/pull/55",
                    head_sha=head_sha,
                    head_ref="fix-100",
                    governing_issue=100,
                ),
                # A second PR with no matching dispatcher task at all —
                # neither its PR number nor its governing issue is tracked.
                77: GithubPull(
                    number=77,
                    title="Unrelated branch work",
                    state="open",
                    html_url=f"https://github.com/{REPO}/pull/77",
                    head_sha="b" * 40,
                    head_ref="unrelated-branch",
                    governing_issue=None,
                ),
            },
            checks={head_sha: "success"},
            branches=("fix-100", "unrelated-branch"),
        )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=fake_reader,
    )

    assert _source(payload, "github-live")["state"] == "fresh"
    assert payload["github"]["countable"] is True
    assert payload["github"]["open_prs"] == 2

    item = _item_by_issue(payload, 100)
    rungs = {r["name"]: r for r in item["rungs"]}
    assert rungs["pr"]["class"] == "proven"
    assert "55" in rungs["pr"]["value"]
    assert rungs["ci_sha"]["class"] == "proven"
    assert head_sha[:12] in rungs["ci_sha"]["value"]
    assert "success" in rungs["ci_sha"]["value"]
    # The card's out-link must follow the same live-only PR match the rung
    # just claimed — not fall back to the plain issue URL (#4450 review).
    assert item["links"] == [f"https://github.com/{REPO}/pull/55"]

    # PR #77 matches no dispatcher task by PR number or governing issue: it
    # must render as a card, not disappear.
    unsynced_ids = {t["pr_number"] for t in payload["unsynced_threads"]}
    assert 77 in unsynced_ids
    # PR #55 IS reachable from a dispatcher task (via its governing issue),
    # so it must not be double-counted as unsynced.
    assert 55 not in unsynced_ids


def test_dispatcher_dead_still_surfaces_live_prs_as_unsynced(tmp_path: Path) -> None:
    """When the dispatcher store itself cannot be read, nothing is "known",
    so every live PR is honestly unsynced rather than assumed tracked."""
    missing_db = tmp_path / "nowhere" / "dispatcher.sqlite3"

    def fake_reader(repo: str) -> GithubLiveSnapshot:
        return GithubLiveSnapshot(
            read_at=_now(),
            pulls={
                9: GithubPull(
                    number=9,
                    title="Some PR",
                    state="open",
                    html_url=f"https://github.com/{REPO}/pull/9",
                    head_sha="c" * 40,
                    head_ref="some-branch",
                    governing_issue=None,
                )
            },
        )

    payload = build_registry(
        db_path=missing_db,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=fake_reader,
    )

    assert payload["claim"]["kind"] == "refused"  # dispatcher-store is dead
    assert _source(payload, "github-live")["state"] == "fresh"  # unrelated source
    unsynced_ids = {t["pr_number"] for t in payload["unsynced_threads"]}
    assert unsynced_ids == {9}


# ---------------------------------------------------------------------------
# test_cards_carry_authority_outlinks
# ---------------------------------------------------------------------------


def test_cards_carry_authority_outlinks(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    # No sync_state at all: the mirror's url field is empty (audit F9's
    # historical production reality) — the live read must supply the link
    # independently.
    store.upsert_task(_task(status="in_progress", issue_number=200, title="no mirror url"))
    # A second task that does have a linked_pr: the live PR url should win
    # over the live issue url (the nearer authority).
    store.upsert_task(
        _task(status="in_progress", issue_number=201, title="has pr", linked_pr="9")
    )

    def fake_reader(repo: str) -> GithubLiveSnapshot:
        return GithubLiveSnapshot(
            read_at=_now(),
            issues={
                200: GithubIssue(
                    number=200,
                    title="no mirror url",
                    state="open",
                    html_url=f"https://github.com/{REPO}/issues/200",
                ),
                201: GithubIssue(
                    number=201,
                    title="has pr",
                    state="open",
                    html_url=f"https://github.com/{REPO}/issues/201",
                ),
            },
            pulls={
                9: GithubPull(
                    number=9,
                    title="has pr",
                    state="open",
                    html_url=f"https://github.com/{REPO}/pull/9",
                    head_sha="d" * 40,
                    head_ref="pr-9",
                    governing_issue=201,
                )
            },
        )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=fake_reader,
    )

    item_200 = _item_by_issue(payload, 200)
    assert item_200["links"] == [f"https://github.com/{REPO}/issues/200"]

    item_201 = _item_by_issue(payload, 201)
    assert item_201["links"] == [f"https://github.com/{REPO}/pull/9"]


def test_live_link_falls_back_to_mirror_url_on_read_failure(tmp_path: Path) -> None:
    """A github-live failure must not remove an out-link the mirror already had."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(
        _task(
            status="in_progress",
            issue_number=300,
            title="has mirror url",
            sync_state={"url": f"https://github.com/{REPO}/issues/300"},
        )
    )

    def failing_reader(repo: str) -> GithubLiveSnapshot:
        raise GithubReadError("simulated failure")

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=failing_reader,
    )

    item = _item_by_issue(payload, 300)
    assert item["links"] == [f"https://github.com/{REPO}/issues/300"]


# ---------------------------------------------------------------------------
# test_no_cross_render_cache
# ---------------------------------------------------------------------------


def test_no_cross_render_cache(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=1))

    call_count = {"n": 0}

    def counting_reader(repo: str) -> GithubLiveSnapshot:
        call_count["n"] += 1
        return GithubLiveSnapshot(
            read_at=f"2026-07-31T00:00:0{call_count['n']}+00:00",
        )

    first = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=counting_reader,
    )
    second = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=counting_reader,
    )

    # Every render pays for its own read: the reader is called once per
    # build_registry() call, never memoized.
    assert call_count["n"] == 2
    first_read = _source(first, "github-live")["last_successful_read"]
    second_read = _source(second, "github-live")["last_successful_read"]
    assert first_read == "2026-07-31T00:00:01+00:00"
    assert second_read == "2026-07-31T00:00:02+00:00"
    assert first_read != second_read

    # A third render whose reader fails must not inherit the prior render's
    # success — nothing GitHub-derived survives across calls.
    def failing_reader(repo: str) -> GithubLiveSnapshot:
        raise GithubReadError("simulated failure after two successful reads")

    third = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=failing_reader,
    )
    assert _source(third, "github-live")["state"] == "unavailable"
    assert third["github"]["countable"] is False


# ---------------------------------------------------------------------------
# test_mirror_fields_name_mirror_watermark
# ---------------------------------------------------------------------------


def test_mirror_fields_name_mirror_watermark(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    mirror_watermark = "2026-07-20T10:00:00+00:00"
    store.upsert_task(
        _task(
            status="in_progress",
            issue_number=400,
            title="mirror-synced",
            sync_state={
                "labels": ["type:task"],
                "url": f"https://github.com/{REPO}/issues/400",
                "last_pull_at": mirror_watermark,
            },
        )
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        # No github_repo configured: isolates the assertion to the mirror
        # watermark, independent of the live plane's own freshness.
        github_repo=None,
    )

    item = _item_by_issue(payload, 400)
    dispatcher_store_read = _source(payload, "dispatcher-store")["last_successful_read"]

    assert item["mirror_watermark"] == mirror_watermark
    # The mirror's own watermark must never be silently replaced by the
    # dispatcher-store SQLite read instant.
    assert item["mirror_watermark"] != dispatcher_store_read


def test_mirror_watermark_absent_when_sync_state_lacks_it(tmp_path: Path) -> None:
    db_path, store = _make_store(tmp_path)
    store.upsert_task(
        _task(
            status="in_progress",
            issue_number=401,
            title="no watermark yet",
            sync_state={"labels": [], "url": None},
        )
    )

    payload = build_registry(
        db_path=db_path, deploy_receipt_dir=tmp_path / "deploys", github_repo=None
    )

    item = _item_by_issue(payload, 401)
    assert item["mirror_watermark"] is None


# ---------------------------------------------------------------------------
# Per-PR check-status read failures, and the real reader (#4471)
# ---------------------------------------------------------------------------


def test_check_status_read_failure_is_distinguishable_from_no_checks(
    tmp_path: Path,
) -> None:
    """A failed per-SHA check read must not impersonate "this SHA has no CI".

    Both cases leave the SHA out of ``checks``. Only one of them is a claim
    about GitHub; the other is a claim about our own read. The rung says which,
    and the "PR without CI" flaw refuses to fire on evidence nobody has.
    """
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=610, title="unread ci"))
    store.upsert_task(_task(status="in_progress", issue_number=620, title="no ci"))

    unread_sha = "c" * 40
    genuinely_bare_sha = "d" * 40

    def _pull(number: int, issue: int, sha: str) -> GithubPull:
        return GithubPull(
            number=number,
            title=f"Fix #{issue}",
            state="open",
            html_url=f"https://github.com/{REPO}/pull/{number}",
            head_sha=sha,
            head_ref=f"fix-{issue}",
            governing_issue=issue,
        )

    def fake_reader(repo: str) -> GithubLiveSnapshot:
        return GithubLiveSnapshot(
            read_at=_now(),
            issues={},
            pulls={61: _pull(61, 610, unread_sha), 62: _pull(62, 620, genuinely_bare_sha)},
            # Neither SHA is in `checks`. The difference is entirely in why.
            checks={},
            branches=("fix-610", "fix-620"),
            check_read_failures=frozenset({unread_sha}),
        )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=fake_reader,
    )

    unread_item = _item_by_issue(payload, 610)
    unread_rung = {r["name"]: r for r in unread_item["rungs"]}["ci_sha"]
    assert unread_rung["class"] == "absent"
    assert unread_sha[:12] in unread_rung["value"]
    assert "unread" in unread_rung["value"]

    bare_item = _item_by_issue(payload, 620)
    bare_rung = {r["name"]: r for r in bare_item["rungs"]}["ci_sha"]
    assert bare_rung["class"] == "absent"
    assert "unread" not in (bare_rung["value"] or "")

    # The flaw is a claim about GitHub, so it fires only for the SHA we
    # actually read — never for the one we failed to read.
    def _flaw_names(item: dict) -> set[str]:
        return {flaw["predicate"] for flaw in item.get("flaws", [])}

    assert "pr_without_ci_on_head_sha" in _flaw_names(bare_item)
    assert "pr_without_ci_on_head_sha" not in _flaw_names(unread_item)


def test_default_github_reader_builds_snapshot_from_mocked_gh_calls(
    monkeypatch,
) -> None:
    """Direct coverage of the reader that actually runs in production.

    Every other test here injects a snapshot, so ``default_github_reader`` —
    pagination, PR/issue separation, the per-SHA status loop, and its failure
    handling — had none. The ``gh`` subprocess boundary is mocked, so this
    still performs no network I/O.
    """
    good_sha = "e" * 40
    failing_sha = "f" * 40
    calls: list[list[str]] = []

    def fake_run_gh(args: list[str]):
        calls.append(args)
        endpoint = args[1]
        if endpoint.endswith("/issues"):
            return [
                {
                    "number": 700,
                    "title": "a real issue",
                    "state": "open",
                    "html_url": f"https://github.com/{REPO}/issues/700",
                },
                # The raw /issues endpoint mixes PRs in; they must be dropped.
                {
                    "number": 701,
                    "title": "a pr wearing an issue shape",
                    "state": "open",
                    "html_url": f"https://github.com/{REPO}/pull/701",
                    "pull_request": {"url": "..."},
                },
            ]
        if endpoint.endswith("/pulls"):
            return [
                {
                    "number": 71,
                    "title": "Fix the thing",
                    "state": "open",
                    "html_url": f"https://github.com/{REPO}/pull/71",
                    "head": {"sha": good_sha, "ref": "fix-700"},
                    "body": "Governing-Issue: #700",
                },
                {
                    "number": 72,
                    "title": "Another",
                    "state": "open",
                    "html_url": f"https://github.com/{REPO}/pull/72",
                    "head": {"sha": failing_sha, "ref": "other"},
                    "body": "no governing line here",
                },
            ]
        if endpoint.endswith("/branches"):
            return [{"name": "fix-700"}, {"name": "other"}]
        if endpoint.endswith(f"/commits/{good_sha}/status"):
            return {"state": "success"}
        if endpoint.endswith(f"/commits/{failing_sha}/status"):
            raise GithubReadError("simulated rate limit on one PR's checks")
        raise AssertionError(f"unexpected gh call: {args}")

    monkeypatch.setattr(cockpit_github_plane, "_run_gh", fake_run_gh)

    snapshot = cockpit_github_plane.default_github_reader(REPO)

    assert set(snapshot.issues) == {700}
    assert set(snapshot.pulls) == {71, 72}
    assert snapshot.pulls[71].governing_issue == 700
    assert snapshot.pulls[72].governing_issue is None
    assert snapshot.branches == ("fix-700", "other")

    # One PR's check read succeeded, the other failed. The failure is recorded
    # rather than swallowed, and does not refuse the whole plane.
    assert snapshot.checks == {good_sha: "success"}
    assert snapshot.check_read_failures == frozenset({failing_sha})
    assert snapshot.check_read_failed(failing_sha) is True
    assert snapshot.check_read_failed(good_sha) is False

    # REST only, never GraphQL (the shared budget dies on GraphQL first).
    assert all(call[0] == "api" for call in calls)
    assert not any("graphql" in " ".join(call) for call in calls)


def test_default_github_reader_rejects_a_malformed_repo_slug() -> None:
    try:
        cockpit_github_plane.default_github_reader("not-a-slug")
    except GithubReadError as exc:
        assert "owner/name" in str(exc)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("a slug with no '/' must be refused before any call")
