from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.builderops.model_inquiry_adapters import AdapterExecutionError, LocalCommandAdapter
from app.model_access.codex_cli import (
    CodexCliError,
    CodexCliExecutor,
    CodexCliSafeProfile,
    MODEL_CATALOG_SCHEMA_VERSION,
    SAFE_PROFILE_REF,
    TOOL_SURFACE_CATALOG_VERSION,
)
from app.model_access.process_supervisor import _clone_or_copy_descriptor


_HELP = """Codex exec options:
--ephemeral
--ignore-rules
--ignore-user-config
--model
--output-last-message
--output-schema
--sandbox
"""
_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
_MODEL = {
    "additional_speed_tiers": [],
    "apply_patch_tool_type": "freeform",
    "availability_nux": None,
    "base_instructions": "PRIVATE_CATALOG_TEXT must never enter receipts.",
    "comp_hash": None,
    "context_window": 128000,
    "default_reasoning_level": "medium",
    "default_reasoning_summary": "auto",
    "default_verbosity": "medium",
    "description": "fixture",
    "display_name": "Luna",
    "effective_context_window_percent": 95,
    "experimental_supported_tools": ["clock", "search_tool"],
    "include_apps_usage_instructions": True,
    "include_plugin_usage_instructions": True,
    "include_skills_usage_instructions": True,
    "input_modalities": ["text"],
    "max_context_window": 128000,
    "model_messages": {"tools": {"code_mode": {"description": "tool"}}},
    "multi_agent_reasoning_effort": "high",
    "multi_agent_version": "v2",
    "node_repl_auto_review_required": True,
    "node_repl_disabled": False,
    "priority": 1,
    "service_tiers": [],
    "shell_type": "unified_exec",
    "slug": "gpt-5.6-luna",
    "support_verbosity": True,
    "supported_in_api": True,
    "supported_reasoning_levels": [
    {"effort": "low", "description": "low"},
    {"effort": "medium", "description": "medium"},
    {"effort": "high", "description": "high"},
    {"effort": "xhigh", "description": "xhigh"},
    ],
    "supports_experimental_context": True,
    "supports_image_detail_original": True,
    "supports_search_tool": True,
    "tool_mode": "code_mode_only",
    "truncation_policy": {"mode": "tokens", "limit": 10000},
    "upgrade": None,
    "use_responses_lite": False,
    "visibility": "list",
    "web_search_tool_type": "run",
}


def _profile_file(
    path: Path,
    *,
    output_schema_supported: bool = True,
    cli_version: str = "codex-cli 0.99.0",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "codex-cli-safe-profile.v2",
                "profile_ref": SAFE_PROFILE_REF,
                "cli_version": cli_version,
                "output_schema_supported": output_schema_supported,
                "tool_surface_catalog_version": TOOL_SURFACE_CATALOG_VERSION,
                "model_catalog_schema_version": MODEL_CATALOG_SCHEMA_VERSION,
            }
        ),
        encoding="utf-8",
    )
    return path


def _catalog(*slugs: str) -> dict[str, list[dict[str, object]]]:
    return {
        "models": [
            {**_MODEL, "slug": slug}
            for slug in (slugs or ("gpt-5.6-luna",))
        ]
    }


