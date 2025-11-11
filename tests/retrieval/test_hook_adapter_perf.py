from __future__ import annotations

import importlib
import random
import string
import time

import pytest

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def clear_rerank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RERANK_ENABLE", "RERANK_PROVIDER", "RERANK_TOP_K"):
        monkeypatch.delenv(key, raising=False)


def randt(n: int) -> str:
    alphabet = string.ascii_lowercase + " "
    return "".join(random.choice(alphabet) for _ in range(n))


def test_perf_no_quadratic_blowup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RERANK_ENABLE", "1")
    monkeypatch.setenv("RERANK_PROVIDER", "mock_ce")
    mod = importlib.import_module("app.retrieval.hook_adapter")
    importlib.reload(mod)
    items = [{"id": str(i), "text": randt(80)} for i in range(1000)]
    t0 = time.time()
    out = mod.maybe_rerank("alpha beta gamma", items)
    dt = time.time() - t0
    assert len(out) == len(items)
    assert dt < 0.5
