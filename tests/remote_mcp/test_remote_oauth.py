"""ADR-0070 §3 single-owner OAuth server: client, PKCE, consent, tokens, grant coupling (#6668)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.remote_mcp.grant import GrantRefused, issue_grant, load_grant, revoke_grant
from app.remote_mcp.oauth import (
    REDIRECT_URI,
    AuthorizationServer,
    OAuthError,
    load_config,
    main as oauth_main,
    provision,
)
from app.remote_mcp.oauth_http import (
    FAILED_TOKEN_ATTEMPTS_CAP,
    PUBLIC_RATE_PER_MINUTE,
    public_app,
    tailnet_app,
)

ISSUER = "https://mimer.example.ts.net"
RESOURCE = f"{ISSUER}/mcp"
AUTH_ORIGIN = f"{ISSUER}:8443"
OWNER = "owner@example.invalid"
OWNER_HEADERS = {"Tailscale-User-Login": OWNER, "Origin": AUTH_ORIGIN}


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Rig:
    server: AuthorizationServer
    public: TestClient
    tailnet: TestClient
    clock: Clock
    client_id: str
    secret: str
    grant_path: Path
    config_path: Path

    @property
    def basic(self) -> dict[str, str]:
        raw = f"{self.client_id}:{self.secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    grant_path = tmp_path / "grant.json"
    issue_grant(
        grant_path, vault_binding_id="binding-a", tools=["mimer.health", "mimer.capture"], days=90
    )
    config_path = tmp_path / "oauth.json"
    config, secret = provision(
        config_path,
        issuer=ISSUER,
        resource=RESOURCE,
        authorization_origin=AUTH_ORIGIN,
        owner_login=OWNER,
        store_path=tmp_path / "oauth.sqlite3",
        grant_path=grant_path,
    )
    clock = Clock()
    server = AuthorizationServer(config, clock=clock)
    return Rig(
        server,
        TestClient(public_app(server)),
        TestClient(tailnet_app(server), base_url=AUTH_ORIGIN),
        clock,
        config.client_id,
        secret,
        grant_path,
        config_path,
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _auth_params(rig: Rig, challenge: str, **overrides: str) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": rig.client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-123",
        "resource": RESOURCE,
    }
    params.update(overrides)
    return {k: v for k, v in params.items() if v != "<omit>"}


def _consent(rig: Rig, challenge: str) -> tuple[str, str]:
    page = rig.tailnet.get(
        "/oauth/authorize", params=_auth_params(rig, challenge), headers=OWNER_HEADERS
    )
    assert page.status_code == 200, page.text
    assert "binding-a" in page.text and "mimer.capture" in page.text
    # no-referrer would make the browser send `Origin: null` on the consent POST.
    assert page.headers["referrer-policy"] == "same-origin"
    assert page.headers["x-frame-options"] == "DENY"
    request_id = re.search(r'name="request_id" value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return request_id, csrf


def _code(rig: Rig, challenge: str) -> str:
    request_id, csrf = _consent(rig, challenge)
    response = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "approve"},
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(REDIRECT_URI + "?")
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == ["st-123"]
    return query["code"][0]


def _exchange(rig: Rig, code: str, verifier: str, headers: dict | None = None, **extra: str):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
        **extra,
    }
    return rig.public.post(
        "/oauth/token", data=data, headers=rig.basic if headers is None else headers
    )


def _tokens(rig: Rig) -> dict:
    verifier, challenge = _pkce()
    response = _exchange(rig, _code(rig, challenge), verifier)
    assert response.status_code == 200, response.text
    return response.json()


def _refresh(rig: Rig, refresh_token: str, headers: dict | None = None):
    return rig.public.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        headers=rig.basic if headers is None else headers,
    )


def test_metadata_points_authorization_at_the_tailnet_origin(rig):
    resource = rig.public.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == RESOURCE and resource["authorization_servers"] == [ISSUER]
    meta = rig.public.get("/.well-known/oauth-authorization-server").json()
    assert meta["authorization_endpoint"] == f"{AUTH_ORIGIN}/oauth/authorize"
    assert meta["token_endpoint"] == f"{ISSUER}/oauth/token"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert "registration_endpoint" not in meta
    # The public surface has no authorization or consent route.
    assert rig.public.get("/oauth/authorize").status_code == 404
    assert rig.public.post("/oauth/authorize/decision").status_code == 404


def test_full_flow_issues_opaque_hashed_tokens_bound_to_the_grant(rig, caplog):
    caplog.set_level(logging.DEBUG, logger="mimer.remote_oauth")
    verifier, challenge = _pkce()
    code = _code(rig, challenge)
    response = _exchange(rig, code, verifier)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    tokens = response.json()
    assert tokens["token_type"] == "Bearer" and 3590 <= tokens["expires_in"] <= 3600
    grant = rig.server.verify_access_token(tokens["access_token"])
    assert grant.vault_binding_id == "binding-a"

    dump = "\n".join(sqlite3.connect(rig.server.config.store_path).iterdump())
    server_logs = "\n".join(
        r.getMessage() for r in caplog.records if r.name == "mimer.remote_oauth"
    )
    assert "op=token outcome=issued" in server_logs
    for secret in (code, tokens["access_token"], tokens["refresh_token"], rig.secret):
        assert secret not in dump
        assert secret not in server_logs
    assert "st-123" not in server_logs
    assert rig.secret not in rig.config_path.read_text()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**OWNER_HEADERS, "Tailscale-Funnel-Request": "?1"},
        {"Tailscale-User-Login": "someone@example.invalid"},
        [("Tailscale-User-Login", OWNER), ("Tailscale-User-Login", OWNER)],
    ],
)
def test_authorize_admits_only_the_owner_on_the_tailnet(rig, headers):
    _verifier, challenge = _pkce()
    response = rig.tailnet.get(
        "/oauth/authorize", params=_auth_params(rig, challenge), headers=headers
    )
    assert response.status_code == 403
    assert 'name="csrf"' not in response.text
    decision = rig.tailnet.post(
        "/oauth/authorize/decision", data={"decision": "approve"}, headers=headers
    )
    assert decision.status_code == 403


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge": "<omit>"}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"resource": "https://elsewhere.example/mcp"}, "invalid_target"),
    ],
)
def test_bad_authorization_requests_are_returned_to_the_verified_callback(rig, override, error):
    _verifier, challenge = _pkce()
    response = rig.tailnet.get(
        "/oauth/authorize",
        params=_auth_params(rig, challenge, **override),
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query == {"error": [error], "state": ["st-123"]}


@pytest.mark.parametrize(
    "override",
    [
        {"client_id": "other"},
        {"redirect_uri": "https://claude.ai/api/mcp/auth_callback/x"},
        {"redirect_uri": "https://evil.example/cb"},
    ],
)
def test_unknown_client_or_redirect_never_redirects(rig, override):
    _verifier, challenge = _pkce()
    response = rig.tailnet.get(
        "/oauth/authorize",
        params=_auth_params(rig, challenge, **override),
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "location" not in response.headers


def test_consent_requires_csrf_is_single_use_and_expires(rig):
    _verifier, challenge = _pkce()
    request_id, csrf = _consent(rig, challenge)
    bad = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": "wrong", "decision": "approve"},
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert bad.status_code == 403
    deny = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "deny"},
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert deny.status_code == 303
    assert parse_qs(urlsplit(deny.headers["location"]).query) == {
        "error": ["access_denied"],
        "state": ["st-123"],
    }
    again = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "approve"},
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert again.status_code == 403

    request_id, csrf = _consent(rig, challenge)
    rig.clock.advance(601)
    late = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "approve"},
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert late.status_code == 403


def test_code_is_single_use_and_replay_revokes_its_tokens(rig):
    verifier, challenge = _pkce()
    code = _code(rig, challenge)
    first = _exchange(rig, code, verifier).json()
    replay = _exchange(rig, code, verifier)
    assert (replay.status_code, replay.json()["error"]) == (400, "invalid_grant")
    with pytest.raises(OAuthError):
        rig.server.verify_access_token(first["access_token"])
    assert _refresh(rig, first["refresh_token"]).status_code == 400


def test_code_binding_pkce_expiry_and_client_authentication(rig):
    verifier, challenge = _pkce()
    code = _code(rig, challenge)
    wrong_verifier = _exchange(rig, code, _pkce()[0])
    assert wrong_verifier.json()["error"] == "invalid_grant"
    # A failed attempt still consumes the code.
    assert _exchange(rig, code, verifier).json()["error"] == "invalid_grant"

    code = _code(rig, challenge)
    assert (
        _exchange(rig, code, verifier, redirect_uri="https://claude.ai/other").json()["error"]
        == "invalid_grant"
    )

    code = _code(rig, challenge)
    bad_secret = {
        "Authorization": "Basic " + base64.b64encode(f"{rig.client_id}:nope".encode()).decode()
    }
    unauth = _exchange(rig, code, verifier, headers=bad_secret)
    assert (unauth.status_code, unauth.json()["error"]) == (401, "invalid_client")
    assert _exchange(rig, code, verifier, headers={}).status_code == 401

    code = _code(rig, challenge)
    rig.clock.advance(61)
    assert _exchange(rig, code, verifier).json()["error"] == "invalid_grant"

    code = _code(rig, challenge)
    posted = _exchange(
        rig, code, verifier, headers={}, client_id=rig.client_id, client_secret=rig.secret
    )
    assert posted.status_code == 200

    code = _code(rig, challenge)
    other_audience = _exchange(rig, code, verifier, resource="https://elsewhere.example/mcp")
    assert other_audience.json()["error"] == "invalid_target"


def test_refresh_rotates_with_one_grace_retry_then_revokes_the_family(rig):
    tokens = _tokens(rig)
    rotated = _refresh(rig, tokens["refresh_token"])
    assert rotated.status_code == 200
    rotated = rotated.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    # A provider retry with the previous token inside the grace window is accepted once.
    rig.clock.advance(10)
    assert _refresh(rig, tokens["refresh_token"]).status_code == 200
    reuse = _refresh(rig, tokens["refresh_token"])
    assert reuse.json()["error"] == "invalid_grant"
    with pytest.raises(OAuthError):
        rig.server.verify_access_token(rotated["access_token"])
    assert _refresh(rig, rotated["refresh_token"]).status_code == 400


def test_refresh_needs_client_auth_expires_and_after_grace_is_a_replay(rig):
    tokens = _tokens(rig)
    assert _refresh(rig, tokens["refresh_token"], headers={}).status_code == 401
    rotated = _refresh(rig, tokens["refresh_token"]).json()
    rig.clock.advance(61)
    assert _refresh(rig, tokens["refresh_token"]).json()["error"] == "invalid_grant"
    assert _refresh(rig, rotated["refresh_token"]).status_code == 400

    fresh = _tokens(rig)
    rig.clock.advance(3601)
    with pytest.raises(OAuthError):
        rig.server.verify_access_token(fresh["access_token"])
    rig.clock.advance(30 * 24 * 3600)
    assert _refresh(rig, fresh["refresh_token"]).json()["error"] == "invalid_grant"


def test_revoking_or_replacing_the_runtime_grant_ends_every_token(rig):
    tokens = _tokens(rig)
    revoke_grant(rig.grant_path)
    with pytest.raises(OAuthError) as refused:
        rig.server.verify_access_token(tokens["access_token"])
    assert refused.value.status == 401
    assert _refresh(rig, tokens["refresh_token"]).status_code == 400

    issue_grant(rig.grant_path, vault_binding_id="binding-a", tools=["mimer.health"], days=1)
    with pytest.raises(OAuthError):
        rig.server.verify_access_token(tokens["access_token"])
    # With an inactive grant no consent is offered at all.
    revoke_grant(rig.grant_path)
    _verifier, challenge = _pkce()
    response = rig.tailnet.get(
        "/oauth/authorize",
        params=_auth_params(rig, challenge),
        headers=OWNER_HEADERS,
        follow_redirects=False,
    )
    assert parse_qs(urlsplit(response.headers["location"]).query)["error"] == ["access_denied"]


def test_only_authenticated_failures_lock_the_token_endpoint(rig):
    tokens = _tokens(rig)
    # Unauthenticated internet noise has its own budget and never locks out the client.
    for _ in range(PUBLIC_RATE_PER_MINUTE + 5):
        rig.public.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": "x"})
    rotated = _refresh(rig, tokens["refresh_token"])
    assert rotated.status_code == 200
    assert rig.public.post("/oauth/token", data={"grant_type": "x"}).status_code == 429

    for _ in range(FAILED_TOKEN_ATTEMPTS_CAP):
        assert _refresh(rig, "not-a-token").status_code == 400
    assert _refresh(rig, rotated.json()["refresh_token"]).status_code == 429


@pytest.mark.parametrize(
    ("base_url", "headers", "method"),
    [
        # DNS rebinding of the loopback backend: wrong Host.
        ("http://127.0.0.1:8443", OWNER_HEADERS, "GET"),
        ("https://evil.example", OWNER_HEADERS, "GET"),
        ("https://mimer.example.ts.net", OWNER_HEADERS, "GET"),
        # Cross-origin POST, or no Origin and no same-origin fetch metadata.
        (AUTH_ORIGIN, {**OWNER_HEADERS, "Origin": "https://evil.example"}, "POST"),
        (AUTH_ORIGIN, {"Tailscale-User-Login": OWNER}, "POST"),
        (AUTH_ORIGIN, {"Tailscale-User-Login": OWNER, "Sec-Fetch-Site": "cross-site"}, "POST"),
        (AUTH_ORIGIN, {"Tailscale-User-Login": OWNER, "Origin": "null"}, "POST"),
    ],
)
def test_tailnet_surface_requires_its_own_host_and_origin(rig, base_url, headers, method):
    client = TestClient(tailnet_app(rig.server), base_url=base_url)
    _verifier, challenge = _pkce()
    if method == "GET":
        response = client.get(
            "/oauth/authorize", params=_auth_params(rig, challenge), headers=headers
        )
        assert response.status_code == 403
        assert 'name="csrf"' not in response.text
        return
    request_id, csrf = _consent(rig, challenge)
    response = client.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "approve"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 403
    # The refused attempt did not consume the pending request: the owner can still decide.
    # What a real browser sends for the consent form: an opaque Origin plus fetch metadata.
    same_origin = {"Tailscale-User-Login": OWNER, "Origin": "null", "Sec-Fetch-Site": "same-origin"}
    ok = rig.tailnet.post(
        "/oauth/authorize/decision",
        data={"request_id": request_id, "csrf": csrf, "decision": "approve"},
        headers=same_origin,
        follow_redirects=False,
    )
    assert ok.status_code == 303


def test_token_endpoint_bounds_and_encoding(rig):
    big = rig.public.post(
        "/oauth/token",
        content="a=" + "x" * 9000,
        headers={**rig.basic, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert big.status_code == 413
    as_json = rig.public.post(
        "/oauth/token", json={"grant_type": "refresh_token"}, headers=rig.basic
    )
    assert as_json.json()["error"] == "invalid_request"
    duplicated = rig.public.post(
        "/oauth/token",
        content="grant_type=refresh_token&grant_type=refresh_token",
        headers={**rig.basic, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert duplicated.json()["error"] == "invalid_request"
    unsupported = rig.public.post(
        "/oauth/token", data={"grant_type": "password"}, headers=rig.basic
    )
    assert unsupported.json()["error"] == "unsupported_grant_type"


def test_config_requires_a_separate_authorization_origin(tmp_path):
    path = tmp_path / "oauth.json"
    with pytest.raises(ValueError):
        provision(
            path,
            issuer=ISSUER,
            resource=RESOURCE,
            authorization_origin=ISSUER,
            owner_login=OWNER,
            store_path=tmp_path / "s",
            grant_path=tmp_path / "g",
        )
    with pytest.raises(ValueError):
        provision(
            path,
            issuer=ISSUER,
            resource="https://other.example/mcp",
            authorization_origin=AUTH_ORIGIN,
            owner_login=OWNER,
            store_path=tmp_path / "s",
            grant_path=tmp_path / "g",
        )


def test_owner_cli_provisions_rotates_and_revokes(tmp_path, capsys, rig):
    path = tmp_path / "cli.json"
    secret_file = tmp_path / "client-secret"
    args = [
        "provision",
        "--config",
        str(path),
        "--secret-out",
        str(secret_file),
        "--issuer",
        ISSUER,
        "--resource",
        RESOURCE,
        "--authorization-origin",
        AUTH_ORIGIN,
        "--owner-login",
        OWNER,
        "--store-path",
        str(tmp_path / "cli.sqlite3"),
        "--grant-path",
        str(rig.grant_path),
    ]
    assert oauth_main(args) == 0
    printed = capsys.readouterr().out
    issued = json.loads(secret_file.read_text())
    secret = issued["client_secret"]
    assert json.loads(printed) == {"handover_file": str(secret_file)}
    assert secret_file.stat().st_mode & 0o077 == 0
    assert secret not in path.read_text()
    assert load_config(path).client_id == issued["client_id"]
    # The secret file is never overwritten.
    assert (
        oauth_main(["rotate-secret", "--config", str(path), "--secret-out", str(secret_file)]) == 2
    )
    rotated_file = tmp_path / "client-secret-2"
    assert (
        oauth_main(["rotate-secret", "--config", str(path), "--secret-out", str(rotated_file)]) == 0
    )
    capsys.readouterr()
    assert json.loads(rotated_file.read_text())["client_secret"] != secret

    tokens = _tokens(rig)
    assert oauth_main(["revoke-tokens", "--config", str(rig.config_path)]) == 0
    with pytest.raises(OAuthError):
        rig.server.verify_access_token(tokens["access_token"])


def test_grant_file_must_be_private_regular_and_well_formed(tmp_path):
    path = tmp_path / "grant.json"
    issue_grant(path, vault_binding_id="b", tools=["mimer.health"], days=1)
    load_grant(path)
    os.chmod(path, 0o644)
    with pytest.raises(GrantRefused):
        load_grant(path)
    os.chmod(path, 0o600)

    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(GrantRefused):
        load_grant(link)

    payload = json.loads(path.read_text())
    for mutation in (
        {"credential_sha256": "é" * 64},
        {"credential_sha256": "ab"},
        {"expires_at": (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()},
    ):
        path.write_text(json.dumps({**payload, **mutation}))
        with pytest.raises(GrantRefused):
            load_grant(path)
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".remote-grant-")]
