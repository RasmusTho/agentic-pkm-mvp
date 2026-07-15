from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.build_pr_evidence_pack import build_pack, render_markdown


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pr_body(owner_doc_line: str = "- [x] No owner-doc change implied.") -> str:
    return f"""Governing-Issue: #3214

Closes #3214

- [x] Governance lane

## Owner-Doc Writeback
{owner_doc_line}

## BuilderOps Routing
- Records/projections/receipts: none
- Reason: represented by issue and PR
"""


def _clean_pack():
    return build_pack(
        pr={
            "number": 99,
            "title": "automation: add PR evidence pack builder",
            "body": _pr_body(),
            "head": {"sha": "abc123"},
            "base": {"ref": "main"},
        },
        files_payload=[
            {"filename": "scripts/build_pr_evidence_pack.py"},
            {"filename": "tests/scripts/test_build_pr_evidence_pack.py"},
        ],
        checks_payload={
            "check_runs": [
                {"name": "pr-contract", "status": "completed", "conclusion": "success"},
                {"name": "Unit tests (not pg)", "status": "completed", "conclusion": "success"},
            ]
        },
        issue={"state": "open", "labels": [{"name": "agent:ready"}, {"name": "prio:high"}]},
    )


def test_pack_builder_emits_markdown_and_json(tmp_path: Path) -> None:
    pr_json = tmp_path / "pr.json"
    files_json = tmp_path / "files.json"
    checks_json = tmp_path / "checks.json"
    issue_json = tmp_path / "issue.json"
    out_json = tmp_path / "evidence.json"
    out_md = tmp_path / "evidence.md"

    pr_json.write_text(
        json.dumps(
            {
                "number": 99,
                "title": "automation: add PR evidence pack builder",
                "body": _pr_body(),
                "head": {"sha": "abc123"},
                "base": {"ref": "main"},
            }
        ),
        encoding="utf-8",
    )
    files_json.write_text(
        json.dumps([{"filename": "scripts/build_pr_evidence_pack.py"}]),
        encoding="utf-8",
    )
    checks_json.write_text(
        json.dumps({"check_runs": [{"name": "pr-contract", "status": "completed", "conclusion": "success"}]}),
        encoding="utf-8",
    )
    issue_json.write_text(
        json.dumps({"state": "open", "labels": [{"name": "agent:ready"}]}),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.build_pr_evidence_pack",
            "--pr-json",
            str(pr_json),
            "--files-json",
            str(files_json),
            "--checks-json",
            str(checks_json),
            "--issue-json",
            str(issue_json),
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
    assert payload["pr_number"] == 99
    assert payload["linked_issues"] == [3214]
    assert payload["lane_classification"] == "governance"
    assert payload["pr_contract_status"] == "success"
    assert payload["owner_doc_writeback_declaration"] == "no_owner_doc_change"
    assert "# PR Evidence Pack" in markdown


def test_evidence_pack_fixture_matrix(tmp_path: Path) -> None:
    clean = _clean_pack()
    assert clean.failing_checks == []
    assert clean.human_exception_required is False

    failing = build_pack(
        pr={
            "number": 99,
            "title": "failure",
            "body": _pr_body(),
            "head": {"sha": "abc123"},
            "base": {"ref": "main"},
        },
        files_payload=[{"filename": "scripts/build_pr_evidence_pack.py"}],
        checks_payload={
            "check_runs": [
                {"name": "pr-contract", "status": "completed", "conclusion": "failure"},
            ]
        },
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
    )
    assert failing.failing_checks[0].name == "pr-contract"
    assert failing.pr_contract_status == "failure"

    missing_issue = build_pack(
        pr={"number": 100, "title": "missing", "body": "", "head": {}, "base": {}},
        files_payload=[],
        checks_payload={},
        issue={},
    )
    assert "linked issue not found in PR body" in missing_issue.unknowns_missing_evidence

    owner_doc = build_pack(
        pr={
            "number": 101,
            "title": "owner doc",
            "body": _pr_body("- [x] Owner-doc updated in this PR."),
            "head": {},
            "base": {},
        },
        files_payload=[{"filename": "docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"}],
        checks_payload={"check_runs": []},
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
    )
    assert owner_doc.owner_doc_writeback_declaration == "owner_doc_updated"

    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text("docker-compose.prod.yml @RasmusTho\n", encoding="utf-8")
    authority_risk = build_pack(
        pr={
            "number": 102,
            "title": "authority",
            "body": _pr_body(),
            "head": {},
            "base": {},
        },
        files_payload=[{"filename": "docker-compose.prod.yml"}],
        checks_payload={"check_runs": []},
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
        codeowners_path=codeowners,
    )
    assert authority_risk.human_exception_required is True
    assert authority_risk.risk_hints == ["codeowner_required:docker-compose.prod.yml:@RasmusTho"]


def test_evidence_pack_uses_canonical_closing_keyword_variants() -> None:
    pack = build_pack(
        pr={
            "number": 102,
            "title": "variant",
            "body": _pr_body().replace("Closes #3214", "Fixed: #3214"),
            "head": {"sha": "abc123"},
            "base": {"ref": "main"},
        },
        files_payload=[{"filename": "app/runtime.py"}],
        checks_payload={"check_runs": []},
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
    )

    assert pack.linked_issues == [3214]


def test_missing_data_is_reported_as_unknown_not_guessed() -> None:
    pack = build_pack(
        pr={"number": 99, "title": "unknown", "body": "", "head": {}, "base": {}},
        files_payload=[],
        checks_payload={},
        issue={},
    )

    assert pack.linked_issues == []
    assert pack.issue_readiness_state == "unknown"
    assert pack.pr_contract_status == "unknown"
    assert "check run evidence unavailable" in pack.unknowns_missing_evidence


def test_human_exception_requires_observed_exception_evidence(tmp_path: Path) -> None:
    normal = _clean_pack()
    assert normal.human_exception_required is False

    codeowners = tmp_path / "CODEOWNERS"
    codeowners.write_text(".github/workflows/ @RasmusTho\n", encoding="utf-8")
    risky = build_pack(
        pr={
            "number": 99,
            "title": "workflow",
            "body": _pr_body(),
            "head": {},
            "base": {},
        },
        files_payload=[{"filename": ".github/workflows/deploy.yml"}],
        checks_payload={"check_runs": []},
        issue={"state": "open", "labels": [{"name": "agent:ready"}]},
        codeowners_path=codeowners,
    )

    assert risky.human_exception_required is True
    assert "workflow_authority_path:.github/workflows/deploy.yml" in risky.risk_hints


def test_markdown_distinguishes_facts_and_unknowns() -> None:
    markdown = render_markdown(_clean_pack())

    assert "## Unknowns / Missing Evidence" in markdown
    assert "## Risk Hints" in markdown
