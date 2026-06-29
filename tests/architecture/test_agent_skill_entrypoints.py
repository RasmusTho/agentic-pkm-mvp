from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _section_between(text: str, start: str, end: str) -> str:
    return text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def _canonical_branch_truth_branch_capture() -> str:
    text = _read(".codex/skills/_shared/BRANCH_TRUTH_GATE.md")
    procedure = _section_between(text, "## Procedure", "## Fallback")
    capture_block = procedure.split("```bash", maxsplit=1)[1].split("```", maxsplit=1)[0]
    lines = [line.strip() for line in capture_block.splitlines()]

    branch_capture = next(line for line in lines if line.startswith("EXPECTED_BRANCH="))
    return branch_capture


def test_canonical_agents_entrypoint_routes_to_repo_skill_index() -> None:
    text = _read("AGENTS.md")
    assert ".codex/skills/README.md" in text
    assert ".codex/skills/issue-to-code/SKILL.md" in text
    assert ".codex/skills/deliver-issue-set/SKILL.md" in text
    assert "In Progress" in text
    assert "remove `agent:ready`" in text


def test_compatibility_entrypoints_route_to_skill_index() -> None:
    codex_text = _read(".codex/AGENTS.md")
    claude_text = _read("CLAUDE.md")

    assert ".codex/skills/README.md" in codex_text
    assert ".codex/skills/issue-to-code/SKILL.md" in codex_text
    assert ".codex/skills/README.md" in claude_text
    assert ".codex/skills/issue-to-code/SKILL.md" in claude_text


def test_repo_skill_index_describes_connected_workflow_paths() -> None:
    text = _read(".codex/skills/README.md")
    for name in (
        "agentic-pkm",
        "issue-to-code",
        "deliver-issue-set",
        "publish-pr",
        "issue-maintenance-change-control",
        "pr-integration",
        "verification-and-closure",
    ):
        assert name in text
    assert "agentic-pkm -> issue-to-code -> publish-pr -> pr-integration -> verification-and-closure" in text


def test_issue_to_code_preflight_captures_expected_branch_and_worktree() -> None:
    text = _read(".codex/skills/issue-to-code/SKILL.md")
    section = _section_between(
        text,
        "15a. **Branch-Truth Gate",
        "15b. **Branch-Truth Gate",
    )

    branch_capture = _canonical_branch_truth_branch_capture()
    worktree_capture = 'EXPECTED_WORKTREE="<absolute-worktree-path>"'
    preflight = "scripts/agent_workspace_preflight.sh"

    assert branch_capture in section
    assert worktree_capture in section
    assert 'EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"' not in section
    assert preflight in section
    assert section.index(branch_capture) < section.index(preflight)
    assert section.index(worktree_capture) < section.index(preflight)
    assert '--expected-branch "$EXPECTED_BRANCH"' in section
    assert '--expected-worktree "$EXPECTED_WORKTREE"' in section
    assert "|| exit 1" in section
    assert "Do not continue with empty expected values" in section


def test_subagent_role_governance_is_discoverable() -> None:
    agents_text = _read("AGENTS.md")
    claude_text = _read("CLAUDE.md")
    role_doc = "docs/development/BUILDER_SUBAGENT_ROLES.md"

    assert role_doc in agents_text
    assert role_doc in claude_text
    assert ".codex/agents" in agents_text
    assert "skills remain" in agents_text.lower()
