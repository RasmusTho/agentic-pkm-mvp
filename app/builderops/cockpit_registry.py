"""Read-time join for the BuilderOps cockpit registry.

The cockpit is a projection over existing builder authorities — the dispatcher
task store, verification runs, and deploy receipts. It owns no plane, no queue,
no register, and no decision right. Everything here is recomputed on every call;
nothing survives a reload.

Honesty rules this module enforces (owner doc: docs/BUILDEROPS_COCKPIT/README.md):

- Band derivation is fail-closed: a task whose status has no band mapping lands
  in ``unclassified``, never silently in a band.
- A view that cannot name per-source freshness must not claim emptiness: when a
  source read fails, the claim is refused and bands owned by that source report
  ``countable: false`` instead of zero.
- Evidence rungs classify by key class, not content quality: only DB-keyed or
  CI-forced edges are ``proven``. Rungs with no machine-readable object in v1
  (intention, capability, epic, tried-by-owner) render ``absent`` — visible
  absence is the point.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.builderops.cockpit_github_plane import (
    GithubLiveSnapshot,
    GithubReader,
    default_github_reader,
    fetch_github_live,
)

__all__ = [
    "BANDS",
    "RUNG_ORDER",
    "STATUS_BAND",
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

# Dispatcher status -> band. Fail-closed: anything absent from this table is
# reported as unclassified, never guessed into a band.
STATUS_BAND: dict[str, str] = {
    "claimed": "working",
    "in_progress": "working",
    "review": "working",
    "completed": "done",
    "done": "done",
    "blocked": "flawed",
    "backlog": "forgotten",
    "ready": "forgotten",
}

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
# BOPS-COCKPIT-03 (#4450): it is now a named, per-render read source.
UNREAD_PLANES: tuple[str, ...] = (
    "docs-frontmatter",
    "ckm-projection",
    "git",
)

_DEPLOY_CHANNELS: tuple[str, ...] = ("dev", "test", "prod")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class _SourceRead:
    name: str
    state: str  # "fresh" | "empty" | "unavailable"
    last_successful_read: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "last_successful_read": self.last_successful_read,
            "detail": self.detail,
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
            rows = conn.execute(
                "SELECT task_id, issue_number, title, status, priority, repo,"
                " claimed_by, lease_expires_at, linked_pr, blocked_reason,"
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
    """
    result = fetch_github_live(repo, reader=reader)
    sources.add(
        _SourceRead(
            name="github-live",
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


def _rung(name: str, cls: str, value: str | None = None) -> dict[str, Any]:
    return {"name": name, "class": cls, "value": value}


def _build_rungs(
    task: dict[str, Any],
    verification: dict[tuple[str, int], dict[str, Any]],
    github_snapshot: GithubLiveSnapshot | None = None,
) -> list[dict[str, Any]]:
    """Classify the eight rungs for one task.

    Key classes: ``proven`` (DB-keyed or CI-forced edge), ``absent`` (no object
    at that level in the system). v1 has no prose-derived rungs; ``derived``
    appears once epic/capability edges are joined in a later slice.

    BOPS-COCKPIT-03 (#4450): when a live GitHub read succeeded, ``pr`` and
    ``ci_sha`` can additionally be proven from live PR + check keys even when
    the dispatcher store has no ``linked_pr``/verification run for this task
    yet — a thread the owner already pushed a PR for should not read as
    "no PR" just because the dispatcher store has not caught up. When the
    live read failed or was not configured, ``github_snapshot`` is ``None``
    and this function behaves exactly as it did before #4450 — refusal never
    fabricates an upgrade.
    """
    rungs: list[dict[str, Any]] = [
        _rung("intention", "absent"),
        _rung("capability", "absent"),
        _rung("epic", "absent"),
    ]
    repo = task.get("repo") or ""
    issue_number = task.get("issue_number")
    if issue_number:
        rungs.append(_rung("slice", "proven", f"{repo}#{issue_number}"))
    else:
        rungs.append(_rung("slice", "absent"))

    linked_pr = task.get("linked_pr")
    pr_number = _pr_number_from_linked(linked_pr)
    live_pull = None
    if linked_pr:
        rungs.append(_rung("pr", "proven", f"PR #{linked_pr}"))
    elif (
        github_snapshot is not None
        and issue_number is not None
        and (governing := github_snapshot.pulls_governing(int(issue_number)))
    ):
        live_pull = governing[0]
        pr_number = live_pull.number
        rungs.append(_rung("pr", "proven", f"PR #{live_pull.number} (live)"))
    else:
        rungs.append(_rung("pr", "absent"))

    if live_pull is None and pr_number is not None and github_snapshot is not None:
        live_pull = github_snapshot.pulls.get(pr_number)

    run = verification.get((repo, pr_number)) if pr_number is not None else None
    live_check_state = (
        github_snapshot.check_state_for(live_pull.head_sha)
        if live_pull is not None and github_snapshot is not None
        else None
    )
    if run and run.get("verified_head_sha"):
        rungs.append(_rung("ci_sha", "proven", str(run["verified_head_sha"])[:12]))
    elif live_check_state and live_pull is not None:
        rungs.append(
            _rung(
                "ci_sha",
                "proven",
                f"{live_pull.head_sha[:12]} ({live_check_state}, live)",
            )
        )
    elif run:
        rungs.append(_rung("ci_sha", "absent", f"run {run.get('status', '?')}"))
    else:
        rungs.append(_rung("ci_sha", "absent"))

    if run and run.get("terminal_receipt_json"):
        rungs.append(_rung("receipt", "proven", str(run.get("updated_at") or "")))
    else:
        rungs.append(_rung("receipt", "absent"))

    rungs.append(_rung("tried", "absent"))
    return rungs


def _why_now(task: dict[str, Any], band: str) -> str:
    """The gate's own wording, not a score."""
    status = task.get("status") or "?"
    if band == "flawed" and task.get("blocked_reason"):
        return f"blocked: {task['blocked_reason']}"
    if band == "working" and task.get("claimed_by"):
        return f"{status} · claimed by {task['claimed_by']}"
    if band == "forgotten":
        return f"{status} since {task.get('updated_at') or 'unknown'}"
    return status


def _build_item(
    task: dict[str, Any],
    band: str,
    verification: dict[tuple[str, int], dict[str, Any]],
    github_snapshot: GithubLiveSnapshot | None = None,
) -> dict[str, Any]:
    labels = _sync_labels(task.get("sync_state"))
    mirror_url = _sync_url(task.get("sync_state"))
    mirror_watermark = _sync_last_pull_at(task.get("sync_state"))
    issue_number = task.get("issue_number")
    linked_pr = task.get("linked_pr")
    pr_number = _pr_number_from_linked(linked_pr)

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
        "why_now": _why_now(task, band),
        "links": links,
        "rungs": _build_rungs(task, verification, github_snapshot),
        "sources": sources,
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
) -> dict[str, Any]:
    """Build the cockpit registry payload. Pure read; never writes anywhere.

    ``github_repo``/``github_reader`` are injection points for the live
    GitHub plane (BOPS-COCKPIT-03, #4450): tests pass a fake ``github_reader``
    so no test performs network I/O; ``github_repo`` carries no fallback to
    an ambient env var here (mirroring ``deploy_receipt_dir`` — the caller,
    ``app/api/routes/cockpit.py``, is solely responsible for resolving
    ``COCKPIT_GITHUB_REPO``), so a direct call with ``github_repo=None``
    always refuses, deterministically, with no environment dependence.
    Every call performs its own fresh read — decision Q5 forbids any cache
    surviving across two ``build_registry`` calls.
    """
    sources = _Sources()
    tasks = _read_tasks(db_path, sources)
    verification = _read_verification_runs(db_path, sources)
    deployments = _read_deploy_receipts(deploy_receipt_dir, sources)
    github_snapshot = _read_github_live(github_repo, sources, reader=github_reader)

    generated_at = _utc_now()
    bands: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []

    if tasks is None:
        # The band counts are owned by the dispatcher store. Without it the
        # only honest claim is a refusal — "cannot be counted", never zero.
        for key, question in BANDS:
            bands.append(
                {
                    "key": key,
                    "question": question,
                    "countable": False,
                    "count": None,
                    "items": [],
                }
            )
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
            labels = _sync_labels(task.get("sync_state"))
            if _NEEDS_HUMAN_LABEL in labels:
                band = "needs_you"
            elif status in STATUS_BAND:
                band = STATUS_BAND[status]
            else:
                unclassified.append(
                    {
                        "id": task["task_id"],
                        "title": task.get("title"),
                        "status": status,
                        "reason": f"status {status!r} has no band mapping",
                    }
                )
                continue
            grouped[band].append(
                _build_item(task, band, verification, github_snapshot)
            )
        for key, question in BANDS:
            bands.append(
                {
                    "key": key,
                    "question": question,
                    "countable": True,
                    "count": len(grouped[key]),
                    "items": grouped[key],
                }
            )
        total = sum(len(items) for items in grouped.values())
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
        "unsynced_threads": _build_unsynced_threads(tasks, github_snapshot),
    }
