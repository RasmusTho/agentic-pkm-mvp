"""YouTube Source Sync V1: one account, one enabled Inbox playlist.

The adapter enumerates only through the delivered YSS-03 client, disposes
each new Inbox playlist-item identity through the delivered YSS-04 request
queue, and only then publishes the YSS-01 cursor. A failed API/auth/network
poll never mutates cursor/known state and never emits an empty-success receipt.

Owned/public/Liked playlists, scheduling, leases, backfill, and automatic
knowledge promotion are deliberately absent from this V1 surface.
"""

from __future__ import annotations

import time
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, NoReturn

from app.knowledge_acquisition.acquisition_requests import (
    DiscoveryTrigger,
    request_identity,
)
from app.knowledge_acquisition.source_registry import SourceBinding, SourceRegistry
from app.knowledge_acquisition.youtube_api_client import (
    NotModified,
    PlaylistItemsPage,
    YouTubeApiError,
)
CURSOR_VERSION = 1
MAX_KNOWN_PLAYLIST_ITEMS = 5_000
V1_COLLECTION_KIND = "inbox_playlist"
V1_REQUEST_MODE = "acquire_transcript"
SAFE_REASON_CODES = frozenset(
    {
        "auth_missing",
        "auth_key_missing",
        "auth_expired",
        "auth_revoked",
        "auth_disconnected",
        "quota_exhausted",
        "api_unavailable",
        "network_error",
        "source_gone",
        "policy_unsupported",
        "paused_source",
        "inbox_missing",
    }
)

