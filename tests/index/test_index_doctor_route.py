from __future__ import annotations

from app.index.doctor import diagnose_index


def test_index_doctor_expected_identity_uses_router(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()
    expected = result.get("expected_identity") or {}

    assert expected.get("provider") == "mock"
    assert expected.get("model") == "mock-embedding"
    assert expected.get("dim") == 12


def test_index_doctor_reports_rebuild_fields(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()

    assert "rebuild_required" in result
    assert "compatible_identity" in result
    assert "empty_index" in result
