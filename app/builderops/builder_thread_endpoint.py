"""Authenticated HTTP transport for the Builder Thread writer host.

This module is a BuilderOps-host entrypoint, not a Product Runtime route.  The
host owns writer-root and client-token configuration; clients receive only an
endpoint URL, their identity, and their token.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import asdict
from typing import Any, Literal, Mapping, cast

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.builderops.builder_threads_serialized import (
    BuilderInbox,
    BuilderThread,
    BuilderThreadClient,
    BuilderThreadError,
    BuilderThreadWriterHost,
    ThreadEntry,
    ThreadMutation,
    ThreadMutationResult,
    WriterEndpoint,
    WriterUnavailableError,
)

_CLIENT_URL_ENV = "BUILDEROPS_THREAD_ENDPOINT_URL"
_CLIENT_TOKEN_ENV = "BUILDEROPS_THREAD_CLIENT_TOKEN"
_CLIENT_ID_ENV = "BUILDEROPS_THREAD_CLIENT_ID"
_HOST_TOKENS_ENV = "BUILDEROPS_THREAD_WRITER_CLIENT_TOKENS_JSON"


class EndpointConfigurationError(WriterUnavailableError):
    """A configured client or host endpoint is incomplete or malformed."""


class HttpWriterEndpoint(WriterEndpoint):
    """Configured client transport; it never receives writer-root settings."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip() or not client_id.strip() or not token.strip():
            raise EndpointConfigurationError("Builder Thread endpoint configuration is required")
        self._client_id = client_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Builder-Thread-Client": client_id,
            },
            timeout=10.0,
            transport=transport,
        )

    @classmethod
    def from_environment(
        cls, *, transport: httpx.BaseTransport | None = None
    ) -> "HttpWriterEndpoint":
        return cls(
            base_url=os.getenv(_CLIENT_URL_ENV, ""),
            client_id=os.getenv(_CLIENT_ID_ENV, ""),
            token=os.getenv(_CLIENT_TOKEN_ENV, ""),
            transport=transport,
        )

    def mutate(self, command: ThreadMutation) -> ThreadMutationResult:
        payload = self._request("POST", "/v1/builder-threads/mutate", json=_mutation_payload(command))
        return ThreadMutationResult(thread=_thread_from_payload(payload["thread"]), replayed=payload["replayed"])

    def read_thread(self, thread_id: str) -> BuilderThread:
        return _thread_from_payload(self._request("GET", f"/v1/builder-threads/{thread_id}"))

    def inbox(self, recipient: str, *, limit: int) -> BuilderInbox:
        payload = self._request("GET", "/v1/builder-threads/inbox", params={"recipient": recipient, "limit": limit})
        return BuilderInbox(
            recipient=payload["recipient"],
            threads=tuple(_summary_from_payload(item) for item in payload["threads"]),
            truncated=payload["truncated"],
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise WriterUnavailableError("Builder Thread endpoint is unavailable") from exc
        if response.status_code >= 500:
            raise WriterUnavailableError("Builder Thread endpoint is unavailable")
        if response.status_code >= 400:
            detail = response.json().get("detail", "Builder Thread endpoint refused request")
            raise BuilderThreadError(str(detail))
        payload = response.json()
        if not isinstance(payload, dict):
            raise WriterUnavailableError("Builder Thread endpoint returned an invalid response")
        return payload


class BuilderThreadEndpointHost:
    """Host-only HTTP adapter around the existing serialized writer."""

    def __init__(self, writer_host: BuilderThreadWriterHost, *, client_tokens: Mapping[str, str]) -> None:
        if not client_tokens or any(not identity or not token for identity, token in client_tokens.items()):
            raise EndpointConfigurationError("writer client-token mapping is required")
        self._writer_host = writer_host
        self._client_tokens = dict(client_tokens)
        self._endpoints = {
            identity: writer_host.endpoint_for(identity) for identity in self._client_tokens
        }

    @classmethod
    def from_environment(cls) -> "BuilderThreadEndpointHost":
        raw_tokens = os.getenv(_HOST_TOKENS_ENV, "")
        try:
            client_tokens = json.loads(raw_tokens)
        except json.JSONDecodeError as exc:
            raise EndpointConfigurationError("writer client-token mapping is invalid") from exc
        if not isinstance(client_tokens, dict) or not all(
            isinstance(identity, str) and isinstance(token, str)
            for identity, token in client_tokens.items()
        ):
            raise EndpointConfigurationError("writer client-token mapping is invalid")
        return cls(BuilderThreadWriterHost.from_environment(), client_tokens=client_tokens)

    def app(self) -> FastAPI:
        app = FastAPI(title="Builder Thread writer endpoint", docs_url=None, redoc_url=None)

        def endpoint_for(request: Request) -> WriterEndpoint:
            identity = request.headers.get("X-Builder-Thread-Client", "")
            authorization = request.headers.get("Authorization", "")
            expected = self._client_tokens.get(identity)
            supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
            if expected is None or not hmac.compare_digest(supplied, expected):
                raise HTTPException(status_code=401, detail="Builder Thread endpoint authentication failed")
            return self._endpoints[identity]

        @app.post("/v1/builder-threads/mutate")
        async def mutate(request: Request) -> dict[str, Any]:
            endpoint = endpoint_for(request)
            try:
                command = _mutation_from_payload(await request.json())
                result = endpoint.mutate(command)
            except WriterUnavailableError as exc:
                raise HTTPException(status_code=503, detail="Builder Thread writer is unavailable") from exc
            except (BuilderThreadError, KeyError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"thread": _thread_payload(result.thread), "replayed": result.replayed}

        @app.get("/v1/builder-threads/inbox")
        def inbox(request: Request, recipient: str, limit: int = 20) -> dict[str, Any]:
            endpoint = endpoint_for(request)
            try:
                result = endpoint.inbox(recipient, limit=limit)
            except WriterUnavailableError as exc:
                raise HTTPException(status_code=503, detail="Builder Thread writer is unavailable") from exc
            except BuilderThreadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"recipient": result.recipient, "threads": [asdict(item) for item in result.threads], "truncated": result.truncated}

        @app.get("/v1/builder-threads/{thread_id}")
        def read(request: Request, thread_id: str) -> dict[str, Any]:
            endpoint = endpoint_for(request)
            try:
                return _thread_payload(endpoint.read_thread(thread_id))
            except WriterUnavailableError as exc:
                raise HTTPException(status_code=503, detail="Builder Thread writer is unavailable") from exc
            except BuilderThreadError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return app


