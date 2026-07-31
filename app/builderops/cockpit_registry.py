"""Read-time join for the BuilderOps cockpit registry.

The cockpit is a projection over existing builder authorities — the dispatcher
task store, verification runs, and deploy receipts. It owns no plane, no queue,
no register, and no decision right. Everything here is recomputed on every call;
nothing survives a reload.

Honesty rules this module enforces (owner doc: docs/BUILDEROPS_COCKPIT/README.md):

- Band derivation is fail-closed: a thread whose **chain position** cannot be
  computed lands in ``unclassified``, never silently in a band
  (BOPS-COCKPIT-04, #4452 — this replaced the earlier status-word mapping).
- A view that cannot name per-source freshness must not claim emptiness: when a
  source read fails, the claim is refused and bands owned by that source report
  ``countable: false`` instead of zero. A source that is readable but *stale*
  turns its dependent rungs amber and has the counts it owns withdrawn.
- Evidence rungs classify by key class, not content quality: only DB-keyed or
  CI-forced edges are ``proven``. Rungs with no machine-readable object in v1
  (intention, capability, epic, tried-by-owner) render ``absent`` — visible
  absence is the point.
- One identity, many appearances: a thread holds exactly one position band and
  additionally appears in the flaws band when a predicate fires. The flaws band
  holds the same object, never a copy.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.builderops.cockpit_chain import (
    RUNG_SOURCE,
    SOURCE_STALE_AFTER_DAYS,
    TRIED_TIER_REASON,
    ThreadContext,
    amber_if_stale,
    derive_position,
    evaluable_predicates,
    evaluate_flaws,
    flaws_band_header,
    order_within_band,
    risk_meter,
    stale_source_names,
    why_now,
)
from app.builderops.cockpit_docs_plane import (
    DocsPlaneSnapshot,
    build_lanes,
    classify_capability,
    classify_epic,
    read_docs_plane,
    unlinked_docs_threads,
)
from app.builderops.cockpit_github_plane import (
    GithubLiveSnapshot,
    GithubReader,
    default_github_reader,
    fetch_github_live,
)

__all__ = [
    "BANDS",
    "RUNG_ORDER",
    "UNREAD_PLANES",
    "build_registry",
]

# Band keys in locked document order. The needs-you band is last by design:
# it is a band inside the register, not the front page.
BANDS: tuple[tuple[str, str], ...] = (
    ("working", "What are we working on?"),
    ("done", "What is done?"),
    ("flawed", "What has flaws?"),
    ("forgotten", "What is forgotten?"),
    ("needs_you", "Needs you"),
)

# Band membership is derived in `app/builderops/cockpit_chain.py` from the
# thread's *chain position*, not from its dispatcher status word
# (BOPS-COCKPIT-04, #4452). The status word is one input among several
# (movement timestamps, lease expiry, live PR existence); the mapping table
# that used to live here is gone, because "ready" is not "forgotten" — a fresh
# unclaimed ready issue is in progress, and forgotten requires a stall.
_NEEDS_HUMAN_LABEL = "agent:needs-human"

# Locked rung order for the evidence spine.
RUNG_ORDER: tuple[str, ...] = (
    "intention",
    "capability",
    "epic",
    "slice",
    "pr",
    "ci_sha",
    "receipt",
    "tried",
)

# Planes the v1 join deliberately does not read. Named so their absence is
# visible instead of implied. github-live moved out of this tuple in
# BOPS-COCKPIT-03 (#4450); docs-frontmatter moved out in BOPS-COCKPIT-05
# (#4451): both are now named, per-render read sources. ckm-projection stays
# unread by design (ADR-0057: CKM is a lens, never spine — it must never
# become a fourth join input here).
# BOPS-COCKPIT-04 (#4452) names two further planes it does not read, because
# each carries a deficiency predicate the flaws band would otherwise appear to
# cover: session records and issue comments (see
# `cockpit_chain.UNREAD_FLAW_PREDICATES`, which names the predicate each one
# blocks).
UNREAD_PLANES: tuple[str, ...] = (
    "ckm-projection",
    "git",
    "session-records",
    "issue-comments",
)

_DEPLOY_CHANNELS: tuple[str, ...] = ("dev", "test", "prod")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class _SourceRead:
    # "stale" is the third pill state EXT-3 accepted and #4452 enacts: a
    # readable source whose own watermark is older than
    # SOURCE_STALE_AFTER_DAYS. It is applied after every read completes (see
    # `stale_source_names`), and never rewrites `last_successful_read` — the
    # pill must keep naming the instant it actually read.
    name: str
    state: str  # "fresh" | "stale" | "empty" | "unavailable"
    last_successful_read: str | None
    detail: str
    # EXT-8: an optional-by-design plane whose enabling config is simply absent
    # is not a broken source. `configured` separates the two so the surface can
    # render "never turned on" calmly while a genuinely dead source stays loud.
    # It never affects `state`, which stays "unavailable" either way — an
    # unconfigured plane still owns no countable facts.
    configured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "last_successful_read": self.last_successful_read,
            "detail": self.detail,
            "stale_after_days": SOURCE_STALE_AFTER_DAYS,
            "configured": self.configured,
        }


@dataclass
class _Sources:
    reads: list[_SourceRead] = field(default_factory=list)

    def add(self, read: _SourceRead) -> None:
        self.reads.append(read)

    def state_of(self, name: str) -> str:
        for read in self.reads:
            if read.name == name:
                return read.state
        return "unavailable"


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    """Open the dispatcher DB strictly read-only.

    ``sqlite3.connect(path)`` would create a missing file, which would turn a
    dead source into a fabricated empty one — the exact failure mode the
    cockpit exists to refuse.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_tasks(db_path: Path, sources: _Sources) -> list[dict[str, Any]] | None:
    if not db_path.exists():
        sources.add(
            _SourceRead(
                name="dispatcher-store",
                state="unavailable",
                last_successful_read=None,
                detail=f"database not found at {db_path.name}",
            )
        )
        return None
    try:
        with _read_only_connection(db_path) as conn:
            # lease_id / last_heartbeat_at joined in by BOPS-COCKPIT-04
            # (#4452): the expired-lease flaw predicate needs the lease's own
            # id as evidence, and the forgotten stall test needs the heartbeat
            # as a second movement timestamp alongside updated_at.
            rows = conn.execute(
                "SELECT task_id, issue_number, title, status, priority, repo,"
                " claimed_by, lease_id, lease_expires_at, last_heartbeat_at,"
                " linked_pr, blocked_reason,"
                " sync_state, created_at, updated_at"
                " FROM dispatcher_tasks WHERE status != '_meta'"
                " ORDER BY updated_at DESC, created_at DESC"
            ).fetchall()
    except sqlite3.Error as exc:
        sources.add(
            _SourceRead(
                name="dispatcher-store",
                state="unavailable",
                last_successful_read=None,
                detail=f"read failed: {exc}",
            )
        )
        return None
    sources.add(
        _SourceRead(
            name="dispatcher-store",
            state="fresh",
            last_successful_read=_utc_now(),
            detail=f"{len(rows)} tasks",
        )
    )
    return [dict(row) for row in rows]


