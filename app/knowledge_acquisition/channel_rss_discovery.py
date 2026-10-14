"""Bounded, conservative YSS-07 subscription RSS discovery.

This adapter turns a channel's newest YouTube RSS entries into durable
discovery dispositions and optional AcquisitionRequests. It never writes vault
notes. The request/discovery rows and events are persisted before the registry
cursor advances, so a retry converges through the existing idempotency keys.
"""

from __future__ import annotations

import math
import os
import re
import time
import uuid
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.config.database import explicit_runtime_database_url
from app.events.models import new_event
from app.events.types import YOUTUBE_SYNC_COMPLETED, YOUTUBE_SYNC_DEGRADED
from app.knowledge_acquisition.acquisition_requests import (
    AcquisitionRequests,
    AcquisitionRequestPolicyConflictError,
    DiscoveryTrigger,
    request_identity,
)
from app.knowledge_acquisition.source_registry import (
    ISO_639_1_LANGUAGE_CODES,
    SourceBinding,
    SourceRegistry,
    SourceRegistryValidationError,
)
from app.knowledge_acquisition.youtube_plugin import MetadataAcquisitionError, yt_dlp_extract_metadata
from app.services.outbox import derive_idempotency_key, open_outbox_txn_conn, write_outbox_event
from app.source_egress import assert_source_egress_allowed

ATOM = "{http://www.w3.org/2005/Atom}"
YOUTUBE = "{http://www.youtube.com/xml/schemas/2015}"
MAX_FEED_BYTES = 1_048_576
MAX_FEED_ENTRIES = 100
MAX_RECENT_ENTRY_IDS = 50
HTTP_TIMEOUT_SECONDS = 10
CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}\Z")
LANGUAGE_CODE_RE = re.compile(r"[a-z]{2}\Z")


class RSSFeedError(ValueError):
    """A bounded, reason-coded RSS fetch or parse refusal."""

    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class RSSVideo:
    entry_id: str
    video_id: str
    channel_id: str
    published_at: datetime


@dataclass(frozen=True)
class ChannelRSSPollResult:
    binding_id: str
    run_id: str
    discovered: int = 0
    enqueued: int = 0
    deduped: int = 0
    filtered_out: int = 0
    not_modified: bool = False
    duration_ms: int = 0
    degraded: bool = False
    reason_code: str | None = None
    detail: str | None = None


def build_feed_url(channel_id: str) -> str:
    if not isinstance(channel_id, str) or CHANNEL_ID_RE.fullmatch(channel_id) is None:
        raise RSSFeedError("source_mismatch", "The subscription channel id is invalid.")
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def fetch_channel_feed(channel_id: str) -> bytes:
    """Fetch one fixed-host, bounded RSS response; redirects are refused."""
    url = build_feed_url(channel_id)
    assert_source_egress_allowed("channel_rss_discovery.fetch_channel_feed")
    request = Request(url, headers={"Accept": "application/atom+xml, application/xml"})
    opener = build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            final_url = response.geturl()
            if final_url != url:
                raise RSSFeedError("rss_feed_unavailable", "The RSS endpoint redirected; redirects are refused.")
            content = response.read(MAX_FEED_BYTES + 1)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RSSFeedError("rss_feed_unavailable", "The RSS endpoint redirected; redirects are refused.") from exc
        raise RSSFeedError("rss_feed_unavailable", "The RSS endpoint returned an unsuccessful response.") from exc
    except URLError as exc:
        raise RSSFeedError("network_error", "The RSS endpoint could not be reached.") from exc
    except TimeoutError as exc:
        raise RSSFeedError("network_error", "The RSS request timed out.") from exc
    if len(content) > MAX_FEED_BYTES:
        raise RSSFeedError("rss_feed_too_large", "The RSS response exceeded the configured size limit.")
    return content


def _parse_published(value: str | None) -> datetime:
    if not value:
        raise RSSFeedError("rss_feed_invalid", "An RSS entry is missing its published timestamp.")
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            published = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RSSFeedError("rss_feed_invalid", "An RSS entry has an invalid published timestamp.") from exc
    if published.tzinfo is None:
        raise RSSFeedError("rss_feed_invalid", "An RSS entry timestamp has no timezone.")
    return published.astimezone(timezone.utc)