def _fake_cli(
    path: Path,
    *,
    trace_path: Path,
    version: str = "codex-cli 0.99.0",
    login_output: str = "Logged in using ChatGPT",
    login_exit: int = 0,
    help_output: str = _HELP,
    response: str = '{"answer":"ok"}',
    catalog_output: str | None = None,
    execution_exit: int = 0,
    execution_delay_seconds: float = 0,
    execution_stdout_bytes: int = 0,
    spawn_child: bool = False,
    redirect_child_stdio: bool = False,
    crash_parent: bool = False,
    replace_self_during_catalog: bool = False,
    minimal_trace: bool = False,
) -> Path:
    script = f"""#!{sys.executable}
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
    print({version!r})
elif args == ["exec", "--help"]:
    print({help_output!r})
elif args == ["login", "status"]:
    print({login_output!r})
    raise SystemExit({login_exit})
elif args == ["debug", "models", "--bundled"]:
    sys.stdout.write({(catalog_output if catalog_output is not None else json.dumps(_catalog()))!r})
    if not {(catalog_output if catalog_output is not None else json.dumps(_catalog()))!r}.endswith("\\n"):
        sys.stdout.write("\\n")
    if {replace_self_during_catalog!r}:
        replacement = Path(__file__).with_suffix(".replacement")
        replacement.write_text("#!{sys.executable}\\nraise SystemExit(0)\\n", encoding="utf-8")
        replacement.chmod(0o700)
        os.replace(replacement, __file__)
else:
    trace = Path({str(trace_path)!r})
    if {minimal_trace!r}:
        count_path = trace.with_suffix(trace.suffix + ".count")
        count = int(count_path.read_text(encoding="utf-8")) if count_path.exists() else 0
        count_path.write_text(str(count + 1), encoding="utf-8")
        trace.write_text(json.dumps({{"pid": os.getpid()}}), encoding="utf-8")
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text({response!r}, encoding="utf-8")
        raise SystemExit({execution_exit})
    count_path = trace.with_suffix(trace.suffix + ".count")
    count = int(count_path.read_text(encoding="utf-8")) if count_path.exists() else 0
    count_path.write_text(str(count + 1), encoding="utf-8")
    record = {{
        "argv": args,
        "prompt": sys.stdin.read(),
        "openai_api_key_present": "OPENAI_API_KEY" in os.environ,
        "home": os.environ.get("HOME"),
        "pid": os.getpid(),
        "executable_directory": str(Path(__file__).parent),
        "cwd_entries": sorted(item.name for item in Path.cwd().iterdir()),
    }}
    if {spawn_child!r}:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdout=subprocess.DEVNULL if {redirect_child_stdio!r} else None,
            stderr=subprocess.DEVNULL if {redirect_child_stdio!r} else None,
        )
        record["child_pid"] = child.pid
    trace.write_text(json.dumps(record), encoding="utf-8")
    output_path = Path(args[args.index("--output-last-message") + 1])
    config_values = [args[index + 1] for index, item in enumerate(args[:-1]) if item == "-c"]
    model_catalog_config = next(item.split("=", 1)[1] for item in config_values if item.startswith("model_catalog_json="))
    safe_catalog_path = Path(json.loads(model_catalog_config))
    safe_catalog = json.loads(safe_catalog_path.read_text(encoding="utf-8"))
    record["effective_model_surfaces"] = [
        {{key: descriptor[key] for key in (
            "slug", "tool_mode", "shell_type", "apply_patch_tool_type",
            "supports_search_tool", "experimental_supported_tools",
            "multi_agent_version", "node_repl_disabled",
            "node_repl_auto_review_required", "web_search_tool_type",
            "model_messages",
            "include_apps_usage_instructions", "include_plugin_usage_instructions",
            "include_skills_usage_instructions",
        )}}
        for descriptor in safe_catalog["models"]
    ]
    trace.write_text(json.dumps(record), encoding="utf-8")
    output_path.write_text({response!r}, encoding="utf-8")
    if {crash_parent!r}:
        os.kill(os.getppid(), signal.SIGKILL)
    if {execution_delay_seconds!r}:
        time.sleep({execution_delay_seconds!r})
    print("x" * {execution_stdout_bytes!r})
    raise SystemExit({execution_exit})
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(0o700)
    return path


def _executor(
    binary: Path,
    *,
    home: Path,
    profile: Path | None = None,
    max_output_bytes: int = 1_000_000,
    max_input_bytes: int = 2_000_000,
) -> CodexCliExecutor:
    return CodexCliExecutor(
        safe_profile_path=profile if profile is not None else _profile_file(home.parent / "profile.json"),
        executable_name=binary.name,
        environment={
            "PATH": f"{binary.parent}:{os.environ.get('PATH', '')}",
            "HOME": str(home),
            "OPENAI_API_KEY": "secret-must-not-be-forwarded",
        },
        execution_timeout_seconds=2,
        preflight_timeout_seconds=2,
        max_output_bytes=max_output_bytes,
        max_input_bytes=max_input_bytes,
    )


def _assert_pids_exit(*pids: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            return
        time.sleep(0.02)
    pytest.fail(f"processes survived bounded cleanup: {alive}")


def _subscription_bridge_adapter(
    *,
    binary: Path,
    home: Path,
    profile: Path,
    timeout_seconds: float,
    adapter_id: str,
) -> LocalCommandAdapter:
    bridge = Path(__file__).resolve().parents[2] / "scripts" / "model_inquiry_subscription_adapter.py"
    return LocalCommandAdapter(
        adapter_id=adapter_id,
        provider="openai",
        model="gpt-5.6-luna",
        argv=(
            sys.executable,
            str(bridge),
            "--perspective",
            "synthesis",
            "--model",
            "gpt-5.6-luna",
            "--reasoning-effort",
            "low",
            "--output-schema-ref",
            "builderops.model-turn-response.v1",
        ),
        timeout_seconds=timeout_seconds,
        environment={
            "HOME": str(home),
            "PATH": f"{binary.parent}:{os.environ.get('PATH', '')}",
            "CODEX_CLI_SAFE_PROFILE_PATH": str(profile),
        },
    )


def _run_bridge(adapter: LocalCommandAdapter) -> None:
    adapter.execute(
        {
            "system_prompt": "trusted",
            "question": "untrusted",
            "reviewed_artifact_refs": [],
        }
    )


def test_preflight_classifies_cli_auth_and_version_failures(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    missing = CodexCliExecutor(
        safe_profile_path=_profile_file(tmp_path / "missing-profile.json"),
        environment={"PATH": "", "HOME": str(home)},
    )
    with pytest.raises(CodexCliError) as error:
        missing.preflight(model="gpt-5.6-luna")
    assert error.value.failure_code == "cli_missing"

    expired_dir = tmp_path / "expired"
    expired_dir.mkdir()
    expired_binary = _fake_cli(
        expired_dir / "codex",
        trace_path=tmp_path / "expired-trace.json",
        login_output="Session expired; please run /login",
        login_exit=1,
    )
    with pytest.raises(CodexCliError) as error:
        _executor(expired_binary, home=home).preflight(model="gpt-5.6-luna")
    assert error.value.failure_code == "session_expired"
    assert "secret-must-not-be-forwarded" not in str(error.value)

    auth_dir = tmp_path / "auth-unavailable"
    auth_dir.mkdir()
    no_auth = _fake_cli(
        auth_dir / "codex",
        trace_path=tmp_path / "no-auth-trace.json",
        login_output="Authentication status unavailable",
        login_exit=1,
    )
    with pytest.raises(CodexCliError) as error:
        _executor(no_auth, home=home).preflight(model="gpt-5.6-luna")
    assert error.value.failure_code == "authentication_unavailable"

    api_key_dir = tmp_path / "api-key-auth"
    api_key_dir.mkdir()
    api_key_auth = _fake_cli(
        api_key_dir / "codex",
        trace_path=tmp_path / "api-key-auth-trace.json",
        login_output="Logged in using an API key - synthetic-redacted-key",
    )
    with pytest.raises(CodexCliError) as error:
        _executor(api_key_auth, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "authentication_unavailable"
    assert not (tmp_path / "api-key-auth-trace.json").exists()
    assert "synthetic-redacted-key" not in str(error.value)

    for case, status in (
        (
            "mixed-api-key",
            "Logged in using ChatGPT\nLogged in using an API key synthetic-secret",
        ),
        (
            "mixed-workload-identity",
            "Logged in using ChatGPT\nLogged in using a workload identity",
        ),
        (
            "extra-status-line",
            "Logged in using ChatGPT\nAdditional authentication status",
        ),
    ):
        ambiguous_binary = _fake_cli(
            tmp_path / f"codex-{case}",
            trace_path=tmp_path / f"{case}-trace.json",
            login_output=status,
        )
        with pytest.raises(CodexCliError) as error:
            _executor(ambiguous_binary, home=home).execute(
                model="gpt-5.6-luna",
                reasoning_effort="low",
                developer_instructions="developer",
                user_prompt="user",
            )
        assert error.value.failure_code == "authentication_unavailable"
        assert not (tmp_path / f"{case}-trace.json").exists()
        assert "synthetic-secret" not in str(error.value)

    subscription_dir = tmp_path / "subscription-auth"
    subscription_dir.mkdir()
    subscription_auth = _fake_cli(
        subscription_dir / "codex",
        trace_path=tmp_path / "subscription-auth-trace.json",
    )
    preflight = _executor(subscription_auth, home=home).preflight(
        model="gpt-5.6-luna"
    )
    assert preflight.authentication_status == "chatgpt_subscription"

    version_dir = tmp_path / "wrong-version"
    version_dir.mkdir()
    wrong_version = _fake_cli(
        version_dir / "codex",
        trace_path=tmp_path / "wrong-version-trace.json",
        version="codex-cli 0.100.0",
    )
    with pytest.raises(CodexCliError) as error:
        _executor(wrong_version, home=home).preflight(model="gpt-5.6-luna")
    assert error.value.failure_code == "cli_version_unsupported"


def test_execution_timeout_and_cli_failure_are_terminal_and_redacted(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    slow = _fake_cli(
        tmp_path / "codex-slow",
        trace_path=tmp_path / "slow-trace.json",
        execution_delay_seconds=1,
        spawn_child=True,
    )
    timeout_executor = CodexCliExecutor(
        safe_profile_path=_profile_file(tmp_path / "timeout-profile.json"),
        executable_name=slow.name,
        environment={
            "PATH": f"{slow.parent}:{os.environ.get('PATH', '')}",
            "HOME": str(home),
        },
        preflight_timeout_seconds=2,
        execution_timeout_seconds=0.5,
    )
    with pytest.raises(CodexCliError) as error:
        timeout_executor.execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "command_timeout"
    assert (tmp_path / "slow-trace.json.count").read_text() == "1"
    slow_trace = json.loads((tmp_path / "slow-trace.json").read_text())
    _assert_pids_exit(slow_trace["pid"], slow_trace["child_pid"])

    failed = _fake_cli(
        tmp_path / "codex-failed",
        trace_path=tmp_path / "failed-trace.json",
        execution_exit=19,
    )
    with pytest.raises(CodexCliError) as error:
        _executor(failed, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "command_exit_nonzero"
    assert "Logged in" not in str(error.value)
    assert (tmp_path / "failed-trace.json.count").read_text() == "1"

    chatty = _fake_cli(
        tmp_path / "codex-chatty",
        trace_path=tmp_path / "chatty-trace.json",
        execution_stdout_bytes=2048,
    )
    with pytest.raises(CodexCliError) as error:
        _executor(chatty, home=home, max_output_bytes=1024).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "stdout_oversize"
    assert (tmp_path / "chatty-trace.json.count").read_text() == "1"


def test_exit_cleanup_kills_descendant_with_redirected_output(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "success-with-child.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        spawn_child=True,
    )

    started = time.monotonic()
    result = _executor(binary, home=home).execute(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        developer_instructions="developer",
        user_prompt="user",
    )

    assert result.response_text == '{"answer":"ok"}'
    assert time.monotonic() - started < 2
    invocation = json.loads(trace.read_text(encoding="utf-8"))
    _assert_pids_exit(invocation["pid"], invocation["child_pid"])


def test_parent_loss_terminates_codex_process_tree(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "parent-loss-trace.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        execution_delay_seconds=10,
        spawn_child=True,
    )
    profile = _profile_file(tmp_path / "parent-loss-profile.json")
    repository_root = Path(__file__).resolve().parents[2]
    driver = f"""
