"""YSS-02 (#3917): minimal-scope OAuth 2.0 account binding for YouTube.

Implements ``docs/YOUTUBE_SOURCE_SYNC/BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md`` and
the normative ``SOURCE_SYNC_CONTRACT.md :: Secrets and private bindings /
Egress posture / Reason codes``. Two consent flows over the existing ``httpx``
dependency (no Google SDK):

- **Device authorization grant (primary)** -- headless-friendly; the user
  approves in any browser via the complete-URL / QR.
- **Loopback installed-app grant (secondary)** -- authorization-code + PKCE
  against a ``127.0.0.1`` redirect, with OAuth ``state`` validated before any
  code exchange.

The single requested scope is exactly ``youtube.readonly`` (AC7). Tokens are
persisted only through the AES-256-GCM ``youtube_token_store``; the non-secret
account binding lives in ``youtube_account_binding``; OAuth client credentials
resolve from host env and their values are never persisted or printed.

Secret discipline (INV-YSS-5): no refresh/access token, authorization/device
code, or client secret ever appears in a returned payload, log line, event,
receipt, or exception text. The guarantee is primarily *structural* -- secrets
never enter those objects -- and defended by redaction-aware ``__repr__`` on
the secret-bearing dataclasses, provider-error sanitization (HTTP status + the
``error`` enum only, never a response body that might echo a token), and
:func:`redact` over every emitted mapping.

Auth degradation (INV-YSS-4): a revoked/expired grant or a missing token-store
key degrades the binding and its dependent authenticated sources with a legible
reason code, mutates no source cursor, and never records an auth failure as an
empty-success. Connect, reconnect, refresh, and disconnect serialize each
binding's credential lifecycle across service instances and processes that
share its channel token store. A retryable revoke failure preserves the
encrypted credential and source state; a permanent provider rejection completes
local teardown because the old grant no longer provides useful retry authority.
Acquired artifacts are never deleted.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

import httpx

from app.knowledge_acquisition.source_registry import SourceRegistry
from app.knowledge_acquisition.youtube_account_binding import AccountBinding, AccountBindingStore
from app.knowledge_acquisition.youtube_token_store import (
    StoredToken,
    TokenStoreKeyMissingError,
    YouTubeTokenStore,
    resolve_token_store_key,
)

_log = logging.getLogger(__name__)

# --- Contract constants ------------------------------------------------------

SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
CLIENT_ID_ENV = "YOUTUBE_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "YOUTUBE_OAUTH_CLIENT_SECRET"

# Egress posture (SSRF guard): every OAuth call must target one of these hosts.
ALLOWED_OAUTH_HOSTS: frozenset[str] = frozenset(
    {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"}
)
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

_DEFAULT_TIMEOUT_SECONDS = 30.0
_ACCESS_TOKEN_SKEW_SECONDS = 60

# Defense-in-depth redaction: a value is redacted when its key name carries a
# secret marker, EXCEPT for these documented non-secret mode fields whose names
# merely contain such a substring.
_SECRET_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "refresh",
    "authorization",
    "client_id",
    "device_code",
    "code_verifier",
)
_REDACTION_SAFE_KEYS = frozenset({"token_store", "token_type"})


# --- Errors ------------------------------------------------------------------


class OAuthClientCredentialsMissingError(RuntimeError):
    """OAuth client id/secret env not provisioned (host secret boundary)."""


class OAuthStateMismatchError(RuntimeError):
    """Loopback ``state`` did not match -- refuse to exchange the code."""


class DisallowedOAuthHostError(RuntimeError):
    """Refused OAuth egress to a non-allowlisted host (SSRF guard)."""


class OAuthProviderError(RuntimeError):
    """A non-2xx (or transport) response from the OAuth provider.

    Carries only the HTTP ``status`` and the provider's ``error`` enum value --
    never the response body, which could echo a token (INV-YSS-5).
    """

    def __init__(self, *, status: int, error_code: str | None) -> None:
        self.status = status
        self.error_code = error_code
        super().__init__(f"OAuth provider error: HTTP {status} ({error_code or 'unknown'})")


class DeviceAuthorizationPending(RuntimeError):
    """The user has not yet approved the device code (poll again after interval)."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(f"device authorization pending: {error_code}")


