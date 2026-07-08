from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.build_branch_guardrail_packet import build_packet, render_markdown


REPO_ROOT = Path(__file__).resolve().parents[2]


CHECK_RUNS = {
    "check_runs": [
        {"name": "pr-contract", "workflow_name": "Issue and PR Governance", "conclusion": "success"},
        {"name": "Unit tests (not pg)", "workflow_name": "CI", "conclusion": "success"},
        {"name": "import-linter", "workflow_name": "import-linter", "conclusion": "success"},
        {"name": "smoke", "workflow_name": "CI Smoke", "conclusion": "success"},
        {"name": "smoke-docker", "workflow_name": "CI Smoke", "conclusion": "success"},
        {"name": "CodeQL", "workflow_name": "CodeQL", "conclusion": "success"},
    ]
}


def test_guardrail_packet_records_main_protection_state(tmp_path: Path) -> None:
    repo_json = tmp_path / "repo.json"
    checks_json = tmp_path / "checks.json"
    out_json = tmp_path / "guardrail.json"
    out_md = tmp_path / "guardrail.md"

    repo_json.write_text(json.dumps({"allow_auto_merge": False}), encoding="utf-8")
    checks_json.write_text(json.dumps(CHECK_RUNS), encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "scripts/build_branch_guardrail_packet.py",
            "--repo-json",
            str(repo_json),
            "--main-protection-status",
            "404",
            "--check-runs-json",
            str(checks_json),
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
    assert payload["branch_protection_active"] is False
    assert "main branch protection is not active" in payload["unresolved_blockers"]
    assert "# Branch Guardrail Packet" in markdown


def test_guardrail_packet_records_repo_auto_merge_state() -> None:
    packet = build_packet(
        repo={"allow_auto_merge": False},
        main_protection={},
        main_protection_status=404,
        check_runs_payload=CHECK_RUNS,
    )

    assert packet.repo_auto_merge_allowed is False
    assert "repository auto-merge is disabled" in packet.unresolved_blockers


def test_required_checks_cite_observed_workflow_evidence() -> None:
    packet = build_packet(
        repo={"allow_auto_merge": True},
        main_protection={"required_status_checks": {}},
        main_protection_status=200,
        check_runs_payload=CHECK_RUNS,
    )

    assert packet.required_checks_selected == [
        "pr-contract",
        "Unit tests (not pg)",
        "import-linter",
        "smoke",
        "smoke-docker",
        "CodeQL",
    ]
    assert any(check.workflow_name == "CI" for check in packet.observed_check_evidence)


def test_guardrail_workflow_does_not_enable_pr_auto_merge_or_merge() -> None:
    packet = build_packet(
        repo={"allow_auto_merge": False},
        main_protection={},
        main_protection_status=404,
        check_runs_payload=CHECK_RUNS,
    )

    assert packet.no_pr_merged is True
    assert packet.no_existing_pr_auto_merge_enabled is True
    assert "Do not enable auto-merge on any existing pull request." in packet.exact_admin_settings_required


def test_human_exception_packet_contains_exact_admin_settings() -> None:
    packet = build_packet(
        repo={"allow_auto_merge": False},
        main_protection={},
        main_protection_status=404,
        check_runs_payload=CHECK_RUNS,
    )
    markdown = render_markdown(packet)

    assert packet.human_exception_required is True
    assert "Protect `main`" in markdown
    assert "Set required status checks for `main`" in markdown
    assert "Enable repository auto-merge only after `main` protection is active." in markdown
