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
# visible instead of implied.
UNREAD_PLANES: tuple[str, ...] = (
    "github-live",
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


def _rung(name: str, cls: str, value: str | None = None) -> dict[str, Any]:
    return {"name": name, "class": cls, "value": value}


def _build_rungs(
    task: dict[str, Any],
    verification: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Classify the eight rungs for one task.

    Key classes: ``proven`` (DB-keyed or CI-forced edge), ``absent`` (no object
    at that level in the system). v1 has no prose-derived rungs; ``derived``
    appears once epic/capability edges are joined in a later slice.
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
    pr_number: int | None = None
    if linked_pr:
        rungs.append(_rung("pr", "proven", f"PR #{linked_pr}"))
        try:
            pr_number = int(str(linked_pr).lstrip("#"))
        except ValueError:
            pr_number = None
    else:
        rungs.append(_rung("pr", "absent"))

    run = verification.get((repo, pr_number)) if pr_number is not None else None
    if run and run.get("verified_head_sha"):
        rungs.append(_rung("ci_sha", "proven", str(run["verified_head_sha"])[:12]))
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
) -> dict[str, Any]:
    labels = _sync_labels(task.get("sync_state"))
    url = _sync_url(task.get("sync_state"))
    links = [url] if url else []
    return {
        "id": task["task_id"],
        "issue_number": task.get("issue_number"),
        "repo": task.get("repo"),
        "title": task.get("title"),
        "band": band,
        "status": task.get("status"),
        "priority": task.get("priority"),
        "claimed_by": task.get("claimed_by"),
        "linked_pr": task.get("linked_pr"),
        "labels": labels,
        "why_now": _why_now(task, band),
        "links": links,
        "rungs": _build_rungs(task, verification),
        "sources": ["dispatcher-store", "verification-runs"],
        "updated_at": task.get("updated_at"),
    }


def build_registry(
    *,
    db_path: Path,
    deploy_receipt_dir: Path,
) -> dict[str, Any]:
    """Build the cockpit registry payload. Pure read; never writes anywhere."""
    sources = _Sources()
    tasks = _read_tasks(db_path, sources)
    verification = _read_verification_runs(db_path, sources)
    deployments = _read_deploy_receipts(deploy_receipt_dir, sources)

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
            grouped[band].append(_build_item(task, band, verification))
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
    }