def parse_channel_feed(content: bytes, *, expected_channel_id: str) -> tuple[RSSVideo, ...]:
    if not isinstance(content, bytes):
        raise RSSFeedError("rss_feed_invalid", "The RSS response was not bytes.")
    if len(content) > MAX_FEED_BYTES:
        raise RSSFeedError("rss_feed_too_large", "The RSS response exceeded the configured size limit.")
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RSSFeedError("rss_feed_invalid", "The RSS response was not valid UTF-8 XML.") from exc
    # XML 1.0 does not permit NUL characters. Reject them before ElementTree
    # can auto-detect a BOM-less UTF-16 byte pattern and reinterpret the feed.
    if "\x00" in decoded:
        raise RSSFeedError("rss_feed_invalid", "The RSS response contained prohibited NUL bytes.")
    upper = decoded.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise RSSFeedError("rss_feed_invalid", "DTD and entity declarations are refused.")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise RSSFeedError("rss_feed_invalid", "The RSS response was not valid XML.") from exc
    if root.tag != f"{ATOM}feed":
        raise RSSFeedError("rss_feed_invalid", "The RSS document is not an Atom feed.")
    feed_channel_id = (root.findtext(f"{YOUTUBE}channelId") or "").strip()
    if feed_channel_id != expected_channel_id:
        raise RSSFeedError("source_mismatch", "The RSS response channel did not match the requested subscription.")

    entries: list[RSSVideo] = []
    seen: set[str] = set()
    for entry in root.findall(f"{ATOM}entry"):
        if len(entries) >= MAX_FEED_ENTRIES:
            raise RSSFeedError("rss_feed_invalid", "The RSS response contained too many entries.")
        video_id = (entry.findtext(f"{YOUTUBE}videoId") or "").strip()
        entry_id = (entry.findtext(f"{ATOM}id") or "").strip()
        entry_channel_id = (entry.findtext(f"{YOUTUBE}channelId") or feed_channel_id).strip()
        if (
            VIDEO_ID_RE.fullmatch(video_id) is None
            or not entry_id
            or "\x00" in entry_id
            or entry_channel_id != expected_channel_id
        ):
            raise RSSFeedError("rss_feed_invalid", "The RSS response contained an invalid or mismatched entry.")
        if entry_id in seen:
            continue
        seen.add(entry_id)
        published = _parse_published(entry.findtext(f"{ATOM}published"))
        entries.append(
            RSSVideo(
                entry_id=entry_id,
                video_id=video_id,
                channel_id=entry_channel_id,
                published_at=published,
            )
        )
    if not entries:
        raise RSSFeedError("rss_feed_invalid", "The RSS feed contained no usable entries.")
    entries.sort(key=lambda item: (item.published_at, item.entry_id), reverse=True)
    return tuple(entries)


def _cursor_state(cursor: dict[str, Any]) -> tuple[datetime | None, list[str]]:
    newest_raw = cursor.get("newest_published_seen")
    newest = None
    if newest_raw is not None:
        if not isinstance(newest_raw, str):
            raise RSSFeedError("rss_feed_invalid", "The stored RSS cursor timestamp is invalid.")
        newest = _parse_published(newest_raw)
    recent = cursor.get("recent_entry_ids", [])
    if not isinstance(recent, list) or not all(isinstance(value, str) and value for value in recent):
        raise RSSFeedError("rss_feed_invalid", "The stored RSS cursor entry ids are invalid.")
    if len(recent) > MAX_RECENT_ENTRY_IDS:
        raise RSSFeedError("rss_feed_invalid", "The stored RSS cursor exceeds its entry-id limit.")
    return newest, list(dict.fromkeys(recent))


def _filter_matches(
    binding: SourceBinding,
    filters: dict[str, Any],
    *,
    metadata_fetcher: Callable[[str], dict[str, Any]],
    video_id: str,
) -> bool:
    channels = filters.get("channel_allowlist")
    if channels is not None and binding.collection_ref not in channels:
        return False
    language_allowlist = filters.get("language_allowlist")
    minimum = filters.get("min_duration_seconds")
    maximum = filters.get("max_duration_seconds")
    if language_allowlist is None and minimum is None and maximum is None:
        return True
    try:
        metadata = metadata_fetcher(f"https://www.youtube.com/watch?v={video_id}")
    except Exception as exc:
        raise RSSFeedError(
            "filter_metadata_unavailable", "Required metadata for the subscription filter was unavailable."
        ) from exc
    if not isinstance(metadata, dict):
        raise RSSFeedError("filter_metadata_unavailable", "Required metadata for the subscription filter was unavailable.")
    if language_allowlist is not None:
        language = metadata.get("language")
        if not isinstance(language, str) or not language.strip():
            raise RSSFeedError("filter_metadata_unavailable", "The video language was unavailable.")
        primary_language = language.strip().partition("-")[0].lower()
        if (
            LANGUAGE_CODE_RE.fullmatch(primary_language) is None
            or primary_language not in ISO_639_1_LANGUAGE_CODES
        ):
            raise RSSFeedError("filter_metadata_unavailable", "The video language was unavailable.")
        if primary_language not in language_allowlist:
            return False
    if minimum is not None or maximum is not None:
        duration = metadata.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, int | float) or not math.isfinite(duration):
            raise RSSFeedError("filter_metadata_unavailable", "The video duration was unavailable.")
        if minimum is not None and duration < minimum:
            return False
        if maximum is not None and duration > maximum:
            return False
    return True


