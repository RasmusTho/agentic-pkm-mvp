"""Regression coverage for empty-message httpx transport failures (#3386)."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from companion_ui.workspace.entry_state import resolve_entry_state
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientNetworkError,
    WorkspaceHttpClient,
)


@pytest.mark.parametrize("exception_type", (httpx.ReadTimeout, httpx.ConnectTimeout))
def test_empty_message_timeout_classifies_unreachable(
    exception_type: type[httpx.TimeoutException],
) -> None:
    """A silent httpx timeout reaches the designed unreachable entry state."""
    with patch("httpx.get", side_effect=exception_type("")):
        client = WorkspaceHttpClient(base_url="http://localhost:18001")
        with pytest.raises(WorkspaceClientNetworkError) as exc_info:
            client.get("/api/companion/workspace", params={})

    assert str(exc_info.value)
    resolution = resolve_entry_state(error=str(exc_info.value))
    assert resolution.state == "no_vault"