from pathlib import Path
from app.model_access.codex_cli import CodexCliExecutor

CodexCliExecutor(
    safe_profile_path=Path({str(profile)!r}),
    executable_name={binary.name!r},
    environment={{"PATH": {str(binary.parent)!r}, "HOME": {str(home)!r}}},
    execution_timeout_seconds=20,
    preflight_timeout_seconds=2,
).execute(
    model="gpt-5.6-luna",
    reasoning_effort="low",
    developer_instructions="developer",
    user_prompt="user",
)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(repository_root), environment.get("PYTHONPATH", "")]
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", driver],
        cwd=repository_root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    invocation: dict[str, int] | None = None
    while time.monotonic() < deadline:
        if parent.poll() is not None:
            pytest.fail("request parent exited before fake CLI reached execution")
        try:
            value = json.loads(trace.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.02)
            continue
        if "child_pid" in value:
            invocation = value
            break
        time.sleep(0.02)
    if invocation is None:
        parent.kill()
        parent.wait(timeout=2)
        pytest.fail("fake Codex CLI did not reach execution")

    parent.kill()
    parent.wait(timeout=2)
    _assert_pids_exit(invocation["pid"], invocation["child_pid"])


def test_execution_is_ephemeral_pinned_bounded_and_single_target(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.json"
    bundled_catalog = _catalog("gpt-6-astra", "gpt-5.6-luna")
    bundled_catalog["models"][0].pop("multi_agent_reasoning_effort")
    bundled_catalog["models"][0].pop("multi_agent_version")
    bundled_catalog["models"][0].pop("tool_mode")
    bundled_catalog["models"][0]["model_specialty"] = "code"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        response="x" * 65536,
        catalog_output=json.dumps(bundled_catalog),
    )
    executor = _executor(binary, home=home, max_output_bytes=32768)

    with pytest.raises(CodexCliError) as error:
        executor.execute(
            model="gpt-5.6-luna",
            reasoning_effort="high",
            developer_instructions="trusted developer channel",
            user_prompt="untrusted user channel",
        )

    assert error.value.failure_code == "stdout_oversize"
    invocation = json.loads(trace.read_text(encoding="utf-8"))
    argv = invocation["argv"]
    assert argv[argv.index("--model") + 1] == "gpt-5.6-luna"
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    reasoning = next(value for value in argv if value.startswith("model_reasoning_effort="))
    assert json.loads(reasoning.split("=", 1)[1]) == "high"
    assert invocation["prompt"] == "untrusted user channel"
    assert invocation["openai_api_key_present"] is False
    assert invocation["cwd_entries"] == []
    surfaces = invocation["effective_model_surfaces"]
    assert len(surfaces) == 2
    for surface in surfaces:
        assert surface["model_messages"] == {}
        assert surface["tool_mode"] is None
        assert surface["shell_type"] == "disabled"
        assert surface["apply_patch_tool_type"] is None
        assert surface["supports_search_tool"] is False
        assert surface["experimental_supported_tools"] == []
        assert surface["multi_agent_version"] is None
        assert surface["node_repl_disabled"] is True
        assert surface["node_repl_auto_review_required"] is False
        assert surface["web_search_tool_type"] is None
        assert surface["include_apps_usage_instructions"] is False
        assert surface["include_plugin_usage_instructions"] is False
        assert surface["include_skills_usage_instructions"] is False
    assert "PRIVATE_CATALOG_TEXT" not in trace.read_text(encoding="utf-8")
    assert trace.with_suffix(trace.suffix + ".count").read_text() == "1"


