"""Separate runtime ingress for the ADR-0070 remote entrypoint.

This ASGI wrapper is served on its own loopback port or Unix socket, never on
the ordinary API listener. Every request arriving here is the remote subject:

* the remote-subject credential is verified against the host-side grant on
  every request, before any route runs;
* loopback trust is switched off: the immediate peer is replaced and every
  forwarding, API-key, context-carrier and Tailscale header is dropped;
* only the routes for granted tools are reachable (enforced here, so routes
  without an authentication dependency are covered too);
* a capture is pinned to the grant's vault binding.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Sequence

from starlette.types import ASGIApp, Receive, Scope, Send

from app.remote_mcp.grant import GRANT_PATH_ENV, GrantRefused, RemoteGrant, admit

_LOG = logging.getLogger("mimer.remote_ingress")

CREDENTIAL_HEADER = b"x-mimer-remote-credential"
REMOTE_PEER = ("remote-mcp-ingress", 0)
STATE_KEY = "mimer_remote_grant"
MAX_BODY_BYTES = 64 * 1024

#: Granted tool -> the one runtime route it may reach.
TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "mimer.health": ("GET", "/healthz"),
    "mimer.capture": ("POST", "/api/companion/capture/scoped"),
}
_CAPTURE_ROUTE = TOOL_ROUTES["mimer.capture"]

#: ADR-0070 §3: the ingress derives the active context from the grant and *rejects* any
#: carrier the entrypoint sends, rather than silently ignoring it.
_CARRIER_HEADERS = frozenset({b"x-active-context-session", b"x-active-context-override"})

_DROPPED_HEADERS = frozenset(
    {
        b"x-forwarded-for",
        b"x-forwarded-host",
        b"x-forwarded-proto",
        b"x-forwarded-port",
        b"x-real-ip",
        b"forwarded",
        b"x-api-key",
        b"x-active-context-session",
        b"x-active-context-override",
        CREDENTIAL_HEADER,
    }
)


def _drop(name: bytes) -> bool:
    return name in _DROPPED_HEADERS or name.startswith(b"tailscale-")


async def _send_json(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RemoteIngress:
    """Wrap the runtime app so only the remote subject can use this listener."""

    def __init__(self, app: ASGIApp, *, grant_path: Path) -> None:
        self._app = app
        self._grant_path = grant_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        headers = scope.get("headers") or []
        presented = next(
            (
                value.decode("latin-1")
                for name, value in headers
                if name.lower() == CREDENTIAL_HEADER
            ),
            None,
        )
        route = (scope["method"], scope["path"])
        try:
            grant = admit(self._grant_path, presented)
        except GrantRefused as refused:
            _LOG.warning("remote_ingress_refused reason=%s", refused.reason)
            await _send_json(send, refused.status_code, refused.reason)
            return
        if any(name.lower() in _CARRIER_HEADERS for name, _ in headers):
            _LOG.warning("remote_ingress_refused reason=remote_context_carrier_rejected")
            await _send_json(send, 403, "remote_context_carrier_rejected")
            return
        if route not in {TOOL_ROUTES[tool] for tool in grant.tools}:
            _LOG.warning("remote_ingress_refused reason=remote_route_not_granted")
            await _send_json(send, 404, "remote_route_not_granted")
            return

        inner = dict(scope)
        inner["headers"] = [(name, value) for name, value in headers if not _drop(name.lower())]
        inner["client"] = REMOTE_PEER
        inner["state"] = {**(scope.get("state") or {}), STATE_KEY: grant}
        if route == _CAPTURE_ROUTE:
            pinned = await self._pinned_capture_body(receive, grant)
            if isinstance(pinned, tuple):
                await _send_json(send, *pinned)
                return
            inner["headers"] = [
                (n, v)
                for n, v in inner["headers"]
                if n.lower() not in {b"content-length", b"content-type"}
            ]
            inner["headers"].append((b"content-type", b"application/json"))
            inner["headers"].append((b"content-length", str(len(pinned)).encode()))
            receive = _replay(pinned)
        await self._app(inner, receive, send)

    @staticmethod
    async def _pinned_capture_body(receive: Receive, grant: RemoteGrant) -> bytes | tuple[int, str]:
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return (400, "remote_request_incomplete")
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                return (413, "remote_request_too_large")
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        try:
            payload: Any = json.loads(b"".join(chunks) or b"null")
        except ValueError:
            return (422, "remote_request_invalid")
        if not isinstance(payload, dict):
            return (422, "remote_request_invalid")
        requested = payload.get("target_binding_id")
        if requested is not None and requested != grant.vault_binding_id:
            return (403, "remote_binding_not_granted")
        payload["target_binding_id"] = grant.vault_binding_id
        return json.dumps(payload).encode()


def _replay(body: bytes) -> Receive:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def build_ingress(grant_path: Path | None = None) -> RemoteIngress:
    from app.api.app import app

    path = grant_path or Path(os.environ[GRANT_PATH_ENV])
    return RemoteIngress(app, grant_path=path)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - process entrypoint
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m app.api.remote_ingress")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--uds", help="Unix socket path for the remote ingress")
    target.add_argument("--port", type=int, help="loopback port for the remote ingress")
    parser.add_argument("--grant-path", type=Path, default=os.environ.get(GRANT_PATH_ENV))
    args = parser.parse_args(argv)
    if not args.grant_path:
        parser.error(f"--grant-path or {GRANT_PATH_ENV} is required")
    ingress = build_ingress(args.grant_path)
    if args.uds:
        uvicorn.run(ingress, uds=args.uds, access_log=False)
    else:
        uvicorn.run(ingress, host="127.0.0.1", port=args.port, access_log=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
