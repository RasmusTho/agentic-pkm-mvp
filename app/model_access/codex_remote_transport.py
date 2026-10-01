"""Product-side, single-attempt client for the private Mac completion API."""

from __future__ import annotations

import ipaddress
import json
import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.model_access.remote_contract import (
    CatalogRequest,
    CatalogResponse,
    CompletionRequest,
    CompletionResponse,
    PreflightRequest,
    PreflightResponse,
)


MAX_REMOTE_RESPONSE_BYTES = 600_000
MAX_REMOTE_REQUEST_BYTES = 256_000
MAX_PREFLIGHT_RESPONSE_BYTES = 16_000
MAX_CATALOG_REQUEST_BYTES = 4_096
MAX_CATALOG_RESPONSE_BYTES = 2_100_000
_PRIVATE_INGRESS_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_PREFLIGHT_ERROR_CODES = frozenset(
    {
        "serve_capability_required",
        "serve_capability_invalid",
        "loopback_only",
        "invalid_json",
        "request_too_large",
        "content_length_required",
        "invalid_request",
        "route_not_declared",
        "native_tools_unavailable",
        "output_token_limit_unavailable",
        "structured_output_unavailable",
        "trusted_instruction_mapping_unavailable",
        "literal_system_role_unavailable",
        "executor_busy",
        "cli_missing",
        "command_timeout",
        "input_oversize",
        "stdout_oversize",
        "model_unavailable",
        "schema_violation",
        "unsupported_profile",
        "session_expired",
        "authentication_unavailable",
        "cli_version_unsupported",
        "tool_surface_unknown",
        "credential_unavailable",
        "ollama_unavailable",
        "ollama_timeout",
        "ollama_model_unavailable",
        "ollama_model_capabilities_unavailable",
        "ollama_completion_unavailable",
        "ollama_response_invalid",
        "ollama_response_too_large",
        "catalog_unavailable",
        "catalog_stale",
        "catalog_invalid",
        "catalog_auth_failed",
        "catalog_response_too_large",
        "PATH_UNAVAILABLE",
        "CONNECT_TIMEOUT",
        "PREFLIGHT_TIMEOUT",
        "PATH_AUTHENTICATION_FAILED",
    }
)


class RemoteCompletionError(RuntimeError):
    """Sanitized remote failure; indeterminate means execution may have started."""

    def __init__(self, code: str, *, indeterminate: bool = False) -> None:
        self.code = code
        self.indeterminate = indeterminate
        super().__init__(code)


class RemotePreflightError(RuntimeError):
    """Sanitized failure from the dedicated endpoint that never runs inference."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RemoteCatalogError(RuntimeError):
    """Sanitized failure from the read-only, authenticated catalog operation."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _validate_private_https_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or host is None
            or not host.lower().endswith(".ts.net")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
        ):
            raise ValueError("unsupported executor endpoint")
        # A literal IP cannot be a verified Serve DNS identity.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("executor endpoint must use its Serve DNS name")
    except (TypeError, ValueError) as exc:
        raise ValueError("executor endpoint must be a private Tailscale HTTPS origin") from exc
    return f"https://{host.lower()}/v1/complete"


def _validate_private_ingress_endpoint(endpoint: str) -> str:
    """Validate an HTTPS origin supplied by host-local VLAN configuration."""
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or host is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or host.lower().endswith(".ts.net")
        ):
            raise ValueError("unsupported private ingress endpoint")
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("unsupported private ingress port")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError(
                "private ingress endpoint must use a private-network IP literal"
            ) from exc
        if not any(address in network for network in _PRIVATE_INGRESS_NETWORKS):
            raise ValueError(
                "private ingress endpoint must use a private-network IP literal"
            )
    except (TypeError, ValueError) as exc:
        raise ValueError("endpoint must be a host-local private HTTPS origin") from exc
    host_authority = f"[{host.lower()}]" if ":" in host else host.lower()
    authority = host_authority if port is None else f"{host_authority}:{port}"
    return f"https://{authority}/v1/complete"


