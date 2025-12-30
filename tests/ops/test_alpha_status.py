from __future__ import annotations

from typing import Tuple

import pytest

from scripts.alpha_status import render_status

FetchResult = Tuple[int | None, dict | None, str | None]


@pytest.mark.not_pg
def test_alpha_status_handles_non_json_status() -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> FetchResult:
        calls.append(url)
        if url.endswith("/api/status"):
            return 200, None, "not json"
        if url.endswith("/api/health"):
            return 200, {"state": "running", "writes_allowed": True}, None
        return None, None, "missing"

    output = render_status(fake_fetch, api_base_url="http://localhost:18000")
    assert "Alpha status" in output
    assert "- api: OK (200)" in output
    assert "- health: mode=running writes_allowed=True" in output
    assert "- stores:" in output
    assert "- watcher:" in output
    assert calls == [
        "http://localhost:18000/api/status",
        "http://localhost:18000/api/health",
    ]


@pytest.mark.not_pg
def test_alpha_status_handles_fetch_error() -> None:
    def fake_fetch(url: str) -> FetchResult:
        return None, None, "unreachable"

    output = render_status(fake_fetch, api_base_url="http://localhost:18000")
    assert "Alpha status" in output
    assert "- api: ERROR (unreachable)" in output
    assert "- health: ERROR (unreachable)" in output
    assert "- stores:" in output
    assert "- watcher:" in output
