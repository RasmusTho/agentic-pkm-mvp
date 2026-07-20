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


def _exception_graph(error: BaseException) -> tuple[BaseException, ...]:
    pending = [error]
    seen: set[int] = set()
    graph: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        graph.append(current)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return tuple(graph)


def _assert_exception_graph_secret_free(error: BaseException, sentinel: str) -> None:
    graph = _exception_graph(error)
    for current in graph:
        inspectable = "\n".join(
            (
                str(current),
                repr(current),
                repr(current.args),
                repr(vars(current)),
            )
        )
        assert sentinel not in inspectable
    assert error.__cause__ is None
    assert error.__context__ is None


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


@pytest.mark.parametrize(
    "location",
    (
        "https://[SENTINEL-malformed-redirect/youtube/v3/channels",
        "https://www.googleapis.com:65536/youtube/v3/channels"
        "?provider=SENTINEL-malformed-redirect",
    ),
)
def test_malformed_redirect_location_is_safely_normalized(location: str) -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = "SENTINEL-malformed-redirect"
    response_holder: list[httpx.Response] = []

    class _TrackedRedirectResponse(httpx.Response):
        close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            super().close()

    def handler(request: httpx.Request) -> httpx.Response:
        response = _TrackedRedirectResponse(
            302,
            request=request,
            headers={"Location": location},
            stream=httpx.ByteStream(b"provider body must remain unread"),
        )
        response_holder.append(response)
        return response

    with pytest.raises(YouTubeApiError) as captured:
        _client(_Api(handler)).get_my_channel()

    error = captured.value
    assert error.reason_code == "api_unavailable"
    assert error.status == 302
    assert response_holder[0].close_calls == 1
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))
    _assert_exception_graph_secret_free(error, sentinel)


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
        _assert_exception_graph_secret_free(error, sentinel)

    timeout_api = _Api(
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout(sentinel, request=request))
    )
    with pytest.raises(YouTubeApiError) as timeout_error:
        _client(timeout_api).get_my_channel()
    assert timeout_error.value.reason_code == "api_unavailable"
    assert sentinel not in timeout_error.value.detail
    _assert_exception_graph_secret_free(timeout_error.value, sentinel)

    network_api = _Api(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError(sentinel, request=request))
    )
    with pytest.raises(YouTubeApiError) as network_error:
        _client(network_api).get_my_channel()
    assert network_error.value.reason_code == "network_error"
    assert sentinel not in network_error.value.detail
    _assert_exception_graph_secret_free(network_error.value, sentinel)

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
    _assert_exception_graph_secret_free(stream_error.value, sentinel)

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
    _assert_exception_graph_secret_free(invalid_json_error.value, sentinel)

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
    _assert_exception_graph_secret_free(captured.value, sentinel.decode())


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
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))
    _assert_exception_graph_secret_free(error, sentinel)

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


@pytest.mark.parametrize("failure_stage", ("send", "iterate", "close"))
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

    def handler(request: httpx.Request) -> httpx.Response:
        if failure_stage == "send":
            raise httpx.StreamError(sentinel)
        return httpx.Response(200, request=request, stream=_ActualStreamError())

    api = _Api(handler)
    with pytest.raises(YouTubeApiError) as captured:
        _client(api).get_my_channel()

    error = captured.value
    assert error.reason_code == "api_unavailable"
    assert error.status == (None if failure_stage == "send" else 200)
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))
    _assert_exception_graph_secret_free(error, sentinel)


@pytest.mark.parametrize(
    ("status", "allow_not_modified", "body", "headers", "fail_on_close", "status_reason"),
    (
        (304, True, b"", {"ETag": "etag-v2"}, 1, None),
        (
            302,
            False,
            b"",
            {"Location": "https://www.googleapis.com/youtube/v3/channels"},
            1,
            "api_unavailable",
        ),
        (200, False, b'{"items": []}', {}, 2, None),
        (401, False, b'{"error": {}}', {}, 2, "auth_expired"),
    ),
)
@pytest.mark.parametrize(
    ("failure_type", "close_reason"),
    ((httpx.CloseError, "network_error"), (httpx.ReadTimeout, "api_unavailable")),
)
def test_explicit_response_close_failure_is_safely_normalized(
    status: int,
    allow_not_modified: bool,
    body: bytes,
    headers: dict[str, str],
    fail_on_close: int,
    status_reason: str | None,
    failure_type: type[httpx.RequestError],
    close_reason: str,
) -> None:
    from app.knowledge_acquisition.youtube_api_client import YouTubeApiError

    sentinel = f"SENTINEL-explicit-close-{failure_type.__name__}-must-never-leak"
    response_holder: list[httpx.Response] = []
    stream_holder: list[httpx.SyncByteStream] = []

    class _TrackedBodyStream(httpx.SyncByteStream):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            yield body

    class _ExplicitCloseFailureResponse(httpx.Response):
        close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == fail_on_close:
                raise failure_type(sentinel, request=self.request)
            super().close()

    def handler(request: httpx.Request) -> httpx.Response:
        stream = _TrackedBodyStream()
        response = _ExplicitCloseFailureResponse(
            status,
            request=request,
            headers=headers,
            stream=stream,
        )
        stream_holder.append(stream)
        response_holder.append(response)
        return response

    client = _client(_Api(handler))
    with pytest.raises(YouTubeApiError) as captured:
        if allow_not_modified:
            client.list_playlist_items("PL__test__playlist", etag="etag-v1")
        else:
            client.get_my_channel()

    error = captured.value
    assert error.reason_code == (status_reason or close_reason)
    assert error.status == status
    assert response_holder[0].close_calls == fail_on_close
    assert stream_holder[0].iterations == (0 if status in {302, 304} else 1)
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))
    _assert_exception_graph_secret_free(error, sentinel)


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
    assert sentinel not in error.detail
    assert sentinel not in "".join(traceback.format_exception(error))
    _assert_exception_graph_secret_free(error, sentinel)


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
