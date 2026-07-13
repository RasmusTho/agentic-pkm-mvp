from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.builderops.model_inquiry_adapters import (
    ADAPTER_CONFIG_ENV,
    AdapterExecutionError,
    LocalCommandAdapter,
    load_adapter_descriptors,
)
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION


def _response() -> dict[str, object]:
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "stance": "draft",
        "content": "bounded output",
        "claims": [],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": [],
        "accepted_artifact_hash": None,
    }


def test_local_command_adapter_is_bounded_and_secret_safe(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    program = (
        "import json,sys; request=json.load(sys.stdin); "
        f"assert request['literal'] == '; touch {marker}'; "
        f"print(json.dumps({_response()!r}))"
    )
    adapter = LocalCommandAdapter(
        adapter_id="fable-command",
        provider="fable",
        model="configured-specialist",
        argv=(sys.executable, "-c", program),
        timeout_seconds=2,
        max_output_bytes=10_000,
        environment={"LOCAL_SECRET": "credential-sentinel"},
    )

    result = adapter.execute({"literal": f"; touch {marker}"})

    assert json.loads(result.response_text)["content"] == "bounded output"
    assert not marker.exists()
    assert "credential-sentinel" not in result.response_text

    oversized = LocalCommandAdapter(
        adapter_id="oversized",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", "print('x' * 100)"),
        timeout_seconds=2,
        max_output_bytes=10,
    )
    with pytest.raises(AdapterExecutionError, match="exceeded limit"):
        oversized.execute({"request": True})

    timed_out = LocalCommandAdapter(
        adapter_id="timeout",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", "import time; time.sleep(2)"),
        timeout_seconds=0.01,
    )
    with pytest.raises(AdapterExecutionError, match="timed out"):
        timed_out.execute({"request": True})

    echo_secret = LocalCommandAdapter(
        adapter_id="secret-echo",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", "import os; print(os.environ['LOCAL_SECRET'])"),
        timeout_seconds=2,
        environment={"LOCAL_SECRET": "credential-sentinel"},
    )
    with pytest.raises(AdapterExecutionError, match="contained an allowed environment value"):
        echo_secret.execute({"request": True})


def test_local_command_adapter_exposes_allowlisted_exit_diagnostic_without_stderr() -> None:
    adapter = LocalCommandAdapter(
        adapter_id="fable-command",
        provider="fable",
        model="configured-specialist",
        argv=(
            sys.executable,
            "-c",
            "import sys; print('credential-sentinel', file=sys.stderr); sys.exit(17)",
        ),
        timeout_seconds=2,
    )

    with pytest.raises(AdapterExecutionError) as raised:
        adapter.execute({"request": True})

    error = raised.value
    assert error.failure_class == "command_exit_nonzero"
    assert error.exit_code == 17
    assert "credential-sentinel" not in str(error)


def test_local_command_adapter_maps_subscription_timeout_exit_to_timeout() -> None:
    adapter = LocalCommandAdapter(
        adapter_id="fable-command",
        provider="fable",
        model="configured-specialist",
        argv=(sys.executable, "-c", "import sys; sys.exit(124)"),
        timeout_seconds=2,
    )

    with pytest.raises(AdapterExecutionError) as raised:
        adapter.execute({"request": True})

    assert raised.value.failure_class == "command_timeout"
    assert raised.value.exit_code == 124


def test_provider_enabled_roles_require_distinct_non_mock_attestation() -> None:
    config = {
        role: {
            "kind": "command",
            "role_identity": role,
            "adapter_id": f"{role}-adapter",
            "provider": "mock",
            "model": "not-fable",
            "argv": [sys.executable, "-c", "print('{}')"],
        }
        for role in ("fable", "gpt_codex")
    }
    descriptors = load_adapter_descriptors({ADAPTER_CONFIG_ENV: json.dumps(config)})
    assert descriptors["fable"]["available"] is False
    assert descriptors["gpt_codex"]["available"] is False
    assert all("mock" in item["reason"] for item in descriptors.values())
