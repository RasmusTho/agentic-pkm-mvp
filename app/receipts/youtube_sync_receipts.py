"""Secret-free YouTube Source Sync receipt projection (YSS-09).

The projection joins the existing acquisition request rows with the existing
outbox lineage topics and source registry rows.  It intentionally owns no
state: callers can rebuild it from those durable sources after a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.config.environment import active_environment
from app.events.types import (
    ACQUISITION_COMPLETED,
    ACQUISITION_FAILED,
    ACQUISITION_REQUESTED,
    ACQUISITION_STARTED,
    KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED,
    YOUTUBE_SOURCE_DISCOVERED,
)
from app.receipts.outbox_sources import (
    first_str,
    read_receipt_source_records,
    record_event,
    record_payload,
)


@dataclass(frozen=True)
class YouTubeSyncReceiptQuery:
    item_ref: str | None = None
    request_id: str | None = None
    source_binding_id: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class YouTubeSyncTrigger:
    binding_id: str | None
    collection_kind: str | None
    collection_ref: str | None
    discovered_at: str | None
    trigger: str | None
    playlist_item_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "binding_id": self.binding_id,
            "collection_kind": self.collection_kind,
            "collection_ref": self.collection_ref,
            "at": self.discovered_at,
            "discovered_at": self.discovered_at,
            "trigger": self.trigger,
            "playlist_item_id": self.playlist_item_id,
        }


@dataclass(frozen=True)
class YouTubeSyncReceiptRow:
    item_ref: str
    request_id: str | None
    status: str | None
    requested_at: str | None
    completed_at: str | None
    artifact_path: str | None
    content_identity: str | None
    triggers: tuple[YouTubeSyncTrigger, ...] = ()
    attempts: int = 0
    next_attempt_at: str | None = None
    failed_stage: str | None = None
    failure_reason_code: str | None = None
    failure_at: str | None = None
    cursor_advanced: bool = False
    cursor_frontier: str | None = None
    account_binding_ids: tuple[str, ...] = ()
    channel_database: str | None = None
    source_event_ids: tuple[str, ...] = ()
    non_authoritative_records: tuple[dict[str, str | None], ...] = field(default_factory=tuple)

    @property
    def deduplicated(self) -> bool:
        return len(self.triggers) > 1

    @property
    def sources(self) -> tuple[dict[str, str | None], ...]:
        return tuple(trigger.to_dict() for trigger in self.triggers)

    @property
    def source_bindings(self) -> tuple[dict[str, str | None], ...]:
        return self.sources

    @property
    def failed_step(self) -> dict[str, str | None] | None:
        if not self.failure_reason_code and not self.failed_stage:
            return None
        return {
            "stage": self.failed_stage,
            "reason_code": self.failure_reason_code,
            "at": self.failure_at,
        }

    @property
    def next_retry_at(self) -> str | None:
        return self.next_attempt_at

    def to_dict(self) -> dict[str, Any]:
        """Return the operator shape, with no error text or credential fields."""
        return {
            "item_ref": self.item_ref,
            "request_id": self.request_id,
            "status": self.status,
            "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            "artifact_path": self.artifact_path,
            "content_identity": self.content_identity,
            "triggers": list(self.sources),
            "sources": list(self.sources),
            "deduplicated": self.deduplicated,
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
            "next_retry_at": self.next_retry_at,
            "failed_step": {
                "stage": self.failed_stage,
                "reason_code": self.failure_reason_code,
                "at": self.failure_at,
            }
            if self.failure_reason_code or self.failed_stage
            else None,
            "failure": {
                "stage": self.failed_stage,
                "reason_code": self.failure_reason_code,
                "at": self.failure_at,
            }
            if self.failure_reason_code or self.failed_stage
            else None,
            "cursor": {
                "advanced": self.cursor_advanced,
                "frontier": self.cursor_frontier,
            },
            "cursor_advanced": self.cursor_advanced,
            "account_binding_ids": list(self.account_binding_ids),
            "channel_database": self.channel_database,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True)
class YouTubeSyncReceiptQueryResult:
    source_available: bool
    rows: tuple[YouTubeSyncReceiptRow, ...] = ()
    non_authoritative_records: tuple[dict[str, str | None], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_available": self.source_available,
            "rows": [row.to_dict() for row in self.rows],
            "non_authoritative_records": list(self.non_authoritative_records),
        }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _trigger(value: Any, *, fallback: Mapping[str, Any] | None = None) -> YouTubeSyncTrigger | None:
    data = value if isinstance(value, Mapping) else (fallback or {})
    envelope = fallback or {}
    binding_id = first_str(data.get("binding_id"))
    collection_kind = first_str(data.get("collection_kind"), data.get("source_kind"))
    collection_ref = first_str(data.get("collection_ref"), data.get("source_ref"))
    at = first_str(
        data.get("discovered_at"),
        data.get("at"),
        data.get("timestamp"),
        envelope.get("timestamp"),
        envelope.get("created_at"),
    )
    trigger = first_str(data.get("trigger"))
    if not any((binding_id, collection_kind, collection_ref, at, trigger)):
        return None
    return YouTubeSyncTrigger(
        binding_id=binding_id,
        collection_kind=collection_kind,
        collection_ref=collection_ref,
        discovered_at=at,
        trigger=trigger,
        playlist_item_id=first_str(data.get("playlist_item_id")),
    )


def _trigger_identity(trigger: YouTubeSyncTrigger) -> tuple[str | None, str | None, str | None]:
    """Identity follows the stored trigger contract, not projection timestamps."""

    return (trigger.binding_id, trigger.trigger, trigger.playlist_item_id)


def _merge_trigger(kept: YouTubeSyncTrigger, other: YouTubeSyncTrigger) -> YouTubeSyncTrigger:
    """Fill fields the stored row omits (e.g. ``collection_ref``) from its event twin."""

    missing = {
        item.name: getattr(other, item.name)
        for item in fields(kept)
        if getattr(kept, item.name) is None and getattr(other, item.name) is not None
    }
    return replace(kept, **missing) if missing else kept


def _request_rows(requests: Iterable[Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if requests is None:
        return result
    for request in requests:
        request_id = first_str(_field(request, "request_id"))
        if request_id:
            result[request_id] = request
    return result


def _source_rows(sources: Iterable[Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if sources is None:
        return result
    for source in sources:
        binding_id = first_str(_field(source, "binding_id"))
        if binding_id:
            result[binding_id] = source
    return result


def _rows_from_records(
    records: Iterable[dict[str, Any]],
    *,
    requests: Iterable[Any] | None,
    sources: Iterable[Any] | None,
    channel_database: str | None,
) -> tuple[list[YouTubeSyncReceiptRow], list[dict[str, str | None]]]:
    request_map = _request_rows(requests)
    source_map = _source_rows(sources)
    groups: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, str | None]] = []

    def group_for(item_ref: str | None, request_id: str | None) -> dict[str, Any] | None:
        key = request_id or item_ref
        if not key:
            return None
        if request_id and item_ref and request_id not in groups and item_ref in groups:
            groups[request_id] = groups.pop(item_ref)
        group = groups.setdefault(key, {"item_ref": item_ref, "request_id": request_id, "triggers": [], "events": [], "failures": [], "channel_database": None, "account_binding_ids": []})
        if item_ref and not group.get("item_ref"):
            group["item_ref"] = item_ref
        if request_id and not group.get("request_id"):
            group["request_id"] = request_id
        return group

    for record in records:
        event = record_event(record)
        payload = record_payload(record)
        item_ref = first_str(payload.get("item_ref"), payload.get("video_id"))
        request_id = first_str(payload.get("request_id"))
        if event == YOUTUBE_SOURCE_DISCOVERED:
            group = group_for(item_ref, request_id)
            if group is not None:
                trigger = _trigger(payload, fallback=record)
                if trigger is not None:
                    group["triggers"].append(trigger)
                    group["events"].append(first_str(record.get("event_id")))
            continue
        is_sync_event = event.startswith("youtube.sync.")
        if event not in {
            ACQUISITION_REQUESTED,
            ACQUISITION_STARTED,
            ACQUISITION_COMPLETED,
            ACQUISITION_FAILED,
            KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED,
        } and not is_sync_event:
            continue
        group = group_for(item_ref, request_id)
        if group is None:
            if is_sync_event and not item_ref and not request_id:
                diagnostics.append(
                    {
                        "event_id": first_str(record.get("event_id")),
                        "trace_id": first_str(record.get("trace_id")),
                        "event": event,
                        "at": first_str(record.get("timestamp"), record.get("created_at"), payload.get("at")),
                        "reason_code": first_str(payload.get("reason_code"), payload.get("code")),
                        "reason": "source_level_sync_receipt",
                        "binding_id": first_str(payload.get("binding_id")),
                        "run_id": first_str(payload.get("run_id")),
                    }
                )
            else:
                diagnostics.append({"event_id": first_str(record.get("event_id")), "trace_id": first_str(record.get("trace_id")), "reason": "missing_item_ref_and_request_id"})
            continue
        group["events"].append(first_str(record.get("event_id")))
        event_channel_database = first_str(
            payload.get("channel_database"), payload.get("database"), payload.get("db_name")
        )
        if event_channel_database:
            group["channel_database"] = event_channel_database
        account_binding_id = first_str(payload.get("account_binding_id"))
        if account_binding_id:
            group["account_binding_ids"].append(account_binding_id)
        if event in {ACQUISITION_FAILED, KNOWLEDGE_ACQUISITION_STAGE_DEAD_LETTERED} or event.endswith((".failed", ".degraded")):
            group["failures"].append({
                "stage": first_str(payload.get("stage"), payload.get("stage_id"), "acquisition" if event in {ACQUISITION_FAILED} or event.endswith((".failed", ".degraded")) else "knowledge_acquisition"),
                "reason_code": first_str(payload.get("reason_code"), payload.get("code")),
                "at": first_str(record.get("timestamp"), record.get("created_at"), payload.get("at")),
            })

    for request_id, request in request_map.items():
        item_ref = first_str(_field(request, "item_ref"))
        group = group_for(item_ref, request_id)
        if group is None:
            continue
        triggers: list[YouTubeSyncTrigger] = []
        trigger_index: dict[tuple[str | None, str | None, str | None], int] = {}
        stored = [_trigger(value) for value in _field(request, "discovery_triggers", ()) or ()]
        for trigger in [*stored, *group["triggers"]]:
            if trigger is None:
                continue
            identity = _trigger_identity(trigger)
            if identity in trigger_index:
                # The stored row stays authoritative; its event twin only
                # supplies metadata the stored contract does not persist.
                position = trigger_index[identity]
                triggers[position] = _merge_trigger(triggers[position], trigger)
            else:
                trigger_index[identity] = len(triggers)
                triggers.append(trigger)
        group["triggers"] = triggers

    rows: list[YouTubeSyncReceiptRow] = []
    for group in groups.values():
        item_ref = first_str(group.get("item_ref"))
        if not item_ref:
            continue
        request_key = first_str(group.get("request_id"))
        request = request_map.get(request_key) if request_key else None
        projected_triggers = tuple(group.get("triggers") or ())
        source_binding_ids = tuple(
            sorted({trigger.binding_id for trigger in projected_triggers if trigger.binding_id})
        )
        account_binding_ids = set(group.get("account_binding_ids") or ())
        source_successes: dict[str, str] = {}
        source_frontiers: dict[str, str] = {}
        for binding_id in source_binding_ids:
            source = source_map.get(binding_id)
            if source is None:
                continue
            account_binding_id = first_str(_field(source, "account_binding_id"))
            account_binding_ids.add(account_binding_id or binding_id)
            success = first_str(_field(source, "last_success_at"))
            if success:
                source_successes[binding_id] = success
            cursor = _field(source, "cursor", {})
            if isinstance(cursor, Mapping):
                frontier = first_str(
                    cursor.get("frontier_playlist_item_id"),
                    cursor.get("frontier"),
                    cursor.get("newest_published_seen"),
                    cursor.get("newest_published_at"),
                    cursor.get("last_published_at"),
                )
                if frontier:
                    source_frontiers[binding_id] = frontier
        discovered_times_by_binding: dict[str, list[str]] = {}
        for trigger in projected_triggers:
            if trigger is None or not trigger.binding_id or not trigger.discovered_at:
                continue
            discovered_times_by_binding.setdefault(trigger.binding_id, []).append(
                trigger.discovered_at
            )
        cursor_advanced = bool(source_binding_ids) and all(
            binding_id in source_successes
            and bool(discovered_times_by_binding.get(binding_id))
            and source_successes[binding_id]
            >= max(discovered_times_by_binding[binding_id])
            for binding_id in source_binding_ids
        )
        cursor_frontier = (
            source_frontiers.get(source_binding_ids[0])
            if len(source_binding_ids) == 1
            else None
        )
        failures = group.get("failures") or []
        failure = failures[-1] if failures else None
        request_id = first_str(group.get("request_id"))
        event_ids = tuple(str(event_id) for event_id in (group.get("events") or []) if event_id)
        rows.append(
            YouTubeSyncReceiptRow(
                item_ref=item_ref,
                request_id=request_id,
                status=first_str(_field(request, "status")) if request is not None else None,
                requested_at=first_str(_field(request, "requested_at")) if request is not None else None,
                completed_at=first_str(_field(request, "completed_at")) if request is not None else None,
                artifact_path=first_str(_field(request, "artifact_path")) if request is not None else None,
                content_identity=first_str(_field(request, "content_identity")) if request is not None else None,
                triggers=projected_triggers,
                attempts=int(_field(request, "attempts", 0) or 0) if request is not None else 0,
                next_attempt_at=first_str(_field(request, "next_attempt_at")) if request is not None else None,
                failed_stage=first_str(failure.get("stage")) if failure else None,
                failure_reason_code=first_str(failure.get("reason_code")) if failure else None,
                failure_at=first_str(failure.get("at")) if failure else None,
                cursor_advanced=cursor_advanced,
                cursor_frontier=cursor_frontier,
                account_binding_ids=tuple(sorted(account_binding_ids)),
                channel_database=first_str(
                    group.get("channel_database"), channel_database, active_environment()
                ),
                source_event_ids=event_ids,
            )
        )
    rows.sort(key=lambda row: (row.requested_at or "", row.item_ref))
    return rows, diagnostics


def query_youtube_sync_receipts(
    query: YouTubeSyncReceiptQuery | None = None,
    *,
    item_ref: str | None = None,
    request_id: str | None = None,
    source_binding_id: str | None = None,
    status: str | None = None,
    vault_root: Path | None = None,
    outbox_path: Path | None = None,
    records: Iterable[dict[str, Any]] | None = None,
    requests: Iterable[Any] | None = None,
    sources: Iterable[Any] | None = None,
    channel_database: str | None = None,
) -> YouTubeSyncReceiptQueryResult:
    """Query the durable sync lineage without returning secret payloads."""

    del vault_root
    source_records = list(records) if records is not None else read_receipt_source_records(outbox_path=outbox_path)
    if source_records is None:
        return YouTubeSyncReceiptQueryResult(source_available=False)
    if requests is None:
        try:
            from app.knowledge_acquisition.acquisition_requests import AcquisitionRequests

            requests = AcquisitionRequests.for_runtime().list_all()
        except Exception:
            requests = ()
    if sources is None:
        try:
            from app.knowledge_acquisition.source_registry import SourceRegistry

            sources = SourceRegistry.for_runtime().list_all()
        except Exception:
            sources = ()
    rows, diagnostics = _rows_from_records(
        source_records,
        requests=requests,
        sources=sources,
        channel_database=channel_database,
    )
    filters = query or YouTubeSyncReceiptQuery(
        item_ref=item_ref,
        request_id=request_id,
        source_binding_id=source_binding_id,
        status=status,
    )
    rows = [
        row
        for row in rows
        if (not filters.item_ref or row.item_ref == filters.item_ref)
        and (not filters.request_id or row.request_id == filters.request_id)
        and (not filters.status or row.status == filters.status)
        and (not filters.source_binding_id or filters.source_binding_id in row.account_binding_ids)
    ]
    return YouTubeSyncReceiptQueryResult(
        source_available=True,
        rows=tuple(rows),
        non_authoritative_records=tuple(diagnostics),
    )


def project_youtube_sync_receipt(
    item_ref: str,
    **kwargs: Any,
) -> YouTubeSyncReceiptRow | None:
    result = query_youtube_sync_receipts(YouTubeSyncReceiptQuery(item_ref=item_ref), **kwargs)
    return result.rows[0] if result.rows else None


__all__ = [
    "YouTubeSyncReceiptQuery",
    "YouTubeSyncReceiptQueryResult",
    "YouTubeSyncReceiptRow",
    "YouTubeSyncTrigger",
    "project_youtube_sync_receipt",
    "query_youtube_sync_receipts",
]
