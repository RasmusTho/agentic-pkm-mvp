"""ADR-0070 remote MCP entrypoint: Streamable HTTP over OAuth, health and capture only.

One loopback listener (the Funnel mapping's backend) serves:

* the OAuth discovery metadata and token endpoint (``oauth_http.public_routes``);
* the MCP path (the canonical resource URL's path). Every request needs a valid bearer access
  token for this resource, re-checked against the live runtime grant; there is no
  unauthenticated MCP route.

Tool semantics are the delivered v1 layer (``mimer_mcp_sidecar.semantic``) unchanged, so receipts,
errors, and ``capture_ambiguous`` / verify-before-retry behaviour are identical to stdio. Only the
granted subset of {health, capture} is listed or callable; ``ask``, ``retrieve`` and ``read_note``
are never reachable here. The runtime is reached only through the separate remote ingress over its
Unix socket, carrying the host-provisioned remote credential; a TCP address (and so the ordinary
API listener) is refused by configuration. The MCP SDK and the sidecar are imported lazily: core
Mimer does not depend on them.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Mapping, Sequence
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app.remote_mcp.grant import RemoteGrant, read_owner_only
from app.remote_mcp.oauth import CONFIG_PATH_ENV, AuthorizationServer, OAuthError, load_config
from app.remote_mcp.oauth_http import SlidingWindow, public_routes

_LOG = logging.getLogger("mimer.remote_mcp")

#: The tools this profile can ever expose (ADR-0070 §2, first stage). The live grant narrows it.
REMOTE_TOOLS = frozenset({"mimer.health", "mimer.capture"})
CREDENTIAL_HEADER = "x-mimer-remote-credential"
INGRESS_BASE_URL = "http://remote-ingress"
CAPTURE_ROUTE = "/api/companion/capture/scoped"
_STATE_KEY = "mimer_remote_grant"
#: ADR-0070 §5: global (Funnel peers are shared egress) request budget for the MCP path, and a
#: cap on failed bearer attempts after which failures are no longer logged one by one. A failed
#: bearer always receives 401 with the challenge.
MCP_RATE_PER_MINUTE = 600
FAILED_BEARER_CAP = 30
FAILED_BEARER_WINDOW_SECONDS = 600
# Libraries whose diagnostics may carry request payloads, headers, or tool arguments.
_QUIET_LOGGERS = ("mcp", "httpx", "httpcore", "uvicorn", "sse_starlette")


@dataclass(frozen=True)
class EntrypointConfig:
    oauth_config: Path
    ingress_socket: Path
    credential_file: Path
    port: int

    @classmethod
    def build(
        cls, *, oauth_config: str | Path, ingress: str, credential_file: str | Path, port: int
    ) -> EntrypointConfig:
        if "://" in ingress or ":" in ingress or not ingress.startswith("/"):
            # ADR-0070 §3: the entrypoint cannot fall back to the ordinary (TCP) API listener.
            raise ValueError("the remote ingress must be an absolute Unix socket path")
        if not 1024 <= port <= 65535:
            raise ValueError("port must be an unprivileged loopback port")
        return cls(Path(oauth_config), Path(ingress), Path(credential_file), port)


def read_credential(path: Path) -> str:
    credential = read_owner_only(path).strip()
    if not credential or any(ch.isspace() for ch in credential):
        raise ValueError("remote credential file is empty or malformed")
    return credential


def ingress_client(socket_path: Path, credential: str) -> httpx.Client:
    """The only runtime client: the remote ingress Unix socket, with the remote credential."""

    info = os.stat(socket_path)
    if not stat.S_ISSOCK(info.st_mode):
        raise ValueError("remote ingress path is not a Unix socket")
    return httpx.Client(
        transport=httpx.HTTPTransport(uds=str(socket_path)),
        base_url=INGRESS_BASE_URL,
        headers={CREDENTIAL_HEADER: credential},
        timeout=httpx.Timeout(10.0),
        trust_env=False,
        follow_redirects=False,
    )


def build_semantic(client: httpx.Client) -> Any:
    """The v1 semantic server over the remote ingress; capture uses the context-bound route."""

    from mimer_mcp_sidecar.semantic import MimerMcpServer, _GovernedMimerHttpOperations

    class _RemoteOperations(_GovernedMimerHttpOperations):  # type: ignore[misc, valid-type]
        def capture(self, *, text: str, trace_id: str | None) -> httpx.Response:
            return self._client.post(
                CAPTURE_ROUTE,
                json={"text": text},
                headers=self._headers(trace_id),
                timeout=self._runtime_managed_timeout,
            )

        def _not_granted(self, *_args: object, **_kwargs: object) -> httpx.Response:
            raise RuntimeError("operation is not part of the remote profile")

        ask = retrieve = read_note = _not_granted

    return MimerMcpServer(_RemoteOperations(client))


def _granted(grant: RemoteGrant) -> frozenset[str]:
    return frozenset(grant.tools) & REMOTE_TOOLS


def _mcp_server(semantic: Any) -> Any:
    import anyio
    from mcp import types
    from mcp.server.lowlevel import Server
    from mimer_mcp_sidecar.transport import _result_content, _tool_definitions

    server: Any = Server("mimer-mcp", version="1")

    def grant() -> RemoteGrant:
        request = server.request_context.request
        found = request.scope.get("state", {}).get(_STATE_KEY) if request is not None else None
        if not isinstance(found, RemoteGrant):  # pragma: no cover - the bearer gate always sets it
            raise PermissionError("remote grant missing")
        return found

    @server.list_tools()  # type: ignore[misc]
    async def list_tools() -> list[types.Tool]:
        allowed = _granted(grant())
        return _tool_definitions([tool for tool in semantic.list_tools() if tool.name in allowed])

    @server.call_tool(validate_input=False)  # type: ignore[misc]
    async def call_tool(name: str, arguments: Mapping[str, Any]) -> types.CallToolResult:
        if name not in _granted(grant()):
            _LOG.info("remote_mcp op=tools/call outcome=tool_not_granted")
            payload = json.dumps({"error": "tool_not_granted", "tool": name})
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=payload)], isError=True
            )
        result = await anyio.to_thread.run_sync(semantic.call_tool, name, dict(arguments or {}))
        _LOG.info(
            "remote_mcp op=tools/call tool=%s outcome=%s trace=%s",
            name,
            "error" if result.is_error else "ok",
            result.trace_id or "-",
        )
        return types.CallToolResult(content=_result_content(result), isError=result.is_error)

    return server


async def _send_plain(
    send: Send, status: int, payload: dict[str, str], extra: list[tuple[bytes, bytes]]
) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *extra,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BearerGate:
    """ASGI gate for the MCP path: valid access token + live grant, or 401 before the SDK runs."""

    def __init__(self, oauth: AuthorizationServer, manager: Any) -> None:
        self._oauth = oauth
        self._manager = manager
        self._rate = SlidingWindow(MCP_RATE_PER_MINUTE, 60)
        self._failures = SlidingWindow(FAILED_BEARER_CAP, FAILED_BEARER_WINDOW_SECONDS)
        self._burst_logged = False
        resource_path = urlsplit(oauth.config.resource).path.strip("/")
        metadata = f"{oauth.config.issuer}/.well-known/oauth-protected-resource"
        self._metadata_url = f"{metadata}/{resource_path}" if resource_path else metadata

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._rate.hit():  # before any token lookup
            _LOG.warning("remote_mcp security_event op=bearer outcome=rate_limited")
            await _send_plain(
                send, 429, {"error": "temporarily_unavailable"}, [(b"retry-after", b"60")]
            )
            return
        headers = [(n, v) for n, v in scope.get("headers") or [] if n.lower() == b"authorization"]
        token: str | None = None
        if len(headers) == 1:
            scheme, _, value = headers[0][1].decode("latin-1").partition(" ")
            token = value.strip() if scheme.lower() == "bearer" else None
        try:
            grant = self._oauth.verify_access_token(token)
        except OAuthError as exc:
            # Always answer 401 with the challenge (a client with an expired token must learn to
            # refresh); the global budget above bounds the lookups. Past the cap, only the
            # per-failure log lines are suppressed, and capped failures are not recorded, so a
            # trickle of junk cannot keep the window full.
            if self._failures.exceeded():
                if not self._burst_logged:
                    self._burst_logged = True
                    _LOG.warning("remote_mcp security_event op=bearer outcome=failure_cap_reached")
            else:
                self._failures.record()
                self._burst_logged = False
                _LOG.warning("remote_mcp security_event op=bearer outcome=%s", exc.error)
            challenge = f'Bearer resource_metadata="{self._metadata_url}"'
            if token:
                challenge += ', error="invalid_token"'
            body = json.dumps({"error": exc.error}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"www-authenticate", challenge.encode()),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        inner = dict(scope)
        inner["headers"] = [
            (n, v) for n, v in scope.get("headers") or [] if n.lower() != b"authorization"
        ]
        inner["state"] = {**(scope.get("state") or {}), _STATE_KEY: grant}
        await self._manager.handle_request(inner, receive, send)


def build_app(oauth: AuthorizationServer, client: httpx.Client) -> Starlette:
    """The complete public-listener app: OAuth discovery/token plus the gated MCP path."""

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings

    issuer = urlsplit(oauth.config.issuer)
    host = (issuer.hostname or "").lower()
    manager = StreamableHTTPSessionManager(
        app=_mcp_server(build_semantic(client)),
        json_response=True,
        stateless=True,  # no per-session server state survives a request or a restart
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, f"{host}:443"],
            allowed_origins=[oauth.config.issuer, "https://claude.ai"],
        ),
        max_request_body_size=64 * 1024,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():  # the caller owns (and closes) the ingress client
            yield

    mcp_path = urlsplit(oauth.config.resource).path or "/"
    gate = _BearerGate(oauth, manager)
    return Starlette(
        routes=[*public_routes(oauth), Route(mcp_path, gate, methods=["GET", "POST", "DELETE"])],
        lifespan=lifespan,
    )


class _DropLibraryRecords(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(_QUIET_LOGGERS)


def quiet_library_diagnostics() -> None:
    """Keep SDK, HTTP-client and server diagnostics (which may carry payloads) out of the logs."""

    guard = _DropLibraryRecords()
    for handler in logging.getLogger().handlers:
        handler.addFilter(guard)
    for name in _QUIET_LOGGERS:
        library = logging.getLogger(name)
        library.setLevel(logging.CRITICAL + 1)
        library.propagate = False


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - process entrypoint
    import uvicorn

    parser = argparse.ArgumentParser(prog="python -m app.remote_mcp.entrypoint")
    parser.add_argument("--oauth-config", default=os.environ.get(CONFIG_PATH_ENV))
    parser.add_argument("--ingress-uds", required=True, help="the remote ingress Unix socket")
    parser.add_argument(
        "--credential-file", required=True, help="owner-only remote credential file"
    )
    parser.add_argument("--port", type=int, required=True, help="loopback port (Funnel backend)")
    args = parser.parse_args(argv)
    if not args.oauth_config:
        parser.error(f"--oauth-config or {CONFIG_PATH_ENV} is required")
    try:
        config = EntrypointConfig.build(
            oauth_config=args.oauth_config,
            ingress=args.ingress_uds,
            credential_file=args.credential_file,
            port=args.port,
        )
        oauth = AuthorizationServer(
            load_config(config.oauth_config), config_path=config.oauth_config
        )
        client = ingress_client(config.ingress_socket, read_credential(config.credential_file))
    except (OSError, ValueError) as exc:
        parser.error(f"refused: {type(exc).__name__}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    quiet_library_diagnostics()
    try:
        uvicorn.run(
            build_app(oauth, client),
            host="127.0.0.1",
            port=config.port,
            access_log=False,
            log_config=None,
            server_header=False,
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
