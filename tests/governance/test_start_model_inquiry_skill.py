from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.builderops.model_inquiry import ModelInquiryService

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.sh"
PYTHON_LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.py"
SUBSCRIPTION_ADAPTER = REPO_ROOT / "scripts" / "model_inquiry_subscription_adapter.py"


def _adapter_script(tmp_path: Path) -> Path:
    script = tmp_path / "adapter.py"
    script.write_text(
        """\
import json
import sys

request = json.load(sys.stdin)
role = sys.argv[1]
reviewed = request["reviewed_artifact_refs"]
if reviewed:
    response = {
        "schema_version": "builderops.model-turn-response.v1",
        "stance": "accept",
        "content": f"{role} accepts the shared artifact",
        "claims": ["shared contract is coherent"],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": reviewed,
        "accepted_artifact_hash": request["input_artifacts"][0]["artifact_hash"],
    }
else:
    response = {
        "schema_version": "builderops.model-turn-response.v1",
        "stance": "draft",
        "content": f"{role} independent draft",
        "claims": [f"{role} claim"],
        "risks": [],
        "blocking_questions": [],
        "reviewed_artifact_refs": [],
        "accepted_artifact_hash": None,
    }
print(json.dumps(response))
""",
        encoding="utf-8",
    )
    return script


def _configured_env(tmp_path: Path) -> dict[str, str]:
    vault = tmp_path / "vault"
    vault.mkdir()
    script = _adapter_script(tmp_path)
    config = {
        role: {
            "kind": "command",
            "role_identity": role,
            "adapter_id": f"adapter-{role}",
            "provider": role,
            "model": f"test-{role}",
            "argv": [sys.executable, str(script), role],
        }
        for role in ("fable", "gpt_codex")
    }
    return {
        **os.environ,
        "PATH": "/usr/bin:/bin",
        "BUILDEROPS_PYTHON": sys.executable,
        "BUILDEROPS_DB_PATH": str(tmp_path / "builderops.sqlite3"),
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_INQUIRY_ADAPTERS_JSON": json.dumps(config),
    }


def test_local_launcher_runs_common_command(tmp_path: Path) -> None:
    env = _configured_env(tmp_path)
    marker = tmp_path / "must-not-exist"
    question = f"Keep quotes ' and newlines safe\n$(touch {marker})"
    question_file = tmp_path / "question.md"
    question_file.write_text(question, encoding="utf-8")
    result = subprocess.run(
        [
            str(LAUNCHER),
            "--question-file",
            str(question_file),
            "--max-rounds",
            "1",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["inquiry_id"].startswith("inq_")
    assert payload["final_state"] == "consensus"
    assert payload["terminal_receipt_id"]
    report = Path(payload["human_readable_report"])
    assert report.is_file()
    assert report.parent.name == payload["inquiry_id"]
    assert not marker.exists()
    trace = ModelInquiryService.from_env(env).trace(payload["inquiry_id"])
    assert trace["question"]["content"] == question
    assert trace["question"]["source_refs"] == [
        {"ref_type": "desktop_skill", "ref": "start-model-inquiry"}
    ]
    launcher = PYTHON_LAUNCHER.read_text()
    assert '"builderops",\n                "inquiry",\n                "start"' in launcher


def test_local_launcher_emits_terminal_provider_error_json(tmp_path: Path) -> None:
    env = _configured_env(tmp_path)
    failing_adapter = tmp_path / "failing_adapter.py"
    failing_adapter.write_text(
        "import sys\nprint('credential-sentinel', file=sys.stderr)\nsys.exit(17)\n",
        encoding="utf-8",
    )
    config = json.loads(env["BUILDEROPS_INQUIRY_ADAPTERS_JSON"])
    config["fable"]["argv"] = [sys.executable, str(failing_adapter)]
    env["BUILDEROPS_INQUIRY_ADAPTERS_JSON"] = json.dumps(config)
    question_file = tmp_path / "question.md"
    question_file.write_text("Produce a safe failure receipt.", encoding="utf-8")

    result = subprocess.run(
        [str(LAUNCHER), "--question-file", str(question_file), "--max-rounds", "1"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["final_state"] == "provider_error"
    assert payload["inquiry_id"]
    assert payload["terminal_receipt_id"]
    assert Path(payload["human_readable_report"]).is_file()
    assert payload["diagnostic"] == {
        "adapter_id": "adapter-fable",
        "adapter_failure_class": "command_exit_nonzero",
        "adapter_exit_code": 17,
    }
    rendered = "".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "vault").rglob("*.json")
    )
    assert "credential-sentinel" not in rendered
    assert "credential-sentinel" not in result.stdout


def test_subscription_adapter_uses_high_reasoning_profile(monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("model_inquiry_subscription_adapter", SUBSCRIPTION_ADAPTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/fixtures/{name}")

    fable_argv = module.build_argv("fable", "system prompt")
    codex_argv = module.build_argv("gpt_codex", "system prompt")

    assert module.COMMAND_TIMEOUT_SECONDS == 540
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
        lambda *args, **kwargs: (_ for _ in ()).throw(module.subprocess.TimeoutExpired(args[0], 540)),
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
            "Do not install dependencies, run vault-init, configure adapters, or use API keys.",
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
        [str(LAUNCHER), "Question"],
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
        [str(LAUNCHER), "Question"],
        cwd=REPO_ROOT,
        env={**clean_env, "BUILDEROPS_VAULT_ROOT": str(vault)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_adapters.returncode == 2
    assert "explicit adapter not configured" in missing_adapters.stderr
    assert not (vault / "model-inquiries").exists()

    config = {
        role: {
            "kind": "command",
            "role_identity": role,
            "adapter_id": f"adapter-{role}",
            "provider": role,
            "model": f"test-{role}",
            "argv": [f"definitely-missing-{role}"],
        }
        for role in ("fable", "gpt_codex")
    }
    missing_executable = subprocess.run(
        [str(LAUNCHER), "Question"],
        cwd=REPO_ROOT,
        env={
            **clean_env,
            "BUILDEROPS_VAULT_ROOT": str(vault),
            "BUILDEROPS_INQUIRY_ADAPTERS_JSON": json.dumps(config),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_executable.returncode == 2
    assert "local command unavailable" in missing_executable.stderr
    assert not (vault / "model-inquiries").exists()


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
