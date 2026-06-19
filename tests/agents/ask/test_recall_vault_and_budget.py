"""ASK recall vault resolution + context-budget regressions (#2186).

Two residuals from the 2026-06-18 terminal review-thread audit (#2148):

1. ``_active_recall_vault_root`` (app/agents/ask/graph.py) read only the live
   ``VaultManager.context``. After an API restart the manager boots with an
   empty no-vault context; the persisted last-active vault is materialized only
   on demand. So ASK recall silently fell back to ``VAULT_ROOT`` (or ``None``)
   instead of the vault the rest of the runtime uses. Fix: lazily call
   ``load_last_active()`` before the env fallback.

2. ``build_ask_context`` (app/agents/ask/utils.py) counted only body/source text
   against ``max_context_chars``; the framing lines ([SOURCE n] / Question / …)
   were uncounted, so a note that consumed the full budget overflowed by the
   framing bytes (16082 vs 16000 reproduced). Fix: cap the assembled string.

Both tests assert on the production call path.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.ask import graph as ask_graph
from app.agents.ask.utils import build_ask_context
from app.settings.models import AskSettings
from app.vault.manager import VaultContext, no_vault_context


# --------------------------------------------------------------------------- #
# AC1: lazy-load the persisted active vault before ASK recall
# --------------------------------------------------------------------------- #


class _RestartedVaultManager:
    """Mirrors a freshly-restarted manager: empty context, persisted vault."""

    def __init__(self, persisted: VaultContext) -> None:
        self._persisted = persisted
        # A just-rebooted API has not materialized the persisted vault yet.
        self.context = no_vault_context()
        self.load_last_active_calls = 0

    def load_last_active(self) -> VaultContext:
        self.load_last_active_calls += 1
        # load_last_active() updates the live context as a side effect, exactly
        # like the real VaultManager.select_vault path it delegates to.
        self.context = self._persisted
        return self._persisted


def _selected(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-persisted",
        active_vault_name="Persisted Vault",
        active_vault_path=str(root),
    )


def test_recall_vault_lazily_loads_persisted_vault_after_restart(tmp_path: Path, monkeypatch) -> None:
    """After a restart, recall resolves the persisted vault, not VAULT_ROOT.

    Fail-before: with only ``manager.context`` consulted, the empty no-vault
    context falls through to the ``VAULT_ROOT`` env fallback. Pass-after: the
    persisted vault is lazily loaded and wins over the env fallback.
    """
    persisted_root = tmp_path / "persisted-vault"
    env_root = tmp_path / "env-vault"
    persisted_root.mkdir()
    env_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(env_root))

    manager = _RestartedVaultManager(_selected(persisted_root))
    monkeypatch.setattr(ask_graph, "get_vault_manager", lambda: manager)

    resolved = ask_graph._active_recall_vault_root()

    assert manager.load_last_active_calls == 1
    assert resolved == persisted_root.resolve()
    assert resolved != env_root.resolve()


def test_recall_vault_does_not_reload_when_already_selected(tmp_path: Path, monkeypatch) -> None:
    """When a vault is already selected, recall must not re-trigger a load."""
    selected_root = tmp_path / "live-vault"
    selected_root.mkdir()

    class _LiveManager:
        context = _selected(selected_root)
        load_last_active_calls = 0

        def load_last_active(self) -> VaultContext:  # pragma: no cover - guard
            self.load_last_active_calls += 1
            raise AssertionError("must not reload when a vault is already selected")

    manager = _LiveManager()
    monkeypatch.setattr(ask_graph, "get_vault_manager", lambda: manager)

    resolved = ask_graph._active_recall_vault_root()

    assert resolved == selected_root.resolve()
    assert manager.load_last_active_calls == 0


def test_recall_vault_falls_back_to_env_when_no_persisted_vault(tmp_path: Path, monkeypatch) -> None:
    """No selected and no persisted vault -> env fallback still applies."""
    env_root = tmp_path / "env-vault"
    env_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(env_root))

    class _NoVaultManager:
        context = no_vault_context()

        def load_last_active(self) -> VaultContext:
            # Nothing persisted: stays in the no-vault picker state.
            return no_vault_context()

    monkeypatch.setattr(ask_graph, "get_vault_manager", lambda: _NoVaultManager())

    resolved = ask_graph._active_recall_vault_root()

    assert resolved == env_root.resolve()


# --------------------------------------------------------------------------- #
# AC2: enforce the context budget after using full bodies
# --------------------------------------------------------------------------- #


def _long_hit(body: str) -> dict[str, object]:
    return {
        "id": "budget-1",
        "doc_id": "budget-1",
        "text": body,
        "snippet": body[:300],
        "source_ref": "vault/long-note.md",
        "payload": {"title": "Long Note", "origin": "vault"},
    }


def test_build_ask_context_respects_budget_including_framing() -> None:
    """The assembled prompt never exceeds max_context_chars, framing included.

    Fail-before: the per-block budget bounded only the body, so a body that
    consumed the full budget produced an assembled string longer than the
    budget by the framing bytes (16082 > 16000 reproduced). Pass-after: the
    final cap keeps the whole prompt within the contract.
    """
    settings = AskSettings()
    budget = settings.max_context_chars
    # A body that fully consumes the per-block budget; the framing lines plus
    # the question are what previously pushed the total over the cap.
    body = "x" * (budget + 500)

    context = build_ask_context("What is the budget?", [_long_hit(body)], settings)

    assert len(context) <= budget


def test_build_ask_context_budget_holds_across_multiple_sources() -> None:
    """The cap holds when several over-budget source hits are assembled."""
    settings = AskSettings()
    budget = settings.max_context_chars
    hits = [_long_hit("s" * budget) for _ in range(3)]

    context = build_ask_context("Why does the budget hold?", hits, settings)

    assert len(context) <= budget


def test_build_ask_context_unbounded_when_budget_disabled() -> None:
    """A zero/disabled budget keeps the existing no-cap behavior unchanged."""
    settings = AskSettings(max_context_chars=0)
    body = "y" * 50_000

    context = build_ask_context("No budget?", [_long_hit(body)], settings)

    assert body in context
