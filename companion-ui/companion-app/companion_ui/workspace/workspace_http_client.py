"""Live HTTP client for workspace confirm/session APIs (#1071).

Concrete adapter implementing the HttpClient protocol consumed by
WorkspaceConfirmSession. Uses httpx to call:
  GET  /api/companion/workspace
  POST /api/canvas/sessions
  POST /api/canvas/sessions/{id}/coauthor
  POST /api/panel/confirm
  DELETE /api/canvas/sessions/{id}/edits/last
  DELETE /api/canvas/sessions/{id}

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

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST request to the runtime API. Raises WorkspaceClientError on failure."""
        full_url = self._base_url + url
        try:
            request_kwargs: dict[str, Any] = {"json": json, "timeout": self._timeout}
            if headers is not None:
                request_kwargs["headers"] = headers
            resp = httpx.post(full_url, **request_kwargs)
        except httpx.RequestError as exc:
            raise WorkspaceClientNetworkError(str(exc)) from exc
        if resp.status_code >= 400:
            raise WorkspaceClientHTTPError(resp.status_code, resp.text)
        return resp.json()

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """DELETE request to the runtime API. Raises WorkspaceClientError on failure."""
        full_url = self._base_url + url
        try:
            resp = httpx.delete(full_url, params=params, timeout=self._timeout)
        except httpx.RequestError as exc:
            raise WorkspaceClientNetworkError(str(exc)) from exc
        if resp.status_code >= 400:
            raise WorkspaceClientHTTPError(resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------
    # Canvas co-authoring (#1717)
    # ------------------------------------------------------------------

    def coauthor(
        self,
        session_id: str,
        intent: str,
        change_summary: str | None = None,
    ) -> dict[str, Any]:
        """Request a server-generated co-authoring edit for ``session_id``.

        Posts the user's intent to ``POST /api/canvas/sessions/{id}/coauthor``.
        The server generates and applies the new body, then returns the
        applied body and its change summary. The client composes no body
        itself; it only forwards the intent.

        Raises WorkspaceClientHTTPError on a non-2xx response. A 409 signals a
        governance-bearing mutation that the server routed to the Panel rather
        than applying in place; the caller renders it as routed-to-Panel.
        """
        payload: dict[str, Any] = {"intent": intent}
        if change_summary is not None:
            payload["change_summary"] = change_summary
        return self.post(
            f"/api/canvas/sessions/{session_id}/coauthor",
            json=payload,
        )

    def undo_last_edit(self, session_id: str) -> dict[str, Any]:
        """Undo the last co-authoring body edit for ``session_id``.

        Calls ``DELETE /api/canvas/sessions/{id}/edits/last``. The server
        restores the prior body; the client performs no vault write itself.
        """
        return self.delete(f"/api/canvas/sessions/{session_id}/edits/last")
