"""Single-owner OAuth 2.1 authorization server for the remote MCP entrypoint (ADR-0070 §3).

Scope is deliberately minimal: one pre-registered confidential client, the exact Claude
callback, authorization code with PKCE S256, opaque tokens stored only as SHA-256 hashes,
refresh with client authentication and a one-time grace window after rotation. Every token is
bound to the host-side runtime grant (``app.remote_mcp.grant``) and re-checked against it on
every use, so revoking or replacing that grant ends all tokens.

Tokens are transport admission only; they carry no vault authority. Client and token records
are transport state, not governance authority.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence
from urllib.parse import unquote_plus, urlencode, urlsplit

from app.remote_mcp.grant import GrantRefused, RemoteGrant, load_grant

CONFIG_SCHEMA = "mimer_remote_oauth.v1"
CONFIG_PATH_ENV = "MIMER_REMOTE_OAUTH_CONFIG"
#: The only accepted redirect (Claude's connector callback), matched exactly.
REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
SCOPE = "mimer"

CODE_TTL_SECONDS = 60
PENDING_TTL_SECONDS = 600
ACCESS_TTL_SECONDS = 3600
REFRESH_TTL_SECONDS = 30 * 24 * 3600
REFRESH_GRACE_SECONDS = 60

_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9\-_]{43}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class OAuthError(Exception):
    """An RFC 6749 error response. ``redirectable`` errors go back to the client callback."""

    def __init__(
        self, error: str, description: str, *, status: int = 400, redirectable: bool = False
    ) -> None:
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.status = status
        self.redirectable = redirectable


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _https_origin(value: object, *, path_allowed: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("url must be a string")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.query
        or parts.fragment
        or parts.username
    ):
        raise ValueError(f"not an https url: {value!r}")
    if not path_allowed and parts.path not in ("", "/"):
        raise ValueError(f"origin must not carry a path: {value!r}")
    return value.rstrip("/") if not path_allowed else value


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    resource: str
    authorization_origin: str
    client_id: str
    client_secret_sha256: str
    owner_login: str
    store_path: Path
    grant_path: Path

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.authorization_origin}/oauth/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/oauth/token"

    def as_payload(self) -> dict[str, object]:
        return {
            "schema": CONFIG_SCHEMA,
            "issuer": self.issuer,
            "resource": self.resource,
            "authorization_origin": self.authorization_origin,
            "client_id": self.client_id,
            "client_secret_sha256": self.client_secret_sha256,
            "owner_login": self.owner_login,
            "store_path": str(self.store_path),
            "grant_path": str(self.grant_path),
        }


def load_config(path: Path) -> OAuthConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != CONFIG_SCHEMA:
        raise ValueError("not a remote OAuth config")
    issuer = _https_origin(raw["issuer"], path_allowed=False)
    resource = _https_origin(raw["resource"], path_allowed=True)
    authorization_origin = _https_origin(raw["authorization_origin"], path_allowed=False)
    if urlsplit(resource).netloc != urlsplit(issuer).netloc:
        raise ValueError("resource must be served from the issuer origin")
    if authorization_origin == issuer:
        # ADR-0070 §1: authorize/consent must live on the tailnet-only Serve origin.
        raise ValueError("authorization origin must differ from the public issuer origin")
    for key in ("client_id", "owner_login"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise ValueError(f"{key} is required")
    if not isinstance(raw["client_secret_sha256"], str) or not _HEX64.match(
        raw["client_secret_sha256"]
    ):
        raise ValueError("client_secret_sha256 must be a sha256 hex digest")
    return OAuthConfig(
        issuer=issuer,
        resource=resource,
        authorization_origin=authorization_origin,
        client_id=raw["client_id"],
        client_secret_sha256=raw["client_secret_sha256"],
        owner_login=raw["owner_login"],
        store_path=Path(raw["store_path"]),
        grant_path=Path(raw["grant_path"]),
    )


def write_config(path: Path, config: OAuthConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".oauth-config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config.as_payload(), handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pending (
    id TEXT PRIMARY KEY, csrf_sha256 TEXT NOT NULL, owner TEXT NOT NULL, client_id TEXT NOT NULL,
    code_challenge TEXT NOT NULL, state TEXT NOT NULL, grant_id TEXT NOT NULL,
    created_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS codes (
    code_sha256 TEXT PRIMARY KEY, client_id TEXT NOT NULL, redirect_uri TEXT NOT NULL,
    code_challenge TEXT NOT NULL, audience TEXT NOT NULL, state TEXT NOT NULL,
    grant_id TEXT NOT NULL, family_id TEXT NOT NULL, expires_at REAL NOT NULL,
    used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tokens (
    token_sha256 TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
    audience TEXT NOT NULL, grant_id TEXT NOT NULL, family_id TEXT NOT NULL,
    expires_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, rotated_at REAL,
    grace_used INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS tokens_family ON tokens(family_id);
"""


