"""Deterministic contracts for the opt-in native Companion UI smoke."""

from __future__ import annotations

from typing import Any

import pytest

from tests.companion_ui.live_smoke_contract import (
    parse_finite_timeout_ms,
    wait_for_real_required_health,
)


class _Response:
    def __init__(self, payload: Any, *, ok: bool = True, status: int = 200) -> None:
        self._payload = payload
        self.ok = ok
        self.status = status

    def json(self) -> Any:
        return self._payload


class _Request:
    def __init__(self, responses: list[_Response], *, repeat_last: bool = False) -> None:
        self._responses = iter(responses)
        self._last_response = responses[-1]
        self._repeat_last = repeat_last
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str, *, timeout: int) -> _Response:
        self.calls.append((url, timeout))
        try:
            return next(self._responses)
        except StopIteration:
            if self._repeat_last:
                return self._last_response
            raise


def test_smoke_waits_for_real_required_health_within_budget() -> None:
    """A cold observation is retried until the gateway returns real health."""
    request = _Request([_Response({"ok": False}), _Response({"ok": True})])
    elapsed = 0.0

    def clock() -> float:
        return elapsed

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    payload = wait_for_real_required_health(
        request,
        "http://gateway/api/operator/health",
        timeout_ms=2_000,
        allow_embedding_rebuild_required=False,
        poll_interval_ms=100,
        clock=clock,
        sleeper=sleep,
    )

    assert payload == {"ok": True}
    assert len(request.calls) == 2
    assert request.calls == [
        ("http://gateway/api/operator/health", 2_000),
        ("http://gateway/api/operator/health", 2_000),
    ]


@pytest.mark.parametrize(
    "response",
    (_Response({"ok": False}), _Response({}, ok=False, status=503)),
)
def test_smoke_rejects_persistent_unknown_or_unavailable_within_budget(
    response: _Response,
) -> None:
    """Persistent non-healthy observations fail at the finite deadline."""
    request = _Request([response], repeat_last=True)
    elapsed = 0.0

    def clock() -> float:
        return elapsed

    def sleep(seconds: float) -> None:
        nonlocal elapsed
        elapsed += seconds

    with pytest.raises(AssertionError):
        wait_for_real_required_health(
            request,
            "http://gateway/api/operator/health",
            timeout_ms=250,
            allow_embedding_rebuild_required=False,
            poll_interval_ms=100,
            clock=clock,
            sleeper=sleep,
        )
    assert elapsed == 0.25


def test_smoke_navigation_uses_configured_finite_budget() -> None:
    """Native smoke defaults to the established finite 60-second budget."""
    assert parse_finite_timeout_ms(None) == 60_000
    assert parse_finite_timeout_ms("60000") == 60_000

    for invalid in ("0", "-1", "60001", "inf", "unbounded"):
        with pytest.raises(ValueError):
            parse_finite_timeout_ms(invalid, name="navigation timeout")
