from __future__ import annotations

import importlib

import pytest

import app.settings

pytestmark = pytest.mark.not_pg


def test_invalid_debug_env_is_normalized_for_settings_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG", "release")
    reloaded = importlib.reload(app.settings)
    try:
        assert reloaded.settings.debug is False
    finally:
        monkeypatch.delenv("DEBUG", raising=False)
        importlib.reload(app.settings)