class OAuthStore:
    """SQLite transport state. Secrets are stored only as SHA-256 hashes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        db = sqlite3.connect(path, timeout=5)
        try:
            db.executescript(_SCHEMA_SQL)  # executescript manages its own commit
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def revoke_family(self, db: sqlite3.Connection, family_id: str) -> None:
        db.execute("UPDATE tokens SET revoked = 1 WHERE family_id = ?", (family_id,))

    def revoke_all(self) -> int:
        with self.transaction() as db:
            return db.execute("UPDATE tokens SET revoked = 1 WHERE revoked = 0").rowcount


@dataclass(frozen=True)
class ConsentRequest:
    request_id: str
    csrf: str
    grant: RemoteGrant
    started_at: float


def _single(params: Mapping[str, Sequence[str]], name: str, *, required: bool = True) -> str | None:
    values = params.get(name, [])
    if len(values) > 1:
        raise OAuthError("invalid_request", f"duplicate parameter {name}")
    if not values or values[0] == "":
        if required:
            raise OAuthError("invalid_request", f"missing parameter {name}")
        return None
    return values[0]


class AuthorizationServer:
    def __init__(self, config: OAuthConfig, *, clock: Callable[[], float] = time.time) -> None:
        self.config = config
        self.store = OAuthStore(config.store_path)
        self._clock = clock

    # --- metadata -------------------------------------------------------------------------

    def protected_resource_metadata(self) -> dict[str, object]:
        return {
            "resource": self.config.resource,
            "authorization_servers": [self.config.issuer],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [SCOPE],
        }

    def authorization_server_metadata(self) -> dict[str, object]:
        return {
            "issuer": self.config.issuer,
            "authorization_endpoint": self.config.authorization_endpoint,
            "token_endpoint": self.config.token_endpoint,
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "scopes_supported": [SCOPE],
        }

    # --- runtime grant --------------------------------------------------------------------

    def _live_grant(self, *, redirectable: bool = False) -> RemoteGrant:
        try:
            grant = load_grant(self.config.grant_path)
        except GrantRefused as exc:
            raise OAuthError(
                "temporarily_unavailable",
                "remote grant unavailable",
                status=503,
                redirectable=redirectable,
            ) from exc
        if not grant.active or grant.expires_at.timestamp() <= self._clock():
            raise OAuthError(
                "access_denied", "remote grant is not active", status=403, redirectable=redirectable
            )
        return grant

    # --- authorization (tailnet-only origin) ----------------------------------------------

    def begin_authorization(
        self, params: Mapping[str, Sequence[str]], *, owner: str
    ) -> ConsentRequest:
        """Validate an authorization request and record it pending the owner's explicit consent."""

        client_id = _single(params, "client_id")
        redirect_uri = _single(params, "redirect_uri")
        if client_id != self.config.client_id or redirect_uri != REDIRECT_URI:
            # Never redirect to an unverified client or callback.
            raise OAuthError("invalid_request", "unknown client or redirect")
        state = _single(params, "state")
        assert state is not None
        try:
            if _single(params, "response_type") != "code":
                raise OAuthError("unsupported_response_type", "only code is supported")
            challenge = _single(params, "code_challenge")
            if _single(params, "code_challenge_method") != "S256" or not _CHALLENGE.match(
                challenge or ""
            ):
                raise OAuthError("invalid_request", "PKCE S256 is required")
            resource = _single(params, "resource", required=False)
            if resource is not None and resource != self.config.resource:
                raise OAuthError("invalid_target", "unknown resource")
            grant = self._live_grant()
        except OAuthError as exc:
            exc.redirectable = True
            raise
        assert challenge is not None
        request_id = secrets.token_urlsafe(18)
        csrf = secrets.token_urlsafe(32)
        now = self._clock()
        with self.store.transaction() as db:
            db.execute("DELETE FROM pending WHERE created_at < ?", (now - PENDING_TTL_SECONDS,))
            db.execute(
                "INSERT INTO pending (id, csrf_sha256, owner, client_id, code_challenge, state, grant_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    _sha256(csrf),
                    owner,
                    client_id,
                    challenge,
                    state,
                    grant.grant_id,
                    now,
                ),
            )
        return ConsentRequest(request_id=request_id, csrf=csrf, grant=grant, started_at=now)

    def decide(self, *, request_id: str, csrf: str, owner: str, approve: bool) -> str:
        """Consume a pending request (single use) and return the client redirect URL."""

        now = self._clock()
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM pending WHERE id = ?", (request_id,)).fetchone()
            valid = (
                row is not None
                and not row["consumed"]
                and row["created_at"] >= now - PENDING_TTL_SECONDS
                and row["owner"] == owner
                and hmac.compare_digest(row["csrf_sha256"], _sha256(csrf))
            )
            if valid:
                db.execute("UPDATE pending SET consumed = 1 WHERE id = ?", (request_id,))
        if not valid:
            raise OAuthError("invalid_request", "consent request is not valid", status=403)
        state = row["state"]
        if not approve:
            return f"{REDIRECT_URI}?{urlencode({'error': 'access_denied', 'state': state})}"
        grant = self._live_grant(redirectable=True)
        if grant.grant_id != row["grant_id"]:
            raise OAuthError("access_denied", "remote grant changed during consent", status=403)
        code = secrets.token_urlsafe(32)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO codes (code_sha256, client_id, redirect_uri, code_challenge, audience, state,"
                " grant_id, family_id, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _sha256(code),
                    row["client_id"],
                    REDIRECT_URI,
                    row["code_challenge"],
                    self.config.resource,
                    state,
                    grant.grant_id,
                    secrets.token_hex(12),
                    now + CODE_TTL_SECONDS,
                ),
            )
        return f"{REDIRECT_URI}?{urlencode({'code': code, 'state': state})}"

    # --- token endpoint (public origin) ---------------------------------------------------

    def _authenticate_client(
        self, form: Mapping[str, Sequence[str]], authorization: str | None
    ) -> str:
        basic: tuple[str, str] | None = None
        if authorization:
            scheme, _, value = authorization.partition(" ")
            if scheme.lower() != "basic":
                raise OAuthError("invalid_client", "unsupported client authentication", status=401)
            try:
                decoded = base64.b64decode(value, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError) as exc:
                raise OAuthError(
                    "invalid_client", "malformed client authentication", status=401
                ) from exc
            user, sep, password = decoded.partition(":")
            if not sep:
                raise OAuthError("invalid_client", "malformed client authentication", status=401)
            basic = (unquote_plus(user), unquote_plus(password))
        posted_id = _single(form, "client_id", required=False)
        posted_secret = _single(form, "client_secret", required=False)
        if basic is not None and posted_secret is not None:
            raise OAuthError("invalid_request", "use one client authentication method")
        client_id, secret = basic if basic is not None else (posted_id, posted_secret)
        if basic is not None and posted_id is not None and posted_id != client_id:
            raise OAuthError("invalid_client", "client mismatch", status=401)
        if (
            client_id is None
            or secret is None
            or not hmac.compare_digest(client_id.encode(), self.config.client_id.encode())
            or not hmac.compare_digest(_sha256(secret), self.config.client_secret_sha256)
        ):
            raise OAuthError("invalid_client", "client authentication failed", status=401)
        return client_id

    def _check_resource(self, form: Mapping[str, Sequence[str]]) -> None:
        resource = _single(form, "resource", required=False)
        if resource is not None and resource != self.config.resource:
            raise OAuthError("invalid_target", "unknown resource")

    def _issue_pair(
        self,
        db: sqlite3.Connection,
        *,
        client_id: str,
        grant: RemoteGrant,
        family_id: str,
        refresh_expires_at: float,
    ) -> dict[str, object]:
        now = self._clock()
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        access_expires = min(now + ACCESS_TTL_SECONDS, grant.expires_at.timestamp())
        rows = (
            (_sha256(access), "access", access_expires),
            (_sha256(refresh), "refresh", min(refresh_expires_at, grant.expires_at.timestamp())),
        )
        for digest, kind, expires in rows:
            db.execute(
                "INSERT INTO tokens (token_sha256, kind, client_id, audience, grant_id, family_id, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (digest, kind, client_id, self.config.resource, grant.grant_id, family_id, expires),
            )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": max(1, int(access_expires - now)),
            "refresh_token": refresh,
            "scope": SCOPE,
        }

    def exchange(
        self, form: Mapping[str, Sequence[str]], *, authorization: str | None
    ) -> dict[str, object]:
        client_id = self._authenticate_client(form, authorization)
        grant_type = _single(form, "grant_type")
        self._check_resource(form)
        if grant_type == "authorization_code":
            return self._exchange_code(form, client_id)
        if grant_type == "refresh_token":
            return self._exchange_refresh(form, client_id)
        raise OAuthError("unsupported_grant_type", "unsupported grant type")

    # Single-use marks and revocations must commit even when the request is refused, so each
    # exchange records its refusal inside the transaction and raises only after commit.

    def _exchange_code(
        self, form: Mapping[str, Sequence[str]], client_id: str
    ) -> dict[str, object]:
        code = _single(form, "code")
        redirect_uri = _single(form, "redirect_uri")
        verifier = _single(form, "code_verifier")
        assert code is not None and verifier is not None
        now = self._clock()
        failure: OAuthError | None = None
        result: dict[str, object] = {}
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM codes WHERE code_sha256 = ?", (_sha256(code),)
            ).fetchone()
            if row is None:
                failure = OAuthError("invalid_grant", "unknown code")
            elif row["used"]:
                # A replayed code revokes everything issued from it (OAuth 2.1 §4.1.3).
                self.store.revoke_family(db, row["family_id"])
                failure = OAuthError("invalid_grant", "code already used")
            else:
                db.execute("UPDATE codes SET used = 1 WHERE code_sha256 = ?", (row["code_sha256"],))
                failure = self._code_failure(
                    row, client_id=client_id, redirect_uri=redirect_uri, verifier=verifier, now=now
                )
                if failure is None:
                    grant, failure = self._grant_matching(row["grant_id"])
                    if grant is not None:
                        result = self._issue_pair(
                            db,
                            client_id=client_id,
                            grant=grant,
                            family_id=row["family_id"],
                            refresh_expires_at=now + REFRESH_TTL_SECONDS,
                        )
        if failure is not None:
            raise failure
        return result

    @staticmethod
    def _code_failure(
        row: sqlite3.Row, *, client_id: str, redirect_uri: str | None, verifier: str, now: float
    ) -> OAuthError | None:
        if row["expires_at"] <= now:
            return OAuthError("invalid_grant", "code expired")
        if row["client_id"] != client_id or row["redirect_uri"] != redirect_uri:
            return OAuthError("invalid_grant", "code not issued for this client or redirect")
        if not _VERIFIER.match(verifier):
            return OAuthError("invalid_grant", "malformed code verifier")
        computed = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode()
        )
        if not hmac.compare_digest(computed, row["code_challenge"]):
            return OAuthError("invalid_grant", "PKCE verification failed")
        return None

    def _grant_matching(self, grant_id: str) -> tuple[RemoteGrant | None, OAuthError | None]:
        try:
            grant = self._live_grant()
        except OAuthError as exc:
            return None, OAuthError("invalid_grant", exc.description)
        if grant.grant_id != grant_id:
            return None, OAuthError("invalid_grant", "remote grant changed")
        return grant, None

    def _exchange_refresh(
        self, form: Mapping[str, Sequence[str]], client_id: str
    ) -> dict[str, object]:
        presented = _single(form, "refresh_token")
        assert presented is not None
        now = self._clock()
        failure: OAuthError | None = None
        result: dict[str, object] = {}
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM tokens WHERE token_sha256 = ? AND kind = 'refresh'",
                (_sha256(presented),),
            ).fetchone()
            if row is None or row["revoked"] or row["client_id"] != client_id:
                failure = OAuthError("invalid_grant", "refresh token is not valid")
            elif row["expires_at"] <= now:
                failure = OAuthError("invalid_grant", "refresh token expired")
            elif row["rotated_at"] is not None and (
                now - row["rotated_at"] > REFRESH_GRACE_SECONDS or row["grace_used"]
            ):
                self.store.revoke_family(db, row["family_id"])
                failure = OAuthError("invalid_grant", "refresh token already rotated")
            else:
                if row["rotated_at"] is None:
                    db.execute(
                        "UPDATE tokens SET rotated_at = ? WHERE token_sha256 = ?",
                        (now, row["token_sha256"]),
                    )
                else:  # the one retry admitted inside the grace window
                    db.execute(
                        "UPDATE tokens SET grace_used = 1 WHERE token_sha256 = ?",
                        (row["token_sha256"],),
                    )
                grant, failure = self._grant_matching(row["grant_id"])
                if grant is None:
                    self.store.revoke_family(db, row["family_id"])
                else:
                    result = self._issue_pair(
                        db,
                        client_id=client_id,
                        grant=grant,
                        family_id=row["family_id"],
                        refresh_expires_at=row["expires_at"],
                    )
        if failure is not None:
            raise failure
        return result

    # --- resource-server check (used by the MCP entrypoint) ------------------------------

    def verify_access_token(self, presented: str | None) -> RemoteGrant:
        """Return the live runtime grant for a valid access token, or raise ``OAuthError(401)``."""

        if not presented:
            raise OAuthError("invalid_token", "missing access token", status=401)
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM tokens WHERE token_sha256 = ? AND kind = 'access'",
                (_sha256(presented),),
            ).fetchone()
        if (
            row is None
            or row["revoked"]
            or row["expires_at"] <= self._clock()
            or row["audience"] != self.config.resource
        ):
            raise OAuthError("invalid_token", "access token is not valid", status=401)
        try:
            grant = self._live_grant()
        except OAuthError as exc:
            raise OAuthError("invalid_token", "remote grant is not active", status=401) from exc
        if grant.grant_id != row["grant_id"]:
            raise OAuthError("invalid_token", "remote grant changed", status=401)
        return grant


