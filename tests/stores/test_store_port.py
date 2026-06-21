from __future__ import annotations

import pytest

from app.stores import reset_store_backends, resolve_object_store_port


@pytest.fixture(autouse=True)
def _reset_between_tests():
    reset_store_backends()
    yield
    reset_store_backends()


def test_object_store_port_classifies_rebuildable_store(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")

    binding = resolve_object_store_port()

    assert binding.contract == "StorePort"
    assert binding.owner_subsystem == "PDM"
    assert binding.name == "object_store"
    assert binding.backend == "memory"
    assert binding.classification == "rebuildable"
    assert binding.rebuild_source
    assert hasattr(binding.store, "put")
    assert hasattr(binding.store, "get")


def test_object_store_port_selects_store_from_reported_backend(monkeypatch):
    class FakeStore:
        rebuild_source = "test rebuild source"

    fake_store = FakeStore()
    monkeypatch.setattr("app.stores._resolve_backend", lambda: "pg")
    monkeypatch.setattr("app.stores._pg_instances", lambda: (fake_store, object(), object()))

    binding = resolve_object_store_port()

    assert binding.backend == "pg"
    assert binding.store is fake_store
