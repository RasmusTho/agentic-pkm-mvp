"""
Tests for consistency between companion tracking provenance and index event provenance.

Issue #975: companion created_by_instance and index event instance_provenance.instance_id
must agree for the same ingest run — both resolved from the same settings-bundle source.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.stores import reset_store_backends


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        '---\ninclude_folders:\n  - "."\n---\n\nVault layout.\n',
        encoding="utf-8",
    )


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    # Disable companion cooldown so companion is written immediately in tests
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def test_companion_and_index_event_share_instance_provenance(
    tmp_path: Path, _mock_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    For a single ingest run the companion created_by_instance must equal
    the instance_id that would appear in event provenance metadata — both
    resolved from the same settings-bundle source.

    This verifies that vault_alpha._resolve_instance_id() and
    app.events.schema._instance_provenance() both draw from the same
    runtime identity resolver (get_settings_bundle), ensuring provenance
    is consistent between the companion surface and event metadata.
    """
    bundle = SimpleNamespace(
        instance=SimpleNamespace(id="home", role="master", environment="prod")
    )
    monkeypatch.setattr(
        "app.ingest.vault_alpha.get_settings_bundle", lambda: bundle, raising=False
    )
    monkeypatch.setattr(
        "app.events.schema.get_settings_bundle", lambda: bundle, raising=False
    )

    _write_layout(tmp_path)
    note = tmp_path / "provenance_test.md"
    note.write_text(
        "---\ntitle: Provenance Test Note\n---\n\nBody text for provenance test.",
        encoding="utf-8",
    )

    run_vault_alpha_ingest_paths(
        vault_root=tmp_path,
        paths=[note],
    )

    # Read companion
    companions_dir = tmp_path / "⚙️ System" / "companions"
    written = list(companions_dir.glob("*.md")) if companions_dir.exists() else []
    assert written, "No companion note written"

    from scripts.yaml_roundtrip import load_frontmatter
    fm, _ = load_frontmatter(written[0].read_text(encoding="utf-8"))
    assert isinstance(fm, dict)
    companion_instance = fm.get("created_by_instance", "")

    # Resolve what event schema would emit for the same bundle
    from app.events.schema import _instance_provenance
    event_prov = _instance_provenance()
    assert event_prov is not None, "Event schema could not resolve instance provenance"
    event_instance_id = event_prov["instance_id"]

    assert companion_instance == event_instance_id, (
        f"companion created_by_instance={companion_instance!r} does not match "
        f"event provenance instance_id={event_instance_id!r}; "
        "both must draw from the same settings-bundle resolver"
    )
