from __future__ import annotations

from copy import deepcopy

import pytest

from tests.companion_ui.live_smoke_contract import assert_operator_health


def _embedding_rebuild_payload() -> dict[str, object]:
    return {
        "ok": False,
        "required_ok": False,
        "checks": {
            "embedding_index": {
                "ok": False,
                "required": True,
                "status": "rebuild_required",
            },
            "index_outbox": {"ok": True, "required": True},
            "obsidian": {"ok": False, "required": False},
        },
        "runtime": {
            "db": {"ok": True},
            "llm": {"ok": True},
            "watcher": {"ok": True},
            "worker": {"ok": True},
        },
    }


def test_embedding_cutover_accepts_only_rebuild_required_degradation() -> None:
    payload = _embedding_rebuild_payload()
    assert_operator_health(payload, allow_embedding_rebuild_required=True)

    with pytest.raises(AssertionError, match="operator health not ok"):
        assert_operator_health(payload, allow_embedding_rebuild_required=False)

    other_required_failure = deepcopy(payload)
    checks = other_required_failure["checks"]
    assert isinstance(checks, dict)
    checks["index_outbox"] = {"ok": False, "required": True}
    with pytest.raises(AssertionError, match="sole required failure"):
        assert_operator_health(
            other_required_failure,
            allow_embedding_rebuild_required=True,
        )

    wrong_transition = deepcopy(payload)
    wrong_checks = wrong_transition["checks"]
    assert isinstance(wrong_checks, dict)
    embedding_check = wrong_checks["embedding_index"]
    assert isinstance(embedding_check, dict)
    embedding_check["status"] = "mixed_identities"
    with pytest.raises(AssertionError, match="rebuild_required"):
        assert_operator_health(wrong_transition, allow_embedding_rebuild_required=True)

    runtime_failure = deepcopy(payload)
    runtime = runtime_failure["runtime"]
    assert isinstance(runtime, dict)
    runtime["db"] = {"ok": False, "status": "unreachable"}
    with pytest.raises(AssertionError, match="runtime failures"):
        assert_operator_health(runtime_failure, allow_embedding_rebuild_required=True)
