"""Live HTTP client for workspace confirm/session APIs (#1071).

Concrete adapter implementing the HttpClient protocol consumed by
WorkspaceConfirmSession. Uses httpx to call:
  GET  /api/companion/workspace
  POST /api/panel/confirm

The base URL is configurable so the same client works against dev,
test, or prod runtime instances. The runtime environment determines
which vault is bound — the client does not know or choose it.

Environment contract:
  - dev runtime → dev-bound vault (e.g. Nifelheim)
  - test runtime → test-bound vault (e.g. Bifröst)
  - prod runtime → prod-bound vault (e.g. Midgård)
  Named vaults above are examples of environment binding only;
  they must not be hardcoded in UI logic.

This module does NOT:
- read or write vault files directly
- choose or configure the active vault
- make decisions based on vault names or environment names
"""

from __future__ import annotations

from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Typed client errors
# ---------------------------------------------------------------------------


class WorkspaceClientError(Exception):
    """Base error for workspace HTTP client failures."""


class WorkspaceClientHTTPError(WorkspaceClientError):
    """HTTP error (4xx/5xx) returned by the runtime API."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class WorkspaceClientNetworkError(WorkspaceClientError):
    """Network-level failure (connection refused, timeout, DNS, etc.)."""


# ---------------------------------------------------------------------------
# Live HTTP client
# ---------------------------------------------------------------------------


class WorkspaceHttpClient:
    """Live HTTP client for workspace confirm/session APIs.

    Pass a different base_url to target dev, test, or prod runtime.
    Vault binding is entirely owned by the runtime; the client only
    holds a configured API target.

    Example:
        # dev runtime (binds dev vault, e.g. Nifelheim)
        client = WorkspaceHttpClient("http://localhost:18001")

        # test runtime (binds test vault, e.g. Bifröst)
        client = WorkspaceHttpClient("http://localhost:18002")
    """

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        """GET request to the runtime API. Raises WorkspaceClientError on failure."""
        full_url = self._base_url + url
        try:
            resp = httpx.get(full_url, params=params, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise WorkspaceClientNetworkError(str(exc)) from exc
        if resp.status_code >= 400:
            raise WorkspaceClientHTTPError(resp.status_code, resp.text)
        return resp.json()

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        """POST request to the runtime API. Raises WorkspaceClientError on failure."""
        full_url = self._base_url + url
        try:
            resp = httpx.post(full_url, json=json, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise WorkspaceClientNetworkError(str(exc)) from exc
        if resp.status_code >= 400:
            raise WorkspaceClientHTTPError(resp.status_code, resp.text)
        return resp.json()
