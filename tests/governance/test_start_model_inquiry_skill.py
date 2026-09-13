from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.builderops.model_inquiry_adapters import (
    OPERATIONAL_SUBSCRIPTION_MODE_ENV,
    CredentialUnavailableError,
)
from app.builderops.model_inquiry import ModelInquiryService
from app.builderops.models import BuilderOpsValidationError
import scripts.start_model_inquiry as start_model_inquiry
from scripts.start_model_inquiry import preflight_dependencies
from tests.builderops.inquiry_intent import (
    intent_env,
    provisioned_env,
    resolver_for_targets,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.sh"
PYTHON_LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.py"
SUBSCRIPTION_ADAPTER = REPO_ROOT / "scripts" / "model_inquiry_subscription_adapter.py"


def test_canonical_launcher_invokes_real_host_secret_bootstrap(
    tmp_path: Path,
) -> None:
    trace = tmp_path / "python-argv"
    fake_python = tmp_path / "python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$TRACE_FILE\"\nexit 23\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o700)

    result = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "BUILDEROPS_PYTHON": str(fake_python),
            "TRACE_FILE": str(trace),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 23
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "app.ops.host_secret_bootstrap",
        "--channel",
        "dev",
        "--consumer",
        "builderops-model-inquiry",
        "--run-on-credential-unavailable",
        "--",
        str(fake_python),
        str(PYTHON_LAUNCHER),
        "--help",
    ]


def test_local_launcher_emits_terminal_provider_error_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        start_model_inquiry,
        "preflight_dependencies",
        lambda *_args, **_kwargs: {
            "vault": "available",
            "credential_resolution": "host-secret-contract",
            "adapters": {},
        },
    )
    responses = iter(
        [
            {"inquiry": {"inquiry_id": "inq_safe"}},
            {
                "outcome": "provider_error",
                "terminal_receipt_id": "receipt_safe",
                "human_readable_report": "/safe/report.md",
                "details": {
                    "diagnostic": {
                        "adapter_id": "anthropic-safe",
                        "adapter_failure_class": "unexpected_adapter_error",
                    }
                },
            },
        ]
    )
    monkeypatch.setattr(
        start_model_inquiry,
        "_run_cli",
        lambda *_args, **_kwargs: next(responses),
    )

    payload = start_model_inquiry.launch(
        "Produce a safe failure receipt.",
        max_rounds=1,
        env={},
        repo_root=REPO_ROOT,
    )

    assert payload["final_state"] == "provider_error"
    assert payload["diagnostic"]["adapter_failure_class"] == "unexpected_adapter_error"
    assert "credential-sentinel" not in json.dumps(payload)


