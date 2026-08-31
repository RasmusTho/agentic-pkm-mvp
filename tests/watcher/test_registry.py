from pathlib import Path

from app.watcher import registry


def test_settings_rebind_rejects_traversal_error_before_acknowledgement(monkeypatch) -> None:
    def broken_walk(*_args, **_kwargs):
        if False:
            yield Path("unreachable")
        raise OSError("injected traversal failure")

    summary: dict[str, object] = {}
    monkeypatch.setattr(registry, "iter_vault_markdown_files", broken_walk)

    assert list(
        registry._scan_markdown_many(Path("/vault"), [Path("/vault")], "**/*.md", summary=summary)
    ) == []
    assert summary["scan_complete"] is False
    assert summary["scan_incomplete_reason"] == "traversal"
