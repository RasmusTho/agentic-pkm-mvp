"""HTTP surfaces of the single-owner OAuth server (ADR-0070 §1, §3, §5).

Two separate ASGI apps, each for its own loopback listener:

* ``public_app`` is what the Funnel mapping on port 443 reaches: discovery metadata and the
  token endpoint. The MCP path is mounted onto it by the entrypoint (later slice).
* ``tailnet_app`` is reached only through the tailnet-only Serve mapping: the authorization
  and consent endpoints. It admits only the owner's Tailscale identity and refuses any
  Funnel-forwarded request and any tagged node (which carries no user identity headers).

Logs carry operation, outcome, and a server-generated trace id only.
"""

from __future__ import annotations

import html
import logging
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import SplitResult, parse_qs, urlencode, urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app.remote_mcp.oauth import REDIRECT_URI, AuthorizationServer, OAuthError

logger = logging.getLogger("mimer.remote_oauth")

MAX_FORM_BYTES = 8 * 1024
PUBLIC_RATE_PER_MINUTE = 60
FAILED_TOKEN_ATTEMPTS_CAP = 10
FAILED_TOKEN_WINDOW_SECONDS = 600

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_PAGE_HEADERS = {
    **_NO_STORE,
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://claude.ai; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


class SlidingWindow:
    """A global (not per-source) event counter: Funnel peers are shared egress addresses."""

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, now: float) -> None:
        while self._events and self._events[0] <= now - self.window:
            self._events.popleft()

    def exceeded(self) -> bool:
        with self._lock:
            self._trim(self._clock())
            return len(self._events) >= self.limit

    def record(self) -> None:
        with self._lock:
            now = self._clock()
            self._trim(now)
            self._events.append(now)

    def hit(self) -> bool:
        """Record one event; return True when the limit was already reached."""

        with self._lock:
            now = self._clock()
            self._trim(now)
            if len(self._events) >= self.limit:
                return True
            self._events.append(now)
            return False


def _log(op: str, outcome: str, *, security: bool = False) -> None:
    trace = secrets.token_hex(8)
    if security:
        logger.warning("remote_oauth security_event op=%s outcome=%s trace=%s", op, outcome, trace)
    else:
        logger.info("remote_oauth op=%s outcome=%s trace=%s", op, outcome, trace)


def _oauth_json(exc: OAuthError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if exc.status == 401 and exc.error == "invalid_client":
        headers["WWW-Authenticate"] = 'Basic realm="mimer"'
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status,
        headers=headers,
    )


def _too_many() -> JSONResponse:
    return JSONResponse({"error": "temporarily_unavailable"}, status_code=429, headers=_NO_STORE)


async def _read_form(request: Request) -> dict[str, list[str]]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise OAuthError("invalid_request", "form encoding required")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_FORM_BYTES:
            raise OAuthError("invalid_request", "request too large", status=413)
    try:
        return parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=bool(body))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OAuthError("invalid_request", "malformed form") from exc


def public_app(server: AuthorizationServer) -> Starlette:
    rate = {"metadata": SlidingWindow(PUBLIC_RATE_PER_MINUTE, 60)}
    unauthenticated = SlidingWindow(PUBLIC_RATE_PER_MINUTE, 60)
    grant_failures = SlidingWindow(FAILED_TOKEN_ATTEMPTS_CAP, FAILED_TOKEN_WINDOW_SECONDS)

    def limited(
        name: str, handler: Callable[[Request], Awaitable[Response]]
    ) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            if rate[name].hit():
                _log(name, "rate_limited", security=True)
                return _too_many()
            return await handler(request)

        return endpoint

    async def protected_resource(_request: Request) -> Response:
        return JSONResponse(server.protected_resource_metadata())

    async def authorization_server(_request: Request) -> Response:
        return JSONResponse(server.authorization_server_metadata())

    async def token(request: Request) -> Response:
        # Unauthenticated noise from the public internet must never lock out the client:
        # it has its own budget, and only failures *after* client authentication (which
        # needs the client secret) count toward the lockout of the authenticated client.
        try:
            form = await _read_form(request)
            client_id = server.authenticate_client(
                form, authorization=request.headers.get("authorization")
            )
        except OAuthError as exc:
            if unauthenticated.hit():
                _log("token", "unauthenticated_rate_limited", security=True)
                return _too_many()
            _log("token", exc.error, security=exc.error == "invalid_client")
            return _oauth_json(exc)
        if grant_failures.exceeded():
            _log("token", "locked_out", security=True)
            return _too_many()
        try:
            issued = server.exchange_authenticated(form, client_id)
        except OAuthError as exc:
            grant_failures.record()
            _log("token", exc.error, security=exc.error == "invalid_grant")
            return _oauth_json(exc)
        _log("token", "issued")
        return JSONResponse(issued, headers=_NO_STORE)

    return Starlette(
        routes=[
            Route("/.well-known/oauth-protected-resource", limited("metadata", protected_resource)),
            Route(
                "/.well-known/oauth-protected-resource/{rest:path}",
                limited("metadata", protected_resource),
            ),
            Route(
                "/.well-known/oauth-authorization-server", limited("metadata", authorization_server)
            ),
            Route("/oauth/token", token, methods=["POST"]),
        ]
    )


