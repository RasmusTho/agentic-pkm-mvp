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
    ADAPTER_FAILURE_CLASSES,
    INQUIRY_INTENT_CONFIG_ENV,
    AdapterExecutionError,
    AdapterResult,
    CredentialUnavailableError,
    HttpModelAdapter,
    LocalCommandAdapter,
    ModelTurnAdapter,
    ScriptedAdapter,
    load_adapter_descriptors,
    load_adapters,
    sanitized_adapter_failure,
)
from app.builderops.models import BuilderOpsValidationError
from app.ops.host_secret_bootstrap import HOST_SECRET_RUNTIME_ENV_FILE
from app.ops.host_secret_contract import load_host_secret_contract
from llm_contract import (
    ADAPTER_FAILURE_CLASSES as KERNEL_ADAPTER_FAILURE_CLASSES,
    AdapterResult as KernelAdapterResult,
    ModelTurnAdapter as KernelModelTurnAdapter,
)
from app.builderops import model_inquiry_adapters as adapters_module
from app.builderops.model_inquiry_contract import RESPONSE_SCHEMA_VERSION
from tests.builderops.inquiry_intent import (
    COMMITTED_INTENT_CONFIG,
    COMMITTED_INTENT_PATH,
    CONTRACT_PATH,
    DECLARED_TEST_CREDENTIALS,
    intent_config,
    intent_env,
    resolver_for_targets,
    runtime_secret_file,
)


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

    # An injected provider credential leaves no value in the classified
    # diagnostic a receipt is allowed to retain; only the logical identifier.
    credential_failure = CredentialUnavailableError(
        adapter_id="anthropic-configured-model",
        credential_identity_ref="anthropic.api-key",
    )
    diagnostic = sanitized_adapter_failure(
        credential_failure, adapter_id="anthropic-configured-model"
    )
    assert diagnostic == {
        "adapter_id": "anthropic-configured-model",
        "adapter_failure_class": "credential_unavailable",
        "credential_identity_ref": "anthropic.api-key",
    }
    assert "credential-sentinel" not in json.dumps(diagnostic)
    http_adapter = HttpModelAdapter(
        adapter_id="anthropic-configured-model",
        provider="anthropic",
        model="configured-model",
        endpoint="https://api.anthropic.com/v1/messages",
        api_key="credential-sentinel",
    )
    assert "credential-sentinel" not in json.dumps(
        adapters_module.sanitized_adapter_identity(http_adapter)
    )


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


def test_provider_enabled_roles_require_distinct_non_mock_attestation(
    tmp_path: Path,
) -> None:
    mock_resolver = resolver_for_targets(
        tmp_path / "mock",
        {"fable": ("mock", "mock-chat"), "gpt_codex": ("mock", "mock-chat")},
    )
    mocked = load_adapter_descriptors(intent_env(), resolver=mock_resolver)
    assert [item["available"] for item in mocked.values()] == [False, False]
    assert all("mock" in item["reason"] for item in mocked.values())

    collided_resolver = resolver_for_targets(
        tmp_path / "collided",
        {
            "fable": ("anthropic", "claude-fable-5"),
            "gpt_codex": ("anthropic", "claude-fable-5"),
        },
    )
    collided = load_adapter_descriptors(intent_env(), resolver=collided_resolver)
    assert [item["available"] for item in collided.values()] == [False, False]
    assert all("distinct_effective_target" in item["reason"] for item in collided.values())
    with pytest.raises(BuilderOpsValidationError, match="distinct_effective_target"):
        load_adapters(intent_env(), resolver=collided_resolver)

    resolved = load_adapter_descriptors(intent_env())
    assert resolved["fable"]["adapter_id"] != resolved["gpt_codex"]["adapter_id"]
    assert (
        resolved["fable"]["target_fingerprint"]
        != resolved["gpt_codex"]["target_fingerprint"]
    )


