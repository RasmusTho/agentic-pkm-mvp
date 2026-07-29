from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.builderops.model_inquiry_adapters import CredentialUnavailableError
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


def test_launcher_fails_closed_on_an_absent_declared_credential(
    tmp_path: Path,
) -> None:
    """The reported failure class is the credential, never a session or CLI exit."""
    vault = tmp_path / "vault"
    vault.mkdir()
    question_file = tmp_path / "question.md"
    question_file.write_text("Fail closed without a declared value.", encoding="utf-8")
    result = subprocess.run(
        [str(LAUNCHER), "--question-file", str(question_file), "--max-rounds", "1"],
        cwd=REPO_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "BUILDEROPS_PYTHON": sys.executable,
            "BUILDEROPS_DB_PATH": str(tmp_path / "builderops.sqlite3"),
            "BUILDEROPS_VAULT_ROOT": str(vault),
            **intent_env(),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert "anthropic.api-key" in result.stderr
    assert "ANTHROPIC_API_KEY" not in result.stderr
    assert not (vault / "model-inquiries").exists()


def test_subscription_adapter_uses_high_reasoning_profile(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("model_inquiry_subscription_adapter", SUBSCRIPTION_ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/fixtures/{name}")

    fable_argv = module.build_argv("fable", "system prompt")
    codex_argv = module.build_argv("gpt_codex", "system prompt")

    assert module.COMMAND_TIMEOUT_SECONDS == 1200
    assert fable_argv[fable_argv.index("--effort") + 1] == "xhigh"
    assert codex_argv[codex_argv.index("-c") + 1] == 'model_reasoning_effort="xhigh"'


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
        module.run_role(
            {"system_prompt": "system", "reviewed_artifact_refs": [], "phase": "draft"},
            "fable",
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
        for contract_field in (
            "mode `0600`",
            "scp \"$QUESTION_FILE\" Tailscale_macmini:/tmp/model-inquiry-question.md",
            "ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'",
            "inquiry_id",
            "final_state",
            "terminal_receipt_id",
            "human_readable_report",
            "empty stdout",
            "malformed JSON",
            "Do not re-run the inquiry",
            "single-flight operation",
            "mkdir /tmp/yggdrasil-model-inquiry.lock",
            "rm -f /tmp/model-inquiry-question.md; rmdir /tmp/yggdrasil-model-inquiry.lock",
            "Do not remove an existing lock",
            "Do not register remote lock release until the launch outcome is known",
            "Do not release the remote lock after an ambiguous launcher outcome",
            "high-reasoning profile",
        ):
            assert contract_field in skill
        for required_boundary in (
            "Do not run local BuilderOps, Python, Codex, or Claude commands",
            "Do not install dependencies, run vault-init, configure adapters, or provision API keys.",
            "host-secret bootstrap",
        ):
            assert required_boundary in skill
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
    assert "inquiry role intent is not configured" in missing_adapters.stderr
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
    assert "anthropic.api-key" in missing_credential.stderr
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

    assert set(result["adapters"]) == {"fable", "gpt_codex"}
    assert result["credential_resolution"] == "host-secret-contract"
    assert {identity["provider"] for identity in result["adapters"].values()} == {
        "anthropic",
        "openai",
    }
    assert not (vault / "model-inquiries").exists()
    assert not list(bin_dir.iterdir())

    # A mock policy target is refused rather than silently substituted, and a
    # declared credential that is absent fails closed instead of degrading.
    with pytest.raises(CredentialUnavailableError, match="anthropic.api-key"):
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