class DeviceAuthorizationError(RuntimeError):
    """The device flow terminally failed (denied or expired) before any binding."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(f"device authorization failed: {error_code}")


class AuthDegradedError(RuntimeError):
    """An authenticated operation degraded with a legible reason code (INV-YSS-4)."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or f"authentication degraded: {reason_code}")


class ReconnectChannelMismatchError(RuntimeError):
    """Reconnect consent resolved to a different channel than the target binding."""


# --- Credential + redaction helpers -----------------------------------------


def resolve_oauth_client_credentials() -> tuple[str, str]:
    """Resolve ``(client_id, client_secret)`` from env; fail loud if absent.

    Their *values* are never persisted or printed; only the env-var *names* may
    appear in settings/receipts (INV-YSS-5).
    """
    client_id = (os.environ.get(CLIENT_ID_ENV) or "").strip()
    client_secret = (os.environ.get(CLIENT_SECRET_ENV) or "").strip()
    if not client_id or not client_secret:
        missing = [n for n, v in ((CLIENT_ID_ENV, client_id), (CLIENT_SECRET_ENV, client_secret)) if not v]
        raise OAuthClientCredentialsMissingError(
            "OAuth client credentials are not provisioned: missing env "
            f"{', '.join(missing)}. Provision them via the host secret boundary "
            "(docs/LOCAL_SECRET_PROVISIONING/); their values are never stored in the repo/vault."
        )
    return client_id, client_secret


def redact(payload: Any) -> Any:
    """Redaction-aware copy: values under secret-marked keys become ``***``.

    Defense-in-depth over the structural guarantee that secrets never enter
    emitted payloads. Known non-secret mode fields (``token_store``,
    ``token_type``) are preserved.
    """
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            if key_lower not in _REDACTION_SAFE_KEYS and any(m in key_lower for m in _SECRET_KEY_MARKERS):
                out[key] = "***"
            else:
                out[key] = redact(value)
        return out
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    return payload


def _safe_error_code(response: httpx.Response) -> str | None:
    """Extract only the provider ``error`` enum; never the body (INV-YSS-5)."""
    try:
        body = response.json()
    except Exception:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, str):
            return error
    return None


def _retryable_revoke_error(error: OAuthProviderError) -> bool:
    """Whether provider revocation can safely be retried with this token."""
    return error.status == 0 or error.status in {408, 429} or 500 <= error.status < 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso(expires_in: Any) -> str | None:
    if expires_in is None:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# --- Value types -------------------------------------------------------------


@dataclass(frozen=True)
class ChannelIdentity:
    """The connected account's primary channel (resolved by an injected probe).

    Resolving the real channel id/title is a Data API read owned by YSS-03; this
    slice takes it as an injected ``IdentityProbe`` so the binding seam stays
    decoupled from the API client (and stubbable in tests).
    """

    channel_id: str
    channel_title: str


IdentityProbe = Callable[[str], ChannelIdentity]


@dataclass(frozen=True)
class TokenBundle:
    """A token grant/refresh result. Secret fields are redacted in ``repr``."""

    access_token: str
    refresh_token: str | None
    expires_in: int | None
    scope: str | None
    token_type: str | None

    def __repr__(self) -> str:  # redaction-aware (INV-YSS-5)
        return (
            f"TokenBundle(access_token=***, refresh_token=***, expires_in={self.expires_in!r}, "
            f"scope={self.scope!r}, token_type={self.token_type!r})"
        )


