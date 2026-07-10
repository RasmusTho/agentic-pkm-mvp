from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_active_pickup_contract_is_label_only() -> None:
    agents = _read("AGENTS.md")
    issue_to_code = _read(".codex/skills/issue-to-code/SKILL.md")
    deliver_issue_set = _read(".codex/skills/deliver-issue-set/SKILL.md")
    dev_workflow = _read("docs/development/DEV_WORKFLOW.md")
    labels = _read(".codex/skills/_shared/LABEL_TAXONOMY.md")

    assert "strictly valid `agent:ready`" in agents
    assert "without requiring GitHub Project Status" in agents
    assert "Work only from GitHub Issues labeled `agent:ready`" in issue_to_code
    assert "Project Status is not a pickup precondition" in issue_to_code
    assert "Project Status is not a dispatch precondition" in deliver_issue_set
    assert "Project Status is not a pickup gate" in dev_workflow
    assert "without requiring Project Status" in labels
    assert "label removal + claimant receipt" in issue_to_code

    canonical_pickup_contracts = (
        agents,
        issue_to_code,
        deliver_issue_set,
        dev_workflow,
        _read(".codex/skills/README.md"),
        _read("docs/development/BUILDER_SYSTEM_PROCESS_MAP.md"),
    )
    forbidden_gates = (
        "Issue -> Project -> Agent",
        "both `Status=Ready` and labeled `agent:ready`",
        "`agent:ready` + Status=Ready",
        "Status=Ready qualifies pickup",
    )
    for contract in canonical_pickup_contracts:
        for phrase in forbidden_gates:
            assert phrase not in contract


def test_ready_producers_do_not_require_project_status() -> None:
    producers = (
        _read(".codex/skills/docs-to-issue/SKILL.md"),
        _read(".codex/skills/feature-breakdown/SKILL.md"),
        _read(".codex/skills/learning-to-issue/SKILL.md"),
        _read(".codex/skills/bug-to-issue/SKILL.md"),
        _read(".codex/skills/issue-maintenance-change-control/SKILL.md"),
    )

    for contract in producers:
        assert "Use `agent:ready` only with `Status=Ready`" not in contract
        assert "can label as `agent:ready` with `Status=Ready` only" not in contract
        assert "project" in contract.lower()
        assert "optional" in contract.lower()


def test_builderops_authority_roles_are_explicit() -> None:
    dispatcher = _read("docs/AGENT_ISSUE_DISPATCHER.md")
    architecture = _read("docs/ARCHITECTURE.md")
    process_map = _read("docs/development/BUILDER_SYSTEM_PROCESS_MAP.md")

    for text in (dispatcher, architecture, process_map):
        assert "GitHub Issues / PRs / CI" in text
        assert "Dispatcher SQLite" in text
        assert "external BuilderOps Vault" in text
        assert "Project" in text
        assert "projection" in text
    assert "GitHub Project v2 is the delivery state machine" not in architecture
    assert "Status=Ready qualifies pickup" not in process_map
    assert "labels, Project states, `Verify:` markers" not in process_map
    assert "labels, Project status, skill routing" not in process_map


def test_external_vault_separates_authoritative_leases_from_advisory_claims() -> None:
    contract = _read(
        "docs/BUILDEROPS_MODEL_INQUIRY/EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md"
    )

    assert "shared Markdown artifacts" in contract
    assert "TTL-based advisory claim signals" in contract
    assert "local authoritative dispatcher leases" in contract
    assert "without creating SQLite files or provider credentials" in contract
    assert "exclusive distributed" in contract
