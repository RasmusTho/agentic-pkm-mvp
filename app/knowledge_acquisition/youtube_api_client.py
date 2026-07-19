"""YSS-03 (#3918): bounded read-only YouTube Data API v3 client.

This module is the single Data API boundary for YouTube Source Sync. It owns
the absolute ``www.googleapis.com`` allowlist, input validation, pagination
and payload bounds, conditional ETag reads, secret-free error taxonomy, and
durable per-UTC-day quota accounting required by
``docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md``.

The quota store follows the existing YSS store discipline: an explicit memory
backend for ``not pg`` tests and a migration-owned Postgres table for runtime.
A configured-but-unreachable Postgres backend never silently falls back to
volatile memory (INV-YSS-7).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.db.dsn import resolve_dsn

ALLOWED_DATA_API_HOST = "www.googleapis.com"
DEFAULT_BASE_URL = "https://www.googleapis.com/youtube/v3/"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_PAGES = 10
DEFAULT_QUOTA_BUDGET = 10_000
MAX_PAGE_TOKEN_LENGTH = 2_048

_TABLE = "youtube_api_quota_daily"
_MIGRATION_HINT = (
    "youtube_api_quota_daily schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See "
    "app/alembic/versions/d9e0f1a2b3c4_yss03_youtube_api_quota.py."
)
_ALLOWED_BACKENDS = {"memory", "pg"}
_SAFE_REF = re.compile(r"^[A-Za-z0-9_-]+$")
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_QUOTA_REASONS = frozenset(
    {
        "quotaExceeded",
        "dailyLimitExceeded",
        "rateLimitExceeded",
        "userRateLimitExceeded",
    }
)


class AccessTokenProvider(Protocol):
    """The YSS-02 token-provider port consumed by this client."""

    def get_access_token(self) -> str: ...


class InvalidYouTubeRefError(ValueError):
    """A source-native id or opaque page token failed local validation."""


class DisallowedYouTubeHostError(ValueError):
    """A request or redirect targeted a host outside the Data API allowlist."""


class YouTubeQuotaSchemaMissingError(RuntimeError):
    """The runtime selected Postgres but its migration-owned table is absent."""


class YouTubeApiError(RuntimeError):
    """Safe, structured Data API failure.

    ``detail`` is constructed only from local classifications and status
    values. Provider bodies, URLs, headers, and exception text are never
    copied into it (INV-YSS-5).
    """

    def __init__(self, reason_code: str, status: int | None, detail: str) -> None:
        self.reason_code = reason_code
        self.status = status
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}")


@dataclass(frozen=True)
class Playlist:
    playlist_id: str
    title: str
    item_count: int


@dataclass(frozen=True)
class PlaylistItem:
    playlist_item_id: str
    video_id: str
    position: int
    published_at: str
    title: str


@dataclass(frozen=True)
class PlaylistListResult:
    items: tuple[Playlist, ...]
    next_page_token: str | None
    pagination_truncated: bool


@dataclass(frozen=True)
class PlaylistItemsPage:
    items: tuple[PlaylistItem, ...]
    next_page_token: str | None
    etag: str | None
    pagination_truncated: bool
    not_modified: bool = False


@dataclass(frozen=True)
class NotModified:
    etag: str | None
    not_modified: bool = True


@dataclass(frozen=True)
class Channel:
    channel_id: str
    title: str
    liked_videos_ref: str = "LL"


@dataclass(frozen=True)
class _QuotaRow:
    quota_date: str
    spent: int
    exhausted: bool


def validate_video_id(value: str) -> str:
    if not isinstance(value, str) or not _VIDEO_ID.fullmatch(value):
        raise InvalidYouTubeRefError("video id must be exactly 11 URL-safe characters")
    return value


def validate_playlist_id(value: str) -> str:
    if not isinstance(value, str) or not value or not _SAFE_REF.fullmatch(value):
        raise InvalidYouTubeRefError("playlist id must be a non-empty URL-safe source id")
    if value in {"WL", "HL"}:
        raise InvalidYouTubeRefError("Watch Later and Watch History are unsupported")
    if value != "LL" and not value.startswith(("PL", "UU", "LL")):
        raise InvalidYouTubeRefError("playlist id must use the PL, UU, or LL source-id shape")
    return value


def validate_channel_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("UC")
        or len(value) <= 2
        or not _SAFE_REF.fullmatch(value)
    ):
        raise InvalidYouTubeRefError("channel id must use the UC source-id shape")
    return value


def _validate_page_token(value: str | None) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_PAGE_TOKEN_LENGTH
        or "\x00" in value
    ):
        raise InvalidYouTubeRefError("page token must be a bounded non-empty opaque string")
    return value


def _utc_day(clock: Callable[[], datetime]) -> str:
    now = clock()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).date().isoformat()


class _QuotaBackend(Protocol):
    def increment(self, quota_date: str) -> _QuotaRow: ...

    def mark_exhausted(self, quota_date: str) -> _QuotaRow: ...

    def get(self, quota_date: str) -> _QuotaRow: ...


class _MemoryQuotaBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, _QuotaRow] = {}

    def increment(self, quota_date: str) -> _QuotaRow:
        with self._lock:
            current = self._rows.get(quota_date, _QuotaRow(quota_date, 0, False))
            updated = _QuotaRow(quota_date, current.spent + 1, current.exhausted)
            self._rows[quota_date] = updated
            return updated

    def mark_exhausted(self, quota_date: str) -> _QuotaRow:
        with self._lock:
            current = self._rows.get(quota_date, _QuotaRow(quota_date, 0, False))
            updated = _QuotaRow(quota_date, current.spent, True)
            self._rows[quota_date] = updated
            return updated

    def get(self, quota_date: str) -> _QuotaRow:
        with self._lock:
            return self._rows.get(quota_date, _QuotaRow(quota_date, 0, False))

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_QUOTA = _MemoryQuotaBackend()


def reset_memory_youtube_quota() -> None:
    """Test-only reset hook for the explicit in-process fallback."""
    _MEMORY_QUOTA.clear()


def _resolve_backend() -> str:
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if override:
        if override not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend {override!r} is unsupported for YouTube quota accounting; "
                "set STORE_BACKEND to 'pg' or 'memory'."
            )
        return override
    dsn = resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No store backend configured for YouTube quota accounting: set "
            "STORE_BACKEND=memory explicitly for tests or configure DATABASE_URL/DB_DSN."
        )
    try:
        import psycopg  # noqa: PLC0415

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "YouTube quota backend resolution failed: Postgres is configured but unreachable. "
            "Refusing volatile fallback."
        ) from exc
    return "pg"


def _pg_connect() -> Any:
    import psycopg  # noqa: PLC0415

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.getenv("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    if not (row and row[0]):
        raise YouTubeQuotaSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            quota_date DATE PRIMARY KEY,
            spent INTEGER NOT NULL DEFAULT 0,
            exhausted BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT youtube_api_quota_daily_spent_chk CHECK (spent >= 0)
        )
        """
    )