def _read_verification_runs(
    db_path: Path, sources: _Sources
) -> dict[tuple[str, int], dict[str, Any]]:
    """Latest verification run per (repository, pr_number)."""
    if not db_path.exists():
        sources.add(
            _SourceRead(
                name="verification-runs",
                state="unavailable",
                last_successful_read=None,
                detail=f"database not found at {db_path.name}",
            )
        )
        return {}
    try:
        with _read_only_connection(db_path) as conn:
            table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table'"
                " AND name='verification_runs'"
            ).fetchone()
            if table is None:
                sources.add(
                    _SourceRead(
                        name="verification-runs",
                        state="empty",
                        last_successful_read=_utc_now(),
                        detail="no verification_runs table in this store",
                    )
                )
                return {}
            rows = conn.execute(
                "SELECT repository, pr_number, verified_head_sha,"
                " current_head_sha, status, stage, terminal_receipt_json,"
                " updated_at"
                " FROM verification_runs ORDER BY updated_at ASC"
            ).fetchall()
    except sqlite3.Error as exc:
        sources.add(
            _SourceRead(
                name="verification-runs",
                state="unavailable",
                last_successful_read=None,
                detail=f"read failed: {exc}",
            )
        )
        return {}
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:  # ascending order: later rows overwrite earlier ones
        latest[(row["repository"], row["pr_number"])] = dict(row)
    sources.add(
        _SourceRead(
            name="verification-runs",
            state="fresh",
            last_successful_read=_utc_now(),
            detail=f"{len(latest)} (repository, pr) pairs",
        )
    )
    return latest


def _read_deploy_receipts(
    deploy_dir: Path, sources: _Sources
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    errors: list[str] = []
    for channel in _DEPLOY_CHANNELS:
        path = deploy_dir / f"{channel}-latest.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        receipts.append(
            {
                "channel": payload.get("channel", channel),
                "sha": payload.get("sha"),
                "recorded_at": payload.get("recorded_at"),
            }
        )
    if errors:
        sources.add(
            _SourceRead(
                name="deploy-receipts",
                state="unavailable",
                last_successful_read=None,
                detail="; ".join(errors),
            )
        )
    elif receipts:
        sources.add(
            _SourceRead(
                name="deploy-receipts",
                state="fresh",
                last_successful_read=_utc_now(),
                detail=f"{len(receipts)} channel receipts",
            )
        )
    else:
        # A missing receipt file is the structural absence of a deploy, not a
        # dead source: nothing was ever recorded here.
        sources.add(
            _SourceRead(
                name="deploy-receipts",
                state="empty",
                last_successful_read=_utc_now(),
                detail="no channel receipts recorded",
            )
        )
    return receipts


