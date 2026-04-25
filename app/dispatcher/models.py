"""Dispatcher MVP data model.

Mirrors the contract in ``docs/AGENT_ISSUE_DISPATCHER.md``. Persistence is
intentionally minimal: the dispatcher is operational coordination state, not a
durable lifecycle replacement for GitHub.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskRecord:
    task_id: str
    issue_number: int
    title: str
    status: str
    priority: str
    source_anchor_refs: list[str]
    created_at: str
    updated_at: str
    claimed_by: str | None = None
    lease_id: str | None = None
    lease_expires_at: str | None = None
    linked_pr: str | None = None
    blocked_reason: str | None = None
    last_heartbeat_at: str | None = None
    sync_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LeaseRecord:
    lease_id: str
    resource: str
    holder: str
    ttl_seconds: int
    acquired_at: str
    expires_at: str
    heartbeat_at: str | None = None
    released_at: str | None = None
    release_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EventRecord:
    event_id: str
    timestamp: str
    task_id: str
    event_type: str
    actor: str
    lease_id: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncState:
    last_pull_at: str | None = None
    source_version: str | None = None
    sync_result: str | None = None
    sync_note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        return data
