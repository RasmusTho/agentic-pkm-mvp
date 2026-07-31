"""Tests for chain-derived states and flaw predicates (BOPS-COCKPIT-04, #4452).

Every test drives the production join path (``build_registry``) end to end with
injected plane fixtures — no test performs network or live-repo I/O, and no
test asserts against a wrapper the production surface does not use.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.builderops.cockpit_chain import (
    FLAW_PREDICATES,
    FORGOTTEN_STALL_DAYS,
    RISK_MAX_TICKS,
    SOURCE_STALE_AFTER_DAYS,
    UNREAD_FLAW_PREDICATES,
)
from app.builderops.cockpit_github_plane import (
    GithubIssue,
    GithubLiveSnapshot,
    GithubPull,
)
from app.builderops.cockpit_registry import build_registry
from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore

REPO = "RasmusTho/agentic-pkm-mvp"


# ---------------------------------------------------------------------------
# fixtures / helpers (same conventions as the three prior slices' test files)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="microseconds")


def _days_ago(days: float) -> str:
    return _iso(_now() - timedelta(days=days))


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
    blocked_reason: str | None = None,
    claimed_by: str | None = None,
    lease_id: str | None = None,
    lease_expires_at: str | None = None,
    last_heartbeat_at: str | None = None,
    updated_at: str | None = None,
    sync_state: dict | None = None,
) -> TaskRecord:
    stamp = updated_at or _iso(_now())
    return TaskRecord(
        task_id=f"task-{issue_number}-{uuid.uuid4().hex[:6]}",
        issue_number=issue_number,
        title=title,
        status=status,
        priority="med",
        repo=repo,
        source_anchor_refs=[],
        linked_pr=linked_pr,
        blocked_reason=blocked_reason,
        claimed_by=claimed_by,
        lease_id=lease_id,
        lease_expires_at=lease_expires_at,
        last_heartbeat_at=last_heartbeat_at,
        sync_state=sync_state,
        created_at=stamp,
        updated_at=stamp,
    )


def _band(payload: dict, key: str) -> dict:
    return next(band for band in payload["bands"] if band["key"] == key)


def _items(payload: dict, key: str) -> list[dict]:
    return _band(payload, key)["items"]


def _issues_in(payload: dict, key: str) -> set[int]:
    return {item["issue_number"] for item in _items(payload, key)}


def _item_by_issue(payload: dict, issue_number: int) -> dict:
    for band in payload["bands"]:
        for item in band["items"]:
            if item["issue_number"] == issue_number:
                return item
    raise AssertionError(f"no item for issue {issue_number} in payload")


def _source(payload: dict, name: str) -> dict:
    return next(s for s in payload["sources"] if s["name"] == name)


def _flaw_names(item: dict) -> set[str]:
    return {flaw["predicate"] for flaw in item["flaws"]}


def _all_flaws(payload: dict) -> dict[str, dict]:
    """Every fired flaw across the whole payload, keyed by predicate name."""
    found: dict[str, dict] = {}
    for item in _items(payload, "flawed"):
        for flaw in item["flaws"]:
            found[flaw["predicate"]] = flaw
    return found


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


_CAPABILITIES_YAML = """capabilities:
  - id: chain-fixture
    name: Chain Fixture Capability
    boundary_ref: CFX