def _row_to_quota(row: tuple[Any, ...]) -> _QuotaRow:
    day = row[0]
    if isinstance(day, date):
        day = day.isoformat()
    return _QuotaRow(str(day), int(row[1]), bool(row[2]))


class _PgQuotaBackend:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def increment(self, quota_date: str) -> _QuotaRow:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            row = conn.execute(
                f"""
                INSERT INTO {_TABLE} (quota_date, spent, exhausted, updated_at)
                VALUES (%s::date, 1, false, now())
                ON CONFLICT (quota_date) DO UPDATE
                SET spent = {_TABLE}.spent + 1, updated_at = now()
                RETURNING quota_date, spent, exhausted
                """,
                (quota_date,),
            ).fetchone()
            assert row is not None
            return _row_to_quota(tuple(row))
        finally:
            conn.close()

    def mark_exhausted(self, quota_date: str) -> _QuotaRow:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            row = conn.execute(
                f"""
                INSERT INTO {_TABLE} (quota_date, spent, exhausted, updated_at)
                VALUES (%s::date, 0, true, now())
                ON CONFLICT (quota_date) DO UPDATE
                SET exhausted = true, updated_at = now()
                RETURNING quota_date, spent, exhausted
                """,
                (quota_date,),
            ).fetchone()
            assert row is not None
            return _row_to_quota(tuple(row))
        finally:
            conn.close()

    def get(self, quota_date: str) -> _QuotaRow:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            row = conn.execute(
                f"SELECT quota_date, spent, exhausted FROM {_TABLE} WHERE quota_date = %s::date",
                (quota_date,),
            ).fetchone()
            return _row_to_quota(tuple(row)) if row else _QuotaRow(quota_date, 0, False)
        finally:
            conn.close()


