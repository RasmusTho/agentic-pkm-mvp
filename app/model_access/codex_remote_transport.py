"""Product-side, single-attempt client for the private Mac completion API."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.model_access.remote_contract import CompletionRequest, CompletionResponse


MAX_REMOTE_RESPONSE_BYTES = 600_000
MAX_REMOTE_REQUEST_BYTES = 256_000


class RemoteCompletionError(RuntimeError):
    """Sanitized remote failure; indeterminate means execution may have started."""

    def __init__(self, code: str, *, indeterminate: bool = False) -> None:
        self.code = code
        self.indeterminate = indeterminate
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


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


class CodexRemoteTransport:
    """Post one exact route to Serve HTTPS; never retry or select a fallback."""

    def __init__(
        self,
        *,
        endpoint: str,
        timeout_seconds: float = 1_260.0,
        max_request_bytes: int = MAX_REMOTE_REQUEST_BYTES,
        max_response_bytes: int = MAX_REMOTE_RESPONSE_BYTES,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or max_request_bytes <= 0 or max_response_bytes <= 0:
            raise ValueError("remote transport bounds must be positive")
        self._url = _validate_private_https_endpoint(endpoint)
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        # HTTPX verifies TLS certificates by default; spell this out for the production
        # transport, disable environment proxies, and disable transport-level retries.
        client_transport = transport or httpx.HTTPTransport(verify=True, retries=0)
        self._client = httpx.Client(
            transport=client_transport,
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            follow_redirects=False,
            trust_env=False,
        )

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


__all__ = [
    "CodexRemoteTransport",
    "MAX_REMOTE_REQUEST_BYTES",
    "MAX_REMOTE_RESPONSE_BYTES",
    "RemoteCompletionError",
]
