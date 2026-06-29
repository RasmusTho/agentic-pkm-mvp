"""Governance contract for Codex specialist subagent role adapters.

These adapters are Builder System execution roles, not workflow contracts. The tests
enforce that they exist, parse, declare bounded settings, and route work into the
canonical `.codex/skills/**` rather than duplicating skill contract text. See
`docs/development/BUILDER_SUBAGENT_ROLES.md` and the artifact map in
`docs/architecture/SBS_OPERATING_MODEL.md`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".codex" / "agents"
CONFIG_PATH = REPO_ROOT / ".codex" / "config.toml"
ROLE_DOC = "docs/development/BUILDER_SUBAGENT_ROLES.md"

# filename -> (expected name field, expected canonical skill path fragment)
REQUIRED_AGENT_FILES = {
    "issue-set-coordinator.toml": ("issue_set_coordinator", ".codex/skills/deliver-issue-set/SKILL.md"),
    "slice-implementer.toml": ("slice_implementer", ".codex/skills/issue-to-code/SKILL.md"),
    "backlog-contract-maintainer.toml": (
        "backlog_contract_maintainer",
        ".codex/skills/issue-maintenance-change-control/SKILL.md",
    ),
    "verification-closer.toml": ("verification_closer", ".codex/skills/verification-and-closure/SKILL.md"),
}

VALID_REASONING = {"minimal", "low", "medium", "high", "xhigh"}
VALID_SANDBOX = {"read-only", "workspace-write"}


def _load_agent(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_required_codex_agents_exist_and_parse() -> None:
    for filename, (expected_name, _skill) in REQUIRED_AGENT_FILES.items():
        path = AGENTS_DIR / filename
        assert path.exists(), filename
        data = _load_agent(path)
        assert data["name"] == expected_name
        assert data["description"]
        assert data["developer_instructions"].strip()


def test_codex_agents_are_execution_roles_not_skill_replacements() -> None:
    for filename, (_name, skill) in REQUIRED_AGENT_FILES.items():
        data = _load_agent(AGENTS_DIR / filename)
        instructions = data["developer_instructions"]
        assert "AGENTS.md" in instructions
        assert "BUILDER_SUBAGENT_ROLES.md" in instructions
        assert "canonical workflow contract" in instructions
        assert "subagent_handoff_receipt" in instructions
        # Adapter must explicitly load its canonical skill (Codex does not auto-discover
        # this repo's .codex/skills/**), not inline the contract.
        assert skill in instructions, filename


def test_codex_agent_model_reasoning_and_sandbox_are_bounded() -> None:
    for path in sorted(AGENTS_DIR.glob("*.toml")):
        data = _load_agent(path)
        assert data.get("model"), path.name
        assert data.get("model_reasoning_effort") in VALID_REASONING, path.name
        sandbox = data.get("sandbox_mode")
        assert sandbox in VALID_SANDBOX, path.name
        assert sandbox != "danger-full-access", path.name


def test_codex_subagent_config_limits_fanout() -> None:
    data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["agents"]["max_threads"] == 3
    assert data["agents"]["max_depth"] == 1