class YouTubeQuotaStore:
    """Atomic per-UTC-day quota counter over the selected store backend."""

    def __init__(
        self,
        backend: _QuotaBackend,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._backend = backend
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @classmethod
    def for_runtime(cls, *, clock: Callable[[], datetime] | None = None) -> YouTubeQuotaStore:
        backend: _QuotaBackend
        if _resolve_backend() == "pg":
            backend = _PgQuotaBackend()
        else:
            backend = _MEMORY_QUOTA
        return cls(backend, clock=clock)

    def increment(self) -> _QuotaRow:
        return self._backend.increment(_utc_day(self._clock))

    def mark_exhausted(self, quota_date: str | None = None) -> _QuotaRow:
        return self._backend.mark_exhausted(quota_date or _utc_day(self._clock))

    def status(self, budget: int) -> dict[str, int | bool]:
        row = self._backend.get(_utc_day(self._clock))
        return {
            "spent_today": row.spent,
            "budget": budget,
            "exhausted": row.exhausted or row.spent >= budget,
        }


class YouTubeApiClient:
    """One bounded, allowlisted, quota-accounted Data API client."""

    def __init__(
        self,
        *,
        token_provider: AccessTokenProvider,
        quota: YouTubeQuotaStore | None = None,
        http: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_pages: int = DEFAULT_MAX_PAGES,
        quota_budget: int = DEFAULT_QUOTA_BUDGET,
    ) -> None:
        self._base_url = _validate_absolute_data_url(base_url, require_path=True)
        if not self._base_url.endswith("/"):
            self._base_url += "/"
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        if max_pages <= 0:
            raise ValueError("max_pages must be positive")
        if quota_budget <= 0:
            raise ValueError("quota_budget must be positive")
        self._tokens = token_provider
        self._quota = quota or YouTubeQuotaStore.for_runtime()
        self._http = http or httpx.Client()
        self._timeout = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_pages = max_pages
        self._quota_budget = quota_budget

    def list_my_playlists(self) -> PlaylistListResult:
        rows: list[Playlist] = []
        token: str | None = None
        for _ in range(self._max_pages):
            payload, _ = self._get_json(
                "playlists",
                {
                    "part": "snippet,contentDetails",
                    "mine": "true",
                    "maxResults": "50",
                    "fields": "nextPageToken,items(id,snippet(title),contentDetails(itemCount))",
                    **({"pageToken": token} if token else {}),
                },
            )
            if isinstance(payload, NotModified):  # impossible without allow_not_modified
                raise _shape_error()
            rows.extend(_parse_playlists(payload))
            next_token = _payload_page_token(payload)
            if not next_token:
                return PlaylistListResult(tuple(rows), None, False)
            _reject_token_cycle(token, next_token)
            token = next_token
        return PlaylistListResult(tuple(rows), token, token is not None)

    def list_playlist_items(
        self,
        playlist_id: str,
        *,
        etag: str | None = None,
        page_token: str | None = None,
    ) -> PlaylistItemsPage | NotModified:
        playlist_id = validate_playlist_id(playlist_id)
        token = _validate_page_token(page_token)
        if etag is not None and (
            not isinstance(etag, str) or not etag or "\r" in etag or "\n" in etag
        ):
            raise InvalidYouTubeRefError("etag must be a non-empty single-line string")
        rows: list[PlaylistItem] = []
        first_etag: str | None = None
        for page_index in range(self._max_pages):
            payload, response_etag = self._get_json(
                "playlistItems",
                {
                    "part": "snippet",
                    "playlistId": playlist_id,
                    "maxResults": "50",
                    "fields": (
                        "etag,nextPageToken,items(id,snippet(position,publishedAt,title,"
                        "resourceId(videoId)))"
                    ),
                    **({"pageToken": token} if token else {}),
                },
                etag=etag if page_index == 0 else None,
                allow_not_modified=page_index == 0,
            )
            if isinstance(payload, NotModified):
                return payload
            if page_index == 0:
                first_etag = response_etag or _optional_str(payload.get("etag"))
            rows.extend(_parse_playlist_items(payload))
            next_token = _payload_page_token(payload)
            if not next_token:
                return PlaylistItemsPage(tuple(rows), None, first_etag, False)
            _reject_token_cycle(token, next_token)
            token = next_token
        return PlaylistItemsPage(tuple(rows), token, first_etag, token is not None)

    def get_my_channel(self) -> Channel:
        payload, _ = self._get_json(
            "channels",
            {
                "part": "snippet",
                "mine": "true",
                "maxResults": "1",
                "fields": "items(id,snippet(title))",
            },
        )
        if isinstance(payload, NotModified):  # impossible without allow_not_modified
            raise _shape_error()
        items = _payload_items(payload)
        if not items:
            raise YouTubeApiError("source_gone", 404, "authenticated channel was not found")
        item = items[0]
        snippet = item.get("snippet")
        if not isinstance(snippet, Mapping):
            raise _shape_error()
        channel_id = _required_str(item.get("id"))
        title = _required_str(snippet.get("title"))
        try:
            validate_channel_id(channel_id)
        except InvalidYouTubeRefError as exc:
            raise _shape_error() from exc
        return Channel(channel_id, title)

    def quota_status(self) -> dict[str, int | bool]:
        return self._quota.status(self._quota_budget)

    def _get_json(
        self,
        resource: str,
        params: Mapping[str, str],
        *,
        etag: str | None = None,
        allow_not_modified: bool = False,
    ) -> tuple[dict[str, Any] | NotModified, str | None]:
        url = _validate_absolute_data_url(urljoin(self._base_url, resource), require_path=True)
        access_token = self._tokens.get_access_token()
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        if etag:
            headers["If-None-Match"] = etag
        request = self._http.build_request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=self._timeout,
        )
        # An injected/default Client may carry a cookie jar. This API boundary
        # is bearer-only, so strip cookies at the final production call site.
        request.headers.pop("cookie", None)
        _validate_absolute_data_url(str(request.url), require_path=True)
        quota_date = self._quota.increment().quota_date
        try:
            response = self._http.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException:
            raise YouTubeApiError("api_unavailable", None, "Data API request timed out") from None
        except httpx.TransportError:
            raise YouTubeApiError("network_error", None, "Data API transport failed") from None

        try:
            response_etag = response.headers.get("etag")
            if response.status_code == 304 and allow_not_modified:
                return NotModified(response_etag or etag), response_etag
            if response.is_redirect:
                location = response.headers.get("location")
                if location:
                    _validate_absolute_data_url(
                        urljoin(str(request.url), location), require_path=True
                    )
                raise YouTubeApiError(
                    "api_unavailable", response.status_code, "Data API redirect was refused"
                )
            try:
                raw = _read_bounded(response, self._max_response_bytes)
            except httpx.DecodingError:
                if response.status_code >= 400:
                    error = _mapped_http_error(response.status_code, {})
                    if error.reason_code == "quota_exhausted":
                        self._quota.mark_exhausted(quota_date)
                    raise error from None
                raise YouTubeApiError(
                    "api_unavailable",
                    response.status_code,
                    "Data API response decoding failed",
                ) from None
            except YouTubeApiError:
                if response.status_code >= 400:
                    error = _mapped_http_error(response.status_code, {})
                    if error.reason_code == "quota_exhausted":
                        self._quota.mark_exhausted(quota_date)
                    raise error from None
                raise
            except httpx.TimeoutException:
                raise YouTubeApiError(
                    "api_unavailable", response.status_code, "Data API response timed out"
                ) from None
            except httpx.TransportError:
                raise YouTubeApiError(
                    "network_error", response.status_code, "Data API response transport failed"
                ) from None
        finally:
            response.close()

        if response.status_code >= 400:
            payload = _decode_error_object(raw)
            error = _mapped_http_error(response.status_code, payload)
            if error.reason_code == "quota_exhausted":
                self._quota.mark_exhausted(quota_date)
            raise error
        payload = _decode_object(raw, status=response.status_code)
        return payload, response_etag