def _write_sync_event(topic: str, payload: dict[str, Any], *, run_id: str, binding_id: str, conn: Any) -> None:
    event = new_event(
        event_type=topic,
        payload=payload,
        trace_id=run_id,
        source="knowledge_acquisition.source_sync",
    )
    write_outbox_event(
        event,
        conn=conn,
        idempotency_key=derive_idempotency_key(topic, binding_id, run_id),
        required_db=_transaction_required(),
    )


def _has_named_database() -> bool:
    return explicit_runtime_database_url(os.environ) is not None


def _transaction_required() -> bool:
    return _has_named_database() or (os.environ.get("STORE_BACKEND") or "").strip().lower() == "pg"


def _finish_success(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    run_id: str,
    cursor: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    conn = open_outbox_txn_conn()
    if conn is None and _transaction_required():
        raise RuntimeError("Could not open a transaction for the subscription cursor and completion receipt.")
    try:
        if conn is None:
            _write_sync_event(
                YOUTUBE_SYNC_COMPLETED,
                payload,
                run_id=run_id,
                binding_id=binding.binding_id,
                conn=None,
            )
            registry.record_poll_success(binding.binding_id, cursor=cursor)
            return
        with conn.transaction():
            registry.record_poll_success(binding.binding_id, cursor=cursor, transaction_conn=conn)
            _write_sync_event(
                YOUTUBE_SYNC_COMPLETED,
                payload,
                run_id=run_id,
                binding_id=binding.binding_id,
                conn=conn,
            )
    finally:
        if conn is not None:
            conn.close()


def _finish_degraded(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    run_id: str,
    reason_code: str,
    detail: str,
    duration_ms: int,
) -> ChannelRSSPollResult:
    payload = {
        "binding_id": binding.binding_id,
        "collection_kind": "subscription_feed",
        "collection_ref": binding.collection_ref,
        "run_id": run_id,
        "reason_code": reason_code,
        "detail": detail[:240],
        "duration_ms": duration_ms,
    }
    conn = open_outbox_txn_conn()
    if conn is None and _transaction_required():
        raise RuntimeError("Could not open a transaction for the subscription degradation receipt.")
    try:
        if conn is None:
            _write_sync_event(
                YOUTUBE_SYNC_DEGRADED,
                payload,
                run_id=run_id,
                binding_id=binding.binding_id,
                conn=None,
            )
            registry.record_poll_failure(binding.binding_id, reason_code=reason_code, detail=detail)
        else:
            with conn.transaction():
                registry.record_poll_failure(
                    binding.binding_id,
                    reason_code=reason_code,
                    detail=detail,
                    transaction_conn=conn,
                )
                _write_sync_event(
                    YOUTUBE_SYNC_DEGRADED,
                    payload,
                    run_id=run_id,
                    binding_id=binding.binding_id,
                    conn=conn,
                )
    finally:
        if conn is not None:
            conn.close()
    return ChannelRSSPollResult(
        binding_id=binding.binding_id,
        run_id=run_id,
        duration_ms=duration_ms,
        degraded=True,
        reason_code=reason_code,
        detail=detail,
    )


def poll_source(
    binding: SourceBinding,
    *,
    registry: SourceRegistry,
    requests: AcquisitionRequests,
    fetch_feed: Callable[[str], bytes] = fetch_channel_feed,
    metadata_fetcher: Callable[[str], dict[str, Any]] = yt_dlp_extract_metadata,
) -> ChannelRSSPollResult:
    """Poll one subscription binding and advance only after each item is disposed."""
    if not isinstance(binding, SourceBinding):
        raise TypeError("binding must be a SourceBinding")
    run_id = str(uuid.uuid4())
    started = time.monotonic()

    current = registry.get(binding.binding_id)
    if current is None:
        raise KeyError(f"no such binding: {binding.binding_id}")
    binding = current
    if binding.collection_kind != "subscription_feed":
        raise SourceRegistryValidationError("the channel RSS poller accepts only subscription_feed bindings")
    if binding.discovery_mode != "rss_poll":
        return _finish_degraded(
            binding,
            registry=registry,
            run_id=run_id,
            reason_code="policy_unsupported",
            detail="This poller accepts only RSS subscription bindings.",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    if not binding.enabled:
        return _finish_degraded(
            binding,
            registry=registry,
            run_id=run_id,
            reason_code="paused_source",
            detail="This subscription binding is disabled.",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
    if CHANNEL_ID_RE.fullmatch(binding.collection_ref) is None:
        return _finish_degraded(
            binding,
            registry=registry,
            run_id=run_id,
            reason_code="source_mismatch",
            detail="The subscription channel id is invalid.",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    policy = deepcopy(binding.acquisition_policy)
    mode = policy.get("mode")
    if mode not in {"discover_only", "candidate_metadata_only", "acquire_transcript", "acquire_if_filter_matches"}:
        return _finish_degraded(
            binding,
            registry=registry,
            run_id=run_id,
            reason_code="policy_unsupported",
            detail="The stored acquisition policy is not supported by this discovery path.",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )

    try:
        cursor = deepcopy(binding.cursor)
        newest_seen, prior_recent = _cursor_state(cursor)
        feed = parse_channel_feed(fetch_feed(binding.collection_ref), expected_channel_id=binding.collection_ref)
        prior_ids = set(prior_recent)
        new_entries = [entry for entry in feed if entry.entry_id not in prior_ids]
        enqueued = deduped = filtered_out = 0

        for entry in new_entries:
            trigger = DiscoveryTrigger(
                binding_id=binding.binding_id,
                collection_kind=binding.collection_kind,
                collection_ref=binding.collection_ref,
                trigger="poll",
            )
            if mode == "discover_only":
                requests.record_discovery(item_ref=entry.video_id, trigger=trigger, trace_id=run_id)
                continue

            effective_policy = policy
            if mode == "acquire_if_filter_matches":
                filters = policy.get("filters")
                if not isinstance(filters, dict) or not filters:
                    raise SourceRegistryValidationError(
                        "acquire_if_filter_matches requires a validated non-empty filters object"
                    )
                if not _filter_matches(
                    binding,
                    filters,
                    metadata_fetcher=metadata_fetcher,
                    video_id=entry.video_id,
                ):
                    requests.record_discovery(item_ref=entry.video_id, trigger=trigger, trace_id=run_id)
                    filtered_out += 1
                    continue
                effective_policy = dict(policy)
                effective_policy.pop("filters", None)
                effective_policy["mode"] = "acquire_transcript"

            policy_version = effective_policy.get("policy_version", 1)
            existing = requests.get(request_identity("youtube_url", entry.video_id, policy_version))
            try:
                requests.enqueue(
                    source_kind="youtube_url",
                    item_ref=entry.video_id,
                    source_ref=f"https://www.youtube.com/watch?v={entry.video_id}",
                    trigger=trigger,
                    priority=binding.priority,
                    policy_snapshot=effective_policy,
                    trace_id=run_id,
                )
            except AcquisitionRequestPolicyConflictError:
                requests.record_discovery(item_ref=entry.video_id, trigger=trigger, trace_id=run_id)
                raise
            if existing is None:
                enqueued += 1
            else:
                deduped += 1

        current_newest = max((entry.published_at for entry in feed), default=newest_seen)
        if newest_seen is not None and current_newest is not None:
            current_newest = max(newest_seen, current_newest)
        recent_ids = list(dict.fromkeys([*(entry.entry_id for entry in feed), *prior_recent]))[:MAX_RECENT_ENTRY_IDS]
        next_cursor = {
            "version": 1,
            "newest_published_seen": current_newest.isoformat() if current_newest is not None else None,
            "recent_entry_ids": recent_ids,
        }
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        payload = {
            "binding_id": binding.binding_id,
            "collection_kind": "subscription_feed",
            "collection_ref": binding.collection_ref,
            "run_id": run_id,
            "discovered": len(new_entries),
            "enqueued": enqueued,
            "deduped": deduped,
            "filtered_out": filtered_out,
            "not_modified": False,
            "duration_ms": duration_ms,
            "quota_units_spent": 0,
        }
        _finish_success(binding, registry=registry, run_id=run_id, cursor=next_cursor, payload=payload)
        return ChannelRSSPollResult(
            binding_id=binding.binding_id,
            run_id=run_id,
            discovered=len(new_entries),
            enqueued=enqueued,
            deduped=deduped,
            filtered_out=filtered_out,
            duration_ms=duration_ms,
        )
    except RSSFeedError as exc:
        reason_code, detail = exc.reason_code, exc.detail
    except MetadataAcquisitionError:
        reason_code, detail = "filter_metadata_unavailable", "Required metadata for the subscription filter was unavailable."
    except AcquisitionRequestPolicyConflictError:
        reason_code, detail = "policy_conflict", "The video already has a request with a different acquisition policy."
    except Exception:
        reason_code, detail = "network_error", "The discovery or durable persistence step failed."
    return _finish_degraded(
        binding,
        registry=registry,
        run_id=run_id,
        reason_code=reason_code,
        detail=detail,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
    )


__all__ = [
    "ChannelRSSPollResult",
    "MAX_FEED_BYTES",
    "RSSFeedError",
    "RSSVideo",
    "build_feed_url",
    "fetch_channel_feed",
    "parse_channel_feed",
    "poll_source",
]