@dataclass(frozen=True)
class DeviceFlowHandle:
    """Device-flow handle. ``device_code`` is secret-ish and never emitted."""

    device_code: str
    user_code: str
    verification_url: str
    verification_url_complete: str
    interval: int
    expires_in: int

    def __repr__(self) -> str:  # redaction-aware (INV-YSS-5)
        return (
            f"DeviceFlowHandle(device_code=***, user_code={self.user_code!r}, "
            f"verification_url={self.verification_url!r}, "
            f"verification_url_complete={self.verification_url_complete!r}, "
            f"interval={self.interval!r}, expires_in={self.expires_in!r})"
        )

    def public_view(self) -> dict[str, Any]:
        """The non-secret subset safe to emit as ``--json`` (no ``device_code``)."""
        return redact(
            {
                "user_code": self.user_code,
                "verification_url": self.verification_url,
                "verification_url_complete": self.verification_url_complete,
                "interval": self.interval,
                "expires_in": self.expires_in,
            }
        )


@dataclass(frozen=True)
class LoopbackFlow:
    """Loopback flow handle. ``code_verifier`` is a PKCE secret; never emitted."""

    authorization_url: str
    state: str
    code_verifier: str
    redirect_uri: str

    def __repr__(self) -> str:  # redaction-aware (INV-YSS-5)
        # The authorization_url embeds the client_id, state, and code_challenge;
        # redact it wholesale so a repr'd flow in a log/exception cannot leak the
        # client identifier or the CSRF state (redacting only the fields would
        # otherwise be defeated by printing the URL that contains them).
        return (
            "LoopbackFlow(authorization_url=***, state=***, code_verifier=***, "
            f"redirect_uri={self.redirect_uri!r})"
        )


@dataclass(frozen=True)
class DeviceConnection:
    """An in-flight device connection (start → finish), plus reconnect target."""

    handle: DeviceFlowHandle
    reconnect_binding_id: str | None = None

    def public_view(self) -> dict[str, Any]:
        return self.handle.public_view()


def _bundle_from_response(data: dict[str, Any]) -> TokenBundle:
    access = data.get("access_token")
    if not access or not isinstance(access, str):
        # A 2xx token response with no access token is not a success -- never
        # treat it as an empty-success (INV-YSS-4).
        raise OAuthProviderError(status=200, error_code="missing_access_token")
    return TokenBundle(
        access_token=access,
        refresh_token=data.get("refresh_token"),
        expires_in=data.get("expires_in"),
        scope=data.get("scope"),
        token_type=data.get("token_type"),
    )


# --- OAuth HTTP client -------------------------------------------------------