def _read_github_live(
    repo: str | None,
    sources: _Sources,
    *,
    reader: GithubReader,
) -> GithubLiveSnapshot | None:
    """Read the live GitHub plane and fold it into the named source list.

    Mirrors the try/except-per-source shape of ``_read_tasks`` and
    ``_read_deploy_receipts``: the read itself never raises past this
    function (``fetch_github_live`` already catches every failure mode), and
    a failed/unconfigured read yields ``state="unavailable"`` — the refused
    claim, never a fabricated empty snapshot.

    The two refusals are distinguished by ``configured`` (EXT-8), not by
    ``state``: this plane is opt-in, so an absent ``repo`` means nobody asked
    for it, while a present ``repo`` whose read fails is a real outage. The
    flag mirrors ``fetch_github_live``'s own ``if not repo`` branch — the one
    place that "no repo configured" refusal is produced — rather than matching
    on its detail text.
    """
    result = fetch_github_live(repo, reader=reader)
    sources.add(
        _SourceRead(
            name="github-live",
            state=result.state,
            last_successful_read=result.last_successful_read,
            detail=result.detail,
            configured=bool(repo),
        )
    )
    return result.snapshot


def _read_docs_plane_snapshot(
    docs_root: Path | None,
    capabilities_yaml_path: Path | None,
    matrix_path: Path | None,
    sources: _Sources,
) -> DocsPlaneSnapshot | None:
    """Read the docs/capability plane and fold it into the named source list.

    Mirrors ``_read_github_live``'s shape: unconfigured (any path is ``None``)
    or a failed read both degrade to ``state="unavailable"`` — the refused
    claim, never a fabricated empty snapshot (BOPS-COCKPIT-05, #4451).
    """
    if docs_root is None or capabilities_yaml_path is None or matrix_path is None:
        sources.add(
            _SourceRead(
                name="docs-frontmatter",
                state="unavailable",
                last_successful_read=None,
                detail="docs plane not configured",
            )
        )
        return None
    result = read_docs_plane(
        capabilities_yaml_path=capabilities_yaml_path,
        matrix_path=matrix_path,
        docs_root=docs_root,
    )
    sources.add(
        _SourceRead(
            name="docs-frontmatter",
            state=result.state,
            last_successful_read=result.last_successful_read,
            detail=result.detail,
        )
    )
    return result.snapshot


def _sync_labels(sync_state: str | None) -> list[str]:
    if not sync_state:
        return []
    try:
        payload = json.loads(sync_state)
    except json.JSONDecodeError:
        return []
    labels = payload.get("labels")
    if isinstance(labels, list):
        return [str(label) for label in labels]
    return []


def _sync_url(sync_state: str | None) -> str | None:
    if not sync_state:
        return None
    try:
        payload = json.loads(sync_state)
    except json.JSONDecodeError:
        return None
    url = payload.get("url")
    return str(url) if url else None


def _sync_last_pull_at(sync_state: str | None) -> str | None:
    """The mirror's own watermark for its labels/url fields.

    Per decision Q5 (docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Q5), the
    dispatcher-store SQLite read instant is *not* a valid freshness claim for
    ``labels``/``url`` — those are populated by a separate, slower-moving
    sync mirror (``app/dispatcher/sync_github.py``). This reads the mirror's
    own ``sync_state.last_pull_at`` so the item can name its true source
    instead of borrowing the store's read time.
    """
    if not sync_state:
        return None
    try:
        payload = json.loads(sync_state)
    except json.JSONDecodeError:
        return None
    last_pull_at = payload.get("last_pull_at")
    return str(last_pull_at) if last_pull_at else None


def _pr_number_from_linked(linked_pr: str | None) -> int | None:
    if not linked_pr:
        return None
    try:
        return int(str(linked_pr).lstrip("#"))
    except ValueError:
        return None


def _snapshot_for_task(
    task: dict[str, Any],
    github_snapshot: GithubLiveSnapshot | None,
    github_repo: str | None,
) -> GithubLiveSnapshot | None:
    """The live snapshot, but only for a task in the repo that snapshot is of.

    One live read covers exactly one repository (``COCKPIT_GITHUB_REPO``),
    while the dispatcher store carries a ``repo`` per task. Issue and PR
    numbers are only unique *within* a repository, so joining them across
    repositories would let a task in repo B inherit rungs, out-links, and
    flaw evidence from a same-numbered PR in repo A. The existing
    verification-runs join is already keyed on ``(repo, pr_number)``; this
    applies the same key to the live plane.

    Gating here rather than inside each consumer is deliberate: every live
    consumer — ``_resolve_pr``, the rung classifier, and every flaw predicate
    reading ``github_snapshot`` — is covered by this one rule, so no future
    predicate can be added on the unscoped path by omission.

    Single-repo deployments (today's reality) see no behavior change: every
    task's ``repo`` equals the configured one.
    """
    if github_snapshot is None or github_repo is None:
        return github_snapshot
    return github_snapshot if str(task.get("repo") or "") == github_repo else None


