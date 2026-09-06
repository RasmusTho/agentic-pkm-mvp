from pathlib import Path
import os

import pytest

from app.instance._storage_boundary import RegistryError
from app.watcher import registry
from app.watcher.settings_rebind import load_settings_rebind_watcher_receipt
from tests.integration.test_watcher_cross_process_rebind import (
    _commit,
    _fixture,
    _revision_receipt_path,
)


@pytest.mark.parametrize("phase", ["prepared", "drained"])
def test_settings_rebind_rejects_traversal_error_before_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str,
) -> None:
    runtime, vault_a, _vault_b, config_path = _fixture(tmp_path, monkeypatch)
    if phase == "drained":
        registry.run_registry_once(config_path)
        _commit(runtime)
        registry.run_registry_once(config_path)
        assert load_settings_rebind_watcher_receipt(_revision_receipt_path(tmp_path, 1)).stage == "drained"

    blocked = vault_a / "unreadable"
    blocked.mkdir()
    (blocked / "hidden.md").write_text("must be scanned\n", encoding="utf-8")
    (vault_a / "healthy.md").write_text("healthy sibling\n", encoding="utf-8")
    iterdir = Path.iterdir

    def unavailable_iterdir(path):
        if Path(path) == blocked:
            raise PermissionError("injected subtree traversal failure")
        return iterdir(path)

    with monkeypatch.context() as failure:
        failure.setattr(Path, "iterdir", unavailable_iterdir)
        with pytest.raises(RegistryError, match="settings rebind watcher scan was incomplete"):
            registry.run_registry_once(config_path)

    receipt_path = _revision_receipt_path(tmp_path, 1)
    if phase == "prepared":
        assert runtime.open_settings_rebind_store().read().phase == "prepared"
        assert not receipt_path.exists()
    else:
        assert load_settings_rebind_watcher_receipt(receipt_path).stage == "drained"

    # A retry traverses the formerly unavailable subtree before acknowledging.
    registry.run_registry_once(config_path)
    receipt = load_settings_rebind_watcher_receipt(receipt_path)
    assert receipt.stage == ("acknowledged" if phase == "prepared" else "completed")
    assert "unreadable/hidden.md" in {item.relative_path for item in receipt.buffer}


def test_vault_enumerator_propagates_traversal_failure_to_scan_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, vault_a, _vault_b, _config = _fixture(tmp_path, monkeypatch)
    blocked = vault_a / "unreadable"
    blocked.mkdir()
    (vault_a / "healthy.md").write_text("healthy sibling\n", encoding="utf-8")
    scandir = os.scandir

    def unavailable_scandir(path):
        if Path(path) == blocked:
            raise PermissionError("injected subtree traversal failure")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", unavailable_scandir)
    summary: dict[str, object] = {}
    observed = list(registry._scan_markdown_many(vault_a, [vault_a], "*.md,**/*.md", summary=summary))
    assert any(rel == Path("healthy.md") for rel, _mtime, _path in observed)
    assert summary["scan_complete"] is False
    assert summary["scan_incomplete_reason"] == "traversal"