"""

_MATRIX_MD = """| Area | Control boundaries | Implementation issues |
|---|---|---|
| Fixture | CFX | #9001 |
"""


def _write_docs_fixture(
    docs_root: Path,
    *,
    epic_issue: int = 807,
    child_issue: int = 808,
    spec_dir_name: str = "CHAIN_FIXTURE",
) -> None:
    """A minimal spec directory with a *machine* epic edge and one child doc."""
    _write(docs_root / "capabilities.yaml", _CAPABILITIES_YAML)
    _write(docs_root / "matrix.md", _MATRIX_MD)
    _write(
        docs_root / spec_dir_name / "PARENT_FEATURE_ISSUE.md",
        f"---\nname: Chain Fixture\ngithub_issue: {epic_issue}\n---\n\n"
        "# Chain Fixture\n",
    )
    _write(
        docs_root / spec_dir_name / "CHILD_TASK.md",
        "---\n"
        "name: Child Task\n"
        "task_id: CFX-01\n"
        f"github_issue: {child_issue}\n"
        "parent_capability: Chain Fixture Capability\n"
        "---\n\n# Child Task\n",
    )


def _docs_kwargs(docs_root: Path) -> dict:
    return {
        "docs_root": docs_root,
        "capabilities_yaml_path": docs_root / "capabilities.yaml",
        "matrix_path": docs_root / "matrix.md",
    }


def _snapshot(**kwargs) -> GithubLiveSnapshot:
    kwargs.setdefault("read_at", _iso(_now()))
    return GithubLiveSnapshot(**kwargs)


def _reader(snapshot: GithubLiveSnapshot):
    def _read(repo: str) -> GithubLiveSnapshot:
        assert repo == REPO
        return snapshot

    return _read


# ---------------------------------------------------------------------------
# AC1 — fail-closed chain position
# ---------------------------------------------------------------------------


def test_unresolvable_position_is_unclassified_not_guessed(tmp_path: Path) -> None:
    """A position that cannot be computed lands in ``unclassified``, never in a
    band — and contradictory planes never rescue it into one.

    The fixture is deliberately contradictory: GitHub reports live, open work
    while the dispatcher record is either unmapped or carries an unreadable
    movement timestamp. Fail-closed must not mean fail-blind, so the third
    thread proves the opposite direction: when the live plane *does* settle the
    stall question on its own, the position is resolved rather than refused.
    """
    db_path, store = _make_store(tmp_path)
    # A: a status word that maps to no chain position at all.
    store.upsert_task(_task(status="mystery_status", issue_number=901, title="unmapped"))
    # B: an open status whose only movement timestamps are unreadable, and no
    #    live PR to settle the stall question from the other side.
    store.upsert_task(
        _task(
            status="ready",
            issue_number=902,
            title="unreadable movement",
            updated_at="not-a-timestamp",
        )
    )
    # C: the same unreadable timestamps, but an open live PR — resolvable.
    store.upsert_task(
        _task(
            status="ready",
            issue_number=903,
            title="unreadable movement but live PR",
            updated_at="not-a-timestamp",
        )
    )

    snapshot = _snapshot(
        issues={
            number: GithubIssue(
                number=number,
                title="still open in GitHub",
                state="open",
                html_url=f"https://github.com/{REPO}/issues/{number}",
            )
            for number in (901, 902, 903)
        },
        pulls={
            93: GithubPull(
                number=93,
                title="Governing-Issue: #903",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/93",
                head_sha="a" * 40,
                head_ref="pr-93",
                governing_issue=903,
            )
        },
        checks={"a" * 40: "success"},
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(snapshot),
    )

    unclassified = {entry["id"]: entry for entry in payload["unclassified"]}
    assert len(unclassified) == 2

    # Neither refused thread appears in any band — not even the flaws band,
    # and not even though GitHub says both issues are open.
    banded_issues = {
        item["issue_number"] for band in payload["bands"] for item in band["items"]
    }
    assert 901 not in banded_issues
    assert 902 not in banded_issues

    reasons = " | ".join(entry["reason"] for entry in unclassified.values())
    assert "mystery_status" in reasons
    assert "stall test cannot be evaluated" in reasons

    # Fail-closed is not fail-blind: the live plane alone resolves C.
    item = _item_by_issue(payload, 903)
    assert item["chain_position"] == "in_progress"
    assert item["position_evidence"]["open_authority_work"] == 93
    assert 903 in _issues_in(payload, "working")

    # Band counts never absorb a refused thread.
    assert _band(payload, "working")["count"] == 1


def test_needs_human_card_states_its_unresolved_reason(tmp_path: Path) -> None:
    """A needs_you-labelled thread whose chain position is unresolvable must
    still carry ITS OWN reason on the card — the routing label bypasses the
    fail-closed band rule, but it must not silently drop the "why null"
    explanation the unclassified path would otherwise have surfaced."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(
        _task(
            status="mystery_status",
            issue_number=940,
            title="needs a human, unresolvable position",
            sync_state={"labels": ["agent:needs-human"]},
        )
    )

    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    item = _item_by_issue(payload, 940)
    assert 940 in _issues_in(payload, "needs_you")
    assert item["chain_position"] is None
    assert item["position_unresolved_reason"] is not None
    assert "mystery_status" in item["position_unresolved_reason"]
    assert "mystery_status" in item["why_now"]
    assert "labelled for a human" in item["why_now"]


# ---------------------------------------------------------------------------
# AC2 — every flaw predicate fires with named evidence
# ---------------------------------------------------------------------------


