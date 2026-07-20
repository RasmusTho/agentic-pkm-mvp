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
share its channel token store. Key and atomic-store readiness are proven before
device polling, including cryptographic key/aggregate binding; an issued grant
is encrypted in a pending journal before the identity probe or binding work,
and an unproven compensation preserves that recoverable authority. Pending
promotion/cleanup and retry share one lifecycle-lock order, and retry never
revokes a grant represented by canonical encrypted authority. First-connect
binding ids are deterministic per provider channel, and an indeterminate
binding-create result always preserves the encrypted credential so a delayed
commit or retry retains authority. Only
Google's documented ``400 invalid_token`` revoke outcome permits destructive
local teardown; every other revoke failure preserves retry authority. OAuth
POSTs never follow redirects. Acquired artifacts are never deleted.
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
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, NoReturn
from urllib.parse import urlencode, urlsplit

import httpx

from app.knowledge_acquisition.source_registry import SourceRegistry
from app.knowledge_acquisition.youtube_account_binding import AccountBinding, AccountBindingStore
from app.knowledge_acquisition.youtube_token_store import (
    StoredToken,
    TokenStoreDurabilityError,
    TokenStoreKeyMissingError,
    YouTubeTokenStore,
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

# Provider-controlled strings are not safe merely because they occupy an
# ``error`` field: a proxy or malformed response could echo secret material
# there. Admit only documented OAuth enums that local control flow understands
# or may safely report.
_SAFE_OAUTH_ERROR_CODES: frozenset[str] = frozenset(
    {
        "access_denied",
        "authorization_pending",
        "expired_token",
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "invalid_scope",
        "invalid_token",
        "slow_down",
        "temporarily_unavailable",
        "unauthorized_client",
        "unsupported_grant_type",
        "unsupported_response_type",
        "unsupported_token_type",
    }
)


# --- Errors ------------------------------------------------------------------


class OAuthClientCredentialsMissingError(RuntimeError):
    """OAuth client id/secret env not provisioned (host secret boundary)."""


class OAuthStateMismatchError(RuntimeError):
    """Loopback ``state`` did not match -- refuse to exchange the code."""


class InvalidLoopbackRedirectURIError(ValueError):
    """Loopback redirect is outside the exact installed-app boundary."""


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


class OAuthGrantDurabilityError(RuntimeError):
    """An issued grant was compensated or retained as pending authority."""

    def __init__(self, reason_code: str, *, pending_grant_id: str | None = None) -> None:
        self.reason_code = reason_code
        self.pending_grant_id = pending_grant_id
        if reason_code == "grant_compensated":
            message = "OAuth grant finalization failed; provider revocation was confirmed"
        elif reason_code == "grant_pending":
            message = "OAuth grant finalization failed; encrypted pending authority was preserved"
        elif reason_code == "refresh_pending":
            message = "OAuth refresh finalization failed; encrypted pending authority was preserved"
        elif reason_code == "refresh_conflict":
            message = "OAuth refresh finalization found conflicting encrypted authority"
        else:
            message = "OAuth grant finalization failed without durable recovery authority"
        super().__init__(message)


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
        if isinstance(error, str) and error in _SAFE_OAUTH_ERROR_CODES:
            return error
    return None


def _provider_confirms_token_already_invalid(error: OAuthProviderError) -> bool:
    """Whether Google authoritatively says the revoke objective already holds.

    Google's revocation contract documents ``invalid_token`` for a token that
    is already expired or revoked, and documents HTTP 400 for error outcomes.
    Status alone is not authority: intermediary and malformed-request 4xx
    responses preserve the encrypted credential for retry.
    """
    return error.status == 400 and error.error_code == "invalid_token"


def _binding_candidate_id(provider_channel_id: str) -> str:
    """Return the stable first-connect idempotency key for a YouTube channel."""
    name = f"urn:agentic-pkm:youtube-account-binding:{provider_channel_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def _pending_grant_id(device_code: str, reconnect_binding_id: str | None) -> str:
    """Opaque stable journal id for one device-flow completion attempt."""
    target = reconnect_binding_id or "first-connect"
    digest = hashlib.sha256(f"{target}\0{device_code}".encode("utf-8")).hexdigest()
    return f"pending-youtube-grant-{digest}"


def _pending_refresh_id(binding_id: str) -> str:
    """Stable opaque journal id for one binding's serialized refresh lane."""
    digest = hashlib.sha256(f"youtube-refresh\0{binding_id}".encode("utf-8")).hexdigest()
    return f"pending-youtube-refresh-{digest}"


def _same_refresh_authority(left: StoredToken, right: StoredToken) -> bool:
    """Constant-time equality for the standing provider credential."""
    return bool(left.refresh_token) and hmac.compare_digest(
        left.refresh_token, right.refresh_token
    )


def _canonical_token_from_pending(pending: StoredToken) -> StoredToken:
    """Remove encrypted retry metadata before canonical persistence."""
    return replace(
        pending,
        promotion_target_binding_id=None,
        promotion_predecessor_refresh_token=None,
        promotion_predecessor_generation=None,
        promotion_display_label=None,
        promotion_compensation_state=None,
    )


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


def _bundle_from_response(
    data: dict[str, Any], *, preserve_refresh_on_incomplete_access: bool = False
) -> TokenBundle:
    access = data.get("access_token")
    if not access or not isinstance(access, str):
        refresh = data.get("refresh_token")
        if preserve_refresh_on_incomplete_access and isinstance(refresh, str) and refresh:
            # Device completion owns compensation/journaling. Preserve the
            # refresh credential in-memory long enough for that boundary to
            # revoke or encrypt it instead of throwing it away in the parser.
            return TokenBundle(
                access_token="",
                refresh_token=refresh,
                expires_in=data.get("expires_in"),
                scope=data.get("scope"),
                token_type=data.get("token_type"),
            )
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
                url,
                data=data,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
                follow_redirects=False,
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
        return _bundle_from_response(data, preserve_refresh_on_incomplete_access=True)

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


def _validate_loopback_redirect_uri(redirect_uri: str) -> None:
    """Admit only ``http://127.0.0.1:<ephemeral-port>/<path>``.

    Flow handles can cross a serialization boundary, so creation and
    completion both validate. The error excludes the rejected URI because its
    userinfo/query text is untrusted and may contain credential material.
    """
    valid = (
        isinstance(redirect_uri, str)
        and redirect_uri == redirect_uri.strip()
        and "?" not in redirect_uri
        and "#" not in redirect_uri
        and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in redirect_uri)
    )
    try:
        parsed = urlsplit(redirect_uri) if valid else None
        port = parsed.port if parsed is not None else None
    except ValueError:
        parsed = None
        port = None
    if (
        parsed is None
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidLoopbackRedirectURIError(
            "OAuth loopback redirect must use exact http 127.0.0.1 with an explicit valid port and no userinfo, query, or fragment"
        )


def start_loopback_flow(client: OAuthClient, *, redirect_uri: str) -> LoopbackFlow:
    """Build the loopback authorization request: URL + ``state`` + PKCE verifier.

    The tokens never appear in any URL beyond the provider's own redirect params
    (BIND spec); the caller opens ``authorization_url`` and later hands the
    redirect back to :func:`complete_loopback_flow`.
    """
    _validate_loopback_redirect_uri(redirect_uri)
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
    _validate_loopback_redirect_uri(flow.redirect_uri)
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
                token = self._recover_pending_refresh(token)
                terminal_reason = self._terminal_binding_reason()
                if terminal_reason is not None:
                    raise AuthDegradedError(
                        terminal_reason,
                        "account binding authority is locally disabled",
                    ) from None
                if self._is_fresh(token):
                    return token.access_token  # type: ignore[return-value]
                return self._refresh(token)

    def _read_token(self) -> StoredToken:
        try:
            token = self._store.get(self._binding_id)
        except TokenStoreKeyMissingError:
            terminal_reason = self._terminal_binding_reason()
            if terminal_reason is not None:
                raise AuthDegradedError(
                    terminal_reason, "account binding is disconnected"
                ) from None
            self._degrade("auth_key_missing")
            raise AuthDegradedError("auth_key_missing", "token store key is not provisioned") from None
        if token is None:
            terminal_reason = self._terminal_binding_reason()
            if terminal_reason is not None:
                raise AuthDegradedError(
                    terminal_reason, "account binding is disconnected"
                ) from None
            self._degrade("auth_missing")
            raise AuthDegradedError("auth_missing", "no token stored for this binding")
        return token

    def _terminal_binding_reason(self) -> str | None:
        if self._bindings is None:
            return None
        binding = self._bindings.get(self._binding_id)
        if binding is not None and binding.reason_code in {
            "auth_disconnected",
            "auth_revoked",
        }:
            return binding.reason_code
        return None

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
        # The provider call can return fresh authority. Prove the encrypted
        # aggregate and its crash barrier before crossing that boundary.
        self._store.preflight_write_ready()
        try:
            bundle = self._client.refresh(token.refresh_token)
        except AuthDegradedError as exc:
            self._degrade(exc.reason_code)
            raise
        rotated_refresh = (
            bundle.refresh_token
            if isinstance(bundle.refresh_token, str)
            and bundle.refresh_token
            and not hmac.compare_digest(bundle.refresh_token, token.refresh_token)
            else None
        )
        refreshed = StoredToken(
            refresh_token=rotated_refresh or token.refresh_token,
            access_token=bundle.access_token,
            expires_at=_expiry_iso(bundle.expires_in),
            scopes=token.scopes or (SCOPE,),
            obtained_at=_now_iso(),
            provider_channel_id=token.provider_channel_id,
            authority_generation=(
                token.authority_generation + 1
                if rotated_refresh is not None
                else token.authority_generation
            ),
        )
        pending_id: str | None = None
        if rotated_refresh is not None:
            pending_id = _pending_refresh_id(self._binding_id)
            pending = replace(
                refreshed,
                promotion_target_binding_id=self._binding_id,
                promotion_predecessor_refresh_token=token.refresh_token,
                promotion_predecessor_generation=token.authority_generation,
            )
            if not self._write_refresh_journal(pending_id, pending):
                # Google documents refresh as access-token renewal, but if an
                # adversarial/non-standard response rotates the standing
                # credential and local journaling still fails after preflight,
                # revoke that returned authority when the provider can confirm
                # it.  An indeterminate double failure remains fail-closed.
                compensation_pending = replace(
                    pending, promotion_compensation_state="pending"
                )
                if not self._write_refresh_journal(
                    pending_id, compensation_pending
                ):
                    self._degrade("auth_refresh_durability")
                    raise OAuthGrantDurabilityError(
                        "refresh_durability_unavailable"
                    ) from None
                if self._compensate_refresh_rotation(compensation_pending):
                    compensated = replace(
                        compensation_pending,
                        promotion_compensation_state="compensated",
                    )
                    self._write_refresh_journal(pending_id, compensated)
                    self._degrade("auth_revoked")
                    self._delete_refresh_journal(pending_id)
                    raise AuthDegradedError(
                        "auth_revoked",
                        "rotated refresh authority was revoked after local durability failure",
                    ) from None
                self._degrade("auth_refresh_durability")
                raise OAuthGrantDurabilityError(
                    "refresh_durability_unavailable"
                ) from None

        write_error: Exception | None = None
        try:
            self._store.put(self._binding_id, refreshed)
        except Exception as error:
            write_error = error
        if write_error is not None and not self._stored_token_matches(
            self._binding_id, refreshed, write_error=write_error
        ):
            if pending_id is not None:
                self._degrade("auth_refresh_pending")
                raise OAuthGrantDurabilityError(
                    "refresh_pending", pending_grant_id=pending_id
                ) from None
            self._degrade("auth_refresh_durability")
            raise OAuthGrantDurabilityError("refresh_durability_unavailable") from None
        if pending_id is not None:
            self._delete_refresh_journal(pending_id)
        self._clear_degradation()
        return bundle.access_token

    def _recover_pending_refresh(self, canonical: StoredToken) -> StoredToken:
        """Promote a journal only while its exact predecessor is canonical."""
        pending_id = _pending_refresh_id(self._binding_id)
        pending = self._store.get(pending_id)
        if pending is None:
            return canonical
        compensation_state = pending.promotion_compensation_state
        if compensation_state is not None:
            if compensation_state == "pending":
                if not self._compensate_refresh_rotation(pending):
                    self._degrade("auth_refresh_durability")
                    raise OAuthGrantDurabilityError(
                        "refresh_durability_unavailable",
                        pending_grant_id=pending_id,
                    ) from None
                compensated = replace(
                    pending, promotion_compensation_state="compensated"
                )
                self._write_refresh_journal(pending_id, compensated)
                pending = compensated
            elif compensation_state != "compensated":
                self._degrade("auth_refresh_durability")
                raise OAuthGrantDurabilityError(
                    "refresh_durability_unavailable",
                    pending_grant_id=pending_id,
                ) from None
            self._degrade("auth_revoked")
            self._delete_refresh_journal(pending_id)
            raise AuthDegradedError(
                "auth_revoked",
                "rotated refresh authority was already provider-compensated",
            ) from None
        if (
            pending.promotion_target_binding_id != self._binding_id
            or pending.promotion_predecessor_refresh_token is None
            or pending.promotion_predecessor_generation is None
        ):
            self._degrade("auth_refresh_conflict")
            raise OAuthGrantDurabilityError(
                "refresh_conflict", pending_grant_id=pending_id
            ) from None

        if _same_refresh_authority(pending, canonical):
            # Canonical promotion already landed (possibly with a lost ack), or
            # a later access-only refresh retained the same standing grant.
            self._delete_refresh_journal(pending_id)
            self._clear_degradation()
            return canonical

        predecessor_matches = (
            canonical.authority_generation
            == pending.promotion_predecessor_generation
            and hmac.compare_digest(
                canonical.refresh_token,
                pending.promotion_predecessor_refresh_token,
            )
        )
        if not predecessor_matches:
            # A newer/different canonical credential is proven. Neither delete
            # nor revoke the mismatched pending authority, and never overwrite
            # the newer generation.
            self._degrade("auth_refresh_conflict")
            raise OAuthGrantDurabilityError(
                "refresh_conflict", pending_grant_id=pending_id
            ) from None

        promoted = _canonical_token_from_pending(pending)
        write_error: Exception | None = None
        try:
            self._store.put(self._binding_id, promoted)
        except Exception as error:
            write_error = error
        if write_error is not None and not self._stored_token_matches(
            self._binding_id, promoted, write_error=write_error
        ):
            self._degrade("auth_refresh_pending")
            raise OAuthGrantDurabilityError(
                "refresh_pending", pending_grant_id=pending_id
            ) from None
        self._delete_refresh_journal(pending_id)
        self._clear_degradation()
        return promoted

    def _write_refresh_journal(self, pending_id: str, pending: StoredToken) -> bool:
        """Persist rotated authority, retrying one post-preflight store fault."""
        for _attempt in range(2):
            write_error: Exception | None = None
            try:
                self._store.put(pending_id, pending)
            except Exception as error:
                write_error = error
            if write_error is None or self._stored_token_matches(
                pending_id, pending, write_error=write_error
            ):
                return True
        return False

    def _delete_refresh_journal(self, pending_id: str) -> None:
        try:
            self._store.delete(pending_id)
        except Exception:
            _log.warning(
                "youtube oauth: canonical refresh retained redundant encrypted journal"
            )

    def _stored_token_matches(
        self,
        binding_id: str,
        expected: StoredToken,
        *,
        write_error: Exception | None = None,
    ) -> bool:
        if isinstance(write_error, TokenStoreDurabilityError):
            return self._store.confirm_record_durable(binding_id, expected)
        try:
            return self._store.get(binding_id) == expected
        except Exception:
            return False

    def _compensate_refresh_rotation(self, pending: StoredToken) -> bool:
        try:
            self._client.revoke(pending.refresh_token)
            return True
        except OAuthProviderError as error:
            return _provider_confirms_token_already_invalid(error)
        except Exception:
            return False

    def _degrade(self, reason_code: str) -> None:
        """Stamp the reason on the binding + dependent sources; no cursor touched."""
        if self._bindings is not None:
            binding = self._bindings.get(self._binding_id)
            if binding is not None:
                if binding.reason_code in {"auth_disconnected", "auth_revoked"}:
                    return
                self._bindings.set_state(self._binding_id, state="degraded", reason_code=reason_code)
        if self._registry is not None:
            for source in self._registry.list_for_account(self._binding_id):
                self._registry.record_source_degradation(source.binding_id, reason_code=reason_code)

    def _clear_degradation(self) -> None:
        if self._bindings is None:
            return
        binding = self._bindings.get(self._binding_id)
        if (
            binding is not None
            and binding.state != "connected"
            and binding.reason_code not in {"auth_disconnected", "auth_revoked"}
        ):
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

    @staticmethod
    def _refresh_degradation_reason(reason_code: str) -> str:
        return {
            "refresh_pending": "auth_refresh_pending",
            "refresh_conflict": "auth_refresh_conflict",
            "refresh_compensated": "auth_revoked",
        }.get(reason_code, "auth_refresh_durability")

    def _degrade_refresh_authority(
        self,
        binding_id: str,
        *,
        reason_code: str,
        pending_grant_id: str | None,
    ) -> None:
        """Persist fail-closed refresh state on binding and dependent sources."""
        failed = False
        try:
            self._bindings.set_state(
                binding_id, state="degraded", reason_code=reason_code
            )
            if self._registry is not None:
                for source in self._registry.list_for_account(binding_id):
                    self._registry.record_source_degradation(
                        source.binding_id, reason_code=reason_code
                    )
        except Exception:
            failed = True
        if failed:
            raise OAuthGrantDurabilityError(
                "refresh_durability_unavailable",
                pending_grant_id=pending_grant_id,
            ) from None

    def retry_pending_grant_compensation(self, pending_grant_id: str) -> dict[str, Any]:
        """Retry revocation for one encrypted pre-binding grant journal."""
        if not pending_grant_id.startswith("pending-youtube-grant-"):
            raise ValueError("not a YouTube pending-grant journal id")
        with self._store.binding_lifecycle_lock(pending_grant_id):
            token = self._store.get(pending_grant_id)
            if token is None:
                return {"status": "absent", "pending_grant_id": pending_grant_id}
            # A cleanup failure after canonical success leaves two encrypted
            # copies of one grant. Retry must never revoke the provider grant
            # while a canonical binding still depends on it. Compose the same
            # pending -> channel -> binding lock order as promotion, re-read
            # both sides under those authorities, then clean or compensate.
            channel_authority = (
                f"channel:{token.provider_channel_id}"
                if token.provider_channel_id is not None
                else None
            )
            channel_lifecycle = (
                self._store.binding_lifecycle_lock(channel_authority)
                if channel_authority is not None
                else nullcontext()
            )
            with channel_lifecycle:
                canonical_ids = {
                    binding_id
                    for binding_id in self._store.binding_ids()
                    if binding_id != pending_grant_id
                    and not binding_id.startswith("pending-youtube-grant-")
                    and not binding_id.startswith("pending-youtube-refresh-")
                }
                if token.provider_channel_id is not None:
                    canonical_ids.add(_binding_candidate_id(token.provider_channel_id))
                    visible = self._bindings.get_by_channel_id(token.provider_channel_id)
                    if visible is not None:
                        canonical_ids.add(visible.account_binding_id)
                if token.promotion_target_binding_id is not None:
                    canonical_ids.add(token.promotion_target_binding_id)

                with ExitStack() as lifecycle_stack:
                    for binding_id in sorted(canonical_ids):
                        lifecycle_stack.enter_context(
                            self._store.binding_lifecycle_lock(binding_id)
                        )
                    token = self._store.get(pending_grant_id)
                    if token is None:
                        return {
                            "status": "absent",
                            "pending_grant_id": pending_grant_id,
                        }
                    resolution, canonical_id = self._pending_resolution(
                        token, canonical_ids
                    )
                    if resolution == "canonical" and canonical_id is not None:
                        try:
                            canonical_binding = self._bindings.get(canonical_id)
                        except Exception:
                            canonical_binding = None
                        if (
                            canonical_binding is None
                            or canonical_binding.provider_channel_id
                            != token.provider_channel_id
                        ):
                            recovery, recovered_binding = (
                                self._recover_candidate_binding_row(
                                    token, canonical_id
                                )
                            )
                            if recovery != "recovered" or recovered_binding is None:
                                return {
                                    "status": recovery,
                                    "pending_grant_id": pending_grant_id,
                                    "binding_id": (
                                        recovered_binding.account_binding_id
                                        if recovered_binding is not None
                                        else canonical_id
                                    ),
                                }
                            canonical_binding = recovered_binding
                        if (
                            canonical_binding.state != "connected"
                            or canonical_binding.reason_code is not None
                        ):
                            try:
                                canonical_binding = self._bindings.set_state(
                                    canonical_id,
                                    state="connected",
                                    reason_code=None,
                                )
                            except Exception:
                                return {
                                    "status": "binding_pending",
                                    "pending_grant_id": pending_grant_id,
                                    "binding_id": canonical_id,
                                }
                        try:
                            self._store.delete(pending_grant_id)
                        except Exception:
                            return {
                                "status": "canonical_pending_cleanup",
                                "pending_grant_id": pending_grant_id,
                                "binding_id": canonical_id,
                            }
                        return {
                            "status": "canonical",
                            "pending_grant_id": pending_grant_id,
                            "binding_id": canonical_id,
                        }
                    if resolution == "promotable" and canonical_id is not None:
                        return self._promote_pending_grant(
                            pending_grant_id, token, canonical_id
                        )
                    if resolution == "conflict" and canonical_id is not None:
                        # Same channel is not same credential authority. A
                        # token mismatch without exact predecessor evidence can
                        # be either an unpromoted grant or a newer rotation, so
                        # preserve both and perform no provider revocation.
                        return {
                            "status": "pending_conflict",
                            "pending_grant_id": pending_grant_id,
                            "binding_id": canonical_id,
                        }
                    if not self._compensate_grant(token):
                        return {
                            "status": "pending",
                            "pending_grant_id": pending_grant_id,
                        }
                    try:
                        self._store.delete(pending_grant_id)
                    except Exception:
                        return {
                            "status": "compensated_pending_cleanup",
                            "pending_grant_id": pending_grant_id,
                        }
                    return {
                        "status": "compensated",
                        "pending_grant_id": pending_grant_id,
                    }

    def finish_device_connection(self, connection: DeviceConnection) -> dict[str, Any]:
        """Complete one device poll, persist tokens encrypted, bind the account.

        Returns the non-secret connect receipt ``{status, account}`` -- no token
        material. Raises :class:`DeviceAuthorizationPending` if the user has not
        approved yet (the caller re-polls after ``interval``).
        """
        pending_id = _pending_grant_id(
            connection.handle.device_code,
            connection.reconnect_binding_id,
        )
        # Lock order is pending grant -> channel/reconnect identity -> binding
        # -> aggregate token file. No lifecycle path acquires these in reverse.
        with self._store.binding_lifecycle_lock(pending_id):
            if connection.reconnect_binding_id is not None:
                # Resolve an interrupted refresh before asking Google for a
                # second standing grant. Lock order remains pending grant ->
                # binding -> aggregate token file.
                with self._store.binding_lifecycle_lock(
                    connection.reconnect_binding_id
                ):
                    refresh_failure: tuple[str, str | None] | None = None
                    try:
                        self._recover_pending_refresh_authority(
                            connection.reconnect_binding_id
                        )
                    except OAuthGrantDurabilityError as error:
                        refresh_failure = (
                            error.reason_code,
                            error.pending_grant_id,
                        )
                    if refresh_failure is not None:
                        refresh_reason, refresh_pending_id = refresh_failure
                        self._degrade_refresh_authority(
                            connection.reconnect_binding_id,
                            reason_code=self._refresh_degradation_reason(
                                refresh_reason
                            ),
                            pending_grant_id=refresh_pending_id,
                        )
                        raise OAuthGrantDurabilityError(
                            refresh_reason,
                            pending_grant_id=refresh_pending_id,
                        ) from None
            # A standing grant must not be requested until the encryption key,
            # aggregate file, lock directory, and atomic replace path are ready.
            self._store.preflight_write_ready()
            bundle = self._client.poll_device_flow(connection.handle.device_code)
            pending_token = StoredToken(
                refresh_token=bundle.refresh_token or "",
                access_token=bundle.access_token,
                expires_at=_expiry_iso(bundle.expires_in),
                scopes=(SCOPE,),
                obtained_at=_now_iso(),
                provider_channel_id=None,
            )
            self._journal_issued_grant(pending_id, pending_token)

            if not bundle.refresh_token or not bundle.access_token:
                self._abort_journaled_grant(pending_id, pending_token)
            identity: ChannelIdentity | None = None
            identity_failed = False
            try:
                identity = self._identity(bundle.access_token)
            except Exception:
                identity_failed = True
            if identity_failed:
                # Identity probing is outside the OAuth transaction and may
                # fail after Google has issued a standing refresh token. Revoke
                # when authoritative; otherwise retain the encrypted journal.
                self._abort_journaled_grant(pending_id, pending_token)

            assert identity is not None
            pending_token = replace(
                pending_token, provider_channel_id=identity.channel_id
            )
            self._bind_pending_grant_identity(pending_id, pending_token)
            binding_error: Exception | None = None
            try:
                result = self._bind_from_bundle(
                    bundle,
                    connection.reconnect_binding_id,
                    identity,
                    pending_id=pending_id,
                )
            except Exception as error:
                binding_error = error
            if binding_error is not None:
                # Unknown binding/store exceptions may embed backend details.
                # When the pending journal still owns the fresh grant, surface
                # only the stable recovery id/reason and never chain text that
                # could echo credential material.
                try:
                    pending_is_durable = self._store.has_record(pending_id)
                except Exception:
                    pending_is_durable = True
                if pending_is_durable:
                    raise OAuthGrantDurabilityError(
                        "grant_pending", pending_grant_id=pending_id
                    )
                raise binding_error
            return result

    def _journal_issued_grant(self, pending_id: str, token: StoredToken) -> None:
        """Durably journal a fresh grant or compensate it at the provider."""
        first_write_error: Exception | None = None
        try:
            self._store.put(pending_id, token)
        except Exception as error:
            first_write_error = error
        if first_write_error is None:
            return

        # A store write can durably replace the aggregate and then lose its
        # acknowledgement (including a parent-directory fsync error). Exact
        # encrypted-record readback is success authority: never revoke it.
        if self._stored_token_matches(
            pending_id, token, write_error=first_write_error
        ):
            raise OAuthGrantDurabilityError(
                "grant_pending", pending_grant_id=pending_id
            )

        if self._compensate_grant(token):
            self._delete_redundant_pending(pending_id)
            raise OAuthGrantDurabilityError("grant_compensated")

        # A transient write can fail after the successful readiness probe. If
        # provider compensation is also indeterminate, retry the encrypted
        # journal before returning control so retry authority remains local.
        retry_write_error: Exception | None = None
        try:
            self._store.put(pending_id, token)
        except Exception as error:
            retry_write_error = error
        if retry_write_error is not None:
            if self._stored_token_matches(
                pending_id, token, write_error=retry_write_error
            ):
                raise OAuthGrantDurabilityError(
                    "grant_pending", pending_grant_id=pending_id
                )
            # The second write may fail for a different transient reason than
            # the first. Re-check provider authority once more before declaring
            # the physically unsatisfiable store+provider double outage.
            if self._compensate_grant(token):
                self._delete_redundant_pending(pending_id)
                raise OAuthGrantDurabilityError("grant_compensated")
            raise OAuthGrantDurabilityError("grant_durability_unavailable")
        raise OAuthGrantDurabilityError(
            "grant_pending", pending_grant_id=pending_id
        )

    def _abort_journaled_grant(self, pending_id: str, token: StoredToken) -> NoReturn:
        """Compensate a pre-binding failure or retain its pending authority."""
        if self._compensate_grant(token):
            try:
                self._store.delete(pending_id)
            except Exception:
                _log.warning(
                    "youtube oauth: compensated grant retained redundant encrypted journal"
                )
            raise OAuthGrantDurabilityError("grant_compensated")
        raise OAuthGrantDurabilityError(
            "grant_pending", pending_grant_id=pending_id
        )

    def _bind_pending_grant_identity(
        self, pending_id: str, token: StoredToken
    ) -> None:
        """Durably attach provider identity before canonical promotion.

        If a later canonical cleanup fails, recovery can still recognize the
        provider/channel relationship even after a subsequent reconnect rotates
        the refresh token. Failure leaves the earlier unannotated journal as
        durable revocation authority and stops before canonical mutation.
        """
        write_error: Exception | None = None
        try:
            self._store.put(pending_id, token)
        except Exception as error:
            write_error = error
        if write_error is None or self._stored_token_matches(
            pending_id, token, write_error=write_error
        ):
            return
        raise OAuthGrantDurabilityError(
            "grant_pending", pending_grant_id=pending_id
        )

    def _stored_token_matches(
        self,
        binding_id: str,
        expected: StoredToken,
        *,
        write_error: Exception | None = None,
    ) -> bool:
        """Exact encrypted-record readback authority for a lost write ack."""
        if isinstance(write_error, TokenStoreDurabilityError):
            # Post-replace visibility is not crash durability. Require a new,
            # successful directory barrier before accepting exact readback.
            return self._store.confirm_record_durable(binding_id, expected)
        try:
            stored = self._store.get(binding_id)
        except Exception:
            return False
        return stored == expected

    def _delete_redundant_pending(self, pending_id: str) -> None:
        try:
            self._store.delete(pending_id)
        except Exception:
            _log.warning(
                "youtube oauth: compensated grant retained redundant encrypted journal"
            )

    def _pending_resolution(
        self, pending: StoredToken, canonical_ids: set[str]
    ) -> tuple[str, str | None]:
        """Classify pending authority using exact credential/generation proof."""
        canonical_by_id: dict[str, StoredToken] = {}
        for binding_id in sorted(canonical_ids):
            canonical = self._store.get(binding_id)
            if canonical is None:
                continue
            canonical_by_id[binding_id] = canonical
            if _same_refresh_authority(pending, canonical):
                return "canonical", binding_id

        target_id = pending.promotion_target_binding_id
        if target_id is not None:
            pending_refresh = self._store.get(_pending_refresh_id(target_id))
            if pending_refresh is not None:
                # A refresh transaction that began after this pending grant is
                # separate authority even while canonical still equals the
                # older predecessor. Resolve it first; never let this retry
                # overwrite or delete the newer pending rotation.
                return "conflict", target_id
            target = canonical_by_id.get(target_id)
            if target is not None:
                predecessor_matches = (
                    pending.promotion_predecessor_refresh_token is not None
                    and pending.promotion_predecessor_generation is not None
                    and target.authority_generation
                    == pending.promotion_predecessor_generation
                    and hmac.compare_digest(
                        target.refresh_token,
                        pending.promotion_predecessor_refresh_token,
                    )
                )
                if predecessor_matches:
                    return "promotable", target_id
            elif (
                pending.promotion_predecessor_refresh_token is None
                and pending.promotion_predecessor_generation == 0
                and pending.authority_generation == 1
            ):
                # Durable evidence recorded that this target had no canonical
                # credential when promotion began. The binding-row guard in
                # ``_promote_pending_grant`` prevents resurrecting a completed
                # disconnect or inventing a never-created first-connect row.
                return "promotable", target_id

        for binding_id, canonical in canonical_by_id.items():
            if (
                pending.provider_channel_id is not None
                and canonical.provider_channel_id == pending.provider_channel_id
            ):
                return "conflict", binding_id
        return "none", None

    def _promote_pending_grant(
        self,
        pending_id: str,
        pending: StoredToken,
        binding_id: str,
    ) -> dict[str, Any]:
        """Complete a proven interrupted promotion without losing authority."""
        binding = self._bindings.get(binding_id)
        if binding is not None and (
            binding.provider_channel_id != pending.provider_channel_id
            or binding.reason_code == "auth_disconnected"
        ):
            return {
                "status": "pending_conflict",
                "pending_grant_id": pending_id,
                "binding_id": binding_id,
            }

        # When an older canonical predecessor already exists, recovering its
        # row is safe and must precede promotion of a distinct later grant. If
        # row creation is still failing, leave both encrypted authorities
        # unchanged instead of overwriting the predecessor without a row.
        if binding is None and self._store.get(binding_id) is not None:
            recovery, binding = self._recover_candidate_binding_row(
                pending, binding_id
            )
            if recovery != "recovered" or binding is None:
                return {
                    "status": recovery,
                    "pending_grant_id": pending_id,
                    "binding_id": (
                        binding.account_binding_id
                        if binding is not None
                        else binding_id
                    ),
                }

        # Canonical encrypted authority must be crash-durable before recovery
        # creates a binding row whose default state claims ``connected``. A
        # pending-only restart followed by a failed canonical write therefore
        # leaves no row to overstate authority. Lost acknowledgements still
        # roll forward through exact durable readback, and a later retry can
        # recover the deterministic row from the now-canonical ciphertext.
        canonical = _canonical_token_from_pending(pending)
        write_error: Exception | None = None
        try:
            self._store.put(binding_id, canonical)
        except Exception as error:
            write_error = error
        if write_error is not None and not self._stored_token_matches(
            binding_id, canonical, write_error=write_error
        ):
            return {
                "status": "promotion_pending",
                "pending_grant_id": pending_id,
                "binding_id": binding_id,
            }
        if binding is None:
            if (
                pending.provider_channel_id is not None
                and binding_id
                == _binding_candidate_id(pending.provider_channel_id)
            ):
                recovery, binding = self._recover_candidate_binding_row(
                    pending, binding_id
                )
                if recovery != "recovered" or binding is None:
                    return {
                        "status": recovery,
                        "pending_grant_id": pending_id,
                        "binding_id": (
                            binding.account_binding_id
                            if binding is not None
                            else binding_id
                        ),
                    }
            else:
                return {
                    "status": "pending_conflict",
                    "pending_grant_id": pending_id,
                    "binding_id": binding_id,
                }
        assert binding is not None
        if (
            binding.provider_channel_id != pending.provider_channel_id
            or binding.reason_code == "auth_disconnected"
        ):
            return {
                "status": "pending_conflict",
                "pending_grant_id": pending_id,
                "binding_id": binding_id,
            }
        try:
            if binding.state != "connected" or binding.reason_code is not None:
                self._bindings.set_state(
                    binding_id, state="connected", reason_code=None
                )
        except Exception:
            return {
                "status": "canonical_pending_state",
                "pending_grant_id": pending_id,
                "binding_id": binding_id,
            }
        try:
            self._store.delete(pending_id)
        except Exception:
            return {
                "status": "canonical_pending_cleanup",
                "pending_grant_id": pending_id,
                "binding_id": binding_id,
            }
        return {
            "status": "promoted",
            "pending_grant_id": pending_id,
            "binding_id": binding_id,
        }

    def _recover_candidate_binding_row(
        self, pending: StoredToken, binding_id: str
    ) -> tuple[str, AccountBinding | None]:
        """Retry one deterministic first-connect create without new consent.

        The caller holds pending -> channel -> candidate lifecycle authority.
        A delayed exact row converges. A different same-channel winner is
        reported as conflict and neither credential is overwritten or revoked.
        """
        channel_id = pending.provider_channel_id
        display_label = pending.promotion_display_label
        if (
            channel_id is None
            or display_label is None
            or pending.promotion_target_binding_id != binding_id
            or binding_id != _binding_candidate_id(channel_id)
        ):
            return "pending_conflict", None
        try:
            created = self._bindings.create(
                provider_channel_id=channel_id,
                display_label=display_label,
                scopes=list(pending.scopes),
                account_binding_id=binding_id,
                obtained_at=pending.obtained_at,
            )
            return "recovered", created
        except Exception:
            pass
        try:
            exact = self._bindings.get(binding_id)
        except Exception:
            exact = None
        if (
            isinstance(exact, AccountBinding)
            and exact.account_binding_id == binding_id
            and exact.provider_channel_id == channel_id
            and exact.reason_code != "auth_disconnected"
        ):
            return "recovered", exact
        try:
            winner = self._bindings.get_by_channel_id(channel_id)
        except Exception:
            winner = None
        if isinstance(winner, AccountBinding):
            return "pending_conflict", winner
        return "binding_pending", None

    def _recover_pending_refresh_authority(
        self, binding_id: str
    ) -> StoredToken | None:
        """Resolve one refresh journal before another credential lifecycle.

        The caller holds the binding lifecycle lock. A mismatched/newer
        canonical generation is never overwritten, deleted, or revoked.
        """
        pending_id = _pending_refresh_id(binding_id)
        canonical = self._store.get(binding_id)
        pending = self._store.get(pending_id)
        if pending is None:
            return canonical
        if pending.promotion_compensation_state == "compensated":
            # The provider-compensated authority is terminal. Persist that
            # fail-closed truth before removing the only crash-recovery marker;
            # a crash after cleanup must never make the binding look connected.
            self._degrade_refresh_authority(
                binding_id,
                reason_code="auth_revoked",
                pending_grant_id=pending_id,
            )
            try:
                self._store.delete(pending_id)
            except Exception:
                raise OAuthGrantDurabilityError(
                    "refresh_compensated",
                    pending_grant_id=pending_id,
                ) from None
            return canonical
        if pending.promotion_compensation_state is not None:
            raise OAuthGrantDurabilityError(
                "refresh_durability_unavailable",
                pending_grant_id=pending_id,
            ) from None
        if canonical is None or (
            pending.promotion_target_binding_id != binding_id
            or pending.promotion_predecessor_refresh_token is None
            or pending.promotion_predecessor_generation is None
        ):
            raise OAuthGrantDurabilityError(
                "refresh_conflict", pending_grant_id=pending_id
            ) from None

        if _same_refresh_authority(pending, canonical):
            cleanup_failed = False
            try:
                self._store.delete(pending_id)
            except Exception:
                cleanup_failed = True
            if cleanup_failed:
                raise OAuthGrantDurabilityError(
                    "refresh_pending", pending_grant_id=pending_id
                ) from None
            return canonical

        predecessor_matches = (
            canonical.authority_generation
            == pending.promotion_predecessor_generation
            and hmac.compare_digest(
                canonical.refresh_token,
                pending.promotion_predecessor_refresh_token,
            )
        )
        if not predecessor_matches:
            raise OAuthGrantDurabilityError(
                "refresh_conflict", pending_grant_id=pending_id
            ) from None

        promoted = _canonical_token_from_pending(pending)
        write_error: Exception | None = None
        try:
            self._store.put(binding_id, promoted)
        except Exception as error:
            write_error = error
        if write_error is not None and not self._stored_token_matches(
            binding_id, promoted, write_error=write_error
        ):
            raise OAuthGrantDurabilityError(
                "refresh_pending", pending_grant_id=pending_id
            ) from None
        cleanup_failed = False
        try:
            self._store.delete(pending_id)
        except Exception:
            cleanup_failed = True
        if cleanup_failed:
            raise OAuthGrantDurabilityError(
                "refresh_pending", pending_grant_id=pending_id
            ) from None
        return promoted

    def _compensate_grant(self, token: StoredToken) -> bool:
        """Return true only when provider revocation is authoritative."""
        revocation_token = token.refresh_token or token.access_token or ""
        if not revocation_token:
            return False
        try:
            self._client.revoke(revocation_token)
            return True
        except OAuthProviderError as error:
            return _provider_confirms_token_already_invalid(error)
        except Exception:
            return False

    def _bind_from_bundle(
        self,
        bundle: TokenBundle,
        reconnect_binding_id: str | None,
        identity: ChannelIdentity,
        *,
        pending_id: str,
    ) -> dict[str, Any]:
        assert bundle.refresh_token is not None  # checked and journaled by caller
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
            binding_id = (
                binding.account_binding_id
                if binding is not None
                else _binding_candidate_id(identity.channel_id)
            )
            lifecycle = (
                self._store.binding_lifecycle_lock(binding_id)
                if binding_id != identity_authority
                else nullcontext()
            )
            with lifecycle:
                self._recover_pending_refresh_authority(binding_id)
                predecessor = self._store.get(binding_id)
                predecessor_generation = (
                    predecessor.authority_generation
                    if predecessor is not None
                    else 0
                )
                token = replace(
                    token,
                    authority_generation=predecessor_generation + 1,
                )
                # Record the exact predecessor and target in the encrypted
                # pending journal while channel/binding authority is held.
                # Retry can now promote only over that predecessor and cannot
                # mistake a newer rotated token for the same grant merely
                # because both belong to one provider channel.
                pending_with_promotion = replace(
                    token,
                    promotion_target_binding_id=binding_id,
                    promotion_predecessor_refresh_token=(
                        predecessor.refresh_token
                        if predecessor is not None
                        else None
                    ),
                    promotion_predecessor_generation=predecessor_generation,
                    promotion_display_label=identity.channel_title,
                )
                self._bind_pending_grant_identity(
                    pending_id, pending_with_promotion
                )
                if binding is None and predecessor is not None:
                    # A prior first-connect attempt durably installed this
                    # deterministic candidate credential but its binding create
                    # is still temporally indeterminate. Never overwrite that
                    # authority with a later consent grant. The new grant keeps
                    # its own pending handle and predecessor evidence; both can
                    # converge once the matching delayed row becomes visible.
                    try:
                        delayed_binding = self._bindings.get(binding_id)
                    except Exception:
                        delayed_binding = None
                    if (
                        isinstance(delayed_binding, AccountBinding)
                        and delayed_binding.account_binding_id == binding_id
                        and delayed_binding.provider_channel_id
                        == identity.channel_id
                    ):
                        binding = delayed_binding
                    else:
                        raise OAuthGrantDurabilityError(
                            "grant_pending", pending_grant_id=pending_id
                        ) from None
                commit_error: Exception | None = None
                result: dict[str, Any] | None = None
                try:
                    result = self._commit_binding(
                        binding, binding_id, identity, token
                    )
                except Exception as error:
                    commit_error = error
                if commit_error is not None:
                    # This code intentionally runs outside the exception
                    # handler: any later sanitized durability error must not
                    # retain a hidden ``__context__`` reference to a
                    # secret-bearing backend error. Canonical ciphertext alone
                    # is not a completed reconnect: the binding row must also
                    # durably converge to connected. Preserve the per-attempt
                    # pending journal on every commit failure so retry can
                    # prove and finish both halves before cleanup.
                    raise commit_error
                assert result is not None
                # Promotion and pending cleanup remain inside channel/binding
                # lifecycle authority. A cleanup failure can leave only a
                # redundant journal, and the retry path rechecks canonical
                # authority under the same lock order before any revocation.
                try:
                    self._store.delete(pending_id)
                except Exception:
                    _log.warning(
                        "youtube oauth: connected binding retained redundant pending grant journal"
                    )
                return result

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
        token_write_error: Exception | None = None
        try:
            self._store.put(binding_id, token)
        except Exception as error:
            token_write_error = error
        if token_write_error is not None and not self._stored_token_matches(
            binding_id, token, write_error=token_write_error
        ):
            raise token_write_error
        if binding is None:
            try:
                binding = self._bindings.create(
                    provider_channel_id=identity.channel_id,
                    display_label=identity.channel_title,
                    scopes=[SCOPE],
                    account_binding_id=binding_id,
                )
            except Exception as create_error:
                # A Postgres INSERT can commit after the client observes an
                # exception, and negative snapshots cannot prove a delayed
                # commit will not appear. Reconcile visible success/concurrent
                # winners, but never compensate the only encrypted revocation
                # authority while completion remains indeterminate.
                try:
                    exact_binding = self._bindings.get(binding_id)
                except Exception:
                    exact_binding = None
                try:
                    channel_binding = self._bindings.get_by_channel_id(identity.channel_id)
                except Exception:
                    channel_binding = None

                committed_binding = (
                    exact_binding
                    if isinstance(exact_binding, AccountBinding)
                    and exact_binding.account_binding_id == binding_id
                    and exact_binding.provider_channel_id == identity.channel_id
                    else None
                )
                if committed_binding is not None:
                    # Lost acknowledgement after commit: roll forward to the
                    # already-connected row and return the normal idempotent
                    # connect receipt.
                    binding = committed_binding
                elif (
                    isinstance(channel_binding, AccountBinding)
                    and channel_binding.provider_channel_id == identity.channel_id
                ):
                    # The provider/channel uniqueness constraint makes a
                    # different visible row the canonical concurrent winner.
                    # A same-channel row is not proof that its credential is
                    # this grant. Never overwrite a different/newer generation;
                    # retain the deterministic candidate and per-attempt journal
                    # for explicit reconciliation instead.
                    canonical_id = channel_binding.account_binding_id
                    canonical_lifecycle = (
                        self._store.binding_lifecycle_lock(canonical_id)
                        if canonical_id != binding_id
                        else nullcontext()
                    )
                    with canonical_lifecycle:
                        canonical = self._store.get(canonical_id)
                        if canonical is None or not _same_refresh_authority(
                            canonical, token
                        ):
                            raise create_error from None
                        if canonical_id != binding_id:
                            self._store.delete(binding_id)
                        binding = channel_binding
                else:
                    # Even two successful negative reads are only snapshots: a
                    # delayed commit can appear afterward. Preserve the grant
                    # under the deterministic candidate id; a later retry will
                    # resolve the row and converge without minting another id.
                    raise create_error from None
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
        try:
            token = self._store.get(binding_id)
            pending_refresh = self._store.get(_pending_refresh_id(binding_id))
        except TokenStoreKeyMissingError:
            token = None
            pending_refresh = None
            state, reason_code = "degraded", "auth_key_missing"
        if pending_refresh is not None:
            # A provider response may have rotated the standing credential
            # while canonical promotion is incomplete. The old canonical row
            # is not sufficient authority for a connected status.
            if pending_refresh.promotion_compensation_state == "compensated":
                state, reason_code = "degraded", "auth_revoked"
            elif pending_refresh.promotion_compensation_state is not None:
                state, reason_code = "degraded", "auth_refresh_durability"
            else:
                state, reason_code = "degraded", "auth_refresh_pending"
        if token is None and state == "connected":
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

        Only Google's documented HTTP 400 ``invalid_token`` outcome (already
        expired or revoked) authorizes destructive local teardown after a
        failed revoke. Every other status/body combination leaves the encrypted
        token and connected source state intact for retry. Successful revocation
        or that provider-authoritative outcome deletes the token record,
        disables dependent sources with ``auth_disconnected``, and deletes no
        acquired artifacts. The whole transition is
        binding-serialized with connect/reconnect/refresh across service
        instances and processes.
        """
        with self._store.binding_lifecycle_lock(binding_id):
            binding = self._bindings.get(binding_id)
            if binding is None:
                raise KeyError(f"no such account binding: {binding_id}")

            revoked = False
            try:
                token = self._recover_pending_refresh_authority(binding_id)
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
            except OAuthGrantDurabilityError as error:
                # Never revoke an older canonical credential while a rotated
                # refresh response remains pending or conflicts with a proven
                # newer generation.
                reason_code = self._refresh_degradation_reason(error.reason_code)
                self._degrade_refresh_authority(
                    binding_id,
                    reason_code=reason_code,
                    pending_grant_id=error.pending_grant_id,
                )
                return redact(
                    {
                        "status": "disconnect_failed",
                        "reason_code": reason_code,
                        "revoked": False,
                        "retryable": True,
                        "sources_disabled": 0,
                    }
                )
            if token is not None:
                # Persist local non-consumability before crossing the provider
                # revocation boundary. If the process dies after Google accepts
                # the revoke, restart truth remains fail-closed while the
                # encrypted record is retained solely as retry authority.
                self._degrade_refresh_authority(
                    binding_id,
                    reason_code="auth_disconnected",
                    pending_grant_id=None,
                )
                revocation_token = token.refresh_token or token.access_token or ""
                if revocation_token:
                    try:
                        self._client.revoke(revocation_token)
                        revoked = True
                    except OAuthProviderError as error:
                        if _provider_confirms_token_already_invalid(error):
                            _log.warning(
                                "youtube oauth: provider confirms token already invalid; "
                                "continuing local disconnect (binding %s)",
                                binding_id,
                            )
                        else:
                            _log.warning(
                                "youtube oauth: indeterminate provider revoke failure; "
                                "encrypted token preserved (binding %s)",
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
    "InvalidLoopbackRedirectURIError",
    "LoopbackFlow",
    "OAuthClient",
    "OAuthClientCredentialsMissingError",
    "OAuthGrantDurabilityError",
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