def _contains_ssl_error(error: BaseException) -> bool:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        for nested in (
            current.__cause__,
            current.__context__,
            getattr(current, "reason", None),
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _private_ingress_ssl_context(
    *, ca_bundle_path: str, client_certificate: tuple[str, str]
) -> ssl.SSLContext:
    """Build explicit mTLS state independently of HTTPX's legacy `cert` option."""
    try:
        context = ssl.create_default_context(cafile=ca_bundle_path)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        context.load_cert_chain(
            certfile=client_certificate[0], keyfile=client_certificate[1]
        )
    except (OSError, ssl.SSLError, TypeError, ValueError):
        raise ValueError("private ingress TLS configuration is invalid") from None
    return context


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _read_bounded_response_body(
    response: httpx.Response, *, max_bytes: int
) -> bytearray | None:
    """Read a fully bounded response body, returning None when it is oversized."""
    body = bytearray()
    for chunk in response.iter_bytes():
        if len(body) + len(chunk) > max_bytes:
            return None
        body.extend(chunk)
    return body


def _known_http_error(status_code: int | None, *, operation: str) -> str | None:
    if status_code is None or status_code == 200:
        return None
    return f"{operation}_http_{status_code}"


class CodexRemoteTransport:
    """Post one exact route to one configured HTTPS path; never retry it."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float = 1_260.0,
        max_request_bytes: int = MAX_REMOTE_REQUEST_BYTES,
        max_response_bytes: int = MAX_REMOTE_RESPONSE_BYTES,
        path_adapter: str = "tailscale_serve_https",
        tls_verify: bool | str = True,
        client_certificate: tuple[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_request_bytes <= 0 or max_response_bytes <= 0:
            raise ValueError("remote transport bounds must be positive")
        if path_adapter == "tailscale_serve_https":
            self._url = _validate_private_https_endpoint(endpoint)
            if tls_verify is not True or client_certificate is not None:
                raise ValueError("Tailscale Serve path must use system TLS trust")
            transport_verify: bool | ssl.SSLContext = True
        elif path_adapter == "private_https_ingress":
            self._url = _validate_private_ingress_endpoint(endpoint)
            if not isinstance(tls_verify, str) or not tls_verify or client_certificate is None:
                raise ValueError("private ingress path requires verified mutual TLS")
            transport_verify = _private_ingress_ssl_context(
                ca_bundle_path=tls_verify,
                client_certificate=client_certificate,
            )
        else:
            raise ValueError("unsupported executor path adapter")
        self._preflight_url = self._url.removesuffix("/v1/complete") + "/v1/preflight"
        self._catalog_url = self._url.removesuffix("/v1/complete") + "/v1/catalog"
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        # HTTPX verifies TLS certificates by default; spell this out for the production
        # transport, disable environment proxies, and disable transport-level retries.
        client_transport = transport or httpx.HTTPTransport(
            verify=transport_verify,
            retries=0,
        )
        self._client = httpx.Client(
            transport=client_transport,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            follow_redirects=False,
            trust_env=False,
        )

    def catalog(self, request: CatalogRequest) -> CatalogResponse:
        """Fetch a transport catalog without invoking a model."""
        try:
            request_body = json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise RemoteCatalogError("catalog_request_invalid") from None
        if len(request_body) > MAX_CATALOG_REQUEST_BYTES:
            raise RemoteCatalogError("catalog_request_too_large")

        body = bytearray()
        response_status: int | None = None
        try:
            with self._client.stream(
                "POST",
                self._catalog_url,
                content=request_body,
                headers={"Content-Type": "application/json"},
            ) as response:
                response_status = response.status_code
                try:
                    response_body = _read_bounded_response_body(
                        response, max_bytes=MAX_CATALOG_RESPONSE_BYTES
                    )
                except Exception:
                    status_error = _known_http_error(
                        response_status, operation="catalog"
                    )
                    if status_error is not None:
                        raise RemoteCatalogError(status_error) from None
                    raise
                if response_body is None:
                    status_error = _known_http_error(
                        response_status, operation="catalog"
                    )
                    if status_error is not None:
                        raise RemoteCatalogError(status_error)
                    raise RemoteCatalogError("catalog_response_too_large")
                body = response_body
                if response.status_code != 200:
                    raise RemoteCatalogError(_catalog_error_code(response.status_code, bytes(body)))
        except RemoteCatalogError:
            raise
        except httpx.ConnectTimeout:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            raise RemoteCatalogError("CONNECT_TIMEOUT") from None
        except httpx.ReadTimeout:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            raise RemoteCatalogError("PREFLIGHT_TIMEOUT") from None
        except httpx.TimeoutException:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            raise RemoteCatalogError("PREFLIGHT_TIMEOUT") from None
        except httpx.ConnectError as exc:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            if _contains_ssl_error(exc):
                raise RemoteCatalogError("PATH_AUTHENTICATION_FAILED") from None
            raise RemoteCatalogError("PATH_UNAVAILABLE") from None
        except httpx.TransportError as exc:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            if _contains_ssl_error(exc):
                raise RemoteCatalogError("PATH_AUTHENTICATION_FAILED") from None
            raise RemoteCatalogError("PATH_UNAVAILABLE") from None
        except Exception:
            status_error = _known_http_error(response_status, operation="catalog")
            if status_error is not None:
                raise RemoteCatalogError(status_error) from None
            # Only recognized network failures permit stale-cache service. Any
            # unexpected adapter failure is terminal for this catalog refresh.
            raise RemoteCatalogError("catalog_invalid") from None

        try:
            result = CatalogResponse.model_validate_json(bytes(body))
        except Exception:
            raise RemoteCatalogError("catalog_response_invalid") from None
        if result.snapshot.transport_id != request.transport_id:
            raise RemoteCatalogError("catalog_transport_mismatch")
        return result

    def preflight(self, request: PreflightRequest) -> PreflightResponse:
        """Check one exact remote route through the no-inference operation."""
        try:
            request_body = json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise RemotePreflightError("preflight_request_invalid") from None
        if len(request_body) > self._max_request_bytes:
            raise RemotePreflightError("preflight_request_too_large")

        body = bytearray()
        response_status: int | None = None
        try:
            with self._client.stream(
                "POST",
                self._preflight_url,
                content=request_body,
                headers={"Content-Type": "application/json"},
            ) as response:
                response_status = response.status_code
                try:
                    response_body = _read_bounded_response_body(
                        response, max_bytes=MAX_PREFLIGHT_RESPONSE_BYTES
                    )
                except Exception:
                    status_error = _known_http_error(
                        response_status, operation="preflight"
                    )
                    if status_error is not None:
                        raise RemotePreflightError(status_error) from None
                    raise
                if response_body is None:
                    status_error = _known_http_error(
                        response_status, operation="preflight"
                    )
                    if status_error is not None:
                        raise RemotePreflightError(status_error)
                    raise RemotePreflightError("preflight_response_too_large")
                body = response_body
                if response.status_code != 200:
                    raise RemotePreflightError(
                        _preflight_error_code(response.status_code, bytes(body))
                    )
        except RemotePreflightError:
            raise
        except httpx.ConnectTimeout:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            raise RemotePreflightError("CONNECT_TIMEOUT") from None
        except httpx.ReadTimeout:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            # Preflight never invokes inference, so a lost preflight response is
            # safe to retry through another configured network path.
            raise RemotePreflightError("PREFLIGHT_TIMEOUT") from None
        except httpx.TimeoutException:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            raise RemotePreflightError("PREFLIGHT_TIMEOUT") from None
        except httpx.ConnectError as exc:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            if _contains_ssl_error(exc):
                raise RemotePreflightError("PATH_AUTHENTICATION_FAILED") from None
            raise RemotePreflightError("PATH_UNAVAILABLE") from None
        except httpx.TransportError as exc:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            if _contains_ssl_error(exc):
                raise RemotePreflightError("PATH_AUTHENTICATION_FAILED") from None
            raise RemotePreflightError("PATH_UNAVAILABLE") from None
        except Exception:
            status_error = _known_http_error(response_status, operation="preflight")
            if status_error is not None:
                raise RemotePreflightError(status_error) from None
            raise RemotePreflightError("preflight_unavailable") from None

        try:
            value = json.loads(
                bytes(body).decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_object_pairs,
                parse_constant=_reject_json_constant,
            )
            result = PreflightResponse.model_validate(value)
        except Exception:
            raise RemotePreflightError("preflight_response_invalid") from None
        if result.route != request.route:
            raise RemotePreflightError("preflight_route_mismatch")
        return result

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        try:
            request_body = json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise RemoteCompletionError("request_invalid") from None
        if len(request_body) > self._max_request_bytes:
            raise RemoteCompletionError("request_too_large")
        body = bytearray()
        try:
            with self._client.stream(
                "POST",
                self._url,
                content=request_body,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    # An HTTP 422 can report output-schema validation after inference.
                    # Without a trusted dispatch-phase receipt, classify every non-200
                    # conservatively and never let it authorize a retry or provider switch.
                    raise RemoteCompletionError(
                        f"executor_http_{response.status_code}", indeterminate=True
                    )
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > self._max_response_bytes:
                        raise RemoteCompletionError("executor_response_too_large", indeterminate=True)
                    body.extend(chunk)
        except RemoteCompletionError:
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            raise RemoteCompletionError("execution_indeterminate", indeterminate=True) from None
        except Exception:
            # Once the request enters the HTTP transport, conservatively assume it may
            # have reached the executor. No second attempt is safe.
            raise RemoteCompletionError("execution_indeterminate", indeterminate=True) from None

        try:
            value = json.loads(
                bytes(body).decode("utf-8", errors="strict"),
                object_pairs_hook=_strict_object_pairs,
                parse_constant=_reject_json_constant,
            )
            result = CompletionResponse.model_validate(value)
        except Exception:
            raise RemoteCompletionError("executor_response_invalid", indeterminate=True) from None

        if result.route != request.route:
            raise RemoteCompletionError("executor_route_mismatch", indeterminate=True)
        try:
            content_bytes = result.content.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise RemoteCompletionError(
                "executor_response_invalid", indeterminate=True
            ) from None
        if not content_bytes or len(content_bytes) > self._max_response_bytes:
            raise RemoteCompletionError("executor_response_invalid", indeterminate=True)
        return result

    def close(self) -> None:
        self._client.close()


def _preflight_error_code(status_code: int, body: bytes) -> str:
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_json_constant,
        )
        code = value.get("error", {}).get("code") if isinstance(value, dict) else None
    except Exception:
        code = None
    if isinstance(code, str) and code in _PREFLIGHT_ERROR_CODES:
        return code
    return f"preflight_http_{status_code}"


def _catalog_error_code(status_code: int, body: bytes) -> str:
    try:
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object_pairs,
            parse_constant=_reject_json_constant,
        )
        code = value.get("error", {}).get("code") if isinstance(value, dict) else None
    except Exception:
        code = None
    if isinstance(code, str) and code in _PREFLIGHT_ERROR_CODES:
        return code
    return f"catalog_http_{status_code}"


__all__ = [
    "CodexRemoteTransport",
    "MAX_REMOTE_REQUEST_BYTES",
    "MAX_REMOTE_RESPONSE_BYTES",
    "MAX_PREFLIGHT_RESPONSE_BYTES",
    "MAX_CATALOG_REQUEST_BYTES",
    "MAX_CATALOG_RESPONSE_BYTES",
    "RemoteCompletionError",
    "RemoteCatalogError",
    "RemotePreflightError",
]
