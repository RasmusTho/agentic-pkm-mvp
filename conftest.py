from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _sanitize_external_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure tests are hermetic and do not accidentally read from a user's real vault
    (e.g. iCloud-backed VAULT_ROOT), which can block filesystem opens and hang the suite.

    Any test that needs these variables must set them explicitly via monkeypatch.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("LLM_EMBED_MODEL", "mock-embed")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
