"""GitHub pull-sync adapter for the local Agent Issue Dispatcher.

Design constraints (from #625):
- Pull-only: no write-back to GitHub in this implementation.
- Tests must be fully offline; no live GitHub API access is required.
- GitHub Projects is not used in the sync hot path.
- Sync failures are observable and must not corrupt the local queue state.
- The adapter is intentionally narrow and mockable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import uuid
from typing import Any, Protocol

from app.dispatcher.models import EventRecord, SyncState, TaskRecord
from app.dispatcher.store import DispatcherStore
from app.dispatcher.github_call_logger import (
    is_kill_switch_active,
    log_github_call,
    get_last_known_remaining,
)

PROVIDER_IDENTITY = "github"

_GITHUB_FAILURE_NETWORK_MARKERS = (
    "connection reset",
    "connection refused",
    "dns",
    "eof",
    "internal server error",
    "gateway timeout",
    "server error",
    "service unavailable",
    "network is unreachable",
    "temporarily unavailable",
    "tls handshake timeout",
    "timed out",
    "bad gateway",
)

_GITHUB_FAILURE_PRIMARY_QUOTA_MARKERS = (
    "api rate limit exceeded",
    "primary rate limit",
    "x-ratelimit-remaining: 0",
)

_GITHUB_FAILURE_SECONDARY_QUOTA_MARKERS = (
    "secondary rate limit",
    "retry-after",
)

_GITHUB_FAILURE_RESOURCE_LIMIT_MARKERS = (
    "resource_limits_exceeded",
    "resource limits exceeded",
    "node limit",
    "node-limit",
    "query timeout",
    "graphql timeout",
    "timeout exceeded",
)

_GITHUB_FAILURE_WRITE_LIMIT_MARKERS = (
    "abuse detection",
    "content creation limit",
    "write limit",
    "mutation limit",
)


@dataclass(frozen=True)
class GitHubFailureClassification:
    """Best-effort GitHub API failure bucket."""

    kind: str
    http_status: int | None = None
    graphql_error_type: str | None = None
    retry_after_seconds: int | None = None
    reset_epoch: int | None = None
    retryable: bool = False
    reduce_page_size: bool = False

    def to_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {"failure_class": self.kind}
        if self.http_status is not None:
            extra["failure_http_status"] = self.http_status
        if self.graphql_error_type is not None:
            extra["failure_graphql_error_type"] = self.graphql_error_type
        if self.retry_after_seconds is not None:
            extra["failure_retry_after_seconds"] = self.retry_after_seconds
        if self.reset_epoch is not None:
            extra["failure_reset_epoch"] = self.reset_epoch
        return extra


def _failure_text(error: Exception | str) -> str:
    if isinstance(error, str):
        return error
    parts = [str(error)]
    for attr in ("stderr", "stdout"):
        value = getattr(error, attr, None)
        if value:
            parts.append(str(value))
    return "\n".join(part for part in parts if part)


def _header_value(headers: Mapping[str, Any] | None, name: str) -> str | None:
    if headers is None:
        return None
    needle = name.lower()
    for key, value in headers.items():
        if str(key).lower() == needle:
            return str(value)
    return None


def _parse_retry_after(
    text: str,
    headers: Mapping[str, Any] | None,
) -> int | None:
    header_value = _header_value(headers, "retry-after")
    if header_value is not None:
        try:
            return max(0, int(float(header_value)))
        except (TypeError, ValueError):
            pass
    match = re.search(r"retry[- ]after[:\s]+(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _parse_reset_epoch(headers: Mapping[str, Any] | None) -> int | None:
    reset_value = _header_value(headers, "x-ratelimit-reset")
    if reset_value is None:
        return None
    try:
        return int(float(reset_value))
    except (TypeError, ValueError):
        return None


def classify_github_api_failure(
    error: Exception | str,
    *,
    http_status: int | None = None,
    graphql_error_type: str | None = None,
    headers: Mapping[str, Any] | None = None,
) -> GitHubFailureClassification:
    """Bucket GitHub API failures for retry / backoff decisions."""

    text = _failure_text(error).lower()
    normalized_error_type = (graphql_error_type or "").upper()
    retry_after_seconds = _parse_retry_after(text, headers)
    reset_epoch = _parse_reset_epoch(headers)

    if (
        normalized_error_type in {"RESOURCE_LIMITS_EXCEEDED", "NODE_LIMIT_EXCEEDED", "TIMEOUT"}
        or any(marker in text for marker in _GITHUB_FAILURE_RESOURCE_LIMIT_MARKERS)
    ):
        return GitHubFailureClassification(
            kind="resource_limit",
            http_status=http_status,
            graphql_error_type=normalized_error_type or None,
            retry_after_seconds=retry_after_seconds,
            reset_epoch=reset_epoch,
            retryable=False,
            reduce_page_size=True,
        )

    if any(marker in text for marker in _GITHUB_FAILURE_WRITE_LIMIT_MARKERS):
        return GitHubFailureClassification(
            kind="write_content_limit",
            http_status=http_status,
            graphql_error_type=normalized_error_type or None,
            retry_after_seconds=retry_after_seconds,
            reset_epoch=reset_epoch,
            retryable=False,
            reduce_page_size=False,
        )

    if any(marker in text for marker in _GITHUB_FAILURE_SECONDARY_QUOTA_MARKERS) or (
        http_status in {403, 429} and retry_after_seconds is not None
    ):
        return GitHubFailureClassification(
            kind="secondary_quota",
            http_status=http_status,
            graphql_error_type=normalized_error_type or None,
            retry_after_seconds=retry_after_seconds,
            reset_epoch=reset_epoch,
            retryable=True,
            reduce_page_size=False,
        )

    if any(marker in text for marker in _GITHUB_FAILURE_PRIMARY_QUOTA_MARKERS) or (
        http_status in {403, 429} and ("rate limit" in text or "remaining" in text)
    ):
        return GitHubFailureClassification(
            kind="primary_quota",
            http_status=http_status,
            graphql_error_type=normalized_error_type or None,
            retry_after_seconds=retry_after_seconds,
            reset_epoch=reset_epoch,
            retryable=True,
            reduce_page_size=False,
        )

    if any(marker in text for marker in _GITHUB_FAILURE_NETWORK_MARKERS) or http_status in {
        500,
        502,
        503,
        504,
    }:
        return GitHubFailureClassification(
            kind="network",
            http_status=http_status,
            graphql_error_type=normalized_error_type or None,
            retry_after_seconds=retry_after_seconds,
            reset_epoch=reset_epoch,
            retryable=True,
            reduce_page_size=False,
        )

    return GitHubFailureClassification(
        kind="unknown",
        http_status=http_status,
        graphql_error_type=normalized_error_type or None,
        retry_after_seconds=retry_after_seconds,
        reset_epoch=reset_epoch,
        retryable=False,
        reduce_page_size=False,
    )


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
        str(lbl.get("name") or lbl) if isinstance(lbl, dict) else str(lbl)
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
    extra: dict[str, Any] | None = None,
) -> None:
    """Persist a sync failure metadata record without touching task rows."""
    merged: dict[str, Any] = dict(extra or {})
    sync_state = SyncState(
        last_pull_at=pull_at,
        sync_result="error",
        sync_note=error,
        extra=merged,
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
    def list_open_issues(self, repo: str, **kwargs: Any) -> list[dict[str, Any]]: ...

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

    def list_open_issues(self, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        """List all open issues with labels from the repo."""
        import json
        import subprocess

        try:
            result = subprocess.run(
                [
                    "gh",
                    "issue",
                    "list",
                    "--repo",
                    repo,
                    "--search",
                    "is:open",
                    "--json",
                    "number,title,state,labels,createdAt,updatedAt",
                    "--limit",
                    "1000",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"gh issue list (open) failed: {result.stderr}")
            return json.loads(result.stdout)
        except FileNotFoundError:
            raise RuntimeError("gh CLI not found; ensure gh is installed and in PATH")

    def get_rate_limit(self) -> dict[str, Any] | None:
        """Get current GitHub API rate limit info."""
        import json
        import subprocess

        try:
            result = subprocess.run(
                ["gh", "api", "rate_limit", "--jq", ".rate"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
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
        self.last_reconciled_count = 0

    def pull(self, repo: str, **kwargs: Any) -> list[TaskRecord]:
        """Pull open issues from *repo* and upsert normalised task records.

        Returns the list of upserted :class:`TaskRecord` objects.
        Raises nothing; on error, records failure metadata and returns ``[]``.

        Kill switch: when the last captured ``rate_limit_remaining`` is below
        threshold, the expensive open-issues scan and stale reconcile are
        skipped. Essential read (agent:ready list) is always attempted.
        """
        import time as _time
        pull_at = datetime.now(timezone.utc).isoformat()
        rate_limit: dict[str, Any] | None = None
        try:
            t0 = _time.monotonic()
            rate_limit = self._source.get_rate_limit()
            log_github_call(
                operation="gh api rate_limit",
                direction="read",
                latency_ms=round((_time.monotonic() - t0) * 1000, 2),
            )
        except Exception as exc:
            log_github_call(operation="gh api rate_limit", direction="read", error=str(exc))

        # Determine last known remaining from current rate_limit response or
        # previously stored sync-meta, then check kill switch.
        rl_remaining: int | None = None
        rl_reset: str | None = None
        if rate_limit:
            rl_remaining = rate_limit.get("remaining")
            rl_reset = rate_limit.get("reset")
        if rl_remaining is None:
            last_meta = get_sync_meta(self._store, self._provider)
            rl_remaining = get_last_known_remaining(last_meta)

        kill_switch = is_kill_switch_active(rl_remaining)

        try:
            t0 = _time.monotonic()
            ready_issues = self._source.list_issues(repo, **kwargs)
            log_github_call(
                operation="gh issue list --label agent:ready",
                direction="read",
                remaining=rl_remaining,
                reset=rl_reset,
                latency_ms=round((_time.monotonic() - t0) * 1000, 2),
            )
        except Exception as exc:
            log_github_call(
                operation="gh issue list --label agent:ready",
                direction="read",
                remaining=rl_remaining,
                error=str(exc),
            )
            failure = classify_github_api_failure(exc)
            record_sync_failure(
                self._store,
                self._provider,
                pull_at,
                f"{failure.kind}: {exc}",
                extra=failure.to_extra(),
            )
            return []

        open_issues_available = True
        if kill_switch:
            # Non-essential scan disabled to protect remaining quota.
            open_issues: list[dict[str, Any]] = []
            open_issues_available = False
        else:
            try:
                t0 = _time.monotonic()
                open_issues = self._source.list_open_issues(repo, **kwargs)
                log_github_call(
                    operation="gh issue list --all-open",
                    direction="read",
                    remaining=rl_remaining,
                    reset=rl_reset,
                    latency_ms=round((_time.monotonic() - t0) * 1000, 2),
                )
            except Exception as exc:
                log_github_call(
                    operation="gh issue list --all-open",
                    direction="read",
                    remaining=rl_remaining,
                    error=str(exc),
                )
                # If open-issues lookup fails, still preserve current upsert behavior.
                open_issues = []
                open_issues_available = False

        upserted: list[TaskRecord] = []
        skipped: list[str] = []
        for issue in ready_issues:
            try:
                task = normalize_github_issue(issue, now=pull_at)
                existing = self._store.get_task(task.task_id)
                if existing is not None and existing.status in {"claimed", "in_progress"}:
                    task.status = existing.status
                    task.claimed_by = existing.claimed_by
                    task.lease_id = existing.lease_id
                    task.lease_expires_at = existing.lease_expires_at
                    task.blocked_reason = existing.blocked_reason
                    task.last_heartbeat_at = existing.last_heartbeat_at
                self._store.upsert_task(task)
                upserted.append(task)
            except Exception as exc:
                skipped.append(f"issue={issue.get('number', '?')}: {exc}")

        ready_issue_numbers: set[int] = set()
        for issue in ready_issues:
            number = issue.get("number")
            if isinstance(number, int):
                ready_issue_numbers.add(number)

        reconciled = self._reconcile_stale_ready(
            pull_at=pull_at,
            ready_issue_numbers=ready_issue_numbers,
            open_issues=open_issues,
            open_issues_available=open_issues_available,
        )
        self.last_reconciled_count = reconciled

        extra: dict[str, Any] = {}
        if skipped:
            extra["skipped_count"] = len(skipped)
            extra["skipped_notes"] = skipped[:10]
        extra["reconciled_count"] = reconciled
        extra["kill_switch_active"] = kill_switch

        record_sync_success(
            self._store,
            self._provider,
            pull_at,
            rate_limit_remaining=rl_remaining,
            rate_limit_reset=rl_reset,
            extra=extra,
        )
        return upserted

    def _reconcile_stale_ready(
        self,
        pull_at: str,
        ready_issue_numbers: set[int],
        open_issues: list[dict[str, Any]],
        open_issues_available: bool = True,
    ) -> int:
        open_issue_labels: dict[int, set[str]] = {}
        for issue in open_issues:
            number = issue.get("number")
            if not isinstance(number, int):
                continue
            labels = {
                str(lbl.get("name") or lbl) if isinstance(lbl, dict) else str(lbl)
                for lbl in issue.get("labels", [])
            }
            open_issue_labels[number] = labels

        reconciled = 0
        for status in ("ready", "blocked"):
            for task in self._store.list_tasks(status=status):
                if task.issue_number in ready_issue_numbers:
                    if task.status == "blocked":
                        task.status = "ready"
                        task.blocked_reason = None
                        task.updated_at = pull_at
                        self._store.upsert_task(task)
                        self._store.append_event(
                            EventRecord(
                                event_id=str(uuid.uuid4()),
                                timestamp=pull_at,
                                task_id=task.task_id,
                                event_type="sync.reconciled",
                                actor=f"sync:{self._provider}",
                                payload={"from": "blocked", "to": "ready", "reason": "agent-ready-label-present"},
                            )
                        )
                        reconciled += 1
                    continue

                task_labels = open_issue_labels.get(task.issue_number)
                if task_labels is None and task.status == "blocked" and not open_issues_available:
                    # Keep blocked tasks stable when open-issue snapshot is unavailable.
                    continue
                if task_labels is None:
                    next_status = "completed"
                    reason = "closed-or-missing-from-open-issues"
                elif "agent:ready" in task_labels:
                    next_status = "ready"
                    reason = "agent-ready-label-present"
                else:
                    next_status = "blocked"
                    reason = "agent-ready-label-removed"

                from_status = task.status
                task.status = next_status
                if next_status != "blocked":
                    task.blocked_reason = None
                task.updated_at = pull_at
                self._store.upsert_task(task)
                self._store.append_event(
                    EventRecord(
                        event_id=str(uuid.uuid4()),
                        timestamp=pull_at,
                        task_id=task.task_id,
                        event_type="sync.reconciled",
                        actor=f"sync:{self._provider}",
                        payload={"from": from_status, "to": next_status, "reason": reason},
                    )
                )
                reconciled += 1
        return reconciled
