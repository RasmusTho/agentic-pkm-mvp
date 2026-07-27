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


def test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed() -> None:
    skill = _read(".codex/skills/start-model-inquiry/SKILL.md")
    normalized_skill = " ".join(skill.split())

    assert skill.index("## Route Selection") < skill.index("## Single-Flight Launch")
    for identity_contract in (
        "/usr/bin/ssh -G Tailscale_macmini",
        "/usr/bin/id -un",
        "NFSHomeDirectory",
        "require the current `$HOME` to equal it byte-for-byte",
        "`$HOME/.ssh/known_hosts` and `$HOME/.ssh/known_hosts2`",
        "`/usr/bin/ssh-keygen -F`",
        "`/etc/ssh/ssh_host_*_key.pub`",
        "Never read a private host-key file",
        "Use the **proven-local route** only when alias expansion, principal binding, home binding, and the pinned host-key proof all succeed.",
        "Never infer that the caller is local because",
        "Once selected, do not switch routes during the invocation.",
    ):
        assert identity_contract in normalized_skill

    launcher_invocations = [
        line.strip()
        for line in skill.splitlines()
        if "yggdrasil-model-inquiry" in line and "--question-file" in line
    ]
    assert launcher_invocations == [
        "ssh -T Tailscale_macmini '$HOME/.local/bin/yggdrasil-model-inquiry --question-file /tmp/model-inquiry-question.md'",
        '"$HOME/.local/bin/yggdrasil-model-inquiry" --question-file /tmp/model-inquiry-question.md',
    ]

    lock_invocations = [
        line.strip()
        for line in skill.splitlines()
        if "mkdir /tmp/yggdrasil-model-inquiry.lock" in line
    ]
    assert lock_invocations == [
        "ssh -T Tailscale_macmini 'mkdir /tmp/yggdrasil-model-inquiry.lock'",
        "/bin/mkdir /tmp/yggdrasil-model-inquiry.lock",
    ]

    local_release = _section_between(
        skill,
        "Fixed proven-local release procedure:",
        "The configured inquiry host owns",
    )
    assert "*** Delete File: /tmp/model-inquiry-question.md" in local_release
    assert "/bin/rmdir /tmp/yggdrasil-model-inquiry.lock" in local_release
    assert "rm -f" not in local_release

    for local_contract in (
        '/usr/bin/install -m 0600 "$QUESTION_FILE" /tmp/model-inquiry-question.md',
        "*** Delete File: <absolute QUESTION_FILE>",
        "Do not use `rm`, `unlink`, a glob, or a shell cleanup wrapper for this local temporary file.",
        "non-empty stdout whose entire contents parse as exactly one JSON object",
        "contain non-empty string values for `inquiry_id`, `final_state`, `terminal_receipt_id`, and",
        "| Failure after lock acquisition but before step 5 starts | Run the fixed remote release command below; report the original failure and any cleanup failure. | Run the fixed proven-local release procedure below; report the original failure and any cleanup failure. |",
        "| Valid terminal response | Preserve the response, then run the fixed remote release command. | Preserve the response, then run the fixed proven-local release procedure. |",
        "| Ambiguous launcher outcome after step 5 starts | Preserve the remote staging file and lock. | Preserve the local staging file and lock. |",
        "a cleanup failure must not replace or reclassify the captured launcher outcome.",
        "The proven-local route may invoke only the fixed subscription-authenticated host launcher.",
    ):
        assert local_contract in normalized_skill

    for forbidden_bypass in (
        "BUILDEROPS_VAULT_ROOT",
        "BUILDEROPS_INQUIRY_ADAPTERS_JSON",
        "scripts/start_model_inquiry.sh",
        "/etc/ssh/ssh_host_ed25519_key",
        "/etc/ssh/ssh_host_rsa_key",
        "tailscale status --json",
        "/bin/rm -f /tmp/model-inquiry-question.md",
    ):
        assert forbidden_bypass not in skill
