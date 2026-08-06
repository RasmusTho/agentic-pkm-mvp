from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_read_scope_mentions_unit_filter_and_pr_docs_guard() -> None:
    contract = (REPO_ROOT / ".codex/skills/_shared/READ_SCOPE.md").read_text(
        encoding="utf-8"
    )

    assert "`AGENTS.md`, `CLAUDE.md`, `.codex/**`, and `docs/**`" in contract
    assert "Only on governance/docs-only pull requests" in contract
    assert "`scripts/docs_guard.py`" in contract
