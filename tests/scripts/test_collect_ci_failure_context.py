from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.collect_ci_failure_context import LogSource, build_context


REPO_ROOT = Path(__file__).resolve().parents[2]


def _context_for(text: str, *, pr_number: int | None = 42, name: str = "job/step.txt"):
    return build_context(
        repository="RasmusTho/agentic-pkm-mvp",
        run_id="123456",
        sources=[LogSource(name=name, text=text)],
        pr_number=pr_number,
        head_sha="abc123",
        base_branch="main" if pr_number is not None else None,
        workflow_name="CI Smoke",
        check_name="smoke",
    )


@pytest.mark.parametrize(
    ("text", "expected_class", "owner"),
    [
        (
            "Run pytest -q tests/scripts/test_collect_ci_failure_context.py\n"
            "FAILED tests/scripts/test_collect_ci_failure_context.py::test_pytest_case\n"
            "E   AssertionError: expected compact context\n",
            "pytest_failure",
            "tests/scripts/test_collect_ci_failure_context.py::test_pytest_case",
        ),
        (
            "Run ruff check scripts/collect_ci_failure_context.py\n"
            "scripts/collect_ci_failure_context.py:12:1: F401 `os` imported but unused\n",
            "ruff_failure",
            "scripts/collect_ci_failure_context.py",
        ),
        (
            "pr-contract\n"
            "Error: PR body must include `## BuilderOps Routing` with concrete fields.\n",
            "governance_pr_contract_failure",
            None,
        ),
        (
            "Run lint-imports --config importlinter.ini\n"
            "Import Linter\n"
            "Broken contracts:\n"
            "Layered architecture imports app.api from app.memory\n",
            "import_boundary_failure",
            "importlinter.ini",
        ),
        (
            "The operation was canceled.\n"
            "Error: The job running on runner GitHub Actions 2 timed out after 22 minutes.\n",
            "timeout_or_infra",
            None,
        ),
        (
            "Run ./custom-check\n"
            "Something unexpected happened without a known signature.\n",
            "unknown_failure",
            None,
        ),
    ],
)
def test_failure_kind_fixtures_are_classified_stably(
    text: str, expected_class: str, owner: str | None
) -> None:
    context = _context_for(text)

    assert context.failure_class == expected_class
    assert context.suspected_owner_script_or_test_file == owner
    assert context.first_useful_failure_block
    assert context.safe_next_action


def test_collector_emits_json_and_markdown_for_failed_run_fixture(tmp_path: Path) -> None:
    log_zip = tmp_path / "logs.zip"
    event_json = tmp_path / "event.json"
    out_json = tmp_path / "context.json"
    out_md = tmp_path / "context.md"

    with zipfile.ZipFile(log_zip, "w") as archive:
        archive.writestr(
            "Unit tests (not pg)/Run not-pg unit tests.txt",
            "Run pytest -q -m \"not pg\"\n"
            "FAILED tests/scripts/test_collect_ci_failure_context.py::test_fixture\n"
            "E   AssertionError: expected artifact context\n",
        )
    event_json.write_text(
        json.dumps(
            {
                "repository": {"full_name": "RasmusTho/agentic-pkm-mvp"},
                "workflow_run": {
                    "id": 98765,
                    "name": "CI",
                    "head_sha": "deadbeef",
                    "pull_requests": [{"number": 3213, "base": {"ref": "main"}}],
                },
            }
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/collect_ci_failure_context.py",
            "--event-json",
            str(event_json),
            "--log-zip",
            str(log_zip),
            "--output-json",
            str(out_json),
            "--output-markdown",
            str(out_md),
        ],
        cwd=REPO_ROOT,
        check=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    markdown = out_md.read_text(encoding="utf-8")
    assert payload["repository"] == "RasmusTho/agentic-pkm-mvp"
    assert payload["pr_number"] == 3213
    assert payload["head_sha"] == "deadbeef"
    assert payload["base_branch"] == "main"
    assert payload["failure_class"] == "pytest_failure"
    assert payload["actionable_by_autonomous_repair"] is True
    assert payload["human_exception_required"] is False
    assert "FAILED tests/scripts/test_collect_ci_failure_context.py::test_fixture" in markdown


def test_run_without_pr_mapping_records_unknowns() -> None:
    context = _context_for(
        "Run ruff check scripts/collect_ci_failure_context.py\n"
        "scripts/collect_ci_failure_context.py:20:1: F401 unused import\n",
        pr_number=None,
    )

    assert context.pr_number is None
    assert context.base_branch is None
    assert context.appears_caused_by_pr == "unknown"
    assert "PR mapping unavailable from workflow_run payload" in context.unknowns_missing_evidence
    assert "base branch unavailable" in context.unknowns_missing_evidence


def test_command_only_successful_steps_do_not_drive_failure_classification() -> None:
    context = build_context(
        repository="RasmusTho/agentic-pkm-mvp",
        run_id="123456",
        sources=[
            LogSource(name="smoke/Lint.txt", text="Run ruff check app tests\n"),
            LogSource(name="import-linter/Lint imports.txt", text="Run lint-imports --config importlinter.ini\n"),
            LogSource(
                name="tests/Run tests.txt",
                text=(
                    "Run pytest -q\n"
                    "Something unexpected happened without a known signature.\n"
                ),
            ),
        ],
        pr_number=42,
        head_sha="abc123",
        base_branch="main",
        workflow_name="CI Smoke",
    )

    assert context.failure_class == "unknown_failure"
    assert "Something unexpected happened" in context.first_useful_failure_block


def test_comment_mode_uses_stable_marker_when_enabled() -> None:
    workflow = (REPO_ROOT / ".github/workflows/pr-ci-failure-context.yml").read_text(
        encoding="utf-8"
    )

    assert "issues: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "github.rest.issues.createComment" not in workflow
    assert "<!-- ci-failure-context" not in workflow