# --- owner CLI ------------------------------------------------------------------------------


def provision(
    path: Path,
    *,
    issuer: str,
    resource: str,
    authorization_origin: str,
    owner_login: str,
    store_path: Path,
    grant_path: Path,
) -> tuple[OAuthConfig, str]:
    """Write a config with a fresh client id and secret; returns the secret (printed once)."""

    secret = secrets.token_urlsafe(32)
    config = OAuthConfig(
        issuer=issuer.rstrip("/"),
        resource=resource,
        authorization_origin=authorization_origin.rstrip("/"),
        client_id=f"mimer-{secrets.token_hex(8)}",
        client_secret_sha256=_sha256(secret),
        owner_login=owner_login,
        store_path=store_path,
        grant_path=grant_path,
    )
    write_config(path, config)
    load_config(path)  # validate what was written
    return config, secret


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.remote_mcp.oauth")
    sub = parser.add_subparsers(dest="command", required=True)
    prov = sub.add_parser("provision", help="create the client; prints the client secret once")
    prov.add_argument("--config", type=Path, required=True)
    for flag in ("--issuer", "--resource", "--authorization-origin", "--owner-login"):
        prov.add_argument(flag, required=True)
    prov.add_argument("--store-path", type=Path, required=True)
    prov.add_argument("--grant-path", type=Path, required=True)
    rotate = sub.add_parser(
        "rotate-secret", help="replace the client secret; prints the new one once"
    )
    rotate.add_argument("--config", type=Path, required=True)
    revoke = sub.add_parser("revoke-tokens", help="revoke every issued token")
    revoke.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "provision":
            config, secret = provision(
                args.config,
                issuer=args.issuer,
                resource=args.resource,
                authorization_origin=args.authorization_origin,
                owner_login=args.owner_login,
                store_path=args.store_path,
                grant_path=args.grant_path,
            )
            print(json.dumps({"client_id": config.client_id, "client_secret": secret}))
        elif args.command == "rotate-secret":
            current = load_config(args.config)
            secret = secrets.token_urlsafe(32)
            write_config(
                args.config,
                OAuthConfig(**{**current.__dict__, "client_secret_sha256": _sha256(secret)}),
            )
            print(json.dumps({"client_id": current.client_id, "client_secret": secret}))
        else:
            revoked = OAuthStore(load_config(args.config).store_path).revoke_all()
            print(json.dumps({"revoked": revoked}))
    except (ValueError, KeyError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
