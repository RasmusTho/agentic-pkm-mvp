"""Freshness and source-coverage rules for the exact-task pickup path."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from app.dispatcher.models import TaskRecord

PICKUP_SYNC_MAX_AGE_SECONDS = 15 * 60


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: object, now: datetime) -> float | None:
    parsed = _timestamp(value)
    if parsed is None:
        return None
    age = (now - parsed).total_seconds()
    return age if age >= 0 else None


def repository_coverage(
    repo_results: object,
    configured_repos: tuple[str, ...],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize only repo-specific sync evidence; missing evidence stays visible."""
    observed_at = now or datetime.now(timezone.utc)
    recorded = repo_results if isinstance(repo_results, Mapping) else {}
    states: dict[str, str] = {}
    ages: dict[str, float | None] = {}

    for repository in configured_repos:
        entry = recorded.get(repository)
        if not isinstance(entry, Mapping):
            states[repository] = "missing"
            ages[repository] = None
            continue

        age = _age_seconds(entry.get("last_pull_at"), observed_at)
        ages[repository] = age
        result = entry.get("sync_result")
        if result == "error":
            states[repository] = "failed"
        elif not isinstance(result, str) or result not in {"ok", "partial"}:
            states[repository] = "unknown"
        elif age is None or age > PICKUP_SYNC_MAX_AGE_SECONDS:
            states[repository] = "stale"
        elif result == "partial":
            states[repository] = "partial"
        else:
            states[repository] = "fresh"

    fresh = [repo for repo, state in states.items() if state == "fresh"]
    partial = [repo for repo, state in states.items() if state == "partial"]
    failed = [repo for repo, state in states.items() if state == "failed"]
    stale = [repo for repo, state in states.items() if state == "stale"]
    missing = [repo for repo, state in states.items() if state == "missing"]
    unknown = [repo for repo, state in states.items() if state == "unknown"]
    ready_scan = [*fresh, *partial]

    if not recorded:
        coverage_state = "unavailable"
    elif failed:
        coverage_state = "failed"
    elif stale:
        coverage_state = "stale"
    elif missing or unknown:
        coverage_state = "incomplete"
    elif partial:
        coverage_state = "partial"
    else:
        coverage_state = "fresh"

    return {
        "state": coverage_state,
        "configured_repositories": list(configured_repos),
        "ready_scan_repositories": ready_scan,
        "fresh_repositories": fresh,
        "partial_repositories": partial,
        "failed_repositories": failed,
        "stale_repositories": stale,
        "missing_repositories": missing,
        "unknown_repositories": unknown,
        "age_seconds_by_repository": ages,
        "ready_scan_complete": bool(configured_repos) and len(ready_scan) == len(configured_repos),
        "complete": bool(configured_repos) and len(fresh) == len(configured_repos),
    }


def last_sync_status(
    sync_meta: Mapping[str, Any] | None,
    configured_repos: tuple[str, ...],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Project persisted sync evidence into a read-only status summary."""
    if sync_meta is None:
        return None
    observed_at = now or datetime.now(timezone.utc)
    age = _age_seconds(sync_meta.get("last_pull_at"), observed_at)
    result = sync_meta.get("sync_result")
    repo_results = sync_meta.get("repo_results")
    coverage = repository_coverage(repo_results, configured_repos, now=observed_at)
    batch_fresh = (
        age is not None
        and age <= PICKUP_SYNC_MAX_AGE_SECONDS
        and isinstance(result, str)
        and result in {"ok", "partial"}
    )
    ready_scan_fresh = coverage["ready_scan_complete"] is True
    return {
        "last_pull_at": sync_meta.get("last_pull_at"),
        "sync_result": result,
        "sync_note": sync_meta.get("sync_note"),
        "kill_switch_active": bool(sync_meta.get("kill_switch_active")),
        "age_seconds": age,
        "freshness_threshold_seconds": PICKUP_SYNC_MAX_AGE_SECONDS,
        "batch_fresh": batch_fresh,
        "ready_scan_fresh": ready_scan_fresh,
        "fresh": batch_fresh and ready_scan_fresh,
        "repository_coverage": coverage,
    }


def pickup_refresh_reason(
    task: TaskRecord | None,
    sync_meta: Mapping[str, Any] | None,
    target_repo: str,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return why one bounded refresh is needed before claiming this task.

    ``None`` means the exact task was observed as ready in a recent successful
    or partial ``agent:ready`` scan for its own configured repository.
    """
    if task is None:
        return "task_missing"
    if task.repo != target_repo:
        return "task_repository_mismatch"
    if sync_meta is None:
        return "sync_metadata_missing"

    repo_results = sync_meta.get("repo_results")
    if not isinstance(repo_results, Mapping):
        return "repository_sync_evidence_missing"
    repo_result = repo_results.get(target_repo)
    if not isinstance(repo_result, Mapping):
        return "target_repository_not_covered"
    result = repo_result.get("sync_result")
    if not isinstance(result, str) or result not in {"ok", "partial"}:
        return "target_repository_sync_failed"

    observed_at = now or datetime.now(timezone.utc)
    age = _age_seconds(repo_result.get("last_pull_at"), observed_at)
    if age is None or age > PICKUP_SYNC_MAX_AGE_SECONDS:
        return "target_repository_sync_stale"

    task_sync_state = task.sync_state
    task_pull_at = task_sync_state.get("last_pull_at") if isinstance(task_sync_state, dict) else None
    if task_pull_at != repo_result.get("last_pull_at"):
        return "task_not_in_latest_ready_set"
    if task.status != "ready":
        return "task_not_ready"
    return None
