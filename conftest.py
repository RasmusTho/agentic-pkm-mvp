from __future__ import annotations

import sys
from pathlib import Path

import pytest

# companion_ui lives at companion-ui/companion-app, outside the rootdir pythonpath,
# and is imported at module level by test trees beyond tests/companion_ui (tests/api,
# tests/uat, tests/tts). It must be importable for every collection target and for
# ini-less CI invocations (`pytest -c /dev/null`), which skip pytest.ini pythonpath
# but still load this conftest.
# See: https://github.com/RasmusTho/agentic-pkm-mvp/issues/3941
_COMPANION_APP_ROOT = Path(__file__).resolve().parent / "companion-ui" / "companion-app"
if str(_COMPANION_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMPANION_APP_ROOT))


def pytest_configure(config) -> None:
    import os

    # Sanitize vault-related environment variables BEFORE test collection to prevent
    # modules from accessing real vault paths during import. This protects against hangs
    # when vault paths are on iCloud sync or other slow filesystems.
    # See: https://github.com/RasmusTho/agentic-pkm-mvp/issues/316
    os.environ.pop("VAULT_ROOT", None)
    os.environ.pop("PANEL_ACTION_WIRING_PATH", None)

    # Provide marker definitions for pytest when pyproject/pytest.ini is ignored.
    markers = {
        "not_pg": "marks tests that do not require Postgres",
        "alpha_llm": "alpha LLM tests (require live providers)",
        "alpha_llm_live": "live alpha LLM tests",
        "eval": "evaluation/deepeval tests",
        "e2e": "end-to-end scenarios",
        "human_uat": "human-need acceptance scenarios",
        "uat_integrated_runtime": "no-mock Integrated Runtime v1 golden-path UAT over the test channel",
        "panel_llm_e2e": "panel + LLM e2e tests",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")

    timeout = getattr(config.option, "faulthandler_timeout", None)
    if timeout is not None:
        # Map CLI alias to the ini setting used by pytest's faulthandler plugin.
        config._inicache["faulthandler_timeout"] = timeout


@pytest.fixture(autouse=True)
def _sanitize_external_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ensure tests are hermetic and do not accidentally read from a user's real vault
    (e.g. iCloud-backed VAULT_ROOT), which can block filesystem opens and hang the suite.

    Any test that needs these variables must set them explicitly via monkeypatch.
    """
    # Prevent accidental reads from a real vault.
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("PANEL_ACTION_WIRING_PATH", raising=False)

    # Deterministic defaults.
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_CHAT_MODEL", "mock-chat")
    monkeypatch.setenv("LLM_EMBED_MODEL", "mock-embed")

    # pg-marked tests must see the environment-provided DATABASE_URL (CI
    # service container, local scratch DB); stripping it here made every pg
    # test in CI skip or fail (#2818). There is no fallback to strip through
    # any more — the pg lane is explicit-or-nothing (#4573). Same guard pattern
    # as tests/conftest.py::force_memory_store_for_non_pg.
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)

    # Eval tests remain opt-in.
    monkeypatch.setenv("EVAL_LLM_MODE", "skip")
