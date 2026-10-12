from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any


_MAX_SMOKE_TIMEOUT_MS = 60_000
_HEALTH_READINESS_DEADLINE_ERROR = (
    "operator health readiness budget expired before a valid observation"
)


def parse_finite_timeout_ms(
    raw_value: str | None,
    *,
    default: int = _MAX_SMOKE_TIMEOUT_MS,
    maximum: int = _MAX_SMOKE_TIMEOUT_MS,
    name: str = "timeout",
) -> int:
    """Parse a positive, bounded millisecond timeout for native smoke work."""
    if raw_value is None or not raw_value.strip():
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{name} must be a finite integer in milliseconds") from exc
    if value <= 0 or value > maximum:
        raise ValueError(
            f"{name} must be between 1 and {maximum} milliseconds"
        )
    return value


def wait_for_real_required_health(
    request: Any,
    url: str,
    *,
    timeout_ms: int,
    allow_embedding_rebuild_required: bool,
    poll_interval_ms: int = 500,
    clock: Any = time.monotonic,
    sleeper: Any = time.sleep,
) -> Mapping[str, Any]:
    """Wait for an actual healthy operator observation within a finite budget.

    Each request is read-only and is accepted only through the existing health
    contract. Unknown, stale, unavailable, or malformed observations therefore
    remain failures until a real healthy response arrives or the deadline is
    reached; each request and response must complete before that deadline, and
    no synthetic freshness or healthy state is introduced.
    """
    timeout_ms = parse_finite_timeout_ms(
        str(timeout_ms), name="health readiness timeout"
    )
    poll_interval_ms = parse_finite_timeout_ms(
        str(poll_interval_ms), name="health poll interval"
    )
    deadline = clock() + timeout_ms / 1000
    last_failure: AssertionError | None = None
    while True:
        remaining = deadline - clock()
        remaining_ms = int(remaining * 1000)
        if remaining_ms <= 0:
            if last_failure is None:
                raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR)
            raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR) from last_failure

        try:
            response = request.get(url, timeout=min(remaining_ms, 10_000))
            if clock() >= deadline:
                if last_failure is None:
                    raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR)
                raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR) from last_failure
            if not response.ok:
                raise AssertionError(f"health proxy HTTP {response.status}")
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise AssertionError("operator health response must be an object")
            assert_operator_health(
                payload,
                allow_embedding_rebuild_required=allow_embedding_rebuild_required,
            )
            if clock() >= deadline:
                if last_failure is None:
                    raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR)
                raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR) from last_failure
            return payload
        except AssertionError as exc:
            if str(exc) == _HEALTH_READINESS_DEADLINE_ERROR:
                raise
            last_failure = exc

        remaining = deadline - clock()
        if remaining <= 0:
            raise AssertionError(_HEALTH_READINESS_DEADLINE_ERROR) from last_failure
        sleeper(min(poll_interval_ms / 1000, remaining))


def assert_operator_channel(
    payload: Mapping[str, Any],
    *,
    expected_channel: str,
) -> None:
    """Validate release-channel identity independently of active-vault state."""

    raw_environment = payload.get("environment")
    assert isinstance(raw_environment, str) and raw_environment.strip(), (
        "operator health environment missing"
    )
    actual_channel = raw_environment.strip().lower()
    normalized_expected = expected_channel.strip().lower()
    assert actual_channel == normalized_expected, (
        f"operator health environment {actual_channel!r} did not match "
        f"expected channel {normalized_expected!r}"
    )


def assert_gateway_identity(
    *,
    actual_channel: str,
    actual_git_sha: str,
    expected_channel: str,
    expected_git_sha: str,
) -> None:
    """Validate gateway-owned identity independently of proxied API state."""

    normalized_channel = actual_channel.strip().lower()
    normalized_expected_channel = expected_channel.strip().lower()
    assert normalized_channel == normalized_expected_channel, (
        f"gateway runtime channel {normalized_channel!r} did not match "
        f"expected channel {normalized_expected_channel!r}"
    )

    normalized_sha = actual_git_sha.strip().lower()
    normalized_expected_sha = expected_git_sha.strip().lower()
    assert normalized_sha == normalized_expected_sha, (
        f"gateway git SHA {normalized_sha!r} did not match "
        f"deployed SHA {normalized_expected_sha!r}"
    )


def assert_operator_health(
    payload: Mapping[str, Any],
    *,
    allow_embedding_rebuild_required: bool,
) -> None:
    """Validate live operator health, with one explicit cutover transition."""

    if payload.get("ok") is True:
        return

    assert allow_embedding_rebuild_required, f"operator health not ok: {payload!r}"
    assert payload.get("required_ok") is False, (
        "embedding cutover allowance requires required_ok=false"
    )
    checks = payload.get("checks")
    assert isinstance(checks, Mapping), "operator health checks missing"
    assert all(isinstance(raw_check, Mapping) for raw_check in checks.values()), (
        "operator health contains malformed checks"
    )

    required_failures = [
        name
        for name, raw_check in checks.items()
        if isinstance(raw_check, Mapping)
        and raw_check.get("required") is True
        and raw_check.get("ok") is not True
    ]
    assert required_failures == ["embedding_index"], (
        "embedding_index must be the sole required failure during an acknowledged "
        f"embedding cutover; got {required_failures!r}"
    )

    embedding_check = checks.get("embedding_index")
    assert isinstance(embedding_check, Mapping), "embedding_index check missing"
    assert embedding_check.get("status") == "rebuild_required", (
        "acknowledged embedding cutover requires embedding_index=rebuild_required"
    )

    runtime = payload.get("runtime")
    assert isinstance(runtime, Mapping), "operator runtime health missing"
    runtime_failures = [
        name
        for name, raw_status in runtime.items()
        if not isinstance(raw_status, Mapping) or raw_status.get("ok") is not True
    ]
    assert not runtime_failures, (
        "embedding cutover acknowledgement cannot admit runtime failures; "
        f"got {runtime_failures!r}"
    )
