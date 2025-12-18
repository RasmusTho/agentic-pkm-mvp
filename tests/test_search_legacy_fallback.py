from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from app.search import service as search_service


class _LegacyVectorIndex:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def upsert(self, *args, **kwargs):
        if "identity" in kwargs:
            raise TypeError("unexpected keyword 'identity'")
        self.calls.append((args, kwargs))
        return None


def test_ingest_object_warns_on_legacy_fallback(monkeypatch, caplog) -> None:
    idx = _LegacyVectorIndex()
    monkeypatch.setenv("VECTOR_INDEX_DISABLE_LEGACY", "0")
    monkeypatch.setattr(search_service, "get_vector_index", lambda *_: idx)
    search_service._LEGACY_FALLBACK_WARNED = False

    caplog.set_level(logging.WARNING)

    search_service.ingest_object(
        object_id=uuid4(),
        kind="note",
        source_ref="tests",
        payload={"text": "legacy"},
        text="legacy",
    )

    assert idx.calls, "Fallback path should upsert without identity"
    assert "Legacy VectorIndex fallback" in caplog.text


def test_ingest_object_raises_when_legacy_disabled(monkeypatch) -> None:
    idx = _LegacyVectorIndex()
    monkeypatch.setenv("VECTOR_INDEX_DISABLE_LEGACY", "1")
    monkeypatch.setattr(search_service, "get_vector_index", lambda *_: idx)
    search_service._LEGACY_FALLBACK_WARNED = False

    with pytest.raises(TypeError):
        search_service.ingest_object(
            object_id=uuid4(),
            kind="note",
            source_ref="tests",
            payload={"text": "legacy"},
            text="legacy",
        )