def test_each_flaw_predicate_fires_with_evidence(tmp_path: Path) -> None:
    """One fixture that reproduces every implemented predicate's real shape.

    Also pins the two boundaries the issue draws around the predicate set:
    ``delivered_never_tried`` is rendered as the done band's empty tried tier
    and is *never* a red mark, and no predicate fires without the evidence keys
    its consumer needs (PR number, SHA, lease id, ...).
    """
    db_path, store = _make_store(tmp_path)
    stale_stamp = _days_ago(FORGOTTEN_STALL_DAYS + 16)

    store.upsert_task(
        _task(
            status="blocked",
            issue_number=801,
            title="blocked",
            blocked_reason="waiting on upstream",
        )
    )
    store.upsert_task(_task(status="completed", issue_number=802, title="merged"))
    store.upsert_task(
        _task(
            status="claimed",
            issue_number=803,
            title="abandoned mid-work",
            claimed_by="agent-x",
            lease_id="lease-803",
            lease_expires_at=_days_ago(2),
        )
    )
    store.upsert_task(
        _task(status="review", issue_number=804, title="red ci", linked_pr="84")
    )
    store.upsert_task(
        _task(status="review", issue_number=805, title="no ci", linked_pr="85")
    )
    store.upsert_task(_task(status="ready", issue_number=806, title="pushed branch"))
    store.upsert_task(
        _task(
            status="ready",
            issue_number=807,
            title="stale epic",
            updated_at=stale_stamp,
        )
    )

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root, epic_issue=807, child_issue=808)

    red_sha = "d" * 40
    quiet_sha = "e" * 40
    snapshot = _snapshot(
        issues={
            # 802 is open in GitHub while the dispatcher says completed.
            802: GithubIssue(
                number=802,
                title="merged",
                state="open",
                html_url=f"https://github.com/{REPO}/issues/802",
            ),
            # 808 is the epic's open child.
            808: GithubIssue(
                number=808,
                title="open child",
                state="open",
                html_url=f"https://github.com/{REPO}/issues/808",
            ),
        },
        pulls={
            84: GithubPull(
                number=84,
                title="red ci",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/84",
                head_sha=red_sha,
                head_ref="fix-red",
                governing_issue=804,
            ),
            85: GithubPull(
                number=85,
                title="no ci",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/85",
                head_sha=quiet_sha,
                head_ref="fix-quiet",
                governing_issue=805,
            ),
        },
        checks={red_sha: "failure"},
        branches=("fix-red", "fix-quiet", "issue-806-wip"),
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(snapshot),
        **_docs_kwargs(docs_root),
    )

    # Every predicate the module declares was evaluable on this fixture.
    header = _band(payload, "flawed")["header"]
    assert header["not_evaluated"] == []
    assert set(header["evaluated"]) == {p["name"] for p in FLAW_PREDICATES}

    fired = _all_flaws(payload)
    assert set(fired) == {p["name"] for p in FLAW_PREDICATES}, (
        "every declared predicate must fire on this fixture; missing: "
        f"{set(p['name'] for p in FLAW_PREDICATES) - set(fired)}"
    )

    # -- named evidence keys, per predicate --------------------------------
    assert fired["blocked_without_next_link"]["evidence"] == {
        "blocked_reason": "waiting on upstream",
        "dispatcher_status": "blocked",
    }
    assert fired["dispatcher_github_contradiction"]["evidence"] == {
        "issue_number": 802,
        "dispatcher_status": "completed",
        "github_issue_state": "open",
    }
    assert fired["expired_lease"]["evidence"]["lease_id"] == "lease-803"
    assert fired["expired_lease"]["evidence"]["holder"] == "agent-x"
    assert fired["expired_lease"]["evidence"]["lease_expires_at"] is not None
    assert fired["pr_ci_red_on_head_sha"]["evidence"] == {
        "pr_number": 84,
        "head_sha": red_sha,
        "check_state": "failure",
    }
    assert fired["pr_without_ci_on_head_sha"]["evidence"] == {
        "pr_number": 85,
        "head_sha": quiet_sha,
    }
    assert fired["pushed_branch_without_pr"]["evidence"] == {
        "branch": "issue-806-wip",
        "issue_number": 806,
    }
    assert fired["delivered_without_verification_receipt"]["evidence"][
        "issue_number"
    ] == 802
    epic_evidence = fired["stale_epic_with_open_children"]["evidence"]
    assert epic_evidence["epic_issue"] == 807
    assert epic_evidence["spec_dir"] == "CHAIN_FIXTURE"
    assert epic_evidence["open_children"] == [808]

    # A branch already carrying an open PR is never reported as PR-less.
    assert _flaw_names(_item_by_issue(payload, 804)) == {"pr_ci_red_on_head_sha"}

    # why_now is the predicate's own phrasing, never a number.
    for item in _items(payload, "flawed"):
        assert item["why_now"] == item["flaws"][0]["text"]
        assert not item["why_now"].strip().replace(".", "").isdigit()

    # -- delivered-never-tried: an empty tier, not a red mark ---------------
    assert "delivered_never_tried" not in fired
    tried_tier = _band(payload, "done")["tried_tier"]
    assert tried_tier["items"] == []
    assert tried_tier["reserved"] is True
    assert "INV-DG-7" in tried_tier["reason"]
    assert any(
        entry["predicate"] == "delivered_never_tried"
        for entry in header["rendered_elsewhere"]
    )