_SAFE_REASON_DETAILS: dict[str, str] = {
    "auth_missing": "YouTube authentication is required for this source.",
    "auth_key_missing": "The YouTube token store is unavailable.",
    "auth_expired": "YouTube authentication has expired; reconnect the account.",
    "auth_revoked": "YouTube authentication was revoked; reconnect the account.",
    "auth_disconnected": "The YouTube account was disconnected.",
    "quota_exhausted": "The YouTube Data API quota is exhausted for this quota window.",
    "api_unavailable": "The YouTube Data API is temporarily unavailable.",
    "network_error": "The YouTube Data API could not be reached.",
    "source_gone": "The playlist is unavailable or the account cannot access it.",
    "policy_unsupported": "The configured acquisition policy cannot be enforced safely.",
    "paused_source": "The source is disabled and was not polled.",
    "inbox_missing": "No YouTube Inbox playlist is configured for this account.",
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
    degraded: bool = False
    reason_code: str | None = None
    detail: str | None = None
    duration_ms: int = 0
    quota_units_spent: int = 0


class V1InboxConfigurationError(ValueError):
    """The one-Inbox product boundary was violated."""


def _raise_persistence_error() -> NoReturn:
    # Construct and raise outside the secret-bearing backend exception handler,
    # so neither message nor exception graph can escape INV-YSS-5.
    error = SourcePollPersistenceError(
        "source sync persistence failed before a confirmed outcome"
    )
    error.__cause__ = None
    error.__context__ = None
    raise error from None


def _best_effort_persistence_degradation(
    binding_id: str,
    registry: SourceRegistry,
) -> None:
    """Record a fixed failure without ever forwarding backend diagnostics."""

    try:
        registry.record_poll_failure(
            binding_id,
            reason_code="network_error",
            detail="Durable source-sync storage was unavailable; retry the manual sync.",
        )
    except Exception:
        # A failed status store cannot safely provide more detail. The detached
        # public exception below remains the only caller-visible diagnostic.
        pass


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
) -> SourcePollResult:
    persistence_failed = False
    try:
        registry.record_poll_success(
            binding.binding_id,
            cursor=cursor,
        )
    except Exception:
        persistence_failed = True
    if persistence_failed:
        recovered: SourceBinding | None = None
        try:
            recovered = registry.get(binding.binding_id)
        except Exception:
            pass
        # An autocommit write can succeed server-side while the client loses
        # its RETURNING response. Reconcile only the exact intended cursor and
        # clean success state; every other outcome remains a detached failure.
        if not (
            recovered is not None
            and recovered.cursor == cursor
            and recovered.last_success_at is not None
            and recovered.last_error is None
            and (
                recovered.cursor != binding.cursor
                or recovered.last_success_at != binding.last_success_at
                or recovered.last_attempt_at != binding.last_attempt_at
            )
        ):
            _best_effort_persistence_degradation(binding.binding_id, registry)
            _raise_persistence_error()
    duration_ms = _duration_ms(started)
    quota_units_spent = max(0, quota_after - quota_before)
    return SourcePollResult(
        binding_id=binding.binding_id,
        run_id=run_id,
        discovered=discovered,
        enqueued=enqueued,
        deduped=deduped,
        not_modified=not_modified,
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
    persistence_failed = False
    try:
        registry.record_poll_failure(
            binding.binding_id,
            reason_code=normalized_reason,
            detail=safe_detail,
        )
    except Exception:
        persistence_failed = True
    if persistence_failed:
        _raise_persistence_error()
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
    return {
        "version": CURSOR_VERSION,
        "etag": page.etag if page.etag is not None else prior.get("etag"),
        "frontier_playlist_item_id": current_ids[0]
        if current_ids
        else prior.get("frontier_playlist_item_id"),
        "known_playlist_item_ids": ordered,
        "dispositions": dispositions,
    }


def poll_source(
    binding: SourceBinding,
    *,
    api_client: Any,
    requests: Any,
    registry: SourceRegistry,
) -> SourcePollResult:
    """Poll the one enabled V1 Inbox and publish only a disposed frontier.

    ``binding`` is treated as an identity/input snapshot; the current durable
    row is re-read before egress so stale callers cannot overwrite current
    policy/cursor state. The production boundary refuses every other source
    kind even though the underlying registry contains future-facing shapes.
    """
    if not isinstance(binding, SourceBinding):
        raise TypeError("binding must be a SourceBinding")
    run_id = str(uuid.uuid4())
    started = time.monotonic()

    current: SourceBinding | None = None
    persistence_failed = False
    try:
        current = registry.get(binding.binding_id)
    except Exception:
        persistence_failed = True
    if persistence_failed:
        _best_effort_persistence_degradation(binding.binding_id, registry)
        _raise_persistence_error()
    if current is None:
        raise KeyError(f"no such binding: {binding.binding_id}")

    if current.collection_kind != V1_COLLECTION_KIND:
        raise V1InboxConfigurationError("V1 sync accepts only one inbox_playlist")
    if not current.account_binding_id:
        return _degraded_result(
            current,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code="auth_missing",
        )

    binding = current
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
    if mode != V1_REQUEST_MODE:
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
    page: Any = None
    failure_reason: str | None = None
    try:
        page = api_client.list_playlist_items(
            binding.collection_ref,
            etag=prior_cursor.get("etag") if isinstance(prior_cursor.get("etag"), str) else None,
            page_token=None,
        )
    except YouTubeApiError as exc:
        failure_reason = exc.reason_code
    except Exception as exc:
        reason_code = getattr(exc, "reason_code", "network_error")
        failure_reason = reason_code if isinstance(reason_code, str) else "network_error"
    if failure_reason is not None:
        return _degraded_result(
            binding,
            registry=registry,
            run_id=run_id,
            started=started,
            reason_code=failure_reason,
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
        try:
            policy_version = policy.get("policy_version", 1)
            existing = None
            if isinstance(policy_version, int) and not isinstance(policy_version, bool):
                getter = getattr(requests, "get", None)
                if callable(getter):
                    existing = getter(
                        request_identity("youtube_url", item.video_id, policy_version)
                    )
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
    )


class YouTubeInboxSyncV1:
    """Minimal operator route for selecting, syncing, and inspecting one Inbox."""

    def __init__(
        self,
        *,
        account_binding_id: str,
        registry: SourceRegistry,
        requests: Any,
        api_client: Any,
        oauth_status: Callable[[str], dict[str, Any]],
    ) -> None:
        self._account_binding_id = account_binding_id
        self._registry = registry
        self._requests = requests
        self._api_client = api_client
        self._oauth_status = oauth_status

    def select_inbox(
        self,
        *,
        playlist_ref: str,
        title: str,
    ) -> SourceBinding:
        """Configure the sole V1 Inbox; a second product Inbox is refused."""

        if playlist_ref == "LL":
            raise V1InboxConfigurationError(
                "V1 Inbox must be an ordinary owned playlist; Liked Videos is unavailable"
            )

        rows = self._registry_call(
            lambda: self._registry.list_for_account(self._account_binding_id)
        )
        enabled = [
            row
            for row in rows
            if row.collection_kind == V1_COLLECTION_KIND and row.enabled
        ]
        if len(enabled) > 1:
            raise V1InboxConfigurationError("V1 requires exactly one enabled Inbox")
        if enabled:
            if enabled[0].collection_ref == playlist_ref:
                return enabled[0]
            raise V1InboxConfigurationError(
                "V1 already has an enabled Inbox; generic multi-playlist configuration is unavailable"
            )

        existing = next(
            (
                row
                for row in rows
                if row.collection_kind == V1_COLLECTION_KIND
                and row.collection_ref == playlist_ref
            ),
            None,
        )
        target = existing or self._registry_call(
            lambda: self._registry.register(
                collection_kind=V1_COLLECTION_KIND,
                collection_ref=playlist_ref,
                title=title,
                account_binding_id=self._account_binding_id,
            )
        )
        return self._registry_call(
            lambda: self._registry.set_inbox(
                self._account_binding_id, target.binding_id
            )
        )

    def sync_now(self) -> dict[str, Any]:
        """Run one synchronous production poll and return a secret-free receipt."""

        binding = self._enabled_inbox()
        result = poll_source(
            binding,
            api_client=self._api_client,
            requests=self._requests,
            registry=self._registry,
        )
        return {
            "status": "degraded" if result.degraded else "connected",
            "discovered": result.discovered,
            "enqueued": result.enqueued,
            "deduped": result.deduped,
            "not_modified": result.not_modified,
            "reason_code": result.reason_code,
        }

    def status(self) -> dict[str, Any]:
        """Expose connected/degraded, last success, and one sanitized error."""

        try:
            auth = self._oauth_status(self._account_binding_id)
        except Exception:
            return {
                "status": "degraded",
                "last_success_at": None,
                "latest_error": self._sanitized_error("api_unavailable"),
            }
        auth_state = auth.get("status") if isinstance(auth, dict) else None
        try:
            rows = self._registry_call(
                lambda: self._registry.list_for_account(self._account_binding_id)
            )
        except SourcePollPersistenceError:
            return {
                "status": "degraded",
                "last_success_at": None,
                "latest_error": self._sanitized_error("network_error"),
            }
        enabled = [
            row
            for row in rows
            if row.collection_kind == V1_COLLECTION_KIND and row.enabled
        ]
        if len(enabled) != 1:
            return {
                "status": "degraded",
                "last_success_at": None,
                "latest_error": self._sanitized_error("inbox_missing"),
            }
        binding = enabled[0]
        latest_error = self._sanitized_stored_error(binding.last_error)
        if auth_state != "connected" and latest_error is None:
            reason = auth.get("reason_code") if isinstance(auth, dict) else None
            latest_error = self._sanitized_error(
                reason if isinstance(reason, str) else "auth_missing"
            )
        return {
            "status": "connected"
            if auth_state == "connected" and latest_error is None
            else "degraded",
            "last_success_at": binding.last_success_at,
            "latest_error": latest_error,
        }

    def _enabled_inbox(self) -> SourceBinding:
        rows = self._registry_call(
            lambda: self._registry.list_for_account(self._account_binding_id)
        )
        enabled = [
            row
            for row in rows
            if row.collection_kind == V1_COLLECTION_KIND and row.enabled
        ]
        if len(enabled) != 1:
            raise V1InboxConfigurationError("V1 requires exactly one enabled Inbox")
        return enabled[0]

    @staticmethod
    def _registry_call(operation: Callable[[], Any]) -> Any:
        """Run one registry operation behind the detached public error seam."""

        failed = False
        result: Any = None
        try:
            result = operation()
        except Exception:
            failed = True
        if failed:
            _raise_persistence_error()
        return result

    @staticmethod
    def _sanitized_error(reason_code: str, *, at: str | None = None) -> dict[str, Any]:
        safe_reason = reason_code if reason_code in SAFE_REASON_CODES else "api_unavailable"
        result: dict[str, Any] = {
            "reason_code": safe_reason,
            "detail": _SAFE_REASON_DETAILS[safe_reason],
        }
        if at is not None:
            result["at"] = at
        return result

    @classmethod
    def _sanitized_stored_error(cls, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        reason = value.get("reason_code")
        at = value.get("at")
        return cls._sanitized_error(
            reason if isinstance(reason, str) else "api_unavailable",
            at=at if isinstance(at, str) else None,
        )


__all__ = [
    "SourcePollPersistenceError",
    "SourcePollResult",
    "V1InboxConfigurationError",
    "YouTubeInboxSyncV1",
    "poll_source",
]
