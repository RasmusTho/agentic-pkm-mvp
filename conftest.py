from __future__ import annotations

import os

os.environ.setdefault("LLM_PROVIDER", "mock")


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
        "panel_llm_e2e": "panel + LLM e2e tests",
    }
    for name, desc in markers.items():
        config.addinivalue_line("markers", f"{name}: {desc}")

    timeout = getattr(config.option, "faulthandler_timeout", None)
    if timeout is not None:
        # Map CLI alias to the ini setting used by pytest's faulthandler plugin.
        config._inicache["faulthandler_timeout"] = timeout


def pytest_sessionstart(session):
    os.environ.setdefault("STORE_BACKEND", "memory")