def test_predicates_not_evaluated_when_their_plane_is_absent(tmp_path: Path) -> None:
    """A predicate whose plane is missing is named as unevaluated, not fired.

    This is the honesty seam that keeps the flaws band from reading as "no
    flaws" when it really means "we could not look".
    """
    db_path, store = _make_store(tmp_path)
    store.upsert_task(
        _task(status="blocked", issue_number=811, title="blocked", blocked_reason="x")
    )

    # No github plane, no docs plane configured.
    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    header = _band(payload, "flawed")["header"]
    unevaluated = {entry["predicate"] for entry in header["not_evaluated"]}
    assert "pushed_branch_without_pr" in unevaluated
    assert "stale_epic_with_open_children" in unevaluated
    assert "dispatcher_github_contradiction" in unevaluated
    for entry in header["not_evaluated"]:
        assert "not fresh" in entry["reason"]
        assert entry["requires"]

    # The predicates that only need the dispatcher store still run.
    assert "blocked_without_next_link" in header["evaluated"]
    assert _flaw_names(_item_by_issue(payload, 811)) == {"blocked_without_next_link"}


# ---------------------------------------------------------------------------
# AC3 — one identity, two bands
# ---------------------------------------------------------------------------


def test_dual_band_single_identity(tmp_path: Path) -> None:
    """A thread holds a working position *and* carries flaws: same id, same
    spine, no copy drift — including after JSON serialisation, which is where
    a cloned card would actually diverge on the wire."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(
        _task(
            status="blocked",
            issue_number=820,
            title="working and flawed",
            blocked_reason="upstream contract missing",
        )
    )

    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    working = _items(payload, "working")
    flawed = _items(payload, "flawed")
    assert len(working) == 1
    assert len(flawed) == 1

    wire = json.loads(json.dumps(payload))
    working_card = _items(wire, "working")[0]
    flawed_card = _items(wire, "flawed")[0]

    # One identity.
    assert working_card["id"] == flawed_card["id"]
    # No copy drift: the two appearances are byte-identical on the wire.
    assert working_card == flawed_card
    # Same spine, rung for rung.
    assert working_card["rungs"] == flawed_card["rungs"]
    # The card names both bands it appears in; its position stays "working".
    assert working_card["bands"] == ["working", "flawed"]
    assert working_card["band"] == "working"
    assert working_card["chain_position"] == "in_progress"

    # One thread, counted once — band memberships are not summed.
    assert payload["claim"]["text"].startswith("1 threads in motion")


# ---------------------------------------------------------------------------
# AC4 — forgotten needs a stall, never age alone
# ---------------------------------------------------------------------------


def test_forgotten_needs_stall_not_age(tmp_path: Path) -> None:
    """Decision Q1: forgotten = age **and** no movement in the thread's own
    authority. Each conjunct alone leaves the thread in progress, so the
    forgotten band can never become a seniority list."""
    db_path, store = _make_store(tmp_path)
    old = _days_ago(FORGOTTEN_STALL_DAYS + 46)

    # A: old and silent in every authority -> forgotten.
    store.upsert_task(
        _task(status="ready", issue_number=830, title="truly stalled", updated_at=old)
    )
    # B: exactly as old, but an open PR is live movement in GitHub.
    store.upsert_task(
        _task(status="ready", issue_number=831, title="old but moving", updated_at=old)
    )
    # C: no age at all.
    store.upsert_task(_task(status="ready", issue_number=832, title="fresh"))
    # D: old updated_at, but a recent dispatcher heartbeat.
    store.upsert_task(
        _task(
            status="ready",
            issue_number=833,
            title="old row, live heartbeat",
            updated_at=old,
            last_heartbeat_at=_iso(_now() - timedelta(hours=2)),
        )
    )
    # E: old and silent, and its governing PR is CLOSED (dead, not live) —
    # a closed pull sitting in the snapshot must never be treated as open
    # authority movement, or a genuinely abandoned thread could never
    # become forgotten just because a dead PR still matches its issue.
    store.upsert_task(
        _task(status="ready", issue_number=834, title="old, closed pr", updated_at=old)
    )

    snapshot = _snapshot(
        pulls={
            31: GithubPull(
                number=31,
                title="Governing-Issue: #831",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/31",
                head_sha="f" * 40,
                head_ref="pr-31",
                governing_issue=831,
            ),
            32: GithubPull(
                number=32,
                title="Governing-Issue: #834",
                state="closed",
                html_url=f"https://github.com/{REPO}/pull/32",
                head_sha="c" * 40,
                head_ref="pr-32",
                governing_issue=834,
            ),
        },
        checks={"f" * 40: "success"},
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(snapshot),
    )

    # Only threads that are both old *and* silent are forgotten — a closed
    # PR (E) does not exempt a thread the way an open one (B) does.
    assert _issues_in(payload, "forgotten") == {830, 834}
    assert _issues_in(payload, "working") == {831, 832, 833}

    closed_pr_thread = _item_by_issue(payload, 834)
    assert closed_pr_thread["chain_position"] == "forgotten"
    assert closed_pr_thread["position_evidence"]["open_authority_work"] is None

    # B is provably as old as A — age was present and deliberately insufficient.
    old_but_moving = _item_by_issue(payload, 831)
    assert old_but_moving["chain_position"] == "in_progress"
    assert old_but_moving["position_evidence"]["aged_past_threshold"] is True
    assert old_but_moving["position_evidence"]["open_authority_work"] == 31

    # A names both halves of the conjunct as its evidence.
    stalled = _item_by_issue(payload, 830)
    assert stalled["chain_position"] == "forgotten"
    assert stalled["position_evidence"]["aged_past_threshold"] is True
    assert stalled["position_evidence"]["open_authority_work"] is None
    assert stalled["position_evidence"]["stall_threshold_days"] == FORGOTTEN_STALL_DAYS
    # why_now is the gate's own phrasing, not an age number.
    assert stalled["why_now"].startswith("stalled without closure")

    # C is not aged; D's heartbeat is the dispatcher's own movement signal.
    assert _item_by_issue(payload, 832)["position_evidence"]["aged_past_threshold"] is False
    assert _item_by_issue(payload, 833)["position_evidence"]["aged_past_threshold"] is False


def test_stale_epic_exempt_when_epic_has_open_pr(tmp_path: Path) -> None:
    """`stale_epic_with_open_children` must agree with `derive_position` about
    what counts as movement: an epic with a live open PR against it is not
    stalled, even if its dispatcher row's own timestamps are old — a card
    must never carry `chain_position: in_progress` (from the open PR) and
    the "no movement in the window" flaw for the same reason at once."""
    db_path, store = _make_store(tmp_path)
    stale_stamp = _days_ago(FORGOTTEN_STALL_DAYS + 16)
    store.upsert_task(
        _task(
            status="ready",
            issue_number=907,
            title="epic with a live pr",
            updated_at=stale_stamp,
        )
    )

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root, epic_issue=907, child_issue=908, spec_dir_name="LIVE_EPIC")

    snapshot = _snapshot(
        issues={
            908: GithubIssue(
                number=908,
                title="open child",
                state="open",
                html_url=f"https://github.com/{REPO}/issues/908",
            ),
        },
        pulls={
            90: GithubPull(
                number=90,
                title="Governing-Issue: #907",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/90",
                head_sha="9" * 40,
                head_ref="pr-90",
                governing_issue=907,
            )
        },
        checks={"9" * 40: "success"},
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(snapshot),
        **_docs_kwargs(docs_root),
    )

    item = _item_by_issue(payload, 907)
    assert item["chain_position"] == "in_progress"
    assert "stale_epic_with_open_children" not in _flaw_names(item)


# ---------------------------------------------------------------------------
# AC5 — ordering within a band only; never hides
# ---------------------------------------------------------------------------


def test_ordering_never_crosses_bands_or_hides(tmp_path: Path) -> None:
    """EXT-7 / ADR-0057 A1: the risk meter orders inside one band, caps at four
    ticks, and neither promotes a card into another band nor removes one."""
    db_path, store = _make_store(tmp_path)
    old = _days_ago(FORGOTTEN_STALL_DAYS + 6)

    # working, four flaws: blocked + expired lease + PR without CI + a pushed
    # branch with no PR of its own.
    store.upsert_task(
        _task(
            status="blocked",
            issue_number=950,
            title="four flaws",
            blocked_reason="needs a decision",
            claimed_by="agent-y",
            lease_id="lease-950",
            lease_expires_at=_days_ago(3),
            linked_pr="90",
        )
    )
    # working, zero flaws.
    store.upsert_task(_task(status="in_progress", issue_number=951, title="clean"))
    # forgotten, one flaw — more flaws than the clean working card, and it must
    # still stay in its own band.
    store.upsert_task(
        _task(
            status="blocked",
            issue_number=952,
            title="forgotten and flawed",
            blocked_reason="nobody picked this up",
            updated_at=old,
        )
    )

    snapshot = _snapshot(
        pulls={
            90: GithubPull(
                number=90,
                title="four flaws",
                state="open",
                html_url=f"https://github.com/{REPO}/pull/90",
                head_sha="c" * 40,
                head_ref="pr-90",
                governing_issue=950,
            )
        },
        branches=("pr-90", "issue-950-old-attempt"),
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(snapshot),
    )

    # -- nothing hidden: every stored thread is in exactly one position band --
    position_bands = ("working", "done", "forgotten", "needs_you")
    appearances: list[int] = []
    for key in position_bands:
        appearances.extend(_issues_in(payload, key))
    assert sorted(appearances) == [950, 951, 952]
    assert payload["unclassified"] == []

    # -- the meter caps at four and turns destructive only at the cap --------
    four_flaw = _item_by_issue(payload, 950)
    assert len(four_flaw["flaws"]) >= RISK_MAX_TICKS
    assert four_flaw["risk_meter"] == {
        "ticks": RISK_MAX_TICKS,
        "max_ticks": RISK_MAX_TICKS,
        "tone": "destructive",
    }
    assert _item_by_issue(payload, 951)["risk_meter"]["tone"] is None
    assert _item_by_issue(payload, 952)["risk_meter"]["tone"] == "amber"

    # -- ordering is within-band: ticks are non-increasing inside each band --
    for band in payload["bands"]:
        ticks = [item["risk_meter"]["ticks"] for item in band["items"]]
        assert ticks == sorted(ticks, reverse=True), band["key"]
        assert band["count"] == len(band["items"])

    # -- ordering never crosses a band: the 1-tick forgotten card is NOT
    #    hoisted above the 0-tick working card into the working band ---------
    assert _issues_in(payload, "working") == {950, 951}
    assert _issues_in(payload, "forgotten") == {952}
    assert [i["issue_number"] for i in _items(payload, "working")] == [950, 951]

    # -- the contract is stated on the payload, so no frontend may reread the
    #    meter as a ranking (ADR-0057 A1) ---------------------------------
    ordering = payload["within_band_ordering"]
    assert ordering["applied"] is True
    joined = " ".join(ordering["never"]).lower()
    assert "across bands" in joined
    assert "hiding" in joined
    assert "selection" in joined


# ---------------------------------------------------------------------------
# AC6 — unread flaw planes named in the flaws band header
# ---------------------------------------------------------------------------


def test_unread_flaw_planes_named(tmp_path: Path) -> None:
    """Predicates whose plane this capability does not read at all are named in
    the flaws band header — absence made visible, never silently omitted."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=960, title="a thread"))

    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    header = _band(payload, "flawed")["header"]
    named = {entry["predicate"]: entry for entry in header["unread"]}
    assert named.keys() == {entry["predicate"] for entry in UNREAD_FLAW_PREDICATES}
    assert named["unpushed_local_worktree"]["plane"] == "git working trees"
    assert named["unlanded_session_insight"]["plane"] == "session records"
    assert named["closed_issue_without_owner_doc_receipt"]["plane"] == "issue comments"
    for entry in named.values():
        assert entry["reason"]

    # The planes behind those predicates are also named at payload level, so
    # the surface's own "planes not read" line stays true.
    assert {"git", "session-records", "issue-comments"} <= set(payload["unread_planes"])

    # The header is structural: it must still name the unread planes when the
    # dispatcher store is dead and nothing can be counted at all.
    refused = build_registry(
        db_path=tmp_path / "nowhere" / "dispatcher.sqlite3",
        deploy_receipt_dir=tmp_path / "deploys",
    )
    assert refused["claim"]["kind"] == "refused"
    refused_header = _band(refused, "flawed")["header"]
    assert {entry["predicate"] for entry in refused_header["unread"]} == named.keys()
    assert _band(refused, "done")["tried_tier"]["reserved"] is True


