from pathlib import Path
from types import SimpleNamespace

import pytest

from app.instance.context_bound_read import ContextBoundReadRoot
from app.instance.context_settings import (
    IncompatibleBindingSettingsError,
    resolve_context_settings,
)
from app.vault.settings_service import RUNTIME_GATING_SETTINGS
from app.settings.models import RetrievalTuning, SettingsBundle


def _effective(value: bool) -> dict[str, SimpleNamespace]:
    return {key: SimpleNamespace(value=value) for key in RUNTIME_GATING_SETTINGS}


def test_many_binding_request_fails_before_effect_for_incompatible_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No binding order may select a request-wide runtime behavior."""

    roots = (
        ContextBoundReadRoot("a", Path("/vault-a"), 7),
        ContextBoundReadRoot("b", Path("/vault-b"), 7),
    )
    monkeypatch.setattr(
        "app.instance.context_settings.resolve_context_read_roots", lambda *_a, **_kw: roots
    )
    monkeypatch.setattr("app.instance.context_settings.is_vault_root", lambda _root: True)
    monkeypatch.setattr(
        "app.instance.context_settings.VaultManager.validate_vault", lambda _self, root: root
    )

    class Service:
        def resolve(self, root: Path):
            return SimpleNamespace(settings=_effective(root.name == "vault-a"))

    monkeypatch.setattr("app.instance.context_settings.SettingsService", Service)
    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(object(), registry_store=object())  # type: ignore[arg-type]


def test_many_binding_request_rejects_incompatible_retrieval_policy(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    roots = (
        ContextBoundReadRoot("a", tmp_path / "vault-a", 7),
        ContextBoundReadRoot("b", tmp_path / "vault-b", 7),
    )
    roots[0].root.mkdir()
    roots[1].root.mkdir()
    monkeypatch.setattr(
        "app.instance.context_settings.resolve_context_read_roots", lambda *_a, **_kw: roots
    )
    monkeypatch.setattr("app.instance.context_settings.is_vault_root", lambda _root: True)
    monkeypatch.setattr(
        "app.instance.context_settings.VaultManager.validate_vault", lambda _self, root: root
    )
    monkeypatch.setattr(
        "app.instance.context_settings.SettingsService",
        lambda: type("Service", (), {"resolve": lambda _self, _root: type("R", (), {"settings": _effective(True)})()})(),
    )
    monkeypatch.setattr(
        "app.instance.context_settings.compile_all",
        lambda *, vault_root, **_kwargs: SettingsBundle(
            retrieval_tuning=RetrievalTuning(
                retrieve_depth=1 if Path(vault_root).name == "vault-a" else 2
            )
        ),
    )

    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(object(), registry_store=object())  # type: ignore[arg-type]