def test_schema_support_and_strict_validation_fallback(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    supported_trace = tmp_path / "supported-trace.json"
    supported = _fake_cli(
        tmp_path / "codex-supported",
        trace_path=supported_trace,
    )
    supported_result = _executor(supported, home=home).execute(
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        developer_instructions="developer",
        user_prompt="user",
        output_schema_ref="answer.v1",
        output_schema=_SCHEMA,
    )
    supported_argv = json.loads(supported_trace.read_text())["argv"]
    assert "--output-schema" in supported_argv
    assert json.loads(supported_result.response_text) == {"answer": "ok"}

    fallback_trace = tmp_path / "fallback-trace.json"
    fallback = _fake_cli(
        tmp_path / "codex-fallback",
        trace_path=fallback_trace,
    )
    fallback_result = _executor(
        fallback,
        home=home,
        profile=_profile_file(
            tmp_path / "fallback-profile.json", output_schema_supported=False
        ),
    ).execute(
        model="gpt-5.6-luna",
        reasoning_effort="medium",
        developer_instructions="developer",
        user_prompt="user",
        output_schema_ref="answer.v1",
        output_schema=_SCHEMA,
    )
    fallback_argv = json.loads(fallback_trace.read_text())["argv"]
    assert "--output-schema" not in fallback_argv
    assert json.loads(fallback_result.response_text) == {"answer": "ok"}

    for invalid_schema in (
        {"type": "object", "properties": {"x": float("nan")}},
        {"$ref": "#"},
        {"type": "object", "description": "x" * 256},
    ):
        invalid_schema_trace = tmp_path / f"schema-refused-{len(str(invalid_schema))}.json"
        invalid_schema_binary = _fake_cli(
            tmp_path / f"codex-schema-refused-{len(str(invalid_schema))}",
            trace_path=invalid_schema_trace,
        )
        with pytest.raises(CodexCliError) as error:
            _executor(
                invalid_schema_binary,
                home=home,
                profile=_profile_file(
                    tmp_path / f"profile-schema-refused-{len(str(invalid_schema))}.json",
                    output_schema_supported=False,
                ),
                max_input_bytes=64,
            ).execute(
                model="gpt-5.6-luna",
                reasoning_effort="medium",
                developer_instructions="developer",
                user_prompt="user",
                output_schema_ref="invalid.v1",
                output_schema=invalid_schema,
            )
        assert error.value.failure_code == "schema_violation"
        assert not invalid_schema_trace.exists()

    invalid_binary = _fake_cli(
        tmp_path / "codex-invalid",
        trace_path=tmp_path / "invalid-trace.json",
        response='{"answer":"ok","extra":true}',
    )
    with pytest.raises(CodexCliError) as error:
        _executor(
            invalid_binary,
            home=home,
            profile=_profile_file(
                tmp_path / "invalid-profile.json", output_schema_supported=False
            ),
        ).execute(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            developer_instructions="developer",
            user_prompt="user",
            output_schema_ref="answer.v1",
            output_schema=_SCHEMA,
        )
    assert error.value.failure_code == "schema_violation"

    strict_number_schema = {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    for nonstandard_constant in ("NaN", "Infinity", "-Infinity"):
        invalid_constant = _fake_cli(
            tmp_path / f"codex-invalid-{nonstandard_constant.replace('-', 'minus')}",
            trace_path=tmp_path / f"invalid-{nonstandard_constant.replace('-', 'minus')}.json",
            response=f'{{"value":{nonstandard_constant}}}',
        )
        with pytest.raises(CodexCliError) as error:
            _executor(invalid_constant, home=home).execute(
                model="gpt-5.6-luna",
                reasoning_effort="medium",
                developer_instructions="developer",
                user_prompt="user",
                output_schema_ref="json-number-object.v1",
                output_schema=strict_number_schema,
            )
        assert error.value.failure_code == "schema_violation"

    overflow_number = _fake_cli(
        tmp_path / "codex-overflow-number",
        trace_path=tmp_path / "overflow-number.json",
        response='{"value":1e999}',
    )
    with pytest.raises(CodexCliError) as error:
        _executor(overflow_number, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            developer_instructions="developer",
            user_prompt="user",
            output_schema_ref="json-number-object.v1",
            output_schema=strict_number_schema,
        )
    assert error.value.failure_code == "schema_violation"

    deep_response = '{"answer":' + "[" * 2000 + "0" + "]" * 2000 + "}"
    deeply_nested = _fake_cli(
        tmp_path / "codex-deep-response",
        trace_path=tmp_path / "deep-response.json",
        response=deep_response,
    )
    with pytest.raises(CodexCliError) as error:
        _executor(deeply_nested, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="medium",
            developer_instructions="developer",
            user_prompt="user",
            output_schema_ref="answer.v1",
            output_schema=_SCHEMA,
        )
    assert error.value.failure_code == "schema_violation"


def test_response_file_is_hard_limited_during_execution(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "oversized-response.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        response="x" * 8192,
        minimal_trace=True,
    )

    with pytest.raises(CodexCliError) as error:
        _executor(binary, home=home, max_output_bytes=1024).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )

    assert error.value.failure_code == "stdout_oversize"
    assert (tmp_path / "oversized-response.json.count").read_text() == "1"


def test_trusted_instruction_and_user_content_use_separate_channels(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.json"
    binary = _fake_cli(tmp_path / "codex", trace_path=trace)
    executor = _executor(binary, home=home)

    executor.execute(
        model="gpt-5.6-luna",
        reasoning_effort="high",
        developer_instructions="trusted text must not be concatenated",
        user_prompt="untrusted text remains the only stdin prompt",
    )

    invocation = json.loads(trace.read_text(encoding="utf-8"))
    argv = invocation["argv"]
    developer_value = next(
        value for value in argv if value.startswith("developer_instructions=")
    )
    assert json.loads(developer_value.split("=", 1)[1]) == (
        "trusted text must not be concatenated"
    )
    assert invocation["prompt"] == "untrusted text remains the only stdin prompt"
    assert "trusted text must not be concatenated" not in invocation["prompt"]


def test_versioned_no_tools_profile_fails_closed_on_unknown_features(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(CodexCliError) as error:
        CodexCliSafeProfile.from_mapping(
            {
                "schema_version": "codex-cli-safe-profile.v1",
                "profile_ref": SAFE_PROFILE_REF,
                "cli_version": "codex-cli 0.99.0",
                "output_schema_supported": True,
                "tool_surface_catalog_version": "codex_cli_tool_surfaces.v1",
                "model_catalog_schema_version": "codex_cli_model_catalog.v1",
            }
        )
    assert error.value.failure_code == "unsupported_profile"

    executor = CodexCliExecutor(environment={"PATH": "", "HOME": str(home)})
    with pytest.raises(CodexCliError) as error:
        executor.preflight(model="gpt-5.6-luna")
    assert error.value.failure_code == "unsupported_profile"

    binary = _fake_cli(tmp_path / "codex", trace_path=tmp_path / "trace.json")
    executor = _executor(binary, home=home)
    executor.execute(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        developer_instructions="developer",
        user_prompt="user",
    )
    argv = json.loads((tmp_path / "trace.json").read_text())["argv"]
    config_values = [
        argv[index + 1]
        for index, _value in enumerate(argv[:-1])
        if argv[index] == "-c"
    ]
    disabled = {item: value for item, value in (entry.split("=", 1) for entry in config_values)}
    assert disabled["features.shell_tool"] == "false"
    assert disabled["features.unified_exec"] == "false"
    assert disabled["features.apps"] == "false"
    assert disabled["features.multi_agent"] == "false"
    assert disabled["features.remote_plugin"] == "false"
    assert disabled["features.sleep_tool"] == "false"
    assert disabled["features.view_image"] == "false"
    assert disabled["features.tool_search"] == "false"
    assert disabled["features.token_budget"] == "false"
    assert disabled["features.request_permissions_tool"] == "false"
    assert disabled["features.default_mode_request_user_input"] == "false"
    assert disabled["mcp_servers"] == "{}"
    assert disabled["tools.view_image"] == "false"
    assert disabled["tools.web_search"] == "false"
    assert disabled["web_search"] == '"disabled"'


def test_catalog_schema_drift_and_unknown_model_fail_before_model_execution(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.json"
    missing_model = _fake_cli(
        tmp_path / "codex-missing-model",
        trace_path=trace,
        catalog_output=json.dumps(_catalog("another-model")),
    )
    with pytest.raises(CodexCliError) as error:
        _executor(missing_model, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "model_unavailable"
    assert not trace.exists()

    changed_catalog = _catalog()
    changed_catalog["models"][0]["new_tool_surface"] = True
    changed = _fake_cli(
        tmp_path / "codex-changed-catalog",
        trace_path=trace,
        catalog_output=json.dumps(changed_catalog),
    )
    with pytest.raises(CodexCliError) as error:
        _executor(changed, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="developer",
            user_prompt="user",
        )
    assert error.value.failure_code == "tool_surface_unknown"
    assert not trace.exists()

    for case in (
        "missing_required_field",
        "wrong_scalar_type",
        "wrong_nested_type",
        "wrong_reasoning_preset",
        "wrong_truncation_policy",
        "wrong_service_tier",
    ):
        malformed = _catalog()
        descriptor = malformed["models"][0]
        if case == "missing_required_field":
            descriptor.pop("description")
        elif case == "wrong_scalar_type":
            descriptor["context_window"] = "128000"
        elif case == "wrong_nested_type":
            descriptor["supported_reasoning_levels"] = ["low", "medium"]
        elif case == "wrong_reasoning_preset":
            descriptor["supported_reasoning_levels"] = [
                {"effort": False, "unknown_tool": True}
            ]
        elif case == "wrong_truncation_policy":
            descriptor["truncation_policy"] = {"mode": ["bytes"], "unknown": 1}
        else:
            descriptor["service_tiers"] = [{"id": "fast", "unknown_tool": True}]
        malformed_binary = _fake_cli(
            tmp_path / f"codex-{case}",
            trace_path=trace,
            catalog_output=json.dumps(malformed),
        )
        with pytest.raises(CodexCliError) as error:
            _executor(malformed_binary, home=home).execute(
                model="gpt-5.6-luna",
                reasoning_effort="low",
                developer_instructions="developer",
                user_prompt="user",
            )
        assert error.value.failure_code == "tool_surface_unknown"
        assert not trace.exists()


def test_requested_reasoning_effort_must_be_declared_by_selected_model(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "unsupported-effort-trace.json"
    binary = _fake_cli(tmp_path / "codex", trace_path=trace)

    with pytest.raises(CodexCliError) as error:
        _executor(binary, home=home).execute(
            model="gpt-5.6-luna",
            reasoning_effort="ultra",
            developer_instructions="developer",
            user_prompt="user",
        )

    assert error.value.failure_code == "model_unavailable"
    assert not trace.exists()


def test_cli_self_replacement_is_confined_to_staged_snapshot(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        replace_self_during_catalog=True,
    )

    result = _executor(binary, home=home).execute(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        developer_instructions="developer",
        user_prompt="user",
    )

    assert result.response_text == '{"answer":"ok"}'
    assert json.loads(trace.read_text(encoding="utf-8"))["pid"] > 0
    assert "args = sys.argv[1:]" in binary.read_text(encoding="utf-8")


def test_cli_snapshot_preserves_install_bin_context(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "trace.json"
    binary = _fake_cli(tmp_path / "codex", trace_path=trace)

    _executor(binary, home=home).execute(
        model="gpt-5.6-luna",
        reasoning_effort="low",
        developer_instructions="developer",
        user_prompt="user",
    )

    invocation = json.loads(trace.read_text(encoding="utf-8"))
    assert invocation["executable_directory"] == str(binary.parent)


def test_verified_open_executable_snapshot_survives_path_replacement(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "codex"
    replacement = tmp_path / "codex.replacement"
    executable.write_text(f"#!{sys.executable}\nprint('original')\n", encoding="utf-8")
    replacement.write_text(
        f"#!{sys.executable}\nprint('replacement')\n", encoding="utf-8"
    )
    executable.chmod(0o700)
    replacement.chmod(0o700)
    fd = os.open(executable, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    opened = os.fstat(fd)
    expected_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    )
    os.replace(replacement, executable)
    staged = tmp_path / "staged-codex"
    try:
        with pytest.raises(ValueError):
            _clone_or_copy_descriptor(fd, expected_identity, staged)
        expected_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            os.fstat(fd).st_ctime_ns,
        )
        _clone_or_copy_descriptor(fd, expected_identity, staged)
    finally:
        os.close(fd)

    result = subprocess.run(
        [str(staged)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "original"


def test_local_bridge_timeout_kills_codex_process_group(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "slow-cli.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        execution_delay_seconds=5,
        spawn_child=True,
    )
    adapter = _subscription_bridge_adapter(
        binary=binary,
        home=home,
        profile=_profile_file(tmp_path / "bridge-profile.json"),
        timeout_seconds=2,
        adapter_id="codex_subscription-timeout-test",
    )

    with pytest.raises(AdapterExecutionError) as error:
        _run_bridge(adapter)
    assert error.value.failure_class == "command_timeout"
    invocation = json.loads(trace.read_text(encoding="utf-8"))
    _assert_pids_exit(invocation["pid"], invocation["child_pid"])


def test_bridge_crash_cleans_codex_and_descendant_after_bridge_exits(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    trace = tmp_path / "crashing-cli.json"
    binary = _fake_cli(
        tmp_path / "codex",
        trace_path=trace,
        execution_delay_seconds=30,
        spawn_child=True,
        crash_parent=True,
    )
    adapter = _subscription_bridge_adapter(
        binary=binary,
        home=home,
        profile=_profile_file(tmp_path / "crash-profile.json"),
        timeout_seconds=5,
        adapter_id="codex_subscription-crash-test",
    )

    with pytest.raises(AdapterExecutionError):
        _run_bridge(adapter)

    invocation = json.loads(trace.read_text(encoding="utf-8"))
    _assert_pids_exit(invocation["pid"], invocation["child_pid"])


def test_unimplemented_product_tools_are_not_advertised() -> None:
    descriptor = ModelAccessAdapterFactory.from_declared_sources().describe(
        "codex_cli", provider="openai", model="gpt-5.6-luna"
    )

    assert descriptor.supported_capabilities.native_tools is False


def test_codex_cli_does_not_claim_literal_system_role(tmp_path: Path) -> None:
    with pytest.raises(CodexCliError) as error:
        CodexCliExecutor(
            safe_profile_path=_profile_file(tmp_path / "profile.json")
        ).execute(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            developer_instructions="trusted",
            user_prompt="user",
            literal_system_role_required=True,
        )
    assert error.value.failure_code == "unsupported_profile"
