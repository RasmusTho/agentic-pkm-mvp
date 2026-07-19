from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.builderops.model_inquiry_adapters import (
    ADAPTER_CONFIG_ENV,
    AdapterExecutionError,
    LocalCommandAdapter,
    load_adapter_descriptors,
)
from app.builderops import model_inquiry_adapters as adapters_module
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


def test_local_command_adapter_translates_process_group_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "command-tree-pids"
    def deny_process_group_signal(*_args: object) -> None:
        raise PermissionError("credential-sentinel /secret/host/path must not leak")

    monkeypatch.setattr("app.builderops.model_inquiry_adapters.os.killpg", deny_process_group_signal)
    wrapper = (
        "import os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        f"open({str(pid_file)!r},'w').write(f'{{os.getpid()}} {{child.pid}}'); "
        "print('x' * 100000, flush=True); "
        "time.sleep(60)"
    )
    adapter = LocalCommandAdapter(
        adapter_id="permission-denied-cleanup",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", wrapper),
        timeout_seconds=2,
        max_output_bytes=10,
        environment={"LOCAL_SECRET": "credential-sentinel"},
    )

    with pytest.raises(AdapterExecutionError, match="cleanup denied") as raised:
        adapter.execute({"request": True})

    assert raised.value.failure_class == "stdout_oversize"
    formatted = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert "credential-sentinel" not in formatted
    assert "/secret/host/path" not in formatted
    wrapper_pid, child_pid = (int(value) for value in pid_file.read_text().split())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and any(
        _process_exists(pid) for pid in (wrapper_pid, child_pid)
    ):
        time.sleep(0.01)
    assert not _process_exists(wrapper_pid)
    assert not _process_exists(child_pid)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_local_command_adapter_preserves_output_failure_when_cleanup_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_process_group_signal(*_args: object) -> None:
        raise PermissionError("credential-sentinel /secret/host/path must not leak")

    monkeypatch.setattr("app.builderops.model_inquiry_adapters.os.killpg", deny_process_group_signal)
    adapter = LocalCommandAdapter(
        adapter_id="permission-denied-output",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", "print('x' * 100000)"),
        timeout_seconds=2,
        max_output_bytes=10,
    )

    with pytest.raises(AdapterExecutionError, match="cleanup denied") as raised:
        adapter.execute({"request": True})

    assert raised.value.failure_class == "stdout_oversize"
    formatted = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert "credential-sentinel" not in formatted
    assert "/secret/host/path" not in formatted


def test_denied_cleanup_does_not_signal_same_lstart_reused_descendant_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.pid = 7000
    process.poll.return_value = None
    process.wait.return_value = -9
    signaled: list[int] = []

    monkeypatch.setattr(adapters_module.os, "killpg", Mock(side_effect=PermissionError))
    monkeypatch.setattr(
        adapters_module,
        "_descendant_process_identities",
        Mock(return_value=[(7001, (7000, 100, 0))]),
    )
    monkeypatch.setattr(
        adapters_module,
        "_kernel_process_identity",
        Mock(return_value=(7000, 200, 0)),
    )
    monkeypatch.setattr(adapters_module.os, "kill", lambda pid, _signal: signaled.append(pid))

    assert adapters_module._kill_process_group(process) is True
    assert signaled == []
    process.kill.assert_called_once_with()


def test_denied_cleanup_preserves_timeout_failure_and_hides_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_process_group_signal(*_args: object) -> None:
        raise PermissionError("credential-sentinel /secret/host/path must not leak")

    monkeypatch.setattr("app.builderops.model_inquiry_adapters.os.killpg", deny_process_group_signal)
    adapter = LocalCommandAdapter(
        adapter_id="permission-denied-timeout",
        provider="local",
        model="fixture",
        argv=(sys.executable, "-c", "import time; time.sleep(60)"),
        timeout_seconds=0.01,
    )

    with pytest.raises(AdapterExecutionError, match="cleanup denied") as raised:
        adapter.execute({"request": True})

    assert raised.value.failure_class == "command_timeout"
    formatted = "".join(
        traceback.format_exception(type(raised.value), raised.value, raised.value.__traceback__)
    )
    assert "credential-sentinel" not in formatted
    assert "/secret/host/path" not in formatted
    assert "TimeoutExpired" not in formatted


def test_denied_cleanup_uses_one_global_deadline_for_many_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.pid = 8000
    process.poll.return_value = None
    clock = Mock()
    clock.now = 0.0
    signaled: list[int] = []

    def monotonic() -> float:
        return float(clock.now)

    def identity(pid: int) -> tuple[int, int, int]:
        clock.now += 0.4
        return (8000, pid, 0)

    identities = [(pid, (8000, pid, 0)) for pid in range(8001, 8101)]
    monkeypatch.setattr(adapters_module.time, "monotonic", monotonic)
    monkeypatch.setattr(adapters_module.os, "killpg", Mock(side_effect=PermissionError))
    monkeypatch.setattr(
        adapters_module,
        "_descendant_process_identities",
        Mock(return_value=identities),
    )
    monkeypatch.setattr(adapters_module, "_kernel_process_identity", identity)
    monkeypatch.setattr(adapters_module.os, "kill", lambda pid, _signal: signaled.append(pid))

    assert adapters_module._kill_process_group(process) is True
    assert len(signaled) < len(identities)
    assert clock.now <= adapters_module.CLEANUP_TIMEOUT_SECONDS
    process.kill.assert_called_once_with()


def test_descendant_identity_capture_rejects_changed_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree_snapshot = Mock(stdout="8000 1\n8001 8000\n")
    monkeypatch.setattr(adapters_module.subprocess, "run", Mock(return_value=tree_snapshot))
    monkeypatch.setattr(
        adapters_module,
        "_kernel_process_identity",
        Mock(return_value=(9999, 12345, 0)),
    )

    descendants = adapters_module._descendant_process_identities(
        8000,
        deadline=time.monotonic() + 1,
    )

    assert descendants == []


def test_linux_process_identity_is_bytes_safe_for_non_utf8_comm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stat = b"9000 (bad\xffname) S 8000 " + b" ".join([b"0"] * 17 + [b"12345"])
    monkeypatch.setattr(adapters_module.sys, "platform", "linux")
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: io.BytesIO(stat))

    assert adapters_module._kernel_process_identity(9000) == (8000, 12345, 0)


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
