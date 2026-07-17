from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.settings import compiler
from app.settings import runtime as settings_runtime
from app.settings.ingestion import STATE_OK, ingest_settings, reset_settings_ingestion_state
from app.settings.runtime import get_settings_bundle
from app.vault.manager import VaultManager


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATED_RUNTIME_UAT") != "1",
    reason="integrated runtime UAT is opt-in",
)


def test_settings_canonical_root_reaches_runtime_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    VaultManager().initialize_vault(vault, remember=False)
    (vault / "settings" / "global.md").write_text(
        "# Global\n\n```yaml settings\nlog_level: DEBUG\n```\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    monkeypatch.setattr(settings_runtime, "RUNTIME", runtime_dir)
    reset_settings_ingestion_state()

    state = ingest_settings(reason="integrated_uat", vault_root=vault)

    assert state.state == STATE_OK
    assert state.source == "vault"
    assert get_settings_bundle().global_.log_level == "DEBUG"
