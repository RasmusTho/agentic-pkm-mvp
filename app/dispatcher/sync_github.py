"""GitHub pull-sync adapter for the local Agent Issue Dispatcher.

Design constraints (from #625):
- Pull-only: no write-back to GitHub in this implementation.
- Tests must be fully offline; no live GitHub API access is required.
- GitHub Projects is not used in the sync hot path.
- Sync failures are observable and must not corrupt the local queue state.
- The adapter is intentionally narrow and mockable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.dispatcher.models import EventRecord, SyncState, TaskRecord
from app.dispatcher.store import DispatcherStore

PROVIDER_IDENTITY = "github"


@dataclass
class PullResult:
    """Result of a pull-sync operation."""

    upserted: list[TaskRecord] = field(default_factory=list)
    reconciled: list[TaskRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Label → priority mapping
# ---------------------------------------------------------------------------

_LABEL_PRIORITY: dict[str, str] = {
    "prio:high": "high",
    "prio:med": "med",
    "prio:low": "low",
    "priority:high": "high",
    "priority:medium": "med",
    "priority:low": "low",
}

_LABEL_STATUS: dict[str, str] = {
    "agent:ready": "ready",
    "agent:blocked": "blocked",
}


def normalize_github_issue(payload: dict[str, Any], now: str | None = None) -> TaskRecord:
    """Normalize a GitHub issue API payload into a local :class:`TaskRecord`.

    The function is deterministic and requires no network access; callers pass
    raw GitHub issue dicts (real or mocked).

    Priority defaults to ``med`` when no recognised priority label is present.
    Status defaults to ``ready`` when no recognised status label is present.
    """
    if now is None:
        now = datetime.now(timezone.utc).isoformat()

    number = payload["number"]
    task_id = f"github-issue-{number}"

    labels: list[str] = [
        (lbl.get("name") or lbl) if isinstance(lbl, dict) else str(lbl)
        for lbl in payload.get("labels", [])
    ]

    priority = "med"
    for lbl in labels:
        if lbl in _LABEL_PRIORITY:
            priority = _LABEL_PRIORITY[lbl]
            break

    status = "ready"
    for lbl in labels:
        if lbl in _LABEL_STATUS:
            status = _LABEL_STATUS[lbl]
            break

    updated_at = payload.get("updatedAt") or payload.get("updated_at") or now

    sync_state = SyncState(
        last_pull_at=now,
        source_version=payload.get("updatedAt") or payload.get("updated_at"),
        sync_result="ok",
        sync_note=None,
    )

    return TaskRecord(
        task_id=task_id,
        issue_number=number,
        title=payload.get("title", ""),
        status=status,
        priority=priority,
        source_anchor_refs=[f"github:issue:{number}"],
        created_at=payload.get("createdAt") or payload.get("created_at") or now,
        updated_at=updated_at,
        sync_state=sync_state.to_dict(),
    )


# ---------------------------------------------------------------------------
# Sync-state persistence helpers
# ---------------------------------------------------------------------------

def _meta_task_id(provider: str) -> str:
    return f"_sync_meta_{provider}"


def record_sync_success(
    store: DispatcherStore,
    provider: str,
    pull_at: str,
    rate_limit_remaining: int | None = None,
    rate_limit_reset: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a successful pull-sync metadata record for *provider*."""
    merged: dict[str, Any] = dict(extra or {})
    if rate_limit_remaining is not None:
        merged["rate_limit_remaining"] = rate_limit_remaining
    if rate_limit_reset is not None:
        merged["rate_limit_reset"] = rate_limit_reset

    sync_state = SyncState(
        last_pull_at=pull_at,
        sync_result="ok",
        sync_note=None,
        extra=merged,
    )
    _write_sync_meta(store, provider, sync_state, pull_at)


def record_sync_failure(
    store: DispatcherStore,
    provider: str,
    pull_at: str,
    error: str,
) -> None:
    """Persist a sync failure metadata record without touching task rows."""
    sync_state = SyncState(
        last_pull_at=pull_at,
        sync_result="error",
        sync_note=error,
    )
    _write_sync_meta(store, provider, sync_state, pull_at)


def _write_sync_meta(
    store: DispatcherStore,
    provider: str,
    sync_state: SyncState,
    pull_at: str,
) -> None:
    task_id = _meta_task_id(provider)
    existing = store.get_task(task_id)
    if existing is None:
        record = TaskRecord(
            task_id=task_id,
            issue_number=0,
            title=f"_sync_meta:{provider}",
            status="_meta",
            priority="low",
            source_anchor_refs=[],
            created_at=pull_at,
            updated_at=pull_at,
            sync_state=sync_state.to_dict(),
        )
    else:
        existing.sync_state = sync_state.to_dict()
        existing.updated_at = pull_at
        record = existing
    store.upsert_task(record)


def get_sync_meta(store: DispatcherStore, provider: str) -> dict[str, Any] | None:
    """Return the last recorded sync metadata for *provider*, or None."""
    task_id = _meta_task_id(provider)
    record = store.get_task(task_id)
    if record is None:
        return None
    return record.sync_state


# ---------------------------------------------------------------------------
# Pull-sync adapter protocol and implementation
# ---------------------------------------------------------------------------

