from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_memory.recall_retrieval import read_promoted_memories, retrieve_relevant_promoted


def test_recall_retrieval_no_vault_returns_empty_without_cwd_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()

    assert read_promoted_memories() == []
    assert retrieve_relevant_promoted("anything") == []
