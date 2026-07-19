"""YSS-03 (#3918): bounded YouTube Data API client contract.

All egress runs through ``httpx.MockTransport`` while exercising the real
request-building, host-validation, response-bounding, parsing, pagination,
error-mapping, and quota-accounting call sites. Fixture ids are synthetic
(INV-YSS-9), and planted secret sentinels prove provider bodies and auth
headers never enter structured error details (INV-YSS-5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import traceback
from typing import Any

import httpx
import pytest

from app.knowledge_acquisition.youtube_oauth import AuthDegradedError


class _TokenProvider:
    def __init__(self, token: str = "sentinel-access-token-never-leak") -> None:
        self.token = token
        self.calls = 0

    def get_access_token(self) -> str:
        self.calls += 1
        return self.token


class _RevokedTokenProvider:
    def get_access_token(self) -> str:
        raise AuthDegradedError("auth_revoked")


class _Api:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


@pytest.fixture(autouse=True)
def _memory_quota(monkeypatch: pytest.MonkeyPatch):
    from app.knowledge_acquisition import youtube_api_client as api

    monkeypatch.setenv("STORE_BACKEND", "memory")
    api.reset_memory_youtube_quota()
    yield
    api.reset_memory_youtube_quota()


def _response(
    request: httpx.Request, payload: dict[str, Any], *, status: int = 200
) -> httpx.Response:
    return httpx.Response(status, request=request, json=payload)


def _client(
    api: _Api,
    *,
    token_provider: Any | None = None,
    max_pages: int = 10,
    budget: int = 10_000,
    max_response_bytes: int = 2 * 1024 * 1024,
    cookies: dict[str, str] | None = None,
    quota: Any | None = None,
):
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiClient

    return YouTubeApiClient(
        token_provider=token_provider or _TokenProvider(),
        http=httpx.Client(transport=httpx.MockTransport(api.handler), cookies=cookies),
        max_pages=max_pages,
        quota_budget=budget,
        max_response_bytes=max_response_bytes,
        quota=quota,
    )


def _playlist_item(n: int) -> dict[str, Any]:
    return {
        "id": f"PLI__test__{n}",
        "snippet": {
            "position": n,
            "publishedAt": "2026-07-19T00:00:00Z",
            "title": f"Fixture video {n}",
            "resourceId": {"videoId": f"vidTEST{n:04d}"},
        },
    }


def test_pagination_and_bounded_page_cap() -> None:
    from app.knowledge_acquisition.youtube_api_client import PlaylistItemsPage

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("pageToken")
        page = {None: 1, "page-2": 2, "page-3": 3}[token]
        next_token = {1: "page-2", 2: "page-3", 3: None}[page]
        payload: dict[str, Any] = {"etag": "etag-first", "items": [_playlist_item(page)]}
        if next_token:
            payload["nextPageToken"] = next_token
        return _response(request, payload)

    complete_api = _Api(handler)
    complete = _client(
        complete_api,
        max_pages=3,
        cookies={"session": "sentinel-cookie-must-not-cross-boundary"},
    ).list_playlist_items("PL__test__playlist")
    assert isinstance(complete, PlaylistItemsPage)
    assert [item.position for item in complete.items] == [1, 2, 3]
    assert complete.pagination_truncated is False
    assert complete.next_page_token is None
    assert complete.etag == "etag-first"
    assert len(complete_api.requests) == 3

    capped_api = _Api(handler)
    capped = _client(capped_api, max_pages=2).list_playlist_items("PL__test__playlist")
    assert isinstance(capped, PlaylistItemsPage)
    assert [item.position for item in capped.items] == [1, 2]
    assert capped.pagination_truncated is True
    assert capped.next_page_token == "page-3"
    assert len(capped_api.requests) == 2

    for request in complete_api.requests + capped_api.requests:
        assert request.url.host == "www.googleapis.com"
        assert request.url.params["maxResults"] == "50"
        assert request.url.params["part"] == "snippet"
        assert "items(id,snippet(" in request.url.params["fields"]
        assert "cookie" not in request.headers

    def playlists_handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("pageToken")
        page = 1 if token is None else 2
        payload: dict[str, Any] = {
            "items": [
                {
                    "id": f"PL__test__owned_{page}",
                    "snippet": {"title": f"Owned {page}"},
                    "contentDetails": {"itemCount": page},
                }
            ]
        }
        if page == 1:
            payload["nextPageToken"] = "owned-page-2"
        return _response(request, payload)

    playlists_api = _Api(playlists_handler)
    playlists = _client(playlists_api, max_pages=2).list_my_playlists()
    assert [row.playlist_id for row in playlists.items] == [
        "PL__test__owned_1",
        "PL__test__owned_2",
    ]
    assert playlists.pagination_truncated is False
    assert playlists.next_page_token is None
    assert playlists_api.requests[1].url.params["pageToken"] == "owned-page-2"


def test_etag_not_modified_roundtrip() -> None:
    from app.knowledge_acquisition.youtube_api_client import NotModified

    api = _Api(lambda request: httpx.Response(304, request=request, headers={"ETag": "etag-v2"}))
    result = _client(api).list_playlist_items("PL__test__playlist", etag="etag-v1")

    assert isinstance(result, NotModified)
    assert result.not_modified is True
    assert result.etag == "etag-v2"
    assert api.requests[0].headers["If-None-Match"] == "etag-v1"
    assert (
        _client(_Api(lambda request: _response(request, {"items": []}))).quota_status()[
            "spent_today"
        ]
        == 1
    )


def test_host_allowlist_and_ref_validation() -> None:
    from app.knowledge_acquisition.youtube_api_client import (
        DisallowedYouTubeHostError,
        InvalidYouTubeRefError,
        YouTubeApiClient,
        validate_channel_id,
        validate_video_id,
    )

    token_provider = _TokenProvider()
    api = _Api(lambda request: _response(request, {"items": []}))
    client = _client(api, token_provider=token_provider)

    for invalid in ("", "WL", "HL", "https://evil.example/playlist", "PL bad", "XX123"):
        with pytest.raises(InvalidYouTubeRefError):
            client.list_playlist_items(invalid)
    with pytest.raises(InvalidYouTubeRefError):
        validate_video_id("too-short")
    with pytest.raises(InvalidYouTubeRefError):
        validate_channel_id("PL__not_a_channel")
    assert api.requests == []
    assert token_provider.calls == 0

    with pytest.raises(DisallowedYouTubeHostError):
        YouTubeApiClient(
            token_provider=token_provider,
            http=httpx.Client(transport=httpx.MockTransport(api.handler)),
            base_url="https://evil.example/youtube/v3",
        )
    with pytest.raises(DisallowedYouTubeHostError):
        YouTubeApiClient(
            token_provider=token_provider,
            http=httpx.Client(transport=httpx.MockTransport(api.handler)),
            base_url="https://www.googleapis.com/youtube/v3-impersonator/",
        )

    redirect_api = _Api(
        lambda request: httpx.Response(
            302, request=request, headers={"Location": "https://evil.example/steal"}
        )
    )
    with pytest.raises(DisallowedYouTubeHostError):
        _client(redirect_api).get_my_channel()
    assert len(redirect_api.requests) == 1


def test_error_taxonomy_mapping_secret_free() -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = "SENTINEL-provider-body-must-never-leak"

    cases = (
        (
            403,
            {"error": {"message": sentinel, "errors": [{"reason": "quotaExceeded"}]}},
            "quota_exhausted",
        ),
        (
            403,
            {"error": {"message": sentinel, "errors": [{"reason": "playlistItemsNotAccessible"}]}},
            "source_gone",
        ),
        (404, {"error": {"message": sentinel}}, "source_gone"),
        (503, {"error": {"message": sentinel}}, "api_unavailable"),
        (401, {"error": {"message": sentinel}}, "auth_expired"),
    )
    for status, payload, reason_code in cases:
        api = _Api(lambda request, s=status, p=payload: _response(request, p, status=s))
        with pytest.raises(YouTubeApiError) as captured:
            _client(api).get_my_channel()
        error = captured.value
        assert error.reason_code == reason_code
        assert error.status == status
        assert sentinel not in error.detail
        assert sentinel not in str(error)
        assert "sentinel-access-token-never-leak" not in error.detail

    timeout_api = _Api(
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout(sentinel, request=request))
    )
    with pytest.raises(YouTubeApiError) as timeout_error:
        _client(timeout_api).get_my_channel()
    assert timeout_error.value.reason_code == "api_unavailable"
    assert sentinel not in timeout_error.value.detail
    assert timeout_error.value.__cause__ is None

    network_api = _Api(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError(sentinel, request=request))
    )
    with pytest.raises(YouTubeApiError) as network_error:
        _client(network_api).get_my_channel()
    assert network_error.value.reason_code == "network_error"
    assert sentinel not in network_error.value.detail
    assert network_error.value.__cause__ is None

    class _FailingResponseStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError(sentinel)

    stream_api = _Api(
        lambda request: httpx.Response(
            200,
            request=request,
            stream=_FailingResponseStream(),
        )
    )
    with pytest.raises(YouTubeApiError) as stream_error:
        _client(stream_api).get_my_channel()
    assert stream_error.value.reason_code == "network_error"
    assert sentinel not in stream_error.value.detail
    assert stream_error.value.__cause__ is None

    invalid_json_api = _Api(
        lambda request: httpx.Response(
            200,
            request=request,
            content=b'{"provider_secret":"SENTINEL-provider-body-must-never-leak",',
        )
    )
    with pytest.raises(YouTubeApiError) as invalid_json_error:
        _client(invalid_json_api).get_my_channel()
    assert invalid_json_error.value.reason_code == "api_unavailable"
    assert invalid_json_error.value.__cause__ is None

    auth_api = _Api(lambda request: _response(request, {"items": []}))
    with pytest.raises(AuthDegradedError) as auth_error:
        _client(auth_api, token_provider=_RevokedTokenProvider()).get_my_channel()
    assert auth_error.value.reason_code == "auth_revoked"
    assert auth_api.requests == []


@pytest.mark.parametrize(
    ("status", "reason_code"),
    ((401, "auth_expired"), (404, "source_gone"), (429, "quota_exhausted")),
)
@pytest.mark.parametrize("body", (b"not-json", b"x" * 256))
def test_http_status_taxonomy_survives_non_json_and_oversized_bodies(
    status: int,
    reason_code: str,
    body: bytes,
) -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    api = _Api(
        lambda request: httpx.Response(
            status,
            request=request,
            content=body,
        )
    )
    with pytest.raises(YouTubeApiError) as captured:
        _client(api, max_response_bytes=64).get_my_channel()

    assert captured.value.reason_code == reason_code
    assert captured.value.status == status
    if status == 429:
        assert (
            _client(_Api(lambda request: _response(request, {"items": []}))).quota_status()[
                "exhausted"
            ]
            is True
        )


def test_malformed_content_encoding_is_normalized_without_raw_cause() -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = b"SENTINEL-malformed-gzip-must-never-leak"
    api = _Api(
        lambda request: httpx.Response(
            200,
            request=request,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(sentinel),
        )
    )
    with pytest.raises(YouTubeApiError) as captured:
        _client(api).get_my_channel()

    assert captured.value.reason_code == "api_unavailable"
    assert captured.value.status == 200
    assert sentinel.decode() not in captured.value.detail
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    ("status", "reason_code"),
    ((401, "auth_expired"), (404, "source_gone"), (429, "quota_exhausted")),
)
@pytest.mark.parametrize("failure_stage", ("iterate", "close"))
def test_actual_stream_error_uses_known_status_and_keeps_exception_chain_secret(
    status: int,
    reason_code: str,
    failure_stage: str,
) -> None:
    from app.knowledge_acquisition.youtube_api_client import (
        YouTubeApiError,
        YouTubeQuotaStore,
    )

    sentinel = "SENTINEL-stream-error-must-never-leak"
    now = {"value": datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)}
    quota = YouTubeQuotaStore.for_runtime(clock=lambda: now["value"])

    class _ActualStreamError(httpx.SyncByteStream):
        def __iter__(self):
            if failure_stage == "iterate":
                raise httpx.StreamError(sentinel)
            yield b"not-json"

        def close(self) -> None:
            if failure_stage == "close":
                raise httpx.StreamError(sentinel)

    def handler(request: httpx.Request) -> httpx.Response:
        now["value"] = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        return httpx.Response(status, request=request, stream=_ActualStreamError())

    with pytest.raises(YouTubeApiError) as captured:
        _client(_Api(handler), quota=quota).get_my_channel()

    error = captured.value
    assert error.reason_code == reason_code
    assert error.status == status
    assert error.__cause__ is None
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))

    if status == 429:
        now["value"] = datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)
        assert quota.status(100) == {
            "spent_today": 1,
            "budget": 100,
            "exhausted": True,
        }
        now["value"] = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        assert quota.status(100) == {
            "spent_today": 0,
            "budget": 100,
            "exhausted": False,
        }


@pytest.mark.parametrize("failure_stage", ("iterate", "close"))
def test_actual_stream_error_on_success_status_is_safely_normalized(
    failure_stage: str,
) -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = "SENTINEL-stream-error-must-never-leak"

    class _ActualStreamError(httpx.SyncByteStream):
        def __iter__(self):
            if failure_stage == "iterate":
                raise httpx.StreamError(sentinel)
            yield b'{"items": []}'

        def close(self) -> None:
            if failure_stage == "close":
                raise httpx.StreamError(sentinel)

    api = _Api(lambda request: httpx.Response(200, request=request, stream=_ActualStreamError()))
    with pytest.raises(YouTubeApiError) as captured:
        _client(api).get_my_channel()

    error = captured.value
    assert error.reason_code == "api_unavailable"
    assert error.status == 200
    assert error.__cause__ is None
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("resource", ("playlists", "playlist_items"))
def test_provider_controlled_shape_value_is_absent_from_exception_chain(
    resource: str,
) -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = "SENTINEL-provider-field-must-never-leak"

    def handler(request: httpx.Request) -> httpx.Response:
        if resource == "playlists":
            return _response(
                request,
                {
                    "items": [
                        {
                            "id": "PL__test__owned",
                            "snippet": {"title": "Owned"},
                            "contentDetails": {"itemCount": sentinel},
                        }
                    ]
                },
            )
        item = _playlist_item(1)
        item["snippet"]["position"] = sentinel
        return _response(request, {"items": [item]})

    with pytest.raises(YouTubeApiError) as captured:
        client = _client(_Api(handler))
        if resource == "playlists":
            client.list_my_playlists()
        else:
            client.list_playlist_items("PL__test__playlist")

    error = captured.value
    assert error.reason_code == "api_unavailable"
    assert error.__cause__ is None
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))


def test_quota_accounting_durable_and_exhaustion() -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    ok_api = _Api(lambda request: _response(request, {"items": []}))
    first = _client(ok_api, budget=2)
    first.list_my_playlists()
    assert first.quota_status() == {"spent_today": 1, "budget": 2, "exhausted": False}

    # A distinct client + quota-store instance sees the same process-wide memory
    # fallback row. The Postgres backend uses the same per-day key durably.
    second = _client(ok_api, budget=2)
    second.list_my_playlists()
    assert second.quota_status() == {"spent_today": 2, "budget": 2, "exhausted": True}

    quota_api = _Api(
        lambda request: _response(
            request,
            {"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
            status=403,
        )
    )
    quota_client = _client(quota_api, budget=100)
    with pytest.raises(YouTubeApiError, match="quota_exhausted"):
        quota_client.get_my_channel()
    assert quota_client.quota_status() == {
        "spent_today": 3,
        "budget": 100,
        "exhausted": True,
    }


def test_quota_exhaustion_latches_the_request_day_across_utc_rollover() -> None:
    from app.knowledge_acquisition.youtube_api_client import (
        YouTubeApiError,
        YouTubeQuotaStore,
    )

    now = {"value": datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)}
    quota = YouTubeQuotaStore.for_runtime(clock=lambda: now["value"])

    def handler(request: httpx.Request) -> httpx.Response:
        now["value"] = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
        return httpx.Response(429, request=request, content=b"not-json")

    with pytest.raises(YouTubeApiError, match="quota_exhausted"):
        _client(_Api(handler), quota=quota).get_my_channel()

    now["value"] = datetime(2026, 7, 19, 23, 59, tzinfo=timezone.utc)
    assert quota.status(100) == {"spent_today": 1, "budget": 100, "exhausted": True}
    now["value"] = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    assert quota.status(100) == {"spent_today": 0, "budget": 100, "exhausted": False}


def test_resource_shapes_minimal_fields_and_response_bound() -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/playlists"):
            return _response(
                request,
                {
                    "items": [
                        {
                            "id": "PL__test__owned",
                            "snippet": {"title": "Owned"},
                            "contentDetails": {"itemCount": 7},
                        }
                    ]
                },
            )
        return _response(
            request,
            {"items": [{"id": "UC__test__channel", "snippet": {"title": "Fixture channel"}}]},
        )

    api = _Api(handler)
    client = _client(api)
    playlists = client.list_my_playlists()
    channel = client.get_my_channel()
    assert [(row.playlist_id, row.title, row.item_count) for row in playlists.items] == [
        ("PL__test__owned", "Owned", 7)
    ]
    assert (channel.channel_id, channel.title, channel.liked_videos_ref) == (
        "UC__test__channel",
        "Fixture channel",
        "LL",
    )
    assert api.requests[0].url.params["mine"] == "true"
    assert api.requests[0].url.params["part"] == "snippet,contentDetails"
    assert api.requests[1].url.params["mine"] == "true"
    assert api.requests[1].url.params["part"] == "snippet"

    oversize = _Api(
        lambda request: httpx.Response(
            200,
            request=request,
            content=b'{"items":["' + (b"x" * 200) + b'"]}',
        )
    )
    with pytest.raises(YouTubeApiError) as captured:
        _client(oversize, max_response_bytes=64).get_my_channel()
    assert captured.value.reason_code == "api_unavailable"
    assert "response exceeded" in captured.value.detail
