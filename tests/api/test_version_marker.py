"""Tests for the runtime version marker (issue #2602, OBSSTAB-05).

These tests inject ``VCS_REF`` via monkeypatch so no Docker build is required.
They verify:
  - GET /version returns the injected git SHA.
  - GET /api/health includes a ``version`` field with the same SHA.
  - The /version value is NOT the static doc-version string from app/version.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.version import SOT_VERSION


_FAKE_SHA = "abc1234deadbeef5678cafe0000111122223333"


@pytest.fixture()
def _inject_vcs_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a known VCS_REF env var so get_runtime_version() returns a deterministic SHA."""
    monkeypatch.setenv("VCS_REF", _FAKE_SHA)
    monkeypatch.setenv("BUILT_AT", "2026-06-28T00:00:00Z")
    # Suppress outbox / heartbeat / knowledge adapter env requirements for a minimal client
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("KNOWLEDGE_PRIMARY_ADAPTER", "fs_vault")
    monkeypatch.setenv("KNOWLEDGE_ALLOW_FALLBACK", "0")
    monkeypatch.setenv("KNOWLEDGE_STRICT_STARTUP", "0")


@pytest.fixture()
def _settings_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.settings.models import SettingsBundle
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


def test_version_matches_git_sha(
    _inject_vcs_ref: None,
    _settings_bundle: None,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /version returns the git SHA matching the built checkout (AC1)."""
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    resp = client.get("/version")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "git_sha" in data, f"Missing 'git_sha' key: {data}"
    assert data["git_sha"] == _FAKE_SHA, (
        f"Expected git_sha={_FAKE_SHA!r}, got {data['git_sha']!r}"
    )


def test_api_health_includes_version(
    _inject_vcs_ref: None,
    _settings_bundle: None,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/health has a `version` field with the same SHA as /version (AC2)."""
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("WORKER_ENABLE", "0")
    monkeypatch.delenv("WATCHER_HEARTBEAT_PATH", raising=False)

    client = TestClient(app)
    health_resp = client.get("/api/health")
    assert health_resp.status_code == 200, f"Expected 200, got {health_resp.status_code}: {health_resp.text}"
    health_data = health_resp.json()
    assert "version" in health_data, f"'version' key missing from /api/health response: {list(health_data.keys())}"
    assert health_data["version"] == _FAKE_SHA, (
        f"Expected version={_FAKE_SHA!r}, got {health_data['version']!r}"
    )


def test_version_not_static_doc_version(
    _inject_vcs_ref: None,
    _settings_bundle: None,
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /version value is NOT the static doc-version string from app/version.py:4 (AC3)."""
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    client = TestClient(app)
    resp = client.get("/version")
    assert resp.status_code == 200
    data = resp.json()
    git_sha = data.get("git_sha", "")
    assert git_sha != SOT_VERSION, (
        f"git_sha must not equal SOT_VERSION={SOT_VERSION!r}; "
        f"the /version surface returns runtime identity, not the doc-version string"
    )
