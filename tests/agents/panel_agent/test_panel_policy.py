from __future__ import annotations

from pathlib import Path

from app.agents.panel_agent.policy import (
    get_auto_run_mode,
    watcher_may_run_panel,
    watcher_panel_candidate,
    watcher_panel_writeback_allowed,
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


def test_watcher_panel_writeback_uses_authoritative_note_class_mapping(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    for relative_path in (
        Path("Notes/panel.md"),
        Path("Sources/panel.md"),
        Path("Acquired/panel.md"),
    ):
        target = vault / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("Panel\n", encoding="utf-8")

    assert watcher_panel_writeback_allowed("Notes/panel.md", vault_root=vault) is True
    assert watcher_panel_writeback_allowed("Sources/panel.md", vault_root=vault) is False
    assert (
        watcher_panel_writeback_allowed(
            "Acquired/panel.md",
            vault_root=vault,
            sources_root_rel="Acquired",
        )
        is False
    )


def test_watcher_panel_writeback_rejects_same_vault_symlink_alias(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    source = vault / "Sources" / "panel-source.md"
    source.parent.mkdir(parents=True)
    source.write_text("Panel\n", encoding="utf-8")
    alias = vault / "Notes" / "source-alias.md"
    alias.parent.mkdir()
    alias.symlink_to(Path("..") / "Sources" / source.name)

    assert (
        watcher_panel_writeback_allowed(
            alias.relative_to(vault),
            vault_root=vault,
        )
        is False
    )
