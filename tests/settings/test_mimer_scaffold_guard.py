"""Guard-at-seam enforcement for the yggdrasil-init scaffolder (#2877).

``MimerScaffolder.scaffold`` provisions a brand-new Yggdrasil root
(module folders + Mimer layout + @Settings notes) via raw ``mkdir`` and
``write_note_from_absolute`` with no WriteGuard, reached from the production
``yggdrasil-init`` CLI seam (``app/cli/__init__.py::yggdrasil_init``) —
formal-model.md §2.3 T-scaffold / gap #1.

These tests drive the real ``yggdrasil-init`` CLI (not the guard in isolation)
to prove the reconciled stance:

* a guard that denies the ``"yggdrasil.scaffold"`` action blocks the write
  atomically (zero dirs, zero files, non-zero CLI exit);
* the *named bootstrap escape* still lets a genuine pre-vault-selection
  provision through under health-blocked states (``safe_mode``/``unhealthy``);
* the allowed path is byte-for-byte unchanged and idempotent on re-run.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.settings.mimer_scaffolder import SCAFFOLD_ACTION
from app.write_guard import DEFAULT_WRITE_GUARD

pytestmark = pytest.mark.not_pg

MODULES = ("Mimer", "Hugin", "Munin", "Ratatosk", "Brokkr", "Tyr", "Heimdall")


def _all_paths(root: Path) -> set[Path]:
    return set(root.rglob("*")) if root.exists() else set()


def test_blocked_scaffold_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A guard that denies ``yggdrasil.scaffold`` → zero mutation, non-zero exit.

    Exercises the real guard denial (health-blocked state + the scaffold action
    removed from the bootstrap allow-list) through the production CLI, and
    proves ``assert_writes_allowed`` is invoked from the scaffolder seam.
    """
    root = tmp_path / "Yggdrasil"

    # Genuine denial: blocked state AND the scaffold action is NOT on this
    # guard's named bootstrap allow-list, so the escape does not apply.
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "safe_mode", "reason": "test-blocked"}
    )
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "bootstrap_actions", frozenset())

    # Spy proves the seam consults the guard, while still exercising the real
    # allow-list denial logic (the spy delegates to the real bound method).
    seen: list[str] = []
    real_assert = DEFAULT_WRITE_GUARD.assert_writes_allowed

    def spy(action: str) -> None:
        seen.append(action)
        real_assert(action)

    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "assert_writes_allowed", spy)

    runner = CliRunner()
    result = runner.invoke(cli, ["yggdrasil-init", "--root", str(root)])

    # Clean non-zero CLI error, not an uncaught traceback with a partial tree.
    assert result.exit_code != 0
    assert "blocked" in result.output.lower()

    # Guard was consulted from the scaffolder seam with the bootstrap action.
    assert SCAFFOLD_ACTION in seen

    # Atomic block: the assertion precedes all filesystem mutation, so the
    # target root has zero created paths (no root dir, no modules, no files).
    assert not root.exists()
    assert _all_paths(root) == set()


def test_bootstrap_escape_provisions_under_health_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Named bootstrap escape: default guard blocked → full provision succeeds.

    With the *default* guard reporting a health-blocked state, the named escape
    (``"yggdrasil.scaffold"`` ∈ ``DEFAULT_BOOTSTRAP_ACTIONS``) still permits the
    pre-vault-selection provision, so a brand-new vault is fully scaffolded.
    """
    root = tmp_path / "Yggdrasil"

    # Default guard, blocked health state — bootstrap_actions retains the
    # scaffold escape (not cleared), so provisioning must survive the block.
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "unhealthy", "reason": "store down"}
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["yggdrasil-init", "--root", str(root)])

    assert result.exit_code == 0, result.output

    # Full module + Mimer layout provisioned despite the health block.
    for module in MODULES:
        assert (root / module).is_dir(), f"missing module {module}"
    settings_dir = root / "Mimer" / "settings"
    assert (settings_dir / "global.md").is_file()
    assert (settings_dir / "system-settings.md").is_file()
    assert (root / "Mimer" / "⚙️ System" / "vault.layout.md").exists()


def test_scaffold_output_unchanged_when_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allowed path is byte-for-byte unchanged and idempotent on re-run."""
    root = tmp_path / "Yggdrasil"

    # Plain allowed path: healthy state (escape not even needed).
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})

    runner = CliRunner()
    first = runner.invoke(cli, ["yggdrasil-init", "--root", str(root)])
    assert first.exit_code == 0, first.output
    assert "Created:" in first.output

    # Snapshot the provisioned tree, then re-run: the second invocation must
    # create nothing new and leave the tree byte-for-byte identical.
    tree_after_first = _all_paths(root)
    contents_after_first = {
        p: p.read_bytes() for p in sorted(tree_after_first) if p.is_file()
    }

    second = runner.invoke(cli, ["yggdrasil-init", "--root", str(root)])
    assert second.exit_code == 0, second.output
    assert "Created:" not in second.output
    assert "Already existed:" in second.output

    tree_after_second = _all_paths(root)
    contents_after_second = {
        p: p.read_bytes() for p in sorted(tree_after_second) if p.is_file()
    }

    assert tree_after_second == tree_after_first
    assert contents_after_second == contents_after_first