def _resolve_pr(
    task: dict[str, Any],
    github_snapshot: GithubLiveSnapshot | None,
) -> tuple[int | None, Any | None]:
    """Resolve the governing PR number and its live pull, one precedence rule.

    Store-linked PR wins; otherwise a live governing-issue match. Both the
    rung classification and the authority out-link must agree on this same
    PR, or a card can render "PR #NN (live) proven" while its out-link still
    points at the plain issue (the drift #4450 review caught).
    """
    issue_number = task.get("issue_number")
    linked_pr = task.get("linked_pr")
    pr_number = _pr_number_from_linked(linked_pr)
    live_pull = None
    if not linked_pr and (
        github_snapshot is not None
        and issue_number is not None
        and (governing := github_snapshot.pulls_governing(int(issue_number)))
    ):
        live_pull = governing[0]
        pr_number = live_pull.number
    if live_pull is None and pr_number is not None and github_snapshot is not None:
        live_pull = github_snapshot.pulls.get(pr_number)
    return pr_number, live_pull


def _rung(name: str, cls: str, value: str | None = None) -> dict[str, Any]:
    return {"name": name, "class": cls, "value": value}


def _build_rungs(
    task: dict[str, Any],
    verification: dict[tuple[str, int], dict[str, Any]],
    github_snapshot: GithubLiveSnapshot | None = None,
    docs_snapshot: DocsPlaneSnapshot | None = None,
    stale_sources: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Classify the eight rungs for one task.

    Key classes: ``proven`` (DB-keyed, CI-forced, or docs-plane machine edge),
    ``derived`` (prose-only edge — epic rung only, BOPS-COCKPIT-05/#4451),
    ``amber`` (capability rung only: the docs plane was read but named no
    edge for this thread — freestanding, never guessed under a parent),
    ``absent`` (no object at that level in the system at all, or the docs
    plane itself was not configured/could not be read).

    BOPS-COCKPIT-03 (#4450): when a live GitHub read succeeded, ``pr`` and
    ``ci_sha`` can additionally be proven from live PR + check keys even when
    the dispatcher store has no ``linked_pr``/verification run for this task
    yet — a thread the owner already pushed a PR for should not read as
    "no PR" just because the dispatcher store has not caught up. When the
    live read failed or was not configured, ``github_snapshot`` is ``None``
    and this function behaves exactly as it did before #4450 — refusal never
    fabricates an upgrade. The same posture applies to ``docs_snapshot`` for
    the ``capability``/``epic`` rungs.

    BOPS-COCKPIT-04 (#4452): ``stale_sources`` names sources that read
    successfully but whose watermark is older than the staleness threshold.
    Every rung is ambered against *the source that actually produced its
    value* — a ``pr`` rung proven from the dispatcher store's own
    ``linked_pr`` is not ambered by a stale live-GitHub read, and vice versa.
    The downgrade is one-directional: ``absent`` never becomes anything else.
    """
    issue_number = task.get("issue_number")
    capability = classify_capability(issue_number, docs_snapshot)
    epic = classify_epic(issue_number, docs_snapshot)
    rungs: list[dict[str, Any]] = [
        _rung("intention", "absent"),
        amber_if_stale(capability["rung"], RUNG_SOURCE["capability"], stale_sources),
        amber_if_stale(epic["rung"], RUNG_SOURCE["epic"], stale_sources),
    ]
    repo = task.get("repo") or ""
    if issue_number:
        rungs.append(
            amber_if_stale(
                _rung("slice", "proven", f"{repo}#{issue_number}"),
                RUNG_SOURCE["slice"],
                stale_sources,
            )
        )
    else:
        rungs.append(_rung("slice", "absent"))

    linked_pr = task.get("linked_pr")
    pr_number, live_pull = _resolve_pr(task, github_snapshot)
    if linked_pr:
        rungs.append(
            amber_if_stale(
                _rung("pr", "proven", f"PR #{linked_pr}"),
                "dispatcher-store",
                stale_sources,
            )
        )
    elif live_pull is not None and pr_number is not None:
        rungs.append(
            amber_if_stale(
                _rung("pr", "proven", f"PR #{pr_number} (live)"),
                "github-live",
                stale_sources,
            )
        )
    else:
        rungs.append(_rung("pr", "absent"))

    run = verification.get((repo, pr_number)) if pr_number is not None else None
    live_check_state = (
        github_snapshot.check_state_for(live_pull.head_sha)
        if live_pull is not None and github_snapshot is not None
        else None
    )
    if run and run.get("verified_head_sha"):
        rungs.append(
            amber_if_stale(
                _rung("ci_sha", "proven", str(run["verified_head_sha"])[:12]),
                "verification-runs",
                stale_sources,
            )
        )
    elif live_check_state and live_pull is not None:
        rungs.append(
            amber_if_stale(
                _rung(
                    "ci_sha",
                    "proven",
                    f"{live_pull.head_sha[:12]} ({live_check_state}, live)",
                ),
                "github-live",
                stale_sources,
            )
        )
    elif (
        live_pull is not None
        and github_snapshot is not None
        and github_snapshot.check_read_failed(live_pull.head_sha)
    ):
        # The check state for this SHA was not read, which is not the same
        # claim as "this SHA has no checks". Say so on the rung instead of
        # letting a failed read wear the same bare `absent` as a real absence.
        rungs.append(
            _rung(
                "ci_sha",
                "absent",
                f"{live_pull.head_sha[:12]} (check state unread: live read failed)",
            )
        )
    elif run:
        rungs.append(_rung("ci_sha", "absent", f"run {run.get('status', '?')}"))
    else:
        rungs.append(_rung("ci_sha", "absent"))

    if run and run.get("terminal_receipt_json"):
        rungs.append(
            amber_if_stale(
                _rung("receipt", "proven", str(run.get("updated_at") or "")),
                RUNG_SOURCE["receipt"],
                stale_sources,
            )
        )
    else:
        rungs.append(_rung("receipt", "absent"))

    rungs.append(_rung("tried", "absent"))
    return rungs


def _build_item(
    task: dict[str, Any],
    band: str,
    position: Any,
    verification: dict[tuple[str, int], dict[str, Any]],
    github_snapshot: GithubLiveSnapshot | None = None,
    docs_snapshot: DocsPlaneSnapshot | None = None,
    stale_sources: frozenset[str] = frozenset(),
    evaluated_predicates: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    labels = _sync_labels(task.get("sync_state"))
    mirror_url = _sync_url(task.get("sync_state"))
    mirror_watermark = _sync_last_pull_at(task.get("sync_state"))
    issue_number = task.get("issue_number")
    linked_pr = task.get("linked_pr")
    # Same precedence _build_rungs uses for its "PR #NN (live) proven" rung —
    # a card whose rung claims a live PR match must out-link to that same PR,
    # not fall back to the plain issue (the drift #4450 review caught).
    pr_number, live_pull = _resolve_pr(task, github_snapshot)

    # BOPS-COCKPIT-04 (#4452): deficiency predicates over the joined planes.
    # Every predicate is a pure function of already-fetched snapshots, so no
    # predicate can perform I/O, fail a read, or raise past this call.
    repo = task.get("repo") or ""
    flaws = evaluate_flaws(
        ThreadContext(
            task=task,
            repo=repo,
            issue_number=issue_number,
            position=position.position,
            pr_number=pr_number,
            live_pull=live_pull,
            verification_run=(
                verification.get((repo, pr_number)) if pr_number is not None else None
            ),
            github_snapshot=github_snapshot,
            docs_snapshot=docs_snapshot,
            now=now or datetime.now(timezone.utc),
        ),
        evaluated_predicates or [],
    )
    # The bands this one identity appears in: its position band always, plus
    # the flaws band when a predicate fired. Same object, never a copy.
    appears_in = [band] + (["flawed"] if flaws else [])

    # AC3 (#4450): every card carries its authority out-link from the live
    # GitHub read, independent of the sync mirror's `url` field (audit F9,
    # historically empty in production). The live link wins when a read
    # succeeded and found a match; otherwise fall back to whatever the mirror
    # carries so a live-read failure never removes an out-link that already
    # existed.
    live_link = (
        github_snapshot.authority_link(issue_number=issue_number, pr_number=pr_number)
        if github_snapshot is not None
        else None
    )
    links = [live_link] if live_link else ([mirror_url] if mirror_url else [])

    sources = ["dispatcher-store", "verification-runs"]
    if github_snapshot is not None:
        sources.append("github-live")
    if docs_snapshot is not None:
        sources.append("docs-frontmatter")

    capability = classify_capability(issue_number, docs_snapshot)
    capability_lane = (
        {
            "key": capability["lane_key"],
            "name": capability["lane_name"],
            "rung": capability["rung"]["class"],
        }
        if capability["lane_key"] is not None
        else None
    )

    return {
        "id": task["task_id"],
        "issue_number": issue_number,
        "repo": task.get("repo"),
        "title": task.get("title"),
        "band": band,
        "status": task.get("status"),
        "priority": task.get("priority"),
        "claimed_by": task.get("claimed_by"),
        "linked_pr": linked_pr,
        "labels": labels,
        # BOPS-COCKPIT-03 (#4450, decision Q5): labels/url are mirror-derived
        # fields; they name the mirror's own `sync_state.last_pull_at`
        # watermark here, never the dispatcher-store SQLite read instant the
        # `dispatcher-store` source pill reports.
        "mirror_watermark": mirror_watermark,
        "why_now": why_now(task, position, band, flaws, evaluated_predicates),
        "links": links,
        "rungs": _build_rungs(
            task, verification, github_snapshot, docs_snapshot, stale_sources
        ),
        "sources": sources,
        "capability_lane": capability_lane,
        # Chain position (#4452): the derived position and the evidence that
        # produced it, so the card can state *why* it sits where it sits.
        "chain_position": position.position,
        "position_evidence": position.evidence,
        # Populated only when the position is unresolvable (e.g. a
        # needs_you-labelled thread whose fail-closed position could not
        # be derived) — the card's own stated reason, not just a null.
        "position_unresolved_reason": position.unresolved_reason,
        "bands": appears_in,
        "flaws": flaws,
        "risk_meter": risk_meter(flaws),
        "updated_at": task.get("updated_at"),
    }


def _github_facts(
    sources: _Sources, github_snapshot: GithubLiveSnapshot | None
) -> dict[str, Any]:
    """The github-live source's own counted facts.

    AC1 (#4450): these facts are owned by the ``github-live`` source alone —
    on a refused read they must report ``countable: False`` with every count
    ``None``, never ``0``. A real zero (an authenticated read that legitimately
    found no open issues/PRs) is only reachable through the success branch.
    """
    read_state = sources.state_of("github-live")
    if github_snapshot is None or read_state != "fresh":
        return {
            "countable": False,
            "open_issues": None,
            "open_prs": None,
            "branches": None,
        }
    return {
        "countable": True,
        "open_issues": len(github_snapshot.issues),
        "open_prs": len(github_snapshot.pulls),
        "branches": len(github_snapshot.branches),
    }


def _build_unsynced_threads(
    tasks: list[dict[str, Any]] | None,
    github_snapshot: GithubLiveSnapshot | None,
    github_repo: str | None = None,
) -> list[dict[str, Any]]:
    """PRs visible in GitHub with no matching dispatcher task.

    AC2 (#4450): "threads with a branch/PR but no dispatcher task appear
    rather than being invisible." Matched against the dispatcher store by PR
    number (``linked_pr``) and by the PR's own governing-issue number
    (``issue_number``); a live PR that matches neither is a thread the owner
    already pushed a branch/PR for that the dispatcher-store side has not
    caught up on — surfaced as a card, not silently dropped. When the
    dispatcher store itself could not be read (``tasks is None``), there is
    nothing to cross this against, so every live PR is honestly unsynced
    rather than guessed to already be tracked. Bounded to PRs (not raw open
    issues): "branch/PR" is a code artifact, distinct from the much larger
    set of untriaged open issues that BOPS-COCKPIT-04 will classify.
    """
    if github_snapshot is None:
        return []
    known_pr_numbers: set[int] = set()
    known_issue_numbers: set[int] = set()
    for task in tasks or []:
        # Only a task in the repo this snapshot describes can vouch for one of
        # its PRs. Without this, a same-numbered task in another repository
        # would suppress a genuinely-unsynced live PR as "already known" — the
        # silent direction of the same collision `_snapshot_for_task` guards.
        if _snapshot_for_task(task, github_snapshot, github_repo) is None:
            continue
        pr_number = _pr_number_from_linked(task.get("linked_pr"))
        if pr_number is not None:
            known_pr_numbers.add(pr_number)
        issue_number = task.get("issue_number")
        if issue_number is not None:
            known_issue_numbers.add(int(issue_number))

    unsynced: list[dict[str, Any]] = []
    for pull in github_snapshot.pulls.values():
        if pull.number in known_pr_numbers:
            continue
        if pull.governing_issue is not None and pull.governing_issue in known_issue_numbers:
            continue
        unsynced.append(
            {
                "id": f"github-live-pr-{pull.number}",
                "kind": "pr",
                "pr_number": pull.number,
                "issue_number": pull.governing_issue,
                "title": pull.title,
                "why_now": "open in GitHub with a branch/PR;"
                " no dispatcher task tracks it yet",
                "links": [pull.html_url] if pull.html_url else [],
                "sources": ["github-live"],
            }
        )
    return unsynced


def build_registry(
    *,
    db_path: Path,
    deploy_receipt_dir: Path,
    github_repo: str | None = None,
    github_reader: GithubReader = default_github_reader,
    docs_root: Path | None = None,
    capabilities_yaml_path: Path | None = None,
    matrix_path: Path | None = None,
) -> dict[str, Any]:
    """Build the cockpit registry payload. Pure read; never writes anywhere.

    ``github_repo``/``github_reader`` are injection points for the live
    GitHub plane (BOPS-COCKPIT-03, #4450): tests pass a fake ``github_reader``
    so no test performs network I/O; ``github_repo`` carries no fallback to
    an ambient env var here (mirroring ``deploy_receipt_dir`` — the caller,
    ``app/api/routes/cockpit.py``, is solely responsible for resolving
    ``COCKPIT_GITHUB_REPO``), so a direct call with ``github_repo=None``
    always refuses, deterministically, with no environment dependence.
    ``docs_root``/``capabilities_yaml_path``/``matrix_path`` are the same kind
    of injection point for the docs/capability plane (BOPS-COCKPIT-05,
    #4451): all three default to ``None``, so a direct call with no docs
    plane configured always refuses that source too, deterministically —
    tests point them at a fixture tree under ``tmp_path`` rather than the
    live repo docs. Every call performs its own fresh read — decision Q5
    forbids any cache surviving across two ``build_registry`` calls.
    """
    sources = _Sources()
    tasks = _read_tasks(db_path, sources)
    verification = _read_verification_runs(db_path, sources)
    deployments = _read_deploy_receipts(deploy_receipt_dir, sources)
    github_snapshot = _read_github_live(github_repo, sources, reader=github_reader)
    docs_snapshot = _read_docs_plane_snapshot(
        docs_root, capabilities_yaml_path, matrix_path, sources
    )

    now = datetime.now(timezone.utc)
    # EXT-3's third pill state, enacted (#4452): flip readable-but-old sources
    # to "stale" before anything reads their state. Everything downstream —
    # rung colour, count withdrawal, predicate evaluability — keys off the
    # post-flip state, so a stale source degrades consistently everywhere
    # instead of ambering one surface and staying calm on another.
    stale_sources = stale_source_names(sources.reads, now=now)
    source_state = {read.name: read.state for read in sources.reads}
    # A predicate whose plane is not fresh is not evaluated at all: never
    # fired on absent evidence, never silently dropped. The header names it.
    evaluated_predicates, not_evaluated_predicates = evaluable_predicates(source_state)

    generated_at = _utc_now()
    bands: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []

    if tasks is None:
        # The band counts are owned by the dispatcher store. Without it the
        # only honest claim is a refusal — "cannot be counted", never zero.
        for key, question in BANDS:
            refused_band: dict[str, Any] = {
                "key": key,
                "question": question,
                "countable": False,
                "count": None,
                "items": [],
            }
            # The flaws header and the tried tier are structural, not counts:
            # they must still say what is unread and what is reserved even
            # when nothing can be counted at all.
            if key == "flawed":
                refused_band["header"] = flaws_band_header(
                    evaluated_predicates, not_evaluated_predicates
                )
            if key == "done":
                refused_band["tried_tier"] = {
                    "items": [],
                    "reserved": True,
                    "reason": TRIED_TIER_REASON,
                }
            bands.append(refused_band)
        claim = {
            "kind": "refused",
            "text": "I cannot say what is in motion: the dispatcher store"
            " could not be read.",
            "as_of": generated_at,
        }
    else:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in BANDS}
        for task in tasks:
            status = str(task.get("status") or "")
            try:
                labels = _sync_labels(task.get("sync_state"))
                # Scoped once per task, then used everywhere below: position
                # derivation, rungs, out-links, and flaw predicates all read
                # the same repo-checked snapshot.
                task_snapshot = _snapshot_for_task(task, github_snapshot, github_repo)
                _, live_pull = _resolve_pr(task, task_snapshot)
                position = derive_position(task, now=now, live_pull=live_pull)
                if _NEEDS_HUMAN_LABEL in labels:
                    # An explicit human-routing label is the owner's own
                    # authority speaking, not a derived claim, so it is not
                    # subject to the fail-closed position rule: it routes
                    # even when the chain position itself is unresolvable
                    # (the card still carries `chain_position: null` and
                    # its reason).
                    band = "needs_you"
                elif position.band is not None:
                    band = position.band
                else:
                    unclassified.append(
                        {
                            "id": task["task_id"],
                            "title": task.get("title"),
                            "status": status,
                            "reason": position.unresolved_reason
                            or f"status {status!r} has no chain position",
                        }
                    )
                    continue
                item = _build_item(
                    task,
                    band,
                    position,
                    verification,
                    task_snapshot,
                    docs_snapshot,
                    stale_sources,
                    evaluated_predicates,
                    now,
                )
            except Exception as exc:  # noqa: BLE001 - one thread's derivation
                # failure must never crash the whole render (the #4451-class
                # bug this exact pattern exists to prevent, applied per task
                # rather than per source): the thread renders as explicitly
                # unclassified instead of taking bands/tasks/everything down.
                unclassified.append(
                    {
                        "id": task.get("task_id"),
                        "title": task.get("title"),
                        "status": status,
                        "reason": f"chain-position derivation failed: {exc}",
                    }
                )
                continue
            grouped[band].append(item)
            # The flaws band is cross-cutting: a thread holds one position
            # band and additionally appears here when a predicate fired. The
            # *same object* goes in both lists — one identity, no copy drift.
            if item["flaws"] and band != "flawed":
                grouped["flawed"].append(item)
            all_items.append(item)
        # The band counts are owned by the dispatcher store, and the staleness
        # rule deliberately does not reach them: `_read_tasks` stamps its
        # watermark at the instant it reads, so `dispatcher-store` is either
        # fresh or unavailable and can never be stale. That matters beyond
        # bookkeeping — `countable: false` already means "no cards either" to
        # the delivered surface (`app/web/static/cockpit.js` renders no body
        # for an uncountable band), so emitting an uncountable band that still
        # carries items would hide cards, which is exactly what "withdraw the
        # count, never the card" forbids. Withdrawal therefore applies only to
        # counts owned by sources with a non-instant watermark: the docs
        # plane's lane grouping and the github-live facts.
        for key, question in BANDS:
            band_payload: dict[str, Any] = {
                "key": key,
                "question": question,
                "countable": True,
                "count": len(grouped[key]),
                # EXT-7: ordering applies strictly within this band's own item
                # list, so it structurally cannot move a card across bands.
                "items": order_within_band(grouped[key]),
            }
            if key == "flawed":
                band_payload["header"] = flaws_band_header(
                    evaluated_predicates, not_evaluated_predicates
                )
            if key == "done":
                # EXT-2 / decision Q3: the tried tier renders, is empty, and
                # says why. Delivered-never-tried is visible here as absence,
                # never as a red mark in the flaws band.
                band_payload["tried_tier"] = {
                    "items": [],
                    "reserved": True,
                    "reason": TRIED_TIER_REASON,
                }
            bands.append(band_payload)
        # Distinct threads, not the sum of band memberships: a thread in both
        # its position band and the flaws band is one thread, counted once.
        total = len(all_items)
        if total == 0 and not unclassified:
            claim = {
                "kind": "counted",
                "text": f"0 threads in motion as of {generated_at}."
                " Every source below carries its own read time.",
                "as_of": generated_at,
            }
        else:
            claim = {
                "kind": "counted",
                "text": f"{total} threads in motion as of {generated_at}.",
                "as_of": generated_at,
            }

    # BOPS-COCKPIT-05 (#4451): "countable": False + "lanes": None is the
    # refused claim, never an empty lane list. That refusal fires on either
    # of two independent failures: the docs plane itself is unreadable
    # (build_lanes returns None), or the dispatcher store is unreadable
    # (tasks is None) — in which case all_items is an artifact of nothing
    # being known, not a true empty set, so lanes must refuse too rather
    # than calmly reporting "0 lanes" next to the bands' own refusal above.
    #
    # #4452 adds a third: the docs plane read fine but is *stale*, so the lane
    # grouping it owns is withdrawn rather than shown whole (EXT-3's stale-
    # source rule). The lane cards themselves are not hidden — they simply
    # stop being counted, which is what "withdraw the numbers that source
    # owns" means.
    lanes = (
        build_lanes(all_items, docs_snapshot)
        if tasks is not None and "docs-frontmatter" not in stale_sources
        else None
    )

    # Only counts owned by a source that can actually go stale appear here —
    # see the band-count comment above for why `dispatcher-store` is absent.
    withdrawn_counts = [
        {"source": name, "counts": counts}
        for name, counts in (
            ("github-live", ["github.open_issues", "github.open_prs", "github.branches"]),
            ("docs-frontmatter", ["capability_lanes.lanes"]),
        )
        if name in stale_sources
    ]

    return {
        "authority": "read_time_join",
        "generated_at": generated_at,
        "claim": claim,
        "sources": [read.to_dict() for read in sources.reads],
        "unread_planes": list(UNREAD_PLANES),
        "bands": bands,
        "unclassified": unclassified,
        "deployments": deployments,
        "github": _github_facts(sources, github_snapshot),
        "unsynced_threads": _build_unsynced_threads(
            tasks, github_snapshot, github_repo
        ),
        "capability_lanes": {"countable": lanes is not None, "lanes": lanes},
        "docs_only_threads": unlinked_docs_threads(docs_snapshot),
        # The counts a stale source no longer backs. Named so the withdrawal
        # is visible on the surface instead of looking like a quiet zero.
        "withdrawn_counts": withdrawn_counts,
        # EXT-7's binding constraint, stated in the payload so a frontend
        # cannot reinterpret the risk meter as a ranking (ADR-0057 A1).
        "within_band_ordering": {
            "applied": True,
            "basis": "count of fired flaw predicates, capped at four ticks",
            "never": [
                "reordering across bands",
                "hiding, capping, or demoting a card",
                "selection, ranking, or filtering (ADR-0057 A1: a risk number"
                " is a signal to read, never a selection input)",
            ],
        },
    }
