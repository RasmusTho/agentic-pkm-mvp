"""YSS-05 (#3920): one generic adapter for playlist-shaped YouTube sources.

The adapter enumerates only through the delivered YSS-03 client, disposes
each new playlist-item identity through the delivered YSS-04 request queue (or
an explicit ``discover_only`` trace), and only then publishes the YSS-01
cursor.  A failed API/auth/network poll never mutates cursor/known state and
never emits an empty-success receipt (INV-YSS-1/2/4).

Scheduling, leases, historical backfill, and acquisition draining remain with
YSS-06/YSS-08/YSS-04 respectively.
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NoReturn

from app.events.models import new_event
from app.events.types import (
    YOUTUBE_SOURCE_DISCOVERED,
    YOUTUBE_SYNC_COMPLETED,
    YOUTUBE_SYNC_DEGRADED,
)
from app.knowledge_acquisition.acquisition_requests import (
    DiscoveryTrigger,
    discovered_event_key,
    request_identity,
)
from app.knowledge_acquisition.source_registry import (
    UNSUPPORTED_COLLECTION_REFS,
    SourceBinding,
    SourceRegistry,
)
from app.knowledge_acquisition.youtube_api_client import (
    NotModified,
    PlaylistItem,
    PlaylistItemsPage,
    YouTubeApiError,
)
from app.services.outbox import derive_idempotency_key, write_outbox_event

YOUTUBE_SOURCE_DISCOVERED_TOPIC = YOUTUBE_SOURCE_DISCOVERED
YOUTUBE_SYNC_COMPLETED_TOPIC = YOUTUBE_SYNC_COMPLETED
YOUTUBE_SYNC_DEGRADED_TOPIC = YOUTUBE_SYNC_DEGRADED

EVENT_SOURCE = "knowledge_acquisition.source_sync"
CURSOR_VERSION = 1
MAX_KNOWN_PLAYLIST_ITEMS = 5_000
PLAYLIST_COLLECTION_KINDS = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos", "public_playlist"}
)
AUTH_REQUIRED_COLLECTION_KINDS = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos"}
)
REQUEST_MODES = frozenset({"candidate_metadata_only", "acquire_transcript"})
SAFE_REASON_CODES = frozenset(
    {
        "auth_missing",
        "auth_key_missing",
        "auth_expired",
        "auth_revoked",
        "quota_exhausted",
        "api_unavailable",
        "network_error",
        "source_gone",
        "source_unsupported",
        "policy_unsupported",
        "paused_source",
    }
)

_SAFE_REASON_DETAILS: dict[str, str] = {
    "auth_missing": "YouTube authentication is required for this source.",
    "auth_key_missing": "The YouTube token store is unavailable.",
    "auth_expired": "YouTube authentication has expired; reconnect the account.",
    "auth_revoked": "YouTube authentication was revoked; reconnect the account.",
    "quota_exhausted": "The YouTube Data API quota is exhausted for this quota window.",
    "api_unavailable": "The YouTube Data API is temporarily unavailable.",
    "network_error": "The YouTube Data API could not be reached.",
    "source_gone": "The playlist is unavailable or the account cannot access it.",
    "source_unsupported": (
        "Watch Later and Watch History are unsupported because the official YouTube Data API "
        "does not expose them; no cookie or browser-session fallback is used."
    ),
    "policy_unsupported": "The configured acquisition policy cannot be enforced safely.",
    "paused_source": "The source is disabled and was not polled.",
}


class SourcePollPersistenceError(RuntimeError):
    """A durable request/disposition could not be proven before cursor write."""


@dataclass(frozen=True)
class SourcePollResult:
    binding_id: str
    run_id: str
    discovered: int = 0
    enqueued: int = 0
    deduped: int = 0
    not_modified: bool = False
    backfill_needed: bool = False
    degraded: bool = False
    reason_code: str | None = None
    detail: str | None = None
    duration_ms: int = 0
    quota_units_spent: int = 0


def _raise_persistence_error() -> NoReturn:
    # Construct and raise outside the secret-bearing backend exception handler,
    # so neither message nor exception graph can escape INV-YSS-5.
    error = SourcePollPersistenceError("request persistence failed before cursor advance")
    error.__cause__ = None
    error.__context__ = None
    raise error from None


def _quota_spent(api_client: Any) -> int:
    quota_status = getattr(api_client, "quota_status", None)
    if not callable(quota_status):
        return 0
    try:
        value = quota_status().get("spent_today", 0)
    except Exception:
        return 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _emit(
    topic: str,
    payload: dict[str, Any],
    *,
    binding_id: str,
    fingerprint: str,
    trace_id: str,
) -> None:
    event = new_event(
        event_type=topic,
        payload=payload,
        trace_id=trace_id,
        source=EVENT_SOURCE,
    )
    write_outbox_event(
        event,
        idempotency_key=derive_idempotency_key(topic, binding_id, fingerprint),
    )


def _emit_discover_only(binding: SourceBinding, item: PlaylistItem, *, run_id: str) -> None:
    payload = {
        "binding_id": binding.binding_id,
        "collection_kind": binding.collection_kind,
        "collection_ref": binding.collection_ref,
        "item_ref": item.video_id,
        "playlist_item_id": item.playlist_item_id,
        "trigger": "poll",
    }
    event = new_event(
        event_type=YOUTUBE_SOURCE_DISCOVERED_TOPIC,
        payload=payload,
        trace_id=run_id,
        source=EVENT_SOURCE,
    )
    write_outbox_event(
        event,
        idempotency_key=discovered_event_key(binding.binding_id, item.video_id),
    )


def _successful_result(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    run_id: str,
    started: float,
    quota_before: int,
    quota_after: int,
    cursor: dict[str, Any],
    discovered: int,
    enqueued: int,
    deduped: int,
    not_modified: bool,
    backfill_needed: bool,
) -> SourcePollResult:
    registry.record_poll_success(
        binding.binding_id,
        expected_updated_at=binding.updated_at,
        cursor=cursor,
    )
    duration_ms = _duration_ms(started)
    quota_units_spent = max(0, quota_after - quota_before)
    payload = {
        "binding_id": binding.binding_id,
        "run_id": run_id,
        "discovered": discovered,
        "enqueued": enqueued,
        "deduped": deduped,
        "not_modified": not_modified,
        "duration_ms": duration_ms,
        "quota_units_spent": quota_units_spent,
    }
    _emit(
        YOUTUBE_SYNC_COMPLETED_TOPIC,
        payload,
        binding_id=binding.binding_id,
        fingerprint=run_id,
        trace_id=run_id,
    )
    return SourcePollResult(
        binding_id=binding.binding_id,
        run_id=run_id,
        discovered=discovered,
        enqueued=enqueued,
        deduped=deduped,
        not_modified=not_modified,
        backfill_needed=backfill_needed,
        duration_ms=duration_ms,
        quota_units_spent=quota_units_spent,
    )


def _degraded_result(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    run_id: str,
    started: float,
    reason_code: str,
    detail: str | None = None,
) -> SourcePollResult:
    normalized_reason = reason_code if reason_code in SAFE_REASON_CODES else "api_unavailable"
    safe_detail = detail or _SAFE_REASON_DETAILS[normalized_reason]
    registry.record_poll_failure(
        binding.binding_id,
        expected_updated_at=binding.updated_at,
        reason_code=normalized_reason,
        detail=safe_detail,
    )
    _emit(
        YOUTUBE_SYNC_DEGRADED_TOPIC,
        {
            "binding_id": binding.binding_id,
            "run_id": run_id,
            "reason_code": normalized_reason,
            "detail": safe_detail,
        },
        binding_id=binding.binding_id,
        fingerprint=run_id,
        trace_id=run_id,
    )
    return SourcePollResult(
        binding_id=binding.binding_id,
        run_id=run_id,
        degraded=True,
        reason_code=normalized_reason,
        detail=safe_detail,
        duration_ms=_duration_ms(started),
    )


def _known_item_ids(cursor: dict[str, Any]) -> list[str]:
    raw = cursor.get("known_playlist_item_ids", [])
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in raw:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dispositions(cursor: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = cursor.get("dispositions", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        item_ref = value.get("item_ref")
        outcome = value.get("outcome")
        if isinstance(item_ref, str) and isinstance(outcome, str):
            result[key] = {"item_ref": item_ref, "outcome": outcome}
    return result


def _next_cursor(
    prior: dict[str, Any],
    page: PlaylistItemsPage,
    outcomes: dict[str, dict[str, str]],
) -> dict[str, Any]:
    prior_known = _known_item_ids(prior)
    current_ids = [item.playlist_item_id for item in page.items]
    ordered = list(dict.fromkeys([*current_ids, *prior_known]))[:MAX_KNOWN_PLAYLIST_ITEMS]
    dispositions = _dispositions(prior)
    dispositions.update(outcomes)
    dispositions = {key: dispositions[key] for key in ordered if key in dispositions}
    prior_backfill = bool(prior.get("backfill_needed"))
    backfill_needed = page.pagination_truncated or prior_backfill
    backfill_page_token = (
        page.next_page_token
        if page.pagination_truncated
        else prior.get("backfill_page_token") if prior_backfill else None
    )
    return {
        "version": CURSOR_VERSION,
        "etag": page.etag if page.etag is not None else prior.get("etag"),
        "frontier_playlist_item_id": current_ids[0]
        if current_ids
        else prior.get("frontier_playlist_item_id"),
        "known_playlist_item_ids": ordered,
        "dispositions": dispositions,
        "backfill_needed": backfill_needed,
        "backfill_page_token": backfill_page_token,
    }


def poll_source(
    binding: SourceBinding,
    *,
    api_client: Any,
    requests: Any,
    registry: SourceRegistry,
) -> SourcePollResult:
    """Poll one playlist-shaped source and publish only a disposed frontier.

    ``binding`` is treated as an identity/input snapshot; the current durable
    row is re-read before egress so stale callers cannot overwrite current
    policy/cursor state.  Watch Later/History and missing Liked Videos auth are
    checked against the supplied snapshot first for defense in depth.
    """
    if not isinstance(binding, SourceBinding):
        raise TypeError("binding must be a SourceBinding")
    run_id = str(uuid.uuid4())
    started = time.monotonic()

    current = registry.get(binding.binding_id)
    if current is None:
        raise KeyError(f"no such binding: {binding.binding_id}")

    if binding.collection_ref in UNSUPPORTED_COLLECTION_REFS:
        return _degraded_result(
            current,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="source_unsupported",
            detail=_SAFE_REASON_DETAILS["source_unsupported"],
        )
    if binding.collection_kind in AUTH_REQUIRED_COLLECTION_KINDS and not binding.account_binding_id:
        return _degraded_result(
            current,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="auth_missing",
        )

    binding = current
    if binding.collection_kind not in PLAYLIST_COLLECTION_KINDS:
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="source_unsupported",
            detail="This source is not a playlist-shaped YouTube collection.",
        )
    if not binding.enabled:
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="paused_source",
        )

    policy = deepcopy(binding.acquisition_policy)
    mode = policy.get("mode")
    # YSS-01's delivered policy shape has no declared filter object and YSS-03
    # exposes no language/duration metadata.  Advancing as if the filter did
    # not match would silently discard intent, so this target-state mode stays
    # fail-closed until its policy/metadata contract is explicitly delivered.
    if mode == "acquire_if_filter_matches":
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="policy_unsupported",
        )
    if mode not in REQUEST_MODES and mode != "discover_only":
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="policy_unsupported",
        )

    prior_cursor = deepcopy(binding.cursor)
    known = set(_known_item_ids(prior_cursor))
    quota_before = _quota_spent(api_client)
    try:
        page = api_client.list_playlist_items(
            binding.collection_ref,
            etag=prior_cursor.get("etag") if isinstance(prior_cursor.get("etag"), str) else None,
            page_token=None,
        )
    except YouTubeApiError as exc:
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code=exc.reason_code,
        )
    except Exception as exc:
        reason_code = getattr(exc, "reason_code", "network_error")
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code=reason_code if isinstance(reason_code, str) else "network_error",
        )
    quota_after = _quota_spent(api_client)

    if isinstance(page, NotModified):
        return _successful_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            quota_before=quota_before,
            quota_after=quota_after,
            cursor=prior_cursor,
            discovered=0,
            enqueued=0,
            deduped=0,
            not_modified=True,
            backfill_needed=bool(prior_cursor.get("backfill_needed")),
        )
    if not isinstance(page, PlaylistItemsPage):
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="api_unavailable",
        )

    discovered = 0
    enqueued = 0
    deduped = 0
    outcomes: dict[str, dict[str, str]] = {}
    seen_in_response: set[str] = set()
    persistence_failed = False

    for item in page.items:
        if item.playlist_item_id in seen_in_response:
            continue
        seen_in_response.add(item.playlist_item_id)
        if item.playlist_item_id in known:
            continue
        discovered += 1
        if mode == "discover_only":
            try:
                _emit_discover_only(binding, item, run_id=run_id)
            except Exception:
                persistence_failed = True
                break
            outcomes[item.playlist_item_id] = {
                "item_ref": item.video_id,
                "outcome": "discover_only",
            }
            continue

        policy_version = policy.get("policy_version", 1)
        existing = None
        if isinstance(policy_version, int) and not isinstance(policy_version, bool):
            getter = getattr(requests, "get", None)
            if callable(getter):
                existing = getter(request_identity("youtube_url", item.video_id, policy_version))
        try:
            requests.enqueue(
                source_kind="youtube_url",
                item_ref=item.video_id,
                source_ref=f"https://www.youtube.com/watch?v={item.video_id}",
                trigger=DiscoveryTrigger(
                    binding_id=binding.binding_id,
                    collection_kind=binding.collection_kind,
                    collection_ref=binding.collection_ref,
                    trigger="poll",
                    playlist_item_id=item.playlist_item_id,
                ),
                priority=binding.priority,
                policy_snapshot=policy,
                trace_id=run_id,
            )
        except Exception:
            persistence_failed = True
            break
        if existing is None:
            enqueued += 1
            outcome = "request_enqueued"
        else:
            deduped += 1
            outcome = "request_deduped"
        outcomes[item.playlist_item_id] = {
            "item_ref": item.video_id,
            "outcome": outcome,
        }

    if persistence_failed:
        try:
            _degraded_result(
                binding,
                registry=registry,
                run_id=run_id,
                started=started,
                reason_code="network_error",
                detail="Durable request storage was unavailable; the cursor was not advanced.",
            )
        except Exception:
            # The durable-store/outbox boundary may itself be the failed
            # dependency. Never replace the stable public failure with a raw
            # backend exception or advance the cursor to manufacture success.
            pass
        _raise_persistence_error()

    cursor = _next_cursor(prior_cursor, page, outcomes)
    return _successful_result(
        binding,
        registry=registry,
        run_id=run_id,
        started=started,
        quota_before=quota_before,
        quota_after=quota_after,
        cursor=cursor,
        discovered=discovered,
        enqueued=enqueued,
        deduped=deduped,
        not_modified=False,
        backfill_needed=bool(cursor["backfill_needed"]),
    )


__all__ = [
    "SourcePollPersistenceError",
    "SourcePollResult",
    "YOUTUBE_SYNC_COMPLETED_TOPIC",
    "YOUTUBE_SYNC_DEGRADED_TOPIC",
    "poll_source",
]