def test_role_credentials_resolve_through_the_host_secret_contract(
    tmp_path: Path,
) -> None:
    contract = load_host_secret_contract(CONTRACT_PATH)
    descriptors = load_adapter_descriptors(intent_env())
    for role in ("fable", "gpt_codex"):
        assert contract.required_secrets_for_role(
            consumer="builderops-model-inquiry", role=role
        ) == (descriptors[role]["credential_identity_ref"],)

    secret_file = runtime_secret_file(tmp_path)
    adapters = load_adapters(
        {**intent_env(), HOST_SECRET_RUNTIME_ENV_FILE: str(secret_file)}
    )
    assert set(adapters) == {"fable", "gpt_codex"}
    for role, binding in (("fable", "ANTHROPIC_API_KEY"), ("gpt_codex", "OPENAI_API_KEY")):
        adapter = adapters[role]
        assert isinstance(adapter, HttpModelAdapter)
        assert adapter.api_key == DECLARED_TEST_CREDENTIALS[binding]

    # The same values in ambient process environment are not a credential source.
    with pytest.raises(CredentialUnavailableError) as ambient:
        load_adapters({**intent_env(), **DECLARED_TEST_CREDENTIALS})
    assert ambient.value.credential_identity_ref == "anthropic.api-key"
    assert ambient.value.failure_class == "credential_unavailable"

    # A malformed declared value fails closed rather than reaching a provider.
    malformed = runtime_secret_file(
        tmp_path / "malformed",
        {"ANTHROPIC_API_KEY": "short", "OPENAI_API_KEY": "short"},
    )
    with pytest.raises(CredentialUnavailableError) as invalid:
        load_adapters({**intent_env(), HOST_SECRET_RUNTIME_ENV_FILE: str(malformed)})
    assert invalid.value.credential_identity_ref == "anthropic.api-key"

    # Caller configuration may not name a credential, its environment binding,
    # a provider, a model, or a transport target.
    for forbidden in ("api_key_env", "provider", "model", "endpoint", "argv"):
        payload = intent_config()
        payload["roles"]["fable"][forbidden] = "declared-elsewhere"
        with pytest.raises(BuilderOpsValidationError):
            load_adapter_descriptors(
                {INQUIRY_INTENT_CONFIG_ENV: json.dumps(payload)}
            )


def test_committed_inquiry_intent_config_is_provider_free_and_value_free() -> None:
    raw = COMMITTED_INTENT_PATH.read_text(encoding="utf-8")
    lowered = raw.lower()
    for forbidden in (
        "anthropic",
        "openai",
        "claude",
        "gpt-",
        "api_key",
        "api-key",
        "apikey",
        "endpoint",
        "http",
        "_env",
        "keychain",
        "/users/",
        "ssh",
        "localhost",
        "argv",
        "command",
    ):
        assert forbidden not in lowered, forbidden
    assert set(COMMITTED_INTENT_CONFIG["roles"]) == {"fable", "gpt_codex"}
    for intent in COMMITTED_INTENT_CONFIG["roles"].values():
        assert set(intent) == {
            "capability_tier",
            "reasoning_effort",
            "determinism_required",
            "output_schema_ref",
            "independence",
            "fallback_requirement",
            "side_effect_class",
        }
        assert intent["independence"] == "distinct_effective_target"
        assert intent["fallback_requirement"] == "fallback_forbidden"

    # It validates through the production resolver path and yields the declared
    # census targets, which the committed document itself never names.
    descriptors = load_adapter_descriptors(intent_env())
    assert [descriptors[role]["available"] for role in ("fable", "gpt_codex")] == [
        True,
        True,
    ]
    assert descriptors["fable"]["provider"] != descriptors["gpt_codex"]["provider"]
    assert all(
        descriptor["credential_identity_ref"].endswith(".api-key")
        for descriptor in descriptors.values()
    )


def test_expired_interactive_session_is_not_a_generic_command_failure() -> None:
    adapter = LocalCommandAdapter(
        adapter_id="interactive-session",
        provider="fable",
        model="configured-specialist",
        argv=(
            sys.executable,
            "-c",
            f"import sys; sys.exit({adapters_module.SUBSCRIPTION_ADAPTER_SESSION_EXPIRED_EXIT_CODE})",
        ),
        timeout_seconds=5,
    )

    with pytest.raises(AdapterExecutionError) as raised:
        adapter.execute({"request": True})

    assert raised.value.failure_class == "session_expired"
    assert raised.value.exit_code == (
        adapters_module.SUBSCRIPTION_ADAPTER_SESSION_EXPIRED_EXIT_CODE
    )


def test_auth_failure_classes_are_in_the_closed_vocabulary() -> None:
    assert ADAPTER_FAILURE_CLASSES is KERNEL_ADAPTER_FAILURE_CLASSES
    assert {"credential_unavailable", "session_expired"} <= ADAPTER_FAILURE_CLASSES


def test_existing_adapter_contract_regression_suite() -> None:
    assert AdapterResult is KernelAdapterResult
    assert ModelTurnAdapter is KernelModelTurnAdapter

    adapter = ScriptedAdapter(
        adapter_id="compatibility-adapter",
        provider="fixture",
        model="fixture-model",
        responses=[json.dumps(_response())],
        calls=[],
    )
    result = adapter.execute({"request": "unchanged"})

    assert isinstance(result, AdapterResult)
    assert result.provider_request_id == "scripted-compatibility-adapter-0"
    assert adapter.calls == [{"request": "unchanged"}]
