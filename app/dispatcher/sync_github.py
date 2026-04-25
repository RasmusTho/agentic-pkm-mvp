"""GitHub pull-sync adapter for the local Agent Issue Dispatcher.

Design constraints (from #625):
- Pull-only: no write-back to GitHub in this implementation.
- Tests must be fully offline; no live GitHub API access is required.
- GitHub Projects is not used in the sync hot path.
- Sync failures are observable and must not corrupt the local queue state.
- The adapter is intentionally narrow and mockable.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from app.dispatcher.models import SyncState, TaskRecord
from app.dispatcher.store import DispatcherStore

PROVIDER_IDENTITY = "github"


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
) -> None:
    """Persist a successful pull-sync metadata record for *provider*."""
    extra: dict[str, Any] = {}
    if rate_limit_remaining is not None:
        extra["rate_limit_remaining"] = rate_limit_remaining
    if rate_limit_reset is not None:
        extra["rate_limit_reset"] = rate_limit_reset

    sync_state = SyncState(
        last_pull_at=pull_at,
        sync_result="ok",
        sync_note=None,
        extra=extra,
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

    def pull(self, repo: str, **kwargs: Any) -> list[TaskRecord]:
        """Pull open issues from *repo* and upsert normalised task records.

        Returns the list of upserted :class:`TaskRecord` objects.
        Raises nothing; on error, records failure metadata and returns ``[]``.
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
            return []

        upserted: list[TaskRecord] = []
        for issue in issues:
            task = normalize_github_issue(issue, now=pull_at)
            self._store.upsert_task(task)
            upserted.append(task)

        rl_remaining: int | None = None
        rl_reset: str | None = None
        if rate_limit:
            rl_remaining = rate_limit.get("remaining")
            rl_reset = rate_limit.get("reset")

        record_sync_success(
            self._store,
            self._provider,
            pull_at,
            rate_limit_remaining=rl_remaining,
            rate_limit_reset=rl_reset,
        )
        return upserted
