from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONSUMER = ROOT / "app/dispatcher/verification_consumer.py"
LOOP = ROOT / "app/dispatcher/verification_agent_loop.py"
CI = ROOT / ".github/workflows/ci.yml"


def test_consumer_delegates_all_mutation_authority_to_verification_skill() -> None:
    text = CONSUMER.read_text(encoding="utf-8")
    assert ".codex/skills/verification-and-closure/SKILL.md" in text
    assert ".codex/agents/verification-closer.toml" in text
    for forbidden in ("gh pr merge", "gh issue close", "agent:ready", "agent:blocked"):
        assert forbidden not in text


def test_agent_execution_is_host_local_not_github_actions() -> None:
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github/workflows").glob("*.y*ml")
    )
    assert "verification_consumer" not in workflow_text
    assert "codex exec --json --sandbox workspace-write" not in workflow_text
    assert "CodexExecLauncher" in CONSUMER.read_text(encoding="utf-8")


def test_chatgpt_subscription_keyring_auth_is_required() -> None:
    text = CONSUMER.read_text(encoding="utf-8")
    assert 'forced_login_method")' in text
    assert 'cli_auth_credentials_store")' in text
    assert 'mode != "chatgpt"' in text
    assert 'store != "keyring"' in text
    assert '["codex", "login", "status"]' in text
    assert '_COORDINATOR_REQUIRED_ENVIRONMENT = ("HOME", "PATH")' in text
    assert "_COORDINATOR_OPTIONAL_ENVIRONMENT" in text
    assert text.count("_coordinator_environment(os.environ)") == 2
    assert "os.environ.items()" not in text
    assert "OPENAI_API_KEY" not in text
    assert "CODEX_API_KEY" not in text
    assert "auth.json" in text  # only in the explicit never-read contract docstring
    assert "read_text" not in "\n".join(
        line for line in text.splitlines() if "auth.json" in line
    )


def test_codex_exec_contract_is_explicit_and_structured() -> None:
    text = CONSUMER.read_text(encoding="utf-8")
    for token in ('"--json"', '"--sandbox"', '"workspace-write"', '"--output-schema"'):
        assert token in text
    assert "--full-auto" not in text
    assert (ROOT / "app/dispatcher/schemas/verification_closer_receipt.schema.json").is_file()


def test_required_verification_check_runs_repo_wide_mypy() -> None:
    workflow = CI.read_text(encoding="utf-8")
    unit_job = workflow.split("name: Unit tests (not pg)", 1)[1].split(
        "  validate-context:", 1
    )[0]
    assert "Run mandatory repo-wide mypy gate" in unit_job
    assert "mypy app" in unit_job


def test_pr_wide_attempt_and_human_exception_contracts_are_durable() -> None:
    schema = (ROOT / "app/dispatcher/schema.py").read_text(encoding="utf-8")
    loop = LOOP.read_text(encoding="utf-8")
    assert "verification_attempts" in schema
    assert "verification_exceptions" in schema
    assert "standard_repair" in loop and "escalated_repair" in loop
    assert "independent re-review requires a fresh session" in loop


def test_terminal_delivery_requires_trusted_merge_and_closure_proof() -> None:
    text = CONSUMER.read_text(encoding="utf-8")
    for token in (
        "resolve_verified_merge_authority_receipt",
        "resolve_verified_merge_phase",
        "merge_commit",
        "merge_commit_closing_attempt",
        "issue_set_closure_evidence",
        "_repository_merge_closed_issues",
        "repos/{repository}/issues/events?per_page=100",
        "repository issue-events cap reached before merge coverage",
        "nodes(ids:$ids)",
        "GraphQL PullRequest closer identity mismatch",
        're.fullmatch(r"[A-Za-z0-9_-]{1,256}", node_id)',
        "observed_issue_numbers",
        "closure_evidence_incomplete",
        "unauthorized_closure",
        "_recover_merged_run",
    ):
        assert token in text
    assert 'command.extend(("-f", f"ids[]={node_id}"))' in text
    assert 'command.extend(("-F", f"ids[]={node_id}"))' not in text
    assert "issues?state=closed" not in text