def test_provider_api_launcher_refuses_operational_subscription_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_preflight(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("provider preflight must not run after a mode-boundary violation")

    monkeypatch.setattr(
        start_model_inquiry,
        "preflight_dependencies",
        unexpected_preflight,
    )

    with pytest.raises(
        start_model_inquiry.LauncherError,
        match="refuses operational subscription mode",
    ):
        start_model_inquiry.launch(
            "Keep auth paths separate.",
            max_rounds=1,
            env={OPERATIONAL_SUBSCRIPTION_MODE_ENV: "1"},
            repo_root=REPO_ROOT,
        )


def _typed_credential_terminal() -> dict[str, object]:
    return {
        "schema": "builderops.model-inquiry-desktop-launch.v1",
        "inquiry_id": "inq_typed",
        "final_state": "provider_error",
        "terminal_receipt_id": "receipt_typed",
        "human_readable_report": "/safe/report.md",
        "preflight": {"vault": "available"},
        "diagnostic": {
            "adapter_id": "anthropic-claude-fable-5",
            "adapter_failure_class": "credential_unavailable",
            "credential_identity_ref": "anthropic.api-key",
        },
    }


def test_desktop_terminal_classifier_accepts_only_exact_typed_credential_failure() -> None:
    valid = _typed_credential_terminal()
    serialized = json.dumps(valid)

    assert start_model_inquiry._launcher_exit_code(valid) == 1
    assert start_model_inquiry.is_valid_desktop_terminal_response(1, serialized)
    assert not start_model_inquiry.is_valid_desktop_terminal_response(0, serialized)
    assert not start_model_inquiry.is_valid_desktop_terminal_response(2, serialized)
    assert not start_model_inquiry.is_valid_desktop_terminal_response(1, "{not-json")

    invalid_payloads: list[dict[str, object]] = []
    for missing_field in ("adapter_id", "credential_identity_ref"):
        candidate = json.loads(serialized)
        del candidate["diagnostic"][missing_field]
        invalid_payloads.append(candidate)
    for bad_adapter_id in ("", "/tmp/adapter", "adapter secret"):
        candidate = json.loads(serialized)
        candidate["diagnostic"]["adapter_id"] = bad_adapter_id
        invalid_payloads.append(candidate)
    for bad_credential_ref in ("", "/tmp/key", "credential-sentinel", "ANTHROPIC_API_KEY"):
        candidate = json.loads(serialized)
        candidate["diagnostic"]["credential_identity_ref"] = bad_credential_ref
        invalid_payloads.append(candidate)
    extra_diagnostic = json.loads(serialized)
    extra_diagnostic["diagnostic"]["adapter_exit_code"] = 1
    invalid_payloads.append(extra_diagnostic)
    wrong_final_state = json.loads(serialized)
    wrong_final_state["final_state"] = "consensus"
    invalid_payloads.append(wrong_final_state)
    extra_top_level = json.loads(serialized)
    extra_top_level["unexpected"] = "field"
    invalid_payloads.append(extra_top_level)
    for invalid_preflight in (None, "available", ["available"]):
        candidate = json.loads(serialized)
        candidate["preflight"] = invalid_preflight
        invalid_payloads.append(candidate)

    for invalid in invalid_payloads:
        assert start_model_inquiry._launcher_exit_code(invalid) == 2
        assert not start_model_inquiry.is_valid_desktop_terminal_response(
            1,
            json.dumps(invalid),
        )


def test_launcher_fails_closed_on_an_absent_declared_credential(
    tmp_path: Path,
) -> None:
    """The canonical path durably records the typed failure without a model call."""
    vault = tmp_path / "vault"
    vault.mkdir()
    question_file = tmp_path / "question.md"
    question_file.write_text("Fail closed without a declared value.", encoding="utf-8")
    provider_call_marker = tmp_path / "provider-called"
    subscription_call_marker = tmp_path / "subscription-called"
    instrumentation = tmp_path / "instrumentation"
    instrumentation.mkdir()
    (instrumentation / "sitecustomize.py").write_text(
        """
import ctypes
import os
from pathlib import Path

def _missing_keychain(*_args, **_kwargs):
    raise OSError("injected missing Keychain item")

ctypes.CDLL = _missing_keychain

try:
    import requests
except ImportError:
    pass
else:
    def _forbid_provider(*_args, **_kwargs):
        Path(os.environ["PROVIDER_CALL_MARKER"]).write_text("called", encoding="utf-8")
        raise AssertionError("provider transport was reached")
    requests.post = _forbid_provider
""",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("claude", "codex"):
        executable = fake_bin / command
        executable.write_text(
            "#!/bin/sh\nprintf called > \"$SUBSCRIPTION_CALL_MARKER\"\nexit 91\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)
    result = subprocess.run(
        [str(LAUNCHER), "--question-file", str(question_file), "--max-rounds", "1"],
        cwd=REPO_ROOT,
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONPATH": str(instrumentation),
            "PROVIDER_CALL_MARKER": str(provider_call_marker),
            "SUBSCRIPTION_CALL_MARKER": str(subscription_call_marker),
            "BUILDEROPS_PYTHON": sys.executable,
            "BUILDEROPS_DB_PATH": str(tmp_path / "builderops.sqlite3"),
            "BUILDEROPS_VAULT_ROOT": str(vault),
            **intent_env(),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["final_state"] == "provider_error"
    assert payload["diagnostic"] == {
        "adapter_id": "openai-gpt-5.6-sol",
        "adapter_failure_class": "credential_unavailable",
        "credential_identity_ref": "openai.api-key",
    }
    trace = ModelInquiryService(vault).trace(payload["inquiry_id"])
    assert trace["turns"] == []
    terminal = next(
        receipt
        for receipt in trace["receipts"]
        if receipt["event_type"] == "inquiry_run_terminal"
    )
    assert terminal["details"]["diagnostic"] == payload["diagnostic"]
    assert not provider_call_marker.exists()
    assert not subscription_call_marker.exists()
    serialized = result.stdout + result.stderr + json.dumps(trace)
    assert "ANTHROPIC_API_KEY" not in serialized
    assert "OPENAI_API_KEY" not in serialized


def test_subscription_adapter_uses_high_reasoning_profile(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("model_inquiry_subscription_adapter", SUBSCRIPTION_ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/fixtures/{name}")

    sol_argv = module.build_argv("configured-sol-model", "high")

    assert module.COMMAND_TIMEOUT_SECONDS == 1200
    assert sol_argv[sol_argv.index("-c") + 1] == 'model_reasoning_effort="high"'
    assert sol_argv[sol_argv.index("--model") + 1] == "configured-sol-model"


def test_subscription_adapter_uses_safe_timeout_exit(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("model_inquiry_subscription_adapter", SUBSCRIPTION_ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/fixtures/{name}")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(module.subprocess.TimeoutExpired(args[0], 1200)),
    )

    with pytest.raises(SystemExit) as raised:
        module.run_perspective(
            {"system_prompt": "system", "reviewed_artifact_refs": [], "phase": "draft"},
            "synthesis",
            "configured-sol-model",
            "xhigh",
            module.OUTPUT_SCHEMA_REF,
        )

    assert raised.value.code == module.TIMEOUT_EXIT_CODE


def test_subscription_adapter_preserves_invalid_provider_fields_for_runner_validation() -> None:
    spec = importlib.util.spec_from_file_location("model_inquiry_subscription_adapter", SUBSCRIPTION_ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = {
        "schema_version": "builderops.model-turn-response.v1",
        "stance": "refuse",
        "content": "I cannot complete this turn.",
        "claims": [],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": ["forged-turn"],
        "accepted_artifact_hash": None,
        "unexpected_field": "runner must reject this rather than the adapter stripping it",
    }

    assert module._response_from_text(json.dumps(response)) == response


def test_desktop_skills_route_to_macmini_launcher(tmp_path: Path) -> None:
    codex = (REPO_ROOT / ".codex/skills/start-model-inquiry/SKILL.md").read_text()
    claude = (REPO_ROOT / "claude-skills/start-model-inquiry/SKILL.md").read_text()
    for skill in (codex, claude):
        normalized_skill = " ".join(skill.split())
        for contract_field in (
            "mode-0600",
            "scripts/start_model_inquiry_workflow.py --question-file <exact-question-file>",
            "SanctionedModelInquiryWorkflow",
            "Tailscale_macmini",
            "$HOME/.local/bin/yggdrasil-model-inquiry",
            "inquiry_id",
            "final_state",
            "terminal_receipt_id",
            "human_readable_report",
            "duplicate JSON fields",
            "malformed output is ambiguous",
            "No automatic second launch",
            "/tmp/yggdrasil-model-inquiry.lock",
            "/tmp/model-inquiry-question.md",
            "Failed acquisition cannot remove the existing lock",
            "Ambiguous attempts preserve both",
            "exact-path runtime helper",
            "high-reasoning profile",
            "exit zero",
            "provider selection, subscription auth",
            "Nonzero status",
            "never a CKM credential source",
            "inq_20260730T075136Z_b73ed0da",
        ):
            assert contract_field in normalized_skill
        for required_boundary in (
            "Never invoke a generic agent runner",
            "Do not install dependencies, initialize a vault, configure adapters, provision credentials",
            "Do not inspect, modify, replace or reproduce the host-owned subscription session or bridge",
            "dormant `$HOME/.local/bin/yggdrasil-model-inquiry-provider-api` path as a substitute",
        ):
            assert required_boundary in normalized_skill
        for forbidden in (
            "scripts/start_model_inquiry.sh",
            "BUILDEROPS_VAULT_ROOT",
            "osascript",
            "AppleScript",
            "pyautogui",
            "/Applications/",
        ):
            assert forbidden not in skill

    archive = tmp_path / "start-model-inquiry.zip"
    packaged = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/package_claude_skill.py"),
            "--output",
            str(archive),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert packaged.returncode == 0, packaged.stderr
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["start-model-inquiry/SKILL.md"]
        assert bundle.read(bundle.namelist()[0]).decode() == claude


def test_manual_skill_facade_preserves_fixed_route_and_exact_question(tmp_path, monkeypatch) -> None:
    from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow
    from tests.builderops.inquiry_operation_fixture import InquiryGraph
    graph = InquiryGraph(tmp_path, monkeypatch)
    question = tmp_path / "user-owned-question.md"
    exact = "Question with ' shell ; text $HOME `unchanged` åäö\n\n".encode()
    question.write_bytes(exact)
    result = SanctionedModelInquiryWorkflow().manual(question)
    assert result["state"] == "terminal"
    assert graph.manual_question == exact and question.read_bytes() == exact
    assert graph.launches == 1 and graph.reserves == 0
    assert graph.calls[0] == ["/usr/bin/ssh", "-G", "Tailscale_macmini"]
    launcher_calls = [call for call in graph.calls if "yggdrasil-model-inquiry\" --question-file" in call[-1]]
    assert len(launcher_calls) == 1 and launcher_calls[0][-1] == '"$HOME/.local/bin/yggdrasil-model-inquiry" --question-file /tmp/model-inquiry-question.md'
    assert not graph.lock.exists() and not graph.stage.exists()
    # The documented direct script boot does not depend on the caller's cwd.
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    help_result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts/start_model_inquiry_workflow.py"), "--help"], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert help_result.returncode == 0 and "--question-file" in help_result.stdout


def test_workflow_local_route_requires_complete_host_proof(monkeypatch) -> None:
    from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow
    real_is_file, real_read_text = Path.is_file, Path.read_text
    key_path = Path("/etc/ssh/ssh_host_ed25519_key.pub")
    monkeypatch.setattr(Path, "is_file", lambda path: True if path == key_path else real_is_file(path))
    monkeypatch.setattr(Path, "read_text", lambda path, *args, **kwargs: "ssh-ed25519 exact-public-test-key" if path == key_path else real_read_text(path, *args, **kwargs))
    state = {"home": str(Path.home()), "key": "exact-public-test-key"}
    calls = []
    def process(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["/usr/bin/ssh", "-G"]:
            raw = "user fixture-user\nhostname fixed-host\nuserknownhostsfile /fixture/known_hosts\n"
        elif argv == ["/usr/bin/id", "-un"]:
            raw = "fixture-user\n"
        elif argv[0] == "/usr/bin/dscl":
            raw = "NFSHomeDirectory: " + state["home"]
        elif argv[0] == "/usr/bin/ssh-keygen":
            raw = "fixed-host ssh-ed25519 " + state["key"]
        else:
            raise AssertionError(argv)
        return subprocess.CompletedProcess(argv, 0, raw.encode(), b"")
    monkeypatch.setattr(SanctionedModelInquiryWorkflow, "_process", staticmethod(process))
    assert SanctionedModelInquiryWorkflow()._route() is True
    state["key"] = "mismatched-public-key"
    assert SanctionedModelInquiryWorkflow()._route() is False
    state["home"] = "/another/home"
    assert SanctionedModelInquiryWorkflow()._route() is False
    assert not any("yggdrasil-model-inquiry" in argument for call in calls for argument in call)


@pytest.mark.parametrize("outcome", ["malformed", "nonzero", "empty", "prefix", "duplicate", "timeout", "existing_lock", "existing_stage"])
def test_facade_cleanup_preserves_ambiguous_recovery_state(tmp_path, monkeypatch, outcome) -> None:
    from app.builderops.model_inquiry_workflow import SanctionedModelInquiryWorkflow, canonical_bytes
    from tests.builderops.inquiry_operation_fixture import InquiryGraph
    graph = InquiryGraph(tmp_path, monkeypatch)
    question = tmp_path / "user-question.md"
    question.write_text("Keep the exact question.\n")
    if outcome == "existing_lock":
        graph.lock.mkdir()
        graph.stage.write_text("protected existing question")
    elif outcome == "existing_stage":
        graph.stage.write_text("protected existing question")
    else:
        def response(argv, value):
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(argv, 1)
            raw = {"malformed": b"[]", "nonzero": canonical_bytes(value), "empty": b"", "prefix": b"prefix " + canonical_bytes(value), "duplicate": b'{"inquiry_id":"one","inquiry_id":"two"}'}[outcome]
            return subprocess.CompletedProcess(argv, 1 if outcome == "nonzero" else 0, raw, b"")
        graph.manual_response = response
    result = SanctionedModelInquiryWorkflow().manual(question)
    assert question.exists()
    assert graph.stage.exists()
    if outcome in {"existing_lock", "existing_stage"}:
        assert graph.launches == 0 and graph.stage.read_text() == "protected existing question"
        assert graph.lock.exists() is (outcome == "existing_lock")
    else:
        assert result["state"] == "ambiguous" and graph.lock.exists()
        assert result["workflow_cleanup"] == "preserved_for_reconciliation" and graph.launches == 1


def test_skill_preflight_reports_missing_dependencies(tmp_path: Path) -> None:
    clean_env = {
        "PATH": os.environ["PATH"],
        "BUILDEROPS_PYTHON": sys.executable,
        "BUILDEROPS_DB_PATH": str(tmp_path / "builderops.sqlite3"),
    }
    missing_vault = subprocess.run(
        [sys.executable, str(PYTHON_LAUNCHER), "Question"],
        cwd=REPO_ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_vault.returncode == 2
    assert "BUILDEROPS_VAULT_ROOT is required" in missing_vault.stderr

    vault = tmp_path / "vault"
    vault.mkdir()
    missing_adapters = subprocess.run(
        [sys.executable, str(PYTHON_LAUNCHER), "Question"],
        cwd=REPO_ROOT,
        env={**clean_env, "BUILDEROPS_VAULT_ROOT": str(vault)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_adapters.returncode == 2
    assert "inquiry intent is not configured" in missing_adapters.stderr
    assert not (vault / "model-inquiries").exists()

    missing_credential = subprocess.run(
        [sys.executable, str(PYTHON_LAUNCHER), "Question"],
        cwd=REPO_ROOT,
        env={
            **clean_env,
            "BUILDEROPS_VAULT_ROOT": str(vault),
            **intent_env(),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_credential.returncode == 2
    assert "openai.api-key" in missing_credential.stderr
    assert not (vault / "model-inquiries").exists()


def test_desktop_preflight_resolves_declared_roles_without_a_session(
    tmp_path: Path,
) -> None:
    """Preflight needs no host role entrypoint, provider CLI, or session lineage."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {
        **os.environ,
        "PATH": str(bin_dir),
        "BUILDEROPS_DB_PATH": str(tmp_path / "builderops.sqlite3"),
        "BUILDEROPS_VAULT_ROOT": str(vault),
        **provisioned_env(tmp_path / "secrets"),
    }

    result = preflight_dependencies(env, command_cwd=REPO_ROOT)

    assert set(result["adapters"]) == {"synthesis", "verification"}
    assert result["credential_resolution"] == "host-secret-contract"
    assert {identity["provider"] for identity in result["adapters"].values()} == {
        "openai",
    }
    assert not (vault / "model-inquiries").exists()
    assert not list(bin_dir.iterdir())

    # A mock policy target is refused rather than silently substituted, and a
    # declared credential that is absent fails closed instead of degrading.
    with pytest.raises(CredentialUnavailableError, match="openai.api-key"):
        preflight_dependencies(
            {key: value for key, value in env.items() if "HOST_SECRET" not in key},
            command_cwd=REPO_ROOT,
        )
    mocked_resolver = resolver_for_targets(
        tmp_path / "mock-resolver",
        {"fable": ("mock", "mock-chat"), "gpt_codex": ("mock", "mock-chat")},
    )
    with pytest.raises(BuilderOpsValidationError, match="mock"):
        preflight_dependencies(
            env,
            command_cwd=REPO_ROOT,
            resolver=mocked_resolver,
        )


def _run_host_installer(
    tmp_path: Path,
    bin_dir: Path,
    *,
    python: Path = Path(sys.executable),
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "install_model_inquiry_host.py"),
            "install",
            "--repo-root",
            str(REPO_ROOT),
            "--bin-dir",
            str(bin_dir),
            "--python",
            str(python),
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "BUILDEROPS_DB_PATH": str(tmp_path / "unused.sqlite3")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_launcher_fails_loud_without_venv_or_override(tmp_path: Path) -> None:
    # Isolated copy so venv walk-up can't discover this checkout's real .venv,
    # proving the fail-loud path holds when BUILDEROPS_PYTHON is unset.
    isolated_scripts = tmp_path / "isolated" / "scripts"
    isolated_lib = isolated_scripts / "lib"
    isolated_lib.mkdir(parents=True)
    launcher_copy = isolated_scripts / "start_model_inquiry.sh"
    launcher_copy.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    launcher_copy.chmod(0o755)
    (isolated_lib / "resolve_repo_python.sh").write_text(
        (REPO_ROOT / "scripts" / "lib" / "resolve_repo_python.sh").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(launcher_copy), "--help"],
        cwd=isolated_scripts.parent,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert (
        "Model inquiry launch requires the repo virtualenv" in result.stderr
    ), result.stderr


def test_launcher_fails_loud_with_invalid_override(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-python"
    bogus.write_text("not executable", encoding="utf-8")

    result = subprocess.run(
        [str(LAUNCHER), "--help"],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "BUILDEROPS_PYTHON": str(bogus)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "BUILDEROPS_PYTHON is set to" in result.stderr
    assert "not an executable file" in result.stderr
