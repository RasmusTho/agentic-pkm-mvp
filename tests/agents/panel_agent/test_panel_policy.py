from __future__ import annotations

from app.agents.panel_agent.policy import (
    get_auto_run_mode,
    watcher_may_run_panel,
    watcher_panel_candidate,
)


def _sample_markdown_with_panel() -> str:
    return """%% AI:Start %%\n## AI-instruction\n- [ ] Run something\n%% AI:End %%\n"""


def test_policy_defaults_to_manual() -> None:
    frontmatter = {}
    assert get_auto_run_mode(frontmatter) == "manual"
    assert watcher_may_run_panel(frontmatter) is True


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
    assert watcher_may_run_panel(fm) is True


def test_watcher_panel_candidate_flags_ai_fence_notes() -> None:
    frontmatter: dict[str, object] = {}
    markdown = _sample_markdown_with_panel()
    assert watcher_panel_candidate(frontmatter, markdown)


def test_watcher_panel_candidate_respects_never_opt_out() -> None:
    frontmatter = {"ai_panel_auto_run": "never"}
    markdown = _sample_markdown_with_panel()
    assert watcher_panel_candidate(frontmatter, markdown) is False


def test_watcher_panel_candidate_needs_panel_fence() -> None:
    frontmatter: dict[str, object] = {}
    markdown = "# No AI fence here\nJust text"
    assert watcher_panel_candidate(frontmatter, markdown) is False