def configured_builder_thread_client() -> BuilderThreadClient:
    """Return the sanctioned Codex/Claude client path from configured endpoint settings."""
    endpoint = HttpWriterEndpoint.from_environment()
    return BuilderThreadClient(endpoint, client_id=endpoint._client_id)


def _mutation_payload(command: ThreadMutation) -> dict[str, Any]:
    return asdict(command)


def _mutation_from_payload(payload: Any) -> ThreadMutation:
    if not isinstance(payload, dict):
        raise BuilderThreadError("Builder Thread mutation must be an object")
    refs = payload.get("source_refs", ())
    if not isinstance(refs, list):
        raise BuilderThreadError("source_refs must be a list")
    return ThreadMutation(
        request_id=cast(str, payload.get("request_id")),
        kind=cast(Literal["create", "reply", "close", "archive"], payload.get("kind")),
        actor=cast(str, payload.get("actor")),
        thread_id=payload.get("thread_id"), recipient=payload.get("recipient"),
        subject=payload.get("subject"), content=payload.get("content"), source_refs=tuple(refs),
    )


def _thread_payload(thread: BuilderThread) -> dict[str, Any]:
    return asdict(thread)


def _thread_from_payload(payload: Any) -> BuilderThread:
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise WriterUnavailableError("Builder Thread endpoint returned an invalid thread")
    return BuilderThread(
        thread_id=payload["thread_id"], vault_id=payload["vault_id"], subject=payload["subject"],
        reply_expected=payload["reply_expected"], privacy_class=payload["privacy_class"], state=payload["state"],
        entries=tuple(ThreadEntry(**entry) for entry in payload["entries"]),
    )


def _summary_from_payload(payload: Any) -> Any:
    from app.builderops.builder_threads_serialized import BuilderThreadSummary
    if not isinstance(payload, dict):
        raise WriterUnavailableError("Builder Thread endpoint returned an invalid inbox")
    payload["last_source_refs"] = tuple(payload["last_source_refs"])
    return BuilderThreadSummary(**payload)


def main() -> None:
    import uvicorn
    uvicorn.run(BuilderThreadEndpointHost.from_environment().app(), host="127.0.0.1", port=18002)


if __name__ == "__main__":
    main()
