from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


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
    section = text.split("15a. **Branch-Truth Gate", maxsplit=1)[1].split(
        "15b. **Branch-Truth Gate", maxsplit=1
    )[0]

    branch_capture = 'EXPECTED_BRANCH="$(git branch --show-current)"'
    worktree_capture = 'EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"'
    preflight = "scripts/agent_workspace_preflight.sh"

    assert branch_capture in section
    assert worktree_capture in section
    assert preflight in section
    assert section.index(branch_capture) < section.index(preflight)
    assert section.index(worktree_capture) < section.index(preflight)
    assert '--expected-branch "$EXPECTED_BRANCH"' in section
    assert '--expected-worktree "$EXPECTED_WORKTREE"' in section
    assert "Do not continue with empty expected values" in section
