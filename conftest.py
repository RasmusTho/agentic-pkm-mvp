from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")


def pytest_configure(config) -> None:
    # Provide marker definitions for pytest when pyproject/pytest.ini is ignored.
    markers = {
        "not_pg": "marks tests that do not require Postgres",
        "alpha_llm": "alpha LLM tests (require live providers)",
        "alpha_llm_live": "live alpha LLM tests",
        "eval": "evaluation/deepeval tests",
        "e2e": "end-to-end scenarios",
        "panel_llm_e2e": "panel + LLM e2e tests",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")


def pytest_sessionstart(session):
    os.environ.setdefault("STORE_BACKEND", "memory")
