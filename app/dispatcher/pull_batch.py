"""One bounded multi-repository pull over the existing read-only adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.dispatcher.pickup_refresh import repository_coverage
from app.dispatcher.repositories import normalize_repositories
from app.dispatcher.store import DispatcherStore
from app.dispatcher.sync_github import (
    PROVIDER_IDENTITY,
    GhCliIssueSource,
    GitHubIssueSource,
    PullSyncAdapter,
    get_sync_meta,
    record_sync_batch_summary,
    record_sync_failure,
)


@dataclass(frozen=True)
class PullBatchResult:
    payload: dict[str, Any]
    exit_code: int
    observed_ready_task_ids: frozenset[str]


def pull_repositories(
    store: DispatcherStore,
    repositories: tuple[str, ...] | list[str],
    *,
    configured_repositories: tuple[str, ...],
    source: GitHubIssueSource | None = None,
) -> PullBatchResult:
    """Pull each selected repository once and persist truthful batch coverage."""
    selected = normalize_repositories(repositories)
    configured = normalize_repositories(configured_repositories)
    issue_source = source or GhCliIssueSource()
    adapter = PullSyncAdapter(store=store, source=issue_source)

    total_upserted = 0
    total_reconciled = 0
    total_skipped = 0
    repo_results: dict[str, dict[str, Any]] = {}
    observed_ready_task_ids: set[str] = set()
    failures: list[str] = []
    partials: list[str] = []
    last_meta: dict[str, Any] = {}

    for repository in selected:
        try:
            upserted = adapter.pull(repository)
            observed_ready_task_ids.update(task.task_id for task in upserted)
            sync_meta = get_sync_meta(store, PROVIDER_IDENTITY) or {}
            result = sync_meta.get("sync_result")
            note = sync_meta.get("sync_note")
            reconciled = getattr(adapter, "last_reconciled_count", 0)
            result_is_ready_scan = isinstance(result, str) and result in {"ok", "partial"}
            entry: dict[str, Any] = {
                "last_pull_at": sync_meta.get("last_pull_at"),
                "sync_result": result,
                "ready_issue_scan": result_is_ready_scan,
                "upserted": len(upserted),
                "reconciled": reconciled,
            }
            if isinstance(sync_meta.get("skipped_count"), int):
                entry["skipped"] = sync_meta["skipped_count"]
                total_skipped += sync_meta["skipped_count"]
            if note:
                entry["sync_note"] = note
            if result == "partial":
                entry["kill_switch_active"] = bool(sync_meta.get("kill_switch_active"))
                partials.append(f"{repository}: {note or 'dispatcher pull partial sync'}")
                total_upserted += len(upserted)
                total_reconciled += reconciled
            elif result == "error":
                failures.append(f"{repository}: {note or 'dispatcher pull source failed'}")
            elif result == "ok":
                total_upserted += len(upserted)
                total_reconciled += reconciled
            else:
                entry["sync_result"] = "error"
                entry["ready_issue_scan"] = False
                entry["sync_note"] = "dispatcher pull did not record a terminal sync result"
                failures.append(f"{repository}: {entry['sync_note']}")
            repo_results[repository] = entry
            last_meta = sync_meta
        except Exception as exc:
            failed_at = datetime.now(timezone.utc).isoformat()
            note = f"unexpected pull error: {exc}"
            record_sync_failure(
                store,
                PROVIDER_IDENTITY,
                failed_at,
                note,
                extra={"repository": repository},
            )
            repo_results[repository] = {
                "last_pull_at": failed_at,
                "sync_result": "error",
                "ready_issue_scan": False,
                "upserted": 0,
                "reconciled": 0,
                "sync_note": note,
            }
            failures.append(f"{repository}: {note}")
            last_meta = get_sync_meta(store, PROVIDER_IDENTITY) or {}

    batch_at = datetime.now(timezone.utc).isoformat()
    sync_result = "error" if failures else "partial" if partials else "ok"
    notes = [*failures, *partials]
    sync_note = "; ".join(notes) if notes else None
    kill_switch_active = any(
        bool(entry.get("kill_switch_active")) for entry in repo_results.values()
    )
    summary_extra: dict[str, Any] = {
        "repo_results": repo_results,
        "configured_repositories": list(configured),
        "requested_repositories": list(selected),
        "kill_switch_active": kill_switch_active,
    }
    for key in ("rate_limit_remaining", "rate_limit_reset"):
        value = last_meta.get(key)
        if value is not None:
            summary_extra[key] = value
    record_sync_batch_summary(
        store,
        PROVIDER_IDENTITY,
        batch_at,
        sync_result=sync_result,
        sync_note=sync_note,
        extra=summary_extra,
    )

    payload = {
        "ok": not failures,
        "upserted": total_upserted,
        "reconciled": total_reconciled,
        "skipped": total_skipped,
        "provider": PROVIDER_IDENTITY,
        "sync_result": sync_result,
        "sync_note": sync_note,
        "kill_switch_active": kill_switch_active,
        "configured_repositories": list(configured),
        "repository_coverage": repository_coverage(
            repo_results, configured, now=datetime.now(timezone.utc)
        ),
        "repos": repo_results,
    }
    if failures:
        payload["error"] = "pull failed: " + "; ".join(failures)
    return PullBatchResult(
        payload=payload,
        exit_code=1 if failures else 0,
        observed_ready_task_ids=frozenset(observed_ready_task_ids),
    )
