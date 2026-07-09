from __future__ import annotations

from pathlib import Path

from scripts.build_pr_evidence_pack import build_pack


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_changed_file_snapshot_paginates_all_pages() -> None:
    workflow = (REPO_ROOT / ".github/workflows/pr-evidence-pack.yml").read_text(
        encoding="utf-8"
    )

    command_start = workflow.rindex(
        "gh api --paginate",
        0,
        workflow.index('pulls/${PR_NUMBER}/files?per_page=100'),
    )
    files_snapshot_command = workflow[
        command_start : workflow.index("> pr-evidence-pack/files.json")
    ]
    assert "gh api --paginate" in files_snapshot_command
    assert "jq -s '.'" in files_snapshot_command

    files_payload = [
        {"filename": f"docs/generated/page-{index:03}.md"} for index in range(100)
    ]
    files_payload.append({"filename": "app/runtime/page-two-file.py"})

    pack = build_pack(
        pr={
            "number": 99,
            "title": "large PR",
            "body": "Closes #3239\n\n- [x] Governance lane\n\n"
            "## Owner-Doc Writeback\n"
            "- [x] No owner-doc change implied.\n",
            "head": {"sha": "abc123"},
            "base": {"ref": "main"},
        },
        files_payload=files_payload,
        checks_payload={
            "check_runs": [
                {
                    "name": "pr-contract",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
    )

    assert len(pack.changed_files) == 101
    assert "app/runtime/page-two-file.py" in pack.changed_files
    assert "runtime_or_tooling_path:app/runtime/page-two-file.py" in pack.risk_hints
