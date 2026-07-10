from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from app.builderops.model_inquiry import ModelInquiryService

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.sh"
PYTHON_LAUNCHER = REPO_ROOT / "scripts" / "start_model_inquiry.py"


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
        "BUILDEROPS_VAULT_ROOT": str(vault),
        "BUILDEROPS_INQUIRY_ADAPTERS_JSON": json.dumps(config),
    }


def test_codex_skill_calls_common_command(tmp_path: Path) -> None:
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
    assert not marker.exists()
    trace = ModelInquiryService.from_env(env).trace(payload["inquiry_id"])
    assert trace["question"]["content"] == question
    assert trace["question"]["source_refs"] == [
        {"ref_type": "desktop_skill", "ref": "start-model-inquiry"}
    ]
    skill = (REPO_ROOT / ".codex/skills/start-model-inquiry/SKILL.md").read_text()
    launcher = PYTHON_LAUNCHER.read_text()
    assert "scripts/start_model_inquiry.sh" in skill
    assert '"builderops",\n                "inquiry",\n                "start"' in launcher


def test_claude_package_uses_common_launcher_contract(tmp_path: Path) -> None:
    codex = (REPO_ROOT / ".codex/skills/start-model-inquiry/SKILL.md").read_text()
    claude = (REPO_ROOT / "claude-skills/start-model-inquiry/SKILL.md").read_text()
    for contract_field in (
        "scripts/start_model_inquiry.sh",
        "inquiry_id",
        "final_state",
        "terminal_receipt_id",
    ):
        assert contract_field in codex
        assert contract_field in claude
    for forbidden in ("osascript", "AppleScript", "pyautogui", "/Applications/"):
        assert forbidden not in claude
    assert "set that resolved path as `REPO_ROOT`" in claude
    assert '"$REPO_ROOT/scripts/start_model_inquiry.sh"' in claude
    assert '"$AGENTIC_PKM_REPO_ROOT/scripts/start_model_inquiry.sh"' not in claude

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
    clean_env = {"PATH": os.environ["PATH"], "BUILDEROPS_PYTHON": sys.executable}
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
