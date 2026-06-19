"""Regression: the default-on CRE tick must work on an initialize_vault vault (#2183).

Vaults created by ``VaultManager.initialize_vault`` (the same path
``/api/companion/vault/initialize`` drives) previously wrote only
``settings/*.md`` — no ``vault.layout.md`` and no ``system-settings.yaml``. The
deterministic CRE path resolver ``get_vault_system_dir_rel`` then raised, so the
relevance evaluator failed in ``__init__`` and the tick materialized zero
moments on a freshly initialized vault.

These tests exercise the production path
(``VaultManager.initialize_vault`` -> ``run_relevance_tick``) with the
layout-folder env defaults cleared, so they reproduce the true init-only state
the autouse ``default_vault_layout_env`` fixture would otherwise mask. They fail
against pre-fix code (resolver raises) and pass after the CRE path resolves the
system dir gracefully:

- The CRE evaluator and materialization resolve the system dir gracefully
  (app/relevance/evaluator.py, app/relevance/materialization.py).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.relevance.evaluator import DeterministicRelevanceEvaluator
from app.relevance.materialization import materialize_moment
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.paths import (
    get_vault_system_dir_rel,
    resolve_vault_system_dir_rel_or_default,
)
from app.watcher.relevance_tick import run_relevance_tick

TODAY = date(2026, 6, 13)

# Layout-folder env vars that the autouse ``default_vault_layout_env`` fixture
# injects. Clearing them is what makes these tests exercise the real init-only
# vault state (no env override masking the missing layout note).
_LAYOUT_ENV_VARS = (
    "VAULT_SYSTEM_DIR_REL",
    "VAULT_INBOX_DIR_REL",
    "VAULT_DESK_DIR_REL",
    "VAULT_RUNTIME_DIR_REL",
    "VAULT_ROOT",
    "VAULT_LAYOUT_NOTE_REL",
)


@pytest.fixture
def clear_layout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LAYOUT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _seed_vault_content(vault: Path) -> None:
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")
    note = vault / "Projects" / "CRE.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: cre-uuid\n---\n\n# CRE\n\n- [ ] finish the scarcity gate\n",
        encoding="utf-8",
    )


def _initialized_vault(tmp_path: Path) -> tuple[VaultManager, Path, object]:
    vault = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))
    context = manager.initialize_vault(vault).context
    assert context.status == "selected"
    return manager, vault, context


def test_initialize_vault_resolver_degrades_to_default(
    tmp_path: Path, clear_layout_env: None
) -> None:
    """On an init-only vault the CRE path resolves via the graceful default.

    initialize_vault intentionally does not pre-write ``vault.layout.md`` (that
    regressed the capture-scoped seed/UAT layout). Instead the read-side helper
    the CRE evaluator/materialization use, ``resolve_vault_system_dir_rel_or_default``,
    returns the packaged default system folder rather than raising, so the
    default-on relevance tick never crashes on a freshly initialized vault.
    """

    _manager, vault, _context = _initialized_vault(tmp_path)

    # The graceful resolver (used on the production CRE path) returns a usable
    # default system dir even though no layout note / system-settings.yaml exists.
    system_dir = resolve_vault_system_dir_rel_or_default(vault)
    assert system_dir


def test_relevance_tick_materializes_on_initialized_vault(
    tmp_path: Path, clear_layout_env: None
) -> None:
    """The production tick materializes a moment on a freshly initialized vault.

    Pre-fix this raised in ``DeterministicRelevanceEvaluator.__init__`` (resolver
    failure) and materialized nothing.
    """

    _manager, vault, context = _initialized_vault(tmp_path)
    _seed_vault_content(vault)

    summary = run_relevance_tick(
        vault,
        vault_context=context,
        outbox_path=tmp_path / "moment_receipts.jsonl",
        reachout_outbox_path=tmp_path / "reachout.jsonl",
    )

    assert summary["materialized"] >= 1, summary
    system_dir = resolve_vault_system_dir_rel_or_default(vault)
    moments = list((vault / system_dir / "moments").glob("*.md"))
    assert moments, "the tick must write a moment artifact under the resolved system dir"


def test_evaluator_degrades_on_legacy_init_only_vault(
    tmp_path: Path, clear_layout_env: None
) -> None:
    """A pre-fix vault on disk (settings/*.md only, no layout note) still ticks.

    Simulates a settings-only vault with no layout note: the strict resolver
    raises, but the CRE evaluator must degrade gracefully in ``__init__``
    instead of crashing the default-on tick.
    """

    vault = tmp_path / "legacy"
    (vault / "settings").mkdir(parents=True, exist_ok=True)
    (vault / "settings" / "paths.md").write_text(
        "---\nschema: design-handoff.paths.v1\n---\n", encoding="utf-8"
    )

    # The strict resolver still raises on this hand-built legacy vault...
    with pytest.raises((ValueError, FileNotFoundError)):
        get_vault_system_dir_rel(vault)

    # ...but the graceful resolver and the evaluator do not.
    fallback = resolve_vault_system_dir_rel_or_default(vault)
    assert fallback
    evaluator = DeterministicRelevanceEvaluator(vault)
    assert evaluator._system_dir == fallback
    # No content seeded -> no moments, but crucially no exception.
    assert evaluator.evaluate() == []


def test_materialize_moment_degrades_on_legacy_init_only_vault(
    tmp_path: Path, clear_layout_env: None
) -> None:
    """materialize_moment resolves the system dir gracefully on a legacy vault."""

    vault = tmp_path / "legacy"
    (vault / "settings").mkdir(parents=True, exist_ok=True)
    (vault / "settings" / "paths.md").write_text(
        "---\nschema: design-handoff.paths.v1\n---\n", encoding="utf-8"
    )
    daily = vault / "Daily" / f"{TODAY.isoformat()}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("---\nuuid: daily-uuid\n---\n\n# Today\n", encoding="utf-8")

    evaluator = DeterministicRelevanceEvaluator(vault, today=TODAY)
    moments = evaluator.evaluate()
    assert moments, "seeded daily note should produce at least one moment"

    from app.vault.manager import VaultContext

    context = VaultContext(
        status="selected",
        active_vault_path=str(vault),
        settings_path=str(vault / "settings"),
    )
    result = materialize_moment(
        moments[0],
        vault_context=context,
        outbox_path=tmp_path / "moment_receipts.jsonl",
    )
    assert result.status == "materialized"
    assert result.artifact_path is not None
    fallback = resolve_vault_system_dir_rel_or_default(vault)
    assert result.artifact_path.startswith(f"{fallback}/moments/")