# ---------------------------------------------------------------------------
# AC7 — stale source ambers rungs and withdraws the counts it owns
# ---------------------------------------------------------------------------


def test_stale_source_ambers_rungs_and_withdraws_counts(tmp_path: Path) -> None:
    """EXT-3's third pill state, enacted: a source that read fine but is older
    than the threshold turns its dependent rungs amber and has the counts it
    owns withdrawn — while every card it backs still renders."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="in_progress", issue_number=808, title="child"))

    docs_root = tmp_path / "docs"
    _write_docs_fixture(docs_root, epic_issue=807, child_issue=808)
    # The docs plane's watermark is the newest mtime among the files it reads,
    # so ageing the fixture is the real-world way this source goes stale.
    stale_epoch = (_now() - timedelta(days=SOURCE_STALE_AFTER_DAYS + 23)).timestamp()
    for path in docs_root.rglob("*"):
        if path.is_file():
            os.utime(path, (stale_epoch, stale_epoch))

    stale_github = _snapshot(
        read_at=_iso(_now() - timedelta(days=SOURCE_STALE_AFTER_DAYS + 9)),
        issues={
            808: GithubIssue(
                number=808,
                title="child",
                state="open",
                html_url=f"https://github.com/{REPO}/issues/808",
            )
        },
    )

    payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(stale_github),
        **_docs_kwargs(docs_root),
    )

    # -- the pill states themselves ----------------------------------------
    docs_source = _source(payload, "docs-frontmatter")
    assert docs_source["state"] == "stale"
    # A stale pill must keep naming the instant it actually read.
    assert docs_source["last_successful_read"] is not None
    assert docs_source["stale_after_days"] == SOURCE_STALE_AFTER_DAYS
    assert _source(payload, "github-live")["state"] == "stale"
    # A source read at render time can never be stale — and must not be
    # collateral damage from an unrelated stale one.
    assert _source(payload, "dispatcher-store")["state"] == "fresh"

    # -- dependent rungs render amber, naming the source that went stale ----
    item = _item_by_issue(payload, 808)
    rungs = {rung["name"]: rung for rung in item["rungs"]}
    assert rungs["capability"]["class"] == "amber"
    assert rungs["capability"]["stale_source"] == "docs-frontmatter"
    assert rungs["epic"]["class"] == "amber"
    assert rungs["epic"]["stale_source"] == "docs-frontmatter"
    # A rung proven from a *fresh* source is untouched by an unrelated stale one.
    assert rungs["slice"]["class"] == "proven"
    assert "stale_source" not in rungs["slice"]

    # -- the counts those sources own are withdrawn, not shown whole --------
    assert payload["capability_lanes"] == {"countable": False, "lanes": None}
    assert payload["github"]["countable"] is False
    assert payload["github"]["open_issues"] is None
    withdrawn = {entry["source"] for entry in payload["withdrawn_counts"]}
    assert withdrawn == {"github-live", "docs-frontmatter"}

    # -- withdrawing a count never hides a card ----------------------------
    assert _issues_in(payload, "working") == {808}
    assert _band(payload, "working")["countable"] is True
    assert _band(payload, "working")["count"] == 1

    # -- predicates depending on a stale plane are not evaluated, not fired --
    unevaluated = {
        entry["predicate"] for entry in _band(payload, "flawed")["header"]["not_evaluated"]
    }
    assert "stale_epic_with_open_children" in unevaluated
    assert "pushed_branch_without_pr" in unevaluated

    # -- and a fresh-everything control run proves the threshold is what moved
    fresh_epoch = _now().timestamp()
    for path in docs_root.rglob("*"):
        if path.is_file():
            os.utime(path, (fresh_epoch, fresh_epoch))
    control = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(_snapshot(issues=stale_github.issues)),
        **_docs_kwargs(docs_root),
    )
    assert _source(control, "docs-frontmatter")["state"] == "fresh"
    assert control["capability_lanes"]["countable"] is True
    assert control["withdrawn_counts"] == []
    control_rungs = {r["name"]: r for r in _item_by_issue(control, 808)["rungs"]}
    assert control_rungs["capability"]["class"] == "proven"


def test_delivered_why_now_does_not_overclaim_unevaluated_receipt(tmp_path: Path) -> None:
    """A delivered thread whose verification-runs source could not be read
    must not claim "delivered with a terminal verification receipt" — that
    claims evidence the render never actually saw, the same overclaim class
    as showing a zero over a dead source."""
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="completed", issue_number=920, title="delivered"))

    # Drop verification_runs entirely so the source degrades to unavailable
    # while dispatcher-store itself stays perfectly readable.
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS verification_runs")

    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    assert _source(payload, "verification-runs")["state"] == "empty"
    header = _band(payload, "flawed")["header"]
    assert any(
        entry["predicate"] == "delivered_without_verification_receipt"
        for entry in header["not_evaluated"]
    )
    item = _item_by_issue(payload, 920)
    assert item["chain_position"] == "delivered"
    assert "verification-runs source could not be read" in item["why_now"]
    assert "terminal verification receipt" not in item["why_now"]


# ---------------------------------------------------------------------------
# Degradation boundary — the #4451 review class of defect
# ---------------------------------------------------------------------------


def test_new_reads_and_predicates_degrade_instead_of_crashing(tmp_path: Path) -> None:
    """Everything this slice added degrades to a refusal, never an exception.

    Two real failure modes, not hypotheticals:

    1. the extended ``dispatcher_tasks`` SELECT (``lease_id`` /
       ``last_heartbeat_at``) meeting an older store that predates those
       columns — SQLite raises ``OperationalError`` on the missing column;
    2. a plane snapshot carrying an unexpected value shape, which a predicate
       would otherwise propagate straight out of ``build_registry``.

    Either must leave the whole registry standing, with the failure attributed
    to the source that actually failed.
    """
    # -- 1. an older dispatcher store without the new columns ---------------
    legacy_db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(legacy_db) as conn:
        conn.execute(
            "CREATE TABLE dispatcher_tasks ("
            " task_id TEXT PRIMARY KEY, issue_number INTEGER, title TEXT,"
            " status TEXT, priority TEXT, repo TEXT, claimed_by TEXT,"
            " lease_expires_at TEXT, linked_pr TEXT, blocked_reason TEXT,"
            " sync_state TEXT, created_at TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO dispatcher_tasks (task_id, issue_number, title, status,"
            " priority, repo, created_at, updated_at)"
            " VALUES ('t1', 1, 'legacy row', 'ready', 'med', ?, ?, ?)",
            (REPO, _iso(_now()), _iso(_now())),
        )

    payload = build_registry(
        db_path=legacy_db, deploy_receipt_dir=tmp_path / "deploys"
    )
    dispatcher_source = _source(payload, "dispatcher-store")
    assert dispatcher_source["state"] == "unavailable"
    assert "read failed" in dispatcher_source["detail"]
    assert payload["claim"]["kind"] == "refused"
    for band in payload["bands"]:
        assert band["countable"] is False
        assert band["count"] is None

    # -- 2. a malformed snapshot shape inside a predicate --------------------
    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=970, title="thread"))

    # `branches` carrying a non-string makes the branch matcher raise TypeError.
    malformed = _snapshot(branches=(None, "issue-970-wip"))

    malformed_payload = build_registry(
        db_path=db_path,
        deploy_receipt_dir=tmp_path / "deploys",
        github_repo=REPO,
        github_reader=_reader(malformed),
    )
    # The registry stands; the predicate simply did not fire.
    assert malformed_payload["claim"]["kind"] == "counted"
    assert _issues_in(malformed_payload, "working") == {970}
    assert _flaw_names(_item_by_issue(malformed_payload, 970)) == set()


def test_one_threads_derivation_failure_does_not_crash_the_render(
    tmp_path: Path, monkeypatch
) -> None:
    """A structural defense-in-depth guarantee, not just a happy-path proof:
    if chain-position derivation itself ever raises for one thread (a bug in
    a future edit to this module, not a source-read failure), the whole
    render must still stand — that thread renders unclassified instead of
    taking every other thread down with it."""
    import app.builderops.cockpit_registry as cockpit_registry

    db_path, store = _make_store(tmp_path)
    store.upsert_task(_task(status="ready", issue_number=950, title="poisoned"))
    store.upsert_task(_task(status="ready", issue_number=951, title="healthy"))

    real_derive_position = cockpit_registry.derive_position

    def _poisoned_derive_position(task, **kwargs):
        if task.get("issue_number") == 950:
            raise RuntimeError("synthetic derivation bug")
        return real_derive_position(task, **kwargs)

    monkeypatch.setattr(cockpit_registry, "derive_position", _poisoned_derive_position)

    payload = build_registry(db_path=db_path, deploy_receipt_dir=tmp_path / "deploys")

    assert payload["claim"]["kind"] == "counted"
    unclassified = {entry["id"]: entry for entry in payload["unclassified"]}
    assert len(unclassified) == 1
    (reason,) = [entry["reason"] for entry in unclassified.values()]
    assert "synthetic derivation bug" in reason
    # The other thread is entirely unaffected.
    assert _issues_in(payload, "working") == {951}
