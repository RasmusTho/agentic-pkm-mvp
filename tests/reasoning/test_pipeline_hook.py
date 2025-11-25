from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.agents.pipeline import ingest_and_chunk
from app.reasoning.store import get_reasoning_store, reset_reasoning_store
from app.stores import get_relation_index, reset_store_backends

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def reset_store(monkeypatch: pytest.MonkeyPatch):
    reset_store_backends()
    os.environ.pop("REASONING_ENABLE", None)
    yield
    reset_store_backends()
    os.environ.pop("REASONING_ENABLE", None)
    reset_reasoning_store()


def test_reasoning_inert_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    obj = {"uuid": str(uuid4()), "text": "alpha beta gamma"}
    ingest_and_chunk(obj)
    assert not get_reasoning_store().claims()


def test_reasoning_runs_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REASONING_ENABLE", "1")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("REASONING_PROVIDER", "mock")
    obj = {
        "uuid": "reasoning-sample-1",
        "text": "Alpha memo states that solar storage reduces peak load and cites grid stability data.",
    }
    chunks = ingest_and_chunk(obj)
    assert chunks
    claims = get_reasoning_store().claims()
    assert any("solar storage" in claim.text.lower() for claim in claims)