class GitHubIssueSource(Protocol):
    """Minimal interface for a GitHub issue data source.

    Implementations may call ``gh`` CLI, the REST API, or return mock data.
    The sync adapter never imports or calls GitHub directly; it only uses this
    protocol, keeping unit tests fully offline.
    """

    def list_issues(self, repo: str, **kwargs: Any) -> list[dict[str, Any]]: ...

    def get_rate_limit(self) -> dict[str, Any] | None: ...


class GhCliIssueSource:
    """GitHub issue source using the ``gh`` CLI to list open issues.

    Queries issues with ``agent:ready`` label; requires ``gh`` authentication.
    Completely offline-testable via mocking; no live API imports at module level.
    """

    def __init__(self) -> None:
        pass

    def list_issues(self, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        """List open issues with agent:ready label from the repo."""
        import json
        import subprocess

        try:
            # Query open issues with agent:ready label
            result = subprocess.run(
                [
                    "gh",
                    "issue",
                    "list",
                    "--repo",
                    repo,
                    "--search",
                    "is:open label:agent:ready",
                    "--json",
                    "number,title,state,labels,createdAt,updatedAt",
                    "--limit",
                    "100",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"gh issue list failed: {result.stderr}")
            return json.loads(result.stdout)
        except FileNotFoundError:
            raise RuntimeError("gh CLI not found; ensure gh is installed and in PATH")

    def get_rate_limit(self) -> dict[str, Any] | None:
        """Get current GitHub API rate limit info."""
        import json
        import subprocess

        try:
            result = subprocess.run(
                ["gh", "api", "rate_limit", "--json", "remaining,reset"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("rate_limit", {})
        except Exception:
            pass
        return None


class PullSyncAdapter:
    """Pull issues from *source* and upsert them as local dispatcher tasks.

    Only reads from GitHub; does not write back labels, comments, or status.
    GitHub Projects is not queried or mutated.
    Sync failures record an error state and leave existing task rows untouched.
    """

    def __init__(
        self,
        store: DispatcherStore,
        source: GitHubIssueSource,
        provider: str = PROVIDER_IDENTITY,
    ) -> None:
        self._store = store
        self._source = source
        self._provider = provider

    def pull(self, repo: str, **kwargs: Any) -> PullResult:
        """Pull open issues from *repo*, upsert normalised task records, and
        purge stale local ready tasks no longer in the agent:ready set.

        Returns a :class:`PullResult` with ``upserted`` and ``reconciled`` lists.
        Raises nothing; on error, records failure metadata and returns an empty result.
        """
        pull_at = datetime.now(timezone.utc).isoformat()
        rate_limit: dict[str, Any] | None = None
        try:
            rate_limit = self._source.get_rate_limit()
        except Exception:
            pass

        try:
            issues = self._source.list_issues(repo, **kwargs)
        except Exception as exc:
            record_sync_failure(self._store, self._provider, pull_at, str(exc))
            return PullResult()

        _ACTIVE_STATUSES = frozenset({"blocked", "claimed", "in_progress"})

        upserted: list[TaskRecord] = []
        skipped: list[str] = []
        for issue in issues:
            try:
                task = normalize_github_issue(issue, now=pull_at)
                existing = self._store.get_task(task.task_id)
                if existing is not None and existing.status in _ACTIVE_STATUSES:
                    # Preserve local operational state; only refresh metadata from GitHub.
                    existing.title = task.title
                    existing.priority = task.priority
                    existing.sync_state = task.sync_state
                    existing.updated_at = task.updated_at
                    task = existing
                self._store.upsert_task(task)
                upserted.append(task)
            except Exception as exc:
                skipped.append(f"issue={issue.get('number', '?')}: {exc}")

        # Reconciliation: demote local ready tasks not in the fresh agent:ready set.
        fresh_issue_numbers = {t.issue_number for t in upserted}
        reconciled: list[TaskRecord] = []
        for stale in self._store.list_tasks(status="ready"):
            if stale.task_id.startswith("_"):
                continue  # skip internal meta rows
            if stale.issue_number in fresh_issue_numbers:
                continue
            stale.status = "blocked"
            stale.blocked_reason = "pull-sync: no longer in agent:ready set"
            stale.updated_at = pull_at
            self._store.upsert_task(stale)
            self._store.append_event(EventRecord(
                event_id=f"evt-{uuid.uuid4().hex[:8]}",
                timestamp=pull_at,
                task_id=stale.task_id,
                event_type="task.sync.purged",
                actor="pull-sync",
                payload={"reason": "no longer in agent:ready set"},
            ))
            reconciled.append(stale)

        rl_remaining: int | None = None
        rl_reset: str | None = None
        if rate_limit:
            rl_remaining = rate_limit.get("remaining")
            rl_reset = rate_limit.get("reset")

        extra: dict[str, Any] = {}
        if skipped:
            extra["skipped_count"] = len(skipped)
            extra["skipped_notes"] = skipped[:10]
        if reconciled:
            extra["reconciled_count"] = len(reconciled)

        record_sync_success(
            self._store,
            self._provider,
            pull_at,
            rate_limit_remaining=rl_remaining,
            rate_limit_reset=rl_reset,
            extra=extra,
        )
        return PullResult(upserted=upserted, reconciled=reconciled)
