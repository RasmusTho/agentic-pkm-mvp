"""Architecture tests for vault-first pickup with dispatcher fallback."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill() -> str:
    return (REPO_ROOT / ".codex/skills/issue-to-code/SKILL.md").read_text(encoding="utf-8")


def test_skill_declares_vault_first_and_dispatcher_fallback() -> None:
    content = _skill()

    assert "#### Vault-First Integration" in content
    assert "#### Dispatcher Transition Fallback" in content
    assert content.index("#### Vault-First Integration") < content.index(
        "#### Dispatcher Transition Fallback"
    )
    assert "If a matching vault ticket exists, do not also acquire a dispatcher lease." in content


def test_skill_carries_complete_vault_lease_lifecycle() -> None:
    content = _skill()

    for command in (
        "builderops vault validate",
        "builderops vault claim",
        "builderops vault renew",
        "builderops vault release",
    ):
        assert command in content


def test_skill_keeps_dispatcher_commands_as_transition_fallback() -> None:
    content = _skill()

    for command in (
        "dispatcher status",
        "dispatcher next",
        "dispatcher claim",
        "dispatcher heartbeat",
        "dispatcher complete",
    ):
        assert command in content


def test_skill_forbids_project_v2_in_hot_path() -> None:
    content = _skill()

    assert "GitHub Project v2 is not a hot-path dependency" in content
    assert "Never query or mutate it in pickup" in content
