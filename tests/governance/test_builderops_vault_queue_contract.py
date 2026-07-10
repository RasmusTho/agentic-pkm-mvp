from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_agents_policy_forbids_graphql_in_builder_hot_path() -> None:
    agents = _read("AGENTS.md")

    assert "GraphQL is forbidden in the Builder System hot path" in agents
    assert "do not use `gh api graphql`, `gh project`" in agents


def test_builderops_vault_queue_declares_file_contract_as_api() -> None:
    doc = _read("docs/development/BUILDER_OPS_VAULT_QUEUE.md")

    assert "The vault file contract is the API" in doc
    assert "Signboard, Obsidian, Plane, or a future Kvasir view are replaceable UIs" in doc
    assert "GitHub Project v2 is deprecated for hot-path automation" in doc


def test_dispatcher_doc_marks_dispatcher_as_transition_fallback() -> None:
    doc = _read("docs/AGENT_ISSUE_DISPATCHER.md")

    assert "transition/fallback" in doc
    assert "no longer the long-term" in doc
    assert "The dispatcher SQLite store is the Builder System control plane" not in doc


def test_delivery_skills_use_vault_first_without_project_hot_path() -> None:
    issue_to_code = _read(".codex/skills/issue-to-code/SKILL.md")
    deliver_set = _read(".codex/skills/deliver-issue-set/SKILL.md")
    closure = _read(".codex/skills/verification-and-closure/SKILL.md")

    assert "#### Vault-First Integration" in issue_to_code
    assert "builderops vault renew" in issue_to_code
    assert "do not also acquire a dispatcher lease" in issue_to_code
    assert "matching vault ticket in `Ready`" in deliver_set
    assert "Project v2 is an optional cold-path" in deliver_set
    assert "move the vault ticket to `Done`" in closure
    assert "do not issue Project GraphQL reads/writes from the closure hot path" in closure