class OAuthClient:
    """Thin OAuth 2.0 client over ``httpx`` with an SSRF host allowlist.

    Every request targets an allowlisted host; a non-2xx response is surfaced as
    a sanitized :class:`OAuthProviderError` (status + provider ``error`` enum).
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        http: httpx.Client,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._timeout = timeout

    @classmethod
    def from_env(cls, *, http: httpx.Client, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> "OAuthClient":
        client_id, client_secret = resolve_oauth_client_credentials()
        return cls(client_id=client_id, client_secret=client_secret, http=http, timeout=timeout)

    def _guard_host(self, url: str) -> None:
        host = urlsplit(url).hostname
        if host not in ALLOWED_OAUTH_HOSTS:
            raise DisallowedOAuthHostError(
                f"refusing OAuth egress to non-allowlisted host: {host!r} "
                f"(allowed: {sorted(ALLOWED_OAUTH_HOSTS)})"
            )

    def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self._guard_host(url)
        try:
            response = self._http.post(
                url, data=data, timeout=self._timeout, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            # Sanitized: exception class only -- never a URL (may carry query
            # secrets) or response body (INV-YSS-5).
            raise OAuthProviderError(status=0, error_code=type(exc).__name__) from None
        if response.status_code // 100 != 2:
            raise OAuthProviderError(status=response.status_code, error_code=_safe_error_code(response))
        if not response.content:
            return {}
        try:
            body = response.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    def start_device_flow(self) -> DeviceFlowHandle:
        data = self._post(DEVICE_CODE_URL, {"client_id": self._client_id, "scope": SCOPE})
        _log.debug("youtube oauth: device flow started")
        return DeviceFlowHandle(
            device_code=str(data.get("device_code", "")),
            user_code=str(data.get("user_code", "")),
            verification_url=str(data.get("verification_url") or data.get("verification_uri") or ""),
            verification_url_complete=str(
                data.get("verification_url_complete") or data.get("verification_uri_complete") or ""
            ),
            interval=int(data.get("interval", 5)),
            expires_in=int(data.get("expires_in", 1800)),
        )

    def poll_device_flow(self, device_code: str) -> TokenBundle:
        """One device-token poll. Raises :class:`DeviceAuthorizationPending`
        while the user has not approved, :class:`DeviceAuthorizationError` on a
        terminal denial/expiry, and returns the :class:`TokenBundle` on grant.
        """
        try:
            data = self._post(
                TOKEN_URL,
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "device_code": device_code,
                    "grant_type": DEVICE_GRANT_TYPE,
                },
            )
        except OAuthProviderError as exc:
            if exc.error_code in ("authorization_pending", "slow_down"):
                raise DeviceAuthorizationPending(exc.error_code) from None
            if exc.error_code in ("access_denied", "expired_token"):
                raise DeviceAuthorizationError(exc.error_code) from None
            raise
        return _bundle_from_response(data)

    def build_authorization_url(self, *, redirect_uri: str, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> TokenBundle:
        data = self._post(
            TOKEN_URL,
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return _bundle_from_response(data)

    def refresh(self, refresh_token: str) -> TokenBundle:
        try:
            data = self._post(
                TOKEN_URL,
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except OAuthProviderError as exc:
            if exc.error_code == "invalid_grant":
                raise AuthDegradedError("auth_revoked", "refresh token rejected (invalid_grant)") from None
            raise
        return _bundle_from_response(data)

    def revoke(self, token: str) -> None:
        self._post(REVOKE_URL, {"token": token})


# --- Loopback (installed-app) flow ------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)  # 43-128 chars per RFC 7636
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def start_loopback_flow(client: OAuthClient, *, redirect_uri: str) -> LoopbackFlow:
    """Build the loopback authorization request: URL + ``state`` + PKCE verifier.

    The tokens never appear in any URL beyond the provider's own redirect params
    (BIND spec); the caller opens ``authorization_url`` and later hands the
    redirect back to :func:`complete_loopback_flow`.
    """
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    url = client.build_authorization_url(redirect_uri=redirect_uri, state=state, code_challenge=challenge)
    return LoopbackFlow(authorization_url=url, state=state, code_verifier=verifier, redirect_uri=redirect_uri)


def complete_loopback_flow(
    client: OAuthClient, flow: LoopbackFlow, *, returned_state: str, returned_code: str
) -> TokenBundle:
    """Validate the redirect ``state`` (constant-time) then exchange the code.

    A tampered/mismatched ``state`` is refused with :class:`OAuthStateMismatchError`
    before any token exchange happens.
    """
    if not hmac.compare_digest(returned_state, flow.state):
        raise OAuthStateMismatchError(
            "OAuth state mismatch: refusing to exchange the authorization code (possible CSRF/tamper)"
        )
    return client.exchange_code(
        code=returned_code, code_verifier=flow.code_verifier, redirect_uri=flow.redirect_uri
    )


# --- Expiry-aware access-token provider -------------------------------------


class TokenProvider:
    """Expiry-aware access-token provider with single-flight refresh.

    Returns a valid access token, refreshing under a lock when the cached one is
    within the skew window of expiry. A missing token-store key or a rejected
    refresh degrades the binding and its dependent sources (INV-YSS-4) and
    raises :class:`AuthDegradedError` -- it never returns an empty/absent token
    as a success.
    """

    def __init__(
        self,
        *,
        binding_id: str,
        token_store: YouTubeTokenStore,
        oauth_client: OAuthClient,
        binding_store: AccountBindingStore | None = None,
        source_registry: SourceRegistry | None = None,
        skew_seconds: int = _ACCESS_TOKEN_SKEW_SECONDS,
    ) -> None:
        self._binding_id = binding_id
        self._store = token_store
        self._client = oauth_client
        self._bindings = binding_store
        self._registry = source_registry
        self._skew = skew_seconds
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        with self._lock:
            # This file-backed binding lock composes the single-flight refresh
            # with connect/reconnect/disconnect across service instances and
            # runtime processes (#3990 review repair).
            with self._store.binding_lifecycle_lock(self._binding_id):
                token = self._read_token()
                if self._is_fresh(token):
                    return token.access_token  # type: ignore[return-value]
                return self._refresh(token)

    def _read_token(self) -> StoredToken:
        try:
            token = self._store.get(self._binding_id)
        except TokenStoreKeyMissingError:
            self._degrade("auth_key_missing")
            raise AuthDegradedError("auth_key_missing", "token store key is not provisioned") from None
        if token is None:
            self._degrade("auth_missing")
            raise AuthDegradedError("auth_missing", "no token stored for this binding")
        return token

    def _is_fresh(self, token: StoredToken) -> bool:
        if not token.access_token or not token.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(token.expires_at)
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc) + timedelta(seconds=self._skew)

    def _refresh(self, token: StoredToken) -> str:
        _log.debug("youtube oauth: refreshing access token for binding %s", self._binding_id)
        try:
            bundle = self._client.refresh(token.refresh_token)
        except AuthDegradedError as exc:
            self._degrade(exc.reason_code)
            raise
        refreshed = StoredToken(
            refresh_token=bundle.refresh_token or token.refresh_token,
            access_token=bundle.access_token,
            expires_at=_expiry_iso(bundle.expires_in),
            scopes=token.scopes or (SCOPE,),
            obtained_at=_now_iso(),
            provider_channel_id=token.provider_channel_id,
        )
        self._store.put(self._binding_id, refreshed)
        self._clear_degradation()
        return bundle.access_token

    def _degrade(self, reason_code: str) -> None:
        """Stamp the reason on the binding + dependent sources; no cursor touched."""
        if self._bindings is not None:
            binding = self._bindings.get(self._binding_id)
            if binding is not None:
                self._bindings.set_state(self._binding_id, state="degraded", reason_code=reason_code)
        if self._registry is not None:
            for source in self._registry.list_for_account(self._binding_id):
                self._registry.record_source_degradation(source.binding_id, reason_code=reason_code)

    def _clear_degradation(self) -> None:
        if self._bindings is None:
            return
        binding = self._bindings.get(self._binding_id)
        if binding is not None and binding.state != "connected":
            self._bindings.set_state(self._binding_id, state="connected", reason_code=None)


# --- Account binding manager -------------------------------------------------


class YouTubeAccountBinder:
    """Connect / status / disconnect / reconnect for a YouTube account binding.

    Wires the OAuth flows, the encrypted token store, the account-binding
    registry, and (for degradation) the source registry into the one seam every
    authenticated surface uses.
    """

    def __init__(
        self,
        *,
        oauth_client: OAuthClient,
        token_store: YouTubeTokenStore,
        binding_store: AccountBindingStore,
        identity_probe: IdentityProbe,
        source_registry: SourceRegistry | None = None,
    ) -> None:
        self._client = oauth_client
        self._store = token_store
        self._bindings = binding_store
        self._identity = identity_probe
        self._registry = source_registry

    # -- connect (device flow) ------------------------------------------------

    def start_device_connection(self) -> DeviceConnection:
        return DeviceConnection(handle=self._client.start_device_flow(), reconnect_binding_id=None)

    def start_reconnect(self, binding_id: str) -> DeviceConnection:
        if self._bindings.get(binding_id) is None:
            raise KeyError(f"no such account binding: {binding_id}")
        return DeviceConnection(handle=self._client.start_device_flow(), reconnect_binding_id=binding_id)

    def finish_device_connection(self, connection: DeviceConnection) -> dict[str, Any]:
        """Complete one device poll, persist tokens encrypted, bind the account.

        Returns the non-secret connect receipt ``{status, account}`` -- no token
        material. Raises :class:`DeviceAuthorizationPending` if the user has not
        approved yet (the caller re-polls after ``interval``).
        """
        bundle = self._client.poll_device_flow(connection.handle.device_code)
        return self._bind_from_bundle(bundle, connection.reconnect_binding_id)

    def _bind_from_bundle(self, bundle: TokenBundle, reconnect_binding_id: str | None) -> dict[str, Any]:
        if not bundle.refresh_token:
            # A binding with no refresh token cannot sustain access; fail loud at
            # bind time rather than storing an empty credential that only breaks
            # later on the first refresh. The loopback/device requests set
            # access_type=offline + prompt=consent, so a grant should always
            # carry one.
            raise OAuthProviderError(status=200, error_code="missing_refresh_token")
        identity = self._identity(bundle.access_token)
        token = StoredToken(
            refresh_token=bundle.refresh_token,
            access_token=bundle.access_token,
            expires_at=_expiry_iso(bundle.expires_in),
            scopes=(SCOPE,),
            obtained_at=_now_iso(),
            provider_channel_id=identity.channel_id,
        )
        identity_authority = reconnect_binding_id or f"channel:{identity.channel_id}"
        with self._store.binding_lifecycle_lock(identity_authority):
            binding = self._resolve_binding(identity, reconnect_binding_id)
            binding_id = binding.account_binding_id if binding is not None else str(uuid.uuid4())
            lifecycle = (
                self._store.binding_lifecycle_lock(binding_id)
                if binding_id != identity_authority
                else nullcontext()
            )
            with lifecycle:
                return self._commit_binding(binding, binding_id, identity, token)

    def _commit_binding(
        self,
        binding: AccountBinding | None,
        binding_id: str,
        identity: ChannelIdentity,
        token: StoredToken,
    ) -> dict[str, Any]:
        if binding is not None:
            # Re-read inside shared authority so a completed disconnect cannot
            # leave reconnect acting on stale ``connected`` state.
            current_binding = self._bindings.get(binding_id)
            if current_binding is None:
                raise KeyError(f"no such account binding: {binding_id}")
            binding = current_binding
            # Persist the encrypted credential before creating a row whose durable
            # state claims the account is connected. A missing/invalid key therefore
            # cannot leave a connected binding without a token record (#3990).
        self._store.put(binding_id, token)
        if binding is None:
            try:
                binding = self._bindings.create(
                    provider_channel_id=identity.channel_id,
                    display_label=identity.channel_title,
                    scopes=[SCOPE],
                    account_binding_id=binding_id,
                )
            except Exception:
                # Compensate the private-store write if the non-secret binding
                # cannot be committed. No orphan credential should survive.
                self._store.delete(binding_id)
                raise
        if binding.state != "connected" or binding.reason_code is not None:
            binding = self._bindings.set_state(
                binding.account_binding_id, state="connected", reason_code=None
            )
        _log.info("youtube oauth: account connected (binding %s)", binding.account_binding_id)
        return redact(
            {
                "status": "connected",
                "account": {
                    "binding_id": binding.account_binding_id,
                    "channel_title": binding.display_label,
                },
            }
        )

    def _resolve_binding(
        self, identity: ChannelIdentity, reconnect_binding_id: str | None
    ) -> AccountBinding | None:
        if reconnect_binding_id is not None:
            target = self._bindings.get(reconnect_binding_id)
            if target is None:
                raise KeyError(f"no such account binding: {reconnect_binding_id}")
            if target.provider_channel_id != identity.channel_id:
                raise ReconnectChannelMismatchError(
                    "reconnect consent resolved to a different channel than the target binding"
                )
            return target
        existing = self._bindings.get_by_channel_id(identity.channel_id)
        if existing is not None:
            return existing
        return None

    # -- status ---------------------------------------------------------------

    def status(self, binding_id: str) -> dict[str, Any]:
        """Live, non-secret status view for ``binding_id``.

        Derives the fail-closed ``auth_key_missing`` state when a token record
        exists but the store key is absent (INV-YSS-4), without persisting a
        read-derived state.
        """
        binding = self._bindings.get(binding_id)
        if binding is None:
            return redact(
                {"status": "absent", "reason_code": "auth_missing", "scopes": [], "token_store": "encrypted"}
            )
        state, reason_code = binding.state, binding.reason_code
        has_token = self._store.has_record(binding_id)
        if has_token:
            try:
                resolve_token_store_key()
            except TokenStoreKeyMissingError:
                state, reason_code = "degraded", "auth_key_missing"
        elif state == "connected":
            # Fail closed for any historical/partial connected row that lacks
            # the encrypted authority needed by authenticated operations.
            state, reason_code = "degraded", "auth_missing"
        return redact(
            {
                "status": state,
                "reason_code": reason_code,
                "scopes": list(binding.scopes),
                "token_store": "encrypted",
            }
        )

    # -- disconnect -----------------------------------------------------------

    def disconnect(self, binding_id: str) -> dict[str, Any]:
        """Revoke at the provider, then tear down local authenticated state.

        Retryable provider failure leaves the encrypted token and connected
        source state intact so the operator can retry revocation. Successful
        revocation or a permanent provider rejection deletes the token record,
        disables dependent sources with ``auth_disconnected``, and deletes no
        acquired artifacts. The whole transition is binding-serialized with
        connect/reconnect/refresh across service instances and processes.
        """
        with self._store.binding_lifecycle_lock(binding_id):
            binding = self._bindings.get(binding_id)
            if binding is None:
                raise KeyError(f"no such account binding: {binding_id}")

            revoked = False
            try:
                token = self._store.get(binding_id)
            except TokenStoreKeyMissingError:
                # The encrypted record is the only recoverable remote-revocation
                # authority. Preserve it until the key is re-provisioned.
                return redact(
                    {
                        "status": "disconnect_failed",
                        "reason_code": "auth_key_missing",
                        "revoked": False,
                        "retryable": True,
                        "sources_disabled": 0,
                    }
                )
            if token is not None:
                revocation_token = token.refresh_token or token.access_token or ""
                if revocation_token:
                    try:
                        self._client.revoke(revocation_token)
                        revoked = True
                    except OAuthProviderError as error:
                        if _retryable_revoke_error(error):
                            _log.warning(
                                "youtube oauth: retryable provider revoke failure; encrypted "
                                "token preserved (binding %s)",
                                binding_id,
                            )
                            return redact(
                                {
                                    "status": "disconnect_failed",
                                    "revoked": False,
                                    "retryable": True,
                                    "sources_disabled": 0,
                                }
                            )
                        _log.warning(
                            "youtube oauth: provider permanently rejected revoke; "
                            "continuing local disconnect (binding %s)",
                            binding_id,
                        )

            self._store.delete(binding_id)
            self._bindings.set_state(
                binding_id, state="degraded", reason_code="auth_disconnected"
            )

            sources_disabled = 0
            if self._registry is not None:
                for source in self._registry.list_for_account(binding_id):
                    self._registry.disable_source_for_auth(
                        source.binding_id, reason_code="auth_disconnected"
                    )
                    sources_disabled += 1

            _log.info("youtube oauth: account disconnected (binding %s)", binding_id)
            return redact(
                {
                    "status": "disconnected",
                    "revoked": revoked,
                    "sources_disabled": sources_disabled,
                }
            )


__all__ = [
    "ALLOWED_OAUTH_HOSTS",
    "AUTHORIZATION_ENDPOINT",
    "AuthDegradedError",
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "ChannelIdentity",
    "DEVICE_CODE_URL",
    "DeviceAuthorizationError",
    "DeviceAuthorizationPending",
    "DeviceConnection",
    "DeviceFlowHandle",
    "DisallowedOAuthHostError",
    "IdentityProbe",
    "LoopbackFlow",
    "OAuthClient",
    "OAuthClientCredentialsMissingError",
    "OAuthProviderError",
    "OAuthStateMismatchError",
    "REVOKE_URL",
    "ReconnectChannelMismatchError",
    "SCOPE",
    "TOKEN_URL",
    "TokenBundle",
    "TokenProvider",
    "YouTubeAccountBinder",
    "complete_loopback_flow",
    "redact",
    "resolve_oauth_client_credentials",
    "start_loopback_flow",
]