def owner_identity(request: Request, owner_login: str, authorization_origin: str) -> str | None:
    """The owner's login when this request is a tailnet Serve request from the owner, else None.

    The identity headers are only meaningful on a request that Serve forwarded for the
    configured authorization origin, so the Host must match it (defeats DNS rebinding of the
    loopback backend). State-changing requests must also come from that origin.
    """

    expected = urlsplit(authorization_origin)
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or hosts[0].lower() not in _origin_hosts(expected):
        return None
    if request.method != "GET":
        origin = request.headers.get("origin")
        if origin is not None:
            if origin.rstrip("/").lower() != authorization_origin.lower():
                return None
        elif request.headers.get("sec-fetch-site") != "same-origin":
            return None
    if "tailscale-funnel-request" in request.headers:
        return None
    logins = request.headers.getlist("tailscale-user-login")
    if len(logins) != 1:
        # Tagged nodes carry no user identity; duplicates are never trusted.
        return None
    login = logins[0].strip()
    return login if login and login.casefold() == owner_login.casefold() else None


def _origin_hosts(origin: SplitResult) -> set[str]:
    host = (origin.hostname or "").lower()
    port = origin.port
    return {f"{host}:{port}"} if port not in (None, 443) else {host, f"{host}:443"}


def _consent_page(
    *, request_id: str, csrf: str, binding: str, tools: list[str], started_at: float
) -> str:
    started = datetime.fromtimestamp(started_at, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    items = "".join(f"<li><code>{html.escape(tool)}</code></li>" for tool in tools)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect Claude to Mimer</title>
<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem;line-height:1.5}}
button{{font-size:1rem;padding:.6rem 1.2rem;margin-right:.5rem}}</style></head><body>
<h1>Connect Claude to Mimer?</h1>
<p>Claude will be able to use these tools on vault binding <code>{html.escape(binding)}</code>:</p>
<ul>{items}</ul>
<p>Results are sent to Anthropic. This request started at {html.escape(started)}.</p>
<form method="post" action="/oauth/authorize/decision">
<input type="hidden" name="request_id" value="{html.escape(request_id)}">
<input type="hidden" name="csrf" value="{html.escape(csrf)}">
<button type="submit" name="decision" value="approve">Allow</button>
<button type="submit" name="decision" value="deny">Deny</button>
</form></body></html>"""


def _error_page(status: int, message: str) -> HTMLResponse:
    body = f"<!doctype html><title>Mimer</title><p>{html.escape(message)}</p>"
    return HTMLResponse(body, status_code=status, headers=_PAGE_HEADERS)


def _redirect_error(exc: OAuthError, state: str | None) -> Response:
    query = {"error": exc.error}
    if state:
        query["state"] = state
    return RedirectResponse(
        f"{REDIRECT_URI}?{urlencode(query)}", status_code=302, headers=_PAGE_HEADERS
    )


def tailnet_app(server: AuthorizationServer) -> Starlette:
    owner_login = server.config.owner_login
    origin = server.config.authorization_origin

    async def authorize(request: Request) -> Response:
        owner = owner_identity(request, owner_login, origin)
        if owner is None:
            _log("authorize", "identity_refused", security=True)
            return _error_page(403, "This page is only available to the owner on the tailnet.")
        params = parse_qs(request.url.query, keep_blank_values=True)
        try:
            consent = server.begin_authorization(params, owner=owner)
        except OAuthError as exc:
            _log("authorize", exc.error)
            if exc.redirectable:
                states = params.get("state", [])
                return _redirect_error(exc, states[0] if len(states) == 1 else None)
            return _error_page(exc.status, "This authorization request is not valid.")
        _log("authorize", "consent_shown")
        page = _consent_page(
            request_id=consent.request_id,
            csrf=consent.csrf,
            binding=consent.grant.vault_binding_id,
            tools=sorted(consent.grant.tools),
            started_at=consent.started_at,
        )
        return HTMLResponse(page, headers=_PAGE_HEADERS)

    async def decision(request: Request) -> Response:
        owner = owner_identity(request, owner_login, origin)
        if owner is None:
            _log("consent", "identity_refused", security=True)
            return _error_page(403, "This page is only available to the owner on the tailnet.")
        try:
            form = await _read_form(request)
            choice = form.get("decision", [""])
            if len(choice) != 1 or choice[0] not in {"approve", "deny"}:
                raise OAuthError("invalid_request", "decision required", status=400)
            target = server.decide(
                request_id=(form.get("request_id") or [""])[0],
                csrf=(form.get("csrf") or [""])[0],
                owner=owner,
                approve=choice[0] == "approve",
            )
        except OAuthError as exc:
            _log("consent", exc.error, security=exc.status == 403)
            return _error_page(
                exc.status, "This consent request is not valid. Start again from Claude."
            )
        _log("consent", "approved" if "code=" in target else "denied")
        return RedirectResponse(target, status_code=303, headers=_PAGE_HEADERS)

    return Starlette(
        routes=[
            Route("/oauth/authorize", authorize, methods=["GET"]),
            Route("/oauth/authorize/decision", decision, methods=["POST"]),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Run one listener: ``--surface public|tailnet --port N | --uds PATH`` (never non-loopback)."""

    import argparse
    import os
    from pathlib import Path

    import uvicorn

    from app.remote_mcp.oauth import CONFIG_PATH_ENV, load_config

    parser = argparse.ArgumentParser(prog="python -m app.remote_mcp.oauth_http")
    parser.add_argument("--surface", choices=["public", "tailnet"], required=True)
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--port", type=int, help="loopback TCP port")
    where.add_argument("--uds", type=Path, help="Unix socket (preferred for the tailnet surface)")
    parser.add_argument("--config", type=Path, default=os.environ.get(CONFIG_PATH_ENV))
    args = parser.parse_args(argv)
    if args.config is None:
        parser.error(f"--config or {CONFIG_PATH_ENV} is required")
    server = AuthorizationServer(load_config(args.config))
    app = public_app(server) if args.surface == "public" else tailnet_app(server)
    if args.uds is not None:
        os.umask(0o077)
        uvicorn.run(app, uds=str(args.uds), access_log=False, log_level="warning")
    else:
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["SlidingWindow", "owner_identity", "public_app", "tailnet_app"]