def _validate_absolute_data_url(value: str, *, require_path: bool) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_DATA_API_HOST
        or parsed.username
        or parsed.password
    ):
        raise DisallowedYouTubeHostError(
            f"Data API egress requires https://{ALLOWED_DATA_API_HOST}"
        )
    if parsed.port not in (None, 443):
        raise DisallowedYouTubeHostError("Data API egress refuses non-HTTPS-standard ports")
    if require_path and not (
        parsed.path == "/youtube/v3" or parsed.path.startswith("/youtube/v3/")
    ):
        raise DisallowedYouTubeHostError("Data API egress path must stay under /youtube/v3")
    return value


def _read_bounded(response: httpx.Response, maximum: int) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > maximum:
                raise YouTubeApiError(
                    "api_unavailable", response.status_code, "Data API response exceeded byte bound"
                )
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > maximum:
            raise YouTubeApiError(
                "api_unavailable", response.status_code, "Data API response exceeded byte bound"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_object(raw: bytes, *, status: int | None = None) -> dict[str, Any]:
    try:
        value = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise YouTubeApiError("api_unavailable", status, "Data API returned invalid JSON") from None
    if not isinstance(value, dict):
        raise YouTubeApiError(
            "api_unavailable", status, "Data API returned an invalid object shape"
        )
    return value


def _decode_error_object(raw: bytes) -> dict[str, Any]:
    """Best-effort provider error parsing after HTTP status classification."""
    try:
        value = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _provider_reasons(payload: Mapping[str, Any]) -> frozenset[str]:
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return frozenset()
    entries = error.get("errors")
    if not isinstance(entries, list):
        return frozenset()
    reasons: set[str] = set()
    for entry in entries:
        if isinstance(entry, Mapping) and isinstance(entry.get("reason"), str):
            reasons.add(entry["reason"])
    return frozenset(reasons)


def _mapped_http_error(status: int, payload: Mapping[str, Any]) -> YouTubeApiError:
    reasons = _provider_reasons(payload)
    if status == 429 or (status == 403 and reasons.intersection(_QUOTA_REASONS)):
        reason_code = "quota_exhausted"
    elif status == 401:
        reason_code = "auth_expired"
    elif status in {403, 404}:
        reason_code = "source_gone"
    elif status >= 500:
        reason_code = "api_unavailable"
    else:
        reason_code = "api_unavailable"
    return YouTubeApiError(reason_code, status, f"Data API request failed with HTTP {status}")


def _shape_error() -> YouTubeApiError:
    return YouTubeApiError("api_unavailable", None, "Data API returned an invalid resource shape")


def _required_str(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise _shape_error()
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _payload_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = payload.get("items", [])
    if not isinstance(items, list) or not all(isinstance(item, Mapping) for item in items):
        raise _shape_error()
    return items


def _payload_page_token(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("nextPageToken")
    if value is None:
        return None
    if not isinstance(value, str):
        raise _shape_error()
    try:
        return _validate_page_token(value)
    except InvalidYouTubeRefError as exc:
        raise _shape_error() from exc


def _reject_token_cycle(previous: str | None, next_token: str) -> None:
    if previous is not None and previous == next_token:
        raise YouTubeApiError("api_unavailable", None, "Data API pagination token repeated")


def _parse_playlists(payload: Mapping[str, Any]) -> tuple[Playlist, ...]:
    parsed: list[Playlist] = []
    for item in _payload_items(payload):
        snippet = item.get("snippet")
        content = item.get("contentDetails")
        if not isinstance(snippet, Mapping) or not isinstance(content, Mapping):
            raise _shape_error()
        playlist_id = _required_str(item.get("id"))
        count_value = content.get("itemCount")
        if isinstance(count_value, bool) or not isinstance(count_value, (int, str)):
            raise _shape_error()
        try:
            validate_playlist_id(playlist_id)
            count = int(count_value)
        except (InvalidYouTubeRefError, TypeError, ValueError) as exc:
            raise _shape_error() from exc
        if count < 0:
            raise _shape_error()
        parsed.append(Playlist(playlist_id, _required_str(snippet.get("title")), count))
    return tuple(parsed)


def _parse_playlist_items(payload: Mapping[str, Any]) -> tuple[PlaylistItem, ...]:
    parsed: list[PlaylistItem] = []
    for item in _payload_items(payload):
        snippet = item.get("snippet")
        if not isinstance(snippet, Mapping):
            raise _shape_error()
        resource = snippet.get("resourceId")
        if not isinstance(resource, Mapping):
            raise _shape_error()
        video_id = _required_str(resource.get("videoId"))
        position_value = snippet.get("position")
        if isinstance(position_value, bool) or not isinstance(position_value, (int, str)):
            raise _shape_error()
        try:
            validate_video_id(video_id)
            position = int(position_value)
        except (InvalidYouTubeRefError, TypeError, ValueError) as exc:
            raise _shape_error() from exc
        if position < 0:
            raise _shape_error()
        parsed.append(
            PlaylistItem(
                playlist_item_id=_required_str(item.get("id")),
                video_id=video_id,
                position=position,
                published_at=_required_str(snippet.get("publishedAt")),
                title=_required_str(snippet.get("title")),
            )
        )
    return tuple(parsed)


__all__ = [
    "AccessTokenProvider",
    "Channel",
    "DisallowedYouTubeHostError",
    "InvalidYouTubeRefError",
    "NotModified",
    "Playlist",
    "PlaylistItem",
    "PlaylistItemsPage",
    "PlaylistListResult",
    "YouTubeApiClient",
    "YouTubeApiError",
    "YouTubeQuotaSchemaMissingError",
    "YouTubeQuotaStore",
    "reset_memory_youtube_quota",
    "validate_channel_id",
    "validate_playlist_id",
    "validate_video_id",
]
