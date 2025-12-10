from __future__ import annotations

from app.agents.panel_agent.policy import get_auto_run_mode, watcher_may_run_panel


def test_policy_defaults_to_manual() -> None:
    frontmatter = {}
    assert get_auto_run_mode(frontmatter) == "manual"
    assert watcher_may_run_panel(frontmatter) is False


def test_policy_allows_watcher() -> None:
    fm = {"ai_panel_auto_run": "watcher"}
    assert get_auto_run_mode(fm) == "watcher"
    assert watcher_may_run_panel(fm) is True


def test_policy_never_blocks_watcher() -> None:
    fm = {"ai_panel_auto_run": "never"}
    assert get_auto_run_mode(fm) == "never"
    assert watcher_may_run_panel(fm) is False


def test_policy_accepts_nested_config() -> None:
    fm = {"ai_panel": {"auto_run": "watcher"}}
    assert get_auto_run_mode(fm) == "watcher"
    assert watcher_may_run_panel(fm) is True


def test_policy_handles_unknown_value() -> None:
    fm = {"ai_panel_auto_run": "unexpected"}
    assert get_auto_run_mode(fm) == "manual"
    assert watcher_may_run_panel(fm) is False
