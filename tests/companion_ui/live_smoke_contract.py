from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
