from __future__ import annotations

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--faulthandler-timeout",
        action="store",
        type=float,
        dest="faulthandler_timeout",
        default=None,
        help="Alias for faulthandler_timeout (seconds) when faulthandler is enabled.",
    )


def pytest_configure(config) -> None:
    # Provide marker definitions for pytest when pyproject/pytest.ini is ignored.
    markers = {
        "not_pg": "marks tests that do not require Postgres",
        "alpha_llm": "alpha LLM tests (require live providers)",
        "alpha_llm_live": "live alpha LLM tests",
        "eval": "evaluation/deepeval tests",
        "e2e": "end-to-end scenarios",
        "human_uat": "human-need acceptance scenarios",
        "panel_llm_e2e": "panel + LLM e2e tests",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")

    timeout = getattr(config.option, "faulthandler_timeout", None)
    if timeout is not None:
        # Map CLI alias to the ini setting used by pytest's faulthandler plugin.
        config._inicache["faulthandler_timeout"] = timeout


@pytest.fixture(autouse=True)
def _sanitize_external_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure tests are hermetic and do not accidentally read from a user's real vault
    (e.g. iCloud-backed VAULT_ROOT), which can block filesystem opens and hang the suite.

    Any test that needs these variables must set them explicitly via monkeypatch.
    """
    # Prevent accidental reads from a real vault.
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)

    # Deterministic defaults.
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("LLM_EMBED_MODEL", "mock-embed")

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    # Eval tests remain opt-in.
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
